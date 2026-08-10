"""GET /md-previews/{relpath:path} — stream a cached OVITO/MD preview PNG.

These previews are rendered upstream by aicryoet-tools (OVITO TachyonRenderer)
into a flat ``.portal_cache`` directory; filenames look like
``{data_type}_{sampleId}..._preview.png``. For now this route only *serves*
the cache — generation/scanning of these PNGs lands later. Mirrors the
thumbnails route (sync handler + path-traversal guard + cache headers).
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
        # 1-day fresh window, then revalidate. NOT immutable: previews are
        # path-addressed (a re-scan rewrites the same URL), so the browser must
        # be able to revalidate and pick up a regenerated image — cheap because
        # FileResponse serves a 304 off its mtime/size ETag on the unchanged case.
        headers={"Cache-Control": "public, max-age=86400"},
    )


# Resolve a preview from just the predictable prefix ({data_type}_{sampleId},
# e.g. "Slab_12mer_25_0.073"). The cached filename has an unpredictable middle
# (run/trajectory/wrap tokens), so the caller can't name it exactly — we glob
# "{prefix}*_preview.png" and serve the first match. Registered before the
# catch-all below so "/by-prefix/..." isn't swallowed by {relpath:path}.
@router.get("/by-prefix/{prefix}")
def get_md_preview_by_prefix(prefix: str, request: Request):
    root = getattr(request.app.state, "md_preview_root", None)
    if root is None:
        raise HTTPException(404, "md previews not configured")
    # prefix is a single flat token — reject anything that could escape root.
    if "/" in prefix or "\\" in prefix or ".." in prefix:
        raise HTTPException(404, "md preview not found")
    for match in sorted(root.glob(f"{prefix}*_preview.png")):
        try:
            return _serve(match.resolve(strict=True), root)
        except (FileNotFoundError, OSError):
            continue
    raise HTTPException(404, "md preview not found")


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
