"""HTTP layer: batches CRUD, batch analytics, hero/flyer generation, seller
order list, seller PWA static mount."""

import pytest
from fastapi.testclient import TestClient

from agents.tiemquen_agent.server import create_app
from infra.storage import LocalJSONStorage
from shared.menu_format import load_demo_fixture

SLUG = "com-tam-co-ba"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)  # imagen mock mode
    monkeypatch.setenv("ACK_TIMEOUT_SECONDS", "0.1")


@pytest.fixture()
def client(tmp_path):
    app = create_app(
        storage=LocalJSONStorage(tmp_path / "db"),
        composed_dir=tmp_path / "composed",
        media_dir=tmp_path / "media",
    )
    with TestClient(app) as c:
        c.post("/api/shops", json=load_demo_fixture())
        yield c


# ---------------------------------------------------------------- batches CRUD


def test_batch_crud_roundtrip(client):
    r = client.post(f"/api/shops/{SLUG}/batches",
                    json={"format": "a5", "location_tag": "office plaza 1"})
    assert r.status_code == 201, r.text
    batch = r.json()
    assert batch["id"].startswith("office-plaza-1-a5-")
    assert batch["qr_url"] == f"/t/{SLUG}?b={batch['id']}"

    r = client.get(f"/api/shops/{SLUG}/batches")
    assert r.status_code == 200
    assert [b["id"] for b in r.json()["batches"]] == [batch["id"]]

    r = client.delete(f"/api/shops/{SLUG}/batches/{batch['id']}")
    assert r.status_code == 204
    assert client.get(f"/api/shops/{SLUG}/batches").json()["batches"] == []


def test_batch_create_validation(client):
    r = client.post(f"/api/shops/{SLUG}/batches", json={"format": "a7", "location_tag": "x"})
    assert r.status_code == 422
    r = client.post(f"/api/shops/{SLUG}/batches", json={"format": "a5", "location_tag": ""})
    assert r.status_code == 422
    r = client.post("/api/shops/khong-ton-tai/batches",
                    json={"format": "a5", "location_tag": "x"})
    assert r.status_code == 404


def test_delete_batch_of_other_shop_404s(client):
    demo2 = load_demo_fixture()
    demo2["shop"]["id"] = "shop_khac"
    demo2["shop"]["slug"] = "quan-khac"
    demo2["shop"]["name"] = "Quán Khác"
    assert client.post("/api/shops", json=demo2).status_code == 201
    batch = client.post("/api/shops/quan-khac/batches",
                        json={"format": "a5", "location_tag": "z"}).json()
    r = client.delete(f"/api/shops/{SLUG}/batches/{batch['id']}")
    assert r.status_code == 404


# ------------------------------------------------------------------ analytics


def test_batch_analytics_counts_orders(client):
    batch = client.post(f"/api/shops/{SLUG}/batches",
                        json={"format": "a5", "location_tag": "office plaza 1"}).json()
    body = {
        "slug": SLUG,
        "batch_id": batch["id"],
        "items": [{"dish_id": "dish_suon_nuong", "qty": 1}],
        "customer": {"name": "An", "phone": "0909000111", "address": "12 Lê Lợi"},
    }
    assert client.post("/orders", json=body).status_code == 201
    assert client.post("/orders", json=body).status_code == 201
    assert client.post("/orders", json={**body, "batch_id": None}).status_code == 201

    r = client.get(f"/api/shops/{SLUG}/batch-analytics")
    assert r.status_code == 200
    per_batch = r.json()["per_batch"]
    assert per_batch[batch["id"]]["orders"] == 2
    assert per_batch[batch["id"]]["location_tag"] == "office plaza 1"
    assert per_batch[batch["id"]]["format"] == "a5"
    assert per_batch["direct"]["orders"] == 1
    assert per_batch["direct"]["location_tag"] is None

    r = client.get(f"/api/shops/{SLUG}/batch-analytics", params={"since": "2099-01-01T00:00:00+00:00"})
    assert r.json()["per_batch"] == {}

    r = client.get(f"/api/shops/{SLUG}/batch-analytics", params={"since": "khong-phai-ngay"})
    assert r.status_code == 422


# --------------------------------------------------------------- hero + flyers


def test_hero_generates_and_seeds_theme_when_missing(client):
    demo = load_demo_fixture()
    del demo["shop"]["theme"]
    demo["shop"]["id"] = "shop_notheme"
    demo["shop"]["slug"] = "quan-chua-theme"
    demo["shop"]["name"] = "Quán Chưa Theme"
    assert client.post("/api/shops", json=demo).status_code == 201

    r = client.post("/api/shops/quan-chua-theme/hero", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "mock" and len(body["palette"]) == 4

    shop = client.get("/api/shops/quan-chua-theme").json()["shop"]
    assert shop["theme"]["seed_colors"] == body["palette"]

    # Hero PNG is served through the /media static mount.
    r = client.get(body["hero_url"])
    assert r.status_code == 200
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"

    # Second call = cache hit.
    assert client.post("/api/shops/quan-chua-theme/hero", json={}).json()["cached"] is True


def test_flyers_endpoint_generates_batches_and_downloadable_pdfs(client):
    r = client.post(f"/api/shops/{SLUG}/flyers",
                    json={"formats": ["a5", "a4"], "location_tag": "office plaza 1"})
    assert r.status_code == 200, r.text
    flyers = r.json()["flyers"]
    assert set(flyers) == {"a5", "a4"}
    for fmt, entry in flyers.items():
        assert entry["batch_id"].startswith("office-plaza-1-" + fmt)
        assert entry["qr_url"] == f"/t/{SLUG}?b={entry['batch_id']}"
        dl = client.get(entry["pdf_url"])
        assert dl.status_code == 200
        assert dl.content[:5] == b"%PDF-"
        assert len(dl.content) > 10_000

    # Batches were registered for analytics.
    ids = {b["id"] for b in client.get(f"/api/shops/{SLUG}/batches").json()["batches"]}
    assert {e["batch_id"] for e in flyers.values()} <= ids


def test_flyers_endpoint_accepts_existing_batch_ids(client):
    batch = client.post(f"/api/shops/{SLUG}/batches",
                        json={"format": "sticker", "location_tag": "tủ lạnh"}).json()
    r = client.post(f"/api/shops/{SLUG}/flyers", json={"batch_ids": {"sticker": batch["id"]}})
    assert r.status_code == 200, r.text
    assert r.json()["flyers"]["sticker"]["batch_id"] == batch["id"]

    # Mismatched format for the batch -> 422.
    r = client.post(f"/api/shops/{SLUG}/flyers", json={"batch_ids": {"a4": batch["id"]}})
    assert r.status_code == 422


def test_flyer_formats_listing(client):
    assert client.get("/api/flyer-formats").json()["formats"] == ["a5", "a4", "sticker"]


# ------------------------------------------------------- seller order list/PWA


def test_seller_order_list_newest_first(client):
    body = {
        "slug": SLUG,
        "items": [{"dish_id": "dish_tra_da", "qty": 1}],
        "customer": {"name": "An", "phone": "0909000111", "address": "12 Lê Lợi"},
    }
    first = client.post("/orders", json=body).json()
    second = client.post("/orders", json=body).json()
    r = client.get(f"/api/shops/{SLUG}/orders")
    assert r.status_code == 200
    ids = [o["id"] for o in r.json()["orders"]]
    assert ids.index(second["id"]) < ids.index(first["id"])

    assert client.get("/api/shops/khong-co/orders").status_code == 404


def test_seller_pwa_shell_served(client):
    r = client.get("/seller/")
    assert r.status_code == 200
    # React bundle (web/dist) or the vanilla fallback shell
    assert "manifest.json" in r.text
    assert ("/webapp/" in r.text) or ("app.js" in r.text)
    for path in ("/seller/app.js", "/seller/manifest.json", "/seller/sw.js",
                 "/seller/styles.css", "/seller/icon.svg"):
        assert client.get(path).status_code == 200, path
    manifest = client.get("/seller/manifest.json").json()
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/seller/"
