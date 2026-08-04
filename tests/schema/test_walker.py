"""Tests for the structured extras walker in schema.loader."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from schema.loader import ExtrasEntry, load_sample_record


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).lstrip())


def _find(extras: list[ExtrasEntry], entity_type: str, key: str) -> ExtrasEntry | None:
    for e in extras:
        if e.entity_type == entity_type and e.key == key:
            return e
    return None


def test_unknown_key_on_sample(tmp_path):
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"
        unknown_sample_key = "x"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.record is not None
    entry = _find(result.extras, "sample", "unknown_sample_key")
    assert entry is not None
    assert entry.entity_pk == (tmp_path.name,)
    assert entry.value == "x"


def test_unknown_key_on_chromatin(tmp_path):
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"

        [chromatin]
        unknown_chromatin_key = 42
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.record is not None
    entry = _find(result.extras, "chromatin", "unknown_chromatin_key")
    assert entry is not None
    assert entry.entity_pk == (tmp_path.name,)
    assert entry.value == 42


def test_unknown_key_on_second_label_uses_positional_pk(tmp_path):
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"

        [[label]]
        aunp_size_nm = 5.0

        [[label]]
        aunp_size_nm = 10.0
        unknown_label_key = "second"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.record is not None
    entry = _find(result.extras, "label", "unknown_label_key")
    assert entry is not None
    assert entry.entity_pk == (tmp_path.name, 1)
    assert entry.value == "second"


def test_unknown_key_on_tomogram_uses_id_not_index(tmp_path):
    """Regression: tomogram extras_pk must use tomogram_id, not the list index."""
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"
        """,
    )
    _write(
        tmp_path / "Position_86" / "acquisition.toml",
        """
        [acquisition]

        [[post_processed_tomogram]]
        id = "first_tomo"

        [[post_processed_tomogram]]
        id = "my_tomo"
        unknown_tomo_key = "value"
        """,
    )
    tomos = tmp_path / "Position_86" / "Reconstructions" / "ts_a" / "Tomograms"
    tomos.mkdir(parents=True)
    (tomos / "first_tomo.mrc").touch()
    (tomos / "my_tomo.mrc").touch()
    result = load_sample_record(tmp_path)
    assert result.record is not None
    entry = _find(result.extras, "post_processed_tomogram", "unknown_tomo_key")
    assert entry is not None
    # Must be id-keyed, not list-index-keyed.
    assert entry.entity_pk == (tmp_path.name, "Position_86", "my_tomo")
    assert entry.value == "value"


def test_nested_unknown_dict_is_not_flattened(tmp_path):
    """An unknown table is recorded as a single entry with the dict as value;
    inner keys are NOT promoted to separate entries.
    """
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"

        [sample.unknown_block]
        foo = 1
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.record is not None
    entry = _find(result.extras, "sample", "unknown_block")
    assert entry is not None
    assert entry.entity_pk == (tmp_path.name,)
    assert entry.value == {"foo": 1}
    # And there is NOT a separate entry for "foo".
    assert _find(result.extras, "sample", "foo") is None
