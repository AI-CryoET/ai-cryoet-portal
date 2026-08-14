"""FastAPI app factory for the catalog read-only API.

The API runs separately from the scanner (the scanner writes; the API reads).
Configuration via environment:
  CATALOG_DB_URL             — SQLAlchemy URL (default: sqlite:///catalog.db)
  CORS_ORIGINS               — comma-separated allowed origins (default: http://localhost:5173)
  CATALOG_DATA_ROOT          — filesystem root that bounds all preview/viewer-launch reads.
                               Required at startup; the API refuses to start without it.
  CATALOG_THUMBNAIL_DIR      — directory containing pre-generated thumbnail PNGs.
                               Defaults to ./data/.thumbnail-cache in the cwd (kept
                               out of the shared CATALOG_DATA_ROOT so concurrent devs
                               don't race on the same cache files); the API refuses
                               to start if the resolved dir is missing.
  CATALOG_MD_PREVIEW_DIR     — directory of cached OVITO/MD preview PNGs. Defaults to
                               ./data/.md-preview-cache in the cwd; a missing dir
                               just disables the /md-previews route.
"""
from __future__ import annotations
import inspect
import logging
import os
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

    # CATALOG_DATA_ROOT is required for preview/viewer-launch routes. Tests may
    # pre-seed app.state.data_root_resolved to avoid needing a real directory.
    pre_seeded_root = getattr(app.state, "data_root_resolved", None) is not None
    if not pre_seeded_root:
        raw_root = os.environ.get("CATALOG_DATA_ROOT")
        if not raw_root:
            raise RuntimeError(
                "CATALOG_DATA_ROOT is required (filesystem root bounding all "
                "preview/viewer-launch reads). Set it to the dir under which "
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
        thumb_path = (
            Path(raw_thumb) if raw_thumb else Path.cwd() / "data" / ".thumbnail-cache"
        )
        try:
            resolved_thumb = thumb_path.resolve(strict=True)
        except (FileNotFoundError, OSError) as exc:
            raise RuntimeError(
                f"CATALOG_THUMBNAIL_DIR={str(thumb_path)!r} does not exist or is "
                "unreadable. Generate thumbnails with: "
                "CATALOG_DATA_ROOT=... pixi run scan --init"
            ) from exc
        if not resolved_thumb.is_dir():
            raise RuntimeError(f"CATALOG_THUMBNAIL_DIR={str(thumb_path)!r} is not a directory")
        app.state.thumbnail_root = resolved_thumb

    # CATALOG_MD_PREVIEW_DIR — directory of cached OVITO/MD preview PNGs
    # Optional: a missing/bad dir just disables the route (404) rather
    # than failing startup. Tests may pre-seed app.state.md_preview_root.
    if not hasattr(app.state, "md_preview_root"):
        raw_md = os.environ.get("CATALOG_MD_PREVIEW_DIR")
        md_path = (
            Path(raw_md) if raw_md else Path.cwd() / "data" / ".md-preview-cache"
        )
        try:
            resolved_md = md_path.resolve(strict=True)
            app.state.md_preview_root = resolved_md if resolved_md.is_dir() else None
        except (FileNotFoundError, OSError):
            app.state.md_preview_root = None
        if app.state.md_preview_root is None:
            logger.warning(
                "CATALOG_MD_PREVIEW_DIR={!r} not found; /md-previews disabled", str(md_path)
            )

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
