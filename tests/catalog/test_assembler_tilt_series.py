"""Integration tests: assembler pulls tilt-series records into SampleRecord."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from schema.schema import DataSource

from catalog.assembler import assemble_sample
from catalog.discovery import SampleLocation


def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(dedent(content).lstrip())


def _write_minimal_sample_toml(sample_dir: Path) -> Path:
    """Write the smallest legal sample.toml under ``sample_dir``.

    Centralised so a schema rev to ``[sample]`` only touches one place.
    """
    path = sample_dir / "sample.toml"
    _write(
        path,
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"
        """,
    )
    return path


def _write_minimal_acquisition_toml(
    sample_dir: Path, acq_id: str = "Pos1", extra: str = ""
) -> Path:
    """Write the smallest legal acquisition.toml under ``sample_dir / acq_id``.

    ``extra`` is appended verbatim (after dedent/lstrip) for tests that need
    additional TOML blocks (e.g. ``[[post_processed_tomogram]]``).
    """
    path = sample_dir / acq_id / "acquisition.toml"
    body = """
        [acquisition]
        microscope = "Krios"
        """
    if extra:
        body = body + extra
    _write(path, body)
    return path


def _sample_loc(sample_dir: Path) -> SampleLocation:
    return SampleLocation(
        path=sample_dir,
        sample_id=sample_dir.name,
        sample_toml=sample_dir / "sample.toml",
        data_source=DataSource.experimental,
        dataset_type=None,
    )


_MDOC = """\
PixelSpacing = 2.93
Voltage = 300
TiltAxisAngle = 84.5

[ZValue = 0]
TiltAngle = -60.0
ExposureDose = 0.5

[ZValue = 1]
TiltAngle = -57.0
ExposureDose = 0.5
"""


def test_assembler_sets_acquisition_tilt_angles(tmp_path: Path) -> None:
    """The MDOC tilt-angle list lands on the ACQUISITION (not a tilt-series row).

    Tilt series are now researcher-authored; with no ``[[tilt_series]]`` block
    and no ``TiltSeries/`` folder, ``acq_file.tilt_series`` stays empty.
    """
    sample_dir = tmp_path / "sample_a"
    _write_minimal_sample_toml(sample_dir)
    _write_minimal_acquisition_toml(sample_dir)
    _write(sample_dir / "Pos1" / "Frames" / "ts.mdoc", _MDOC)
    (sample_dir / "Pos1" / "Frames" / "001.eer").write_bytes(b"")

    result = assemble_sample(_sample_loc(sample_dir))

    assert result.record is not None
    acq_file = result.record.acquisitions["Pos1"]
    assert acq_file.tilt_series == []
    assert acq_file.acquisition.tilt_angles == [
        pytest.approx(-60.0),
        pytest.approx(-57.0),
    ]
    # Acquisition path recorded for the UI's copy-path / file-browser buttons.
    assert acq_file.acquisition.path == str(sample_dir / "Pos1")


def test_assembler_enriches_authored_tilt_series(tmp_path: Path) -> None:
    """An authored ``[[tilt_series]]`` row is enriched with filesystem-derived
    fields (stack path, alignment artifacts, mtime) from its ``TiltSeries/{id}/``
    folder. ``is_aligned=true`` + alignment artifacts → no mismatch warning.
    """
    sample_dir = tmp_path / "sample_a"
    _write_minimal_sample_toml(sample_dir)
    _write_minimal_acquisition_toml(
        sample_dir,
        extra="""
        [[tilt_series]]
        id = "ts_a"
        derived_from = "Frames"
        is_aligned = true
        """,
    )
    ts_dir = sample_dir / "Pos1" / "TiltSeries" / "ts_a"
    (ts_dir / "stack").mkdir(parents=True)
    (ts_dir / "stack" / "ts_a.st").write_bytes(b"")
    (ts_dir / "alignment").mkdir(parents=True)
    (ts_dir / "alignment" / "ts_a.aln").write_text("alignment params\n")

    result = assemble_sample(_sample_loc(sample_dir))

    assert result.record is not None
    acq_file = result.record.acquisitions["Pos1"]
    assert len(acq_file.tilt_series) == 1
    ts = acq_file.tilt_series[0]
    assert ts.tilt_series_id == "ts_a"
    assert ts.derived_from == "Frames"
    assert ts.is_aligned is True
    assert ts.st_path == str(ts_dir / "stack" / "ts_a.st")
    assert ts.alignment_files == [str(ts_dir / "alignment" / "ts_a.aln")]
    assert ts.mtime is not None
    # PK parts injected from the path.
    assert ts.sample_id == "sample_a"
    assert ts.acquisition_id == "Pos1"
    # is_aligned matches on-disk artifacts → no mismatch warning.
    mismatch = [
        w for w in result.warnings if w.category == "tilt_series_alignment_mismatch"
    ]
    assert mismatch == []


def test_assembler_enriches_canonical_pascalcase_subfolders(tmp_path: Path) -> None:
    """The canonical ``Stack/`` + ``Alignment/`` (PascalCase) subfolders are
    discovered the same as the legacy lowercase layout above."""
    sample_dir = tmp_path / "sample_a"
    _write_minimal_sample_toml(sample_dir)
    _write_minimal_acquisition_toml(
        sample_dir,
        extra="""
        [[tilt_series]]
        id = "ts_a"
        derived_from = "Frames"
        is_aligned = true
        """,
    )
    ts_dir = sample_dir / "Pos1" / "TiltSeries" / "ts_a"
    (ts_dir / "Stack").mkdir(parents=True)
    (ts_dir / "Stack" / "ts_a.st").write_bytes(b"")
    (ts_dir / "Alignment").mkdir(parents=True)
    (ts_dir / "Alignment" / "ts_a.aln").write_text("alignment params\n")

    result = assemble_sample(_sample_loc(sample_dir))

    assert result.record is not None
    ts = result.record.acquisitions["Pos1"].tilt_series[0]
    assert ts.st_path == str(ts_dir / "Stack" / "ts_a.st")
    assert ts.alignment_files == [str(ts_dir / "Alignment" / "ts_a.aln")]
    mismatch = [
        w for w in result.warnings if w.category == "tilt_series_alignment_mismatch"
    ]
    assert mismatch == []


def test_assembler_records_acquisition_path_for_synthesized(
    tmp_path: Path,
) -> None:
    """Synthesized acquisitions (no acquisition.toml) still get ``acq.path``."""
    sample_dir = tmp_path / "sample_b"
    _write_minimal_sample_toml(sample_dir)
    # No acquisition.toml; presence of Frames/ alone triggers discovery.
    (sample_dir / "Pos1" / "Frames").mkdir(parents=True)
    _write(sample_dir / "Pos1" / "Frames" / "ts.mdoc", _MDOC)

    result = assemble_sample(_sample_loc(sample_dir))
    assert result.record is not None
    acq = result.record.acquisitions["Pos1"].acquisition
    assert acq.path == str(sample_dir / "Pos1")


def test_assembler_records_sample_path(tmp_path: Path) -> None:
    """The sample directory is recorded on ``sample.path``."""
    sample_dir = tmp_path / "sample_c"
    _write_minimal_sample_toml(sample_dir)
    _write_minimal_acquisition_toml(sample_dir)

    result = assemble_sample(_sample_loc(sample_dir))
    assert result.record is not None
    assert result.record.sample.path == str(sample_dir)


def test_assembler_records_sample_path_with_no_acquisitions(
    tmp_path: Path,
) -> None:
    """A sample with zero acquisitions still gets ``sample.path`` — this is the
    whole point: sample-level copy-path / Fileglancer actions must work even
    when there are no acquisitions to derive a path from."""
    sample_dir = tmp_path / "sample_d"
    _write_minimal_sample_toml(sample_dir)

    result = assemble_sample(_sample_loc(sample_dir))
    assert result.record is not None
    assert result.record.acquisitions == {}
    assert result.record.sample.path == str(sample_dir)


def test_assembler_records_tomogram_size_bytes(tmp_path: Path) -> None:
    """``tomograms.size_bytes`` is recorded from the MRC file's on-disk size."""
    mrcfile_pkg = pytest.importorskip("mrcfile")
    np = pytest.importorskip("numpy")

    sample_dir = tmp_path / "sample_c"
    _write_minimal_sample_toml(sample_dir)
    _write_minimal_acquisition_toml(
        sample_dir,
        extra="""
        [[post_processed_tomogram]]
        id = "tomo_a"
        """,
    )
    mrc_path = (
        sample_dir
        / "Pos1"
        / "Reconstructions"
        / "ts_1"
        / "Tomograms"
        / "tomo_a.mrc"
    )
    mrc_path.parent.mkdir(parents=True)
    with mrcfile_pkg.new(str(mrc_path), overwrite=True) as m:
        m.set_data(np.zeros((4, 4, 4), dtype=np.float32))
        m.voxel_size = 1.0

    result = assemble_sample(_sample_loc(sample_dir))
    assert result.record is not None
    tomo = result.record.acquisitions["Pos1"].post_processed_tomogram[0]
    assert tomo.size_bytes is not None
    assert tomo.size_bytes == mrc_path.stat().st_size


_PER_TILT_HEADER = """\
PixelSpacing = 1.7
Voltage = 200
TiltAxisAngle = 92.5
"""


def test_per_tilt_layout_sets_acquisition_tilt_angles(tmp_path: Path) -> None:
    """Gouauxlab-style frames dir (3 per-tilt MDOCs + EERs) → the acquisition's
    ``tilt_angles`` list (the parser collapses the group by filename angle).

    Per-tilt MDOCs no longer synthesize tilt-series rows; with no authored
    ``[[tilt_series]]`` block, ``acq_file.tilt_series`` stays empty.
    """
    sample_dir = tmp_path / "sample_gouaux"
    _write_minimal_sample_toml(sample_dir)
    _write_minimal_acquisition_toml(sample_dir)
    frames_dir = sample_dir / "Pos1" / "Frames"
    frames_dir.mkdir(parents=True)
    for idx, angle in enumerate(["-30.0", "0.0", "30.0"], start=1):
        (frames_dir / f"20241211_Hipp_42_{idx:03d}_{angle}.eer.mdoc").write_text(
            _PER_TILT_HEADER
        )
        (frames_dir / f"20241211_Hipp_42_{idx:03d}_{angle}.eer").write_bytes(b"")

    result = assemble_sample(_sample_loc(sample_dir))

    assert result.record is not None
    acq_file = result.record.acquisitions["Pos1"]
    assert acq_file.tilt_series == []
    assert acq_file.acquisition.tilt_angles == [
        pytest.approx(-30.0),
        pytest.approx(0.0),
        pytest.approx(30.0),
    ]


def test_assembler_keeps_tilt_series_despite_tomogram_id_typo(
    tmp_path: Path,
) -> None:
    """End-to-end: a tomogram id with no matching folder no longer discards a
    validly-declared tilt series in the same acquisition.

    Regression for the lightbox bug — the bad tomogram used to make the whole
    acquisition.toml unparseable, so no tilt-series row (hence no preview) was
    ever produced. Now the tomogram is dropped (with a warning) and the tilt
    series is enriched normally into a row.
    """
    sample_dir = tmp_path / "sample_typo"
    _write_minimal_sample_toml(sample_dir)
    _write_minimal_acquisition_toml(
        sample_dir,
        extra="""
        [[post_processed_tomogram]]
        id = "relion5_bin5_denoised"

        [[tilt_series]]
        id = "ts_a"
        derived_from = "Frames"
        """,
    )
    # The tilt-series folder matches its id; the tomogram file on disk has stem
    # 'denoised', not the declared 'relion5_bin5_denoised'.
    (sample_dir / "Pos1" / "TiltSeries" / "ts_a" / "stack").mkdir(parents=True)
    tomos = sample_dir / "Pos1" / "Reconstructions" / "ts_a" / "Tomograms"
    tomos.mkdir(parents=True)
    (tomos / "denoised.mrc").write_bytes(b"")

    result = assemble_sample(_sample_loc(sample_dir))

    assert result.record is not None
    acq = result.record.acquisitions["Pos1"]
    # The tilt series survived and is the canonical entity for the preview.
    assert [ts.tilt_series_id for ts in acq.tilt_series] == ["ts_a"]
    assert acq.post_processed_tomogram == []
    assert [
        w for w in result.warnings if w.category == "declared_id_without_folder"
    ]


def test_assembler_warns_undeclared_tilt_series_folder(tmp_path: Path) -> None:
    """A ``TiltSeries/{id}/`` folder on disk with no ``[[tilt_series]]`` block
    triggers an ``undeclared_tilt_series_folder`` warning (no row synthesized).
    """
    sample_dir = tmp_path / "sample_undeclared"
    _write_minimal_sample_toml(sample_dir)
    _write_minimal_acquisition_toml(sample_dir)
    (sample_dir / "Pos1" / "TiltSeries" / "ts_x" / "stack").mkdir(parents=True)

    result = assemble_sample(_sample_loc(sample_dir))

    assert result.record is not None
    assert result.record.acquisitions["Pos1"].tilt_series == []
    undeclared = [
        w
        for w in result.warnings
        if w.category == "undeclared_tilt_series_folder"
    ]
    assert len(undeclared) == 1
    assert "ts_x" in undeclared[0].location
    assert undeclared[0].severity == "warning"


def test_assembler_infos_template_placeholder_tilt_series_folder(
    tmp_path: Path,
) -> None:
    """A ``TiltSeries/tilt_series_id/`` folder — the literal placeholder name
    shipped in templates/sample_id_experimental — is a leftover, un-renamed
    template copy, not a real data problem, so it warns at "info" instead of
    "warning"."""
    sample_dir = tmp_path / "sample_undeclared"
    _write_minimal_sample_toml(sample_dir)
    _write_minimal_acquisition_toml(sample_dir)
    (sample_dir / "Pos1" / "TiltSeries" / "tilt_series_id" / "stack").mkdir(
        parents=True
    )

    result = assemble_sample(_sample_loc(sample_dir))

    undeclared = [
        w
        for w in result.warnings
        if w.category == "undeclared_tilt_series_folder"
    ]
    assert len(undeclared) == 1
    assert undeclared[0].severity == "info"


def test_assembler_warns_acquisition_without_tilt_series(tmp_path: Path) -> None:
    """An acquisition with raw Frames/ but no declared tilt series triggers an
    ``acquisition_without_tilt_series`` warning.

    These half-ingested acquisitions (typically SerialEM raw collection) still
    get a Frames-rendered thumbnail, so they're invisible in the tables but show
    no hero image on the detail pages; the warning surfaces them on /manage.
    """
    sample_dir = tmp_path / "sample_no_ts"
    _write_minimal_sample_toml(sample_dir)
    _write_minimal_acquisition_toml(sample_dir)
    _write(sample_dir / "Pos1" / "Frames" / "ts.mdoc", _MDOC)
    (sample_dir / "Pos1" / "Frames" / "001.eer").write_bytes(b"")

    result = assemble_sample(_sample_loc(sample_dir))

    assert result.record is not None
    assert result.record.acquisitions["Pos1"].tilt_series == []
    without_ts = [
        w
        for w in result.warnings
        if w.category == "acquisition_without_tilt_series"
    ]
    assert len(without_ts) == 1
    assert "Pos1" in without_ts[0].location


def test_assembler_no_without_tilt_series_warning_when_declared(
    tmp_path: Path,
) -> None:
    """A declared ``[[tilt_series]]`` block suppresses the
    ``acquisition_without_tilt_series`` warning even with Frames/ present.
    """
    sample_dir = tmp_path / "sample_with_ts"
    _write_minimal_sample_toml(sample_dir)
    _write_minimal_acquisition_toml(
        sample_dir,
        extra="""
        [[tilt_series]]
        id = "ts_a"
        derived_from = "Frames"
        """,
    )
    # A declared [[tilt_series]] requires a matching TiltSeries/{id}/ folder on
    # disk (else the whole acquisition.toml is rejected as unparseable).
    (sample_dir / "Pos1" / "TiltSeries" / "ts_a" / "stack").mkdir(parents=True)
    _write(sample_dir / "Pos1" / "Frames" / "ts.mdoc", _MDOC)
    (sample_dir / "Pos1" / "Frames" / "001.eer").write_bytes(b"")

    result = assemble_sample(_sample_loc(sample_dir))

    assert result.record is not None
    assert len(result.record.acquisitions["Pos1"].tilt_series) == 1
    assert [
        w
        for w in result.warnings
        if w.category == "acquisition_without_tilt_series"
    ] == []


def test_assembler_warns_is_aligned_mismatch(tmp_path: Path) -> None:
    """An authored ``is_aligned = true`` with no alignment artifacts on disk
    triggers a ``tilt_series_alignment_mismatch`` warning.
    """
    sample_dir = tmp_path / "sample_mismatch"
    _write_minimal_sample_toml(sample_dir)
    _write_minimal_acquisition_toml(
        sample_dir,
        extra="""
        [[tilt_series]]
        id = "ts_a"
        is_aligned = true
        """,
    )
    # Folder exists (so the id↔folder check passes) but has no alignment/.
    (sample_dir / "Pos1" / "TiltSeries" / "ts_a" / "stack").mkdir(parents=True)

    result = assemble_sample(_sample_loc(sample_dir))

    assert result.record is not None
    mismatch = [
        w for w in result.warnings if w.category == "tilt_series_alignment_mismatch"
    ]
    assert len(mismatch) == 1
    assert "ts_a" in mismatch[0].location
