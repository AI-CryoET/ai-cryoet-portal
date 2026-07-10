"""Tests for catalog.assembler."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

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
    assert raw is not None
    assert raw.tomogram_id == "bp_3dctf_bin4"
    # tilt_series_id is derived from the Reconstructions/{ts_id}/ folder (== ts_1),
    # which matches the declared [[tilt_series]] block.
    assert raw.tilt_series_id == "ts_1"
    assert raw.image_size_x == 4
    # voxel_size is derived from the MRC header (not authored in the TOML)
    assert raw.voxel_size == pytest.approx(11.7197, rel=1e-4)
    assert raw.mrc_path is not None
    assert raw.zarr_path is not None
    assert raw.zarr_axes == "zyx"
    assert raw.zarr_scale == [11.72, 11.72, 11.72]

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

        [raw_tomogram]
        id = "tomo_good"
        """,
    )
    _make_mrc(
        sample_dir / "Good" / "Reconstructions" / "ts_good" / "Tomograms"
        / "tomo_good.mrc"
    )
    # Bad acquisition: target_tomogram references unknown tomogram
    _write(
        sample_dir / "Bad" / "acquisition.toml",
        """
        [acquisition]
        microscope = "Krios"

        [[annotation]]
        id = "ann1"
        type = "membrane_segmentation"
        target_tomogram = "ghost"
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
    assert good_raw is not None and good_raw.tomogram_id == "tomo_good"
    assert acqs["Good"].post_processed_tomogram == []
    # Bad is a synthesized placeholder (empty)
    assert acqs["Bad"].raw_tomogram is None
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


def test_tomogram_tilt_series_id_derived_from_folder(tmp_path):
    """The tomogram's tilt_series_id is injected from the enclosing
    Reconstructions/{ts_id}/ folder when it matches a declared [[tilt_series]]."""
    sample_dir = tmp_path / "sample_test"
    _write_minimal_sample_toml(sample_dir)
    _write(
        sample_dir / "acq1" / "acquisition.toml",
        """
        [acquisition]
        microscope = "Krios"

        [[tilt_series]]
        id = "ts_9"

        [raw_tomogram]
        id = "tomo1"
        """,
    )
    (sample_dir / "acq1" / "TiltSeries" / "ts_9").mkdir(parents=True)
    tomos = sample_dir / "acq1" / "Reconstructions" / "ts_9" / "Tomograms"
    _make_mrc(tomos / "tomo1.mrc")

    result = assemble_sample(_sample_loc(sample_dir))
    assert result.record is not None
    raw = result.record.acquisitions["acq1"].raw_tomogram
    assert raw is not None and raw.tilt_series_id == "ts_9"
    assert not any(
        w.category == "undeclared_reconstruction_group" for w in result.warnings
    )


def test_undeclared_reconstruction_group_leaves_tilt_series_id_none(tmp_path):
    """A tomogram under a Reconstructions/{ts_id}/ folder with no matching
    [[tilt_series]] keeps tilt_series_id=None and warns (injecting the
    undeclared id would make cross-ref re-validation drop the sample)."""
    sample_dir = tmp_path / "sample_test"
    _write_minimal_sample_toml(sample_dir)
    _write(
        sample_dir / "acq1" / "acquisition.toml",
        """
        [acquisition]
        microscope = "Krios"

        [raw_tomogram]
        id = "tomo1"
        """,
    )
    tomos = sample_dir / "acq1" / "Reconstructions" / "ts_ghost" / "Tomograms"
    _make_mrc(tomos / "tomo1.mrc")

    result = assemble_sample(_sample_loc(sample_dir))
    assert result.record is not None
    raw = result.record.acquisitions["acq1"].raw_tomogram
    assert raw is not None and raw.tilt_series_id is None
    warned = [
        w for w in result.warnings if w.category == "undeclared_reconstruction_group"
    ]
    assert len(warned) == 1
    assert "tomo1" in warned[0].message
    # The loader's own tilt_series_id derivation note for this same tomogram
    # must not also be forwarded — it has no dedicated category and would
    # otherwise surface as spurious extra_field/<unknown> noise alongside the
    # correct undeclared_reconstruction_group warning above.
    assert not any(w.category == "extra_field" for w in result.warnings)


def test_duplicate_tomogram_id_across_tilt_series_warns(tmp_path):
    """The same tomogram stem under two {ts_id} folders warns once and keeps the
    first (never silently overwrites)."""
    sample_dir = tmp_path / "sample_test"
    _write_minimal_sample_toml(sample_dir)
    _write(
        sample_dir / "acq1" / "acquisition.toml",
        """
        [acquisition]
        microscope = "Krios"

        [[tilt_series]]
        id = "ts_a"

        [[tilt_series]]
        id = "ts_b"

        [raw_tomogram]
        id = "dup"
        """,
    )
    for ts in ("ts_a", "ts_b"):
        (sample_dir / "acq1" / "TiltSeries" / ts).mkdir(parents=True)
        _make_mrc(
            sample_dir / "acq1" / "Reconstructions" / ts / "Tomograms" / "dup.mrc"
        )

    result = assemble_sample(_sample_loc(sample_dir))
    assert result.record is not None
    dupes = [w for w in result.warnings if w.category == "duplicate_tomogram_id"]
    assert len(dupes) == 1
    assert "dup" in dupes[0].message
    # Kept the first folder (ts_a, by sort order).
    raw = result.record.acquisitions["acq1"].raw_tomogram
    assert raw is not None and raw.tilt_series_id == "ts_a"


def test_duplicate_annotation_id_across_tilt_series_warns(tmp_path):
    """The same annotation stem under two {ts_id} folders warns once and keeps
    the first (never silently overwrites) — mirrors duplicate_tomogram_id."""
    sample_dir = tmp_path / "sample_test"
    _write_minimal_sample_toml(sample_dir)
    _write(
        sample_dir / "acq1" / "acquisition.toml",
        """
        [acquisition]
        microscope = "Krios"

        [[tilt_series]]
        id = "ts_a"

        [[tilt_series]]
        id = "ts_b"

        [raw_tomogram]
        id = "tomo1"

        [[annotation]]
        id = "dup"
        type = "segmentation"
        target_tomogram = "tomo1"
        """,
    )
    for ts in ("ts_a", "ts_b"):
        (sample_dir / "acq1" / "TiltSeries" / ts).mkdir(parents=True)
    _make_mrc(
        sample_dir / "acq1" / "Reconstructions" / "ts_a" / "Tomograms" / "tomo1.mrc"
    )
    for ts in ("ts_a", "ts_b"):
        anns = sample_dir / "acq1" / "Reconstructions" / ts / "Annotations"
        anns.mkdir(parents=True)
        (anns / "dup.mrc").write_bytes(b"")

    result = assemble_sample(_sample_loc(sample_dir))
    assert result.record is not None
    dupes = [w for w in result.warnings if w.category == "duplicate_annotation_id"]
    assert len(dupes) == 1
    assert "dup" in dupes[0].message
    # Kept the first folder (ts_a, by sort order) — never overwritten by ts_b.
    ann = result.record.acquisitions["acq1"].annotation[0]
    assert ann.files and "ts_a" in ann.files[0]


def test_annotation_without_target_tomogram_warns(tmp_path):
    """A declared annotation with no target_tomogram warns (the field is
    optional in the schema, so this is a warning rather than an error)."""
    sample_dir = tmp_path / "sample_test"
    _write_minimal_sample_toml(sample_dir)
    _write(
        sample_dir / "acq1" / "acquisition.toml",
        """
        [acquisition]
        microscope = "Krios"

        [[annotation]]
        id = "membrane"
        type = "segmentation"
        """,
    )
    # A declared annotation id must match a reconstruction file on disk (loader
    # rule): experimental annotations are files nested under Reconstructions/{ts}/.
    anns = sample_dir / "acq1" / "Reconstructions" / "ts_1" / "Annotations"
    anns.mkdir(parents=True)
    (anns / "membrane.mrc").write_bytes(b"")

    loc = _sample_loc(sample_dir)
    result = assemble_sample(loc)

    orphans = [
        w
        for w in result.warnings
        if w.category == "annotation_without_target_tomogram"
    ]
    assert len(orphans) == 1
    assert "membrane" in orphans[0].location
    assert "membrane" in orphans[0].message
    # The annotation is still kept — this is a warning, not an error.
    assert result.record is not None


def test_annotation_with_target_tomogram_does_not_warn(tmp_path):
    """An annotation that names an existing target_tomogram produces no
    annotation_without_target_tomogram warning."""
    sample_dir = tmp_path / "sample_test"
    _write_minimal_sample_toml(sample_dir)
    _write(
        sample_dir / "acq1" / "acquisition.toml",
        """
        [acquisition]
        microscope = "Krios"

        [raw_tomogram]
        id = "tomo1"

        [[annotation]]
        id = "membrane"
        type = "segmentation"
        target_tomogram = "tomo1"
        """,
    )
    # Declared tomogram/annotation ids must match reconstruction files on disk
    # (loader rule): experimental entities are files nested under Reconstructions/{ts}/.
    recon = sample_dir / "acq1" / "Reconstructions" / "ts_1"
    _make_mrc(recon / "Tomograms" / "tomo1.mrc")
    (recon / "Annotations").mkdir(parents=True)
    (recon / "Annotations" / "membrane.mrc").write_bytes(b"")

    loc = _sample_loc(sample_dir)
    result = assemble_sample(loc)

    orphans = [
        w
        for w in result.warnings
        if w.category == "annotation_without_target_tomogram"
    ]
    assert orphans == []
    assert result.record is not None


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
