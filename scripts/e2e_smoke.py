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
    # LATER PHASES: append STEP 8+ here (import agent mock, order state
    # machine, notify stub, flyer PDF, ...).
    # ---------------------------------------------------------------------

    print("\nSMOKE OK — all steps passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
