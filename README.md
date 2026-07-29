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

**Note:** This setup guide assumes you are working on machine with access to the Janelia file system.

1. [Install pixi](https://pixi.prefix.dev/latest/installation/).
2. From the repo root, run `pixi install` to materialize the Python environments.

The frontend's Node deps are installed automatically the first time you run `pixi run frontend` (and re-run only when `package.json` / `package-lock.json` change). You don't need a separate `npm install` step.

3. Create the database. Pass the path to the data root via the CATALOG_DATA_ROOT env variable. This will scan the samples at that path and create a SQLite database called `catalog.db` in your repo root.

To also pre-generate tomogram thumbnails, set `CATALOG_THUMBNAIL_DIR` to a writable directory (or pass `--thumbnail-dir`). A plain rescan auto-heals a wiped cache; `--force` fully rebuilds it.

```
CATALOG_DATA_ROOT=/path/to/data CATALOG_THUMBNAIL_DIR=/path/to/thumbnails pixi run scan --init
```

4. The portal has two processes: the FastAPI backend (reads the catalog DB) and the TanStack Start frontend (server-renders + hydrates a React app, proxying `/api` to FastAPI). Run them in two terminals.

**Terminal 1 — API:**
```
CATALOG_DATA_ROOT=/path/to/data CATALOG_THUMBNAIL_DIR=/path/to/thumbnails pixi run api
```
Serves `http://localhost:8000`. Swagger UI at `/docs`.

To serve cached OVITO/MD preview images for simulation samples (rendered upstream by [aicryoet-tools](https://github.com/schneidermc/aicryoet-tools) into a `.portal_cache` directory), set `CATALOG_MD_PREVIEW_DIR` to that directory. It is **optional** — if unset it defaults to `/groups/cryoet/cryoet/data/collepardolab/.portal_cache`, and if the directory is missing the `/api/md-previews` route is simply disabled (it does not block API startup, unlike `CATALOG_THUMBNAIL_DIR`).
```
CATALOG_DATA_ROOT=/path/to/data CATALOG_THUMBNAIL_DIR=/path/to/thumbnails \
  CATALOG_MD_PREVIEW_DIR=/path/to/.portal_cache pixi run api
```

> **No hot-reload.** The API runs with `--no-reload` (single worker). Neuroglancer's in-process HTTP server is incompatible with uvicorn's `--reload` mode, which tries to bind a second HTTP server on the same port.

**Terminal 2 — Frontend:**
```
pixi run frontend
```
Open the data portal at `http://localhost:3000`.

### Alternate port

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

### Neuroglancer configuration

The "View in Neuroglancer" feature starts an in-process HTTP server inside the API process. It listens on its own port, separate from the API port, and is **not** behind nginx — the browser connects to it directly.

| Environment variable | Default | Description |
|---|---|---|
| `NEUROGLANCER_BIND_ADDRESS` | `0.0.0.0` | IP address the Neuroglancer server binds to. |
| `NEUROGLANCER_PORT` | `8050` | Port the Neuroglancer server listens on. Must be published separately from the API port; the browser connects to this port directly (not through nginx). |
| `NEUROGLANCER_MAX_VIEWERS` | `8` | Maximum concurrent viewers in the LRU registry. Each live viewer pins its volume in RAM (~1.3–1.5 GB), so worst-case memory ≈ this × volume size — keep it matched to the pod memory limit (8 fits 24 Gi; ~10–12 is the practical ceiling). Raising it also requires bumping the volume-cache `maxsize` in `_mrc.py`. |
| `NEUROGLANCER_VIEWER_TTL_SECONDS` | `3600` | Idle viewers are torn down (volume RAM freed) after this many seconds without interaction — the stand-in for a browser tab-close signal, which isn't reachable. |
| `NEUROGLANCER_SWEEP_INTERVAL_SECONDS` | `60` | How often the idle sweep runs. |
| `DASHBOARD_HOSTNAME` | _(unset)_ | Overrides the hostname in Neuroglancer viewer URLs. Use in deployments where the server-side host differs from what the browser sees. |

The API must run as a **single worker with `--no-reload`** because the Neuroglancer server is process-global. Running multiple workers or hot-reloading would attempt to bind a second HTTP server on the same port.

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
