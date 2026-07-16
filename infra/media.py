"""Image rehost stub (ENGINE-SPEC §3 `infra/`, used by §5 import agent).

Dish images from import sources (Grab screenshot links, ShopeeFood, seller-
pasted URLs) point at a CDN we don't control and that can vanish (ARCH §4.5:
"nguồn sàn chết không làm chết tiệm đã publish" — so images must not depend
on the source staying up either). This module copies/downloads those images
into our OWN storage (`data/media/<shop_slug>/`) and rewrites `image_url` to
a `/media/...` path that `server.py`'s static mount serves.

Deliberately a STUB: local disk only, no resizing/optimization/CDN — that is
a later-phase concern per ARCH roadmap, not something the MVP import path
needs to get right on day one.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEDIA_DIR = REPO_ROOT / "data" / "media"

_HEADERS = {"User-Agent": "TiemQuenBot/0.1 (+https://tiemquen.com)"}
_SAFE_ID_RE = re.compile(r"[^a-zA-Z0-9._-]+")
_KNOWN_EXTS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif"})
_DEFAULT_EXT = ".jpg"
_EXT_BY_CONTENT_TYPE = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


class MediaRehostError(Exception):
    pass


def _guess_ext(ref: str, content_type: str | None = None) -> str:
    if content_type:
        mapped = _EXT_BY_CONTENT_TYPE.get(content_type.split(";")[0].strip())
        if mapped:
            return mapped
    suffix = Path(urlparse(ref).path).suffix.lower()
    return suffix if suffix in _KNOWN_EXTS else _DEFAULT_EXT


def _dish_filename(dish_id: str, ref: str, content_type: str | None = None) -> str:
    safe_id = _SAFE_ID_RE.sub("_", dish_id) or "dish"
    return f"{safe_id}{_guess_ext(ref, content_type)}"


def rehost_one(
    ref: str, dest_dir: Path, dish_id: str, *, session: Any = None, timeout: float = 10.0
) -> Path:
    """Copy (local path) or download (http/https URL) ONE image into `dest_dir`.

    Raises `MediaRehostError` on any failure — best-effort callers (e.g.
    `rehost_dish_images`) catch this and keep the original ref instead of
    failing the whole import over one dead image link. `dest_dir` is only
    created once we know there's something to write into it.
    """
    dest_dir = Path(dest_dir)

    if ref.startswith("http://") or ref.startswith("https://"):
        getter = session.get if session is not None else requests.get
        try:
            resp = getter(ref, headers=_HEADERS, timeout=timeout)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise MediaRehostError(f"download {ref!r} thất bại: {e}") from e
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / _dish_filename(dish_id, ref, resp.headers.get("Content-Type"))
        dest.write_bytes(resp.content)
        return dest

    src = Path(ref)
    if not src.is_file():
        raise MediaRehostError(f"ảnh nguồn không tồn tại: {ref!r}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / _dish_filename(dish_id, ref)
    shutil.copyfile(src, dest)
    return dest


def rehost_dish_images(
    menu_doc: dict[str, Any], *, media_dir: Path | None = None, session: Any = None
) -> list[str]:
    """Rehost every dish `image_url` not already under `/media/` into
    `data/media/<shop_slug>/`, rewriting `menu_doc` IN PLACE.

    Best-effort per dish: a failure keeps the dish's original `image_url` and
    contributes a warning string instead of raising — one dead image link
    must not fail the whole import (ARCH §4.5).
    """
    slug = menu_doc["shop"]["slug"]
    dest_dir = Path(media_dir or DEFAULT_MEDIA_DIR) / slug
    warnings: list[str] = []

    for dish_id, dish in menu_doc["menu"]["dishes"].items():
        ref = dish.get("image_url")
        if not ref or ref.startswith("/media/"):
            continue
        try:
            dest = rehost_one(ref, dest_dir, dish_id, session=session)
        except MediaRehostError as e:
            warnings.append(f"ảnh món {dish.get('name', dish_id)!r} không rehost được: {e}")
            continue
        dish["image_url"] = f"/media/{slug}/{dest.name}"

    return warnings


__all__ = ["rehost_dish_images", "rehost_one", "MediaRehostError", "DEFAULT_MEDIA_DIR"]
