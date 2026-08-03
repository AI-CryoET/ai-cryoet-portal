"""Self-check for utils/migrate_reconstruction_groups.py.

The script is one-shot, but it rewrites real researcher data in place, so the
paths that matter are pinned here: dry-run touches nothing, --apply produces a
tree the current loader accepts, a second run is a no-op, and anything
ambiguous is left alone rather than guessed at.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "utils" / "migrate_reconstruction_groups.py"
_spec = importlib.util.spec_from_file_location("migrate_reconstruction_groups", _SCRIPT)
migrate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migrate)


_ACQ_TOML = '''\
[acquisition]
resolution = 3.5

[[tilt_series]]
id = "ts_1"
is_aligned = true

[raw_tomogram]
id = "bp_3dctf_bin4"
tilt_series_id = "ts_1"
pipeline = "backprojection"

[[post_processed_tomogram]]
id = "denoised"
tilt_series_id = "ts_1"
denoising_software = "cryoCARE"
derived_from = ["bp_3dctf_bin4"]

[[annotation]]
id = "membrain_seg_v10"
type = "membrane_segmentation"
target_tomogram = "denoised"
'''


def _make_acq(root: Path, *, acq_toml: str = _ACQ_TOML) -> Path:
    """One experimental acquisition in the OLD layout."""
    acq = root / "Experimental" / "sample_a" / "Position_86"
    recon = acq / "Reconstructions"
    (recon / "Tomograms" / "bp_3dctf_bin4").mkdir(parents=True)
    (recon / "Tomograms" / "bp_3dctf_bin4" / "recon.mrc").write_bytes(b"raw")
    (recon / "Tomograms" / "bp_3dctf_bin4" / "recon.ome.zarr").mkdir()
    (recon / "Tomograms" / "denoised").mkdir()
    (recon / "Tomograms" / "denoised" / "out.mrc").write_bytes(b"denoised")
    (recon / "Annotations" / "membrain_seg_v10").mkdir(parents=True)
    (recon / "Annotations" / "membrain_seg_v10" / "seg.mrc").write_bytes(b"seg")
    (acq / "TiltSeries" / "ts_1").mkdir(parents=True)
    (acq / "acquisition.toml").write_text(acq_toml)
    return acq


def _run(root: Path, *, apply: bool, csv: Path | None = None) -> None:
    argv = ["migrate", "--root", str(root)]
    if apply:
        argv.append("--apply")
    elif csv is not None:
        argv += ["--csv", str(csv)]
    old = sys.argv
    sys.argv = argv
    try:
        migrate.main()
    finally:
        sys.argv = old


def test_dry_run_writes_a_csv_and_changes_nothing(tmp_path):
    import csv as _csv

    _make_acq(tmp_path)
    # Snapshot only the data subtree (Experimental/) so the CSV, written to a
    # sibling path under tmp_path, doesn't count as a change to the tree.
    data = tmp_path / "Experimental"
    before = sorted(p.relative_to(tmp_path).as_posix() for p in data.rglob("*"))
    csv_path = tmp_path / "plan.csv"
    _run(tmp_path, apply=False, csv=csv_path)
    after = sorted(p.relative_to(tmp_path).as_posix() for p in data.rglob("*"))
    assert before == after  # the data tree is untouched

    # The plan lands in the CSV, not on the terminal.
    with open(csv_path, newline="") as f:
        rows = list(_csv.DictReader(f))
    assert rows
    # The single-file membrain annotation collapses to a bare {id}.ext in group ts_1.
    membrain = next(
        r for r in rows
        if r["starting_relative_path"] == "Annotations/membrain_seg_v10/seg.mrc"
    )
    assert membrain["containing_folder"] == "Experimental"
    assert membrain["sample_name"] == "sample_a"
    assert membrain["acquisition_name"] == "Position_86"
    assert membrain["ending_relative_path"] == "ts_1/Annotations/membrain_seg_v10.mrc"


def test_apply_moves_files_into_the_group(tmp_path):
    acq = _make_acq(tmp_path)
    _run(tmp_path, apply=True)
    group = acq / "Reconstructions" / "ts_1"
    # A tomogram keeps its descriptive filename, prefixed with the source folder
    # name; a single annotation leaf still collapses onto the folder name.
    assert (group / "Tomograms" / "bp_3dctf_bin4_recon.mrc").read_bytes() == b"raw"
    assert (group / "Tomograms" / "bp_3dctf_bin4_recon.ome.zarr").is_dir()
    assert (group / "Tomograms" / "denoised_out.mrc").read_bytes() == b"denoised"
    assert (group / "Annotations" / "membrain_seg_v10.mrc").read_bytes() == b"seg"
    assert (group / "Alignment").is_dir()
    # The flat dirs are gone, so a rescan can't read them as a bogus group.
    assert not (acq / "Reconstructions" / "Tomograms").exists()
    assert not (acq / "Reconstructions" / "Annotations").exists()


def test_apply_splits_the_processing_log_into_reconstruction_toml(tmp_path):
    acq = _make_acq(tmp_path)
    _run(tmp_path, apply=True)

    recon_toml = (acq / "Reconstructions" / "ts_1" / "reconstruction.toml").read_text()
    assert recon_toml.startswith("#:schema ")
    assert "[reconstruction_alignment]" in recon_toml
    # Singular [raw_tomogram] became the array form, and its lineage moved from
    # the removed tilt_series_id to derived_from.
    assert "[[raw_tomogram]]" in recon_toml
    assert 'derived_from   = "ts_1"' in recon_toml
    assert "tilt_series_id" not in recon_toml
    assert "target_tomogram" not in recon_toml
    assert '[[post_processed_tomogram]]' in recon_toml
    assert '[[annotation]]' in recon_toml

    # acquisition.toml keeps its own sections and loses the processing log.
    acq_toml = (acq / "acquisition.toml").read_text()
    assert "[acquisition]" in acq_toml
    assert "[[tilt_series]]" in acq_toml
    assert "raw_tomogram" not in acq_toml
    assert "annotation" not in acq_toml


def test_migrated_tree_loads(tmp_path):
    """End-to-end: the migrated tree is what the loader now expects."""
    from schema.loader import load_sample_record

    acq = _make_acq(tmp_path)
    (acq.parent / "sample.toml").write_text('[sample]\nproject = "chromatin"\n')
    _run(tmp_path, apply=True)

    result = load_sample_record(acq.parent)
    assert result.sample_errors == []
    assert result.acquisition_errors == {}
    assert result.record is not None
    rf = result.record.reconstructions["Position_86"]["ts_1"]
    assert [t.tomogram_id for t in rf.raw_tomogram] == ["bp_3dctf_bin4_recon"]
    assert rf.raw_tomogram[0].derived_from == "ts_1"
    assert [t.tomogram_id for t in rf.post_processed_tomogram] == ["denoised_out"]
    # the post-processed tomogram's derived_from ref was rewritten to the
    # renamed raw tomogram, so lineage still resolves (no dangling-ref warning).
    assert rf.post_processed_tomogram[0].derived_from == ["bp_3dctf_bin4_recon"]
    assert [a.annotation_id for a in rf.annotation] == ["membrain_seg_v10"]
    assert result.warnings == []


def test_second_apply_is_a_noop(tmp_path):
    _make_acq(tmp_path)
    _run(tmp_path, apply=True)
    after_first = {
        p.relative_to(tmp_path).as_posix(): (p.read_bytes() if p.is_file() else None)
        for p in tmp_path.rglob("*")
    }
    _run(tmp_path, apply=True)
    after_second = {
        p.relative_to(tmp_path).as_posix(): (p.read_bytes() if p.is_file() else None)
        for p in tmp_path.rglob("*")
    }
    assert after_first == after_second


def test_ambiguous_tilt_series_falls_back_to_folder_named_groups(tmp_path, capsys):
    """Two tilt series means no single group id; each {id}/ folder becomes its
    own group rather than being filed under a guessed one."""
    acq_toml = _ACQ_TOML.replace(
        '[[tilt_series]]\nid = "ts_1"\nis_aligned = true\n',
        '[[tilt_series]]\nid = "ts_1"\n\n[[tilt_series]]\nid = "ts_2"\n',
    )
    acq = _make_acq(tmp_path, acq_toml=acq_toml)
    _run(tmp_path, apply=True)
    assert "found 2" in capsys.readouterr().err
    recon = acq / "Reconstructions"
    # A folder that becomes the GROUP hands its entity ids to the files it
    # holds, so bp_3dctf_bin4's recon.mrc + recon.ome.zarr become tomogram
    # "recon" inside group "bp_3dctf_bin4"; a single-file folder still
    # collapses to the folder name.
    assert (recon / "bp_3dctf_bin4" / "Tomograms" / "recon.mrc").is_file()
    assert (recon / "bp_3dctf_bin4" / "Tomograms" / "recon.ome.zarr").is_dir()
    assert (recon / "denoised" / "Tomograms" / "denoised.mrc").is_file()
    assert (
        recon / "membrain_seg_v10" / "Annotations" / "membrain_seg_v10.mrc"
    ).is_file()
    assert not (recon / "ts_1").exists()


def test_loose_file_is_warned_and_left_in_place(tmp_path, capsys):
    """A file directly under Tomograms/ has no {id}/ folder saying which group
    it belongs to, so it can't be placed automatically."""
    acq = _make_acq(tmp_path)
    loose = acq / "Reconstructions" / "Tomograms" / "stray.mrc"
    loose.write_bytes(b"stray")
    _run(tmp_path, apply=True)
    assert "loose file" in capsys.readouterr().err
    assert loose.is_file()


def test_extension_collision_keeps_filenames_as_separate_entities(tmp_path, capsys):
    """Two .mrc in one {id}/ folder can't both take the folder's name, so they
    are separate entities keeping their own filenames — the same policy the
    folder-named-group path uses. The authored block is expanded to match so no
    declaration is left dangling."""
    acq = _make_acq(tmp_path)
    extra = acq / "Reconstructions" / "Tomograms" / "denoised" / "other.mrc"
    extra.write_bytes(b"other")
    _run(tmp_path, apply=True)
    err = capsys.readouterr().err
    assert "do not collapse onto 'denoised'" in err
    assert "2 entities: denoised_other, denoised_out" in err

    tomos = acq / "Reconstructions" / "ts_1" / "Tomograms"
    # Filenames survive; each id is the folder name prefixed onto the surviving
    # filename stem, so the two collide-in-extension files stay separate.
    assert (tomos / "denoised_out.mrc").read_bytes() == b"denoised"
    assert (tomos / "denoised_other.mrc").read_bytes() == b"other"
    assert not (tomos / "denoised.mrc").exists()
    # The unambiguous sibling keeps its prefixed descriptive filename.
    assert (tomos / "bp_3dctf_bin4_recon.mrc").is_file()
    # Nothing is left behind, so the flat dir goes.
    assert not (acq / "Reconstructions" / "Tomograms").exists()

    # The single authored [[post_processed_tomogram]] id = "denoised" became one
    # block per resulting stem, other fields copied verbatim.
    recon = (acq / "Reconstructions" / "ts_1" / "reconstruction.toml").read_text()
    assert 'id = "denoised_out"' in recon
    assert 'id = "denoised_other"' in recon
    assert 'id = "denoised"' not in recon
    assert recon.count("cryoCARE") == 2


@pytest.mark.parametrize(
    "name,expected",
    [("foo.mrc", ".mrc"), ("foo.ome.zarr", ".ome.zarr"), ("foo.star", ".star")],
)
def test_ext_of_strips_multi_suffix_zarr(tmp_path, name, expected):
    """The stem rule must match schema.layout.entity_id_from_path: Path.suffix
    would turn foo.ome.zarr into '.zarr' and split it from its foo.mrc sibling.
    """
    from schema.layout import entity_id_from_path

    path = tmp_path / name
    if name.endswith(".zarr"):
        path.mkdir()
    else:
        path.touch()
    assert migrate._ext_of(path) == expected
    assert path.name[: -len(expected)] == entity_id_from_path(path)


def test_allowlists_match_the_schema():
    """The script is standalone (no `src/` import) so it carries its own copy of
    the extension allowlists. They must equal schema.layout's, or the migration
    moves a file the scanner then ignores — or leaves one behind, which keeps
    the flat Tomograms/Annotations dir alive as a bogus group.
    """
    from schema import layout

    assert migrate.TOMOGRAM_FILE_EXTENSIONS == set(layout.TOMOGRAM_FILE_EXTENSIONS)
    assert migrate.ANNOTATION_FILE_EXTENSIONS == set(layout.ANNOTATION_FILE_EXTENSIONS)


def test_placeholder_folders_are_cleaned_up(tmp_path):
    """A Tomograms/{id}/ holding only a .gitkeep produces no moves, so it is not
    a move source — but leaving it keeps the flat dir alive and the scanner
    reads that as an empty reconstruction group."""
    acq = _make_acq(tmp_path)
    placeholder = acq / "Reconstructions" / "Annotations" / "annotation_id"
    placeholder.mkdir()
    (placeholder / ".gitkeep").write_text("")
    (placeholder / "Thumbs.db").write_bytes(b"")  # OS litter, same class
    _run(tmp_path, apply=True)
    assert not placeholder.exists()
    assert not (acq / "Reconstructions" / "Annotations").exists()
    # ...and it's pruned, not relocated into the group as a bogus annotation.
    assert not (acq / "Reconstructions" / "ts_1" / "Annotations" / "annotation_id").exists()


def test_stray_file_keeps_its_folder(tmp_path):
    """The converse: a file the allowlist does NOT cover is real content the
    migration can't place, so its folder (and the flat dir) must survive rather
    than be silently deleted."""
    acq = _make_acq(tmp_path)
    keep = acq / "Reconstructions" / "Annotations" / "notes"
    keep.mkdir()
    (keep / "readme.txt").write_text("hand-written")
    _run(tmp_path, apply=True)
    assert (keep / "readme.txt").read_text() == "hand-written"


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


def _snapshot(root: Path) -> dict:
    return {
        p.relative_to(root).as_posix(): (p.read_bytes() if p.is_file() else None)
        for p in root.rglob("*")
    }


def test_gouauxlab_single_alignment_second_apply_is_a_noop(tmp_path):
    acq = _make_gouaux(tmp_path, markers={})
    recon = acq / "Reconstructions"
    for folder, files in {
        "Tomograms/bp_3dctf_bin4_liza_az0": ["r.mrc"],
        "Annotations/activezone_0_liza_az0": ["a.star", "p.png", "p2.png"],
    }.items():
        d = recon / folder
        d.mkdir(parents=True)
        for f in files:
            (d / f).write_bytes(b"")
    _run(tmp_path, apply=True)
    after_first = _snapshot(tmp_path)
    _run(tmp_path, apply=True)
    after_second = _snapshot(tmp_path)
    assert after_first == after_second


def test_gouauxlab_multi_alignment_second_apply_is_a_noop(tmp_path):
    acq = _make_gouaux(tmp_path, markers={})
    recon = acq / "Reconstructions"
    for folder, files in {
        "Tomograms/bp_3dctf_bin4_liza_az0": ["r.mrc"],
        "Tomograms/bp_3dctf_bin4_liza_az2": ["r.mrc"],
        "Annotations/activezone_1_liza_az0": ["a.star", "p.png", "p2.png"],
        "Annotations/activezone_1_liza_az2": ["a.star", "p.png", "p2.png"],
        "Annotations/bounding_boxes": ["b.json", "b_ng.json"],  # unmarked
    }.items():
        d = recon / folder
        d.mkdir(parents=True)
        for f in files:
            (d / f).write_bytes(b"")
    _run(tmp_path, apply=True)
    after_first = _snapshot(tmp_path)
    _run(tmp_path, apply=True)
    after_second = _snapshot(tmp_path)
    assert after_first == after_second
    # unmarked bounding_boxes must still be parked in place, not swept into
    # a bogus tilt-series-id group on re-run
    assert (recon / "Annotations" / "bounding_boxes").is_dir()


def test_loose_annotation_file_moves_into_missalignment_group(tmp_path, capsys):
    """A loose file directly under Annotations/ is filed into the Missalignment
    group's Annotations/ when that group forms (real case: rosenlab
    s2xx.catm.star). It keeps its filename, is not warned about, and the flat
    Annotations/ dir is pruned. Re-running is a no-op."""
    # Two tilt series -> folder-as-group, so Tomograms/Missalignment/ becomes a
    # Reconstructions/Missalignment/ group.
    acq_toml = _ACQ_TOML.replace(
        '[[tilt_series]]\nid = "ts_1"\nis_aligned = true\n',
        '[[tilt_series]]\nid = "ts_1"\n\n[[tilt_series]]\nid = "ts_2"\n',
    )
    acq = _make_acq(tmp_path, acq_toml=acq_toml)
    mis = acq / "Reconstructions" / "Tomograms" / "Missalignment"
    mis.mkdir(parents=True)
    (mis / "rec.mrc").write_bytes(b"m")
    loose = acq / "Reconstructions" / "Annotations" / "s200.catm.star"
    loose.write_text("catm")

    _run(tmp_path, apply=True)

    dest = acq / "Reconstructions" / "Missalignment" / "Annotations" / "s200.catm.star"
    assert dest.read_text() == "catm"
    assert not loose.exists()
    assert "loose file" not in capsys.readouterr().err
    assert not (acq / "Reconstructions" / "Annotations").exists()

    # idempotent: nothing left to move on a second apply
    after_first = _snapshot(tmp_path)
    _run(tmp_path, apply=True)
    assert _snapshot(tmp_path) == after_first


def test_loose_annotation_without_missalignment_is_still_warned(tmp_path, capsys):
    """No Missalignment group -> no automatic home, so a loose Annotations/ file
    is left in place and warned about (unchanged behavior)."""
    acq_toml = _ACQ_TOML.replace(
        '[[tilt_series]]\nid = "ts_1"\nis_aligned = true\n',
        '[[tilt_series]]\nid = "ts_1"\n\n[[tilt_series]]\nid = "ts_2"\n',
    )
    acq = _make_acq(tmp_path, acq_toml=acq_toml)
    loose = acq / "Reconstructions" / "Annotations" / "orphan.catm.star"
    loose.write_text("x")
    _run(tmp_path, apply=True)
    assert "loose file" in capsys.readouterr().err
    assert loose.exists()
