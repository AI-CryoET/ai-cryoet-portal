# CLAUDE.md

## Running the Python tests

Tests run through **pixi**, not a bare `pytest`/`.venv`. The dependencies
(`mrcfile`, `neuroglancer`, etc.) only exist inside the pixi environments.

```bash
pixi run -e api pytest                                   # full suite
pixi run -e api pytest tests/catalog/test_api_neuroglancer.py   # one file
```

Environments (see `[tool.pixi.environments]` in `pyproject.toml`):
- `api` — catalog + api + test. Use this; it has everything.
- `catalog` — catalog + test (no fastapi/neuroglancer).

`pixi run -e api test` also works (`test` is the `pytest` task).
