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


def _run(root: Path, *, apply: bool) -> None:
    argv = ["migrate", "--root", str(root)] + (["--apply"] if apply else [])
    old = sys.argv
    sys.argv = argv
    try:
        migrate.main()
    finally:
        sys.argv = old


def test_dry_run_changes_nothing(tmp_path, capsys):
    acq = _make_acq(tmp_path)
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    _run(tmp_path, apply=False)
    after = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    assert before == after
    # …but it does say what it would do.
    out = capsys.readouterr().out
    assert "mv " in out
    assert str(acq / "Reconstructions" / "ts_1") in out


def test_apply_moves_files_into_the_group(tmp_path):
    acq = _make_acq(tmp_path)
    _run(tmp_path, apply=True)
    group = acq / "Reconstructions" / "ts_1"
    # The {id}/ folder name becomes the file stem; a single leaf collapses.
    assert (group / "Tomograms" / "bp_3dctf_bin4.mrc").read_bytes() == b"raw"
    assert (group / "Tomograms" / "bp_3dctf_bin4.ome.zarr").is_dir()
    assert (group / "Tomograms" / "denoised.mrc").read_bytes() == b"denoised"
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
    assert [t.tomogram_id for t in rf.raw_tomogram] == ["bp_3dctf_bin4"]
    assert rf.raw_tomogram[0].derived_from == "ts_1"
    assert [t.tomogram_id for t in rf.post_processed_tomogram] == ["denoised"]
    assert [a.annotation_id for a in rf.annotation] == ["membrain_seg_v10"]
    assert not any("no matching folder" in w for w in result.warnings)


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


def test_ambiguous_extension_collision_is_skipped(tmp_path, capsys):
    """Two .mrc files in one {id}/ folder can't collapse to one stem."""
    acq = _make_acq(tmp_path)
    extra = acq / "Reconstructions" / "Tomograms" / "denoised" / "other.mrc"
    extra.write_bytes(b"other")
    _run(tmp_path, apply=True)
    assert "multiple '.mrc' entries" in capsys.readouterr().err
    # Left untouched; the unambiguous sibling still migrated.
    assert extra.is_file()
    assert (
        acq / "Reconstructions" / "ts_1" / "Tomograms" / "bp_3dctf_bin4.mrc"
    ).is_file()


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
