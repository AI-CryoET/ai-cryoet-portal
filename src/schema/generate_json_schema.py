"""Regenerate schema.json + acquisition.schema.json + md_run.schema.json
+ reconstruction.schema.json.

Writes the JSON Schema for SampleRecord (the merged sample + acquisitions
record), AcquisitionFile (a single acquisition.toml on its own, used by
editor LSPs to validate acquisition.toml without requiring the sample
fields), MdRun (a single md_run.toml on its own), and ReconstructionFile (a
single Reconstructions/{id}/reconstruction.toml on its own). Run whenever
the Pydantic models change so downstream tools (non-Python validators, UIs,
editor schema directives) stay in sync.

Usage:
    pixi run json-schema [output_path]

`output_path` is the SampleRecord schema; the AcquisitionFile schema is
written as `acquisition.schema.json`, the MdRun schema as
`md_run.schema.json`, and the ReconstructionFile schema as
`reconstruction.schema.json` next to it. Defaults to
<repo>/schema/schema.json when no path is given.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from schema import AcquisitionFile, MdRun, ReconstructionFile, SampleRecord


_DEFAULT_OUT = Path(__file__).resolve().parent / "schema.json"
_ACQUISITION_FILENAME = "acquisition.schema.json"
_MD_RUN_FILENAME = "md_run.schema.json"
_RECONSTRUCTION_FILENAME = "reconstruction.schema.json"
_NULL_BRANCH = {"type": "null"}


def strip_nullable(node):
    """Collapse Pydantic's `anyOf: [T, null]` patterns in-place.

    TOML has no null literal — "optional" means the key is absent, not set
    to null. Stripping the null branch lets editor LSPs report a precise
    type error (e.g. "is not of type integer") instead of the generic
    "not valid under any of the schemas in anyOf" wrapper. A field's
    required/optional status is independent (governed by the parent
    object's `required` array), so this transform doesn't affect it.
    """
    if isinstance(node, dict):
        branches = node.get("anyOf")
        if isinstance(branches, list):
            non_null = [b for b in branches if b != _NULL_BRANCH]
            if len(non_null) < len(branches):
                if "default" in node and node["default"] is None:
                    node.pop("default")
                if len(non_null) == 1:
                    node.pop("anyOf")
                    for k, v in non_null[0].items():
                        node.setdefault(k, v)
                else:
                    node["anyOf"] = non_null
        for v in node.values():
            strip_nullable(v)
    elif isinstance(node, list):
        for item in node:
            strip_nullable(item)
    return node


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output",
        nargs="?",
        type=Path,
        default=_DEFAULT_OUT,
        help=f"path to write schema.json (default: {_DEFAULT_OUT})",
    )
    args = parser.parse_args(argv)

    args.output.parent.mkdir(parents=True, exist_ok=True)

    sample_schema = strip_nullable(SampleRecord.model_json_schema())
    args.output.write_text(json.dumps(sample_schema, indent=2) + "\n")
    print(f"wrote {args.output}")

    acquisition_out = args.output.parent / _ACQUISITION_FILENAME
    acquisition_schema = strip_nullable(AcquisitionFile.model_json_schema())
    acquisition_out.write_text(json.dumps(acquisition_schema, indent=2) + "\n")
    print(f"wrote {acquisition_out}")

    md_run_out = args.output.parent / _MD_RUN_FILENAME
    md_run_schema = strip_nullable(MdRun.model_json_schema())
    md_run_out.write_text(json.dumps(md_run_schema, indent=2) + "\n")
    print(f"wrote {md_run_out}")

    reconstruction_out = args.output.parent / _RECONSTRUCTION_FILENAME
    reconstruction_schema = strip_nullable(ReconstructionFile.model_json_schema())
    reconstruction_out.write_text(json.dumps(reconstruction_schema, indent=2) + "\n")
    print(f"wrote {reconstruction_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
