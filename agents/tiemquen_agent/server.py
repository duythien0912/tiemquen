"""Tiệm Quen agent server — FastAPI app factory (ENGINE-SPEC §3).

Phase 1 (foundation): /health + minimal shops CRUD + static mounts.
Phase (orders): buyer page + order state machine + notify + group orders +
order-parse, all under the ZERO-LLM buyer path (ENGINE-SPEC §0/§8) — the
only LLM call anywhere in this file is /api/import and /api/shops/{slug}/compose,
both compose/seller-side, never on the buyer's click-to-checkout path.

Run:
    ./.venv/bin/uvicorn agents.tiemquen_agent.server:app --reload
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import jsonschema
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from agents.tiemquen_agent import imagen
from agents.tiemquen_agent.agents import import_agent
from agents.tiemquen_agent.agents.html_parse import ImportFallbackToOCR
from agents.tiemquen_agent.agents.order_parse_agent import parse_order_text
from compose.cache import ComposeCache
from compose.composer import VARIANTS, compose_all_variants
from infra import pdf_export
from infra.group_orders import GroupOrderError, GroupOrderNotFoundError, GroupOrderStore
from infra.notify import NotifyPipeline
from infra.orders import (
    STATUS_MESSAGES,
    OrderError,
    OrderNotFoundError,
    OrderStore,
    OrderTransitionError,
)
from infra.publish import SlugRegistry
from infra.qr_batch import (
    FLYER_FORMATS,
    BatchError,
    BatchNotFoundError,
    BatchStore,
    orders_per_batch,
    qr_url,
)
from infra.storage import LocalJSONStorage, Storage
from shared.menu_format import apply_menu_edits, load_demo_fixture, validate_menu, MenuEditError

REPO_ROOT = Path(__file__).resolve().parents[2]
SHOPS_COLLECTION = "shops"


def create_app(
    storage: Storage | None = None,
    composed_dir: Path | None = None,
    media_dir: Path | None = None,
) -> FastAPI:
    """Build the app. Inject `storage` for tests; default = data/ on disk.

    Runs entirely without GEMINI_API_KEY — LLM calls are compose-time only
    (mock mode composes from templates, zero network; imagen falls back to
    Pillow placeholders so the flyer path works offline too).
    """
    if storage is None:
        data_dir = Path(os.environ.get("TIEMQUEN_DATA_DIR", REPO_ROOT / "data"))
        storage = LocalJSONStorage(data_dir)
    if composed_dir is None:
        # Keep the compose cache next to whatever data dir storage uses.
        base = getattr(storage, "base_dir", REPO_ROOT / "data")
        composed_dir = Path(base) / "composed"
    if media_dir is None:
        media_dir = REPO_ROOT / "data" / "media"
    media_dir = Path(media_dir)

    registry = SlugRegistry(storage)
    cache = ComposeCache(composed_dir)
    order_store = OrderStore(storage)
    group_store = GroupOrderStore(storage)
    batch_store = BatchStore(storage)
    notify_pipeline = NotifyPipeline()
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

    # ------------------------------------------------------------- import agent
    # ENGINE-SPEC §5. Not `/import` bare — kept under the same `/api` prefix as
    # every other route in this server for routing consistency (see
    # implementation-notes/ImportAgent.html for the deviation from the literal
    # task wording). Returns the review envelope {menu, warnings, confidence};
    # it does NOT persist a shop — the seller reviews first, then the existing
    # POST /api/shops call finalizes (ARCH §3.1).

    @app.post("/api/import")
    async def import_menu_endpoint(request: Request) -> dict[str, Any]:
        """Multipart body: field `screenshot` (1+ files) -> OCR (đường chính).
        JSON body: `{"url": "..."}` (HTML parse, ShopeeFood best-effort) |
        `{"text": "..."}` (paste-menu text) | `{"fixture": "<name>"}` (dev/demo:
        replay `data/fixtures/<name>.json` recorded tool-calls directly).
        """
        content_type = request.headers.get("content-type", "")
        if content_type.startswith("multipart/form-data"):
            form = await request.form()
            uploads = form.getlist("screenshot")
            if not uploads:
                raise HTTPException(422, detail="multipart body cần field 'screenshot'")
            with tempfile.TemporaryDirectory() as tmp:
                paths: list[Path] = []
                for i, upload in enumerate(uploads):
                    suffix = Path(getattr(upload, "filename", "") or "").suffix or ".png"
                    dest = Path(tmp) / f"upload_{i}{suffix}"
                    dest.write_bytes(await upload.read())
                    paths.append(dest)
                try:
                    return import_agent.import_menu(paths)
                except Exception as e:
                    raise HTTPException(422, detail=f"import lỗi: {e}") from e

        raw = await request.body()
        body: dict[str, Any] = {}
        if raw:
            try:
                import json as _json

                body = _json.loads(raw)
            except ValueError as e:
                raise HTTPException(422, detail=f"JSON body không hợp lệ: {e}") from e

        try:
            if "fixture" in body:
                return import_agent.import_from_fixture(body["fixture"])
            if "url" in body:
                return import_agent.import_menu(body["url"])
            if "text" in body:
                return import_agent.import_menu(body["text"])
        except ImportFallbackToOCR as e:
            raise HTTPException(
                status_code=422, detail={"error": str(e), "fallback_to_ocr": True}
            ) from e
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"import lỗi: {e}") from e

        raise HTTPException(
            status_code=422,
            detail="cần multipart 'screenshot', hoặc JSON {'url'|'text'|'fixture': ...}",
        )

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

    # ------------------------------------------------------------- menu review
    # ARCH §3.1 seller review step: sửa giá trực tiếp, ẩn món, thêm món
    # "chỉ bán trực tiếp", đổi tên section. Unlike /patch above, these edits
    # change STRUCTURE (dishes/sections added or reshaped) so they go through
    # a full recompose, not a data-only patch.

    @app.get("/api/shops/{slug}/menu")
    def get_shop_menu(slug: str) -> dict[str, Any]:
        """Current chuẩn-menu `menu` block (sections + dishes) for the review UI."""
        doc = _resolve_shop(slug)
        return {"slug": slug, "menu": doc["menu"]}

    @app.patch("/api/shops/{slug}/menu")
    def patch_shop_menu(slug: str, body: dict[str, Any]) -> dict[str, Any]:
        """Apply seller review edits, persist, and RECOMPOSE (ARCH §3.1).

        Body: `{"edits": [...]}` — ops per `shared.menu_format.apply_menu_edits`:
        `set_price` · `hide_dish` · `add_dish` (supports `direct_only`) ·
        `retitle_section`. Structural change -> full recompose (all variants),
        unlike `/patch` (sold-out/price-only, data patch, no recompose).
        """
        edits = body.get("edits")
        if not isinstance(edits, list) or not edits:
            raise HTTPException(status_code=422, detail="body cần 'edits': [...] không rỗng")

        doc = copy.deepcopy(_resolve_shop(slug))
        try:
            warnings = apply_menu_edits(doc, edits)
            validate_menu(doc)
        except MenuEditError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        except jsonschema.ValidationError as e:
            raise HTTPException(status_code=422, detail=f"menu không hợp lệ sau edit: {e.message}") from e

        storage.put(SHOPS_COLLECTION, doc["shop"]["id"], doc)
        variants = compose_all_variants(doc)  # recompose (ENGINE-SPEC §1: structure đổi)
        cache.write_variants(slug, variants)
        return {
            "slug": slug,
            "menu": doc["menu"],
            "warnings": warnings,
            "recomposed_variants": sorted(variants),
        }

    @app.get("/api/shops/{slug}/composed/{variant}")
    def get_composed_variant(slug: str, variant: str) -> Any:
        """Serve one cached A2UI variant (what the buyer page fetches in dev)."""
        _resolve_shop(slug)
        messages = cache.read_variant(slug, variant)
        if messages is None:
            raise HTTPException(status_code=404, detail=f"variant {variant!r} not composed yet")
        return messages

    # ----------------------------------------------------------------- orders
    # ENGINE-SPEC §8, ARCH §3.2. ZERO LLM on every route below — buyer is a
    # plain REST client (buyer/order.js), seller ack/transition is the same.

    def _price_items(dishes: dict[str, Any], raw_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Server is the price authority — never trust client-sent prices.
        Also the sold-out gate: a race where the buyer's cached page still
        shows a dish that just sold out gets caught HERE, not client-side."""
        if not raw_items:
            raise HTTPException(status_code=422, detail="order cần ít nhất 1 món")
        items: list[dict[str, Any]] = []
        for raw in raw_items:
            dish_id = raw.get("dish_id")
            dish = dishes.get(dish_id)
            if dish is None:
                raise HTTPException(status_code=422, detail=f"món {dish_id!r} không tồn tại")
            qty = int(raw.get("qty", 1))
            if qty <= 0:
                raise HTTPException(status_code=422, detail=f"qty phải > 0 cho {dish_id!r}")
            if dish.get("sold_out"):
                raise HTTPException(status_code=409, detail=f"món {dish['name']!r} đã hết")
            items.append({"dish_id": dish_id, "name": dish["name"], "price": dish["price"], "qty": qty})
        return items

    def _require_customer(customer: dict[str, Any]) -> None:
        missing = [f for f in ("name", "phone", "address") if not customer.get(f)]
        if missing:
            raise HTTPException(status_code=422, detail=f"customer thiếu: {missing}")

    def _seller_phone(shop_doc: dict[str, Any]) -> str:
        shop = shop_doc["shop"]
        return shop.get("phone") or shop.get("zalo") or "unknown"

    @app.post("/orders", status_code=201)
    async def create_order(body: dict[str, Any], background_tasks: BackgroundTasks) -> dict[str, Any]:
        """COD checkout (default payment, ARCH §3.2). Fires the notify chain
        immediately, then schedules the ack-timeout SMS-fallback watcher —
        SLA #1: quán không ack trong ACK_TIMEOUT_SECONDS -> SMS."""
        slug = body.get("slug")
        if not slug:
            raise HTTPException(status_code=422, detail="cần 'slug'")
        doc = _resolve_shop(slug)
        items = _price_items(doc["menu"]["dishes"], body.get("items") or [])
        customer = body.get("customer") or {}
        _require_customer(customer)

        order = order_store.create(
            shop_id=doc["shop"]["id"],
            shop_slug=slug,
            items=items,
            customer=customer,
            batch_id=body.get("batch_id"),
            variant=body.get("variant"),
            payment_method=body.get("payment_method", "cod"),
        )
        seller_phone = _seller_phone(doc)
        notify_pipeline.notify_created(seller_phone, order)
        background_tasks.add_task(
            notify_pipeline.watch_ack,
            seller_phone,
            order,
            lambda: order_store.is_seller_seen(order["id"]),
        )
        return order

    @app.get("/orders/{order_id}")
    def get_order(order_id: str) -> dict[str, Any]:
        try:
            return order_store.get(order_id)
        except OrderNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

    @app.get("/orders/{order_id}/status")
    def get_order_status(order_id: str) -> dict[str, Any]:
        """Buyer polling target — the only thing buyer/order.js reads to show
        'quán đã thấy đơn' (ENGINE-SPEC §8)."""
        try:
            order = order_store.get(order_id)
        except OrderNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        return {"order_id": order_id, "status": order["status"], "message": STATUS_MESSAGES.get(order["status"], "")}

    @app.post("/orders/{order_id}/ack")
    def ack_order(order_id: str) -> dict[str, Any]:
        """Seller app: created -> seller_seen. Idempotent (safe to double-tap)."""
        try:
            return order_store.ack(order_id)
        except OrderNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

    @app.post("/orders/{order_id}/transition")
    def transition_order(order_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Generic seller-dashboard transition: confirmed/delivering/done/
        cancelled/no_show_flagged. Illegal moves -> 409 (shared/order_states)."""
        to = body.get("to")
        if not to:
            raise HTTPException(status_code=422, detail="cần 'to'")
        try:
            return order_store.transition(order_id, to)
        except OrderNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except OrderTransitionError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        except OrderError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e

    @app.post("/orders/parse-text")
    def parse_text_endpoint(body: dict[str, Any]) -> dict[str, Any]:
        """ARCH §3.2 'Đặt qua Zalo' reverse path: seller pastes buyer's chat
        text -> draft the seller still reviews before it becomes a real order."""
        slug, text = body.get("slug"), body.get("text")
        if not slug or not text:
            raise HTTPException(status_code=422, detail="cần 'slug' và 'text'")
        doc = _resolve_shop(slug)
        try:
            return parse_order_text(text, doc)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e

    # ------------------------------------------------------------ group orders
    # ARCH §3.3 — office pantry use case.

    @app.post("/group-orders", status_code=201)
    def create_group_order(body: dict[str, Any]) -> dict[str, Any]:
        slug = body.get("slug")
        if not slug:
            raise HTTPException(status_code=422, detail="cần 'slug'")
        doc = _resolve_shop(slug)
        g = group_store.create(doc["shop"]["id"], slug, batch_id=body.get("batch_id"))
        return {**g, "gid": g["id"], "share_url": f"/g/{g['id']}"}

    @app.get("/group-orders/{gid}")
    def get_group_order(gid: str) -> dict[str, Any]:
        try:
            return group_store.get(gid)
        except GroupOrderNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

    @app.post("/group-orders/{gid}/members")
    def add_group_order_member(gid: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            g = group_store.get(gid)
        except GroupOrderNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        shop_doc = storage.get(SHOPS_COLLECTION, g["shop_id"])
        dishes = shop_doc["menu"]["dishes"] if shop_doc else {}
        items = _price_items(dishes, body.get("items") or [])
        try:
            return group_store.add_member_items(gid, body.get("name", ""), items)
        except GroupOrderError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e

    @app.post("/group-orders/{gid}/close")
    def close_group_order(gid: str, body: dict[str, Any], background_tasks: BackgroundTasks) -> dict[str, Any]:
        """Chốt kèo -> 1 real Order (same notify pipeline as a solo COD order)."""
        customer = body.get("customer") or {}
        _require_customer(customer)
        try:
            result = group_store.close(
                gid, order_store, body.get("closer_name", ""), customer, variant=body.get("variant")
            )
        except GroupOrderNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except GroupOrderError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e

        shop_doc = storage.get(SHOPS_COLLECTION, result["group_order"]["shop_id"])
        seller_phone = _seller_phone(shop_doc) if shop_doc else "unknown"
        order = result["order"]
        notify_pipeline.notify_created(seller_phone, order)
        background_tasks.add_task(
            notify_pipeline.watch_ack, seller_phone, order, lambda: order_store.is_seller_seen(order["id"])
        )
        return result

    # --------------------------------------------------- seller: order list
    # Đơn tab of the seller PWA polls this (no push channel needed in dev —
    # NotifyPipeline handles the FCM/SMS side separately).

    @app.get("/api/shops/{slug}/orders")
    def list_shop_orders(slug: str, limit: int = 50) -> dict[str, Any]:
        _resolve_shop(slug)
        orders = order_store.list_by_shop(slug)
        return {"slug": slug, "orders": list(reversed(orders))[: max(1, limit)]}

    # ------------------------------------------- flyer batches (QR analytics)
    # ARCH §2: mỗi batch in 1 mã QR riêng -> biết tờ dán chỗ nào ra bao nhiêu
    # đơn. batch_id đi vào ?b= trên QR, orders đã lưu batch_id sẵn.

    @app.post("/api/shops/{slug}/batches", status_code=201)
    def create_batch(slug: str, body: dict[str, Any]) -> dict[str, Any]:
        doc = _resolve_shop(slug)
        fmt = body.get("format", "")
        try:
            batch = batch_store.create_batch(
                doc["shop"]["id"], slug, fmt, body.get("location_tag", "")
            )
        except BatchError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        return {**batch, "qr_url": qr_url(slug, batch["id"])}

    @app.get("/api/shops/{slug}/batches")
    def list_batches(slug: str) -> dict[str, Any]:
        _resolve_shop(slug)
        batches = [
            {**b, "qr_url": qr_url(slug, b["id"])} for b in batch_store.list_by_shop(slug)
        ]
        return {"slug": slug, "batches": batches}

    @app.delete("/api/shops/{slug}/batches/{batch_id}", status_code=204)
    def delete_batch(slug: str, batch_id: str) -> None:
        _resolve_shop(slug)
        try:
            batch = batch_store.get(batch_id)
        except BatchNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        if batch["shop_slug"] != slug:
            raise HTTPException(status_code=404, detail=f"batch {batch_id!r} không thuộc tiệm này")
        batch_store.delete(batch_id)

    @app.get("/api/shops/{slug}/batch-analytics")
    def batch_analytics(slug: str, since: str | None = None) -> dict[str, Any]:
        """Đơn-theo-batch (growth loop ARCH §3.4). `since` = ISO timestamp."""
        _resolve_shop(slug)
        try:
            per_batch = orders_per_batch(storage, slug, since=since)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=f"'since' không hợp lệ: {e}") from e
        batches = {b["id"]: b for b in batch_store.list_by_shop(slug)}
        for batch_id, entry in per_batch.items():
            meta = batches.get(batch_id)
            entry["location_tag"] = meta["location_tag"] if meta else None
            entry["format"] = meta["format"] if meta else None
        return {"slug": slug, "since": since, "per_batch": per_batch}

    # -------------------------------------------------- imagen hero + flyers
    # ENGINE-SPEC §6. Mock mode without GEMINI_API_KEY — whole path offline.

    @app.post("/api/shops/{slug}/hero")
    def generate_hero(slug: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """Sinh hero background 1 format (+ palette 4 seed). Nếu shop chưa có
        theme, palette imagen trở thành `shop.theme.seed_colors` (SPEC §6:
        'theme tiệm từ 4 màu seed') — bước này phải chạy TRƯỚC compose đầu tiên."""
        body = body or {}
        doc = _resolve_shop(slug)
        fmt = body.get("format", "a5")
        try:
            result = imagen.generate_hero(
                doc, fmt, media_dir=media_dir, force=bool(body.get("force"))
            )
        except imagen.ImagenError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        if not doc["shop"].get("theme"):
            doc["shop"]["theme"] = {"seed_colors": result["palette"]}
            storage.put(SHOPS_COLLECTION, doc["shop"]["id"], doc)
        return {
            "slug": slug, "format": fmt, "hero_url": result["url"],
            "palette": result["palette"], "cached": result["cached"], "mode": result["mode"],
        }

    @app.post("/api/shops/{slug}/flyers")
    def generate_flyers(slug: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """Sinh bộ tờ rơi: tạo batch mới cho mỗi format (hoặc dùng
        `batch_ids` truyền sẵn) -> hero (imagen) -> PDF print-ready.

        Body: {"formats": ["a5","a4"], "location_tag": "..."} hoặc
              {"batch_ids": {"a5": "<batch_id>"}}.
        PDF tải qua static mount: /media/<slug>/flyer_<format>.pdf.
        """
        body = body or {}
        doc = _resolve_shop(slug)

        batch_ids: dict[str, str] = dict(body.get("batch_ids") or {})
        for fmt in batch_ids:
            try:
                batch = batch_store.get(batch_ids[fmt])
            except BatchNotFoundError as e:
                raise HTTPException(status_code=404, detail=str(e)) from e
            if batch["shop_slug"] != slug or batch["format"] != fmt:
                raise HTTPException(422, detail=f"batch {batch['id']!r} không khớp tiệm/format")
        formats = body.get("formats") or ([] if batch_ids else ["a5", "a4", "sticker"])
        for fmt in formats:
            if fmt in batch_ids:
                continue
            try:
                batch = batch_store.create_batch(
                    doc["shop"]["id"], slug, fmt, body.get("location_tag") or "cua-quan"
                )
            except BatchError as e:
                raise HTTPException(status_code=422, detail=str(e)) from e
            batch_ids[fmt] = batch["id"]

        try:
            paths = pdf_export.export_flyers(doc, batch_ids, media_dir=media_dir)
        except (pdf_export.PDFExportError, imagen.ImagenError) as e:
            raise HTTPException(status_code=422, detail=str(e)) from e

        # First flyer run also seeds the shop theme from the imagen palette.
        if not doc["shop"].get("theme"):
            first_fmt = next(iter(batch_ids))
            hero = imagen.generate_hero(doc, first_fmt, media_dir=media_dir)
            doc["shop"]["theme"] = {"seed_colors": hero["palette"]}
            storage.put(SHOPS_COLLECTION, doc["shop"]["id"], doc)

        return {
            "slug": slug,
            "flyers": {
                fmt: {
                    "batch_id": batch_ids[fmt],
                    "pdf_url": f"/media/{slug}/{paths[fmt].name}",
                    "qr_url": qr_url(slug, batch_ids[fmt]),
                }
                for fmt in batch_ids
            },
            "formats": sorted(batch_ids),
        }

    @app.get("/api/flyer-formats")
    def flyer_formats() -> dict[str, Any]:
        return {"formats": list(FLYER_FORMATS)}

    # ------------------------------------------------------- buyer/group pages
    # Server-rendered bootstrap: read the committed static HTML, inject a
    # tiny <script> with slug/gid (+ known variants) before it, return AS-IS
    # otherwise — buyer/index.html and buyer/group.html do 100% of the work
    # client-side (ENGINE-SPEC §9, zero LLM, zero templating engine needed).

    def _bootstrapped_html(path: Path, global_name: str, payload: dict[str, Any]) -> HTMLResponse:
        html = path.read_text(encoding="utf-8")
        script = f"<script>window.{global_name} = {json.dumps(payload, ensure_ascii=False)};</script>"
        html = html.replace("<head>", "<head>\n  " + script, 1)
        return HTMLResponse(html)

    @app.get("/t/{slug}")
    def buyer_page(slug: str) -> HTMLResponse:
        _resolve_shop(slug)  # 404 fast if the QR points at an unknown/deleted shop
        return _bootstrapped_html(
            REPO_ROOT / "buyer" / "index.html",
            "__TIEMQUEN__",
            {"slug": slug, "variants": sorted(VARIANTS)},
        )

    @app.get("/g/{gid}")
    def group_order_page(gid: str) -> HTMLResponse:
        try:
            group_store.get(gid)
        except GroupOrderNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        return _bootstrapped_html(REPO_ROOT / "buyer" / "group.html", "__TIEMQUEN_GROUP__", {"gid": gid})

    # ----------------------------------------------------------- static mounts
    # buyer/ + seller/ are committed static sites; data/media holds rehosted
    # images (gitignored) — create so the mount never 500s on a fresh clone.

    media_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/buyer", StaticFiles(directory=REPO_ROOT / "buyer", html=True), name="buyer")
    app.mount("/seller", StaticFiles(directory=REPO_ROOT / "seller", html=True), name="seller")
    app.mount("/media", StaticFiles(directory=media_dir), name="media")

    return app


app = create_app()
