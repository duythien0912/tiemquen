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

from infra.publish import SlugRegistry
from infra.storage import LocalJSONStorage, Storage
from shared.menu_format import load_demo_fixture, validate_menu

REPO_ROOT = Path(__file__).resolve().parents[2]
SHOPS_COLLECTION = "shops"


def create_app(storage: Storage | None = None) -> FastAPI:
    """Build the app. Inject `storage` for tests; default = data/ on disk.

    Runs entirely without GEMINI_API_KEY — LLM calls are compose-time only
    and live behind agent routes added in later phases.
    """
    if storage is None:
        data_dir = Path(os.environ.get("TIEMQUEN_DATA_DIR", REPO_ROOT / "data"))
        storage = LocalJSONStorage(data_dir)

    registry = SlugRegistry(storage)
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
