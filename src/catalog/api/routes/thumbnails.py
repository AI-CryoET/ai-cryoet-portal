"""GET /thumbnails/{relpath:path} — stream a pre-generated PNG from the cache."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

router = APIRouter()


# Sync (`def`, not `async def`) on purpose: the path resolution and file read are
# blocking I/O against the (possibly networked) thumbnail mount. FastAPI runs sync
# routes in a threadpool, so these calls don't block the event loop and stall
# unrelated requests (e.g. the /samples data query) behind a burst of thumbnails.
@router.get("/{relpath:path}")
def get_thumbnail(relpath: str, request: Request):
    root = getattr(request.app.state, "thumbnail_root", None)
    if root is None:
        raise HTTPException(404, "thumbnails not configured")
    try:
        resolved = (root / relpath).resolve(strict=True)
    except (FileNotFoundError, OSError):
        raise HTTPException(404, "thumbnail not found")
    if not resolved.is_relative_to(root) or resolved.suffix != ".png":
        raise HTTPException(404, "thumbnail not found")
    return FileResponse(
        resolved,
        media_type="image/png",
        # 1-day fresh window, then revalidate. NOT immutable: thumbnails are
        # path-addressed (a re-scan rewrites the same URL), so the browser must
        # be able to revalidate and pick up a regenerated image — cheap because
        # FileResponse serves a 304 off its mtime/size ETag on the unchanged case.
        headers={"Cache-Control": "public, max-age=86400"},
    )
