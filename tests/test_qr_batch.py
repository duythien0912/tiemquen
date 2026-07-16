"""infra/qr_batch.py — batch registry + orders_per_batch analytics."""

import datetime

import pytest

from infra.orders import OrderStore
from infra.qr_batch import (
    BatchError,
    BatchNotFoundError,
    BatchStore,
    orders_per_batch,
    qr_url,
)
from infra.storage import LocalJSONStorage


@pytest.fixture()
def storage(tmp_path):
    return LocalJSONStorage(tmp_path)


@pytest.fixture()
def batches(storage):
    return BatchStore(storage)


SHOP = ("shop_comtamcoba", "com-tam-co-ba")


def test_create_batch_embeds_location_and_format(batches):
    batch = batches.create_batch(*SHOP, "a5", "Office Plaza 1")
    assert batch["id"].startswith("office-plaza-1-a5-")
    assert batch["format"] == "a5"
    assert batch["location_tag"] == "Office Plaza 1"
    assert batches.get(batch["id"]) == batch


def test_qr_url_shape(batches):
    batch = batches.create_batch(*SHOP, "a4", "pantry A")
    url = qr_url("com-tam-co-ba", batch["id"])
    assert url == f"/t/com-tam-co-ba?b={batch['id']}"
    absolute = qr_url("com-tam-co-ba", batch["id"], base_url="https://tiemquen.com/")
    assert absolute == f"https://tiemquen.com/t/com-tam-co-ba?b={batch['id']}"


def test_create_batch_validates_inputs(batches):
    with pytest.raises(BatchError):
        batches.create_batch(*SHOP, "a6", "x")  # unknown format
    with pytest.raises(BatchError):
        batches.create_batch(*SHOP, "a5", "")  # missing location


def test_list_and_delete(batches):
    b1 = batches.create_batch(*SHOP, "a5", "cua quan")
    b2 = batches.create_batch(*SHOP, "a4", "pantry")
    batches.create_batch("shop_other", "other-shop", "a5", "elsewhere")
    ids = [b["id"] for b in batches.list_by_shop("com-tam-co-ba")]
    assert ids == [b1["id"], b2["id"]]
    assert batches.delete(b1["id"]) is True
    assert batches.delete(b1["id"]) is False
    with pytest.raises(BatchNotFoundError):
        batches.get(b1["id"])


# ------------------------------------------------------------------ analytics


def _mk_order(orders: OrderStore, batch_id, price=10000, qty=1):
    return orders.create(
        shop_id=SHOP[0], shop_slug=SHOP[1],
        items=[{"dish_id": "d1", "name": "Cơm", "price": price, "qty": qty}],
        customer={"name": "An", "phone": "0", "address": "x"},
        batch_id=batch_id,
    )


def test_orders_per_batch_counts_and_revenue(storage):
    orders = OrderStore(storage)
    _mk_order(orders, "office-plaza-1-a5-aaaa", price=35000)
    _mk_order(orders, "office-plaza-1-a5-aaaa", price=35000, qty=2)
    _mk_order(orders, "cua-quan-a4-bbbb", price=20000)
    _mk_order(orders, None)  # walk-in/direct — no flyer batch

    stats = orders_per_batch(storage, SHOP[1])
    assert stats["office-plaza-1-a5-aaaa"]["orders"] == 2
    assert stats["office-plaza-1-a5-aaaa"]["revenue"] == 35000 * 3
    assert stats["cua-quan-a4-bbbb"]["orders"] == 1
    assert stats["direct"]["orders"] == 1


def test_orders_per_batch_ignores_other_shops(storage):
    orders = OrderStore(storage)
    _mk_order(orders, "office-x")
    orders.create(
        shop_id="shop_other", shop_slug="other-shop",
        items=[{"dish_id": "d", "name": "Bún", "price": 40000, "qty": 1}],
        customer={"name": "B", "phone": "0", "address": "y"},
        batch_id="office-x",
    )
    stats = orders_per_batch(storage, SHOP[1])
    assert stats["office-x"]["orders"] == 1


def test_orders_per_batch_since_filter(storage):
    orders = OrderStore(storage)
    old = _mk_order(orders, "batch-old")
    # Backdate the first order by rewriting its created_at.
    old["created_at"] = "2020-01-01T00:00:00+00:00"
    storage.put("orders", old["id"], old)
    _mk_order(orders, "batch-new")

    cutoff = (
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
    ).isoformat()
    stats = orders_per_batch(storage, SHOP[1], since=cutoff)
    assert "batch-new" in stats and "batch-old" not in stats

    # No cutoff -> both.
    stats_all = orders_per_batch(storage, SHOP[1])
    assert {"batch-new", "batch-old"} <= set(stats_all)
