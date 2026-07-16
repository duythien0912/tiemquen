"""HTML parse — best-effort ShopeeFood menu scrape (ENGINE-SPEC §5, ARCH §3.1).

NOT the primary import path (OCR screenshot is — ARCH §3.1/§4.5: Grab menu is
confirmed unreachable via plain HTTP as of 07/2026, `portal.grab.com` 502s any
anti-bot-looking request). ShopeeFood *sometimes* ships menu data inline as a
JSON blob in a `<script>` tag for an SPA shell — this module makes a single
best-effort attempt at that, and is written to fail LOUDLY and CHEAPLY
(`ImportFallbackToOCR`) rather than guess wrong: a confidently-wrong scrape
that silently produces garbage prices is worse than telling the seller
"chụp screenshot đi". Every failure mode (network, non-2xx, no embedded JSON,
unexpected shape, zero dishes found) raises the same exception so the caller
has exactly one thing to catch.

No dependency on scrape succeeding for the product to work end to end — this
path is entirely optional convenience on top of the OCR path (§4.5: "import
tách khỏi serve — nguồn chết không làm chết tiệm đã publish").
"""

from __future__ import annotations

import json
import re
from typing import Any

import requests
from bs4 import BeautifulSoup

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

#: Keys a dish-like dict is expected to carry (best-effort — ShopeeFood's
#: actual embedded-JSON shape is not publicly documented / may change).
_NAME_KEYS = ("name", "title", "dish_name", "item_name")
_PRICE_KEYS = ("price", "price_display", "sale_price", "salePrice", "current_price")

#: Script patterns that commonly carry SPA hydration state.
_JSON_SCRIPT_PATTERNS = (
    re.compile(r"window\.__NEXT_DATA__\s*=\s*(\{.*\})\s*;?\s*$", re.DOTALL),
    re.compile(r"window\.__NUXT__\s*=\s*(\{.*\})\s*;?\s*$", re.DOTALL),
    re.compile(r"window\.__INITIAL_STATE__\s*=\s*(\{.*\})\s*;?\s*$", re.DOTALL),
)


class ImportFallbackToOCR(Exception):
    """HTML parse gave up — caller should ask the seller for a screenshot instead."""


def _extract_embedded_json(soup: BeautifulSoup) -> list[Any]:
    """Every JSON blob we can find in <script> tags (Next.js hydration data,
    `application/json`/`application/ld+json`, or `window.__X__ = {...}`)."""
    blobs: list[Any] = []

    tag = soup.find("script", id="__NEXT_DATA__")
    if tag and tag.string:
        try:
            blobs.append(json.loads(tag.string))
        except json.JSONDecodeError:
            pass

    for tag in soup.find_all("script", type=lambda t: t in ("application/json", "application/ld+json")):
        if not tag.string:
            continue
        try:
            blobs.append(json.loads(tag.string))
        except json.JSONDecodeError:
            continue

    for tag in soup.find_all("script"):
        text = tag.string or tag.get_text() or ""
        for pattern in _JSON_SCRIPT_PATTERNS:
            m = pattern.search(text.strip())
            if m:
                try:
                    blobs.append(json.loads(m.group(1)))
                except json.JSONDecodeError:
                    continue
    return blobs


def _looks_like_dish(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    has_name = any(k in obj for k in _NAME_KEYS) and isinstance(
        next((obj[k] for k in _NAME_KEYS if k in obj), None), str
    )
    has_price = any(k in obj for k in _PRICE_KEYS)
    return has_name and has_price


def _find_dish_lists(obj: Any, _depth: int = 0) -> list[list[dict[str, Any]]]:
    """Recursively walk a parsed JSON tree for lists that look like dish arrays."""
    if _depth > 12:  # bail out of pathological/cyclic-looking structures
        return []
    found: list[list[dict[str, Any]]] = []
    if isinstance(obj, list):
        dish_items = [x for x in obj if _looks_like_dish(x)]
        if len(dish_items) >= 2:
            found.append(dish_items)
        for item in obj:
            found += _find_dish_lists(item, _depth + 1)
    elif isinstance(obj, dict):
        for value in obj.values():
            found += _find_dish_lists(value, _depth + 1)
    return found


def _price_of(dish: dict[str, Any]) -> int:
    for key in _PRICE_KEYS:
        if key in dish:
            raw = dish[key]
            digits = re.sub(r"[^\d]", "", str(raw))
            if digits:
                return int(digits)
    raise ValueError("dish has no parseable price")


def _name_of(dish: dict[str, Any]) -> str:
    for key in _NAME_KEYS:
        if isinstance(dish.get(key), str) and dish[key].strip():
            return dish[key].strip()
    raise ValueError("dish has no name")


def _shop_name(soup: BeautifulSoup) -> str | None:
    meta = soup.find("meta", property="og:site_name") or soup.find("meta", property="og:title")
    if meta and meta.get("content"):
        return meta["content"].strip()
    if soup.title and soup.title.string:
        # Titles are usually "<Shop name> - ShopeeFood" — keep the first segment.
        return soup.title.string.split("|")[0].split("-")[0].strip() or None
    return None


def parse_shopeefood(url: str, *, timeout: float = 10.0, session: Any = None) -> dict[str, Any]:
    """Best-effort scrape -> `{"shop_name": str, "sections": [...], "source_url": url}`.

    `sections` = `[{"title": str, "dishes": [{"name","price","desc?","image_url?"}]}]`.
    Raises `ImportFallbackToOCR` on ANY failure — see module docstring.
    """
    getter = session.get if session is not None else requests.get
    try:
        resp = getter(url, timeout=timeout, headers=_HEADERS)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise ImportFallbackToOCR(f"fetch {url!r} thất bại: {e}") from e

    soup = BeautifulSoup(resp.text, "html.parser")
    blobs = _extract_embedded_json(soup)
    if not blobs:
        raise ImportFallbackToOCR(
            "không tìm thấy dữ liệu menu nhúng trong HTML (khả năng là SPA render "
            "phía client hoặc trang chặn bot) — rơi về OCR screenshot"
        )

    candidate_lists = [lst for blob in blobs for lst in _find_dish_lists(blob)]
    if not candidate_lists:
        raise ImportFallbackToOCR("HTML có JSON nhúng nhưng không thấy danh sách món — rơi về OCR screenshot")

    dish_items = max(candidate_lists, key=len)
    dishes: list[dict[str, Any]] = []
    for raw in dish_items:
        try:
            name = _name_of(raw)
            price = _price_of(raw)
        except (ValueError, TypeError):
            continue  # skip unparseable entries, keep the rest
        dish: dict[str, Any] = {"name": name, "price": price}
        desc = raw.get("description") or raw.get("desc")
        if isinstance(desc, str) and desc.strip():
            dish["desc"] = desc.strip()
        image = raw.get("image") or raw.get("image_url") or raw.get("thumbnail")
        if isinstance(image, str) and image.strip():
            dish["image_url"] = image.strip()
        dishes.append(dish)

    if not dishes:
        raise ImportFallbackToOCR("parse ra 0 món hợp lệ — rơi về OCR screenshot")

    shop_name = _shop_name(soup)
    if not shop_name:
        raise ImportFallbackToOCR("không xác định được tên quán từ trang — rơi về OCR screenshot")

    return {
        "shop_name": shop_name,
        "sections": [{"title": "Menu", "dishes": dishes}],
        "source_url": url,
    }
