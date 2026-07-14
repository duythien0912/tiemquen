"""Compose cache — data/composed/<slug>/<variant>.json (ENGINE-SPEC §1/§10).

Buyer page đọc THẲNG các file này (static, cache-control ngắn) — không LLM,
không validate lại. Hết món / đổi giá KHÔNG recompose structure: patch_data()
append 1 message updateDataModel vào cuối từng file variant (renderer áp
message theo thứ tự nên patch sau đè data trước). Recompose chỉ khi menu/theme
đổi cấu trúc (write_variants ghi đè cả file).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from agents.tiemquen_agent import a2ui

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMPOSED_DIR = REPO_ROOT / "data" / "composed"

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class CacheError(Exception):
    pass


def _check(name: str, kind: str) -> str:
    if not name or not _SAFE_NAME_RE.match(name) or name in {".", ".."}:
        raise CacheError(f"invalid {kind}: {name!r}")
    return name


class ComposeCache:
    """File-backed cache of composed A2UI variants, keyed (slug, variant)."""

    def __init__(self, base_dir: str | os.PathLike[str] = DEFAULT_COMPOSED_DIR) -> None:
        self.base_dir = Path(base_dir)

    def variant_path(self, slug: str, variant: str) -> Path:
        return self.base_dir / _check(slug, "slug") / f"{_check(variant, 'variant')}.json"

    # ------------------------------------------------------------------ write

    def _write(self, path: Path, messages: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(messages, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def write_variant(self, slug: str, variant: str, messages: list[dict[str, Any]]) -> Path:
        """Overwrite one composed variant (structural recompose)."""
        path = self.variant_path(slug, variant)
        self._write(path, messages)
        return path

    def write_variants(self, slug: str, variants: dict[str, list[dict[str, Any]]]) -> list[Path]:
        return [self.write_variant(slug, v, msgs) for v, msgs in variants.items()]

    # ------------------------------------------------------------------- read

    def read_variant(self, slug: str, variant: str) -> list[dict[str, Any]] | None:
        path = self.variant_path(slug, variant)
        if not path.is_file():
            return None
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def list_variants(self, slug: str) -> list[str]:
        d = self.base_dir / _check(slug, "slug")
        if not d.is_dir():
            return []
        return sorted(p.stem for p in d.glob("*.json"))

    # ------------------------------------------------------------------ patch

    def patch_data(self, slug: str, path: str, value: Any) -> list[str]:
        """Sold-out/price change: append an updateDataModel PATCH to every
        cached variant of the shop — NO structural recompose (SPEC §1).

        A repeated patch on the same data path replaces the previous trailing
        patch message instead of growing the file forever. Returns the list of
        patched variant names.
        """
        if not isinstance(path, str) or not path.startswith("/"):
            raise CacheError(f"patch path must be a /pointer, got {path!r}")

        patched: list[str] = []
        for variant in self.list_variants(slug):
            messages = self.read_variant(slug, variant)
            if not messages:
                continue
            surface_id = _first_surface_id(messages)
            patch = a2ui.make_update_data_model(surface_id, path, value)

            replaced = False
            for i in range(len(messages) - 1, -1, -1):
                upd = messages[i].get("updateDataModel")
                if upd and upd.get("path") == path and upd.get("surfaceId") == surface_id:
                    messages[i] = patch
                    replaced = True
                    break
                if "updateDataModel" not in messages[i]:
                    break  # only coalesce within the trailing patch run
            if not replaced:
                messages.append(patch)

            self._write(self.variant_path(slug, variant), messages)
            patched.append(variant)
        return patched

    def delete_shop(self, slug: str) -> int:
        """Drop all cached variants for a shop. Returns number removed."""
        n = 0
        for variant in self.list_variants(slug):
            self.variant_path(slug, variant).unlink()
            n += 1
        return n


def _first_surface_id(messages: list[dict[str, Any]]) -> str:
    for msg in messages:
        for action in a2ui.ACTION_KEYS:
            payload = msg.get(action)
            if isinstance(payload, dict) and payload.get("surfaceId"):
                return payload["surfaceId"]
    return a2ui.DEFAULT_SURFACE_ID
