# CryoET + AI Data Portal

A Pydantic-validated metadata schema, a directory-walking catalog scanner, a FastAPI read API, and a TanStack Start + Material UI frontend for the CryoET + AI project. The portal answers one question across both the experimental and simulation arms of the project: **which conditions have we covered, and which still need cryoET imaging, simulation, or both?**

> **Status: draft / proposed.** Schema fields and conventions are still evolving as researchers start authoring metadata against it.

---

## Repository map

| Path | Contents |
|---|---|
| `src/schema/` | Authoritative Pydantic schema, JSON Schema generators, and the `validate` CLI. |
| `src/catalog/` | Directory-walking scanner that builds the catalog DB from `sample.toml` + `acquisition.toml` + MDOC/MRC headers. Includes the FastAPI read API under `src/catalog/api/`. |
| `frontend/` | React + TanStack Start + Material UI app that reads from the FastAPI server. |
| `deploy/` | Docker, Kubernetes/OpenShift manifests, nginx config, and the deployment guide (`deploy/DEPLOYMENT.md`). |
| `templates/` | Starter `sample.toml`, `acquisition.toml`, and directory skeletons, containing the TOML files in the expected locations, for new experimental (cryoET) and simulation (MD + synthetic cyroET) samples. |
| `docs/data_organization.md` | The on-disk layout and TOML metadata authoring guide for researchers. |
| `docs/architecture.md` | System architecture overview. |
| `.claude/plans/` | Implementation plans, including the catalog scanner plan. |
| `pyproject.toml` / `pixi.lock` | PyPI dependencies (`[project]`), and pixi config (`[tool.pixi.*]`). |

For the schema itself, see `docs/schema.md` (human reference) and `src/schema/schema.py` (Pydantic source of truth).

---

## Development

> [!IMPORTANT]
> This setup guide assumes you are working on machine with access to the Janelia file system.

### Tier 1 - local development using pixi commands

> [!NOTE]
> This tier does not allow you to test changes to Neuroglancer functionality, either the Python in-process Neuroglancer or the browser-based Neuroglancer.

1. [Install pixi](https://pixi.prefix.dev/latest/installation/).
2. From the repo root, run `pixi install` to materialize the Python environments.

The frontend's Node deps are installed automatically the first time you run `pixi run frontend` (and re-run only when `package.json` / `package-lock.json` change). You don't need a separate `npm install` step.

3. To create the database, run the below command from the repo root. Pass the path to the data root via the CATALOG_DATA_ROOT env variable.

> [!NOTE]
> A small subset of data is maintained in the cryoet fileshare under a `scratch/data` subdirectory of the full tree — this is the recommended path to point CATALOG_DATA_ROOT at; otherwise, create a small subset for your personal use and point it at that. The full dataset is too large for local testing.

```
CATALOG_DATA_ROOT=/path/to/scratch/data pixi run scan --init
```

This command scans the samples under the data root path and creates a SQLite database called `catalog.db` in the root of the current working directory. It also pre-generates tomogram thumbnails and, for simulation samples, OVITO MD-preview images, creating the cache folders on demand. By default the image caches land at `./data/.thumbnail-cache` and `./data/.md-preview-cache` in the current working directory. Override either with `CATALOG_THUMBNAIL_DIR` / `CATALOG_MD_PREVIEW_DIR` (or `--thumbnail-dir` / `--md-preview-dir`) to put them somewhere else.

4. The portal has two processes: the FastAPI backend (reads the catalog DB) and the TanStack Start frontend (server-renders + hydrates a React app, proxying `/api` to FastAPI). Run them in two terminals.

**Terminal 1 — API:**
```
CATALOG_DATA_ROOT=/path/to/scratch/data pixi run api
```
> [!NOTE]
> The API reads thumbnails and MD-preview images from the same default cache paths the scanner wrote them to above; pass matching `CATALOG_THUMBNAIL_DIR` / `CATALOG_MD_PREVIEW_DIR` values if you overrode them during scanning. A missing MD-preview dir just disables the `/api/md-previews` route; a missing thumbnail dir blocks API startup (run the scan first).

> **No hot-reload.** The API runs with `--no-reload` (single worker). Neuroglancer's in-process HTTP server is incompatible with uvicorn's `--reload` mode, which tries to bind a second HTTP server on the same port.

**Terminal 2 — Frontend:**
```
pixi run frontend
```
Open the data portal at `http://localhost:3000`.

#### Alternate port

If port 8000 is taken, pass uvicorn flags through to use an alternate port. You can also change the IP binding:
```
pixi run api --host 0.0.0.0 --port 8034
```

If you change the backend host/port, you will also need to point the frontend to it. The frontend reads its dev-server settings from `frontend/.env.local` (gitignored). Create it like this:

```
# Backend the /api proxy points to (default: http://localhost:8000)
API_PROXY_TARGET=http://localhost:8034

# Port the Vite dev server listens on (default: 3000)
FRONTEND_PORT=3030
```

---
## Production deployment

For Kubernetes deployment, see [deploy/DEPLOYMENT.md](./deploy/DEPLOYMENT.md).

### Testing Docker deployment locally

This models the production deployment using local Docker services. Nginx is the only port exposed to the host and proxies `/api/*` to FastAPI and everything else to the frontend SSR server.

**Prerequisites:** Docker and Docker Compose installed.

1. Create a `.env` file in the repo root:

```
CATALOG_DATA_ROOT=/path/to/data
NGINX_PORT=80            # optional, defaults to 80
```

2. Build all images:

```
docker compose build
```

3. Run the scanner to populate the database (writes into the `catalog-db` Docker volume):

```
docker compose --profile scan run --rm scanner
```

`--profile scan` activates the scanner service, which is excluded from the default `docker compose up` because in production it will run as a Kubernetes CronJob. `run --rm` starts it as a one-shot container and removes it when it exits.

4. Start the stack:

```
docker compose up
```

Open `http://localhost` (or `http://localhost:<NGINX_PORT>` if you changed the port). The API and frontend ports (8000 and 3000) are internal to the Docker network and not accessible from the host.

### Schema changes

The SQLite database persists in the `catalog-db` named volume across restarts. Schema changes are managed by Alembic (see `src/catalog/migrations/README.md`): both the API and the scanner call `init_schema`, which runs `alembic upgrade head` on startup, so pulling a new revision and restarting the stack applies it automatically — no wipe required.

If you do want a clean slate (e.g. testing against fresh sample data), wipe the volume and rescan:

```
docker compose down -v
docker compose --profile scan run --rm scanner
docker compose up
```
---

## Maintaining the schema

`src/schema/schema.py` is the single source of truth for field definitions. When changing a field:

1. Edit `schema.py` and the canonical template(s) — `templates/sample.toml` / `templates/acquisition.toml`.
2. Run `pixi run sync` to regenerate the derived artifacts: `schema.json`, `acquisition.schema.json`, and the `templates/sample_id_{data_type}/` starter copies.
3. Update `docs/schema.md`, the human-readable schema documentation for every stored field, including DB-only ones not in any TOML.
4. Run `pixi run -e api test -- tests/test_repo_consistency.py tests/test_generate_json_schema.py`. The drift guards in `tests/test_repo_consistency.py` and `tests/test_generate_json_schema.py` fail with a fix hint if the generated schemas, starter copies, or docs are out of date.

---

## Schema authoring & validation

For researchers writing `sample.toml` / `acquisition.toml`, the authoring guide is in **[`docs/data_organization.md`](docs/data_organization.md)**. Quick commands:

| Command | What it does |
|---|---|
| `pixi run validate {sample_dir}` | Validate `sample.toml` and all `acquisition.toml` files under a sample directory. |
| `pixi run json-schema` | Regenerate `src/schema/schema.json` and `acquisition.schema.json` from the Pydantic models. Run after any change to `schema.py`. |
| `pixi run test` | Run the test suite. |

---

## Further reading

- **[`docs/data_organization.md`](docs/data_organization.md)** — directory layout, metadata files, schema rules, researcher workflow.
- **[`docs/architecture.md`](docs/architecture.md)** — system architecture.
- **[`docs/schema.md`](docs/schema.md)** — every field that lands in the portal DB, grouped by entity, with the source of each (TOML / MDOC / MRC / directory / derived).
