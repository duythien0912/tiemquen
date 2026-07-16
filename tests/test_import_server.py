"""Server endpoints: POST /api/import, GET/PATCH /api/shops/{slug}/menu."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import agents.tiemquen_agent.server as server_module
from agents.tiemquen_agent.server import create_app
from infra.storage import LocalJSONStorage
from shared.menu_format import load_demo_fixture

SLUG = "com-tam-co-ba"


@pytest.fixture(autouse=True)
def _force_mock(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


@pytest.fixture()
def client(tmp_path):
    storage = LocalJSONStorage(tmp_path)
    app = create_app(storage=storage, composed_dir=tmp_path / "composed")
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def env(tmp_path):
    storage = LocalJSONStorage(tmp_path)
    app = create_app(storage=storage, composed_dir=tmp_path / "composed")
    with TestClient(app) as c:
        c.post("/api/shops", json=load_demo_fixture())
        yield c, tmp_path


# --------------------------------------------------------------------- /import


def test_import_via_fixture_ref_returns_valid_envelope(client):
    r = client.post("/api/import", json={"fixture": "grab_screenshot_toolcalls"})
    assert r.status_code == 200
    body = r.json()
    assert body["menu"]["shop"]["name"] == "Cơm Tấm Cô Ba"
    assert body["confidence"] == 82
    assert "warnings" in body


def test_import_via_fixture_unknown_name_404(client):
    r = client.post("/api/import", json={"fixture": "khong-ton-tai"})
    assert r.status_code == 404


def test_import_via_multipart_screenshot_mock_mode(client):
    r = client.post(
        "/api/import",
        files={"screenshot": ("menu.png", b"\x89PNG-fake-bytes", "image/png")},
    )
    assert r.status_code == 200
    assert r.json()["menu"]["source"]["type"] == "ocr_screenshot"


def test_import_via_multipart_missing_field_422(client):
    r = client.post("/api/import", data={"not_screenshot": "x"})
    assert r.status_code == 422


def test_import_via_url_html_parse_fallback_to_ocr(client, monkeypatch):
    import agents.tiemquen_agent.agents.import_agent as import_agent

    def fake_parse(url, **kwargs):
        from agents.tiemquen_agent.agents.html_parse import ImportFallbackToOCR

        raise ImportFallbackToOCR("SPA, không parse được")

    monkeypatch.setattr(import_agent, "parse_shopeefood", fake_parse)
    r = client.post("/api/import", json={"url": "https://shopeefood.vn/shop/x"})
    assert r.status_code == 422
    assert r.json()["detail"]["fallback_to_ocr"] is True


def test_import_via_text(client):
    r = client.post("/api/import", json={"text": "Cơm sườn - 35.000đ"})
    assert r.status_code == 200
    assert r.json()["menu"]["source"]["type"] == "manual"


def test_import_empty_body_422(client):
    r = client.post("/api/import", json={})
    assert r.status_code == 422


# ---------------------------------------------------------------- /menu review


def test_get_shop_menu(env):
    client, _ = env
    r = client.get(f"/api/shops/{SLUG}/menu")
    assert r.status_code == 200
    body = r.json()
    assert body["slug"] == SLUG
    assert "sections" in body["menu"] and "dishes" in body["menu"]


def test_get_shop_menu_unknown_slug_404(env):
    client, _ = env
    assert client.get("/api/shops/khong-ton-tai/menu").status_code == 404


def test_patch_shop_menu_set_price_triggers_recompose(env, monkeypatch):
    client, _ = env
    calls: list[dict] = []
    original = server_module.compose_all_variants

    def spy(doc, theme=None):
        calls.append({"shop_id": doc["shop"]["id"]})
        return original(doc, theme)

    monkeypatch.setattr(server_module, "compose_all_variants", spy)

    r = client.get(f"/api/shops/{SLUG}/menu")
    dish_id = r.json()["menu"]["sections"][0]["items"][0]
    old_price = r.json()["menu"]["dishes"][dish_id]["price"]
    new_price = int(old_price * 0.9)  # -10%

    r = client.patch(
        f"/api/shops/{SLUG}/menu",
        json={"edits": [{"op": "set_price", "dish_id": dish_id, "price": new_price}]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["menu"]["dishes"][dish_id]["price"] == new_price
    assert len(calls) == 1  # recompose pipeline was actually invoked

    # Persisted + composed cache reflects the new price.
    r2 = client.get(f"/api/shops/{SLUG}/menu")
    assert r2.json()["menu"]["dishes"][dish_id]["price"] == new_price


def test_patch_shop_menu_hide_dish(env):
    client, _ = env
    r = client.get(f"/api/shops/{SLUG}/menu")
    dish_id = r.json()["menu"]["sections"][0]["items"][0]

    r = client.patch(
        f"/api/shops/{SLUG}/menu", json={"edits": [{"op": "hide_dish", "dish_id": dish_id}]}
    )
    assert r.status_code == 200
    assert r.json()["menu"]["dishes"][dish_id]["hidden"] is True


def test_patch_shop_menu_add_direct_only_dish(env):
    client, _ = env
    r = client.get(f"/api/shops/{SLUG}/menu")
    section_id = r.json()["menu"]["sections"][0]["id"]

    r = client.patch(
        f"/api/shops/{SLUG}/menu",
        json={
            "edits": [
                {
                    "op": "add_dish",
                    "section_id": section_id,
                    "name": "Cơm đặc biệt chỉ bán tại tiệm",
                    "price": 60000,
                    "direct_only": True,
                }
            ]
        },
    )
    assert r.status_code == 200
    dishes = r.json()["menu"]["dishes"]
    new_dish = next(d for d in dishes.values() if d["name"] == "Cơm đặc biệt chỉ bán tại tiệm")
    assert new_dish["direct_only"] is True
    assert new_dish["price"] == 60000


def test_patch_shop_menu_retitle_section(env):
    client, _ = env
    r = client.get(f"/api/shops/{SLUG}/menu")
    section_id = r.json()["menu"]["sections"][0]["id"]

    r = client.patch(
        f"/api/shops/{SLUG}/menu",
        json={"edits": [{"op": "retitle_section", "section_id": section_id, "title": "Cơm tấm đặc sản"}]},
    )
    assert r.status_code == 200
    section = next(s for s in r.json()["menu"]["sections"] if s["id"] == section_id)
    assert section["title"] == "Cơm tấm đặc sản"


def test_patch_shop_menu_unknown_dish_422(env):
    client, _ = env
    r = client.patch(
        f"/api/shops/{SLUG}/menu",
        json={"edits": [{"op": "set_price", "dish_id": "khong-ton-tai", "price": 1000}]},
    )
    assert r.status_code == 422


def test_patch_shop_menu_empty_edits_422(env):
    client, _ = env
    r = client.patch(f"/api/shops/{SLUG}/menu", json={"edits": []})
    assert r.status_code == 422


def test_patch_shop_menu_unknown_slug_404(env):
    client, _ = env
    r = client.patch(
        "/api/shops/khong-ton-tai/menu",
        json={"edits": [{"op": "set_price", "dish_id": "x", "price": 1000}]},
    )
    assert r.status_code == 404
