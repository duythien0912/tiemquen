import copy

import pytest
from fastapi.testclient import TestClient

from agents.tiemquen_agent.server import create_app
from infra.storage import LocalJSONStorage
from shared.menu_format import load_demo_fixture


@pytest.fixture()
def client(tmp_path):
    app = create_app(storage=LocalJSONStorage(tmp_path))
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_create_shop_from_fixture_and_get_by_slug(client):
    r = client.post("/api/shops", json=load_demo_fixture())
    assert r.status_code == 201
    slug = r.json()["shop"]["slug"]
    assert slug == "com-tam-co-ba"

    r = client.get(f"/api/shops/{slug}")
    assert r.status_code == 200
    doc = r.json()
    assert doc["shop"]["name"] == "Cơm Tấm Cô Ba"
    assert len(doc["menu"]["dishes"]) == 10


def test_create_shop_empty_body_seeds_demo_fixture(client):
    r = client.post("/api/shops")
    assert r.status_code == 201
    assert r.json()["shop"]["id"] == "shop_comtamcoba"


def test_create_duplicate_shop_conflicts(client):
    assert client.post("/api/shops", json=load_demo_fixture()).status_code == 201
    assert client.post("/api/shops", json=load_demo_fixture()).status_code == 409


def test_create_invalid_doc_rejected(client):
    bad = copy.deepcopy(load_demo_fixture())
    del bad["shop"]["name"]
    r = client.post("/api/shops", json=bad)
    assert r.status_code == 422


def test_get_unknown_slug_404(client):
    assert client.get("/api/shops/khong-ton-tai").status_code == 404


def test_list_and_delete_shop(client):
    client.post("/api/shops", json=load_demo_fixture())
    assert client.get("/api/shops").json()["shop_ids"] == ["shop_comtamcoba"]
    assert client.delete("/api/shops/com-tam-co-ba").status_code == 204
    assert client.get("/api/shops/com-tam-co-ba").status_code == 404
    assert client.get("/api/shops").json()["shop_ids"] == []


def test_static_mounts_serve(client):
    assert client.get("/seller/").status_code == 200  # React shell (web/dist)
    assert client.get("/seller/manifest.json").status_code == 200
