"""Unit tests for the path-walking discovery layer."""

from __future__ import annotations

from pathlib import Path

import pytest

from schema.schema import DataSource, DatasetType

from catalog.discovery import (
    dir_size_bytes,
    iter_acquisitions,
    iter_annotations,
    iter_md_runs,
    iter_misplaced_samples,
    iter_samples,
    iter_tomograms,
    iter_unknown_md_subdirs,
    parse_targets_for_sample,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_iter_samples_finds_chromatin_and_simulation():
    samples = sorted(iter_samples(FIXTURES), key=lambda s: s.sample_id)
    assert [s.sample_id for s in samples] == [
        "SingleMolecule_sample_simulation",
        "sample_chromatin",
    ]
    chrom = samples[0]
    assert chrom.sample_toml.exists()
    assert chrom.path.is_dir()


def test_iter_samples_assigns_arm_from_directory():
    samples = {s.sample_id: s for s in iter_samples(FIXTURES)}
    chrom = samples["sample_chromatin"]
    assert chrom.data_source == DataSource.experimental
    assert chrom.dataset_type is None
    sim = samples["SingleMolecule_sample_simulation"]
    assert sim.data_source == DataSource.simulation
    assert sim.dataset_type == DatasetType.single_molecule


def test_iter_samples_namespaces_simulation_ids_by_subdir(tmp_path):
    """Same folder name under two MdSimulation subdirs gets distinct ids —
    the bare folder name is not unique across Bulk/SingleMolecule/Slab."""
    for sub in ("Bulk", "Slab"):
        d = tmp_path / "MdSimulation" / sub / "12mer_26_0.080"
        d.mkdir(parents=True)
        (d / "sample.toml").write_text(
            '[sample]\ndata_source = "simulation"\nproject = "chromatin"\n'
        )
    ids = {s.sample_id for s in iter_samples(tmp_path)}
    assert ids == {"Bulk_12mer_26_0.080", "Slab_12mer_26_0.080"}


def test_iter_samples_skips_unknown_mdsimulation_subdir(tmp_path):
    # A subdir under MdSimulation/ that isn't one of the four dataset-type dirs
    # is skipped silently.
    bogus = tmp_path / "MdSimulation" / "NotADatasetType" / "s1"
    bogus.mkdir(parents=True)
    (bogus / "sample.toml").write_text(
        '[sample]\ndata_source = "simulation"\nproject = "chromatin"\n'
    )
    good = tmp_path / "MdSimulation" / "Bulk" / "s2"
    good.mkdir(parents=True)
    (good / "sample.toml").write_text(
        '[sample]\ndata_source = "simulation"\nproject = "chromatin"\n'
    )
    found = list(iter_samples(tmp_path))
    assert {s.sample_id for s in found} == {"Bulk_s2"}
    assert found[0].dataset_type == DatasetType.bulk


def test_iter_unknown_md_subdirs_yields_only_unrecognized(tmp_path):
    # Two known dataset-type dirs plus one bogus subdir; only the bogus one
    # should be surfaced (the known dirs hold real samples).
    for name in ("Bulk", "NotADatasetType"):
        (tmp_path / "MdSimulation" / name).mkdir(parents=True)
    unknown = list(iter_unknown_md_subdirs(tmp_path))
    assert [p.name for p in unknown] == ["NotADatasetType"]


def test_iter_unknown_md_subdirs_empty_without_arm(tmp_path):
    # No MdSimulation/ arm at all -> nothing to warn about.
    (tmp_path / "Experimental").mkdir()
    assert list(iter_unknown_md_subdirs(tmp_path)) == []


def test_iter_unknown_md_subdirs_ignores_files(tmp_path):
    # A stray file directly under MdSimulation/ is not a subdir warning.
    md = tmp_path / "MdSimulation"
    md.mkdir()
    (md / "README.txt").write_text("notes")
    assert list(iter_unknown_md_subdirs(tmp_path)) == []


def _write_sample_toml(sample_dir: Path) -> None:
    sample_dir.mkdir(parents=True)
    (sample_dir / "sample.toml").write_text(
        '[sample]\nproject = "chromatin"\n'
    )


def test_iter_misplaced_samples_finds_samples_under_wrong_top_dir(tmp_path):
    # root/{other}/{sample}/sample.toml -> misplaced (other is not an arm).
    _write_sample_toml(tmp_path / "Experiemntal" / "s1")  # typo'd arm
    misplaced = list(iter_misplaced_samples(tmp_path))
    assert [p.name for p in misplaced] == ["s1"]


def test_iter_misplaced_samples_reports_sample_directly_under_top_dir(tmp_path):
    # root/{other}/sample.toml -> the non-arm dir is itself the sample dir.
    _write_sample_toml(tmp_path / "loose_sample")
    misplaced = list(iter_misplaced_samples(tmp_path))
    assert [p.name for p in misplaced] == ["loose_sample"]


def test_iter_misplaced_samples_ignores_recognized_arms(tmp_path):
    # Samples correctly under Experimental/ and MdSimulation/ are never flagged.
    _write_sample_toml(tmp_path / "Experimental" / "s1")
    _write_sample_toml(tmp_path / "MdSimulation" / "Bulk" / "s2")
    assert list(iter_misplaced_samples(tmp_path)) == []


def test_iter_misplaced_samples_ignores_dirs_without_sample_toml(tmp_path):
    # A non-arm top-level dir with no sample.toml anywhere is not flagged.
    (tmp_path / "scratch" / "subdir").mkdir(parents=True)
    (tmp_path / "scratch" / "notes.txt").write_text("hi")
    assert list(iter_misplaced_samples(tmp_path)) == []


def test_iter_samples_tolerates_missing_arm(tmp_path):
    # Only an Experimental/ arm present; MdSimulation/ absent.
    exp = tmp_path / "Experimental" / "s1"
    exp.mkdir(parents=True)
    (exp / "sample.toml").write_text(
        '[sample]\ndata_source = "experimental"\nproject = "chromatin"\n'
    )
    found = list(iter_samples(tmp_path))
    assert {s.sample_id for s in found} == {"s1"}
    assert found[0].data_source == DataSource.experimental


def test_iter_samples_skips_dirs_without_sample_toml(tmp_path):
    exp = tmp_path / "Experimental"
    exp.mkdir()
    (exp / "no_toml_here").mkdir()
    (exp / "with_toml").mkdir(exist_ok=True)
    (exp / "with_toml" / "sample.toml").write_text(
        '[sample]\ndata_source = "experimental"\nproject = "chromatin"\n'
    )
    found = list(iter_samples(tmp_path))
    assert {s.sample_id for s in found} == {"with_toml"}


def test_iter_md_runs_finds_md_run_tomls():
    sim = next(
        s for s in iter_samples(FIXTURES) if s.sample_id == "SingleMolecule_sample_simulation"
    )
    runs = list(iter_md_runs(sim))
    assert [r.md_run_id for r in runs] == ["run_001"]
    assert runs[0].md_run_toml.is_file()
    assert runs[0].md_run_toml.name == "md_run.toml"


def test_iter_md_runs_empty_for_experimental():
    chrom = next(
        s for s in iter_samples(FIXTURES) if s.sample_id == "sample_chromatin"
    )
    assert list(iter_md_runs(chrom)) == []


def test_iter_acquisitions_finds_toml_and_frames_only():
    sample = next(
        s for s in iter_samples(FIXTURES) if s.sample_id == "sample_chromatin"
    )
    acqs = sorted(iter_acquisitions(sample), key=lambda a: a.acquisition_id)
    assert [a.acquisition_id for a in acqs] == ["Position_86", "Position_87"]
    pos86, pos87 = acqs
    assert pos86.acquisition_toml is not None and pos86.acquisition_toml.is_file()
    assert pos87.acquisition_toml is None  # Frames-only acquisition
    assert pos86.frames_dir is not None
    assert pos86.reconstructions_dir is not None


def test_iter_acquisitions_simulation_nested_under_synthetic():
    """Simulation acquisitions live under SyntheticCryoET/<acq>/ (one level
    deeper than experimental); the simulation-aware walk finds them."""
    sim = next(
        s for s in iter_samples(FIXTURES) if s.sample_id == "SingleMolecule_sample_simulation"
    )
    acqs = list(iter_acquisitions(sim))
    assert [a.acquisition_id for a in acqs] == ["sim_acq_01"]
    acq = acqs[0]
    assert acq.acquisition_toml is not None and acq.acquisition_toml.is_file()
    # The acquisition root sits under SyntheticCryoET/.
    assert acq.path.parent.name == "SyntheticCryoET"
    assert acq.reconstructions_dir is not None


def test_iter_tomograms_lists_pipeline_folders():
    sample = next(
        s for s in iter_samples(FIXTURES) if s.sample_id == "sample_chromatin"
    )
    pos86 = next(
        a for a in iter_acquisitions(sample) if a.acquisition_id == "Position_86"
    )
    tomos = list(iter_tomograms(pos86))
    assert len(tomos) == 1
    assert tomos[0].tomogram_id == "bp_3dctf_bin4"
    # id is the file stem; .mrc and .ome.zarr collapse under one tomogram.
    assert any(p.suffix == ".mrc" for p in tomos[0].mrc_files)
    assert any(p.name.endswith(".ome.zarr") for p in tomos[0].zarr_dirs)
    # the group id is the enclosing Reconstructions/{group}/ folder name.
    assert tomos[0].reconstruction_alignment_id == "ts_1"


def test_iter_annotations_filters_by_extension():
    sample = next(
        s for s in iter_samples(FIXTURES) if s.sample_id == "sample_chromatin"
    )
    pos86 = next(
        a for a in iter_acquisitions(sample) if a.acquisition_id == "Position_86"
    )
    anns = list(iter_annotations(pos86))
    assert len(anns) == 1
    ann = anns[0]
    assert ann.annotation_id == "membrain_seg_v10"
    # Two files sharing the stem membrain_seg_v10 collapse to one annotation.
    file_names = {p.name for p in ann.files}
    assert "membrain_seg_v10.mrc" in file_names
    assert "membrain_seg_v10.json" in file_names
    assert ann.reconstruction_alignment_id == "ts_1"


# ---------------------------------------------------------------------------
# file-stem grouping (new Reconstructions layout)
# ---------------------------------------------------------------------------

from catalog.discovery import AcquisitionLocation  # noqa: E402


def _acq_loc(acq_dir: Path) -> AcquisitionLocation:
    recon = acq_dir / "Reconstructions"
    return AcquisitionLocation(
        path=acq_dir,
        sample_id=acq_dir.parent.name,
        acquisition_id=acq_dir.name,
        acquisition_toml=None,
        frames_dir=None,
        tilt_series_dir=None,
        reconstructions_dir=recon if recon.is_dir() else None,
    )


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


def test_iter_tomograms_groups_by_stem_under_the_alignment_group(tmp_path):
    # Two tomograms + two annotations under one group folder; ids are the file
    # stems and the group id is the enclosing folder name.
    tomos_dir = tmp_path / "acq" / "Reconstructions" / "ts_7" / "Tomograms"
    anns_dir = tmp_path / "acq" / "Reconstructions" / "ts_7" / "Annotations"
    tomos_dir.mkdir(parents=True)
    anns_dir.mkdir(parents=True)
    (tomos_dir / "tomo_a.mrc").write_bytes(b"")
    (tomos_dir / "tomo_b.mrc").write_bytes(b"")
    (anns_dir / "ann_a.star").write_text("")
    (anns_dir / "ann_b.mrc").write_bytes(b"")

    acq = _acq_loc(tmp_path / "acq")
    tomos = list(iter_tomograms(acq))
    assert [(t.tomogram_id, t.reconstruction_alignment_id) for t in tomos] == [
        ("tomo_a", "ts_7"),
        ("tomo_b", "ts_7"),
    ]
    anns = list(iter_annotations(acq))
    assert [(a.annotation_id, a.reconstruction_alignment_id) for a in anns] == [
        ("ann_a", "ts_7"),
        ("ann_b", "ts_7"),
    ]


def test_iter_tomograms_collapses_mrc_and_zarr_by_stem(tmp_path):
    # foo.mrc + foo.ome.zarr share the stem foo -> ONE tomogram (Path.stem would
    # split foo.ome.zarr into foo.ome).
    tomos_dir = tmp_path / "acq" / "Reconstructions" / "ts_1" / "Tomograms"
    tomos_dir.mkdir(parents=True)
    (tomos_dir / "foo.mrc").write_bytes(b"")
    (tomos_dir / "foo.ome.zarr").mkdir()

    acq = _acq_loc(tmp_path / "acq")
    tomos = list(iter_tomograms(acq))
    assert len(tomos) == 1
    assert tomos[0].tomogram_id == "foo"
    assert len(tomos[0].mrc_files) == 1
    assert len(tomos[0].zarr_dirs) == 1


def test_iter_tomograms_ignores_stray_files(tmp_path):
    # A .gitkeep / non-tomogram file is not grouped as a tomogram.
    tomos_dir = tmp_path / "acq" / "Reconstructions" / "ts_1" / "Tomograms"
    tomos_dir.mkdir(parents=True)
    (tomos_dir / "real.mrc").write_bytes(b"")
    (tomos_dir / ".gitkeep").write_text("")
    (tomos_dir / "notes.txt").write_text("")

    acq = _acq_loc(tmp_path / "acq")
    tomos = list(iter_tomograms(acq))
    assert [t.tomogram_id for t in tomos] == ["real"]


def test_iter_tomograms_duplicate_stem_across_groups(tmp_path):
    # Same stem under two group folders -> two distinct entities; the group is
    # part of the storage key, so both survive.
    for ts in ("ts_a", "ts_b"):
        d = tmp_path / "acq" / "Reconstructions" / ts / "Tomograms"
        d.mkdir(parents=True)
        (d / "dup.mrc").write_bytes(b"")

    acq = _acq_loc(tmp_path / "acq")
    tomos = list(iter_tomograms(acq))
    assert [(t.tomogram_id, t.reconstruction_alignment_id) for t in tomos] == [
        ("dup", "ts_a"),
        ("dup", "ts_b"),
    ]


def test_iter_tomograms_and_annotations_share_one_layout_across_arms(tmp_path):
    # Both arms share one nesting: files sit under
    # Reconstructions/{reconstruction_alignment_id}/{Tomograms,Annotations}/.
    tomos_dir = tmp_path / "acq" / "Reconstructions" / "grp1" / "Tomograms"
    anns_dir = tmp_path / "acq" / "Reconstructions" / "grp1" / "Annotations"
    tomos_dir.mkdir(parents=True)
    anns_dir.mkdir(parents=True)
    (tomos_dir / "backprojection.mrc").write_bytes(b"")
    (anns_dir / "seg.mrc").write_bytes(b"")

    acq = _acq_loc(tmp_path / "acq")
    tomos = list(iter_tomograms(acq))
    assert [(t.tomogram_id, t.reconstruction_alignment_id) for t in tomos] == [
        ("backprojection", "grp1"),
    ]
    anns = list(iter_annotations(acq))
    assert [(a.annotation_id, a.reconstruction_alignment_id) for a in anns] == [
        ("seg", "grp1")
    ]


def test_parse_targets_for_sample_includes_all_categories():
    sample = next(
        s for s in iter_samples(FIXTURES) if s.sample_id == "sample_chromatin"
    )
    targets = parse_targets_for_sample(sample)
    target_strs = {str(t) for t in targets}
    # sample.toml present
    assert any(t.endswith("sample.toml") for t in target_strs)
    # acquisition.toml only for Position_86 (Position_87 has none)
    assert sum(1 for t in target_strs if t.endswith("acquisition.toml")) == 1
    # mdoc present
    assert any(t.endswith(".mdoc") for t in target_strs)
    # mrc inside Tomograms (id-stem filename under Reconstructions/{ts_id}/)
    assert any(t.endswith("bp_3dctf_bin4.mrc") for t in target_strs)
    # zarr .zattrs
    assert any(t.endswith(".zattrs") for t in target_strs)
    # representative frame file (.eer for Position_86 and Position_87)
    eer_count = sum(1 for t in target_strs if t.endswith(".eer"))
    assert eer_count >= 1  # at least one rep frame per acquisition with a Frames/ dir
    # deterministic, unique
    assert sorted(targets, key=lambda p: str(p)) == targets
    assert len(set(targets)) == len(targets)


def test_parse_targets_for_sample_includes_md_run_toml():
    sim = next(
        s for s in iter_samples(FIXTURES) if s.sample_id == "SingleMolecule_sample_simulation"
    )
    targets = parse_targets_for_sample(sim)
    target_strs = {str(t) for t in targets}
    assert any(t.endswith("MdRuns/run_001/md_run.toml") for t in target_strs)


# ---------------------------------------------------------------------------
# dir_size_bytes
# ---------------------------------------------------------------------------


def test_dir_size_bytes_empty_dir(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    assert dir_size_bytes(d) == 0


def test_dir_size_bytes_flat_files(tmp_path):
    d = tmp_path / "flat"
    d.mkdir()
    (d / "a.bin").write_bytes(b"hello")        # 5 bytes
    (d / "b.bin").write_bytes(b"world!!")      # 7 bytes
    assert dir_size_bytes(d) == 12


def test_dir_size_bytes_nested_subdirs(tmp_path):
    d = tmp_path / "nested"
    d.mkdir()
    (d / "top.txt").write_bytes(b"x" * 10)
    sub = d / "sub"
    sub.mkdir()
    (sub / "mid.txt").write_bytes(b"y" * 20)
    zarr = d / "volume.zarr"
    zarr.mkdir()
    chunk = zarr / "0"
    chunk.mkdir()
    (chunk / "0.0.0").write_bytes(b"z" * 100)
    expected = 10 + 20 + 100
    assert dir_size_bytes(d) == expected


def test_dir_size_bytes_symlinks_not_followed(tmp_path):
    # Large file lives outside the measured directory.
    large = tmp_path / "large.bin"
    large.write_bytes(b"L" * 4096)

    d = tmp_path / "measured"
    d.mkdir()
    regular = d / "small.txt"
    regular.write_bytes(b"S" * 8)

    # Symlink pointing to the large file — must NOT add 4096.
    link = d / "link_to_large"
    link.symlink_to(large)

    # Broken symlink — must not raise.
    broken = d / "broken_link"
    broken.symlink_to(tmp_path / "nonexistent_target")

    result = dir_size_bytes(d)
    # Must not raise and must not count the target's 4096 bytes.
    assert result != pytest.approx(8 + 4096)
    # The regular file's bytes are counted; symlink metadata size is small.
    assert 8 <= result < 8 + 4096


def test_dir_size_bytes_nonexistent_path():
    result = dir_size_bytes(Path("/nonexistent/path/xyz_no_such_dir"))
    assert result == 0
