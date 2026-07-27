"""Regenerate openapi.json from the FastAPI app's route/response models.

The frontend generates its API types from this file via `openapi-typescript`
(`npm run gen:types` in `frontend/`), replacing the old hand-maintained
`frontend/src/types.ts`. Run whenever a route's `response_model` or a
`schemas.py` model changes.

Usage:
    pixi run --environment api openapi-schema [output_path]

Defaults to <repo>/frontend/openapi.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from catalog.api.main import create_app

_DEFAULT_OUT = Path(__file__).resolve().parents[3] / "frontend" / "openapi.json"


def main() -> None:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else _DEFAULT_OUT
    schema = create_app().openapi()
    out_path.write_text(json.dumps(schema, indent=2) + "\n")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
