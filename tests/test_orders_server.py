"""HTTP layer for orders/group-orders/buyer-page (ENGINE-SPEC §8, ARCH §3.2/§3.3)."""

import pytest
from fastapi.testclient import TestClient

from agents.tiemquen_agent.server import create_app
from infra.storage import LocalJSONStorage
from shared.menu_format import load_demo_fixture


@pytest.fixture(autouse=True)
def _fast_ack_timeout(monkeypatch):
    # TestClient awaits BackgroundTasks as part of the request/response cycle
    # (unlike real uvicorn, where they run after the bytes hit the wire) —
    # so every POST /orders would otherwise block the test for the full
    # 120s default ack-timeout. ENGINE-SPEC §8 explicitly calls out tests
    # using 0.1s for exactly this reason.
    monkeypatch.setenv("ACK_TIMEOUT_SECONDS", "0.1")


@pytest.fixture()
def client(tmp_path):
    app = create_app(storage=LocalJSONStorage(tmp_path))
    with TestClient(app) as c:
        c.post("/api/shops", json=load_demo_fixture())
        yield c


SLUG = "com-tam-co-ba"


def _order_body(**overrides):
    body = {
        "slug": SLUG,
        "batch_id": "office-plaza1",
        "items": [{"dish_id": "dish_suon_nuong", "qty": 2}, {"dish_id": "dish_tra_da", "qty": 1}],
        "customer": {"name": "An", "phone": "0909000111", "address": "12 Lê Lợi"},
    }
    body.update(overrides)
    return body


def test_buyer_page_returns_html_with_renderer_script(client):
    r = client.get(f"/t/{SLUG}")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "renderer.js" in r.text
    assert SLUG in r.text  # bootstrap payload injected


def test_buyer_page_unknown_slug_404s(client):
    assert client.get("/t/khong-ton-tai").status_code == 404


def test_create_order_prices_server_side_and_notifies(client):
    r = client.post("/orders", json=_order_body())
    assert r.status_code == 201, r.text
    order = r.json()
    assert order["status"] == "created"
    assert order["total"] == 35000 * 2 + 3000
    assert order["batch_id"] == "office-plaza1"
    assert order["items"][0]["name"] == "Cơm tấm sườn nướng"  # server-resolved, not client-sent


def test_create_order_rejects_sold_out_dish(client):
    body = _order_body(items=[{"dish_id": "dish_canh_khoqua", "qty": 1}])  # sold_out=true in fixture
    r = client.post("/orders", json=body)
    assert r.status_code == 409


def test_create_order_rejects_unknown_dish(client):
    body = _order_body(items=[{"dish_id": "dish_khong_ton_tai", "qty": 1}])
    assert client.post("/orders", json=body).status_code == 422


def test_create_order_requires_customer_fields(client):
    body = _order_body(customer={"name": "An"})
    assert client.post("/orders", json=body).status_code == 422


def test_order_status_and_ack_flow(client):
    order = client.post("/orders", json=_order_body()).json()
    oid = order["id"]

    r = client.get(f"/orders/{oid}/status")
    assert r.json()["status"] == "created"

    r = client.post(f"/orders/{oid}/ack")
    assert r.json()["status"] == "seller_seen"

    r = client.get(f"/orders/{oid}/status")
    assert r.json()["status"] == "seller_seen"
    assert "thấy đơn" in r.json()["message"]


def test_transition_endpoint_valid_and_invalid(client):
    order = client.post("/orders", json=_order_body()).json()
    oid = order["id"]
    r = client.post(f"/orders/{oid}/transition", json={"to": "seller_seen"})
    assert r.status_code == 200 and r.json()["status"] == "seller_seen"

    r = client.post(f"/orders/{oid}/transition", json={"to": "done"})  # skips confirmed/delivering
    assert r.status_code == 409


def test_get_unknown_order_404s(client):
    assert client.get("/orders/ord_nope").status_code == 404
    assert client.post("/orders/ord_nope/ack").status_code == 404


def test_parse_text_endpoint(client):
    r = client.post(
        "/orders/parse-text",
        json={"slug": SLUG, "text": "2 cơm sườn nướng\ngiao 12 Lê Lợi\n0909111222"},
    )
    assert r.status_code == 200, r.text
    draft = r.json()
    assert draft["items"][0]["dish_id"] == "dish_suon_nuong"
    assert draft["items"][0]["qty"] == 2


def test_group_order_full_flow(client):
    r = client.post("/group-orders", json={"slug": SLUG, "batch_id": "office-plaza1"})
    assert r.status_code == 201
    gid = r.json()["gid"]
    assert r.json()["share_url"] == f"/g/{gid}"

    r = client.get(f"/g/{gid}")
    assert r.status_code == 200 and gid in r.text

    r = client.post(
        f"/group-orders/{gid}/members",
        json={"name": "An", "items": [{"dish_id": "dish_suon_nuong", "qty": 1}]},
    )
    assert r.status_code == 200
    assert r.json()["members"]["An"]["subtotal"] == 35000

    client.post(
        f"/group-orders/{gid}/members",
        json={"name": "Binh", "items": [{"dish_id": "dish_tra_da", "qty": 2}]},
    )

    r = client.post(
        f"/group-orders/{gid}/close",
        json={"closer_name": "An", "customer": {"name": "An", "phone": "0909", "address": "12 X"}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["order"]["total"] == 35000 + 6000
    assert body["split"]["An"]["is_payer"] is True
    assert body["split"]["Binh"]["amount"] == 6000

    r = client.get(f"/group-orders/{gid}")
    assert r.json()["status"] == "closed"


def test_group_order_unknown_gid_404s(client):
    assert client.get("/group-orders/g_nope").status_code == 404
    assert client.get("/g/g_nope").status_code == 404
