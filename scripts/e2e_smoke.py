#!/usr/bin/env python3
"""End-to-end smoke test — MUST run without GEMINI_API_KEY (mock mode), exit 0.

Later phases APPEND numbered steps here (import agent, compose, orders, flyer...).
Keep the pattern: one `step(n, title)` banner per section, assert hard, print PASS.

Run:  ./.venv/bin/python scripts/e2e_smoke.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

# Run from anywhere: put repo root on sys.path.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import httpx  # noqa: E402

from agents.tiemquen_agent.server import create_app  # noqa: E402
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
    # LATER PHASES: append STEP 5+ here (import agent mock, compose A2UI,
    # order state machine, notify stub, flyer PDF, ...).
    # ---------------------------------------------------------------------

    print("\nSMOKE OK — all steps passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
