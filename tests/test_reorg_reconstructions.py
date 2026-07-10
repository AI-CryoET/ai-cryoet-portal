"""Self-check for utils/reorg_reconstructions.py.

utils/ is not an importable package (no __init__.py, not on sys.path), so the
migration script is loaded by path via importlib. The test then builds a small
synthetic two-arm data tree in tmp_path and exercises plan_reorg / apply_reorg
end to end — no real data is touched.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).parents[1] / "utils" / "reorg_reconstructions.py"


def _load_reorg():
    spec = importlib.util.spec_from_file_location("reorg_reconstructions", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # Register before exec so the module's dataclasses can resolve their own
    # annotations via sys.modules (needed under `from __future__ import annotations`).
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _build_tree(root: Path) -> None:
    # ── Experimental acquisition ────────────────────────────────────────────
    exp_acq = root / "Experimental" / "sampleA" / "acq1"
    _write(
        exp_acq / "acquisition.toml",
        "\n".join(
            [
                "[[tilt_series]]",
                'id = "ts_1"',
                "",
                "[raw_tomogram]",
                'id = "raw1"',
                'tilt_series_id = "ts_1"',
                "",
                "[[post_processed_tomogram]]",
                'id = "ddw1"',
                'tilt_series_id = "ts_1"',
                "",
                "[[annotation]]",
                'id = "seg1"',
                'type = "membrane_segmentation"',
                'target_tomogram = "ddw1"',
                "",
                "[[post_processed_tomogram]]",
                'id = "raw2"',
                'tilt_series_id = "ts_1"',
                "",
            ]
        ),
    )
    _write(exp_acq / "Reconstructions" / "Tomograms" / "raw1" / "x.mrc")
    _write(exp_acq / "Reconstructions" / "Tomograms" / "ddw1" / "y.mrc")
    # multi-suffix zarr dir for the same tomogram folder
    (exp_acq / "Reconstructions" / "Tomograms" / "ddw1" / "y.ome.zarr").mkdir()
    _write(exp_acq / "Reconstructions" / "Annotations" / "seg1" / "z.mrc")
    # untargetable annotation: no matching [[annotation]] block in the toml
    _write(exp_acq / "Reconstructions" / "Annotations" / "orphan" / "w.mrc")

    # OLD-layout entity whose planned destination is already occupied by an
    # unrelated file (e.g. a hand-created new-layout entity) — must be left
    # in place rather than clobbered by os.rename.
    _write(exp_acq / "Reconstructions" / "Tomograms" / "raw2" / "p.mrc")
    _write(
        exp_acq / "Reconstructions" / "ts_1" / "Tomograms" / "raw2.mrc",
        "pre-existing new-layout content",
    )

    # ── Simulation acquisition ──────────────────────────────────────────────
    sim_acq = (
        root
        / "MdSimulation"
        / "Bulk"
        / "sampleS"
        / "SyntheticCryoET"
        / "acqS"
    )
    _write(sim_acq / "Reconstructions" / "Tomograms" / "sim1" / "a.mrc")


def test_plan_and_apply(tmp_path: Path) -> None:
    reorg = _load_reorg()
    _build_tree(tmp_path)

    exp = tmp_path / "Experimental" / "sampleA" / "acq1"
    sim = tmp_path / "MdSimulation" / "Bulk" / "sampleS" / "SyntheticCryoET" / "acqS"

    plan = reorg.plan_reorg(tmp_path)
    dsts = {dst for _, dst in plan.moves}

    # Experimental tomograms -> Reconstructions/{ts}/Tomograms/{id}.<ext>
    assert exp / "Reconstructions" / "ts_1" / "Tomograms" / "raw1.mrc" in dsts
    assert exp / "Reconstructions" / "ts_1" / "Tomograms" / "ddw1.mrc" in dsts
    assert exp / "Reconstructions" / "ts_1" / "Tomograms" / "ddw1.ome.zarr" in dsts

    # Experimental annotation -> Reconstructions/{ts}/Annotations/{id}.<ext>
    assert exp / "Reconstructions" / "ts_1" / "Annotations" / "seg1.mrc" in dsts

    # Orphan annotation is left in place and warned about.
    assert not any(dst.name.startswith("orphan") for dst in dsts)
    assert any("orphan" in w for w in plan.warnings)

    # raw2's destination already exists on disk -> left in place + warned,
    # never queued for a (clobbering) move.
    assert not any(src.name == "p.mrc" for src, _ in plan.moves)
    assert any(
        "raw2" in w and "already exists" in w for w in plan.warnings
    )

    # Simulation tomogram -> flat Reconstructions/Tomograms/{id}.<ext> (no ts level)
    assert sim / "Reconstructions" / "Tomograms" / "sim1.mrc" in dsts

    # ── apply, then verify results + idempotency ────────────────────────────
    reorg.apply_reorg(plan)

    assert (exp / "Reconstructions" / "ts_1" / "Tomograms" / "raw1.mrc").is_file()
    assert (exp / "Reconstructions" / "ts_1" / "Tomograms" / "ddw1.mrc").is_file()
    assert (exp / "Reconstructions" / "ts_1" / "Tomograms" / "ddw1.ome.zarr").is_dir()
    assert (exp / "Reconstructions" / "ts_1" / "Annotations" / "seg1.mrc").is_file()
    assert (sim / "Reconstructions" / "Tomograms" / "sim1.mrc").is_file()

    # Orphan left untouched on disk.
    assert (exp / "Reconstructions" / "Annotations" / "orphan" / "w.mrc").is_file()

    # raw2 left untouched on disk; the pre-existing destination is unclobbered.
    assert (exp / "Reconstructions" / "Tomograms" / "raw2" / "p.mrc").is_file()
    assert (
        exp / "Reconstructions" / "ts_1" / "Tomograms" / "raw2.mrc"
    ).read_text() == "pre-existing new-layout content"

    # tilt_series_id stripped from the tomogram blocks (default strip on).
    toml_text = (exp / "acquisition.toml").read_text()
    assert "tilt_series_id" not in toml_text
    assert 'target_tomogram = "ddw1"' in toml_text  # untouched

    # Idempotent: a fresh plan on migrated data has nothing left to do — except
    # the still-unresolvable raw2 collision, which re-warns every run.
    plan2 = reorg.plan_reorg(tmp_path)
    assert plan2.moves == []
    assert plan2.toml_edits == []
    assert plan2.dirs_to_remove == []
