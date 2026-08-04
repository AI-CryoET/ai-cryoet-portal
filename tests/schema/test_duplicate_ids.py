"""Exact-duplicate ids must be reported, not just case-insensitive collisions."""
from schema.schema import _case_insensitive_duplicates


def test_exact_duplicate_is_reported():
    problems = _case_insensitive_duplicates(["tomo_001", "tomo_001"], "tomogram id")
    assert problems == ["duplicate tomogram id 'tomo_001'"]


def test_case_insensitive_collision_still_reported():
    problems = _case_insensitive_duplicates(["tomo_001", "Tomo_001"], "tomogram id")
    assert len(problems) == 1
    assert "collides case-insensitively" in problems[0]


def test_distinct_ids_are_clean():
    assert _case_insensitive_duplicates(["a", "b", "c"], "tomogram id") == []
