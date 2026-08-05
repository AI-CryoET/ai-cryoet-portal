"""Tests for schema.loader (formerly scripts.validate)."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from schema.loader import load_sample_record
from schema.schema import DataSource
from schema.validate import main


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).lstrip())


def _minimal_sample(root: Path, *, project: str = "chromatin") -> Path:
    _write(
        root / "sample.toml",
        f"""
        [sample]
        data_source = "experimental"
        project = "{project}"
        """,
    )
    return root


def _minimal_acquisition(root: Path, name: str = "acq1") -> Path:
    acq_dir = root / name
    _write(acq_dir / "acquisition.toml", "[acquisition]\n")
    return acq_dir


# ── load_sample_record ───────────────────────────────────────────────────────


def test_missing_sample_toml(tmp_path):
    result = load_sample_record(tmp_path)
    assert result.record is None
    assert any("missing sample.toml" in e for e in result.sample_errors)
    assert result.warnings == []


def test_sample_toml_parse_error(tmp_path):
    (tmp_path / "sample.toml").write_text("this is = = not valid toml\n")
    result = load_sample_record(tmp_path)
    assert result.record is None
    assert any("TOML parse error" in e for e in result.sample_errors)


def test_acquisition_toml_parse_error(tmp_path):
    """Per-acquisition isolation: a bad acquisition.toml doesn't sink the sample."""
    _minimal_sample(tmp_path)
    (tmp_path / "acq1").mkdir()
    (tmp_path / "acq1" / "acquisition.toml").write_text("not = = valid\n")
    result = load_sample_record(tmp_path)
    assert result.record is not None  # sample-level still validates
    assert "acq1" in result.acquisition_errors
    assert "TOML parse error" in result.acquisition_errors["acq1"]
    assert "acq1" not in result.record.acquisitions


def test_minimal_valid_sample(tmp_path):
    _minimal_sample(tmp_path)
    result = load_sample_record(tmp_path)
    assert result.sample_errors == []
    assert result.acquisition_errors == {}
    assert result.warnings == []
    assert result.record is not None
    assert result.record.sample.data_source.value == "experimental"
    assert result.record.sample.project.value == "chromatin"
    assert result.record.sample.sample_id == tmp_path.name
    assert result.record.acquisitions == {}


def test_missing_required_field(tmp_path):
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.record is None
    assert any("project" in e for e in result.sample_errors)


def test_invalid_enum_value(tmp_path):
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "xray"
        project = "chromatin"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.record is None
    assert any("data_source" in e for e in result.sample_errors)


def test_extra_field_no_typo_only_generic_warning(tmp_path):
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"
        totally_unrelated_key = "foo"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.sample_errors == []
    assert result.record is not None
    typo_warnings = [w for w in result.warnings if "possible typo" in w]
    generic_warnings = [w for w in result.warnings if "not in schema" in w]
    assert typo_warnings == []
    assert any("totally_unrelated_key" in w for w in generic_warnings)


def test_extra_field_typo_produces_suggestion(tmp_path):
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"
        descriptiom = "typo here"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.sample_errors == []
    assert result.record is not None
    typo_warnings = [w for w in result.warnings if "possible typo" in w]
    assert len(typo_warnings) == 1
    assert "descriptiom" in typo_warnings[0]
    assert "description" in typo_warnings[0]
    assert "Sample" in typo_warnings[0]


def test_typo_on_nested_model(tmp_path):
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"

        [chromatin]
        bufffer = "typo"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.sample_errors == []
    typo_warnings = [w for w in result.warnings if "possible typo" in w]
    assert any("bufffer" in w and "buffer" in w and "Chromatin" in w for w in typo_warnings)


def test_typo_in_acquisition(tmp_path):
    _minimal_sample(tmp_path)
    _write(
        tmp_path / "acq1" / "acquisition.toml",
        """
        [acquisition]
        microscoope = "typo"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.sample_errors == []
    assert result.acquisition_errors == {}
    typo_warnings = [w for w in result.warnings if "possible typo" in w]
    assert any("microscoope" in w and "microscope" in w for w in typo_warnings)


def test_typo_warning_preserved_when_validation_fails(tmp_path):
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"
        descriptiom = "typo alongside a hard error"

        [chromatin]
        nucleosome_count = "not-an-int"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.record is None
    assert any("nucleosome_count" in e for e in result.sample_errors)
    typo_warnings = [w for w in result.warnings if "possible typo" in w]
    assert any("descriptiom" in w and "description" in w for w in typo_warnings)


def test_simulation_block_rejected_for_cryoet(tmp_path):
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"

        [simulation]
        dataset_type = "bulk"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.record is None
    assert any("experimental" in e and "simulation" in e for e in result.sample_errors)


def test_synapse_data_source_simulation_rejected(tmp_path):
    """Synapse data is never simulation-derived."""
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "simulation"
        project = "synapse"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.record is None
    assert any("synapse" in e and "simulation" in e for e in result.sample_errors)


def test_synapse_simulation_block_rejected(tmp_path):
    """A [simulation] block on a synapse sample fails even when data_source is
    unset (synapse implies experimental)."""
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        project = "synapse"

        [simulation]
        dataset_type = "bulk"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.record is None
    assert any("synapse" in e and "simulation" in e for e in result.sample_errors)


def test_synapse_md_source_block_rejected(tmp_path):
    """An [md_source] block on a synapse acquisition fails the whole sample
    (synapse implies experimental)."""
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        project = "synapse"
        """,
    )
    _write(
        tmp_path / "acq1" / "acquisition.toml",
        """
        [acquisition]

        [md_source]
        md_run_id = "x"
        frame = 1
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.record is None
    assert any("synapse" in e and "md_source" in e for e in result.sample_errors)


def test_label_block_happy_path(tmp_path):
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"

        [[label]]
        aunp_size_nm = 5.0
        aunp_type = "colloidal"
        fluorophore = "Alexa647"
        conjugation = "Fab"
        conjugation_target = "GluA2"

        [[label]]
        aunp_size_nm = 10.0
        aunp_type = "cluster"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.sample_errors == []
    assert result.warnings == []
    assert result.record is not None
    assert len(result.record.label) == 2
    assert result.record.label[0].aunp_size_nm == 5.0
    assert result.record.label[0].conjugation_target == "GluA2"
    assert result.record.label[1].aunp_type == "cluster"


def test_freezing_block_happy_path(tmp_path):
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"

        [freezing]
        grid_type = "Quantifoil R2/2"
        cryoprotectant = "none"
        method = "HPF"
        planchette_size = "3 mm"
        spacer_thickness = "100 um"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.sample_errors == []
    assert result.warnings == []
    assert result.record is not None
    assert result.record.freezing is not None
    assert result.record.freezing.method == "HPF"
    assert result.record.freezing.planchette_size == "3 mm"


def test_milling_block_happy_path(tmp_path):
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"

        [milling]
        scheme = "cryo-FIB"
        date = 2025-06-15
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.sample_errors == []
    assert result.warnings == []
    assert result.record is not None
    assert result.record.milling is not None
    assert result.record.milling.scheme == "cryo-FIB"
    assert result.record.milling.date.isoformat() == "2025-06-15"


def test_simulation_sample_happy_path(tmp_path):
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "simulation"
        project = "chromatin"

        [simulation]
        dataset_type = "single_molecule"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.sample_errors == []
    assert result.warnings == []
    assert result.record is not None
    assert result.record.sample.data_source.value == "simulation"
    assert result.record.simulation is not None
    assert result.record.simulation.dataset_type == "single_molecule"


def test_acquisition_with_tomogram_and_annotation(tmp_path):
    _minimal_sample(tmp_path)
    _write(
        tmp_path / "acq1" / "acquisition.toml",
        """
        [acquisition]
        resolution = 3.5

        [[raw_tomogram]]
        id = "tomo_001"
        pipeline = "AreTomo"
        derived_from = "ts_a"

        [[post_processed_tomogram]]
        id = "tomo_002"
        derived_from = ["tomo_001"]

        [[annotation]]
        id = "ann_001"

        [[tilt_series]]
        id = "ts_a"

        [[reconstruction_alignment]]
        id = "grp1"
        """,
    )
    # Tomograms/annotations are files nested under Reconstructions/{group_id}/,
    # independent of the tilt_series id.
    recon = tmp_path / "acq1" / "Reconstructions" / "grp1"
    (recon / "Tomograms").mkdir(parents=True)
    (recon / "Tomograms" / "tomo_001.mrc").touch()
    (recon / "Tomograms" / "tomo_002.mrc").touch()
    (recon / "Annotations").mkdir(parents=True)
    (recon / "Annotations" / "ann_001.json").touch()
    (tmp_path / "acq1" / "TiltSeries" / "ts_a").mkdir(parents=True)
    result = load_sample_record(tmp_path)
    assert result.sample_errors == []
    assert result.acquisition_errors == {}
    assert result.record is not None
    acq = result.record.acquisitions["acq1"]
    assert acq.raw_tomogram[0].tomogram_id == "tomo_001"
    assert acq.raw_tomogram[0].derived_from == "ts_a"
    assert [t.tomogram_id for t in acq.post_processed_tomogram] == ["tomo_002"]
    assert acq.reconstruction_alignment[0].reconstruction_alignment_id == "grp1"


def test_tomogram_derived_from_unknown(tmp_path):
    """Per-acquisition isolation: dangling derived_from fails just that acquisition."""
    _minimal_sample(tmp_path)
    _write(
        tmp_path / "acq1" / "acquisition.toml",
        """
        [acquisition]

        [[post_processed_tomogram]]
        id = "tomo_001"
        derived_from = ["ghost"]
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.record is not None
    assert "acq1" in result.acquisition_errors
    assert "ghost" in result.acquisition_errors["acq1"]
    assert "acq1" not in result.record.acquisitions


def test_tomogram_id_without_matching_folder_drops_entry(tmp_path):
    """A declared tomogram id with no matching folder is dropped with a warning,
    not failed — the acquisition still loads instead of being discarded whole."""
    _minimal_sample(tmp_path)
    _write(
        tmp_path / "acq1" / "acquisition.toml",
        """
        [acquisition]

        [[raw_tomogram]]
        id = "bp_3dctf_bin4"
        """,
    )
    # File stem doesn't match the declared id (typo'd on disk).
    tomo_dir = tmp_path / "acq1" / "Reconstructions" / "ts_a" / "Tomograms"
    tomo_dir.mkdir(parents=True)
    (tomo_dir / "bp_3dctf_bn4.mrc").touch()
    result = load_sample_record(tmp_path)
    assert result.record is not None
    # No longer a hard error: the acquisition is kept, the offender dropped.
    assert "acq1" not in result.acquisition_errors
    assert "acq1" in result.record.acquisitions
    assert result.record.acquisitions["acq1"].raw_tomogram == []
    # …surfaced as a warning, located at the acquisition-prefixed entity ref.
    warning = next(w for w in result.warnings if "no matching folder" in w)
    assert "acquisitions.acq1.tomogram[bp_3dctf_bin4]" in warning
    # Fuzzy suggestion should point at the close-but-typo'd folder.
    assert "bp_3dctf_bn4" in warning


def test_folder_mismatch_drops_only_offender_keeps_siblings(tmp_path):
    """A tomogram id typo drops only that tomogram — a validly-declared tilt
    series in the same acquisition.toml survives.

    Regression: a single folder mismatch used to invalidate the whole
    acquisition.toml, silently discarding correctly-declared tilt series (and
    thus disabling their previews).
    """
    _minimal_sample(tmp_path)
    _write(
        tmp_path / "acq1" / "acquisition.toml",
        """
        [acquisition]

        [[post_processed_tomogram]]
        id = "wrong_id"

        [[tilt_series]]
        id = "ts_a"
        """,
    )
    # The tilt-series folder matches; the tomogram file stem does not.
    (tmp_path / "acq1" / "TiltSeries" / "ts_a").mkdir(parents=True)
    tomo_dir = tmp_path / "acq1" / "Reconstructions" / "ts_a" / "Tomograms"
    tomo_dir.mkdir(parents=True)
    (tomo_dir / "denoised.mrc").touch()
    result = load_sample_record(tmp_path)
    assert result.record is not None
    assert "acq1" not in result.acquisition_errors
    acq = result.record.acquisitions["acq1"]
    assert acq.post_processed_tomogram == []  # folderless tomogram dropped
    assert [ts.tilt_series_id for ts in acq.tilt_series] == ["ts_a"]  # survived
    assert any("tomogram[wrong_id]" in w for w in result.warnings)


def test_annotation_id_without_matching_folder_drops_entry(tmp_path):
    """A folderless annotation is dropped with a warning; the valid tomogram
    sibling in the same acquisition.toml survives."""
    _minimal_sample(tmp_path)
    _write(
        tmp_path / "acq1" / "acquisition.toml",
        """
        [acquisition]

        [[raw_tomogram]]
        id = "tomo_001"

        [[annotation]]
        id = "membrain_seg_v10"
        """,
    )
    recon = tmp_path / "acq1" / "Reconstructions" / "ts_a"
    (recon / "Tomograms").mkdir(parents=True)
    (recon / "Tomograms" / "tomo_001.mrc").touch()
    # No matching annotation file.
    (recon / "Annotations").mkdir(parents=True)
    result = load_sample_record(tmp_path)
    assert result.record is not None
    assert "acq1" not in result.acquisition_errors
    acq = result.record.acquisitions["acq1"]
    assert acq.raw_tomogram[0].tomogram_id == "tomo_001"  # sibling survives
    assert acq.annotation == []  # fileless annotation dropped
    warning = next(w for w in result.warnings if "no matching folder" in w)
    assert "acquisitions.acq1.annotation[membrain_seg_v10]" in warning


def test_md_source_valid_reference(tmp_path):
    """A simulation acquisition referencing a declared md_run validates clean.

    MD runs are now authored as ``MdRuns/{id}/md_run.toml`` (the folder name is
    the id); the ``[[md_run]]`` block in sample.toml is deprecated.
    """
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "simulation"
        project = "chromatin"
        """,
    )
    _write(
        tmp_path / "MdRuns" / "run_a" / "md_run.toml",
        """
        seed = 42
        computer = "gpu01"
        """,
    )
    _write(
        tmp_path / "SyntheticCryoET" / "acq1" / "acquisition.toml",
        """
        [acquisition]

        [md_source]
        md_run_id = "run_a"
        frame = 1500
        """,
    )
    result = load_sample_record(tmp_path, data_source=DataSource.simulation)
    assert result.sample_errors == []
    assert result.acquisition_errors == {}
    assert result.record is not None
    assert {r.md_run_id for r in result.record.md_run} == {"run_a"}
    acq = result.record.acquisitions["acq1"]
    assert acq.md_source.md_run_id == "run_a"
    assert acq.md_source.frame == 1500


def test_md_source_dangling_md_run_id_warns(tmp_path):
    """A dangling md_run_id (no MdRuns/ folder) now WARNS rather than failing
    the acquisition — the acquisition is still kept (plan §4.4)."""
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "simulation"
        project = "chromatin"
        """,
    )
    _write(tmp_path / "MdRuns" / "run_a" / "md_run.toml", "seed = 1\n")
    _write(
        tmp_path / "SyntheticCryoET" / "acq_good" / "acquisition.toml",
        """
        [acquisition]

        [md_source]
        md_run_id = "run_a"
        frame = 1
        """,
    )
    _write(
        tmp_path / "SyntheticCryoET" / "acq_bad" / "acquisition.toml",
        """
        [acquisition]

        [md_source]
        md_run_id = "ghost"
        frame = 2
        """,
    )
    result = load_sample_record(tmp_path, data_source=DataSource.simulation)
    # Both acquisitions are kept; the dangling ref only warns.
    assert result.record is not None
    assert result.sample_errors == []
    assert "acq_good" in result.record.acquisitions
    assert "acq_bad" in result.record.acquisitions
    assert "acq_bad" not in result.acquisition_errors
    dangling = [
        w for w in result.warnings if w.startswith("dangling md_source ref:")
    ]
    assert len(dangling) == 1
    assert "ghost" in dangling[0]


def test_deprecated_md_run_block_in_sample_toml_ignored(tmp_path):
    """A stale [[md_run]] array in sample.toml is ignored with a warning (no
    longer a category error on experimental samples)."""
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"

        [[md_run]]
        id = "run_a"
        """,
    )
    result = load_sample_record(tmp_path)
    # The block is ignored, so the experimental sample still validates clean.
    assert result.record is not None
    assert result.record.md_run == []
    assert any(
        w.startswith("[[md_run]] in sample.toml is deprecated")
        for w in result.warnings
    )


def test_md_source_on_experimental_rejected(tmp_path):
    """An [md_source] block on an experimental sample fails the whole sample
    (not isolated) — the dangling-ref isolation path is simulation-only."""
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"
        """,
    )
    _write(
        tmp_path / "acq1" / "acquisition.toml",
        """
        [acquisition]

        [md_source]
        md_run_id = "x"
        frame = 1
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.record is None
    assert any(
        "md_source" in e and "experimental" in e for e in result.sample_errors
    )


def test_multiple_acquisitions(tmp_path):
    _minimal_sample(tmp_path)
    _minimal_acquisition(tmp_path, "acq_a")
    _minimal_acquisition(tmp_path, "acq_b")
    result = load_sample_record(tmp_path)
    assert result.sample_errors == []
    assert result.acquisition_errors == {}
    assert result.record is not None
    assert set(result.record.acquisitions) == {"acq_a", "acq_b"}
    for name, acq in result.record.acquisitions.items():
        assert acq.acquisition.acquisition_id == name


# ── reconstruction_alignment id ↔ disk reconciliation ────────────────────────


def test_raw_tomogram_derived_from_authored_tilt_series(tmp_path):
    """A raw_tomogram's derived_from is authored (not folder-derived) and
    equals the tilt series it was reconstructed from."""
    _minimal_sample(tmp_path)
    _write(
        tmp_path / "acq1" / "acquisition.toml",
        """
        [acquisition]

        [[raw_tomogram]]
        id = "tomo_001"
        derived_from = "ts_a"

        [[tilt_series]]
        id = "ts_a"
        """,
    )
    tomo_dir = tmp_path / "acq1" / "Reconstructions" / "grp1" / "Tomograms"
    tomo_dir.mkdir(parents=True)
    (tomo_dir / "tomo_001.mrc").touch()
    (tmp_path / "acq1" / "TiltSeries" / "ts_a").mkdir(parents=True)
    result = load_sample_record(tmp_path)
    assert result.acquisition_errors == {}
    assert result.record is not None
    assert result.record.acquisitions["acq1"].raw_tomogram[0].derived_from == "ts_a"


def test_declared_reconstruction_alignment_without_folder_drops_entry(tmp_path):
    """A declared [[reconstruction_alignment]] with no matching Reconstructions/
    folder is dropped with a warning, not failed."""
    _minimal_sample(tmp_path)
    _write(
        tmp_path / "acq1" / "acquisition.toml",
        """
        [acquisition]

        [[reconstruction_alignment]]
        id = "ghost_group"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.record is not None
    assert result.acquisition_errors == {}
    assert result.record.acquisitions["acq1"].reconstruction_alignment == []
    assert any(
        "ghost_group" in w and "no matching folder" in w for w in result.warnings
    )


def test_reconstruction_alignment_id_need_not_match_tilt_series_id(tmp_path):
    """The Reconstructions/{id}/ group id is independent of any tilt_series id."""
    _minimal_sample(tmp_path)
    _write(
        tmp_path / "acq1" / "acquisition.toml",
        """
        [acquisition]

        [[tilt_series]]
        id = "ts_a"

        [[reconstruction_alignment]]
        id = "totally_different_group_id"

        [[raw_tomogram]]
        id = "tomo_001"
        derived_from = "ts_a"
        """,
    )
    tomo_dir = (
        tmp_path / "acq1" / "Reconstructions" / "totally_different_group_id"
        / "Tomograms"
    )
    tomo_dir.mkdir(parents=True)
    (tomo_dir / "tomo_001.mrc").touch()
    (tmp_path / "acq1" / "TiltSeries" / "ts_a").mkdir(parents=True)
    result = load_sample_record(tmp_path)
    assert result.acquisition_errors == {}
    assert result.record is not None
    acq = result.record.acquisitions["acq1"]
    assert acq.reconstruction_alignment[0].reconstruction_alignment_id == (
        "totally_different_group_id"
    )
    assert acq.raw_tomogram[0].derived_from == "ts_a"


# ── dual-read: reconstruction.toml reconciliation ────────────────────────────


def test_legacy_acquisition_blocks_warn_deprecation(tmp_path):
    _minimal_sample(tmp_path)
    acq = tmp_path / "acq1"
    tdir = acq / "Reconstructions" / "grpA" / "Tomograms"
    tdir.mkdir(parents=True)
    (tdir / "ctf.mrc").write_bytes(b"")
    _write(acq / "acquisition.toml", '[acquisition]\n[[raw_tomogram]]\nid = "ctf"\n')
    result = load_sample_record(tmp_path)
    assert any("deprecated" in w and "grpA" in w for w in result.warnings)


def test_reconstruction_toml_id_must_match_folder_file(tmp_path):
    _minimal_sample(tmp_path)
    recon = tmp_path / "acq1" / "Reconstructions" / "grpA"
    (recon / "Tomograms").mkdir(parents=True)
    (recon / "Tomograms" / "ctf.mrc").write_bytes(b"")
    _write(tmp_path / "acq1" / "acquisition.toml", "[acquisition]\n")
    _write(
        recon / "reconstruction.toml",
        '[reconstruction_alignment]\n[[raw_tomogram]]\nid = "nope"\n',
    )
    result = load_sample_record(tmp_path)
    assert any("nope" in w and "no matching" in w.lower() for w in result.warnings)


def test_reconstruction_toml_cross_file_derived_from_dangling_warns(tmp_path):
    """A reconstruction.toml raw_tomogram.derived_from that names no tilt_series
    in acquisition.toml is downgraded to a warning, not an error — the group and
    its tomogram still load."""
    _minimal_sample(tmp_path)
    acq = tmp_path / "acq1"
    recon = acq / "Reconstructions" / "grpA"
    (recon / "Tomograms").mkdir(parents=True)
    (recon / "Tomograms" / "tomo_001.mrc").write_bytes(b"")
    _write(acq / "acquisition.toml", "[acquisition]\n[[tilt_series]]\nid = \"ts_a\"\n")
    (acq / "TiltSeries" / "ts_a").mkdir(parents=True)
    _write(
        recon / "reconstruction.toml",
        '[reconstruction_alignment]\n[[raw_tomogram]]\nid = "tomo_001"\n'
        'derived_from = "ts_ghost"\n',
    )
    result = load_sample_record(tmp_path)
    assert result.acquisition_errors == {}
    assert result.record is not None
    assert "tomo_001" in {
        t.tomogram_id
        for t in result.record.reconstructions["acq1"]["grpA"].raw_tomogram
    }
    assert any("ts_ghost" in w and "derived_from" in w for w in result.warnings)


def test_post_processed_derived_from_dropped_sibling_tomogram_warns(tmp_path):
    """The cross-group tomogram-id universe used to validate
    post_processed_tomogram.derived_from must reflect ids that actually survive
    per-group folder-match filtering. grpA declares a raw_tomogram "ghost" with
    no matching file (dropped), grpB's post_processed_tomogram "real" declares
    derived_from = ["ghost"] — this must warn, not pass silently against a
    stale pre-filter universe."""
    _minimal_sample(tmp_path)
    acq = tmp_path / "acq1"
    _write(acq / "acquisition.toml", "[acquisition]\n")

    grp_a = acq / "Reconstructions" / "grpA"
    (grp_a / "Tomograms").mkdir(parents=True)
    _write(
        grp_a / "reconstruction.toml",
        '[reconstruction_alignment]\n[[raw_tomogram]]\nid = "ghost"\n',
    )

    grp_b = acq / "Reconstructions" / "grpB"
    (grp_b / "Tomograms").mkdir(parents=True)
    (grp_b / "Tomograms" / "real.mrc").write_bytes(b"")
    _write(
        grp_b / "reconstruction.toml",
        '[reconstruction_alignment]\n[[post_processed_tomogram]]\nid = "real"\n'
        'derived_from = ["ghost"]\n',
    )

    result = load_sample_record(tmp_path)
    assert any(
        "ghost" in w and "no matching" in w.lower() for w in result.warnings
    )
    assert any(
        "ghost" in w and "derived_from" in w and "unknown tomogram" in w
        for w in result.warnings
    )


# ── main() ───────────────────────────────────────────────────────────────────


def test_main_wrong_argc(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == 2
    # argparse writes usage to stderr by default
    assert "usage" in capsys.readouterr().err.lower()


def test_main_not_a_directory(tmp_path, capsys):
    missing = tmp_path / "does_not_exist"
    rc = main([str(missing)])
    assert rc == 2
    assert "not a directory" in capsys.readouterr().err


def test_main_success(tmp_path, capsys):
    _minimal_sample(tmp_path)
    rc = main([str(tmp_path)])
    out = capsys.readouterr()
    assert rc == 0
    assert "OK" in out.out


def test_main_failure_returns_1(tmp_path, capsys):
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        """,
    )
    rc = main([str(tmp_path)])
    out = capsys.readouterr()
    assert rc == 1
    assert "FAIL" in out.err


def test_main_prints_typo_warning(tmp_path, capsys):
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"
        descriptiom = "typo"
        """,
    )
    rc = main([str(tmp_path)])
    out = capsys.readouterr()
    assert rc == 0
    assert "possible typo" in out.out
