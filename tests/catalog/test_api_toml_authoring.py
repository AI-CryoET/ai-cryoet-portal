"""Tests for ``POST /toml/{kind}`` (backend-authoritative TOML generation).

Asserts the endpoint seam: valid -> 200 clean value-only TOML +
Content-Disposition; invalid -> 422 field errors; empties omitted; extras
preserved; unknown kind -> 404; id omitted from md_run output.
"""

from __future__ import annotations

import tomllib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

pytest.importorskip("tomli_w")

from catalog import db, orm  # noqa: E402
from catalog.api.deps import get_session  # noqa: E402
from catalog.api.main import create_app  # noqa: E402
from schema.schema import DataSource, Project  # noqa: E402


@pytest.fixture
def client():
    return TestClient(create_app())


@pytest.fixture
def seeded_client(tmp_path):
    """Client with a DB holding one md_run, for the pull-from-API load seam."""
    engine = db.make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    db.init_schema(engine)
    Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    s = Session()
    try:
        s.add(
            orm.SampleORM(
                sample_id="samp1",
                data_source=DataSource.simulation,
                project=Project.chromatin,
                path="/data/samp1",
            )
        )
        s.add(orm.MdRunORM(sample_id="samp1", md_run_id="run01", seed=42, timestep=2.0))
        s.add(
            orm.AcquisitionORM(
                sample_id="samp1",
                acquisition_id="Position_1",
                resolution=3.4,
                path="/data/samp1/Position_1",
            )
        )
        s.add(
            orm.MdSourceORM(
                sample_id="samp1", acquisition_id="Position_1", md_run_id="run01"
            )
        )
        s.add(
            orm.TiltSeriesORM(
                sample_id="samp1",
                acquisition_id="Position_1",
                tilt_series_id="ts_raw",
                derived_from="Frames",
            )
        )
        s.add(
            orm.TiltSeriesORM(
                sample_id="samp1",
                acquisition_id="Position_1",
                tilt_series_id="ts_aligned",
                derived_from="ts_raw",
            )
        )
        s.commit()
    finally:
        s.close()

    app = create_app()
    app.state.engine = engine

    def override():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override
    return TestClient(app)


def test_valid_md_run_downloads_clean_toml(client):
    resp = client.post(
        "/toml/md_run",
        json={"md_run_id": "run01", "seed": 42, "timestep": 2.0},
    )
    assert resp.status_code == 200
    assert resp.headers["content-disposition"] == 'attachment; filename="md_run.toml"'
    body = resp.text
    # Clean value-only: no comments, no #:schema pragma.
    assert "#" not in body
    parsed = tomllib.loads(body)
    # Directory-derived id is not written into the file.
    assert "id" not in parsed and "md_run_id" not in parsed
    assert parsed == {"seed": 42, "timestep": 2.0}


def test_empty_optional_fields_omitted(client):
    resp = client.post("/toml/md_run", json={"md_run_id": "run01", "seed": 7})
    assert resp.status_code == 200
    parsed = tomllib.loads(resp.text)
    assert parsed == {"seed": 7}  # unfilled optionals absent, not null/empty


def test_invalid_input_returns_422_with_field_errors(client):
    resp = client.post(
        "/toml/md_run",
        json={"md_run_id": "bad id with spaces", "seed": "not-an-int"},
    )
    assert resp.status_code == 422
    errors = resp.json()["errors"]
    located = {e["loc"][-1] for e in errors}
    assert "md_run_id" in located
    assert "seed" in located
    # Errors are JSON-serializable (loc/msg/type only).
    for e in errors:
        assert set(e) >= {"loc", "msg", "type"}


def test_missing_required_id_returns_422(client):
    resp = client.post("/toml/md_run", json={"seed": 1})
    assert resp.status_code == 422
    located = {e["loc"][-1] for e in resp.json()["errors"]}
    assert "md_run_id" in located


def test_extra_fields_preserved(client):
    resp = client.post(
        "/toml/md_run",
        json={"md_run_id": "run01", "custom_note": "hello"},
    )
    assert resp.status_code == 200
    assert tomllib.loads(resp.text) == {"custom_note": "hello"}


def test_non_toml_serializable_extra_returns_422_not_500(client):
    # extra="allow" lets a nested null through validation; it must not crash
    # tomli_w into a 500 (endpoint is status-discriminated).
    resp = client.post(
        "/toml/md_run",
        json={"md_run_id": "run01", "weird": {"k": None}},
    )
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["type"] == "toml_serialization"


def test_unknown_kind_returns_404(client):
    resp = client.post("/toml/not_a_kind", json={"md_run_id": "x"})
    assert resp.status_code == 404


# ── Seed mode: upload (parse) ───────────────────────────────────────────────


def test_parse_populates_fields(client):
    resp = client.post(
        "/toml/md_run/parse", json={"toml": "seed = 42\ntimestep = 2.0\n"}
    )
    assert resp.status_code == 200
    assert resp.json()["fields"] == {"seed": 42, "timestep": 2.0}


def test_parse_bad_toml_returns_422(client):
    resp = client.post("/toml/md_run/parse", json={"toml": "this is = = not toml"})
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["type"] == "toml_parse"


def test_uploaded_extra_survives_round_trip(client):
    # Parse an uploaded file carrying an extra, then generate from the parsed
    # state: the extra must reach the downloaded output (endpoint seam, AC#3).
    parsed = client.post(
        "/toml/md_run/parse",
        json={"toml": 'seed = 1\ncustom_note = "keep me"\n'},
    ).json()["fields"]
    parsed["md_run_id"] = "run01"  # file is id-less; the form supplies it
    out = client.post("/toml/md_run", json=parsed)
    assert out.status_code == 200
    assert tomllib.loads(out.text) == {"seed": 1, "custom_note": "keep me"}


def test_custom_typed_fields_serialize_as_their_type(client):
    # A boolean/number custom field serializes as that TOML type (AC#4).
    resp = client.post(
        "/toml/md_run",
        json={"md_run_id": "run01", "is_final": True, "replicate": 3},
    )
    assert resp.status_code == 200
    parsed = tomllib.loads(resp.text)
    assert parsed == {"is_final": True, "replicate": 3}
    assert isinstance(parsed["is_final"], bool)
    assert isinstance(parsed["replicate"], int)


# ── Seed mode: pull-from-API (load) ─────────────────────────────────────────


def test_load_by_id_returns_fields(seeded_client):
    resp = seeded_client.get("/toml/md_run/load/run01")
    assert resp.status_code == 200
    assert resp.json()["fields"] == {"md_run_id": "run01", "seed": 42, "timestep": 2.0}


def test_load_md_run_returns_directory_path(seeded_client):
    # md_run has no path column of its own: the directory is derived from the
    # owning sample's path + the MdRuns/{id} convention.
    resp = seeded_client.get("/toml/md_run/load/run01")
    assert resp.status_code == 200
    assert resp.json()["path"] == "/data/samp1/MdRuns/run01"


def test_load_md_run_path_is_null_when_sample_has_no_path(seeded_client):
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(
        bind=seeded_client.app.state.engine, future=True, expire_on_commit=False
    )
    s = Session()
    try:
        s.add(
            orm.SampleORM(
                sample_id="samp_nopath",
                data_source=DataSource.simulation,
                project=Project.chromatin,
            )
        )
        s.add(orm.MdRunORM(sample_id="samp_nopath", md_run_id="run02", seed=1))
        s.commit()
    finally:
        s.close()

    resp = seeded_client.get("/toml/md_run/load/run02")
    assert resp.status_code == 200
    assert resp.json()["path"] is None


def test_load_unknown_id_returns_404(seeded_client):
    assert seeded_client.get("/toml/md_run/load/nope").status_code == 404


# ── Fresh on-disk read at load + OCC baseline (source disk vs catalog) ───────


def test_load_md_run_reads_live_disk_file(seeded_client, tmp_path):
    # md_run has no path column: its directory is the owning sample's path +
    # MdRuns/{id}. With a readable md_run.toml under the data root, load returns
    # the FILE's parsed fields + exact text as baseline, flagged source='disk'.
    from sqlalchemy.orm import sessionmaker

    seeded_client.app.state.data_root_resolved = tmp_path.resolve()
    sample_dir = tmp_path / "Sim" / "SS1"
    run_dir = sample_dir / "MdRuns" / "runX"
    run_dir.mkdir(parents=True)
    text = "seed = 7\ntimestep = 1.5\n"
    (run_dir / "md_run.toml").write_text(text)

    Session = sessionmaker(
        bind=seeded_client.app.state.engine, future=True, expire_on_commit=False
    )
    s = Session()
    try:
        s.add(
            orm.SampleORM(
                sample_id="SS1",
                data_source=DataSource.simulation,
                project=Project.chromatin,
                path=str(sample_dir),
            )
        )
        s.add(orm.MdRunORM(sample_id="SS1", md_run_id="runX", seed=99, timestep=9.9))
        s.commit()
    finally:
        s.close()

    body = seeded_client.get("/toml/md_run/load/runX").json()
    assert body["source"] == "disk"
    assert body["baseline"] == text
    # Fields come from the FILE (id-less, seed=7), not the DB row (seed=99).
    assert body["fields"] == {"seed": 7, "timestep": 1.5}
    assert body["path"] == f"{sample_dir}/MdRuns/runX"


def test_load_md_run_falls_back_to_catalog_without_data_root(seeded_client):
    # No data_root_resolved configured → the guarded disk read raises and load
    # falls back to the DB reconstruction, flagged source='catalog', no baseline.
    body = seeded_client.get("/toml/md_run/load/run01").json()
    assert body["source"] == "catalog"
    assert body["baseline"] is None
    assert body["fields"] == {"md_run_id": "run01", "seed": 42, "timestep": 2.0}


def test_load_falls_back_to_catalog_when_file_missing_under_root(seeded_client, tmp_path):
    # Data root configured, but the record's derived directory is outside it
    # (samp1.path=/data/samp1) so no file is readable → catalog fallback.
    seeded_client.app.state.data_root_resolved = tmp_path.resolve()
    body = seeded_client.get("/toml/md_run/load/run01").json()
    assert body["source"] == "catalog"
    assert body["baseline"] is None


def test_load_unsupported_kind_returns_404(seeded_client):
    # md_run, acquisition, sample are supported; an unknown kind 404s.
    assert seeded_client.get("/toml/not_a_kind/load/x").status_code == 404


# ── Acquisition form (issue 05): [acquisition] + [[tilt_series]] + [md_source] ─


def test_valid_acquisition_downloads_nested_toml(client):
    resp = client.post(
        "/toml/acquisition",
        json={
            "acquisition": {
                "acquisition_id": "Position_1",
                "resolution": 3.4,
                "acquisition_quality": 4,
            },
            "tilt_series": [
                {"tilt_series_id": "ts_raw", "derived_from": "Frames"},
                {"tilt_series_id": "ts_aligned", "derived_from": "ts_raw"},
            ],
        },
    )
    assert resp.status_code == 200
    assert resp.headers["content-disposition"] == (
        'attachment; filename="acquisition.toml"'
    )
    parsed = tomllib.loads(resp.text)
    # Directory-derived acquisition id is dropped; [acquisition] keeps its values.
    assert "acquisition_id" not in parsed["acquisition"]
    assert parsed["acquisition"] == {"resolution": 3.4, "acquisition_quality": 4}
    # [[tilt_series]] entries survive; ids are written (folder names).
    assert [ts["id"] for ts in parsed["tilt_series"]] == ["ts_raw", "ts_aligned"]
    assert parsed["tilt_series"][1]["derived_from"] == "ts_raw"
    # No empty md_source / processing-log tables leak into the output.
    assert "md_source" not in parsed
    assert "post_processed_tomogram" not in parsed
    assert "annotation" not in parsed


def test_acquisition_quality_out_of_range_returns_422(client):
    resp = client.post(
        "/toml/acquisition",
        json={"acquisition": {"acquisition_id": "Position_1", "acquisition_quality": 7}},
    )
    assert resp.status_code == 422
    located = {tuple(e["loc"]) for e in resp.json()["errors"]}
    assert ("acquisition", "acquisition_quality") in located


def test_acquisition_md_source_emitted(client):
    resp = client.post(
        "/toml/acquisition",
        json={
            "acquisition": {"acquisition_id": "Position_1"},
            "md_source": {"md_run_id": "run01", "frame": 5},
        },
    )
    assert resp.status_code == 200
    parsed = tomllib.loads(resp.text)
    assert parsed["md_source"] == {"md_run_id": "run01", "frame": 5}


def test_acquisition_dangling_tilt_series_ref_returns_422(client):
    resp = client.post(
        "/toml/acquisition",
        json={
            "acquisition": {"acquisition_id": "Position_1"},
            "tilt_series": [{"tilt_series_id": "ts1", "derived_from": "nope"}],
        },
    )
    assert resp.status_code == 422


def test_acquisition_parse_round_trips_nested_tables(client):
    toml = (
        "[acquisition]\nresolution = 3.4\n\n"
        '[[tilt_series]]\nid = "ts_raw"\nderived_from = "Frames"\n'
    )
    parsed = client.post("/toml/acquisition/parse", json={"toml": toml}).json()["fields"]
    assert parsed["acquisition"] == {"resolution": 3.4}
    assert parsed["tilt_series"] == [{"id": "ts_raw", "derived_from": "Frames"}]


# ── md_run_id suggestions + composite acquisition load ──────────────────────


def test_md_run_id_suggestions(seeded_client):
    resp = seeded_client.get("/toml/md-run-ids/samp1")
    assert resp.status_code == 200
    assert resp.json()["ids"] == ["run01"]


def test_tilt_series_ids_for_an_acquisition(seeded_client):
    resp = seeded_client.get("/toml/tilt-series-ids/samp1/Position_1")
    assert resp.status_code == 200
    assert resp.json()["ids"] == ["ts_aligned", "ts_raw"]


def test_tilt_series_ids_empty_for_unknown_acquisition(seeded_client):
    resp = seeded_client.get("/toml/tilt-series-ids/samp1/nope")
    assert resp.status_code == 200
    assert resp.json()["ids"] == []


def test_acquisition_load_requires_sample_id(seeded_client):
    assert seeded_client.get("/toml/acquisition/load/Position_1").status_code == 422


def test_acquisition_load_by_composite_id(seeded_client):
    resp = seeded_client.get("/toml/acquisition/load/Position_1?sample_id=samp1")
    assert resp.status_code == 200
    body = resp.json()
    fields = body["fields"]
    assert fields["acquisition"]["acquisition_id"] == "Position_1"
    assert fields["acquisition"]["resolution"] == 3.4
    assert fields["md_source"]["md_run_id"] == "run01"
    assert [ts["tilt_series_id"] for ts in fields["tilt_series"]] == [
        "ts_aligned",
        "ts_raw",
    ]
    assert body["path"] == "/data/samp1/Position_1"


def test_acquisition_load_path_is_null_when_unset(seeded_client):
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(
        bind=seeded_client.app.state.engine, future=True, expire_on_commit=False
    )
    s = Session()
    try:
        s.add(orm.AcquisitionORM(sample_id="samp1", acquisition_id="Position_2"))
        s.commit()
    finally:
        s.close()

    resp = seeded_client.get("/toml/acquisition/load/Position_2?sample_id=samp1")
    assert resp.status_code == 200
    assert resp.json()["path"] is None


def test_load_acquisition_reads_live_disk_file(seeded_client, tmp_path):
    # A readable acquisition.toml under the data root wins over the DB row: load
    # returns the file's parsed fields + exact text as baseline, source='disk'.
    from sqlalchemy.orm import sessionmaker

    seeded_client.app.state.data_root_resolved = tmp_path.resolve()
    acq_dir = tmp_path / "Sim" / "samp1" / "Position_9"
    acq_dir.mkdir(parents=True)
    text = "[acquisition]\nresolution = 9.9\n"
    (acq_dir / "acquisition.toml").write_text(text)

    Session = sessionmaker(
        bind=seeded_client.app.state.engine, future=True, expire_on_commit=False
    )
    s = Session()
    try:
        s.add(
            orm.AcquisitionORM(
                sample_id="samp1",
                acquisition_id="Position_9",
                resolution=1.1,
                path=str(acq_dir),
            )
        )
        s.commit()
    finally:
        s.close()

    body = seeded_client.get(
        "/toml/acquisition/load/Position_9?sample_id=samp1"
    ).json()
    assert body["source"] == "disk"
    assert body["baseline"] == text
    # Fields come from the FILE (resolution 9.9), not the DB row (1.1).
    assert body["fields"]["acquisition"]["resolution"] == 9.9
    assert body["path"] == str(acq_dir)


# ── Issue 06: processing log (tomograms, annotations, cross-refs) ───────────


def test_acquisition_processing_log_round_trips(client):
    # [[raw_tomogram]], [[post_processed_tomogram]], [[annotation]] all serialize
    # with cross-refs that resolve (AC: cross-references resolve at the seam).
    resp = client.post(
        "/toml/acquisition",
        json={
            "acquisition": {"acquisition_id": "Position_1"},
            "tilt_series": [{"tilt_series_id": "ts_raw", "derived_from": "Frames"}],
            "raw_tomogram": [
                {
                    "tomogram_id": "tomo_raw",
                    "derived_from": "ts_raw",
                    "software": "AreTomo",
                }
            ],
            "post_processed_tomogram": [
                {
                    "tomogram_id": "tomo_denoised",
                    "derived_from": ["tomo_raw"],
                    "denoising_software": "cryoCARE",
                }
            ],
            "annotation": [{"annotation_id": "ann1"}],
        },
    )
    assert resp.status_code == 200
    parsed = tomllib.loads(resp.text)
    assert parsed["raw_tomogram"][0]["id"] == "tomo_raw"
    assert parsed["post_processed_tomogram"][0]["derived_from"] == ["tomo_raw"]
    assert parsed["annotation"][0]["id"] == "ann1"


def test_dangling_raw_tomogram_derived_from_returns_422(client):
    # A raw_tomogram derived_from an unknown tilt series is rejected.
    resp = client.post(
        "/toml/acquisition",
        json={
            "acquisition": {"acquisition_id": "Position_1"},
            "raw_tomogram": [{"tomogram_id": "tomo_raw", "derived_from": "ghost"}],
        },
    )
    assert resp.status_code == 422


def test_dangling_derived_from_returns_422(client):
    # A post-processed tomogram derived_from an unknown tomogram id is rejected.
    resp = client.post(
        "/toml/acquisition",
        json={
            "acquisition": {"acquisition_id": "Position_1"},
            "post_processed_tomogram": [
                {"tomogram_id": "tomo1", "derived_from": ["nope"]}
            ],
        },
    )
    assert resp.status_code == 422


def test_acquisition_load_includes_processing_log(seeded_client):
    # Seed a tomogram + annotation, then load: the form receives them to render
    # editable; the client warns if a loaded id is renamed.
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(
        bind=seeded_client.app.state.engine, future=True, expire_on_commit=False
    )
    s = Session()
    try:
        s.add(
            orm.RawTomogramORM(
                sample_id="samp1",
                acquisition_id="Position_1",
                reconstruction_alignment_id="align1",
                tomogram_id="tomo_raw",
                derived_from="ts_raw",
            )
        )
        s.add(
            orm.AnnotationORM(
                sample_id="samp1",
                acquisition_id="Position_1",
                reconstruction_alignment_id="align1",
                annotation_id="ann1",
            )
        )
        s.commit()
    finally:
        s.close()

    fields = seeded_client.get(
        "/toml/acquisition/load/Position_1?sample_id=samp1"
    ).json()["fields"]
    assert fields["raw_tomogram"][0]["tomogram_id"] == "tomo_raw"
    assert fields["annotation"][0]["annotation_id"] == "ann1"


def test_acquisition_load_dedupes_stems_shared_across_alignment_groups(seeded_client):
    """Two alignment groups may each hold a ``denoised.mrc``; the flat form
    cannot express that (``reconstruction_alignment_id`` is not authored, so the
    field that distinguishes the blocks is unrenderable). Load must therefore
    collapse them to one block per leaf id — and the proof is that the loaded
    payload POSTs back cleanly, since two identical blocks land in the same
    ``None`` group bucket and trip the duplicate-id validator.
    """
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(
        bind=seeded_client.app.state.engine, future=True, expire_on_commit=False
    )
    s = Session()
    try:
        for group in ("align_a", "align_b"):
            s.add(
                orm.RawTomogramORM(
                    sample_id="samp1",
                    acquisition_id="Position_1",
                    reconstruction_alignment_id=group,
                    tomogram_id="dup",
                    derived_from="ts_raw",
                )
            )
            s.add(
                orm.AnnotationORM(
                    sample_id="samp1",
                    acquisition_id="Position_1",
                    reconstruction_alignment_id=group,
                    annotation_id="dup_ann",
                )
            )
        # Same stem as a post-processed tomogram in a third group: raw and
        # post-processed share one id namespace in the validator, so the dedupe
        # has to span both sections.
        s.add(
            orm.PostProcessedTomogramORM(
                sample_id="samp1",
                acquisition_id="Position_1",
                reconstruction_alignment_id="align_c",
                tomogram_id="dup",
            )
        )
        s.commit()
    finally:
        s.close()

    fields = seeded_client.get(
        "/toml/acquisition/load/Position_1?sample_id=samp1"
    ).json()["fields"]

    ids = [t["tomogram_id"] for t in fields.get("raw_tomogram", [])]
    ids += [t["tomogram_id"] for t in fields.get("post_processed_tomogram", [])]
    assert ids == ["dup"], ids
    assert [a["annotation_id"] for a in fields.get("annotation", [])] == ["dup_ann"]
    # First group wins, deterministically (queries order by group then id).
    assert fields["raw_tomogram"][0]["derived_from"] == "ts_raw"
    assert "reconstruction_alignment_id" not in fields["raw_tomogram"][0]

    # The round trip is the actual guarantee: the deduped load must be a payload
    # the generator accepts.
    resp = seeded_client.post("/toml/acquisition", json=fields)
    assert resp.status_code == 200, resp.text
    parsed = tomllib.loads(resp.text)
    assert [t["id"] for t in parsed["raw_tomogram"]] == ["dup"]


def test_acquisition_load_dedupes_stems_differing_only_in_case(seeded_client):
    """The duplicate-id validator casefolds, so ``denoised`` in one group and
    ``Denoised`` in another collide on generate. The dedupe must key
    case-insensitively — while still emitting the original id, not a
    lowercased one.
    """
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(
        bind=seeded_client.app.state.engine, future=True, expire_on_commit=False
    )
    s = Session()
    try:
        for group, stem in (("align_a", "denoised"), ("align_b", "Denoised")):
            s.add(
                orm.RawTomogramORM(
                    sample_id="samp1",
                    acquisition_id="Position_1",
                    reconstruction_alignment_id=group,
                    tomogram_id=stem,
                    derived_from="ts_raw",
                )
            )
        s.add(
            orm.AnnotationORM(
                sample_id="samp1",
                acquisition_id="Position_1",
                reconstruction_alignment_id="align_a",
                annotation_id="ann_x",
            )
        )
        s.add(
            orm.AnnotationORM(
                sample_id="samp1",
                acquisition_id="Position_1",
                reconstruction_alignment_id="align_b",
                annotation_id="ANN_X",
            )
        )
        s.commit()
    finally:
        s.close()

    fields = seeded_client.get(
        "/toml/acquisition/load/Position_1?sample_id=samp1"
    ).json()["fields"]

    # Original casing preserved, one block only.
    assert [t["tomogram_id"] for t in fields["raw_tomogram"]] == ["denoised"]
    assert [a["annotation_id"] for a in fields["annotation"]] == ["ann_x"]

    resp = seeded_client.post("/toml/acquisition", json=fields)
    assert resp.status_code == 200, resp.text


def test_author_acquisition_drops_hand_authored_group_id(client):
    """A legacy acquisition.toml can carry a hand-authored
    ``reconstruction_alignment_id`` on a tomogram block; ``/parse`` returns
    unknown keys verbatim, so re-emitting it would produce a file the authoring
    validator accepts but the scanner rejects. The generator applies the same
    scrub the loader does, which also means two blocks that only differ by that
    key collide as the duplicate they are.
    """
    toml = (
        '[acquisition]\nresolution = 3.4\n\n'
        '[[raw_tomogram]]\nid = "dup"\nreconstruction_alignment_id = "align_a"\n'
    )
    parsed = client.post("/toml/acquisition/parse", json={"toml": toml}).json()["fields"]
    assert parsed["raw_tomogram"][0]["reconstruction_alignment_id"] == "align_a"

    out = client.post("/toml/acquisition", json=parsed)
    assert out.status_code == 200, out.text
    assert "reconstruction_alignment_id" not in tomllib.loads(out.text)["raw_tomogram"][0]

    two = {
        "acquisition": {"acquisition_id": "Position_1"},
        "raw_tomogram": [
            {"id": "dup", "reconstruction_alignment_id": "align_a"},
            {"id": "dup", "reconstruction_alignment_id": "align_b"},
        ]
    }
    assert client.post("/toml/acquisition", json=two).status_code == 422


def test_valid_reconstruction_downloads_nested_toml(client):
    resp = client.post(
        "/toml/reconstruction",
        json={
            "reconstruction_alignment": {
                "reconstruction_alignment_id": "recon_1",
                "alignment_software": "IMOD 4.12",
                "alignment_method": "patch_tracking",
            },
            "raw_tomogram": [
                {"tomogram_id": "bp_3dctf_bin4", "derived_from": "ts_aligned"}
            ],
            "post_processed_tomogram": [
                {
                    "tomogram_id": "bp_3dctf_bin4_ddw",
                    "derived_from": ["bp_3dctf_bin4"],
                }
            ],
            "annotation": [
                {"annotation_id": "membrain_seg_v10", "type": "membrane_segmentation"}
            ],
        },
    )
    assert resp.status_code == 200
    assert resp.headers["content-disposition"] == (
        'attachment; filename="reconstruction.toml"'
    )
    parsed = tomllib.loads(resp.text)
    # The folder-derived group id is dropped — the folder name carries it.
    assert "id" not in parsed["reconstruction_alignment"]
    assert parsed["reconstruction_alignment"]["alignment_software"] == "IMOD 4.12"
    assert [t["id"] for t in parsed["raw_tomogram"]] == ["bp_3dctf_bin4"]
    assert parsed["post_processed_tomogram"][0]["derived_from"] == ["bp_3dctf_bin4"]
    assert parsed["annotation"][0]["id"] == "membrain_seg_v10"


def test_reconstruction_parse_round_trips(client):
    body = "\n".join(
        [
            "[reconstruction_alignment]",
            'alignment_software = "IMOD 4.12"',
            "",
            "[[raw_tomogram]]",
            'id = "bp_3dctf_bin4"',
        ]
    )
    resp = client.post("/toml/reconstruction/parse", json={"toml": body})
    assert resp.status_code == 200
    fields = resp.json()["fields"]
    assert fields["reconstruction_alignment"]["alignment_software"] == "IMOD 4.12"
    assert fields["raw_tomogram"][0]["id"] == "bp_3dctf_bin4"


def test_unknown_reconstruction_field_is_preserved(client):
    """extra="allow" means an unrecognised key survives into the output."""
    resp = client.post(
        "/toml/reconstruction",
        json={"reconstruction_alignment": {"tilt_axis_refinement": "per_tilt"}},
    )
    assert resp.status_code == 200
    parsed = tomllib.loads(resp.text)
    assert parsed["reconstruction_alignment"]["tilt_axis_refinement"] == "per_tilt"


# ── Reconstruction form: pull-from-API load, scoped to one group ────────────


def test_reconstruction_load_is_scoped_to_the_group(seeded_client):
    """Two groups may hold the same stem; a load returns only one group's rows."""
    Session = sessionmaker(
        bind=seeded_client.app.state.engine, future=True, expire_on_commit=False
    )
    s = Session()
    try:
        for group, software in (("grp_a", "IMOD 4.12"), ("grp_b", "RELION")):
            s.add(
                orm.ReconstructionAlignmentORM(
                    sample_id="samp1",
                    acquisition_id="Position_1",
                    reconstruction_alignment_id=group,
                    alignment_software=software,
                )
            )
            s.add(
                orm.RawTomogramORM(
                    sample_id="samp1",
                    acquisition_id="Position_1",
                    reconstruction_alignment_id=group,
                    tomogram_id="dup",
                    derived_from="ts_raw",
                )
            )
        s.commit()
    finally:
        s.close()

    fields = seeded_client.get(
        "/toml/reconstruction/load/grp_a?sample_id=samp1&acquisition_id=Position_1"
    ).json()["fields"]
    assert fields["reconstruction_alignment"]["alignment_software"] == "IMOD 4.12"
    assert [t["tomogram_id"] for t in fields["raw_tomogram"]] == ["dup"]
    # grp_b's identically-named tomogram is not included.
    assert len(fields["raw_tomogram"]) == 1


def test_reconstruction_load_returns_directory_path(seeded_client):
    # The alignment group has no path column: the directory is derived from the
    # parent acquisition's path + the Reconstructions/{group} convention. A
    # non-null path is what enables the "Save to file share" button.
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(
        bind=seeded_client.app.state.engine, future=True, expire_on_commit=False
    )
    s = Session()
    try:
        s.add(
            orm.ReconstructionAlignmentORM(
                sample_id="samp1",
                acquisition_id="Position_1",
                reconstruction_alignment_id="grp_a",
                alignment_software="IMOD 4.12",
            )
        )
        s.commit()
    finally:
        s.close()

    resp = seeded_client.get(
        "/toml/reconstruction/load/grp_a?sample_id=samp1&acquisition_id=Position_1"
    )
    assert resp.status_code == 200
    assert resp.json()["path"] == "/data/samp1/Position_1/Reconstructions/grp_a"


def test_reconstruction_load_requires_acquisition_id(seeded_client):
    resp = seeded_client.get("/toml/reconstruction/load/grp_a?sample_id=samp1")
    assert resp.status_code == 422


def test_reconstruction_load_unknown_group_404s(seeded_client):
    resp = seeded_client.get(
        "/toml/reconstruction/load/nope?sample_id=samp1&acquisition_id=Position_1"
    )
    assert resp.status_code == 404


def test_reconstruction_group_ids_for_an_acquisition(seeded_client):
    """The group selector's list: every Reconstructions/ folder in one
    acquisition, sorted, and nothing from a sibling acquisition."""
    Session = sessionmaker(
        bind=seeded_client.app.state.engine, future=True, expire_on_commit=False
    )
    s = Session()
    try:
        for acq, group in (
            ("Position_1", "grp_b"),
            ("Position_1", "grp_a"),
            ("Position_2", "grp_elsewhere"),
        ):
            s.add(
                orm.ReconstructionAlignmentORM(
                    sample_id="samp1",
                    acquisition_id=acq,
                    reconstruction_alignment_id=group,
                )
            )
        s.commit()
    finally:
        s.close()

    resp = seeded_client.get("/toml/reconstruction-group-ids/samp1/Position_1")
    assert resp.status_code == 200
    assert resp.json()["ids"] == ["grp_a", "grp_b"]


def test_reconstruction_group_ids_empty_for_unknown_acquisition(seeded_client):
    resp = seeded_client.get("/toml/reconstruction-group-ids/samp1/nope")
    assert resp.status_code == 200
    assert resp.json()["ids"] == []
