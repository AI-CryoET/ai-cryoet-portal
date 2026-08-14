"""GET /md-previews/{relpath:path} — stream a cached OVITO/MD preview PNG.

The scanner renders these itself (OVITO TachyonRenderer, subprocess-isolated
— see :func:`catalog.md_previews.generate_md_previews`) into
``$CATALOG_MD_PREVIEW_DIR``, one PNG per MD run at ``{sample_id}/{md_run_id}.png``
(``md_runs.preview_path`` in the DB). This route only *serves* that cache.
Mirrors the thumbnails route (sync handler + path-traversal guard + cache
headers).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

router = APIRouter()


def _serve(resolved, root):
    """Validate a resolved path is a PNG inside ``root`` and stream it."""
    if not resolved.is_relative_to(root) or resolved.suffix != ".png":
        raise HTTPException(404, "md preview not found")
    return FileResponse(
        resolved,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


# Sync (`def`) on purpose — see thumbnails.py: blocking reads against a
# (possibly networked) mount run in FastAPI's threadpool so they don't stall
# the event loop behind a burst of preview requests.
@router.get("/{relpath:path}")
def get_md_preview(relpath: str, request: Request):
    root = getattr(request.app.state, "md_preview_root", None)
    if root is None:
        raise HTTPException(404, "md previews not configured")
    try:
        resolved = (root / relpath).resolve(strict=True)
    except (FileNotFoundError, OSError):
        raise HTTPException(404, "md preview not found")
    return _serve(resolved, root)
