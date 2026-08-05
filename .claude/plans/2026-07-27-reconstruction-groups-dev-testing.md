# Dev testing: reconstruction alignment groups

**Branch:** `feat/reconstruction-alignment-groups`
**Date:** 2026-07-27

Local-only runbook — **no k8s**. There is no dev/staging overlay
(`deploy/k8s/overlays/` contains only `production`), so pre-merge testing is
`pixi` on this box against a throwaway copy of `scratch/data`.

Every command below was run end to end on 2026-07-27; the numbers under
"expected" are what it actually produced.

---

## 0. What `scratch/data` is (and isn't) good for

`scratch/data` is the pre-`/data`-migration portal tree, and it was **already
converted to the grouped layout** by the earlier (unmerged) attempt. Most
acquisitions already have `Reconstructions/{group}/`, with a few stale flat
`Tomograms/`/`Annotations/` dirs left behind.

| tests | verdict |
|---|---|
| scanner / loader / API / frontend against grouped data | **good** — this is the real thing |
| the dual-read fallback + "leftover flat dir reads as a bogus group" | **good** — the tree has both |
| `utils/migrate_reconstruction_groups.py` itself | **poor** — almost nothing left to migrate (0 moves) |

For the migration script, use §5 instead.

---

## 1. Make the sandbox

`cp -al` hardlinks: **0 bytes of new disk**, ~12 s for this tree. The migration
only renames files and creates new ones, and rewrites `acquisition.toml` via
`os.replace` (new inode), so the original is untouched even though the clone
shares its inodes. `_sandbox/` is gitignored.

The clone **must be on the same filesystem** as the source — `/tmp` fails with
`Invalid cross-device link`.

```bash
cd /groups/cryoet/cryoet/data/scratch
rm -rf _sandbox && mkdir -p _sandbox/root _sandbox/thumbnails
cp -al data/Experimental data/MdSimulation _sandbox/root/
```

**Expected:** 9 `cannot create hard link … Operation not permitted` errors, all
in `MdSimulation/Slab/12mer_25_0.073/SyntheticCryoET/r1_frame000_a0aa` — those
files belong to another user. Harmless for §2–§4; it does mean that one
acquisition is incompletely cloned (see §5).

Confirm the clone really is free — `du` over both together dedupes hardlinks:

```bash
du -sh data _sandbox     # -> 256G  data   /   0  _sandbox
```

## 2. Scan it into a fresh DB

Three env vars drive everything. `CATALOG_THUMBNAIL_DIR` **must exist** or the
API refuses to start.

```bash
cd /groups/cryoet/cryoet/data/scratch
export CATALOG_DATA_ROOT=$PWD/_sandbox/root
export CATALOG_DB_URL=sqlite:///$PWD/_sandbox/catalog.db
export CATALOG_THUMBNAIL_DIR=$PWD/_sandbox/thumbnails

pixi run -e catalog scan "$CATALOG_DATA_ROOT" --init --force
```

`--init` runs `alembic upgrade head`, which is what applies migration
`a1b2c3d4e5f6` (new `reconstruction_alignments` table + the widened leaf PKs).
`--force` bypasses mtime gating so a re-run actually re-reads.

**Expected:** `upserted=6, skipped=0, healed=0, issues=43, errors=0` in ~45 s.

```bash
python - <<'PY'
import sqlite3
c = sqlite3.connect("_sandbox/catalog.db")
q = lambda s: c.execute(s).fetchone()[0]
for t in ("samples", "acquisitions", "reconstruction_alignments",
          "raw_tomograms", "post_processed_tomograms", "annotations"):
    print(f"{t:28} {q(f'select count(*) from {t}')}")
PY
```

**Expected:** 6 / 40 / **70 groups** / 5 raw / 97 post / 15 annotations. If
`reconstruction_alignments` is 0 you are on old code or the alembic step didn't
run.

## 3. Check the warnings

```bash
python - <<'PY'
import sqlite3
for cat, n in sqlite3.connect("_sandbox/catalog.db").execute(
        "select category, count(*) from issues where resolved_at is null "
        "group by category order by 2 desc"):
    print(f"{n:4}  {cat}")
PY
```

**Expected top rows:** 13 `undeclared_tilt_series_folder`, 12
`undeclared_tomogram_folder`, **6 `undeclared_reconstruction_alignment_folder`**,
6 `acquisition_without_tilt_series`, 4 `undeclared_annotation_folder`.

The 6 `undeclared_reconstruction_alignment_folder` are the point of interest:
they are stale flat `Tomograms/`/`Annotations/` dirs being read as bogus empty
groups. That is the symptom the migration exists to clear (§5).

Cross-check the loader agrees with the scanner:

```bash
pixi run validate _sandbox/root/Experimental/gouauxlab_20241211_HippWaffle
```

## 4. Serve it

The API mounts its routers at `/samples`, `/tomograms`, … — the `/api` prefix is
added by nginx in prod and by the Vite dev proxy locally. Curling the API
directly means **no `/api`**.

```bash
# shell 1 — API on :8000 (env vars from §2 must be exported here)
pixi run -e api api

# shell 2 — SSR frontend on :3000, proxies /api -> :8000
pixi run -e api frontend
```

Smoke-test the grouped payload:

```bash
curl -s "localhost:8000/samples/gouauxlab_20241211_HippWaffle" | python -c "
import json,sys
d=json.load(sys.stdin)
a=[x for x in d['acquisitions'] if x['reconstruction_alignment']][0]
print('acquisition:', a['acquisition_id'])
print('groups:     ', [g['reconstruction_alignment_id'] for g in a['reconstruction_alignment']])
print('annotations:', [(t['reconstruction_alignment_id'], t['annotation_id']) for t in a['annotations']][:3])
"
```

**Expected:**

```
acquisition: HippWaffle_49
groups:      ['activezone_1', 'bounding_boxes', 'bp_3dctf_bin4', 'bp_3dctf_bin4_ddw', 'membrain_seg_v10']
annotations: [('activezone_1', 'active_zonogram_0'), ('activezone_1', 'active_zonogram_0_annotated'), ('activezone_1', 'activezone_1')]
```

Then click through at `http://localhost:3000`:

- **Acquisition detail** → tomogram rows carry a group; expand one and the
  annotations panel lists **only that group's** annotations, not the
  acquisition's whole list. `HippWaffle_49` has 5 groups, so this is visible.
- **A preview thumbnail** — the URL now has the group segment
  (`/api/tomograms/{sample}/{acq}/{group}/{tomogram}/preview.png`); a 404 here
  means the group isn't being threaded through.
- **View in Neuroglancer** on a tomogram and on an annotation.
- **Manage → Author metadata → Reconstruction tab.** Pick a group in the
  selector; the form reloads and **repeatable rows reset** (they must not bleed
  between groups). Then use "Load from portal by id" with a *different* group id
  and confirm the selector and the placement hint both follow it — that pair
  disagreeing is the §5.2 remount bug.
- **Manage → Data organization** — trees show
  `Reconstructions/{reconstruction_alignment_id}/`.

## 5. Testing the migration script

`scratch/data` is already migrated, so it exercises almost nothing (`Applied 0
move(s)`). For a real test clone a slice of the production tree, which is still
in the old layout:

```bash
cd /groups/cryoet/cryoet/data/scratch
rm -rf _sandbox/mig && mkdir -p _sandbox/mig/Experimental
cp -al /groups/cryoet/cryoet/data/Experimental/gouauxlab_20241206_AMmilled24-3 \
       _sandbox/mig/Experimental/

python utils/migrate_reconstruction_groups.py --root $PWD/_sandbox/mig          # dry run
python utils/migrate_reconstruction_groups.py --root $PWD/_sandbox/mig --apply
```

Watch for `contents do not collapse onto '<id>' … becomes N entities: …` — those
folders keep their filenames and **the ids change**. Then scan the migrated
slice and confirm the ids in the DB match what the note predicted.

> **Note on ownership.** `cp -al` refuses on files owned by another user
> (`Operation not permitted`, §1). Those files are absent from the clone, so the
> migration under-reports. The real run doesn't need to own the files — `rename`
> needs write on the *directory* — but confirm write access across all lab dirs
> before the production run, because the script isolates failures per
> acquisition (`apply failed … may be partially migrated`).

## 6. Full check before merging

```bash
cd /groups/cryoet/cryoet/data/scratch
pixi run -e api test                 # 750 passed
pixi run sync                        # must leave the tree clean
pixi run gen-frontend-types          # must leave the tree clean
cd frontend && npm test && npm run build
```

`gen-frontend-types` leaving the tree dirty means the committed `openapi.json` /
`types.gen.ts` are stale — regenerate and amend. `npm run build` runs
`tsc --noEmit`, which is what catches a frontend type that drifted.

## 7. Tear down

```bash
cd /groups/cryoet/cryoet/data/scratch
rm -rf _sandbox
```

Only hardlinks and a throwaway SQLite file — nothing in `scratch/data` or
`/groups/cryoet/cryoet/data` is touched.

---

## Known gaps this does NOT cover

- **Cluster wiring** — PVCs, the nginx Neuroglancer path proxying, the CronJob's
  `scan --init`. No staging overlay exists; `DEPLOYMENT.md` sketches how to add
  one.
- **The 4 loose `.star` files.** After migrating the sandbox, 4 of the 5
  remaining `undeclared_reconstruction_alignment_folder` warnings are caused by
  a single loose `.star` sitting directly under `Annotations/` with no `{id}/`
  folder. They are the last thing keeping a flat dir alive:
  `rosenlab_1210_example30bp_PORTAL_V2/{s200,s206,s208,s211}`.
- **Production-scale migration.** See the dry-run figures in
  `reconstruction-migration-review.md` (untracked, repo root).
