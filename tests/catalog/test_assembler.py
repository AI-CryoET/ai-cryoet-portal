"""Tests for catalog.assembler."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from types import SimpleNamespace

import mrcfile
import numpy as np
import pytest

from schema.schema import DataSource, DatasetType

from catalog.assembler import (
    AssemblyResult,
    ScanIssue,
    assemble_sample,
)
from catalog.discovery import SampleLocation, iter_samples

FIXTURES = Path(__file__).parent / "fixtures"


# ── helpers ──────────────────────────────────────────────────────────────────


def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(dedent(content).lstrip())


def _write_minimal_sample_toml(sample_dir: Path, extra: str = "") -> Path:
    """Write the smallest legal sample.toml under ``sample_dir``.

    ``extra`` is appended verbatim inside the ``[sample]`` block for tests
    that need an additional field (e.g. ``description = "<FILL IN>"`` or
    a deliberate typo). Centralised so a schema rev to ``[sample]`` only
    touches one place.
    """
    path = sample_dir / "sample.toml"
    body = """
        [sample]
        data_source = "experimental"
        project = "chromatin"
        """
    if extra:
        body = body + "        " + extra.strip() + "\n"
    _write(path, body)
    return path


def _make_mrc(p: Path, shape=(4, 4, 4), voxel_size_x: float = 11.7197) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with mrcfile.new(str(p), overwrite=True) as m:
        m.set_data(np.zeros(shape, dtype=np.float32))
        m.voxel_size = voxel_size_x  # broadcast to xyz


def _make_zattrs(zarr_dir: Path, scale=(11.72, 11.72, 11.72)) -> None:
    zarr_dir.mkdir(parents=True, exist_ok=True)
    s = list(scale)
    (zarr_dir / ".zattrs").write_text(
        '{"multiscales": [{"axes": ['
        '{"name": "z"}, {"name": "y"}, {"name": "x"}], '
        '"datasets": [{"path": "0", "coordinateTransformations": '
        f'[{{"type": "scale", "scale": {s}}}]}}]}}]}}'
    )


def _sample_loc(
    sample_dir: Path,
    *,
    data_source: DataSource = DataSource.experimental,
    dataset_type: DatasetType | None = None,
) -> SampleLocation:
    return SampleLocation(
        path=sample_dir,
        sample_id=sample_dir.name,
        sample_toml=sample_dir / "sample.toml",
        data_source=data_source,
        dataset_type=dataset_type,
    )


# ── tests ────────────────────────────────────────────────────────────────────


def test_happy_path_chromatin_fixture():
    samples = {s.sample_id: s for s in iter_samples(FIXTURES)}
    sample_loc = samples["sample_chromatin"]
    result = assemble_sample(sample_loc)

    assert isinstance(result, AssemblyResult)
    assert result.errors == []
    assert result.record is not None
    assert result.record.sample.sample_id == "sample_chromatin"

    acqs = result.record.acquisitions
    assert "Position_86" in acqs
    assert "Position_87" in acqs  # synthesized — Frames-only

    # Position_87 should produce a missing_acquisition_toml warning
    missing = [
        w
        for w in result.warnings
        if w.category == "missing_acquisition_toml"
        and "Position_87" in w.location
    ]
    assert len(missing) == 1
    # New ScanIssue fields: acquisition-scope, warning severity, resolved to the
    # acquisition's acquisition.toml with the acquisition_id attached.
    m = missing[0]
    assert isinstance(m, ScanIssue)
    assert m.severity == "warning"
    assert m.scope == "acquisition"
    assert m.acquisition_id == "Position_87"
    assert m.file_kind == "acquisition_toml"
    assert m.file_path is not None and m.file_path.endswith(
        "Position_87/acquisition.toml"
    )
    assert m.sample_id == "sample_chromatin"

    # Position_86 — MDOC values populated
    p86 = acqs["Position_86"].acquisition
    assert p86.pixel_size == 2.93
    assert p86.voltage == 300.0

    # Raw tomogram populated from MRC + zarr parsers
    raw = acqs["Position_86"].raw_tomogram
    assert raw
    assert raw[0].tomogram_id == "bp_3dctf_bin4"
    # derived_from is authored in the TOML — the tilt series it was reconstructed from.
    assert raw[0].derived_from == "ts_1"
    assert raw[0].image_size_x == 4
    # voxel_size is derived from the MRC header (not authored in the TOML)
    assert raw[0].voxel_size == pytest.approx(11.7197, rel=1e-4)
    assert raw[0].mrc_path is not None
    assert raw[0].zarr_path is not None
    assert raw[0].zarr_axes == "zyx"
    assert raw[0].zarr_scale == [11.72, 11.72, 11.72]

    # Annotation files populated
    anns = {a.annotation_id: a for a in acqs["Position_86"].annotation}
    assert "membrain_seg_v10" in anns
    files = anns["membrain_seg_v10"].files
    assert files, "annotation files should be populated from disk"
    assert any(f.endswith("membrain_seg_v10.mrc") for f in files)
    assert any(f.endswith("membrain_seg_v10.json") for f in files)
    assert files == sorted(files)


def _build_basic_experimental_sample(
    sample_dir: Path,
    *,
    pixel_size: float = 2.93,
    voltage: float = 300.0,
    extra_sample_block: str = "",
) -> SampleLocation:
    _write(
        sample_dir / "sample.toml",
        f"""
        [sample]
        data_source = "experimental"
        project = "chromatin"
        description = "test"
        {extra_sample_block}
        """,
    )
    _write(
        sample_dir / "Pos1" / "acquisition.toml",
        """
        [acquisition]
        microscope = "Krios"

        [raw_tomogram]
        id = "tomo1"
        """,
    )
    _write(
        sample_dir / "Pos1" / "Frames" / "001.mdoc",
        f"""
        PixelSpacing = {pixel_size}
        Voltage = {voltage}

        [ZValue = 0]
        TiltAngle = -60.0
        ExposureDose = 0.5
        """,
    )
    # representative frame
    (sample_dir / "Pos1" / "Frames" / "001.eer").write_bytes(b"")
    tomo_dir = sample_dir / "Pos1" / "Reconstructions" / "Tomograms" / "tomo1"
    _make_mrc(tomo_dir / "recon.mrc")
    _make_zattrs(tomo_dir / "recon.ome.zarr")
    return _sample_loc(sample_dir)


def test_unparseable_mdoc_emits_warning(tmp_path):
    sample_dir = tmp_path / "sample_test"
    _write_minimal_sample_toml(sample_dir)
    _write(
        sample_dir / "Pos1" / "acquisition.toml",
        """
        [acquisition]
        microscope = "Krios"
        """,
    )
    _write(
        sample_dir / "Pos1" / "Frames" / "001.mdoc",
        """
        PixelSpacing = 2.93
        Voltage = not_a_number

        [ZValue = 0]
        TiltAngle = -60.0
        """,
    )

    loc = _sample_loc(sample_dir)
    result = assemble_sample(loc)

    # An unreadable MDOC produces two `unparseable_mdoc` warnings, both at the
    # acquisition's ``.Frames`` location: one from the acquisition MDOC field
    # parser and one from the acquisition-level tilt-angle parser. (Tilt
    # geometry is acquisition-level now — there is no per-tilt-series parser.)
    bad = [w for w in result.warnings if w.category == "unparseable_mdoc"]
    assert len(bad) == 2
    assert all(w.location.endswith("Pos1.Frames") for w in bad)
    # Parser categories carry their concrete offending file path + file_kind.
    assert all(w.file_kind == "mdoc" for w in bad)
    assert all(w.severity == "warning" and w.scope == "acquisition" for w in bad)
    assert all(w.acquisition_id == "Pos1" for w in bad)
    assert all(w.file_path is not None for w in bad)

    acq = result.record.acquisitions["Pos1"].acquisition
    assert acq.pixel_size is None
    assert acq.voltage is None


def test_synthesized_frames_only_acquisition(tmp_path):
    sample_dir = tmp_path / "sample_test"
    _write_minimal_sample_toml(sample_dir)
    # No acquisition.toml under Pos1 — Frames-only
    _write(
        sample_dir / "Pos1" / "Frames" / "001.mdoc",
        """
        PixelSpacing = 2.93
        Voltage = 300

        [ZValue = 0]
        TiltAngle = -60.0
        ExposureDose = 0.5
        """,
    )
    (sample_dir / "Pos1" / "Frames" / "001.eer").write_bytes(b"")

    loc = _sample_loc(sample_dir)
    result = assemble_sample(loc)

    assert result.record is not None
    missing = [
        w for w in result.warnings if w.category == "missing_acquisition_toml"
    ]
    assert len(missing) == 1
    assert missing[0].location == "acquisitions.Pos1"

    acq = result.record.acquisitions["Pos1"].acquisition
    assert acq.acquisition_id == "Pos1"
    # MDOC still populates the synthesized acquisition
    assert acq.pixel_size == 2.93
    assert acq.voltage == 300.0
    assert acq.camera == "Falcon"  # .eer present


def test_unparseable_acquisition_toml_isolated(tmp_path):
    """Bad acquisition.toml -> isolated; good one validates fully."""
    sample_dir = tmp_path / "sample_test"
    _write_minimal_sample_toml(sample_dir)
    # Good acquisition
    _write(
        sample_dir / "Good" / "acquisition.toml",
        """
        [acquisition]
        microscope = "Krios"

        [[raw_tomogram]]
        id = "tomo_good"
        """,
    )
    _make_mrc(
        sample_dir / "Good" / "Reconstructions" / "ts_good" / "Tomograms"
        / "tomo_good.mrc"
    )
    # Bad acquisition: post_processed_tomogram.derived_from references unknown tomogram
    _write(
        sample_dir / "Bad" / "acquisition.toml",
        """
        [acquisition]
        microscope = "Krios"

        [[post_processed_tomogram]]
        id = "tomo1"
        derived_from = ["ghost"]
        """,
    )

    loc = _sample_loc(sample_dir)
    result = assemble_sample(loc)

    assert result.record is not None
    # Bad gets synthesized as a placeholder with an unparseable warning
    bad = [
        w
        for w in result.warnings
        if w.category == "unparseable_acquisition_toml"
    ]
    assert len(bad) == 1
    assert bad[0].location == "acquisitions.Bad"

    acqs = result.record.acquisitions
    assert "Good" in acqs
    assert "Bad" in acqs
    # Good is fully validated and contains its raw tomogram declaration.
    good_raw = acqs["Good"].raw_tomogram
    assert good_raw and good_raw[0].tomogram_id == "tomo_good"
    assert acqs["Good"].post_processed_tomogram == []
    # Bad is a synthesized placeholder (empty)
    assert acqs["Bad"].raw_tomogram == []
    assert acqs["Bad"].post_processed_tomogram == []
    assert acqs["Bad"].annotation == []


def test_typo_warning_categorized(tmp_path):
    sample_dir = tmp_path / "sample_test"
    _write_minimal_sample_toml(sample_dir, extra='descriptiom = "x"')
    loc = _sample_loc(sample_dir)
    # The underlying Pydantic typo-detector emits a UserWarning; the assembler
    # then re-emits it as a categorized ScanIssue. We assert the UserWarning
    # is raised (and capture it) so it doesn't leak into the test summary.
    with pytest.warns(UserWarning, match="closely matches"):
        result = assemble_sample(loc)

    typos = [w for w in result.warnings if w.category == "possible_typo"]
    assert len(typos) == 1
    # location captured from "on Sample closely matches"
    assert typos[0].location == "Sample"


def test_unfilled_placeholder_warning_categorized(tmp_path):
    sample_dir = tmp_path / "sample_test"
    _write_minimal_sample_toml(sample_dir, extra='description = "<FILL IN>"')
    loc = _sample_loc(sample_dir)
    result = assemble_sample(loc)

    placeholders = [
        w for w in result.warnings if w.category == "unfilled_placeholder"
    ]
    assert len(placeholders) == 1
    # Loader emits "<dotted.path>: unfilled <FILL IN> placeholder"
    # so location is the dotted path.
    assert "description" in placeholders[0].location


def test_undeclared_tomogram_folder_warns(tmp_path):
    """A tomogram file under Reconstructions/{ts_id}/Tomograms with no tomogram
    block warns."""
    sample_dir = tmp_path / "sample_test"
    _write_minimal_sample_toml(sample_dir)
    _write(
        sample_dir / "acq1" / "acquisition.toml",
        """
        [acquisition]
        microscope = "Krios"
        """,
    )
    # File exists on disk but is not declared in the TOML.
    tomos = sample_dir / "acq1" / "Reconstructions" / "ts_1" / "Tomograms"
    tomos.mkdir(parents=True)
    (tomos / "stray_tomo.mrc").write_bytes(b"")

    loc = _sample_loc(sample_dir)
    result = assemble_sample(loc)

    undeclared = [
        w for w in result.warnings if w.category == "undeclared_tomogram_folder"
    ]
    assert len(undeclared) == 1
    assert "stray_tomo" in undeclared[0].location
    assert "stray_tomo" in undeclared[0].message


def test_undeclared_annotation_folder_warns(tmp_path):
    sample_dir = tmp_path / "sample_test"
    _write_minimal_sample_toml(sample_dir)
    _write(
        sample_dir / "acq1" / "acquisition.toml",
        """
        [acquisition]
        microscope = "Krios"
        """,
    )
    anns = sample_dir / "acq1" / "Reconstructions" / "ts_1" / "Annotations"
    anns.mkdir(parents=True)
    (anns / "stray_ann.mrc").write_bytes(b"")

    loc = _sample_loc(sample_dir)
    result = assemble_sample(loc)

    undeclared = [
        w for w in result.warnings if w.category == "undeclared_annotation_folder"
    ]
    assert len(undeclared) == 1
    assert "stray_ann" in undeclared[0].location
    assert "stray_ann" in undeclared[0].message


def test_reconstruction_alignment_enriched_from_folder(tmp_path):
    """A declared [[reconstruction_alignment]] whose folder exists on disk is
    enriched with alignment_files/mtime and no undeclared warning fires."""
    sample_dir = tmp_path / "sample_test"
    _write_minimal_sample_toml(sample_dir)
    _write(
        sample_dir / "acq1" / "acquisition.toml",
        """
        [acquisition]
        microscope = "Krios"

        [[reconstruction_alignment]]
        id = "grp1"

        [[raw_tomogram]]
        id = "tomo1"
        """,
    )
    tomos = sample_dir / "acq1" / "Reconstructions" / "grp1" / "Tomograms"
    _make_mrc(tomos / "tomo1.mrc")
    align_dir = sample_dir / "acq1" / "Reconstructions" / "grp1" / "Alignment"
    align_dir.mkdir(parents=True)
    (align_dir / "alignment.json").write_text("{}")

    result = assemble_sample(_sample_loc(sample_dir))
    assert result.record is not None
    ra = result.record.acquisitions["acq1"].reconstruction_alignment
    assert len(ra) == 1
    assert ra[0].reconstruction_alignment_id == "grp1"
    assert ra[0].alignment_files and "alignment.json" in ra[0].alignment_files[0]
    assert not any(
        w.category == "undeclared_reconstruction_alignment_folder"
        for w in result.warnings
    )


def test_migrated_layout_reconstruction_toml_no_undeclared_warning(tmp_path):
    """TRUE migrated layout: acquisition.toml holds only [acquisition]/
    [[tilt_series]] and each group's [reconstruction_alignment] lives in its
    Reconstructions/{group}/reconstruction.toml. The assembler must fold those
    groups into the reconciliation so NO undeclared_reconstruction_alignment_folder
    warning fires (regression: it previously told researchers to re-add the
    deprecated acquisition.toml block)."""
    sample_dir = tmp_path / "sample_test"
    _write_minimal_sample_toml(sample_dir)
    _write(
        sample_dir / "acq1" / "acquisition.toml",
        """
        [acquisition]
        microscope = "Krios"

        [[tilt_series]]
        id = "ts_1"
        """,
    )
    _write(
        sample_dir / "acq1" / "Reconstructions" / "grp1" / "reconstruction.toml",
        """
        [reconstruction_alignment]

        [[raw_tomogram]]
        id = "tomo1"
        """,
    )
    _make_mrc(
        sample_dir / "acq1" / "Reconstructions" / "grp1" / "Tomograms" / "tomo1.mrc"
    )

    result = assemble_sample(_sample_loc(sample_dir))
    assert result.record is not None
    assert not any(
        w.category == "undeclared_reconstruction_alignment_folder"
        for w in result.warnings
    )
    # The per-group reconstruction_alignment is enriched in place (alignment_files
    # would be empty here, but the group is matched — no warning is the assertion).
    assert "grp1" in result.record.reconstructions.get("acq1", {})


def test_undeclared_reconstruction_alignment_folder_warns(tmp_path):
    """A Reconstructions/{id}/ folder with no matching [[reconstruction_alignment]]
    warns but does not fail the sample."""
    sample_dir = tmp_path / "sample_test"
    _write_minimal_sample_toml(sample_dir)
    _write(
        sample_dir / "acq1" / "acquisition.toml",
        """
        [acquisition]
        microscope = "Krios"

        [[raw_tomogram]]
        id = "tomo1"
        """,
    )
    tomos = sample_dir / "acq1" / "Reconstructions" / "grp_ghost" / "Tomograms"
    _make_mrc(tomos / "tomo1.mrc")

    result = assemble_sample(_sample_loc(sample_dir))
    assert result.record is not None
    assert result.record.acquisitions["acq1"].reconstruction_alignment == []
    warned = [
        w
        for w in result.warnings
        if w.category == "undeclared_reconstruction_alignment_folder"
    ]
    assert len(warned) == 1
    assert "grp_ghost" in warned[0].message


def test_zero_voxel_header_flags_tomogram_and_warns(tmp_path):
    """An MRC whose header has no voxel size (cella=0) sets
    ``mrc_voxel_size_missing`` on the tomogram and emits an acquisition-scoped
    ``mrc_header_missing_voxel_size`` warning — a good header does neither."""
    sample_dir = tmp_path / "sample_test"
    _write_minimal_sample_toml(sample_dir)
    _write(
        sample_dir / "acq1" / "acquisition.toml",
        """
        [acquisition]
        microscope = "Krios"

        [[reconstruction_alignment]]
        id = "grp"

        [[raw_tomogram]]
        id = "good"

        [[raw_tomogram]]
        id = "bad"
        """,
    )
    tomos = sample_dir / "acq1" / "Reconstructions" / "grp" / "Tomograms"
    _make_mrc(tomos / "good.mrc", voxel_size_x=10.0)
    _make_mrc(tomos / "bad.mrc", voxel_size_x=0.0)  # cella=0 -> no voxel size

    result = assemble_sample(_sample_loc(sample_dir))
    assert result.record is not None
    by_id = {t.tomogram_id: t for t in result.record.acquisitions["acq1"].raw_tomogram}
    assert by_id["good"].mrc_voxel_size_missing is False
    assert by_id["bad"].mrc_voxel_size_missing is True

    warns = [
        w for w in result.warnings if w.category == "mrc_header_missing_voxel_size"
    ]
    assert len(warns) == 1
    w = warns[0]
    assert w.scope == "acquisition"
    assert w.acquisition_id == "acq1"
    assert "bad" in w.location
    assert w.file_kind == "mrc_header"


def test_same_tomogram_stem_in_two_groups_yields_two_entries(tmp_path):
    """The same stem under two Reconstructions/{id}/ groups is legal: each is a
    distinct tomogram, keyed by its group. No warning, no overwrite."""
    sample_dir = tmp_path / "sample_test"
    _write_minimal_sample_toml(sample_dir)
    _write(
        sample_dir / "acq1" / "acquisition.toml",
        """
        [acquisition]
        microscope = "Krios"

        [[reconstruction_alignment]]
        id = "grp_a"

        [[reconstruction_alignment]]
        id = "grp_b"

        [[raw_tomogram]]
        id = "dup"
        """,
    )
    for grp in ("grp_a", "grp_b"):
        _make_mrc(
            sample_dir / "acq1" / "Reconstructions" / grp / "Tomograms" / "dup.mrc"
        )

    result = assemble_sample(_sample_loc(sample_dir))
    assert result.record is not None
    assert not [w for w in result.warnings if w.category == "duplicate_tomogram_id"]
    raw = result.record.acquisitions["acq1"].raw_tomogram
    # Two distinct entries, one per group, each pointing at its own file.
    assert len(raw) == 2
    by_group = {t.reconstruction_alignment_id: t for t in raw}
    assert set(by_group) == {"grp_a", "grp_b"}
    assert "grp_a" in by_group["grp_a"].mrc_path
    assert "grp_b" in by_group["grp_b"].mrc_path
    # Distinct objects — not one aliased model stamped twice.
    assert by_group["grp_a"] is not by_group["grp_b"]


def test_hand_authored_group_id_cannot_split_the_uniqueness_check(tmp_path):
    """Id uniqueness is per alignment group, so a hand-authored
    reconstruction_alignment_id on a flat acquisition.toml block could otherwise
    put two same-id blocks in different buckets — and the assembler, keying on
    the id alone, would stamp one block's metadata onto both folders. The loader
    drops the authored value, so the file stays rejected as a duplicate."""
    sample_dir = tmp_path / "sample_test"
    _write_minimal_sample_toml(sample_dir)
    _write(
        sample_dir / "acq1" / "acquisition.toml",
        """
        [acquisition]
        microscope = "Krios"

        [[reconstruction_alignment]]
        id = "grp_a"

        [[reconstruction_alignment]]
        id = "grp_b"

        [[raw_tomogram]]
        id = "dup"
        reconstruction_alignment_id = "grp_a"
        pipeline = "pA"

        [[raw_tomogram]]
        id = "dup"
        reconstruction_alignment_id = "grp_b"
        pipeline = "pB"
        """,
    )
    for grp in ("grp_a", "grp_b"):
        _make_mrc(
            sample_dir / "acq1" / "Reconstructions" / grp / "Tomograms" / "dup.mrc"
        )

    result = assemble_sample(_sample_loc(sample_dir))
    bad = [
        w for w in result.warnings if w.category == "unparseable_acquisition_toml"
    ]
    assert len(bad) == 1
    assert "duplicate tomogram id 'dup'" in bad[0].message
    # Nothing survives from the rejected file — no pA/pB cross-contamination.
    assert result.record is not None
    assert result.record.acquisitions["acq1"].raw_tomogram == []


def test_same_post_processed_stem_in_two_groups_stays_post_processed(tmp_path):
    """The per-group copies of a legacy [[post_processed_tomogram]] block land
    in post_processed_tomogram, not raw_tomogram."""
    sample_dir = tmp_path / "sample_test"
    _write_minimal_sample_toml(sample_dir)
    _write(
        sample_dir / "acq1" / "acquisition.toml",
        """
        [acquisition]
        microscope = "Krios"

        [[reconstruction_alignment]]
        id = "grp_a"

        [[reconstruction_alignment]]
        id = "grp_b"

        [[post_processed_tomogram]]
        id = "dup"
        """,
    )
    for grp in ("grp_a", "grp_b"):
        _make_mrc(
            sample_dir / "acq1" / "Reconstructions" / grp / "Tomograms" / "dup.mrc"
        )

    result = assemble_sample(_sample_loc(sample_dir))
    assert result.record is not None
    acq = result.record.acquisitions["acq1"]
    assert acq.raw_tomogram == []
    post = {t.reconstruction_alignment_id: t for t in acq.post_processed_tomogram}
    assert set(post) == {"grp_a", "grp_b"}
    assert "grp_a" in post["grp_a"].mrc_path
    assert "grp_b" in post["grp_b"].mrc_path


def test_same_annotation_stem_in_two_groups_yields_two_entries(tmp_path):
    """Annotation stems are scoped to their group, same as tomograms."""
    sample_dir = tmp_path / "sample_test"
    _write_minimal_sample_toml(sample_dir)
    _write(
        sample_dir / "acq1" / "acquisition.toml",
        """
        [acquisition]
        microscope = "Krios"

        [[reconstruction_alignment]]
        id = "grp_a"

        [[reconstruction_alignment]]
        id = "grp_b"

        [[annotation]]
        id = "seg"
        """,
    )
    for grp in ("grp_a", "grp_b"):
        p = sample_dir / "acq1" / "Reconstructions" / grp / "Annotations" / "seg.star"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")

    result = assemble_sample(_sample_loc(sample_dir))
    assert result.record is not None
    assert not [w for w in result.warnings if w.category == "duplicate_annotation_id"]
    anns = result.record.acquisitions["acq1"].annotation
    assert len(anns) == 2
    by_group = {a.reconstruction_alignment_id: a for a in anns}
    assert set(by_group) == {"grp_a", "grp_b"}
    assert any("grp_a" in f for f in by_group["grp_a"].files)
    assert any("grp_b" in f for f in by_group["grp_b"].files)
    assert by_group["grp_a"] is not by_group["grp_b"]


@pytest.fixture
def assembled_sample_factory(tmp_path):
    """Stage a sample whose Reconstructions/{group}/ each carry a
    reconstruction.toml (per-group metadata), then assemble it.

    ``groups`` maps group_id -> {"raw_tomogram": [{"id": ..., "pipeline": ...}]}.
    Returns a namespace with ``warnings`` + ``record_tomograms()`` (flattened
    per-group tomograms carrying their reconstruction_alignment_id).
    """

    def _factory(*, groups):
        sample_dir = tmp_path / "sample_test"
        _write_minimal_sample_toml(sample_dir)
        ra_blocks = "".join(
            f'[[reconstruction_alignment]]\nid = "{g}"\n\n' for g in groups
        )
        _write(
            sample_dir / "acq1" / "acquisition.toml",
            f"""
            [acquisition]
            microscope = "Krios"

            {ra_blocks}""",
        )
        for group, blocks in groups.items():
            lines: list[str] = []
            for tomo in blocks.get("raw_tomogram", []):
                lines.append("[[raw_tomogram]]")
                lines.extend(f'{k} = "{v}"' for k, v in tomo.items())
                lines.append("")
            _write(
                sample_dir
                / "acq1"
                / "Reconstructions"
                / group
                / "reconstruction.toml",
                "\n".join(lines),
            )
            for tomo in blocks.get("raw_tomogram", []):
                _make_mrc(
                    sample_dir
                    / "acq1"
                    / "Reconstructions"
                    / group
                    / "Tomograms"
                    / f"{tomo['id']}.mrc"
                )
        result = assemble_sample(_sample_loc(sample_dir))

        def record_tomograms():
            out = []
            for group, rf in (result.record.reconstructions.get("acq1", {})).items():
                for t in (*rf.raw_tomogram, *rf.post_processed_tomogram):
                    out.append(
                        SimpleNamespace(
                            reconstruction_alignment_id=group,
                            tomogram_id=t.tomogram_id,
                            pipeline=t.pipeline,
                            mrc_path=t.mrc_path,
                        )
                    )
            return out

        return SimpleNamespace(
            warnings=result.warnings,
            record=result.record,
            record_tomograms=record_tomograms,
        )

    return _factory


def test_two_groups_sharing_a_stem_bind_per_group(assembled_sample_factory):
    """Two Reconstructions/ groups sharing a tomogram stem ``denoised``, each
    with its own reconstruction.toml, are two distinct tomograms — the group is
    part of the storage key. Both bind their own metadata and are enriched from
    their own file; neither clobbers the other."""
    result = assembled_sample_factory(
        groups={
            "A": {"raw_tomogram": [{"id": "denoised", "pipeline": "pA"}]},
            "B": {"raw_tomogram": [{"id": "denoised", "pipeline": "pB"}]},
        }
    )
    assert result.record is not None
    tomos = {
        (t.reconstruction_alignment_id, t.tomogram_id): t
        for t in result.record_tomograms()
    }
    assert tomos[("A", "denoised")].pipeline == "pA"
    assert tomos[("B", "denoised")].pipeline == "pB"
    assert tomos[("A", "denoised")].mrc_path and "A" in tomos[("A", "denoised")].mrc_path
    assert tomos[("B", "denoised")].mrc_path and "B" in tomos[("B", "denoised")].mrc_path


def test_two_groups_distinct_stems_bind_per_group(assembled_sample_factory):
    """Two Reconstructions/ groups with DISTINCT stems are NOT a duplicate —
    per-group metadata binds and each is filesystem-enriched, no warning."""
    result = assembled_sample_factory(
        groups={
            "A": {"raw_tomogram": [{"id": "recon_a", "pipeline": "pA"}]},
            "B": {"raw_tomogram": [{"id": "recon_b", "pipeline": "pB"}]},
        }
    )
    assert result.record is not None
    tomos = {
        (t.reconstruction_alignment_id, t.tomogram_id): t
        for t in result.record_tomograms()
    }
    assert tomos[("A", "recon_a")].pipeline == "pA"
    assert tomos[("B", "recon_b")].pipeline == "pB"
    assert tomos[("A", "recon_a")].mrc_path and "A" in tomos[("A", "recon_a")].mrc_path
    assert tomos[("B", "recon_b")].mrc_path and "B" in tomos[("B", "recon_b")].mrc_path


def test_deprecated_processing_log_warning_categorized(tmp_path):
    """A reconstruction group present on disk while acquisition.toml still
    carries the processing-log blocks (no reconstruction.toml) is the deprecated
    layout — the loader warning is categorized as deprecated_processing_log, not
    the generic extra_field bucket."""
    sample_dir = tmp_path / "sample_test"
    _write_minimal_sample_toml(sample_dir)
    _write(
        sample_dir / "acq1" / "acquisition.toml",
        """
        [acquisition]
        microscope = "Krios"

        [[reconstruction_alignment]]
        id = "grp1"

        [[raw_tomogram]]
        id = "tomo1"
        """,
    )
    _make_mrc(
        sample_dir / "acq1" / "Reconstructions" / "grp1" / "Tomograms" / "tomo1.mrc"
    )

    result = assemble_sample(_sample_loc(sample_dir))
    deprecated = [
        w for w in result.warnings if w.category == "deprecated_processing_log"
    ]
    assert len(deprecated) == 1
    assert "grp1" in deprecated[0].location
    assert deprecated[0].acquisition_id == "acq1"
    assert not any(w.category == "extra_field" for w in result.warnings)


def test_data_source_derived_from_directory(tmp_path):
    """data_source is no longer authored; the directory arm is the source of
    truth and is injected silently (no mismatch warning), overriding any
    legacy value still present in sample.toml."""
    sample_dir = tmp_path / "sample_test"
    # A legacy/stale authored value should simply be overridden by the arm.
    _write(
        sample_dir / "sample.toml",
        """
        [sample]
        data_source = "simulation"
        project = "chromatin"
        """,
    )
    loc = _sample_loc(sample_dir, data_source=DataSource.experimental)
    result = assemble_sample(loc)

    # The dropped mismatch-warning feature must not resurface.
    assert not any(
        w.category == "data_source_mismatch" for w in result.warnings
    )
    # Directory won: the record reflects experimental.
    assert result.record is not None
    assert result.record.sample.data_source == DataSource.experimental


def test_deprecated_md_run_block_warning(tmp_path):
    """A stale [[md_run]] array in sample.toml is ignored with a warning."""
    sample_dir = tmp_path / "sample_sim"
    _write(
        sample_dir / "sample.toml",
        """
        [sample]
        data_source = "simulation"
        project = "chromatin"

        [[md_run]]
        id = "legacy_run"
        seed = 1
        """,
    )
    loc = _sample_loc(
        sample_dir,
        data_source=DataSource.simulation,
        dataset_type=DatasetType.bulk,
    )
    result = assemble_sample(loc)

    deprecated = [
        w for w in result.warnings if w.category == "deprecated_md_run_block"
    ]
    assert len(deprecated) == 1
    # The whole array is stale, not one run — no single id to link.
    assert deprecated[0].md_run_id is None
    # The stale block is ignored: no md_run rows from sample.toml.
    assert result.record is not None
    assert result.record.md_run == []


def test_dangling_md_source_ref_warning(tmp_path):
    """An md_source ref with no matching MdRuns/ folder warns rather than
    failing the acquisition; the acquisition is still kept."""
    sample_dir = tmp_path / "sample_sim"
    _write(
        sample_dir / "sample.toml",
        """
        [sample]
        data_source = "simulation"
        project = "chromatin"
        """,
    )
    _write(
        sample_dir / "SyntheticCryoET" / "acq1" / "acquisition.toml",
        """
        [acquisition]

        [md_source]
        md_run_id = "ghost_run"
        frame = 1
        """,
    )
    loc = _sample_loc(
        sample_dir,
        data_source=DataSource.simulation,
        dataset_type=DatasetType.bulk,
    )
    result = assemble_sample(loc)

    dangling = [
        w for w in result.warnings if w.category == "dangling_md_source_ref"
    ]
    assert len(dangling) == 1
    assert "ghost_run" in dangling[0].message
    # The referenced (if dangling) run id is captured for the manage-page link.
    assert dangling[0].md_run_id == "ghost_run"
    # Acquisition still validates and is kept.
    assert result.record is not None
    assert "acq1" in result.record.acquisitions


def test_md_run_placeholder_warning_captures_run_id(tmp_path):
    """An unfilled placeholder inside a run's own MdRuns/{id}/md_run.toml is
    located as ``md_run[{id}]…`` so the manage page can link straight to that
    run's authoring form, not just the owning sample."""
    sample_dir = tmp_path / "sample_sim"
    _write(
        sample_dir / "sample.toml",
        """
        [sample]
        data_source = "simulation"
        project = "chromatin"
        """,
    )
    _write(
        sample_dir / "MdRuns" / "run_b" / "md_run.toml",
        """
        computer = "<FILL IN>"
        """,
    )
    loc = _sample_loc(
        sample_dir,
        data_source=DataSource.simulation,
        dataset_type=DatasetType.bulk,
    )
    result = assemble_sample(loc)

    placeholder = [
        w for w in result.warnings if w.category == "unfilled_placeholder"
    ]
    assert len(placeholder) == 1
    assert placeholder[0].location == "md_run[run_b].computer"
    assert placeholder[0].file_kind == "md_run_toml"
    assert placeholder[0].md_run_id == "run_b"


# ── _resolve_file (file-resolver) ──────────────────────────────────────────


def test_resolve_file_prefixes(tmp_path):
    """Each ``location`` prefix maps to the expected (file_kind, file_path,
    acquisition_id, md_run_id) via ``_resolve_file`` (plan §4.2)."""
    from catalog.assembler import _resolve_file

    sample_dir = tmp_path / "sample_x"
    loc = _sample_loc(sample_dir)

    # <root> / bare sample path → sample.toml, no acquisition.
    kind, path, acq, run_id = _resolve_file("<root>", loc)
    assert kind == "sample_toml"
    assert path == str(sample_dir / "sample.toml")
    assert acq is None
    assert run_id is None

    # acquisitions.{id}… → that acq's acquisition.toml + acquisition_id.
    kind, path, acq, run_id = _resolve_file("acquisitions.Pos1.tilt_series[ts1]", loc)
    assert kind == "acquisition_toml"
    assert path == str(sample_dir / "Pos1" / "acquisition.toml")
    assert acq == "Pos1"
    assert run_id is None

    # md_source.{id} → md_run.toml, no acquisition, the dangling ref's run id.
    kind, path, acq, run_id = _resolve_file("md_source.run_a", loc)
    assert kind == "md_run_toml"
    assert path == str(sample_dir / "md_run.toml")
    assert acq is None
    assert run_id == "run_a"

    # md_run[{id}].{field} → md_run.toml, the run's own id.
    kind, path, acq, run_id = _resolve_file("md_run[run_b].seed", loc)
    assert kind == "md_run_toml"
    assert acq is None
    assert run_id == "run_b"

    # Bare "md_run" (the deprecated-block warning, <root>-located in practice)
    # names no single run.
    kind, path, acq, run_id = _resolve_file("md_run", loc)
    assert kind == "md_run_toml"
    assert acq is None
    assert run_id is None

    # Unknown / model-name path falls through to sample.toml.
    kind, path, acq, run_id = _resolve_file("<unknown>", loc)
    assert kind == "sample_toml"
    assert acq is None
    assert run_id is None


def test_assembly_failed_emits_error_issue(tmp_path):
    """An unrecoverable sample.toml yields record=None plus a single
    ``assembly_failed`` error-severity, sample-scope issue at <root>."""
    sample_dir = tmp_path / "sample_broken"
    # Missing required ``project`` field → loader sample_errors.
    _write(
        sample_dir / "sample.toml",
        """
        [sample]
        """,
    )
    loc = _sample_loc(sample_dir)
    result = assemble_sample(loc)

    assert result.record is None
    assert result.errors
    failed = [w for w in result.warnings if w.category == "assembly_failed"]
    assert len(failed) == 1
    f = failed[0]
    assert f.severity == "error"
    assert f.scope == "sample"
    assert f.file_kind == "sample_toml"
    assert f.location == "<root>"
    assert f.sample_id == "sample_broken"
