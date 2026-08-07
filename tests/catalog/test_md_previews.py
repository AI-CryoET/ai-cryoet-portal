"""MD-preview orchestration: dump selection, relpath, generation wiring.

These exercise the pure-Python orchestration in :mod:`catalog.md_previews`
without invoking OVITO — the renderer is stubbed. Importing the renderer module
must not require OVITO (it's an optional dep, imported lazily in a subprocess).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from catalog import md_previews
from schema.schema import DatasetType


def test_wrap_policy_matches_upstream_by_dataset_type():
    # aicryoet-tools wraps Bulk/Slab (periodic condensate) but not a single
    # fiber (would fragment across the box boundary).
    assert md_previews.wrap_for_dataset_type(DatasetType.bulk) is True
    assert md_previews.wrap_for_dataset_type(DatasetType.slab) is True
    assert md_previews.wrap_for_dataset_type(DatasetType.single_molecule) is False
    assert md_previews.wrap_for_dataset_type(None) is False


def _make_md_run(sample_dir, run_id, dump_names, *, in_trajectories=True):
    """Create ``{sample}/MdRuns/{run_id}/[Trajectories/]<dumps>`` + md_run.toml."""
    run_dir = sample_dir / "MdRuns" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "md_run.toml").write_text("seed = 1\n")
    dump_dir = run_dir / "Trajectories" if in_trajectories else run_dir
    dump_dir.mkdir(exist_ok=True)
    for name in dump_names:
        (dump_dir / name).write_text("ITEM: ATOMS id type x y z\n")
    return run_dir


def test_renderer_module_imports_without_ovito():
    # Lazy-import contract: importing the module never touches OVITO.
    import catalog.imaging._md_render as r

    assert hasattr(r, "render_md_dump_preview")


def test_relpath_is_sample_scoped():
    assert md_previews.relpath("s1", "run_a") == "s1/run_a.png"


def test_relpath_rejects_unsafe_segments():
    with pytest.raises(ValueError):
        md_previews.relpath("../escape", "run_a")


def test_choose_dump_prefers_dna_dump(tmp_path):
    run_dir = _make_md_run(tmp_path, "r1", ["cores.dump", "dna.dump", "other.dump"])
    chosen = md_previews._choose_dump(run_dir)
    assert chosen is not None and chosen.endswith("Trajectories/dna.dump")


def test_choose_dump_falls_back_to_first_glob(tmp_path):
    run_dir = _make_md_run(tmp_path, "r1", ["snap.lammpstrj"])
    chosen = md_previews._choose_dump(run_dir)
    assert chosen is not None and chosen.endswith("snap.lammpstrj")


def test_choose_dump_searches_run_dir_when_no_trajectories(tmp_path):
    run_dir = _make_md_run(tmp_path, "r1", ["dna.dump"], in_trajectories=False)
    chosen = md_previews._choose_dump(run_dir)
    assert chosen is not None and chosen.endswith("r1/dna.dump")


def test_choose_dump_returns_none_when_empty(tmp_path):
    run_dir = tmp_path / "MdRuns" / "r1"
    run_dir.mkdir(parents=True)
    assert md_previews._choose_dump(run_dir) is None


def test_refs_from_location_one_ref_per_run(tmp_path):
    _make_md_run(tmp_path, "r1", ["dna.dump"])
    _make_md_run(tmp_path, "r2", [])  # run with no dump → dump_path None
    sample_loc = SimpleNamespace(path=tmp_path, sample_id="s1")

    refs = md_previews.refs_from_location(sample_loc)

    by_id = {r.md_run_id: r for r in refs}
    assert set(by_id) == {"r1", "r2"}
    assert by_id["r1"].dump_path is not None
    assert by_id["r2"].dump_path is None


def test_generate_md_previews_renders_and_returns_relpaths(tmp_path, monkeypatch):
    _make_md_run(tmp_path, "r1", ["dna.dump"])
    sample_loc = SimpleNamespace(path=tmp_path, sample_id="s1")
    refs = md_previews.refs_from_location(sample_loc)
    preview_root = tmp_path / "cache"

    rendered: list = []

    def fake_render(dump_path, output_path, **kwargs):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"\x89PNG fake")
        rendered.append((dump_path, output_path))
        return output_path

    monkeypatch.setattr(
        "catalog.imaging._md_render.render_md_dump_preview", fake_render
    )

    result = md_previews.generate_md_previews("s1", refs, preview_root)

    assert result == {"r1": "s1/r1.png"}
    assert (preview_root / "s1" / "r1.png").is_file()
    # rendered to a tmp file then atomically renamed into place.
    assert len(rendered) == 1


def test_generate_md_previews_skips_runs_without_dumps(tmp_path, monkeypatch):
    _make_md_run(tmp_path, "r1", [])  # no dump
    sample_loc = SimpleNamespace(path=tmp_path, sample_id="s1")
    refs = md_previews.refs_from_location(sample_loc)

    monkeypatch.setattr(
        "catalog.imaging._md_render.render_md_dump_preview",
        lambda *a, **k: pytest.fail("should not render a run with no dump"),
    )

    assert md_previews.generate_md_previews("s1", refs, tmp_path / "cache") == {}


def test_generate_md_previews_skip_existing(tmp_path, monkeypatch):
    _make_md_run(tmp_path, "r1", ["dna.dump"])
    sample_loc = SimpleNamespace(path=tmp_path, sample_id="s1")
    refs = md_previews.refs_from_location(sample_loc)
    preview_root = tmp_path / "cache"
    existing = preview_root / "s1" / "r1.png"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"old")

    monkeypatch.setattr(
        "catalog.imaging._md_render.render_md_dump_preview",
        lambda *a, **k: pytest.fail("skip_existing must not re-render"),
    )

    result = md_previews.generate_md_previews(
        "s1", refs, preview_root, skip_existing=True
    )
    assert result == {"r1": "s1/r1.png"}
    assert existing.read_bytes() == b"old"  # untouched
