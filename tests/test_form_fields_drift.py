"""Drift tests for the authored-field registry (ADR-0002).

(1) Completeness — every field on a form's backing model is classified in
    FORM_FIELDS, so adding a schema field can't silently leave the form stale.
(2) Codegen parity — the committed frontend/src/utils/formFields.ts equals a
    fresh render(). Regenerate with `pixi run form-fields`.
"""

from __future__ import annotations

from pathlib import Path

from schema.form_fields import FORM_FIELDS, FORMS
from schema.generate_form_fields import _OUT, render


def test_every_model_field_is_classified():
    for kind, model in FORMS.items():
        classified = {ff.field for ff in FORM_FIELDS if ff.form == kind}
        model_fields = set(model.model_fields)
        missing = model_fields - classified
        assert not missing, (
            f"{kind}: schema fields not classified in form_fields.py: {sorted(missing)}"
        )
        stray = classified - model_fields
        assert not stray, (
            f"{kind}: form_fields.py names fields absent from {model.__name__}: {sorted(stray)}"
        )


def test_committed_ts_matches_codegen():
    committed = Path(_OUT).read_text()
    assert committed == render(), (
        "frontend/src/utils/formFields.ts is out of sync with form_fields.py. "
        "Regenerate with `pixi run form-fields`."
    )
