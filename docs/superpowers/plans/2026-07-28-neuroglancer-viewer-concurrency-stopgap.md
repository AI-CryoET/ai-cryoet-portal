# Neuroglancer Viewer Concurrency Stopgap (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop concurrent Neuroglancer viewers from degrading each other by serving volume chunks from RAM again (instead of on-demand NFS via mmap), sized so 10–25 viewers fit in memory.

**Architecture:** Revert the `read_mrc_volume` load path to an in-RAM copy for volumes ≤ 1.5 GB (mmap fallback above that, so a surprise large volume can't OOM the pod), share one read-only array across concurrent viewers of the same tomogram via a process-wide LRU cache, and resize the pod (memory up, the useless CPU bump down). The coordinate-transform flip stays; the only load-path revert is copy-vs-mmap.

**Tech Stack:** Python 3.14, `mrcfile`, `numpy`, `functools.lru_cache`, `loguru`; FastAPI app; Kustomize/OpenShift manifests. Tests run under the `api` pixi env.

## Global Constraints

- **No persistent `.mrc`→`.zarr` conversion** (project lead constraint). Phase 1 needs none.
- `COPY_MAX_BYTES = int(1.5 * 1024**3)` — volumes at or below this are copied to RAM; larger fall back to mmap.
- `NEUROGLANCER_MAX_VIEWERS` default = **12**; volume LRU `maxsize` = **12** (must stay aligned).
- Worst-case resident memory ≈ `MAX_VIEWERS × COPY_MAX_BYTES` = 12 × 1.5 GB = 18 GB; pod memory limit **24 Gi** / request **6 Gi**.
- Pod CPU limit **4** / request **1** (revert the earlier `cpu: 8`).
- Keep the coordinate-transform flip in `_neuroglancer.py` — do NOT revert it.
- API stays single-replica / single-worker (Neuroglancer server is process-global).
- Test invocation: `.pixi/envs/api/bin/python -m pytest <path> -v` (numpy/mrcfile/neuroglancer live in the `api` env, not the base interpreter).
- **Deploy prerequisite (not a code task):** platform team must confirm the nfs-dmz node can give the api pod 24 Gi.

## File Structure

- `src/catalog/imaging/_mrc.py` — add `COPY_MAX_BYTES`, a size-guarded `_load_mrc_volume`, and a cached `_load_mrc_volume_cached` wrapper; `read_mrc_volume` becomes a thin `(path, mtime)` cache lookup. Responsibility: turning an MRC path into `(data, voxel_size, axis_order)` for the viewer.
- `tests/catalog/test_api_neuroglancer.py` — add unit tests for copy vs mmap and the shared cache (reuses the existing `_write_synthetic_mrc` helper).
- `src/catalog/api/main.py` — `NEUROGLANCER_MAX_VIEWERS` default 32 → 12 (3 occurrences).
- `README.md` — env-var table default 32 → 12, note copy-vs-mmap behaviour.
- `deploy/k8s/overlays/production/config.env` + `config.env.example` — commented default hint 32 → 12.
- `deploy/k8s/base/api.yaml` — resources block (cpu limit 8→4, memory limit 4Gi→24Gi, memory request 512Mi→6Gi).

---

### Task 1: Size-guarded in-RAM copy loader (mmap fallback)

**Files:**
- Modify: `src/catalog/imaging/_mrc.py` (imports at top; replace `read_mrc_volume` body, lines 141–end of function)
- Test: `tests/catalog/test_api_neuroglancer.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `COPY_MAX_BYTES: int` (module constant in `_mrc.py`)
  - `_load_mrc_volume(mrc_path: str) -> tuple[np.ndarray, tuple[float, float, float], str]`
  - `read_mrc_volume(mrc_path: Path | str) -> tuple[np.ndarray, tuple[float, float, float], str]` (unchanged signature; now returns an in-RAM ndarray for volumes ≤ `COPY_MAX_BYTES`, else a `np.memmap`)

- [ ] **Step 1: Write the failing tests**

Add to `tests/catalog/test_api_neuroglancer.py` (the `_write_synthetic_mrc` helper already exists there and writes a tiny 4×8×8 MRC):

```python
def test_read_mrc_volume_small_is_in_ram_copy(tmp_path):
    """Volumes under COPY_MAX_BYTES are read fully into RAM (not a memmap)."""
    from catalog.imaging import _mrc

    p = tmp_path / "small.mrc"
    _write_synthetic_mrc(p)
    data, _voxel, _axes = _mrc.read_mrc_volume(p)
    assert not isinstance(data, np.memmap)


def test_read_mrc_volume_oversize_falls_back_to_mmap(tmp_path, monkeypatch):
    """Volumes over COPY_MAX_BYTES fall back to mmap so the pod can't OOM."""
    from catalog.imaging import _mrc

    monkeypatch.setattr(_mrc, "COPY_MAX_BYTES", 1)  # force the tiny file oversize
    p = tmp_path / "oversize.mrc"
    _write_synthetic_mrc(p)
    data, _voxel, _axes = _mrc.read_mrc_volume(p)
    assert isinstance(data, np.memmap)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.pixi/envs/api/bin/python -m pytest tests/catalog/test_api_neuroglancer.py::test_read_mrc_volume_small_is_in_ram_copy tests/catalog/test_api_neuroglancer.py::test_read_mrc_volume_oversize_falls_back_to_mmap -v`
Expected: FAIL — the current mmap-only `read_mrc_volume` returns a `np.memmap` for the small file (`AssertionError` on the first test), and `_mrc.COPY_MAX_BYTES` does not exist yet (`AttributeError` in the second).

- [ ] **Step 3: Add imports at the top of `_mrc.py`**

After the existing `from pathlib import Path` / `from typing import Literal` block, add:

```python
import os
```

and after the third-party imports (`import mrcfile` / `import numpy as np`) add:

```python
from loguru import logger
```

- [ ] **Step 4: Replace the `read_mrc_volume` function**

Replace the entire current `read_mrc_volume` function (the mmap version, from its `def` through `return data, voxel_size, axis_order`) with:

```python
# Volumes at or below this size are read fully into RAM so Neuroglancer serves
# chunks from memory (fast, no per-chunk NFS reads) — this is what keeps
# concurrent viewers from serializing on blocking NFS reads in the single
# in-process server. Larger volumes fall back to mmap: slow to serve, but the
# pod won't OOM. Sized just above the ~1.3 GB production ceiling; a volume that
# trips the fallback is the signal it's time for Phase 2 (multi-process pool).
COPY_MAX_BYTES = int(1.5 * 1024**3)


def _load_mrc_volume(mrc_path: str) -> tuple[np.ndarray, tuple[float, float, float], str]:
    """Load an MRC into ``(data, voxel_size_nm_in_array_order, axis_order)``.

    ``data`` is an in-RAM copy for volumes ≤ ``COPY_MAX_BYTES`` (fast chunk
    serving, no per-chunk NFS), or a read-only ``mmap`` for larger volumes
    (slow serving, but bounded memory so the pod survives).
    """
    size = os.path.getsize(mrc_path)
    use_copy = size <= COPY_MAX_BYTES
    if not use_copy:
        logger.warning(
            "MRC {} is {:.1f} GB (> {:.1f} GB COPY_MAX_BYTES); serving via mmap "
            "(slow per-chunk). Large volumes are the Phase 2 trigger.",
            mrc_path,
            size / 1024**3,
            COPY_MAX_BYTES / 1024**3,
        )

    # Copy path: read into RAM then close. mmap path: keep the handle open —
    # numpy keeps the map alive via data.base, but closing here would unmap it.
    mrc = (mrcfile.open if use_copy else mrcfile.mmap)(
        mrc_path, mode="r", permissive=True
    )
    data = mrc.data.copy() if use_copy else mrc.data
    # MRC headers store spacing in Angstrom; Neuroglancer is told nm.
    vx = float(mrc.voxel_size.x) / 10.0
    vy = float(mrc.voxel_size.y) / 10.0
    vz = float(mrc.voxel_size.z) / 10.0
    mapc = int(mrc.header.mapc)
    mapr = int(mrc.header.mapr)
    maps = int(mrc.header.maps)
    if use_copy:
        mrc.close()

    axis_names = {1: "x", 2: "y", 3: "z"}
    axis_order = f"{axis_names[maps]}{axis_names[mapr]}{axis_names[mapc]}"
    voxel_map = {"x": vx, "y": vy, "z": vz}
    voxel_size = (
        voxel_map[axis_order[0]],
        voxel_map[axis_order[1]],
        voxel_map[axis_order[2]],
    )
    return data, voxel_size, axis_order


def read_mrc_volume(
    mrc_path: Path | str,
) -> tuple[np.ndarray, tuple[float, float, float], str]:
    """Load an MRC volume + voxel size (nm, array-axis order) + axis order.

    Returns ``(data, voxel_size, axis_order)``. ``data`` is an in-RAM copy for
    volumes ≤ ``COPY_MAX_BYTES`` (Neuroglancer serves chunks from memory), or a
    read-only ``np.memmap`` for larger volumes (bounded memory, slower serving).

    Voxel size is returned in **nm** (MRC headers are Angstrom): ``view_neuroglancer``
    builds a ``CoordinateSpace(units="nm")``, and Neuroglancer rejects ``"angstrom"``.
    """
    return _load_mrc_volume(str(mrc_path))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.pixi/envs/api/bin/python -m pytest tests/catalog/test_api_neuroglancer.py::test_read_mrc_volume_small_is_in_ram_copy tests/catalog/test_api_neuroglancer.py::test_read_mrc_volume_oversize_falls_back_to_mmap -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Run the full neuroglancer suite (regression)**

Run: `.pixi/envs/api/bin/python -m pytest tests/catalog/test_api_neuroglancer.py -v`
Expected: PASS — including the existing `test_read_mrc_volume_returns_nm_in_array_order` (voxel reorder unchanged).

- [ ] **Step 7: Commit**

```bash
git add src/catalog/imaging/_mrc.py tests/catalog/test_api_neuroglancer.py
git commit -m "perf(imaging): read MRC volumes into RAM with an mmap size guard

Reverts the per-chunk mmap serving that serialized concurrent viewers on NFS
reads. Volumes <=COPY_MAX_BYTES (1.5 GB) are copied into RAM (fast serving);
larger ones fall back to mmap so the pod can't OOM.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Shared loaded-volume LRU cache

**Files:**
- Modify: `src/catalog/imaging/_mrc.py` (wrap `_load_mrc_volume`, adjust `read_mrc_volume`)
- Test: `tests/catalog/test_api_neuroglancer.py`

**Interfaces:**
- Consumes: `_load_mrc_volume(mrc_path: str)` from Task 1.
- Produces:
  - `_load_mrc_volume_cached(mrc_path: str, mtime: float) -> tuple[np.ndarray, tuple[float, float, float], str]` (LRU-cached, `maxsize=12`)
  - `read_mrc_volume` now keys the cache on `(str(path), os.path.getmtime(path))`, so concurrent viewers of the same unchanged file share one array object.

- [ ] **Step 1: Write the failing test**

Add to `tests/catalog/test_api_neuroglancer.py`:

```python
def test_read_mrc_volume_shared_cache_returns_same_array(tmp_path):
    """Two loads of the same unchanged file share one array (no re-read)."""
    from catalog.imaging import _mrc

    p = tmp_path / "shared.mrc"
    _write_synthetic_mrc(p)
    d1, _v1, _a1 = _mrc.read_mrc_volume(p)
    d2, _v2, _a2 = _mrc.read_mrc_volume(p)
    assert d1 is d2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.pixi/envs/api/bin/python -m pytest tests/catalog/test_api_neuroglancer.py::test_read_mrc_volume_shared_cache_returns_same_array -v`
Expected: FAIL — without the cache each call re-reads and `.copy()` returns a fresh array, so `d1 is d2` is False.

- [ ] **Step 3: Add the `functools.lru_cache` import**

At the top of `_mrc.py`, add:

```python
from functools import lru_cache
```

- [ ] **Step 4: Wrap the loader in a cache and update `read_mrc_volume`**

Add the cached wrapper immediately after `_load_mrc_volume`:

```python
# Shared across concurrent viewers: two tabs on the same tomogram share one
# read-only array instead of each copying it — the dominant memory saving when
# people view the same dataset. Keyed on (path, mtime) so a re-scan that rewrites
# the file invalidates automatically. maxsize is aligned with
# NEUROGLANCER_MAX_VIEWERS (12); raising that env var means bumping this too.
@lru_cache(maxsize=12)
def _load_mrc_volume_cached(
    mrc_path: str, mtime: float
) -> tuple[np.ndarray, tuple[float, float, float], str]:
    return _load_mrc_volume(mrc_path)
```

Change the body of `read_mrc_volume` from `return _load_mrc_volume(str(mrc_path))` to:

```python
    p = str(mrc_path)
    return _load_mrc_volume_cached(p, os.path.getmtime(p))
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.pixi/envs/api/bin/python -m pytest tests/catalog/test_api_neuroglancer.py::test_read_mrc_volume_shared_cache_returns_same_array -v`
Expected: PASS

- [ ] **Step 6: Run the full neuroglancer + tilt-series + annotations suites (regression)**

Run: `.pixi/envs/api/bin/python -m pytest tests/catalog/test_api_neuroglancer.py tests/catalog/test_api_tilt_series.py tests/catalog/test_api_annotations_preview.py -v`
Expected: PASS (all)

- [ ] **Step 7: Commit**

```bash
git add src/catalog/imaging/_mrc.py tests/catalog/test_api_neuroglancer.py
git commit -m "perf(imaging): share one loaded MRC array across concurrent viewers

Process-wide LRU (maxsize 12, keyed on path+mtime) so multiple tabs on the same
tomogram reuse one read-only array instead of each holding a copy.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Lower `NEUROGLANCER_MAX_VIEWERS` default to 12 + docs

**Files:**
- Modify: `src/catalog/api/main.py` (docstring line 14; `raw_max` default line 208; fallback line 212)
- Modify: `README.md` (env-var table row)
- Modify: `deploy/k8s/overlays/production/config.env` and `config.env.example` (commented hint)

**Interfaces:**
- Consumes: nothing.
- Produces: `app.state.neuroglancer_max_viewers` now defaults to 12.

- [ ] **Step 1: Edit `src/catalog/api/main.py`**

Line 14 (module docstring): change
`  NEUROGLANCER_MAX_VIEWERS   — bounded LRU size for active viewers (default 32).`
to
`  NEUROGLANCER_MAX_VIEWERS   — bounded LRU size for active viewers (default 12).`

Line 208: change `os.environ.get("NEUROGLANCER_MAX_VIEWERS", "32")` to `os.environ.get("NEUROGLANCER_MAX_VIEWERS", "12")`.

Line 212: change `app.state.neuroglancer_max_viewers = 32` to `app.state.neuroglancer_max_viewers = 12`.

- [ ] **Step 2: Edit `README.md`**

Change the env-var table row to:

```markdown
| `NEUROGLANCER_MAX_VIEWERS` | `12` | Maximum concurrent viewers in the LRU registry. Volumes ≤ 1.5 GB are read into RAM, so worst-case memory ≈ this × 1.5 GB — keep it matched to the pod memory limit. Raising it also requires bumping the volume-cache `maxsize` in `_mrc.py`. |
```

- [ ] **Step 3: Edit both production config env files**

In `deploy/k8s/overlays/production/config.env` and `deploy/k8s/overlays/production/config.env.example`, change `# NEUROGLANCER_MAX_VIEWERS=32` to `# NEUROGLANCER_MAX_VIEWERS=12`.

- [ ] **Step 4: Verify the app still imports and the default is 12**

Run: `.pixi/envs/api/bin/python -c "import os; os.environ.pop('NEUROGLANCER_MAX_VIEWERS', None); import ast, pathlib; src = pathlib.Path('src/catalog/api/main.py').read_text(); assert src.count('\"12\"') >= 1 and '= 12' in src and '\"32\"' not in src and '= 32' not in src; print('OK: default is 12')"`
Expected: `OK: default is 12`

- [ ] **Step 5: Commit**

```bash
git add src/catalog/api/main.py README.md deploy/k8s/overlays/production/config.env deploy/k8s/overlays/production/config.env.example
git commit -m "chore: lower NEUROGLANCER_MAX_VIEWERS default to 12

Copies pin ~1.5 GB each, so the viewer cap must match the pod memory budget
(12 x 1.5 GB = 18 GB worst case). Docs note the cache-maxsize coupling.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Resize the api pod (memory up, CPU bump reverted)

**Files:**
- Modify: `deploy/k8s/base/api.yaml` (resources block, lines 80–88)

**Interfaces:**
- Consumes: nothing.
- Produces: api Deployment with `requests: {cpu: "1", memory: 6Gi}`, `limits: {cpu: "4", memory: 24Gi}`.

- [ ] **Step 1: Edit the resources block in `deploy/k8s/base/api.yaml`**

Replace:

```yaml
          resources:
            requests:
              cpu: "1"
              memory: 512Mi
            limits:
              # Tomogram volumes are read into memory for Neuroglancer launches;
              # give the API generous headroom relative to the other services.
              cpu: "8"
              memory: 4Gi
```

with:

```yaml
          resources:
            requests:
              cpu: "1"
              memory: 6Gi
            limits:
              # Tomogram volumes are read into RAM for Neuroglancer serving, so
              # worst-case memory ~= NEUROGLANCER_MAX_VIEWERS (12) x COPY_MAX_BYTES
              # (1.5 GB) ~= 18 GB. 24Gi leaves headroom. CPU serving is light once
              # volumes are resident, so 4 cores is plenty (the 8-core bump was a
              # no-op — the old bottleneck was blocking NFS reads, not CPU).
              cpu: "4"
              memory: 24Gi
```

- [ ] **Step 2: Verify the overlay still renders**

Run: `oc kustomize deploy/k8s/overlays/production >/dev/null && echo "OK: overlay renders"`
Expected: `OK: overlay renders` (if `oc` is unavailable, use `kustomize build deploy/k8s/overlays/production >/dev/null && echo OK`)

- [ ] **Step 3: Confirm the rendered api container limits**

Run: `oc kustomize deploy/k8s/overlays/production | grep -A6 'name: api' | grep -E 'cpu|memory' ; echo '--- expect cpu 1/4, memory 6Gi/24Gi ---'`
Expected: shows `memory: 24Gi` and `cpu: "4"` under limits, `memory: 6Gi` / `cpu: "1"` under requests.

- [ ] **Step 4: Commit**

```bash
git add deploy/k8s/base/api.yaml
git commit -m "chore(k8s): size api pod for in-RAM volume copies (24Gi, 4 cpu)

Worst-case memory 12 viewers x 1.5 GB ~= 18 GB -> 24Gi limit / 6Gi request.
Revert the 8-core bump (no-op; bottleneck was NFS, not CPU) to 4.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Rollout (not code tasks — do after the tasks above)

1. **Confirm node RAM with the platform team:** the nfs-dmz node must be able to grant the api pod 24 Gi. Hard prerequisite.
2. **Build the image:** the `src/` changes ship in a new image — push a `v*.*.*` tag from `main` (per `deploy/DEPLOYMENT.md`) to build/publish, then bump `newTag` in `deploy/k8s/overlays/production/kustomization.yaml`.
3. **Deploy:** `oc apply -k deploy/k8s/overlays/production` (needs cluster-scoped perms for the PV — hand to the platform team, or apply the api Deployment change via `oc set resources`/`oc apply` of the rendered Deployment if namespace-scoped).
4. **Verify:** open 10–15 concurrent tabs; confirm the grey-loading and cross-tab slowdown are gone; watch `oc adm top pod -n ai-cryoet` stays under 24 Gi.

## Self-Review

- **Spec coverage:** in-RAM copy (Task 1) ✓; size guard/mmap fallback (Task 1) ✓; shared LRU cache (Task 2) ✓; MAX_VIEWERS=12 (Task 3) ✓; memory 24Gi / CPU 4 (Task 4) ✓; keep coordinate-transform (Global Constraints — untouched) ✓; node-RAM dependency (Rollout) ✓; testing (each task) ✓; Phase 2 (out of scope, spec only) ✓.
- **Placeholder scan:** none — all steps have concrete code/commands.
- **Type consistency:** `_load_mrc_volume(str)`, `_load_mrc_volume_cached(str, float)`, and `read_mrc_volume(Path|str)` all return `tuple[np.ndarray, tuple[float,float,float], str]`; `COPY_MAX_BYTES` referenced consistently; cache `maxsize=12` matches `NEUROGLANCER_MAX_VIEWERS=12`.
