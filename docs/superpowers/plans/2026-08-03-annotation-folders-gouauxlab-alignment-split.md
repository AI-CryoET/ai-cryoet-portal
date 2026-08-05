# Annotation id-folders + gouauxlab alignment split — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the `Reconstructions/` migration from flattening multi-file annotations (preserve them as `Annotations/{id}/` folders), split gouauxlab acquisitions into per-alignment groups (`cryosnail_az{N}` / `warp` / `best_alignment`), and keep nested tomogram variant filenames intact.

**Architecture:** Three coupled surfaces. (1) The standalone migration script `utils/migrate_reconstruction_groups.py` gains a folder-preserve planner for annotations, a gouauxlab marker→group path, and a nested-subdir naming fix. (2) The scanner `catalog.discovery.iter_annotations` learns to read an annotation subfolder as one entity. (3) The validate-CLI reader `schema.layout.entity_ids_in_dir` learns to count a plain subdir as an annotation id. Tomogram behavior is unchanged except nested-variant filenames.

**Tech Stack:** Python 3, pytest (`pythonpath=src`, `testpaths=tests`). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-03-annotation-folders-gouauxlab-alignment-split-design.md`

## Global Constraints

- The migration script is **standalone** (no `src/` import) and carries its own copies of `TOMOGRAM_FILE_EXTENSIONS` / `ANNOTATION_FILE_EXTENSIONS`. They MUST stay equal to `schema.layout`'s copies — `tests/test_migrate_reconstruction_groups.py::test_allowlists_match_the_schema` pins this. Do not diverge them.
- `ANNOTATION_FILE_EXTENSIONS = {".star", ".mrc", ".png", ".tiff", ".tif", ".csv", ".json", ".npy"}`; `TOMOGRAM_FILE_EXTENSIONS = {".mrc"}`.
- Junk allowlist `IGNORED_JUNK = {".DS_Store", "Thumbs.db", ".gitkeep"}` must not count toward the single-vs-multi decision.
- An annotation id is **always its folder name** (single-file → bare `{id}.ext`, multi-file → folder `{id}/`). Annotation blocks never split.
- gouauxlab group names: numbered → `cryosnail_az{N}` (literal N), `_warp` → `warp`, `_best_alignment` → `best_alignment`. Group is set by the alignment marker, not the `activezone_M` index. Relocate, do not rename folders.
- Run tests from the repo root with `python -m pytest`.

---

### Task 1: Part C — nested tomogram variant filenames

Nested variant subdirs (`ctf/`, `even/`, `odd/`, `gaussian/`) inside a tomogram folder currently collapse to the subfolder name (`ctf/s207_8.00Apx.mrc` → `ctf.mrc`), discarding the original filename. Prepend the subfolder name to the original filename instead. One-line change in `_expand_entity_folder`'s subdir branch; both `plan_reconstructions` and `_plan_folder_as_group` call it, so it applies everywhere tomograms flatten.

**Files:**
- Modify: `utils/migrate_reconstruction_groups.py` (`_expand_entity_folder`, ~line 198)
- Test: `tests/test_migrate_reconstruction_groups.py`

**Interfaces:**
- Consumes: existing `_expand_entity_folder(id_dir, allowed_exts, dest_dir, prepend_folder=False)`.
- Produces: same signature; nested-subdir destination becomes `{prefix}{sub.name}_{entry.name}`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_migrate_reconstruction_groups.py` (uses the existing 2-tilt-series folder-as-group path so the folder routes through `_expand_entity_folder`):

```python
def test_nested_variant_subdir_prepends_folder_to_filename(tmp_path, capsys):
    """A nested variant subdir keeps the original filename, prefixed with the
    subfolder name: ctf/inner.mrc -> ctf_inner.mrc (not ctf.mrc)."""
    acq_toml = _ACQ_TOML.replace(
        '[[tilt_series]]\nid = "ts_1"\nis_aligned = true\n',
        '[[tilt_series]]\nid = "ts_1"\n\n[[tilt_series]]\nid = "ts_2"\n',
    )
    acq = _make_acq(tmp_path, acq_toml=acq_toml)  # 2 tilt series -> folder-as-group
    ctf = acq / "Reconstructions" / "Tomograms" / "bp_3dctf_bin4" / "ctf"
    ctf.mkdir(parents=True)
    (ctf / "s207_8.00Apx.mrc").write_bytes(b"ctf")
    _run(tmp_path, apply=True)
    tomos = acq / "Reconstructions" / "bp_3dctf_bin4" / "Tomograms"
    assert (tomos / "ctf_s207_8.00Apx.mrc").read_bytes() == b"ctf"
    assert not (tomos / "ctf.mrc").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_migrate_reconstruction_groups.py::test_nested_variant_subdir_prepends_folder_to_filename -v`
Expected: FAIL — file lands at `ctf.mrc`, assertion on `ctf_s207_8.00Apx.mrc` fails.

- [ ] **Step 3: Make the change**

In `_expand_entity_folder`, the subdir loop currently ends with:

```python
        (ext, entry), = by_ext.items()
        moves.append((entry, dest_dir / f"{prefix}{sub.name}{ext}"))
```

Change the destination to keep the original filename:

```python
        (ext, entry), = by_ext.items()
        # Keep the original filename, prefixed with the variant subfolder name
        # (ctf/s207_8.00Apx.mrc -> ctf_s207_8.00Apx.mrc), so provenance survives
        # the collapse. entry.name already carries the extension.
        moves.append((entry, dest_dir / f"{prefix}{sub.name}_{entry.name}"))
```

Update the function's docstring line describing subfolder collapse to match (`-> {sub.name}_{filename}`).

- [ ] **Step 4: Run the test + the full migration suite**

Run: `python -m pytest tests/test_migrate_reconstruction_groups.py -v`
Expected: PASS (new test green; existing tests unaffected — none use nested subdirs).

- [ ] **Step 5: Commit**

```bash
git add utils/migrate_reconstruction_groups.py tests/test_migrate_reconstruction_groups.py
git commit -m "feat(migration): keep original filename when collapsing nested tomogram variant subdirs"
```

---

### Task 2: Part A read-side — `entity_ids_in_dir` counts annotation subdirs

The validate CLI reconciles authored ids against disk via `entity_ids_in_dir`. Teach it that a plain (non-`.zarr`) subdir is one id (= folder name), gated by a flag so tomograms stay file-only.

**Files:**
- Modify: `src/schema/layout.py` (`entity_ids_in_dir`, ~line 83; `__main__` self-check, ~line 172)
- Modify: `src/schema/loader.py` (`_reconstruction_ids_on_disk` ~line 225; `_check_reconstruction_files` ~line 393)

**Interfaces:**
- Produces: `entity_ids_in_dir(directory, file_extensions, include_dirs=False) -> set[str]`. With `include_dirs=True`, a plain non-`.zarr` subdir adds `entry.name` to the ids. Tomogram callers keep the default `False`; annotation callers pass `True`.

- [ ] **Step 1: Write the failing self-check**

In `src/schema/layout.py`, extend the `__main__` block (after the existing `entity_ids_in_dir` checks) with a directory case:

```python
        # include_dirs=True: a plain subdir is ONE annotation id (folder name);
        # a .zarr dir is still grouped by stem; files still count.
        (leaf / "ann_folder").mkdir()
        (leaf / "ann_folder" / "a.png").touch()
        (leaf / "ann_folder" / "b.png").touch()
        assert entity_ids_in_dir(
            leaf, ANNOTATION_FILE_EXTENSIONS, include_dirs=True
        ) == {"a", "b", "ann_folder"}
        # default (tomogram behavior): the plain subdir is NOT counted.
        assert entity_ids_in_dir(leaf, TOMOGRAM_FILE_EXTENSIONS) == {"a", "b"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `python src/schema/layout.py`
Expected: FAIL — `entity_ids_in_dir()` got an unexpected keyword `include_dirs` (or AssertionError once the kwarg is accepted but ignored).

- [ ] **Step 3: Implement the flag**

Replace `entity_ids_in_dir` in `src/schema/layout.py`:

```python
def entity_ids_in_dir(
    directory: Path,
    file_extensions: frozenset[str],
    include_dirs: bool = False,
) -> set[str]:
    """Return entity ids (file stems) directly under ``directory``.

    A child counts when it is a file whose suffix is in ``file_extensions``
    (case-insensitive) or a ``.zarr`` / ``.ome.zarr`` store dir. With
    ``include_dirs=True`` (annotations only) a plain non-zarr subdir also counts
    as one id equal to its folder name — an annotation is one folder holding
    several files. Everything else (stray ``notes.txt`` / ``.gitkeep``) is
    ignored. A missing ``directory`` yields the empty set.
    """
    ids: set[str] = set()
    if not directory.is_dir():
        return ids
    for entry in directory.iterdir():
        if entry.is_file() and entry.suffix.lower() in file_extensions:
            ids.add(entity_id_from_path(entry))
        elif entry.is_dir() and is_zarr_dir(entry):
            ids.add(entity_id_from_path(entry))
        elif include_dirs and entry.is_dir():
            ids.add(entry.name)
    return ids
```

- [ ] **Step 4: Wire the annotation call sites in `loader.py`**

In `_reconstruction_ids_on_disk` change the update line to pass the flag for annotations:

```python
        ids.update(
            entity_ids_in_dir(
                group_dir / leaf, file_extensions, include_dirs=(leaf == "Annotations")
            )
        )
```

In `_check_reconstruction_files`, the annotation line (currently ~393):

```python
        ann_on_disk = entity_ids_in_dir(
            group_dir / "Annotations", ANNOTATION_FILE_EXTENSIONS, include_dirs=True
        )
```

Leave the `tomo_on_disk` call unchanged (default `False`).

- [ ] **Step 5: Run the self-check and the schema suite**

Run: `python src/schema/layout.py && python -m pytest tests/ -k "loader or validate or discovery or layout" -v`
Expected: PASS (self-check prints OK; loader/validate tests still green — plain-dir behavior is additive).

- [ ] **Step 6: Commit**

```bash
git add src/schema/layout.py src/schema/loader.py
git commit -m "feat(schema): count a plain annotation subdir as one entity id (include_dirs)"
```

---

### Task 3: Part A read-side — `iter_annotations` reads a subfolder as one annotation

**Files:**
- Modify: `src/catalog/discovery.py` (`iter_annotations`, ~line 357)
- Test: `tests/catalog/test_discovery.py`

**Interfaces:**
- Consumes: `AnnotationLocation(path, annotation_id, files: tuple[Path,...], reconstruction_alignment_id)` (unchanged); `is_zarr_dir`, `entity_id_from_path`, `ANNOTATION_FILE_EXTENSIONS` (already imported).
- Produces: `iter_annotations` yields one `AnnotationLocation` per plain subdir (id = folder name, `files` = allowlisted files inside, recursive) **and** per bare file/`.zarr` stem, folders first then bare stems, each sorted.

- [ ] **Step 1: Write the failing test**

Add to `tests/catalog/test_discovery.py` (near the other `iter_annotations` tests; `_acq_loc` helper already exists):

```python
def test_iter_annotations_reads_a_subfolder_as_one_annotation(tmp_path):
    anns = tmp_path / "acq" / "Reconstructions" / "cryosnail_az0" / "Annotations"
    folder = anns / "activezone_1_liza_az0"
    folder.mkdir(parents=True)
    (folder / "activezone_1.star").write_text("")
    (folder / "active_zonogram_1.png").write_bytes(b"")
    (folder / "active_zonogram_1_selected_aunps.png").write_bytes(b"")  # 2nd .png
    (anns / "membrain_seg_v10_liza_az0.mrc").write_bytes(b"")  # bare single file

    acq = _acq_loc(tmp_path / "acq")
    anns_out = list(iter_annotations(acq))
    by_id = {a.annotation_id: a for a in anns_out}
    assert set(by_id) == {"activezone_1_liza_az0", "membrain_seg_v10_liza_az0"}
    # the folder is ONE annotation holding all three files (both .png kept)
    folder_ann = by_id["activezone_1_liza_az0"]
    assert {p.name for p in folder_ann.files} == {
        "activezone_1.star",
        "active_zonogram_1.png",
        "active_zonogram_1_selected_aunps.png",
    }
    assert folder_ann.reconstruction_alignment_id == "cryosnail_az0"
    # the bare file is still a single-file annotation
    assert [p.name for p in by_id["membrain_seg_v10_liza_az0"].files] == [
        "membrain_seg_v10_liza_az0.mrc"
    ]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/catalog/test_discovery.py::test_iter_annotations_reads_a_subfolder_as_one_annotation -v`
Expected: FAIL — the current loop ignores plain subdirs, so `activezone_1_liza_az0` is missing.

- [ ] **Step 3: Rewrite `iter_annotations`**

Replace the body of `iter_annotations` in `src/catalog/discovery.py`:

```python
def iter_annotations(acq: AcquisitionLocation) -> Iterator[AnnotationLocation]:
    """Yield one AnnotationLocation per annotation under the Annotations folder(s).

    An annotation is either a plain subfolder (``Annotations/{id}/`` — id is the
    folder name, ``files`` are the allowlisted files inside it, recursively) or a
    bare file / ``.zarr`` store whose id is the stem (differently-suffixed files
    sharing a stem, ``ann.json`` + ``ann.mrc``, collapse to one). Folders are
    yielded before bare stems; both are sorted. A ``.zarr`` dir is a store, not a
    container, so it is a single-file annotation, not a folder.
    """
    for leaf_dir, group_id in _reconstruction_leaf_dirs(acq, "Annotations"):
        folders: list[Path] = []
        by_stem: dict[str, list[Path]] = {}
        for entry in leaf_dir.iterdir():
            if entry.is_dir() and not is_zarr_dir(entry):
                folders.append(entry)
            elif entry.is_file() and entry.suffix.lower() in ANNOTATION_FILE_EXTENSIONS:
                by_stem.setdefault(entity_id_from_path(entry), []).append(entry)
            elif entry.is_dir() and is_zarr_dir(entry):
                by_stem.setdefault(entity_id_from_path(entry), []).append(entry)
        for folder in sorted(folders, key=lambda p: p.name):
            files = tuple(
                sorted(
                    (
                        p
                        for p in folder.rglob("*")
                        if p.is_file() and p.suffix.lower() in ANNOTATION_FILE_EXTENSIONS
                    ),
                    key=lambda p: str(p),
                )
            )
            yield AnnotationLocation(
                path=folder,
                annotation_id=folder.name,
                files=files,
                reconstruction_alignment_id=group_id,
            )
        for stem in sorted(by_stem):
            yield AnnotationLocation(
                path=leaf_dir,
                annotation_id=stem,
                files=tuple(sorted(by_stem[stem], key=lambda p: str(p))),
                reconstruction_alignment_id=group_id,
            )
```

- [ ] **Step 4: Run the discovery suite**

Run: `python -m pytest tests/catalog/test_discovery.py -v`
Expected: PASS (new test green; existing flat-file tests still pass — bare files/zarr path unchanged).

- [ ] **Step 5: Commit**

```bash
git add src/catalog/discovery.py tests/catalog/test_discovery.py
git commit -m "feat(discovery): read an annotation subfolder as one multi-file annotation"
```

---

### Task 4: Part A migration — folder-preserve annotation planner

Replace the annotation side of all three migration paths (`plan_reconstructions`, `_plan_folder_as_group`, and thus `plan_shared_name_group`) with a folder-preserve planner: single-file → bare `{id}.ext`; multi-file → move the whole folder verbatim. Tomogram planning is untouched.

**Files:**
- Modify: `utils/migrate_reconstruction_groups.py` (add `_plan_annotation_folder`; edit `plan_reconstructions` ~line 328–364 annotation branch; edit `_plan_folder_as_group` ~line 234–244)
- Test: `tests/test_migrate_reconstruction_groups.py`

**Interfaces:**
- Consumes: `_ext_of`, `_is_leaf`, `IGNORED_JUNK`, `ANNOTATION_FILE_EXTENSIONS`.
- Produces: `_plan_annotation_folder(id_dir: Path, dest_dir: Path) -> list[tuple[Path, Path]]` — moves for one `Annotations/{id}/` folder. Single allowlisted leaf, no non-junk subdirs → `[(leaf, dest_dir / f"{id_dir.name}{ext}")]`; otherwise `[(id_dir, dest_dir / id_dir.name)]` (whole-dir move). The resulting new id (via `_stem_of(dest)`) equals `id_dir.name` in both cases, so `main()`'s rename bookkeeping maps the annotation block id to itself (identity, no split) with no change.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_migrate_reconstruction_groups.py`:

```python
def test_multi_file_annotation_folder_is_preserved(tmp_path):
    """An annotation of several files (two sharing an extension) keeps its folder;
    the id is the folder name and every file survives."""
    acq = _make_acq(tmp_path)
    az = acq / "Reconstructions" / "Annotations" / "activezone_0_liza_az0"
    az.mkdir(parents=True)
    (az / "activezone_0.star").write_text("s")
    (az / "active_zonogram_0.png").write_bytes(b"p1")
    (az / "active_zonogram_0_selected_aunps.png").write_bytes(b"p2")  # 2nd .png
    _run(tmp_path, apply=True)

    dest = acq / "Reconstructions" / "ts_1" / "Annotations" / "activezone_0_liza_az0"
    assert dest.is_dir()
    assert {p.name for p in dest.iterdir()} == {
        "activezone_0.star",
        "active_zonogram_0.png",
        "active_zonogram_0_selected_aunps.png",
    }
    # the single-file membrain annotation still collapses to a bare file
    assert (
        acq / "Reconstructions" / "ts_1" / "Annotations" / "membrain_seg_v10.mrc"
    ).is_file()
    assert not (acq / "Reconstructions" / "Annotations").exists()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_migrate_reconstruction_groups.py::test_multi_file_annotation_folder_is_preserved -v`
Expected: FAIL — the current code splits the folder into separate entities / drops a `.png`.

- [ ] **Step 3: Add `_plan_annotation_folder`**

Add near `_expand_entity_folder` in `utils/migrate_reconstruction_groups.py`:

```python
def _plan_annotation_folder(id_dir: Path, dest_dir: Path) -> list[tuple[Path, Path]]:
    """Folder-preserve planner for ONE Annotations/{id}/ folder.

    A single allowlisted leaf with no non-junk subdirs collapses to a bare
    ``dest_dir/{id}.ext`` (the mixed single-file rule). Otherwise the WHOLE
    folder is relocated verbatim to ``dest_dir/{id}/`` — the annotation's files
    (same-extension pairs, sidecars, nested content, junk) stay together and the
    id is the folder name. Relocate, never rename or split.
    """
    entries = [e for e in id_dir.iterdir() if e.name not in IGNORED_JUNK]
    leaves = [e for e in entries if _is_leaf(e, ANNOTATION_FILE_EXTENSIONS)]
    subdirs = [
        e for e in entries if e.is_dir() and not _is_leaf(e, ANNOTATION_FILE_EXTENSIONS)
    ]
    if len(leaves) == 1 and not subdirs:
        return [(leaves[0], dest_dir / f"{id_dir.name}{_ext_of(leaves[0])}")]
    return [(id_dir, dest_dir / id_dir.name)]
```

- [ ] **Step 4: Reroute `plan_reconstructions`**

In `plan_reconstructions`, the per-`id_dir` loop currently branches on `_entity_files` for both kinds. Route annotations to the new planner before the tomogram logic. Replace the body of the `for id_dir in ...` loop's tail (after the `group_dir is None` guard) with:

```python
            if kind == "Annotations":
                moves += _plan_annotation_folder(id_dir, group_dir / kind)
                continue

            by_ext, _collision = _entity_files(id_dir, allowed_exts)
            if by_ext is None:
                expanded, expand_warnings = _expand_entity_folder(
                    id_dir, allowed_exts, group_dir / kind, prepend_folder=True
                )
                moves += expanded
                warnings += expand_warnings
                stems = sorted({_stem_of(dest) for _src, dest in expanded})
                warnings.append(
                    f"{id_dir}: contents do not collapse onto '{entity_id}' "
                    f"(two files share an extension) — keeping filenames, so "
                    f"this becomes {len(stems)} entities: " + ", ".join(stems)
                )
                continue
            for ext, entry in by_ext.items():
                stem = f"{entity_id}_{_stem_of(entry)}"
                dest = group_dir / kind / f"{stem}{ext}"
                moves.append((entry, dest))
```

Note: with annotations short-circuited, the remaining collision/`by_ext` branch is now tomogram-only, so its `prepend_folder` and `stem` are unconditionally the Tomogram forms (the `if kind == "Tomograms"` ternaries drop out). Keep the surrounding `group_dir is None` warning and the `exclude_ids` skip as they are.

- [ ] **Step 5: Reroute `_plan_folder_as_group`**

In `_plan_folder_as_group`, replace the per-kind flatten with a kind-aware route:

```python
    for kind, allowed_exts in (("Tomograms", TOMOGRAM_FILE_EXTENSIONS), ("Annotations", ANNOTATION_FILE_EXTENSIONS)):
        id_dir = recon_dir / kind / gid
        if not id_dir.is_dir():
            continue
        if kind == "Annotations":
            moves += _plan_annotation_folder(id_dir, group_dir / kind)
            continue
        m, w = _expand_entity_folder(id_dir, allowed_exts, group_dir / kind)
        moves += m
        warnings += w
```

- [ ] **Step 6: Run the full migration suite**

Run: `python -m pytest tests/test_migrate_reconstruction_groups.py -v`
Expected: PASS. Existing single-file annotation assertions (`membrain_seg_v10.mrc`) still hold; the new multi-file test passes; `test_migrated_tree_loads` still green (its annotation is single-file). If `test_migrated_tree_loads` regresses, confirm Tasks 2–3 are merged (the loader/scanner must accept folder annotations).

- [ ] **Step 7: Add an end-to-end folder-annotation load test**

Add to `tests/test_migrate_reconstruction_groups.py` (verifies the migrated multi-file folder round-trips through the loader):

```python
def test_migrated_multi_file_annotation_loads(tmp_path):
    from schema.loader import load_sample_record

    acq = _make_acq(tmp_path)
    (acq.parent / "sample.toml").write_text('[sample]\nproject = "chromatin"\n')
    az = acq / "Reconstructions" / "Annotations" / "activezone_0_liza_az0"
    az.mkdir(parents=True)
    (az / "a.png").write_bytes(b"1")
    (az / "a_selected.png").write_bytes(b"2")
    # declare the annotation so the loader reconciles id -> folder
    toml = (acq / "acquisition.toml").read_text().replace(
        '[[annotation]]\nid = "membrain_seg_v10"\n',
        '[[annotation]]\nid = "activezone_0_liza_az0"\ntype = "gold_points"\n\n'
        '[[annotation]]\nid = "membrain_seg_v10"\n',
    )
    (acq / "acquisition.toml").write_text(toml)
    _run(tmp_path, apply=True)

    result = load_sample_record(acq.parent)
    rf = result.record.reconstructions["Position_86"]["ts_1"]
    ann_ids = {a.annotation_id for a in rf.annotation}
    assert "activezone_0_liza_az0" in ann_ids
    assert result.warnings == []
```

Run: `python -m pytest tests/test_migrate_reconstruction_groups.py::test_migrated_multi_file_annotation_loads -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add utils/migrate_reconstruction_groups.py tests/test_migrate_reconstruction_groups.py
git commit -m "feat(migration): preserve multi-file annotations as folders across all group paths"
```

---

### Task 5: Part B — gouauxlab alignment split

For acquisitions under `Experimental/gouauxlab_*`, group folders by their alignment marker (`az{N}` → `cryosnail_az{N}`, `_warp` → `warp`, `_best_alignment` → `best_alignment`) instead of the tilt-series id. Single alignment → everything into the one group; multiple → marked folders split, unmarked left in place + warned. `raw_tomogram.derived_from` still uses the tilt-series id.

**Files:**
- Modify: `utils/migrate_reconstruction_groups.py` (add `_gouauxlab_group_for`, `plan_gouauxlab`; wire into `main()` ~line 614–698)
- Test: `tests/test_migrate_reconstruction_groups.py`

**Interfaces:**
- Consumes: `_plan_annotation_folder` (Task 4), `_expand_entity_folder`, `group_id_for`, `prepare_processing_log`.
- Produces:
  - `_gouauxlab_group_for(name: str) -> str | None` — `cryosnail_az{N}` / `warp` / `best_alignment` / `None`.
  - `plan_gouauxlab(recon_dir: Path) -> tuple[list, list, list, list] | None` — `(moves, mkdirs, warnings, group_ids)`, or `None` when no marker is present (caller falls back to the generic path).

- [ ] **Step 1: Write the failing unit tests for the marker + planner**

Add to `tests/test_migrate_reconstruction_groups.py`:

```python
import pytest as _pytest

@_pytest.mark.parametrize("name,expected", [
    ("activezone_1_liza_az0", "cryosnail_az0"),
    ("activezone_0_liza_az2", "cryosnail_az2"),
    ("membrain_seg_v10_az1", "cryosnail_az1"),
    ("activezone_0_liza_az0_rerun", "cryosnail_az0"),
    ("bp_3dctf_bin4_warp", "warp"),
    ("activezone_1_best_alignment", "best_alignment"),
    ("membrain_seg_v10", None),
    ("bounding_boxes", None),
])
def test_gouauxlab_group_for(name, expected):
    assert migrate._gouauxlab_group_for(name) == expected


def _make_gouaux(root: Path, *, markers: dict) -> Path:
    """markers: {tomo_or_ann_folder_name: is_single_file(bool)} under one acq."""
    acq = root / "Experimental" / "gouauxlab_20260127_x" / "Position_13_3"
    recon = acq / "Reconstructions"
    (acq / "TiltSeries" / "Position_13_3").mkdir(parents=True)
    (acq / "acquisition.toml").write_text(
        '[acquisition]\n\n[[tilt_series]]\nid = "Position_13_3"\n'
    )
    return acq


def test_plan_gouauxlab_multi_alignment_splits_and_warns(tmp_path):
    acq = _make_gouaux(tmp_path, markers={})
    recon = acq / "Reconstructions"
    for folder, files in {
        "Tomograms/bp_3dctf_bin4_liza_az0": ["r.mrc"],
        "Tomograms/bp_3dctf_bin4_liza_az2": ["r.mrc"],
        "Annotations/activezone_1_liza_az0": ["a.star", "p.png", "p2.png"],
        "Annotations/activezone_1_liza_az2": ["a.star", "p.png", "p2.png"],
        "Annotations/membrain_seg_v10_liza_az0": ["seg.mrc"],
        "Annotations/bounding_boxes": ["b.json", "b_ng.json"],  # unmarked
    }.items():
        d = recon / folder
        d.mkdir(parents=True)
        for f in files:
            (d / f).write_bytes(b"")
    _run(tmp_path, apply=True)

    # az0 / az2 groups get their marked folders
    assert (recon / "cryosnail_az0" / "Annotations" / "activezone_1_liza_az0").is_dir()
    assert (recon / "cryosnail_az2" / "Annotations" / "activezone_1_liza_az2").is_dir()
    assert (recon / "cryosnail_az0" / "Annotations" / "membrain_seg_v10_liza_az0.mrc").is_file()
    assert (recon / "cryosnail_az0" / "Tomograms" / "bp_3dctf_bin4_liza_az0_r.mrc").is_file()
    # unmarked bounding_boxes stays put
    assert (recon / "Annotations" / "bounding_boxes").is_dir()


def test_plan_gouauxlab_single_alignment_absorbs_unmarked(tmp_path):
    acq = _make_gouaux(tmp_path, markers={})
    recon = acq / "Reconstructions"
    for folder, files in {
        "Tomograms/bp_3dctf_bin4_liza_az0": ["r.mrc"],
        "Annotations/activezone_0_liza_az0": ["a.star", "p.png", "p2.png"],
        "Annotations/membrain_seg_v10": ["seg.mrc"],  # unmarked
        "Annotations/bounding_boxes": ["b.json"],       # unmarked, single file
    }.items():
        d = recon / folder
        d.mkdir(parents=True)
        for f in files:
            (d / f).write_bytes(b"")
    _run(tmp_path, apply=True)

    # single alignment az0 -> unmarked folders come along too
    assert (recon / "cryosnail_az0" / "Annotations" / "activezone_0_liza_az0").is_dir()
    assert (recon / "cryosnail_az0" / "Annotations" / "membrain_seg_v10.mrc").is_file()
    assert (recon / "cryosnail_az0" / "Annotations" / "bounding_boxes.json").is_file()
    assert not (recon / "Annotations").exists()
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_migrate_reconstruction_groups.py -k gouauxlab -v`
Expected: FAIL — `_gouauxlab_group_for` / `plan_gouauxlab` don't exist and gouauxlab isn't wired into `main()`.

- [ ] **Step 3: Add `_gouauxlab_group_for` and `plan_gouauxlab`**

Add to `utils/migrate_reconstruction_groups.py`:

```python
def _gouauxlab_group_for(name: str) -> str | None:
    """Map a gouauxlab Tomograms/Annotations folder name to its reconstruction
    group by alignment marker: ``_az{N}`` / ``_liza_az{N}`` (``_rerun`` allowed
    after) -> ``cryosnail_az{N}`` (literal N); ``_warp`` -> ``warp``;
    ``_best_alignment`` -> ``best_alignment``; otherwise None (unmarked). The
    group is the alignment marker, not the leading ``activezone_M`` index."""
    m = re.search(r"_(?:liza_)?az(\d+)", name)
    if m:
        return f"cryosnail_az{m.group(1)}"
    if "_warp" in name:
        return "warp"
    if "_best_alignment" in name:
        return "best_alignment"
    return None


def _plan_gouaux_one(kind: str, exts: set[str], id_dir: Path, dest_dir: Path):
    """Route one folder into its group: annotations folder-preserve, tomograms
    flatten+prepend. Returns (moves, warnings)."""
    if kind == "Annotations":
        return _plan_annotation_folder(id_dir, dest_dir), []
    return _expand_entity_folder(id_dir, exts, dest_dir, prepend_folder=True)


def plan_gouauxlab(recon_dir: Path):
    """Split a gouauxlab acquisition's Reconstructions/ into per-alignment
    groups (see _gouauxlab_group_for). Single alignment -> every folder (marked
    and unmarked) into the one group; multiple -> marked folders split, unmarked
    (bounding_boxes) left in place + warned. Returns
    (moves, mkdirs, warnings, group_ids), or None if no marker is present at all
    (caller falls back to the generic path)."""
    kinds = (
        ("Tomograms", TOMOGRAM_FILE_EXTENSIONS),
        ("Annotations", ANNOTATION_FILE_EXTENSIONS),
    )
    folders = []  # (kind, exts, id_dir, group_or_None)
    for kind, exts in kinds:
        src = recon_dir / kind
        if not src.is_dir():
            continue
        for id_dir in sorted(p for p in src.iterdir() if p.is_dir()):
            folders.append((kind, exts, id_dir, _gouauxlab_group_for(id_dir.name)))

    marked = sorted({g for _, _, _, g in folders if g is not None})
    if not marked:
        return None

    moves, mkdirs, warnings = [], [], []
    if len(marked) == 1:
        single = marked[0]
        for kind, exts, id_dir, _g in folders:
            m, w = _plan_gouaux_one(kind, exts, id_dir, recon_dir / single / kind)
            moves += m
            warnings += w
        group_ids = [single]
    else:
        for kind, exts, id_dir, g in folders:
            if g is None:
                warnings.append(
                    f"{id_dir}: no alignment marker (az/warp/best_alignment) and "
                    "this acquisition has multiple alignments — leaving in place"
                )
                continue
            m, w = _plan_gouaux_one(kind, exts, id_dir, recon_dir / g / kind)
            moves += m
            warnings += w
        group_ids = marked

    for g in group_ids:
        mkdirs.append(recon_dir / g / "Alignment")
    return moves, mkdirs, warnings, group_ids
```

- [ ] **Step 4: Wire into `main()` and decouple `derived_from`**

In `main()`, after computing `group_id, warning = group_id_for(acq_dir)` and `recon_dir`, branch on gouauxlab. Replace the group-planning block (the `if group_id is None: ... else: ...` that builds `moves/mkdirs/warnings/extra_ids`) with:

```python
        is_gouaux = acq_dir.parent.name.startswith("gouauxlab")
        gouaux_plan = plan_gouauxlab(recon_dir) if is_gouaux else None

        if gouaux_plan is not None:
            # gouauxlab: groups are alignment markers, not the tilt-series id.
            moves, mkdirs, warnings, all_group_ids = gouaux_plan
            derived_from_id = group_id  # tilt-series id for raw_tomogram.derived_from
        elif group_id is None:
            moves, mkdirs, warnings, extra_ids = plan_folder_groups(recon_dir)
            all_group_ids = extra_ids
            derived_from_id = None
        else:
            extra_ids = shared_name_groups(recon_dir)
            moves, mkdirs, warnings = [], [], []
            for shared_id in extra_ids:
                m, k, w = plan_shared_name_group(recon_dir, shared_id)
                moves += m; mkdirs += k; warnings += w
            m, k, w = plan_reconstructions(recon_dir, group_id, exclude_ids=frozenset(extra_ids))
            moves += m; mkdirs += k; warnings += w
            all_group_ids = ([group_id] if group_id is not None else []) + extra_ids
            derived_from_id = group_id
```

Then update the downstream code that referenced `group_id` / `all_group_ids`:
- Keep `warnings += loose_file_warnings(recon_dir)` and the warning print loop.
- The rename-bookkeeping loop and `group_tomo_renames`/`group_ann_renames` already build from `all_group_ids` and `moves` — change its init `{gid: {} for gid in all_group_ids}` (it already uses `all_group_ids` via the `([group_id]...) + extra_ids` expression; replace that expression with the `all_group_ids` variable set above).
- `prepared = prepare_processing_log(orig_text, group_id)` → `prepare_processing_log(orig_text, derived_from_id)`.
- The `for gid in all_group_ids:` reconstruction.toml build loop is unchanged (now driven by the `all_group_ids` variable).

Verify no remaining bare `group_id` reference is used as a folder id past this point (only `derived_from_id` and `all_group_ids` should drive TOML content/folders).

- [ ] **Step 5: Run the gouauxlab tests + full suite**

Run: `python -m pytest tests/test_migrate_reconstruction_groups.py -v`
Expected: PASS — gouauxlab split/single/warn tests green; all prior tests (generic path, folder-as-group, folder-preserve) still green.

- [ ] **Step 6: Real-data dry-run smoke check (no writes)**

Run:
```bash
python utils/migrate_reconstruction_groups.py --lab-prefix gouauxlab_20260127 \
  --root /groups/cryoet/cryoet/data 2>&1 | grep -E 'cryosnail_az|best_alignment|leaving in place' | head
```
Expected: `mv` lines into `cryosnail_az0` / `cryosnail_az2` / `best_alignment`, and a "leaving in place" warning for `bounding_boxes` in `Position_13_3`. Confirms markers resolve on live folder names.

- [ ] **Step 7: Commit**

```bash
git add utils/migrate_reconstruction_groups.py tests/test_migrate_reconstruction_groups.py
git commit -m "feat(migration): split gouauxlab acquisitions into per-alignment groups"
```

---

### Task 6: Documentation

**Files:**
- Modify: `docs/data_organization.md`
- Modify: `docs/annotation-reorg-questions.md` (mark Theme 1 resolved)

**Interfaces:** none (docs only).

- [ ] **Step 1: Document the annotation layout + gouauxlab groups**

In `docs/data_organization.md`, in the `Reconstructions/` section, add: an annotation is either a bare `Annotations/{id}.ext` (single file) or a folder `Annotations/{id}/` holding several files (id = folder name); tomograms remain flattened files. Add a short note that gouauxlab acquisitions are split into `cryosnail_az{N}` / `warp` / `best_alignment` groups by the alignment suffix on each folder, with unmarked folders in a multi-alignment acquisition left under a stray `Annotations/` for manual filing.

- [ ] **Step 2: Mark the questions doc resolved**

At the top of `docs/annotation-reorg-questions.md`, add a note that Theme 1 (identity/container) is resolved by `docs/superpowers/specs/2026-08-03-annotation-folders-gouauxlab-alignment-split-design.md`; Theme 2 (neuroglancer composition) remains open.

- [ ] **Step 3: Commit**

```bash
git add docs/data_organization.md docs/annotation-reorg-questions.md
git commit -m "docs: describe annotation folders and gouauxlab alignment groups"
```

---

## Self-Review

**Spec coverage:**
- Part A migration (D1, D2, D7, all 3 paths) → Task 4. ✓
- Part A scanner (A2) → Task 3. ✓
- Part A validate-CLI (A3) → Task 2. ✓
- Part B gouauxlab (D3–D6, D8, D9) → Task 5. ✓
- Part C nested tomogram filenames (D10) → Task 1. ✓
- Docs → Task 6. ✓
- Test-plan items (multi-align, single-align, warp, rosenlab folder-as-group, nested subdir, idempotency, round-trip, allowlist parity) → covered across Tasks 1/3/4/5 + existing `test_second_apply_is_a_noop` and `test_allowlists_match_the_schema`. ✓

**Placeholder scan:** No TBD/TODO; every code step has real code. ✓

**Type consistency:** `_plan_annotation_folder(id_dir, dest_dir) -> list[(src,dest)]` used identically in Tasks 4 and 5. `_gouauxlab_group_for(name) -> str|None` and `plan_gouauxlab(recon_dir) -> tuple|None` consistent between definition (Task 5 step 3) and wiring (step 4). `entity_ids_in_dir(..., include_dirs=False)` signature consistent across Task 2 definition and loader call sites. `iter_annotations` yields `AnnotationLocation(path, annotation_id, files, reconstruction_alignment_id)` — matches the frozen dataclass. ✓

**Ordering:** Read-side (Tasks 2–3) precedes migration tasks (4–5) that produce folder annotations, so their end-to-end loader tests pass. ✓
