# /data-organization Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a researcher-facing `/data-organization` guide page explaining where new cryoET data goes on the Janelia file share so the scanner ingests it, with annotated file trees and downloadable starter templates.

**Architecture:** A static TanStack Start route renders four sections built from a reusable `FileTree` component (MUI-x `SimpleTreeView`). Starter templates are zipped deterministically from the canonical `templates/` dirs into `frontend/public/templates/` by a Python script (beside `sync_templates.py`), served as static downloads; a drift test byte-compares the committed zips against a fresh build.

**Tech Stack:** React 19, TanStack Router/Start, MUI v6, `@mui/x-tree-view@^7`, Vitest; Python 3.11 + pytest (pixi `test` env) for the zip generator/drift guard.

## Global Constraints

- Frontend is **MUI v6** — the tree-view dependency MUST be `@mui/x-tree-view@^7` (v9 requires MUI v7/v9). Copy this floor verbatim.
- The canonical templates under `templates/` and `src/schema/schema.py` are the source of truth — **do not** modify them in this feature.
- Deterministic zips use `ZIP_STORED` (no compression) so byte-comparison is stable across environments (no zlib-version dependency). Templates are tiny; compression is unnecessary.
- Run Python tests with the pixi `test` env binary: `.pixi/envs/test/bin/python -m pytest …` (pixi run shebangs are broken in this workspace).
- All work happens in the `add-data-organization-page` worktree at `/workspace/.worktrees/data-org`.
- `/author` tab links use search params: `{ tab: 'sample' | 'acquisition' | 'md_run' }`.

---

### Task 1: Add `@mui/x-tree-view@^7` to the frontend; drop the stray root pin

**Files:**
- Modify: `frontend/package.json`, `frontend/package-lock.json` (via npm)
- Modify/Delete: `package.json` (root — remove stray `@mui/x-tree-view` pin)

**Interfaces:**
- Produces: `@mui/x-tree-view` importable in `frontend/src` (`SimpleTreeView`, `TreeItem`).

- [ ] **Step 1: Install the correct version in the frontend**

Run:
```bash
cd /workspace/.worktrees/data-org/frontend && npm install @mui/x-tree-view@^7
```
Expected: installs cleanly (no `ERESOLVE`); `frontend/package.json` gains `"@mui/x-tree-view": "^7.x"` under dependencies.

- [ ] **Step 2: Verify it resolved and imports**

Run:
```bash
cd /workspace/.worktrees/data-org/frontend && node -e "require.resolve('@mui/x-tree-view/SimpleTreeView'); console.log('ok')"
```
Expected: prints `ok`.

- [ ] **Step 3: Remove the stray root pin**

The root `/workspace/.worktrees/data-org/package.json` contains only `{ "dependencies": { "@mui/x-tree-view": "^9.9.0" } }` — a wrong pin unused by the frontend build. First confirm nothing references the root manifest:
```bash
cd /workspace/.worktrees/data-org && grep -rn "x-tree-view" --include=*.json --include=*.yml --include=*.yaml --include=Dockerfile* . | grep -v node_modules | grep -v frontend/
```
Expected: only the root `package.json` line appears (plus possibly `package-lock.json`). If so, delete both root manifests:
```bash
cd /workspace/.worktrees/data-org && git rm --cached package.json package-lock.json 2>/dev/null; rm -f package.json package-lock.json
```
(If the grep shows the root manifest IS referenced elsewhere, instead edit `package.json` to `{ "dependencies": {} }` and leave the lockfile.)

- [ ] **Step 4: Commit**

```bash
cd /workspace/.worktrees/data-org && git add -A frontend/package.json frontend/package-lock.json package.json package-lock.json && git commit -m "chore: add @mui/x-tree-view@7 to frontend, drop stray root pin"
```

---

### Task 2: Deterministic template-zip generator + drift guard

**Files:**
- Create: `src/schema/build_template_zips.py`
- Create (generated, committed): `frontend/public/templates/sample_id_experimental.zip`, `frontend/public/templates/sample_id_simulation.zip`
- Create: `tests/test_template_zips.py`
- Modify: `pyproject.toml` (add `template-zips` pixi task; add it to the `sync` aggregate)

**Interfaces:**
- Produces: `build_template_zips.build_zip(src_dir: Path) -> bytes` (deterministic zip of a template dir, entries prefixed with `src_dir.name/`); `ZIP_TARGETS: list[tuple[Path, Path]]` mapping each source template dir to its committed output path; `main(argv) -> int` with `--check`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_template_zips.py`:
```python
"""Drift guard: the committed starter-template zips under
frontend/public/templates/ must match a fresh deterministic build of the
canonical templates/ dirs. Mirrors the sync_templates --check pattern.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

from schema.build_template_zips import ZIP_TARGETS, build_zip

_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_zip_is_deterministic():
    src = _REPO_ROOT / "templates" / "sample_id_experimental"
    assert build_zip(src) == build_zip(src)


def test_zip_contains_sample_toml_and_skeleton_dirs():
    src = _REPO_ROOT / "templates" / "sample_id_experimental"
    names = set(zipfile.ZipFile(io.BytesIO(build_zip(src))).namelist())
    assert "sample_id_experimental/sample.toml" in names
    assert "sample_id_experimental/acquisition_id/Frames/" in names


def test_committed_zips_match_fresh_build():
    stale = []
    for src, out in ZIP_TARGETS:
        if not out.is_file() or out.read_bytes() != build_zip(src):
            stale.append(out.relative_to(_REPO_ROOT))
    assert not stale, (
        f"stale template zips: {stale}. Run `pixi run template-zips`."
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd /workspace/.worktrees/data-org && .pixi/envs/test/bin/python -m pytest tests/test_template_zips.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'schema.build_template_zips'`.

- [ ] **Step 3: Implement the generator**

Create `src/schema/build_template_zips.py`:
```python
"""Zip the researcher starter-template directories into static downloads.

The canonical starter dirs under ``templates/sample_id_experimental/`` and
``templates/sample_id_simulation/`` are zipped into
``frontend/public/templates/{name}.zip`` and served by the frontend as
"Download template" links on the /data-organization page.

Zips are deterministic (sorted entries, fixed timestamp, ZIP_STORED) so
``tests/test_template_zips.py`` can byte-compare the committed files against a
fresh build and fail the suite on drift.

Usage:
    pixi run template-zips              # rewrite the committed zips
    python -m schema.build_template_zips --check   # exit 1 if out of date
"""

from __future__ import annotations

import argparse
import io
import sys
import zipfile
from pathlib import Path

# src/schema/build_template_zips.py -> repo root is three parents up.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATES = _REPO_ROOT / "templates"
_OUT_DIR = _REPO_ROOT / "frontend" / "public" / "templates"

# Fixed DOS timestamp (zip epoch) so output bytes never depend on mtimes.
_FIXED_DT = (1980, 1, 1, 0, 0, 0)

# (source template dir, committed output zip). The zip's top-level folder is
# the source dir name, so unzip yields a renamable starter directory.
ZIP_TARGETS: list[tuple[Path, Path]] = [
    (_TEMPLATES / "sample_id_experimental", _OUT_DIR / "sample_id_experimental.zip"),
    (_TEMPLATES / "sample_id_simulation", _OUT_DIR / "sample_id_simulation.zip"),
]


def build_zip(src_dir: Path) -> bytes:
    """Return a deterministic ZIP_STORED archive of ``src_dir``.

    Entries are sorted and prefixed with ``src_dir.name/``; empty directories
    are preserved as explicit directory entries.
    """
    buf = io.BytesIO()
    prefix = src_dir.name
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        for path in sorted(src_dir.rglob("*"), key=lambda p: p.relative_to(src_dir).as_posix()):
            rel = path.relative_to(src_dir).as_posix()
            arcname = f"{prefix}/{rel}"
            if path.is_dir():
                info = zipfile.ZipInfo(arcname + "/", date_time=_FIXED_DT)
                info.external_attr = (0o40755 << 16) | 0x10  # dir + drwxr-xr-x
                zf.writestr(info, b"")
            else:
                info = zipfile.ZipInfo(arcname, date_time=_FIXED_DT)
                info.external_attr = 0o644 << 16
                zf.writestr(info, path.read_bytes())
    return buf.getvalue()


def _stale() -> list[tuple[Path, Path]]:
    out = []
    for src, dest in ZIP_TARGETS:
        if not dest.is_file() or dest.read_bytes() != build_zip(src):
            out.append((src, dest))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if any committed zip is out of date; write nothing",
    )
    args = parser.parse_args(argv)

    stale = _stale()
    if args.check:
        if stale:
            for _src, dest in stale:
                print(f"out of date: {dest.relative_to(_REPO_ROOT)}")
            print("run `pixi run template-zips` to regenerate")
            return 1
        print("template zips are in sync")
        return 0

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    for src, dest in ZIP_TARGETS:
        dest.write_bytes(build_zip(src))
        print(f"wrote {dest.relative_to(_REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Generate the committed zips**

Run:
```bash
cd /workspace/.worktrees/data-org && .pixi/envs/test/bin/python -m schema.build_template_zips
```
Expected: prints `wrote frontend/public/templates/sample_id_experimental.zip` and `…sample_id_simulation.zip`; both files now exist.

- [ ] **Step 5: Run the test to verify it passes**

Run:
```bash
cd /workspace/.worktrees/data-org && .pixi/envs/test/bin/python -m pytest tests/test_template_zips.py -v
```
Expected: 3 passed.

- [ ] **Step 6: Add the pixi task**

In `pyproject.toml`, under `[tool.pixi.tasks]`, add after the `sync-templates` line:
```toml
template-zips = "python -m schema.build_template_zips"
```
and add `"template-zips"` to the `sync` aggregate's `depends-on` list so `pixi run sync` regenerates everything:
```toml
sync = { depends-on = ["json-schema", "form-fields", "sync-templates", "template-zips"] }
```

- [ ] **Step 7: Commit**

```bash
cd /workspace/.worktrees/data-org && git add src/schema/build_template_zips.py tests/test_template_zips.py pyproject.toml frontend/public/templates && git commit -m "feat: deterministic template-zip generator + drift guard"
```

---

### Task 3: `FileTree` component

**Files:**
- Create: `frontend/src/components/dataOrganization/FileTree.tsx`
- Create: `frontend/src/components/dataOrganization/__tests__/FileTree.test.tsx`

**Interfaces:**
- Produces: `type FileNode = { name: string; kind: 'dir' | 'file'; comment?: string; children?: FileNode[] }` and `export function FileTree({ nodes }: { nodes: FileNode[] }): JSX.Element` — a read-only, fully-expanded annotated tree. Directory names render with a trailing `/`; `comment` renders muted after the name.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/dataOrganization/__tests__/FileTree.test.tsx`:
```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { FileTree, type FileNode } from '../FileTree'

const nodes: FileNode[] = [
  {
    name: 'Experimental',
    kind: 'dir',
    comment: 'data_source = experimental',
    children: [{ name: 'sample.toml', kind: 'file', comment: 'sample-level conditions' }],
  },
]

describe('FileTree', () => {
  it('renders directory names with a trailing slash and their comments', () => {
    render(<FileTree nodes={nodes} />)
    expect(screen.getByText('Experimental/')).toBeInTheDocument()
    expect(screen.getByText('# data_source = experimental')).toBeInTheDocument()
  })

  it('renders nested file nodes (expanded by default)', () => {
    render(<FileTree nodes={nodes} />)
    expect(screen.getByText('sample.toml')).toBeInTheDocument()
    expect(screen.getByText('# sample-level conditions')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd /workspace/.worktrees/data-org/frontend && npx vitest run src/components/dataOrganization/__tests__/FileTree.test.tsx
```
Expected: FAIL — cannot resolve `../FileTree`.

- [ ] **Step 3: Implement `FileTree`**

Create `frontend/src/components/dataOrganization/FileTree.tsx`:
```tsx
import { Box, Typography } from '@mui/material'
import { SimpleTreeView } from '@mui/x-tree-view/SimpleTreeView'
import { TreeItem } from '@mui/x-tree-view/TreeItem'

export type FileNode = {
  name: string
  kind: 'dir' | 'file'
  comment?: string
  children?: FileNode[]
}

// itemId = slash path from the root, stable + unique within one tree.
function renderNodes(nodes: FileNode[], parentId = ''): React.ReactNode {
  return nodes.map((node) => {
    const itemId = parentId ? `${parentId}/${node.name}` : node.name
    return (
      <TreeItem
        key={itemId}
        itemId={itemId}
        label={
          <Box component="span" sx={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
            {node.name}
            {node.kind === 'dir' ? '/' : ''}
            {node.comment && (
              <Typography component="span" color="text.secondary" sx={{ ml: 2, fontFamily: 'monospace' }}>
                # {node.comment}
              </Typography>
            )}
          </Box>
        }
      >
        {node.children ? renderNodes(node.children, itemId) : null}
      </TreeItem>
    )
  })
}

function collectDirIds(nodes: FileNode[], parentId = ''): string[] {
  return nodes.flatMap((node) => {
    const itemId = parentId ? `${parentId}/${node.name}` : node.name
    return node.children ? [itemId, ...collectDirIds(node.children, itemId)] : []
  })
}

export function FileTree({ nodes }: { nodes: FileNode[] }) {
  // Read-only reference tree: expand everything, disable selection.
  return (
    <SimpleTreeView
      defaultExpandedItems={collectDirIds(nodes)}
      disableSelection
      sx={{ overflowX: 'auto' }}
    >
      {renderNodes(nodes)}
    </SimpleTreeView>
  )
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
cd /workspace/.worktrees/data-org/frontend && npx vitest run src/components/dataOrganization/__tests__/FileTree.test.tsx
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd /workspace/.worktrees/data-org && git add frontend/src/components/dataOrganization/FileTree.tsx frontend/src/components/dataOrganization/__tests__/FileTree.test.tsx && git commit -m "feat: FileTree component for annotated data-layout trees"
```

---

### Task 4: Tree data + `/data-organization` route + nav link

**Files:**
- Create: `frontend/src/components/dataOrganization/trees.ts`
- Create: `frontend/src/routes/data-organization.tsx`
- Modify: `frontend/src/components/Header.tsx:63-67` (`DATA_MANAGEMENT_LINKS`)

**Interfaces:**
- Consumes: `FileTree`, `FileNode` (Task 3); `CustomLink` (`~/components/CustomLink`); `@mui/x-tree-view` (Task 1).
- Produces: route `/data-organization`; nav entry in `DATA_MANAGEMENT_LINKS`.

- [ ] **Step 1: Create the tree data**

Create `frontend/src/components/dataOrganization/trees.ts` — transcribe the three source blocks into `FileNode[]`. Use `{id_placeholders}` names verbatim; comments are the trailing `#` notes.
```ts
import type { FileNode } from './FileTree'

// Block #1 — the data root's two arms (source of truth for data_source /
// dataset_type, both derived from placement, never authored).
export const dataRootTree: FileNode[] = [
  {
    name: '{data_root}',
    kind: 'dir',
    children: [
      {
        name: 'Experimental',
        kind: 'dir',
        comment: 'data_source = experimental',
        children: [{ name: '{sample_id}', kind: 'dir', comment: '…' }],
      },
      {
        name: 'MdSimulation',
        kind: 'dir',
        comment: 'data_source = simulation',
        children: [
          { name: 'Bulk', kind: 'dir', comment: 'dataset_type = bulk', children: [{ name: '{sample_id}', kind: 'dir', comment: '…' }] },
          { name: 'SingleMolecule', kind: 'dir', comment: 'dataset_type = single_molecule', children: [{ name: '{sample_id}', kind: 'dir', comment: '…' }] },
          { name: 'Slab', kind: 'dir', comment: 'dataset_type = slab', children: [{ name: '{sample_id}', kind: 'dir', comment: '…' }] },
        ],
      },
    ],
  },
]

// Block #2 — experimental sample layout.
export const experimentalTree: FileNode[] = [
  {
    name: 'Experimental',
    kind: 'dir',
    children: [
      {
        name: '{sample_id}',
        kind: 'dir',
        comment: 'sample identity = directory name',
        children: [
          { name: 'sample.toml', kind: 'file', comment: 'sample-level conditions' },
          {
            name: '{acquisition_id}',
            kind: 'dir',
            comment: 'acquisition identity = directory name',
            children: [
              { name: 'acquisition.toml', kind: 'file', comment: 'per-acquisition params + processing log' },
              { name: 'Frames', kind: 'dir', comment: 'raw movie frames (.eer / .tiff) + .mdoc' },
              { name: 'Gains', kind: 'dir', comment: 'gain reference' },
              {
                name: 'TiltSeries',
                kind: 'dir',
                children: [
                  {
                    name: '{tilt_series_id}',
                    kind: 'dir',
                    comment: 'one subfolder per tilt series (raw and/or aligned)',
                    children: [
                      { name: 'stack', kind: 'dir', comment: '.mrc projection stack (+ .zarr / .rawtlt); MAY be empty' },
                      {
                        name: 'alignment',
                        kind: 'dir',
                        comment: 'MAY be empty if this is the raw tilt series',
                        children: [{ name: 'alignment.json', kind: 'file', comment: 'affine matrix + interpolation recipe (or any other alignment data)' }],
                      },
                    ],
                  },
                ],
              },
              {
                name: 'Reconstructions',
                kind: 'dir',
                children: [
                  {
                    name: 'Tomograms',
                    kind: 'dir',
                    children: [
                      { name: '{tomogram_id}', kind: 'dir', comment: 'one subfolder per processing pipeline', children: [{ name: '*.mrc', kind: 'file' }, { name: '*.zarr', kind: 'file' }] },
                    ],
                  },
                  {
                    name: 'Annotations',
                    kind: 'dir',
                    children: [
                      { name: '{annotation_id}', kind: 'dir', children: [{ name: '*.star', kind: 'file' }, { name: '*.mrc / *.zarr', kind: 'file' }] },
                    ],
                  },
                ],
              },
            ],
          },
        ],
      },
    ],
  },
]

// Block #3 — MD simulation sample layout.
export const simulationTree: FileNode[] = [
  {
    name: 'MdSimulation/{Bulk|SingleMolecule|Slab}',
    kind: 'dir',
    children: [
      {
        name: '{sample_id}',
        kind: 'dir',
        children: [
          { name: 'sample.toml', kind: 'file', comment: 'sample-level conditions' },
          {
            name: 'MdRuns',
            kind: 'dir',
            comment: 'simulation only: one subfolder per MD run',
            children: [
              {
                name: '{md_run_id}',
                kind: 'dir',
                comment: 'the folder name IS the run id',
                children: [
                  { name: 'md_run.toml', kind: 'file', comment: 'seed, sample_time, timestep, computer, …' },
                  { name: 'Trajectories', kind: 'dir', comment: 'raw simulation output' },
                  { name: 'Snapshots', kind: 'dir', comment: 'extracted conformations (frames)' },
                ],
              },
            ],
          },
          {
            name: 'SyntheticCryoET',
            kind: 'dir',
            comment: 'wraps all synthetic-cryoET acquisitions for this sample',
            children: [
              {
                name: '{acquisition_id}',
                kind: 'dir',
                comment: 'synthetic cryoET from one md_run frame',
                children: [
                  { name: 'acquisition.toml', kind: 'file', comment: 'per-acquisition params + [md_source]' },
                  {
                    name: 'TiltSeries',
                    kind: 'dir',
                    children: [
                      { name: '{tilt_series_id}', kind: 'dir', comment: 'one subfolder per tilt series', children: [{ name: 'stack', kind: 'dir' }, { name: 'alignment', kind: 'dir' }] },
                    ],
                  },
                  {
                    name: 'Reconstructions',
                    kind: 'dir',
                    children: [
                      { name: 'Tomograms', kind: 'dir', children: [{ name: '{tomogram_id}', kind: 'dir', comment: 'one subfolder per processing pipeline', children: [{ name: '*.mrc', kind: 'file' }, { name: '*.zarr', kind: 'file' }] }] },
                      { name: 'Annotations', kind: 'dir', children: [{ name: '{annotation_id}', kind: 'dir', children: [{ name: '*.star', kind: 'file' }, { name: '*.mrc / *.zarr', kind: 'file' }] }] },
                    ],
                  },
                ],
              },
            ],
          },
        ],
      },
    ],
  },
]
```

- [ ] **Step 2: Create the route**

Create `frontend/src/routes/data-organization.tsx`. Static content; layout mirrors `author.tsx` (breadcrumb + `Stack` of sections). Author-tab links sit in a row beneath each dataset tree; download buttons use `ButtonLink` is NOT needed — templates are static files, so use a plain MUI `Button component="a" href download`.
```tsx
import { createFileRoute } from '@tanstack/react-router'
import {
  Box,
  Breadcrumbs,
  Button,
  Divider,
  Stack,
  Typography,
} from '@mui/material'
import DownloadIcon from '@mui/icons-material/Download'
import { CustomLink } from '~/components/CustomLink'
import { FileTree } from '~/components/dataOrganization/FileTree'
import {
  dataRootTree,
  experimentalTree,
  simulationTree,
} from '~/components/dataOrganization/trees'

export const Route = createFileRoute('/data-organization')({
  component: DataOrganization,
})

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <Typography variant="h6" component="h2">
      {children}
    </Typography>
  )
}

function AuthorLinks({
  tabs,
}: {
  tabs: { tab: 'sample' | 'acquisition' | 'md_run'; label: string }[]
}) {
  return (
    <Typography variant="body2" color="text.secondary">
      Author these files:{' '}
      {tabs.map((t, i) => (
        <span key={t.tab}>
          {i > 0 && ' · '}
          <CustomLink to="/author" search={{ tab: t.tab }}>
            {t.label}
          </CustomLink>
        </span>
      ))}
    </Typography>
  )
}

function DownloadTemplate({ name, label }: { name: string; label: string }) {
  return (
    <Button
      component="a"
      href={`/templates/${name}.zip`}
      download
      variant="outlined"
      size="small"
      startIcon={<DownloadIcon />}
      sx={{ alignSelf: 'flex-start' }}
    >
      {label}
    </Button>
  )
}

function DataOrganization() {
  return (
    <Stack spacing={4}>
      <Breadcrumbs aria-label="breadcrumb">
        <CustomLink to="/" color="inherit" sx={{ fontWeight: 700 }}>
          Home
        </CustomLink>
        <Typography color="text.primary">Data organization</Typography>
      </Breadcrumbs>

      <Box>
        <Typography variant="h5" component="h1">
          Organizing data for ingestion
        </Typography>
        <Typography variant="body2" color="text.secondary">
          How to place new cryoET data on the Janelia file share so the catalog
          scanner ingests it correctly.
        </Typography>
      </Box>

      {/* Section 1 — where the data lives */}
      <Stack spacing={2}>
        <SectionHeading>1. Where to find the data</SectionHeading>
        <Typography variant="body2">
          All data lives on the Janelia file share, reachable over the{' '}
          <strong>Janelia VPN</strong>, under the <code>cryoet</code> share's{' '}
          <code>data/</code> directory (the data root). Starter templates for a
          new sample live on the same share at <code>scratch/templates/</code>{' '}
          (<code>scratch</code> is a checkout of this repository).
        </Typography>
        <Typography variant="body2">
          The data root has two top-level arms. The arm a sample lives under is
          the source of truth for its <code>data_source</code> (and, for
          simulation, its <code>dataset_type</code>) — these are derived from
          directory placement, never authored in a <code>.toml</code> file.
        </Typography>
        <FileTree nodes={dataRootTree} />
      </Stack>

      <Divider />

      {/* Section 2 — experimental */}
      <Stack spacing={2}>
        <SectionHeading>2. Adding an experimental dataset</SectionHeading>
        <Typography variant="body2">
          Copy the starter template at{' '}
          <code>scratch/templates/sample_id_experimental/</code> into{' '}
          <code>Experimental/</code>, rename the sample directory, and add an
          acquisition subdirectory per acquisition. Author{' '}
          <code>sample.toml</code> at the sample root and{' '}
          <code>acquisition.toml</code> in each acquisition directory.
        </Typography>
        <DownloadTemplate
          name="sample_id_experimental"
          label="Download experimental template"
        />
        <FileTree nodes={experimentalTree} />
        <AuthorLinks
          tabs={[
            { tab: 'sample', label: 'Sample' },
            { tab: 'acquisition', label: 'Acquisition' },
          ]}
        />
      </Stack>

      <Divider />

      {/* Section 3 — simulation */}
      <Stack spacing={2}>
        <SectionHeading>3. Adding an MD simulation dataset</SectionHeading>
        <Typography variant="body2">
          Copy the starter template at{' '}
          <code>scratch/templates/sample_id_simulation/</code> into the matching{' '}
          <code>MdSimulation/{'{Bulk|SingleMolecule|Slab}'}/</code> arm. Author{' '}
          <code>sample.toml</code>, one <code>md_run.toml</code> per MD run under{' '}
          <code>MdRuns/</code>, and an <code>acquisition.toml</code> per
          synthetic-cryoET acquisition under <code>SyntheticCryoET/</code>.
        </Typography>
        <DownloadTemplate
          name="sample_id_simulation"
          label="Download simulation template"
        />
        <FileTree nodes={simulationTree} />
        <AuthorLinks
          tabs={[
            { tab: 'sample', label: 'Sample' },
            { tab: 'md_run', label: 'MD run' },
            { tab: 'acquisition', label: 'Acquisition' },
          ]}
        />
      </Stack>

      <Divider />

      {/* Section 4 — processing log */}
      <Stack spacing={2}>
        <SectionHeading>
          4. Append to the processing log as outputs are produced
        </SectionHeading>
        <Typography variant="body2">
          Each <code>acquisition.toml</code> grows over time. Record the raw
          reconstruction once in <code>[raw_tomogram]</code>; for each new output
          — a denoised version, a segmentation, an STA result — append a new{' '}
          <code>[[post_processed_tomogram]]</code> or <code>[[annotation]]</code>{' '}
          entry to the relevant acquisition's file.
        </Typography>
        <Box component="ul" sx={{ m: 0, pl: 3 }}>
          <Typography component="li" variant="body2">
            Do not delete or modify a tomogram or annotation entry once added.
            Reprocessing produces a new entry with a new <code>id</code>, placed
            at the bottom of the file.
          </Typography>
          <Typography component="li" variant="body2">
            The <code>id</code> must match a folder name under{' '}
            <code>TiltSeries/</code>, <code>Reconstructions/Tomograms/</code>, or{' '}
            <code>Reconstructions/Annotations/</code>.
          </Typography>
          <Typography component="li" variant="body2">
            Use <code>derived_from</code> and <code>target_tomogram</code> to
            record lineage between entries.
          </Typography>
        </Box>
      </Stack>
    </Stack>
  )
}
```

- [ ] **Step 3: Add the nav link**

In `frontend/src/components/Header.tsx`, add `/data-organization` as the first entry of `DATA_MANAGEMENT_LINKS` (lines 63-67):
```tsx
const DATA_MANAGEMENT_LINKS = [
  { to: "/data-organization" as const, label: "Data organization" },
  { to: "/author" as const, label: "Author metadata" },
  { to: "/manage" as const, label: "Review warnings and errors" },
  { to: "/manage/deletions" as const, label: "View deletions and renames" },
];
```

- [ ] **Step 4: Typecheck + build (regenerates the route tree)**

Run:
```bash
cd /workspace/.worktrees/data-org/frontend && npm run build
```
Expected: build succeeds, `tsc --noEmit` passes, and `/data-organization` appears in the regenerated `src/routeTree.gen.ts`. If TypeScript complains that `search` is required on the `/author` `CustomLink`, confirm `{ tab }` satisfies the route's `validateSearch` (it does — `id`/`sampleId` are optional).

- [ ] **Step 5: Run the frontend test suite**

Run:
```bash
cd /workspace/.worktrees/data-org/frontend && npm test
```
Expected: all tests pass (including `FileTree.test.tsx`).

- [ ] **Step 6: Commit**

```bash
cd /workspace/.worktrees/data-org && git add frontend/src/components/dataOrganization/trees.ts frontend/src/routes/data-organization.tsx frontend/src/routeTree.gen.ts frontend/src/components/Header.tsx && git commit -m "feat: add /data-organization guide page + nav link"
```

---

### Task 5: Manual verification + full suites

**Files:** none (verification only)

- [ ] **Step 1: Run both test suites**

```bash
cd /workspace/.worktrees/data-org && .pixi/envs/test/bin/python -m pytest tests/test_template_zips.py tests/test_repo_consistency.py -v
cd /workspace/.worktrees/data-org/frontend && npm test
```
Expected: all pass.

- [ ] **Step 2: Visual smoke test in dev**

```bash
cd /workspace/.worktrees/data-org/frontend && npm run dev
```
Then in a browser over the VPN-equivalent local server: open `/data-organization`. Verify: four sections render; all three trees are expanded and readable; the two download buttons fetch a valid zip (unzip one and confirm it contains `sample_id_experimental/sample.toml` + empty skeleton dirs); the author-tab links navigate to `/author?tab=…`; the "Data organization" nav entry appears first in the Data management menu (desktop dropdown + mobile accordion). Stop the dev server when done.

- [ ] **Step 3: Confirm the drift guard works**

Temporarily edit `templates/sample.toml` (add a blank line), then:
```bash
cd /workspace/.worktrees/data-org && .pixi/envs/test/bin/python -m schema.build_template_zips --check
```
Expected: exit 1 with `out of date: …`. Revert the edit and re-run `--check`; expect `template zips are in sync`.

---

## Notes for the implementer

- The route tree (`frontend/src/routeTree.gen.ts`) is regenerated by the TanStack plugin on `npm run dev`/`npm run build` — don't hand-edit it; commit the regenerated version.
- `public/` is served at web root in dev, the `srvx` prod server, and the Docker image (the frontend build context includes `public/`), so `/templates/*.zip` resolves in all environments.
- If a future schema/template change lands, `pixi run sync` now also rebuilds the zips; `tests/test_template_zips.py` fails loudly if someone forgets.
