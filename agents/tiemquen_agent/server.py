"""Tiệm Quen agent server — FastAPI app factory (ENGINE-SPEC §3).

Phase 1 (foundation): /health + minimal shops CRUD + static mounts.
Later phases add agent routes (import, interview, storefront, flyer,
order-parse, reminder) under deterministic prefixes.

Run:
    ./.venv/bin/uvicorn agents.tiemquen_agent.server:app --reload
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import jsonschema
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from compose.cache import ComposeCache
from compose.composer import compose_all_variants
from infra.publish import SlugRegistry
from infra.storage import LocalJSONStorage, Storage
from shared.menu_format import load_demo_fixture, validate_menu

REPO_ROOT = Path(__file__).resolve().parents[2]
SHOPS_COLLECTION = "shops"


def create_app(
    storage: Storage | None = None, composed_dir: Path | None = None
) -> FastAPI:
    """Build the app. Inject `storage` for tests; default = data/ on disk.

    Runs entirely without GEMINI_API_KEY — LLM calls are compose-time only
    (mock mode composes from templates, zero network).
    """
    if storage is None:
        data_dir = Path(os.environ.get("TIEMQUEN_DATA_DIR", REPO_ROOT / "data"))
        storage = LocalJSONStorage(data_dir)
    if composed_dir is None:
        # Keep the compose cache next to whatever data dir storage uses.
        base = getattr(storage, "base_dir", REPO_ROOT / "data")
        composed_dir = Path(base) / "composed"

    registry = SlugRegistry(storage)
    cache = ComposeCache(composed_dir)
    app = FastAPI(title="Tiệm Quen agent server", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------ health

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "tiemquen-agent"}

    # ------------------------------------------------------- shops (minimal CRUD)

    @app.post("/api/shops", status_code=201)
    def create_shop(doc: dict[str, Any] | None = None) -> dict[str, Any]:
        """Create a shop from a chuẩn-menu-format doc.

        Empty/omitted body -> seed from data/fixtures/demo_shop.json (dev bootstrap).
        Validates against shared/menu_schema.json, claims a unique slug,
        stores under shops/<shop_id>.
        """
        if not doc:
            doc = load_demo_fixture()
        doc = copy.deepcopy(doc)

        try:
            validate_menu(doc)
        except jsonschema.ValidationError as e:
            raise HTTPException(status_code=422, detail=f"invalid menu doc: {e.message}")

        shop = doc["shop"]
        shop_id = shop["id"]
        if storage.exists(SHOPS_COLLECTION, shop_id):
            raise HTTPException(status_code=409, detail=f"shop {shop_id!r} already exists")

        slug = registry.register(shop_id, shop["name"], preferred_slug=shop.get("slug"))
        shop["slug"] = slug  # registry may have suffixed it for uniqueness
        storage.put(SHOPS_COLLECTION, shop_id, doc)
        return doc

    @app.get("/api/shops")
    def list_shops() -> dict[str, Any]:
        return {"shop_ids": storage.list(SHOPS_COLLECTION)}

    @app.get("/api/shops/{slug}")
    def get_shop_by_slug(slug: str) -> dict[str, Any]:
        shop_id = registry.resolve(slug)
        if shop_id is None:
            raise HTTPException(status_code=404, detail=f"no shop at slug {slug!r}")
        doc = storage.get(SHOPS_COLLECTION, shop_id)
        if doc is None:  # slug points at a deleted shop
            raise HTTPException(status_code=404, detail=f"shop {shop_id!r} not found")
        return doc

    @app.delete("/api/shops/{slug}", status_code=204)
    def delete_shop(slug: str) -> None:
        shop_id = registry.resolve(slug)
        if shop_id is None:
            raise HTTPException(status_code=404, detail=f"no shop at slug {slug!r}")
        storage.delete(SHOPS_COLLECTION, shop_id)
        registry.release(slug)
        cache.delete_shop(slug)

    # ------------------------------------------------------------ compose engine

    def _resolve_shop(slug: str) -> dict[str, Any]:
        shop_id = registry.resolve(slug)
        doc = storage.get(SHOPS_COLLECTION, shop_id) if shop_id else None
        if doc is None:
            raise HTTPException(status_code=404, detail=f"no shop at slug {slug!r}")
        return doc

    @app.post("/api/shops/{slug}/compose")
    def compose_shop(slug: str) -> dict[str, Any]:
        """Recompose ALL variants (ARCH §5.3) and overwrite the cache.

        Structural recompose — only for menu/theme changes. Sold-out/price
        changes must use /patch instead (no LLM, no recompose).
        """
        doc = _resolve_shop(slug)
        variants = compose_all_variants(doc)
        cache.write_variants(slug, variants)
        return {
            "slug": slug,
            "variants": sorted(variants),
            "message_counts": {v: len(msgs) for v, msgs in variants.items()},
        }

    @app.post("/api/shops/{slug}/patch")
    def patch_shop(slug: str, body: dict[str, Any]) -> dict[str, Any]:
        """Sold-out / price change: updateDataModel PATCH appended to every
        cached variant — NO structural recompose (ENGINE-SPEC §1).

        Body: {"path": "/soldout/<dish_id>", "value": true}
           or {"dish_id": "...", "sold_out": true} / {"dish_id": "...", "price": 40000}
              / {"dish_id": "...", "almost_out": true}.
        Also syncs the shop doc so the next recompose starts from fresh flags.
        """
        doc = _resolve_shop(slug)
        dishes = doc["menu"]["dishes"]

        patches: list[tuple[str, Any]] = []
        if "path" in body:
            if "value" not in body:
                raise HTTPException(status_code=422, detail="patch needs path AND value")
            patches.append((body["path"], body["value"]))
        elif "dish_id" in body:
            dish_id = body["dish_id"]
            if dish_id not in dishes:
                raise HTTPException(status_code=404, detail=f"unknown dish {dish_id!r}")
            for field, prefix in (("sold_out", "/soldout"), ("almost_out", "/almostout"),
                                  ("price", "/prices")):
                if field in body:
                    patches.append((f"{prefix}/{dish_id}", body[field]))
            if not patches:
                raise HTTPException(
                    status_code=422, detail="dish_id given but no sold_out/almost_out/price"
                )
        else:
            raise HTTPException(status_code=422, detail="need path+value or dish_id form")

        # Sync shop store so flags survive the next structural recompose.
        doc_changed = False
        for path, value in patches:
            if not isinstance(path, str) or not path.startswith("/"):
                raise HTTPException(status_code=422, detail=f"bad patch path {path!r}")
            parts = path.strip("/").split("/")
            if len(parts) == 2 and parts[1] in dishes:
                field = {"soldout": "sold_out", "almostout": "almost_out",
                         "prices": "price"}.get(parts[0])
                if field:
                    dishes[parts[1]][field] = value
                    doc_changed = True
        if doc_changed:
            storage.put(SHOPS_COLLECTION, doc["shop"]["id"], doc)

        patched: set[str] = set()
        for path, value in patches:
            patched.update(cache.patch_data(slug, path, value))
        return {
            "slug": slug,
            "patches": [{"path": p, "value": v} for p, v in patches],
            "patched_variants": sorted(patched),
        }

    @app.get("/api/shops/{slug}/composed/{variant}")
    def get_composed_variant(slug: str, variant: str) -> Any:
        """Serve one cached A2UI variant (what the buyer page fetches in dev)."""
        _resolve_shop(slug)
        messages = cache.read_variant(slug, variant)
        if messages is None:
            raise HTTPException(status_code=404, detail=f"variant {variant!r} not composed yet")
        return messages

    # ----------------------------------------------------------- static mounts
    # buyer/ + seller/ are committed static sites; data/media holds rehosted
    # images (gitignored) — create so the mount never 500s on a fresh clone.

    media_dir = REPO_ROOT / "data" / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/buyer", StaticFiles(directory=REPO_ROOT / "buyer", html=True), name="buyer")
    app.mount("/seller", StaticFiles(directory=REPO_ROOT / "seller", html=True), name="seller")
    app.mount("/media", StaticFiles(directory=media_dir), name="media")

    return app


app = create_app()
