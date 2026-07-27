"""Drift tests for the authored-field registry (ADR-0002).

(1) Completeness — every field on a form's backing model is classified in
    FORM_FIELDS, so adding a schema field can't silently leave the form stale.
    For a composite form (e.g. ``sample``) the backing model is built from
    nested sub-models; the check recurses into each section's sub-model and
    pins that every top-level field is either a declared section or explicitly
    excluded (so a new SampleRecord sub-model can't slip in unclassified).
(2) Codegen parity — the committed frontend/src/utils/formFields.ts equals a
    fresh render(). Regenerate with `pixi run form-fields`.
"""

from __future__ import annotations

from pathlib import Path

from schema.form_fields import (
    EXCLUDED_TOP_FIELDS,
    FORM_FIELDS,
    FORM_SECTIONS,
    FORMS,
)
from schema.generate_form_fields import _OUT, render


def _classified(form: str, section: str) -> set[str]:
    return {ff.field for ff in FORM_FIELDS if ff.form == form and ff.section == section}


def test_every_model_field_is_classified():
    for kind, model in FORMS.items():
        sections = [s for s in FORM_SECTIONS if s.form == kind]
        assert sections, f"{kind}: no FORM_SECTIONS entries"

        # Composite forms (section model != the form model) must account for
        # every top-level field of the form model: it is either a rendered
        # section or an explicit exclusion.
        if any(s.model is not model for s in sections):
            section_names = {s.section for s in sections}
            excluded = EXCLUDED_TOP_FIELDS.get(kind, set())
            unaccounted = set(model.model_fields) - section_names - excluded
            assert not unaccounted, (
                f"{kind}: model fields neither a form section nor excluded: "
                f"{sorted(unaccounted)} (add a FORM_SECTIONS entry or list in "
                "EXCLUDED_TOP_FIELDS)"
            )

        # Each section's sub-model: every field classified, no strays.
        for s in sections:
            classified = _classified(kind, s.section)
            sub_fields = set(s.model.model_fields)
            missing = sub_fields - classified
            assert not missing, (
                f"{kind}.{s.section}: schema fields not classified in "
                f"form_fields.py: {sorted(missing)}"
            )
            stray = classified - sub_fields
            assert not stray, (
                f"{kind}.{s.section}: form_fields.py names fields absent from "
                f"{s.model.__name__}: {sorted(stray)}"
            )


def test_committed_ts_matches_codegen():
    committed = Path(_OUT).read_text()
    assert committed == render(), (
        "frontend/src/utils/formFields.ts is out of sync with form_fields.py. "
        "Regenerate with `pixi run form-fields`."
    )


def test_repeatable_sections_have_exactly_one_required_field():
    """The frontend (hydrateSections / AuthoringForm) derives a repeatable
    section's id field as the sole required field, to key loaded-entry
    warnings and namespace pooling. If a repeatable section ever had zero or
    more than one required field, that derivation would silently attach to
    the wrong field (or none).

    Only covers forms rendered by the generic sectioned renderer — the
    project-gated composite sample form uses its own renderer and doesn't
    rely on this invariant.
    """
    project_gated_forms = {s.form for s in FORM_SECTIONS if s.requires_project}
    for s in FORM_SECTIONS:
        if not s.repeatable or s.form in project_gated_forms:
            continue
        required = [
            ff.field
            for ff in FORM_FIELDS
            if ff.form == s.form and ff.section == s.section and ff.required
        ]
        assert len(required) == 1, (
            f"{s.form}.{s.section}: repeatable section must have exactly one "
            f"required field (found {required}) — the frontend keys the "
            "loaded-entry id on it"
        )
