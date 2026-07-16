"""Server endpoints: POST .../compose (recompose all variants) + .../patch."""

import pytest
from fastapi.testclient import TestClient

from agents.tiemquen_agent.server import create_app
from compose.composer import VARIANTS
from infra.storage import LocalJSONStorage
from shared.menu_format import load_demo_fixture

SLUG = "com-tam-co-ba"


@pytest.fixture(autouse=True)
def _force_mock(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


@pytest.fixture()
def env(tmp_path):
    storage = LocalJSONStorage(tmp_path)
    app = create_app(storage=storage, composed_dir=tmp_path / "composed")
    with TestClient(app) as client:
        client.post("/api/shops", json=load_demo_fixture())
        yield client, tmp_path


def test_compose_writes_all_variant_files(env):
    client, tmp_path = env
    r = client.post(f"/api/shops/{SLUG}/compose")
    assert r.status_code == 200
    body = r.json()
    assert body["variants"] == sorted(VARIANTS)
    for variant in VARIANTS:
        assert (tmp_path / "composed" / SLUG / f"{variant}.json").is_file()
        rv = client.get(f"/api/shops/{SLUG}/composed/{variant}")
        assert rv.status_code == 200
        assert "createSurface" in rv.json()[0]


def test_compose_unknown_slug_404(env):
    client, _ = env
    assert client.post("/api/shops/khong-ton-tai/compose").status_code == 404


def test_composed_variant_404_before_compose(env):
    client, _ = env
    assert client.get(f"/api/shops/{SLUG}/composed/table-regular").status_code == 404


def test_patch_soldout_updates_cache_and_shop_doc(env):
    client, _ = env
    client.post(f"/api/shops/{SLUG}/compose")

    r = client.post(
        f"/api/shops/{SLUG}/patch",
        json={"dish_id": "dish_suon_nuong", "sold_out": True},
    )
    assert r.status_code == 200
    assert r.json()["patched_variants"] == sorted(VARIANTS)
    assert r.json()["patches"] == [{"path": "/soldout/dish_suon_nuong", "value": True}]

    # cached variant now carries the patch as a trailing updateDataModel
    msgs = client.get(f"/api/shops/{SLUG}/composed/office-lunch").json()
    tail = msgs[-1]["updateDataModel"]
    assert tail["path"] == "/soldout/dish_suon_nuong" and tail["value"] is True

    # shop doc synced -> next structural recompose keeps the flag
    doc = client.get(f"/api/shops/{SLUG}").json()
    assert doc["menu"]["dishes"]["dish_suon_nuong"]["sold_out"] is True


def test_patch_price_via_raw_path(env):
    client, _ = env
    client.post(f"/api/shops/{SLUG}/compose")
    r = client.post(
        f"/api/shops/{SLUG}/patch",
        json={"path": "/prices/dish_tra_da", "value": 4000},
    )
    assert r.status_code == 200
    msgs = client.get(f"/api/shops/{SLUG}/composed/table-regular").json()
    assert msgs[-1]["updateDataModel"] == {
        "surfaceId": "shop_menu", "path": "/prices/dish_tra_da", "value": 4000,
    }
    doc = client.get(f"/api/shops/{SLUG}").json()
    assert doc["menu"]["dishes"]["dish_tra_da"]["price"] == 4000


def test_compose_without_theme_409s_with_hero_hint(env):
    # Imported shops have no shop.theme yet (schema-optional) — compose and
    # menu-edit recompose must 409 with a clear message, not 500 on KeyError.
    client, _ = env
    doc = load_demo_fixture()
    doc["shop"].pop("theme", None)
    doc["shop"]["id"] = "shop_chua_theme"
    doc["shop"]["slug"] = "chua-theme"
    doc["shop"]["name"] = "Quán Chưa Theme"
    assert client.post("/api/shops", json=doc).status_code == 201

    r = client.post("/api/shops/chua-theme/compose")
    assert r.status_code == 409
    assert "hero" in r.json()["detail"]

    r = client.patch(
        "/api/shops/chua-theme/menu",
        json={"edits": [{"op": "set_price", "dish_id": "dish_tra_da", "price": 5000}]},
    )
    assert r.status_code == 409


def test_patch_rejects_bad_value_types(env):
    client, _ = env
    client.post(f"/api/shops/{SLUG}/compose")
    # Non-numeric price must never be persisted (would 500 buyer checkout).
    assert client.post(
        f"/api/shops/{SLUG}/patch", json={"dish_id": "dish_tra_da", "price": "abc"}
    ).status_code == 422
    assert client.post(
        f"/api/shops/{SLUG}/patch", json={"path": "/prices/dish_tra_da", "value": None}
    ).status_code == 422
    # Sold-out flags must be booleans.
    assert client.post(
        f"/api/shops/{SLUG}/patch", json={"dish_id": "dish_tra_da", "sold_out": "yes"}
    ).status_code == 422
    doc = client.get(f"/api/shops/{SLUG}").json()
    assert doc["menu"]["dishes"]["dish_tra_da"]["price"] == 3000  # untouched

    # Coercible price strings ('45,000đ') still work — same rule as menu edits.
    r = client.post(
        f"/api/shops/{SLUG}/patch", json={"dish_id": "dish_tra_da", "price": "4.000đ"}
    )
    assert r.status_code == 200
    assert r.json()["patches"] == [{"path": "/prices/dish_tra_da", "value": 4000}]


def test_patch_validation_errors(env):
    client, _ = env
    client.post(f"/api/shops/{SLUG}/compose")
    assert client.post(f"/api/shops/{SLUG}/patch", json={}).status_code == 422
    assert client.post(
        f"/api/shops/{SLUG}/patch", json={"path": "/soldout/x"}
    ).status_code == 422
    assert client.post(
        f"/api/shops/{SLUG}/patch", json={"dish_id": "dish_khong_co", "sold_out": True}
    ).status_code == 404
    assert client.post(
        f"/api/shops/{SLUG}/patch", json={"dish_id": "dish_tra_da"}
    ).status_code == 422
    assert client.post(
        f"/api/shops/{SLUG}/patch", json={"path": "no-slash", "value": 1}
    ).status_code == 422


def test_patch_before_compose_patches_nothing(env):
    client, _ = env
    r = client.post(
        f"/api/shops/{SLUG}/patch",
        json={"dish_id": "dish_tra_da", "sold_out": True},
    )
    assert r.status_code == 200
    assert r.json()["patched_variants"] == []


def test_delete_shop_clears_composed_cache(env):
    client, tmp_path = env
    client.post(f"/api/shops/{SLUG}/compose")
    assert (tmp_path / "composed" / SLUG / "table-regular.json").is_file()
    assert client.delete(f"/api/shops/{SLUG}").status_code == 204
    assert not (tmp_path / "composed" / SLUG / "table-regular.json").exists()
