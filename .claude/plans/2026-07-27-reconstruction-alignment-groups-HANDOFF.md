# Handoff: Reconstructions grouped by 3D alignment group

**Date:** 2026-07-27
**Status:** retry brief — a first attempt exists and works; this is a plan to redo it cleanly.
**Baseline for the retry:** `main`
**Reference implementation:** branch `reconstructions-tilt-series-layout` (57 commits, working, merged nowhere)

> **Progress (2026-07-27):** Step 0 (§6.1) is **done** on branch `feat/openapi-ts-codegen`
> (one commit, `14a095c`, off `6152dab`). Merge it, then start step 1 off the updated `main`.
>
> **Heads-up for step 1+:** the reference branch forked at `15ab167`, which is **13 commits
> behind** today's `main`. `main` has since changed `discovery.py`, `persistence.py`,
> `loader.py`, `state.py`, `imaging/_mrc.py`, and **added `src/schema/layout.py`** — a file
> the old branch also adds. `git checkout reconstructions-tilt-series-layout -- <path>` will
> silently revert those fixes. Port by reading the old branch, not by checking files out of it.

---

## 0. Read this first

There is a **completed, working, tested implementation** of this change on the branch
`reconstructions-tilt-series-layout`. It is not being merged because it grew to 57
commits and ~15k added lines by pivoting mid-flight and rediscovering its own
consequences one review cycle at a time. Your job is to land the *same end state* in
a straight line.

**Do not start from the old plan doc.** `.claude/plans/2026-07-10-reconstructions-process-id-layout-design.md`
describes a *different, abandoned* design (group by existing `tilt_series_id`, no
schema/DB change, `target_tomogram` retained). It was never rewritten after the pivot.
It is misleading. Ignore it.

**Do start from the finished spec.** The old branch's docs are an accurate,
reviewed statement of the target design:

```bash
git show reconstructions-tilt-series-layout:docs/data_organization.md
git show reconstructions-tilt-series-layout:docs/schema.md
git diff main...reconstructions-tilt-series-layout -- docs/
```

Treat those docs as the requirements. When you need to know how a tricky piece was
solved, read it off the old branch — it is a legitimate reference, and §5 below tells
you exactly which parts are worth copying.

---

## 1. The change, in one screen

Reconstruction outputs move from two flat sibling trees into **per-3D-alignment-group
folders**, each owning its own metadata file. Tomograms and annotations become **files
whose stem is their id**, not folders.

```
BEFORE (main)                             AFTER
{acq}/                                    {acq}/
  acquisition.toml   <- params +            acquisition.toml   <- params + [[tilt_series]] only
                        processing log      Reconstructions/
  Reconstructions/                            {reconstruction_alignment_id}/
    Tomograms/                                  reconstruction.toml  <- alignment params
      {tomogram_id}/*.mrc *.zarr                                        + processing log
    Annotations/                                Tomograms/
      {annotation_id}/*.star *.mrc                {tomogram_id}.mrc  {tomogram_id}.zarr
                                                Annotations/
                                                  {annotation_id}.star
                                                Alignment/           <- may be empty
                                                  alignment.json
```

Simulation arm is identical (`MdSimulation/*/SyntheticCryoET/{acq}/Reconstructions/{group}/...`).
Both arms share one layout — there is **no per-arm branch** in the final design. (The
abandoned plan had one; don't build it.)

### Identity rules

| id | Comes from | Notes |
|---|---|---|
| `reconstruction_alignment_id` | the `Reconstructions/{id}/` **folder name** | **never authored** — the loader injects it from the path and overwrites any authored `id`. Independent of `tilt_series_id`; does *not* have to match one. |
| `tomogram_id` | the **file stem** under that group's `Tomograms/` | `foo.mrc` + `foo.ome.zarr` = **one** tomogram `foo` |
| `annotation_id` | the **file stem** under that group's `Annotations/` | |

Stems are computed by stripping a multi-suffix zarr extension
(`discovery.ZARR_DIR_SUFFIXES = (".zarr", ".ome.zarr")`) **or** the single final
suffix — *not* `Path.stem`, which leaves `foo.ome.zarr` as `foo.ome` and splits it
from `foo.mrc`. Only allowlisted extensions group as entities (`.mrc`/`.zarr`/`.ome.zarr`
for tomograms; `discovery.ANNOTATION_FILE_EXTENSIONS` for annotations) so `.gitkeep`
and strays are ignored.

### Schema/model consequences

- `AcquisitionFile.raw_tomogram` becomes a **list** (`RawTomogram | None` → `list[RawTomogram]`).
- New `ReconstructionAlignment` model: PK `(sample_id, acquisition_id, reconstruction_alignment_id)`,
  fields `alignment_software`, `alignment_method`, `alignment_files`, `mtime`,
  `renamed_from`; `reconstruction_alignment_id` uses `alias="id"`.
- New `ReconstructionFile` model = parsed contents of one `reconstruction.toml`:
  one `[reconstruction_alignment]` table + `[[raw_tomogram]]` + `[[post_processed_tomogram]]`
  + `[[annotation]]` lists.
- Tomogram `tilt_series_id` field is **removed**. Tilt-series lineage moves to
  `RawTomogram.derived_from`, which becomes **`IdStr | None` (text)** naming a
  `[[tilt_series]]` id in the acquisition's `acquisition.toml`.
  `PostProcessedTomogram.derived_from` stays `list[IdStr]` (tomogram ids, resolvable
  across sibling groups' `reconstruction.toml` files).
- `Annotation.target_tomogram` is **deleted**. An annotation belongs to the whole
  group; the link is structural, not authored.
- Tomogram and annotation leaves carry `reconstruction_alignment_id` (`None` for
  legacy blocks authored flat in `acquisition.toml`).
- Id-uniqueness validation is **scoped per group**: two groups in one acquisition may
  each hold `denoised.mrc`.

### DB consequences

- New `reconstruction_alignment` table.
- `raw_tomograms`, `post_processed_tomograms`, `annotations` PKs widen to include
  `reconstruction_alignment_id`.
- API tomogram/annotation URLs and preview/neuroglancer routes get scoped by group.
- Frontend annotations/tomograms table gets scoped to the row's group.

### Dual-read / deprecation

The loader and scanner read `Reconstructions/{group}/reconstruction.toml` when
present. If a group folder has none, they fall back to that group's processing-log
blocks still embedded in `acquisition.toml` and emit a **deprecation warning**. A
hand-authored `reconstruction_alignment_id` on a flat `acquisition.toml` block is
**dropped before validation** (shared helper, used by both the loader and the
authoring API so they cannot drift).

### Authoring UI

New `reconstruction.toml` form: registered in the field registry as four sections;
a group selector at the top (`New group…` first, then every existing group in the
acquisition); `raw_tomogram.derived_from` is a dropdown fed by a new endpoint
returning the acquisition's tilt-series ids; a placement-hint showing
`{sample}/{acq}/Reconstructions/{group}/reconstruction.toml`. The form **downloads**
the file; the portal never writes to the data root. The group id is collected for
the hint and **dropped from the emitted TOML**.

---

## 2. Ground rules for this retry

1. **The design is settled. Do not re-explore it.** No brainstorming pass, no
   design-alternatives pass. The docs on the old branch are the spec.
2. **The DB PK widening is step 1 of the risk register, not a discovered
   consequence.** Read §5.1 before writing any persistence code.
3. **One migration script, one layout.** The old branch shipped two (`utils/reorg_reconstructions.py`
   for the abandoned tilt-series layout, then `migrate_reconstructions_3d_alignment.py`
   at the repo root for the pivot — ~1080 lines of one-shot code). Write one, in
   `utils/`, following `utils/reorg_facility_to_portal.py` style: dry-run by default,
   `--apply` to move, idempotent, warn-and-skip rather than guess.
4. **Land the OpenAPI→TypeScript codegen on its own branch FIRST, before starting
   this work.** It rode along inside the last attempt and contributed ~6600 lines of
   generated diff to a review that was about something else. It is independent of every
   schema change here, so it goes first as its own PR — then step 5 of this plan
   *regenerates* `frontend/src/types.ts` instead of hand-editing it. **§6.1 has the
   file list, the extraction command, and the two design points to preserve. Do that
   branch before step 1.**
5. **Also out of scope, do not bundle:** `repopulate_test_data.sh`.
6. **Aim for ~7 commits.** Each one green on its own. If a commit needs a second
   commit to fix a consequence you could have named up front, that's the failure mode
   this handoff exists to prevent.

---

## 3. Step plan

**Step 0 is a separate branch and must land first — see §6.1.** After that, each step
below is one commit on the reconstruction branch. Steps 3 and 4 are the ones that bite.

**0. (separate branch, prerequisite) `feat(frontend)` — OpenAPI→TS codegen.**
Lift `src/catalog/api/generate_openapi.py`, `frontend/openapi.json`,
`frontend/src/types.gen.ts`, the rewritten `frontend/src/types.ts`, and the
`package.json` / `pyproject.toml` wiring off the old branch. Its own PR, merged before
step 1. Everything downstream assumes `pixi run gen-frontend-types` exists.

**1. `feat(schema)` — models.**
`src/schema/schema.py`: add `ReconstructionAlignment` + `ReconstructionFile`; make
`raw_tomogram` a list; drop tomogram `tilt_series_id`; retype
`RawTomogram.derived_from` to text; delete `Annotation.target_tomogram`; add
`reconstruction_alignment_id` to the leaves; scope id-uniqueness per group; declare
`reconstructions: dict[str, dict[str, ReconstructionFile]]` on the sample record.
Regenerate `src/schema/*.schema.json`. Reclassify (don't delete) form fields in
`src/schema/form_fields.py` — deleting a `FormField` leaves the model field
unclassified and fails `tests/test_form_fields_drift.py`.

**2. `feat(discovery+loader)` — read the new layout.**
`src/catalog/discovery.py`: shared stem helper; `iter_reconstruction_alignments`;
`iter_tomograms`/`iter_annotations` walk `Reconstructions/{group}/{Tomograms,Annotations}/`
and carry the group; `parse_targets_for_sample` points at the new file locations;
**delete the dead `SyntheticCryoET/` tomogram fallback** (no real data uses it; only
`test_validate_sample.py` did).
`src/schema/loader.py`: parse `reconstruction.toml`; inject the group id from the
folder; drop authored group ids; dual-read fallback + deprecation warning; switch
`_has_matching_folder`/`_candidate_folder_names` from "a dir named `{id}`" to "a file
stem `{id}`"; resolve `derived_from` across `acquisition.toml` + sibling
`reconstruction.toml` files (dangling → warn, never fail the group).

**3. `feat(orm+migration+persistence)` — the PK widening. One commit.**
`src/catalog/orm.py` + one alembic migration + `src/catalog/persistence.py`.
The keep-sets and `GuardedChild.pk_cols` **must move together in one commit** — a
mismatch classifies every live row as stale and prunes the table. Read §5.1 for the
four §08c traps; solve them here, up front, not in review.

**4. `feat(assembler)` — stamp the group.**
Scope tomogram-id matching to the containing group; stamp the enclosing folder onto
each leaf; **deep-copy legacy `acquisition.toml` blocks per group** (two groups must
not share one Pydantic instance, or the second group's MRC header overwrites the
first's); delete the now-obsolete `duplicate_tomogram_id`/`duplicate_annotation_id`
guards (they existed only because storage couldn't represent two groups sharing a
stem).

**5. `feat(api+frontend)` — scope by group.**
`routes/{tomograms,annotations,samples}.py`: group-scoped URLs and lookups —
**keyword-call** the group and leaf args (four same-typed positionals made a
transposition a silent 404 last time). `routes/toml_authoring.py`: register
`ReconstructionFile` in `_MODELS`; group-ids endpoint; tilt-series-ids endpoint;
`_COMPOSITE_DROP` must resolve the **pydantic alias** for dropped fields (the group
id aliases to `"id"`, so popping by field name is a silent no-op); dedupe the
acquisition-form load by **casefolded** leaf id, first group wins. Frontend: scope
the annotations panel to the row's group; new reconstruction form + group selector —
see §5.2 for the remount trap.

**Regenerate the frontend types, don't hand-edit them** (step 0 landed the codegen):
after the `schemas.py` / route changes, run `pixi run gen-frontend-types` and commit
the updated `frontend/openapi.json` + `frontend/src/types.gen.ts` alongside. Only two
kinds of edit to `frontend/src/types.ts` are still by hand — a new stable-named
re-export, and re-narrowing a backend `str` field to a literal union (see §6.1). If a
type looks wrong, fix `schemas.py` and regenerate; don't patch the generated file.

**6. `feat(templates+migration)` — disk.**
Template skeletons for both arms; `templates/reconstruction.toml` with a `#:schema`
directive; one migration script in `utils/` + its self-check test.

**7. `docs`** — port `docs/data_organization.md` and `docs/schema.md` from the old
branch (they're already written and reviewed).

---

## 4. Verification

```bash
pixi run test                       # python
pixi run gen-frontend-types         # then confirm the diff is committed, not dirty
cd frontend && npm test && npm run build
pixi run validate <sample_dir>      # loader path agrees with the scanner
```

`gen-frontend-types` leaving a dirty tree means the committed `openapi.json` /
`types.gen.ts` are stale against `schemas.py` — regenerate and amend. `npm run build`
runs `tsc --noEmit`, which is what actually catches a frontend type that drifted from
the regenerated schema.

Non-negotiable new tests (each one pins a bug that actually shipped and had to be
fixed on the old branch):

- **PK column order after `alembic upgrade head`** for all three retyped tables,
  expected order taken from `inspect(cls).primary_key`. `compare_metadata` ignores
  `PrimaryKeyConstraint` and every other test builds via `create_all`, so the
  migration's PK order is otherwise exercised **nowhere** — and a transposed
  group/leaf column is a silent-prune bug.
- **Prune determinism under group-scoped renames**, both through the
  `reconstruction.toml` path and the legacy flat path. Include the case that requires
  deferred resolution: a same-stem third-group row that is pre-existing *and* kept
  (invisible to an in-loop resolver's half-built keep-set).
- **Stem grouping**: `foo.mrc` + `foo.ome.zarr` collapse to one entity; `.gitkeep`
  ignored; the same stem in two groups yields two distinct rows.
- **Authoring**: a group switch resets repeatable rows, not just scalars; the
  selector and the placement hint name the same group after a load-by-id.

---

## 5. The five traps that cost the last attempt

These are the specific problems that turned 7 commits into 57. Each is stated as the
bug plus the resolution the old branch converged on.

### 5.1 §08c rename/prune interaction with the widened PK

Four of the old branch's last five commits are persistence fixes here. All four are
consequences of `reconstruction_alignment_id` entering the leaf PKs. Solve them in
step 3.

- **Keep-sets and `pk_cols` must widen in the same commit.** A mismatch classifies
  every live row as stale.
- **`exempt_ids` must be keyed on the old row's PK below the sample**, not on bare
  leaf ids: `(acquisition, group, leaf)` for the group-scoped leaves,
  `(acquisition, leaf)` otherwise. With bare ids, a `renamed_from` on stem X anywhere
  in the sample also exempts a genuinely deleted X in another group or another
  acquisition — those deletions vanish from the §08a audit feed and contribute
  nothing to the §08b prune floor. Read the filter back as
  `tuple(getattr(row, c) for c in pk_cols[1:])` so write and read sites can't drift
  in arity or order.
- **`_record_leaf_rename` must find the old row anywhere in the acquisition**, not
  just in the fresh row's group. Probing `session.get(..., <fresh row's group>, old_id)`
  means a rename that moved a file between groups finds nothing, reads as "already
  recorded", logs no rename event, and still suppresses the deletion. Prefer the
  fresh row's own group; believe a cross-group match only when exactly one other
  group holds the id; record both groups in the event when they differ.
- **Resolve leaf rename hints *after* the merge loop, against the finished
  keep-set.** Running the lookup per-leaf inside the loop autoflushes, so the
  candidate list is "whichever fresh rows happened to merge already" — stale `grp_a/x`
  + fresh `grp_b/y` (`renamed_from: x`) + genuinely new `grp_c/x` produces a rename
  event or a deletion event depending purely on group iteration order. Candidates
  must be restricted to rows the scan is *not* keeping (a row being re-merged is
  alive, so it can't be a rename source), which needs the complete keep-set. Collect
  hints during the loop, resolve immediately after it, still before the Step 8 stale
  sweep.
- **Note on the floor invariant:** exemption is *not* "equal or stricter". Resolving
  a cross-group hint that previously fell back to an unresolvable key now matches a
  real row in `to_delete`, dropping the ratio's numerator — a scan that would have
  raised `ChildPruneSafetyFloorExceeded` can now proceed. That is intended (a
  resolved rename is not a deletion); just don't write the false invariant next to
  the delete path.

### 5.2 The authoring form's remount key

Keying the reconstruction form child on `group` makes every load-by-id a **remount**,
and a remount re-initialises the editable Sample/Acquisition id fields from the route
props and re-fetches with those — while `handleLoad` fetched with the editable state.
From a bare `/author` tab both route props are `undefined`, so a successful load is
immediately followed by a 422 that blanks the form and wipes the context the user just
typed. On a deep link with an edited acquisition id it silently reverts to the route
acquisition.

Resolution: `group` is **only the selector's display value**; a separate counter is
the remount key, and only the selector bumps it. `initialId` is a mount-time seed.
Also: MUI's `SelectInput` skips `onChange` when the clicked value equals the current
one, so a stale selector makes clicking the deep-linked group a dead end — `seed()`
must report the id it actually loaded and the parent must set `group` to it.
Make the test's load mock key fixtures by **acquisition as well as group** and 422 on
a miss, so a fetch with the wrong context fails the test instead of quietly returning
the right body.

### 5.3 Two groups, one stem, one flat form

`GET /toml/acquisition/load` returns one block per `(group, stem)` row, so two groups
each holding a `denoised.mrc` produce two byte-identical blocks the flat acquisition
form cannot tell apart (`reconstruction_alignment_id` isn't authored, so the
distinguishing field is unrenderable) — and `POST /toml/acquisition` then rejects
them as a duplicate id with no way for the user to fix the form.

Resolution: dedupe by leaf id on load, first group wins (deterministic — queries order
by group then id), **casefolded** (the duplicate validator casefolds, so `denoised`
and `Denoised` otherwise both survive and still 422), with a **shared seen set across
raw and post-processed** (schema.py validates them as one id namespace). Log dropped
duplicates; don't try to signal them in the payload.

### 5.4 Warning messages must name the right file

The undeclared-tomogram/annotation warnings told researchers to add a flat
`acquisition.toml` block even when the stem's group already had a `reconstruction.toml`
— misleading precisely when they'd done the right thing. Branch the message on whether
the group is per-group authored; name the correct file and the stale flat block. Don't
add a new warning category.

### 5.5 Loader warnings need a scanner category

Loader-side derivation notes with no matching case in
`_categorize_loader_warning` fall through to a spurious `extra_field/<unknown>`
alongside the assembler's own correct warning. Either give them a category or skip
them in the forwarding loop with a predicate narrow enough to leave sibling warnings
untouched.

---

## 6. Out of scope

- No change to `TiltSeries/`, `Frames/`, `Gains/`, `MdRuns/`, or the simulation
  `GroundTruth/` tree.
- No `Alignments/` tree at the acquisition level — the 2026-06-18 decision to fold
  tilt-series alignment into `TiltSeries/{id}/alignment/` stands. The new
  `Alignment/` folder is *inside* a reconstruction group and holds 3D alignment
  metadata only.
- The OpenAPI/TS codegen switch is **not out of scope — it is a prerequisite on its own
  branch**, landed before step 1. See §6.1.
- No `repopulate_test_data.sh` (a convenience wrapper for wiping and rescanning the
  test data root; useful, unrelated, ~50 lines — lift it separately if wanted).

### 6.1 Step 0: the OpenAPI codegen switch — its own branch, landed first

This is a **complete and worthwhile change that has nothing to do with reconstruction
groups**. It replaces the hand-maintained `frontend/src/types.ts` with types generated
from the FastAPI app's own OpenAPI schema. Do it **first, as its own PR**: the
reconstruction branch then stops carrying ~6600 lines of generated diff, this change
gets reviewed on its own merits, and step 5 regenerates types instead of hand-editing
them.

Files (all from `reconstructions-tilt-series-layout`):

| File | What |
|---|---|
| `src/catalog/api/generate_openapi.py` | new, ~30 lines: `create_app().openapi()` → `frontend/openapi.json` |
| `frontend/openapi.json` | generated, ~4250 lines — committed artifact |
| `frontend/src/types.gen.ts` | generated by `openapi-typescript`, ~2350 lines |
| `frontend/src/types.ts` | rewritten 393 → 158 lines: thin re-exports over `types.gen.ts` |
| `frontend/package.json` | adds `openapi-typescript` devDep, a `gen:types` script, and a `typescript` override to pin the peer |
| `pyproject.toml` | adds pixi tasks `openapi-schema` and `gen-frontend-types` |

Two design points to preserve when extracting — they're the reason this isn't a
mechanical find-and-replace:

- **`types.ts` stays.** It becomes a narrowing layer, not dead weight. It holds a
  `Defined<T>` mapped type that restores the old hand-written contract (every declared
  response field present at every nesting level, only the *value* nullable). This is
  needed because FastAPI always serializes fields with defaults, but the JSON Schema
  permits omitting them, so `openapi-typescript` marks every one `?:` recursively —
  without `Defined<T>` the whole frontend needs `| undefined` handling.
- **Enum-ish fields are re-narrowed by hand.** Several backend fields are `str`, not a
  Python `Enum`, so the generator widens them to `string`. `types.ts` narrows them back
  to literal unions where the frontend depends on it (dropdown options, exhaustive
  display maps). The backend does not enforce those lists, so keeping a new backend
  value in sync remains a **manual step** — say so in the branch's commit message.

Extraction: branch off `main`, then
`git checkout reconstructions-tilt-series-layout -- <the six paths above>`, then
`npm install` in `frontend/` to pick up the new devDep and lockfile. Verify with
`pixi run gen-frontend-types` (tree stays clean — the committed artifacts match a fresh
generation), `cd frontend && npm test && npm run build`, and `pixi run test`. It touches
no schema, no ORM, and no route logic, so it is independent of everything in §3 and
reviews as a self-contained change.

Merge this before starting step 1. Everything downstream assumes
`pixi run gen-frontend-types` exists and that `types.ts` is a narrowing layer over
generated types rather than a hand-maintained file.

---

## 7. If you get stuck

The old branch is a working implementation of everything above:

```bash
git log --oneline main..reconstructions-tilt-series-layout
git show reconstructions-tilt-series-layout:<path>
git diff main...reconstructions-tilt-series-layout -- <path>
```

Its commit *messages* are unusually detailed and often explain the reasoning behind
a non-obvious choice better than the code does — `git log main..reconstructions-tilt-series-layout --format='%h %s%n%b' -- <path>`
is worth reading before you reimplement any file it touched. Reuse freely; the point
of the retry is a smaller, straighter history, not different code.
