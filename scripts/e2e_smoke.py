#!/usr/bin/env python3
"""End-to-end smoke test — MUST run without GEMINI_API_KEY (mock mode), exit 0.

Later phases APPEND numbered steps here (import agent, compose, orders, flyer...).
Keep the pattern: one `step(n, title)` banner per section, assert hard, print PASS.

Run:  ./.venv/bin/python scripts/e2e_smoke.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

# Run from anywhere: put repo root on sys.path.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import httpx  # noqa: E402

from agents.tiemquen_agent import a2ui  # noqa: E402
from agents.tiemquen_agent import imagen as imagen_service  # noqa: E402
from agents.tiemquen_agent.agents import import_agent  # noqa: E402
from infra import vietqr  # noqa: E402
from agents.tiemquen_agent.server import create_app  # noqa: E402
from compose.cache import ComposeCache  # noqa: E402
from compose.composer import VARIANTS, compose_all_variants, is_mock_mode  # noqa: E402
from compose.theme import derive_theme, validate_palette  # noqa: E402
from infra.publish import SlugRegistry, slugify  # noqa: E402
from infra.storage import LocalJSONStorage  # noqa: E402
from shared.menu_format import load_demo_fixture, validate_menu  # noqa: E402


def step(n: int, title: str) -> None:
    print(f"\n=== STEP {n}: {title} ===")


def ok(msg: str) -> None:
    print(f"  PASS  {msg}")


def main() -> int:
    # Isolated scratch storage — smoke never pollutes the real data/ dir.
    scratch = Path(tempfile.mkdtemp(prefix="tiemquen_smoke_"))
    storage = LocalJSONStorage(scratch)
    fixture = load_demo_fixture()

    # ---------------------------------------------------------------------
    step(1, "Fixture validates against chuẩn menu schema")
    # ---------------------------------------------------------------------
    validate_menu(fixture)
    n_dishes = len(fixture["menu"]["dishes"])
    assert n_dishes >= 10, f"expected >=10 dishes, got {n_dishes}"
    ok(f"data/fixtures/demo_shop.json valid ({n_dishes} dishes, "
       f"{len(fixture['menu']['sections'])} sections)")

    # ---------------------------------------------------------------------
    step(2, "Shop store roundtrip via storage adapter")
    # ---------------------------------------------------------------------
    shop_id = fixture["shop"]["id"]
    storage.put("shops", shop_id, fixture)
    loaded = storage.get("shops", shop_id)
    assert loaded == fixture, "stored doc differs from fixture"
    assert shop_id in storage.list("shops")
    ok(f"put/get/list roundtrip for shop {shop_id!r}")

    # ---------------------------------------------------------------------
    step(3, "Slug registry: slugify VN + register + resolve")
    # ---------------------------------------------------------------------
    assert slugify("Cơm Tấm Cô Ba") == "com-tam-co-ba"
    registry = SlugRegistry(storage)
    slug = registry.register(shop_id, fixture["shop"]["name"])
    assert registry.resolve(slug) == shop_id
    ok(f"slug {slug!r} -> {shop_id!r}")

    # ---------------------------------------------------------------------
    step(4, "App boots (httpx ASGI): /health + create shop + get by slug")
    # ---------------------------------------------------------------------
    async def run_http() -> None:
        app = create_app(storage=LocalJSONStorage(scratch / "api"))
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://smoke") as client:
            r = await client.get("/health")
            assert r.status_code == 200 and r.json()["status"] == "ok", r.text
            ok("GET /health -> ok")

            r = await client.post("/api/shops", json=fixture)
            assert r.status_code == 201, r.text
            created_slug = r.json()["shop"]["slug"]
            ok(f"POST /api/shops -> 201 (slug={created_slug!r})")

            r = await client.get(f"/api/shops/{created_slug}")
            assert r.status_code == 200, r.text
            assert r.json()["shop"]["name"] == fixture["shop"]["name"]
            assert len(r.json()["menu"]["dishes"]) == n_dishes
            ok(f"GET /api/shops/{created_slug} -> full menu doc")

    asyncio.run(run_http())

    # ---------------------------------------------------------------------
    step(5, "Compose engine (mock mode): fixture -> 4 A2UI variants, all valid")
    # ---------------------------------------------------------------------
    os.environ.pop("GEMINI_API_KEY", None)  # smoke is ALWAYS mock mode, no network
    assert is_mock_mode()
    theme = derive_theme(fixture["shop"]["theme"]["seed_colors"])
    assert validate_palette(theme) == [], f"palette fails WCAG: {validate_palette(theme)}"
    ok(f"theme derived from 4 seeds, all text pairs >= 4.5 ({len(theme)} colors)")

    catalog = a2ui.load_catalog()
    variants = compose_all_variants(fixture, theme)
    assert set(variants) == set(VARIANTS) and len(VARIANTS) == 4
    for variant, messages in variants.items():
        clean, warnings = a2ui.validate_and_repair(messages, catalog=catalog)
        assert warnings == [] and clean == messages, f"{variant}: {warnings}"
        assert "createSurface" in messages[0]
        used = {
            c["component"]
            for m in messages
            if "updateComponents" in m
            for c in m["updateComponents"]["components"]
        }
        assert used <= a2ui.catalog_component_names(catalog), f"{variant}: {used}"
    ok(f"4 variants composed + validator clean: {sorted(variants)}")

    # ---------------------------------------------------------------------
    step(6, "Compose cache: variant files land under composed/<slug>/")
    # ---------------------------------------------------------------------
    cache = ComposeCache(scratch / "composed")
    slug_for_cache = fixture["shop"]["slug"]
    cache.write_variants(slug_for_cache, variants)
    for variant in VARIANTS:
        path = cache.variant_path(slug_for_cache, variant)
        assert path.is_file(), f"missing cache file {path}"
        assert cache.read_variant(slug_for_cache, variant) == variants[variant]
    ok(f"cache files exist: composed/{slug_for_cache}/<variant>.json x{len(VARIANTS)}")

    # ---------------------------------------------------------------------
    step(7, "Patch flow: sold_out = updateDataModel PATCH, no recompose")
    # ---------------------------------------------------------------------
    patch_path, patch_value = "/soldout/dish_suon_nuong", True
    sizes_before = {v: len(variants[v]) for v in VARIANTS}
    patched = cache.patch_data(slug_for_cache, patch_path, patch_value)
    assert sorted(patched) == sorted(VARIANTS)
    for variant in VARIANTS:
        msgs = cache.read_variant(slug_for_cache, variant)
        assert len(msgs) == sizes_before[variant] + 1, "patch must APPEND, not recompose"
        tail = msgs[-1]["updateDataModel"]
        assert tail["path"] == patch_path and tail["value"] is patch_value
        assert sum(1 for m in msgs if "updateComponents" in m) == 1, "structure untouched"
    ok(f"patch {patch_path}={patch_value} appended to all {len(patched)} cached variants")

    # ---------------------------------------------------------------------
    step(8, "Import agent (mock mode): OCR fixture -> chuẩn menu validates")
    # ---------------------------------------------------------------------
    assert import_agent.is_mock_mode()  # smoke never touches GEMINI_API_KEY
    import_envelope = import_agent.import_menu("fake_screenshot_path.png")
    validate_menu(import_envelope["menu"])
    imported_shop_name = import_envelope["menu"]["shop"]["name"]
    assert imported_shop_name == "Cơm Tấm Cô Ba"
    assert 0 <= import_envelope["confidence"] <= 100
    assert any("Nước sâm" in w for w in import_envelope["warnings"]), (
        "fixture's deliberately-bad OCR price must surface as a price-sanity warning"
    )
    ok(
        f"import_menu(screenshot) -> valid chuẩn menu "
        f"({len(import_envelope['menu']['menu']['dishes'])} dishes, "
        f"confidence={import_envelope['confidence']}, "
        f"{len(import_envelope['warnings'])} warning(s))"
    )

    # ---------------------------------------------------------------------
    step(9, "Full flow via HTTP: import -> create shop -> PATCH price -10% -> recompose")
    # ---------------------------------------------------------------------
    async def run_import_flow() -> None:
        flow_storage = LocalJSONStorage(scratch / "import_flow")
        flow_cache_dir = scratch / "import_flow_composed"
        app = create_app(storage=flow_storage, composed_dir=flow_cache_dir)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://smoke") as client:
            r = await client.post("/api/import", json={"fixture": "grab_screenshot_toolcalls"})
            assert r.status_code == 200, r.text
            imported_menu = r.json()["menu"]
            ok("POST /api/import {fixture:...} -> 200, envelope has valid menu")

            # Theme seed colors come from the Imagen/flyer agent (ENGINE-SPEC
            # §6) — out of scope for the import pipeline. Fake them here so
            # this smoke can exercise /compose without that later phase.
            imported_menu["shop"]["theme"] = {
                "seed_colors": ["#B7410E", "#F5E6C8", "#2F4A34", "#FFB84C"]
            }

            r = await client.post("/api/shops", json=imported_menu)
            assert r.status_code == 201, r.text
            slug = r.json()["shop"]["slug"]
            ok(f"POST /api/shops (imported doc) -> 201 (slug={slug!r})")

            r = await client.get(f"/api/shops/{slug}/menu")
            assert r.status_code == 200, r.text
            menu_before = r.json()["menu"]
            dish_id = menu_before["sections"][0]["items"][0]
            old_price = menu_before["dishes"][dish_id]["price"]
            new_price = round(old_price * 0.9)  # seller drops price -10% direct-order discount
            ok(f"GET /api/shops/{slug}/menu -> dish {dish_id!r} @ {old_price}đ")

            r = await client.post(f"/api/shops/{slug}/compose")
            assert r.status_code == 200, r.text
            cache = ComposeCache(flow_cache_dir)
            before_bytes = {
                v: cache.variant_path(slug, v).stat().st_mtime for v in VARIANTS
            }
            ok(f"POST /api/shops/{slug}/compose -> cache populated for {len(VARIANTS)} variants")

            r = await client.patch(
                f"/api/shops/{slug}/menu",
                json={"edits": [{"op": "set_price", "dish_id": dish_id, "price": new_price}]},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["menu"]["dishes"][dish_id]["price"] == new_price
            assert sorted(body["recomposed_variants"]) == sorted(VARIANTS)
            ok(f"PATCH /api/shops/{slug}/menu set_price -10% -> {new_price}đ, recompose triggered")

            for variant in VARIANTS:
                messages = cache.read_variant(slug, variant)
                assert messages is not None, f"composed cache missing for {variant}"
                prices_msg = next(
                    m["updateDataModel"]
                    for m in messages
                    if m.get("updateDataModel", {}).get("path") == "/prices"
                )
                assert prices_msg["value"][dish_id] == new_price, (
                    f"{variant}: composed cache price stale after recompose"
                )
                # Full recompose overwrites the file (unlike /patch's append-only
                # updateDataModel trick) — mtime must have moved forward.
                assert cache.variant_path(slug, variant).stat().st_mtime >= before_bytes[variant]
            ok(f"composed cache for all {len(VARIANTS)} variants reflects the new price")

    asyncio.run(run_import_flow())

    # ---------------------------------------------------------------------
    step(10, "Order flow: COD order -> notify fired -> ack -> seller_seen -> confirm -> done")
    # ---------------------------------------------------------------------
    # ASGITransport awaits BackgroundTasks as part of the request (same as
    # TestClient) — use a short ack-timeout so this step can't block on the
    # real 120s default (ENGINE-SPEC §8 tests use 0.1-ish, this smoke too).
    os.environ["ACK_TIMEOUT_SECONDS"] = "0.05"

    async def run_order_flow() -> None:
        order_storage = LocalJSONStorage(scratch / "order_flow")
        app = create_app(
            storage=order_storage,
            composed_dir=scratch / "order_flow_composed",
            media_dir=scratch / "order_flow_media",
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://smoke") as client:
            r = await client.post("/api/shops", json=fixture)
            assert r.status_code == 201, r.text
            slug = r.json()["shop"]["slug"]

            r = await client.get(f"/t/{slug}")
            assert r.status_code == 200 and "renderer.js" in r.text
            ok(f"GET /t/{slug} -> buyer page HTML references renderer.js")

            order_body = {
                "slug": slug,
                "batch_id": "office-plaza1",
                "items": [
                    {"dish_id": "dish_suon_nuong", "qty": 2},
                    {"dish_id": "dish_tra_da", "qty": 1},
                ],
                "customer": {"name": "An", "phone": "0909000111", "address": "12 Lê Lợi"},
            }
            r = await client.post("/orders", json=order_body)
            assert r.status_code == 201, r.text
            order = r.json()
            assert order["status"] == "created"
            assert order["total"] == 35000 * 2 + 3000
            ok(
                f"POST /orders -> created (total={order['total']:,}đ), notify chain fired "
                "([fcm-stub]/[console] lines above)"
            )

            r = await client.post(f"/orders/{order['id']}/ack")
            assert r.status_code == 200 and r.json()["status"] == "seller_seen"
            r = await client.get(f"/orders/{order['id']}/status")
            assert r.json()["status"] == "seller_seen" and "thấy đơn" in r.json()["message"]
            ok("POST /orders/{id}/ack -> seller_seen; buyer status shows 'quán đã thấy đơn'")

            for to in ("confirmed", "delivering", "done"):
                r = await client.post(f"/orders/{order['id']}/transition", json={"to": to})
                assert r.status_code == 200 and r.json()["status"] == to, r.text
            ok("confirmed -> delivering -> done via /orders/{id}/transition")

            r = await client.post(f"/orders/{order['id']}/transition", json={"to": "cancelled"})
            assert r.status_code == 409  # done is terminal — state machine rejects it
            ok("illegal transition out of a terminal state -> 409 (shared/order_states)")

            # -----------------------------------------------------------------
            step(11, "Group order: 3 members, uneven split, 1 real order, 1 ship")
            # -----------------------------------------------------------------
            r = await client.post("/group-orders", json={"slug": slug, "batch_id": "office-plaza1"})
            assert r.status_code == 201, r.text
            gid = r.json()["gid"]

            r = await client.get(f"/g/{gid}")
            assert r.status_code == 200 and gid in r.text
            ok(f"POST /group-orders -> {gid!r}; GET /g/{gid} serves the bootstrap HTML")

            members = {
                "An": [{"dish_id": "dish_suon_nuong", "qty": 1}],  # 35.000
                "Binh": [
                    {"dish_id": "dish_suon_bi_cha", "qty": 1},
                    {"dish_id": "dish_tra_da", "qty": 2},
                ],  # 45.000 + 6.000 = 51.000
                "Chi": [{"dish_id": "dish_ga_nuong", "qty": 3}],  # 38.000 x 3 = 114.000
            }
            for name, items in members.items():
                r = await client.post(f"/group-orders/{gid}/members", json={"name": name, "items": items})
                assert r.status_code == 200, r.text

            r = await client.post(
                f"/group-orders/{gid}/close",
                json={
                    "closer_name": "An",
                    "customer": {"name": "An", "phone": "0909000111", "address": "12 Lê Lợi"},
                },
            )
            assert r.status_code == 200, r.text
            result = r.json()
            expected_total = 35000 + 51000 + 114000  # NOT evenly divisible by 3 members
            assert result["order"]["total"] == expected_total
            assert sum(v["amount"] for v in result["split"].values()) == expected_total
            assert result["split"]["An"]["is_payer"] is True and "vietqr_placeholder" not in result["split"]["An"]
            assert result["split"]["Binh"]["amount"] == 51000
            assert result["split"]["Chi"]["amount"] == 114000
            ok(
                f"3-member group order closed -> 1 order total={expected_total:,}đ, "
                "per-member split sums exactly (no equal-division remainder)"
            )

            # -----------------------------------------------------------------
            step(12, "Flyer path: A5+A4 batches -> mock imagen hero -> print PDFs")
            # -----------------------------------------------------------------
            assert imagen_service.is_mock_mode()  # never touches GEMINI_API_KEY
            batch_ids: dict[str, str] = {}
            for fmt in ("a5", "a4"):
                r = await client.post(
                    f"/api/shops/{slug}/batches",
                    json={"format": fmt, "location_tag": "office plaza 1"},
                )
                assert r.status_code == 201, r.text
                batch = r.json()
                assert batch["qr_url"] == f"/t/{slug}?b={batch['id']}"
                batch_ids[fmt] = batch["id"]
            ok(f"2 batches created (A5+A4), QR URLs carry ?b=<batch_id>: {sorted(batch_ids.values())}")

            r = await client.post(f"/api/shops/{slug}/flyers", json={"batch_ids": batch_ids})
            assert r.status_code == 200, r.text
            flyers = r.json()["flyers"]
            assert set(flyers) == {"a5", "a4"}
            for fmt, entry in flyers.items():
                hero_png = scratch / "order_flow_media" / slug / f"hero_{fmt}.png"
                assert hero_png.is_file(), f"mock imagen PNG missing: {hero_png}"
                assert hero_png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
                pdf = scratch / "order_flow_media" / slug / f"flyer_{fmt}.pdf"
                assert pdf.is_file(), f"flyer PDF missing: {pdf}"
                size = pdf.stat().st_size
                assert size > 10_000, f"{fmt}: PDF only {size}B — hero/QR not embedded?"
                dl = await client.get(entry["pdf_url"])
                assert dl.status_code == 200 and dl.content[:5] == b"%PDF-"
            ok("mock imagen hero PNGs + print-ready flyer PDFs (>10KB) downloadable via /media")

            r = await client.get(f"/api/shops/{slug}/batch-analytics")
            assert r.status_code == 200, r.text
            per_batch = r.json()["per_batch"]
            # Both the solo order (step 10) and the group order (step 11) carried
            # batch 'office-plaza1' -> flyer analytics sees 2 orders on it.
            assert per_batch["office-plaza1"]["orders"] == 2
            assert per_batch["office-plaza1"]["revenue"] == 73000 + expected_total
            ok("batch analytics: 2 orders counted on batch 'office-plaza1' (solo + group)")

            # -----------------------------------------------------------------
            step(13, "VietQR: group-split member payload validates CRC (EMVCo TLV)")
            # -----------------------------------------------------------------
            vietqr_conf = fixture["shop"]["payment"]["vietqr"]  # payer's refund account (demo)
            payloads = vietqr.group_split_payloads(result["split"], vietqr_conf)
            assert set(payloads) == {"Binh", "Chi"}  # everyone except payer An
            for name, payload in payloads.items():
                assert vietqr.validate_crc(payload), f"{name}: CRC mismatch"
                top = vietqr.parse_tlv(payload)
                assert top["53"] == "704" and top["58"] == "VN" and top["01"] == "12"
                merchant = vietqr.parse_tlv(top["38"])
                assert merchant["00"] == "A000000727" and merchant["02"] == "QRIBFTTA"
            assert vietqr.parse_tlv(payloads["Binh"])["54"] == "51000"
            assert vietqr.parse_tlv(payloads["Chi"])["54"] == "114000"
            assert vietqr.crc16_ccitt(b"123456789") == 0x29B1  # reference vector
            ok("VietQR payloads for Binh (51.000đ) + Chi (114.000đ): CRC16-CCITT valid, NAPAS fields OK")

    asyncio.run(run_order_flow())

    print("\nSMOKE OK — all steps passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
