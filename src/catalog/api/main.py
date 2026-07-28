"""FastAPI app factory for the catalog read-only API.

The API runs separately from the scanner (the scanner writes; the API reads).
Configuration via environment:
  CATALOG_DB_URL             — SQLAlchemy URL (default: sqlite:///catalog.db)
  CORS_ORIGINS               — comma-separated allowed origins (default: http://localhost:5173)
  CATALOG_DATA_ROOT          — filesystem root that bounds all preview/Neuroglancer reads.
                               Required at startup; the API refuses to start without it.
  CATALOG_THUMBNAIL_DIR      — directory containing pre-generated thumbnail PNGs.
                               Required at startup; the API refuses to start without it.
  CATALOG_MD_PREVIEW_DIR     — directory of cached OVITO/MD preview PNGs
                               (aicryoet-tools .portal_cache). Optional; a missing
                               dir just disables the /md-previews route.
  NEUROGLANCER_MAX_VIEWERS   — bounded LRU size for active viewers (default 12).
"""
from __future__ import annotations
import asyncio
import inspect
import logging
import os
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

# Eager-import matplotlib so the first preview render doesn't pay the import
# cost. We never use the pyplot global state path — the polar/preview routes
# build figures via the OO API (`Figure(); FigureCanvasAgg`).
try:  # pragma: no cover — environments without matplotlib (e.g. catalog-only) skip.
    import matplotlib  # noqa: F401
    import matplotlib.figure  # noqa: F401
except ModuleNotFoundError:
    pass

from catalog import db
from catalog.api.routes import (
    acquisitions as acquisitions_routes,
    annotations as annotations_routes,
    extras,
    filters,
    manage as manage_routes,
    md_previews as md_previews_routes,
    samples,
    stats,
    thumbnails as thumbnails_routes,
    tilt_series as tilt_series_routes,
    toml_authoring,
    tomograms,
    warnings as warnings_routes,
)


class _LoguruInterceptHandler(logging.Handler):
    """Forward stdlib ``logging`` records into loguru.

    Without this, uvicorn's startup/access logs and alembic's migration
    output go through stdlib ``StreamHandler`` writes to a piped stderr,
    which the OS may hold until the process exits when running under
    pixi/docker/etc. Loguru flushes its sink after every write, so once
    records pass through here they appear immediately. Frame-walking
    matches the upstream loguru-docs recipe (avoids attributing the call
    site to ``logging/__init__.py``).
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: int | str = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = inspect.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def _install_log_intercept() -> None:
    """Route stdlib loggers (root + uvicorn) through loguru.

    Uvicorn pins ``propagate=False`` on its own loggers, so a root-only
    handler doesn't catch its access/error output — we have to replace
    handlers on each uvicorn logger explicitly.
    """
    handler = _LoguruInterceptHandler()
    logging.basicConfig(handlers=[handler], level=logging.INFO, force=True)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvi_logger = logging.getLogger(name)
        uvi_logger.handlers = [handler]
        uvi_logger.propagate = False


def _parse_origins(raw: str) -> list[str]:
    return [o.strip() for o in raw.split(",") if o.strip()]


def _detect_multi_worker() -> int | None:
    """Best-effort multi-worker detection from environment signals.

    Returns the worker count if it can be determined and is >1; otherwise None.
    Uvicorn and gunicorn don't expose the worker count to the app process, but
    operators commonly export ``UVICORN_WORKERS`` / ``WEB_CONCURRENCY`` /
    ``GUNICORN_CMD_ARGS=--workers=N``. We sniff those.
    """
    for var in ("UVICORN_WORKERS", "WEB_CONCURRENCY"):
        raw = os.environ.get(var)
        if raw and raw.isdigit() and int(raw) > 1:
            return int(raw)
    return None


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Reroute stdlib logging through loguru's flushing sink — fixes the
    # "Application startup complete." / access-log buffering you hit when
    # running under pixi (piped stderr).
    _install_log_intercept()

    # Tests may pre-seed app.state.engine to bypass DB URL config; respect that.
    pre_seeded_engine = getattr(app.state, "engine", None) is not None
    if not pre_seeded_engine:
        db_url = os.environ.get("CATALOG_DB_URL", db.DEFAULT_DB_URL)
        engine = db.make_engine(db_url)
        db.init_schema(engine)  # idempotent; safe on existing DB
        app.state.engine = engine

    # CATALOG_DATA_ROOT is required for preview/Neuroglancer routes. Tests may
    # pre-seed app.state.data_root_resolved to avoid needing a real directory.
    pre_seeded_root = getattr(app.state, "data_root_resolved", None) is not None
    if not pre_seeded_root:
        raw_root = os.environ.get("CATALOG_DATA_ROOT")
        if not raw_root:
            raise RuntimeError(
                "CATALOG_DATA_ROOT is required (filesystem root bounding all "
                "preview/Neuroglancer reads). Set it to the dir under which "
                "all DB-recorded paths live."
            )
        try:
            resolved = Path(raw_root).resolve(strict=True)
        except (FileNotFoundError, OSError) as exc:
            raise RuntimeError(
                f"CATALOG_DATA_ROOT={raw_root!r} does not exist or is unreadable"
            ) from exc
        if not resolved.is_dir():
            raise RuntimeError(f"CATALOG_DATA_ROOT={raw_root!r} is not a directory")
        app.state.data_root_resolved = resolved

    # CATALOG_THUMBNAIL_DIR is required. Tests may pre-seed app.state.thumbnail_root
    # (even to None) to bypass this; use hasattr so an explicit None is respected.
    pre_seeded_thumb = hasattr(app.state, "thumbnail_root")
    if not pre_seeded_thumb:
        raw_thumb = os.environ.get("CATALOG_THUMBNAIL_DIR")
        if not raw_thumb:
            raise RuntimeError(
                "CATALOG_THUMBNAIL_DIR is required (directory containing pre-generated "
                "thumbnail PNGs). Generate thumbnails with: "
                "CATALOG_DATA_ROOT=... CATALOG_THUMBNAIL_DIR=... pixi run scan --init"
            )
        try:
            resolved_thumb = Path(raw_thumb).resolve(strict=True)
        except (FileNotFoundError, OSError) as exc:
            raise RuntimeError(
                f"CATALOG_THUMBNAIL_DIR={raw_thumb!r} does not exist or is unreadable"
            ) from exc
        if not resolved_thumb.is_dir():
            raise RuntimeError(f"CATALOG_THUMBNAIL_DIR={raw_thumb!r} is not a directory")
        app.state.thumbnail_root = resolved_thumb

    # CATALOG_MD_PREVIEW_DIR — directory of cached OVITO/MD preview PNGs
    # (aicryoet-tools .portal_cache). Optional: unlike thumbnails this is a
    # demo feature, so a missing/bad dir just disables the route (404) rather
    # than failing startup. Tests may pre-seed app.state.md_preview_root.
    if not hasattr(app.state, "md_preview_root"):
        raw_md = os.environ.get(
            "CATALOG_MD_PREVIEW_DIR",
            "/groups/cryoet/cryoet/data/collepardolab/.portal_cache",
        )
        try:
            resolved_md = Path(raw_md).resolve(strict=True)
            app.state.md_preview_root = resolved_md if resolved_md.is_dir() else None
        except (FileNotFoundError, OSError):
            app.state.md_preview_root = None
        if app.state.md_preview_root is None:
            logger.warning(
                "CATALOG_MD_PREVIEW_DIR={!r} not found; /md-previews disabled", raw_md
            )

    workers = _detect_multi_worker()
    if workers is not None:
        logger.warning(
            "Detected {} API workers via env. Neuroglancer binds an HTTP server "
            "once per process; multi-worker breaks viewer launches. Run with "
            "`--workers 1 --no-reload` for the dashboard MVP.",
            workers,
        )

    # Bounded Neuroglancer-viewer registry (plan §7.4 / §11.9). Initialized
    # only if not already set so tests can pre-seed for inspection.
    if getattr(app.state, "active_viewers", None) is None:
        app.state.active_viewers = OrderedDict()
    if getattr(app.state, "active_viewers_lock", None) is None:
        app.state.active_viewers_lock = asyncio.Lock()
    if getattr(app.state, "neuroglancer_max_viewers", None) is None:
        raw_max = os.environ.get("NEUROGLANCER_MAX_VIEWERS", "12")
        try:
            app.state.neuroglancer_max_viewers = max(1, int(raw_max))
        except ValueError:
            app.state.neuroglancer_max_viewers = 12

    yield
    if not pre_seeded_engine:
        app.state.engine.dispose()


def create_app() -> FastAPI:
    cors_origins = _parse_origins(os.environ.get("CORS_ORIGINS", "http://localhost:5173"))
    app = FastAPI(title="CryoET Catalog API", lifespan=_lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.include_router(samples.router, prefix="/samples", tags=["samples"])
    app.include_router(manage_routes.router, prefix="/manage", tags=["manage"])
    app.include_router(warnings_routes.router, prefix="/samples", tags=["warnings"])
    app.include_router(extras.router, prefix="/extras", tags=["extras"])
    app.include_router(filters.router, prefix="/filters", tags=["filters"])
    app.include_router(stats.router, prefix="/stats", tags=["stats"])
    app.include_router(tomograms.router, prefix="/tomograms", tags=["tomograms"])
    app.include_router(
        annotations_routes.router, prefix="/annotations", tags=["annotations"]
    )
    app.include_router(
        acquisitions_routes.router, prefix="/acquisitions", tags=["acquisitions"]
    )
    app.include_router(
        tilt_series_routes.router, prefix="/tilt-series", tags=["tilt-series"]
    )
    app.include_router(thumbnails_routes.router, prefix="/thumbnails", tags=["thumbnails"])
    app.include_router(toml_authoring.router, prefix="/toml", tags=["toml"])
    app.include_router(
        md_previews_routes.router, prefix="/md-previews", tags=["md-previews"]
    )
    return app


app = create_app()
