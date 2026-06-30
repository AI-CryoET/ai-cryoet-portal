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
    # Per section: every field on the section's backing model must be
    # classified (authored or derived) so adding a schema field can't silently
    # leave a form stale.
    for (form, section), model in FORMS.items():
        classified = {
            ff.field
            for ff in FORM_FIELDS
            if ff.form == form and ff.section == section
        }
        model_fields = set(model.model_fields)
        missing = model_fields - classified
        assert not missing, (
            f"{form}/{section}: schema fields not classified in form_fields.py: "
            f"{sorted(missing)}"
        )
        stray = classified - model_fields
        assert not stray, (
            f"{form}/{section}: form_fields.py names fields absent from "
            f"{model.__name__}: {sorted(stray)}"
        )


def test_committed_ts_matches_codegen():
    committed = Path(_OUT).read_text()
    assert committed == render(), (
        "frontend/src/utils/formFields.ts is out of sync with form_fields.py. "
        "Regenerate with `pixi run form-fields`."
    )
