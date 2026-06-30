"""Authored-field registry for the TOML authoring forms (ADR-0002).

Single source of truth, in Python, for which ``schema.py`` fields the authoring
forms expose and how to render them. Codegen'd to
``frontend/src/utils/formFields.ts`` by ``generate_form_fields.py``; both the
completeness and the codegen-parity drift tests live in
``tests/test_form_fields_drift.py``.

Only the **authored** subset of each model is rendered. The directory-derived
identity field (``md_run_id``, injected from the folder name by the loader) is
classified here as the non-persisted *intended-id* field (``is_id=True``): the
form collects it to drive the "save as …" placement hint and to satisfy
model validation, but the endpoint omits it from the written file.

Tracer bullet (issue 02) covers ``md_run`` only; ``sample`` / ``acquisition``
are added by later issues. Each form's backing model is listed in ``FORMS`` so
the completeness test fails when a new field on a covered model is left
unclassified.
"""

from __future__ import annotations

from dataclasses import dataclass

from schema.schema import MdRun


@dataclass(frozen=True)
class FormField:
    form: str  # 'md_run' (later: 'sample' | 'acquisition')
    section: str  # toml table the field belongs to
    field: str  # model field name; also the TOML key (except the id field)
    label: str
    input: str  # 'text' | 'integer' | 'number' | 'select' | 'date'
    required: bool = False
    # The non-persisted intended-id field: collected for the placement hint and
    # model validation, never written into the output file (directory-derived).
    is_id: bool = False
    help: str = ""


@dataclass(frozen=True)
class FormMeta:
    form: str
    title: str
    # Placement-hint template; ``{id}`` filled from the intended-id field. The
    # id is the directory name, not file content — hint only.
    placement: str
    filename: str


FORM_META: list[FormMeta] = [
    FormMeta(
        form="md_run",
        title="MD run",
        placement="MdRuns/{id}/md_run.toml",
        filename="md_run.toml",
    ),
]


FORM_FIELDS: list[FormField] = [
    # ---- md_run ([md_run]; one md_run.toml per run) -----------------------
    FormField(
        "md_run", "md_run", "md_run_id", "Run id", "text",
        required=True, is_id=True,
        help="Folder name under MdRuns/. Sets identity; not written into the file.",
    ),
    FormField("md_run", "md_run", "seed", "Seed", "integer",
              help="Random seed for the simulation run."),
    FormField("md_run", "md_run", "sample_time", "Sample time", "number",
              help="Total simulated time."),
    FormField("md_run", "md_run", "timestep", "Timestep", "number",
              help="Integration timestep."),
    FormField("md_run", "md_run", "computer", "Computer", "text",
              help="Machine the run executed on."),
    FormField("md_run", "md_run", "reference_contact", "Reference / contact", "text"),
    FormField("md_run", "md_run", "force_field_version", "Force field version", "text"),
]


# Form kind -> backing Pydantic model. Drives the completeness drift test:
# every field on a covered model must be classified in FORM_FIELDS.
FORMS = {
    "md_run": MdRun,
}
