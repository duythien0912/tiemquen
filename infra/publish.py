"""Per-shop slug registry (ENGINE-SPEC §3 infra/publish.py).

Slug = URL công khai của tiệm: tiemquen.com/<slug>. Yêu cầu:
- slugify tên tiếng Việt (bỏ dấu, đ -> d, lowercase, gạch ngang)
- duy nhất toàn hệ thống (đụng nhau -> hậu tố -2, -3, ...)
- không đụng reserved words (route hệ thống: api, health, buyer, seller, ...)

Registry lưu qua Storage collection "slugs": slug -> {"shop_id": ...}.
"""

from __future__ import annotations

import re
import unicodedata

from infra.storage import Storage

SLUGS_COLLECTION = "slugs"

#: Slugs that would collide with system routes / static mounts / brand.
RESERVED_SLUGS: frozenset[str] = frozenset(
    {
        "api",
        "health",
        "admin",
        "static",
        "assets",
        "media",
        "data",
        "buyer",
        "seller",
        "shop",
        "shops",
        "order",
        "orders",
        "qr",
        "docs",
        "openapi.json",
        "www",
        "app",
        "tiemquen",
        "tiem-quen",
        "about",
        "login",
        "signup",
    }
)

_NON_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """'Cơm Tấm Cô Ba' -> 'com-tam-co-ba' (bỏ dấu, đ->d, lowercase)."""
    s = name.strip().lower()
    # đ has no combining-mark decomposition — map it explicitly.
    s = s.replace("đ", "d")
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = _NON_SLUG_RE.sub("-", s).strip("-")
    return s


class SlugRegistryError(Exception):
    pass


class SlugRegistry:
    """Uniqueness + reserved-word guard on top of a Storage backend."""

    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    def resolve(self, slug: str) -> str | None:
        """Return the shop_id owning `slug`, or None."""
        doc = self.storage.get(SLUGS_COLLECTION, slug)
        return doc["shop_id"] if doc else None

    def is_available(self, slug: str) -> bool:
        return slug not in RESERVED_SLUGS and self.resolve(slug) is None

    def register(self, shop_id: str, name: str, preferred_slug: str | None = None) -> str:
        """Claim a unique slug for `shop_id` and return it.

        Prefers `preferred_slug` (if given and valid), else slugify(name).
        Re-registering the same shop with the same base slug is idempotent.
        Collisions/reserved words get numeric suffixes: com-tam-co-ba-2, -3, ...
        """
        base = slugify(preferred_slug) if preferred_slug else slugify(name)
        if not base:
            base = slugify(shop_id)
        if not base:
            raise SlugRegistryError(f"cannot derive slug from {name!r} / {shop_id!r}")

        candidate = base
        n = 1
        while True:
            if candidate not in RESERVED_SLUGS:
                owner = self.resolve(candidate)
                if owner is None:
                    self.storage.put(SLUGS_COLLECTION, candidate, {"shop_id": shop_id})
                    return candidate
                if owner == shop_id:  # already ours — idempotent
                    return candidate
            n += 1
            candidate = f"{base}-{n}"

    def release(self, slug: str) -> bool:
        """Free a slug (shop deleted/renamed). Returns True if it existed."""
        return self.storage.delete(SLUGS_COLLECTION, slug)
