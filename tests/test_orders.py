"""Order store — full legal path + every illegal transition (ENGINE-SPEC §8)."""

import pytest

from infra.orders import (
    DEFAULT_BATCH_ID,
    OrderNotFoundError,
    OrderStore,
    OrderTransitionError,
    compute_total,
    order_summary,
)
from infra.storage import LocalJSONStorage
from shared import order_states as st


@pytest.fixture()
def store(tmp_path):
    return OrderStore(LocalJSONStorage(tmp_path))


def _items():
    return [
        {"dish_id": "dish_suon_nuong", "name": "Cơm tấm sườn nướng", "price": 35000, "qty": 2},
        {"dish_id": "dish_tra_da", "name": "Trà đá", "price": 3000, "qty": 1},
    ]


def _customer():
    return {"name": "Khách A", "phone": "0909000111", "address": "12 Lê Lợi", "note": ""}


def test_create_defaults_batch_id_and_computes_total(store):
    order = store.create("shop_x", "shop-x", _items(), _customer())
    assert order["status"] == st.CREATED
    assert order["batch_id"] == DEFAULT_BATCH_ID
    assert order["total"] == compute_total(_items()) == 73000
    assert order["history"] == [{"from": None, "to": st.CREATED, "at": order["created_at"]}]


def test_create_rejects_empty_items(store):
    with pytest.raises(Exception):
        store.create("shop_x", "shop-x", [], _customer())


def test_get_unknown_order_raises(store):
    with pytest.raises(OrderNotFoundError):
        store.get("ord_doesnotexist")


def test_happy_path_full_transition_table(store):
    order = store.create("shop_x", "shop-x", _items(), _customer(), batch_id="office-plaza1")
    oid = order["id"]

    order = store.transition(oid, st.SELLER_SEEN)
    assert order["status"] == st.SELLER_SEEN and order["seller_seen_at"] is not None

    order = store.transition(oid, st.CONFIRMED)
    assert order["status"] == st.CONFIRMED and order["confirmed_at"] is not None

    order = store.transition(oid, st.DELIVERING)
    assert order["status"] == st.DELIVERING and order["delivering_at"] is not None

    order = store.transition(oid, st.DONE)
    assert order["status"] == st.DONE and order["done_at"] is not None
    assert [h["to"] for h in order["history"]] == [
        st.CREATED, st.SELLER_SEEN, st.CONFIRMED, st.DELIVERING, st.DONE
    ]
    assert order["batch_id"] == "office-plaza1"  # survives every transition, for flyer analytics


@pytest.mark.parametrize(
    "path",
    [
        (st.CREATED, st.CONFIRMED),       # skip seller_seen
        (st.CREATED, st.DELIVERING),      # skip further
        (st.CREATED, st.DONE),            # skip everything
        (st.CREATED, st.NO_SHOW_FLAGGED),  # only reachable from confirmed/delivering
        (st.SELLER_SEEN, st.DELIVERING),  # skip confirmed
        (st.SELLER_SEEN, st.DONE),
        (st.CONFIRMED, st.DONE),          # skip delivering
        (st.DELIVERING, st.CREATED),      # backwards
        (st.DELIVERING, st.CONFIRMED),    # backwards
        (st.DONE, st.CANCELLED),          # out of a terminal state
        (st.CANCELLED, st.CREATED),
        (st.NO_SHOW_FLAGGED, st.DONE),
    ],
)
def test_illegal_transitions_raise(store, path):
    current, attempted = path
    order = store.create("shop_x", "shop-x", _items(), _customer())
    oid = order["id"]
    # Drive the order to `current` via ANY legal path before probing the
    # illegal move, unless current IS the fresh `created` state already.
    legal_route = {
        st.SELLER_SEEN: [st.SELLER_SEEN],
        st.CONFIRMED: [st.SELLER_SEEN, st.CONFIRMED],
        st.DELIVERING: [st.SELLER_SEEN, st.CONFIRMED, st.DELIVERING],
        st.DONE: [st.SELLER_SEEN, st.CONFIRMED, st.DELIVERING, st.DONE],
        st.CANCELLED: [st.CANCELLED],
        st.NO_SHOW_FLAGGED: [st.SELLER_SEEN, st.CONFIRMED, st.NO_SHOW_FLAGGED],
    }.get(current, [])
    for step in legal_route:
        order = store.transition(oid, step)
    assert order["status"] == current

    with pytest.raises(OrderTransitionError) as exc_info:
        store.transition(oid, attempted)
    assert exc_info.value.current == current
    assert exc_info.value.attempted == attempted
    # Failed transition must not mutate the stored order.
    assert store.get(oid)["status"] == current


def test_cancel_from_any_active_state(store):
    for target in (st.CREATED, st.SELLER_SEEN, st.CONFIRMED):
        order = store.create("shop_x", "shop-x", _items(), _customer())
        oid = order["id"]
        route = {st.SELLER_SEEN: [st.SELLER_SEEN], st.CONFIRMED: [st.SELLER_SEEN, st.CONFIRMED]}.get(target, [])
        for step in route:
            store.transition(oid, step)
        cancelled = store.transition(oid, st.CANCELLED)
        assert cancelled["status"] == st.CANCELLED
        assert cancelled["cancelled_at"] is not None


def test_ack_moves_created_to_seller_seen(store):
    order = store.create("shop_x", "shop-x", _items(), _customer())
    assert not store.is_seller_seen(order["id"])
    acked = store.ack(order["id"])
    assert acked["status"] == st.SELLER_SEEN
    assert store.is_seller_seen(order["id"])


def test_ack_is_idempotent_past_created(store):
    order = store.create("shop_x", "shop-x", _items(), _customer())
    store.ack(order["id"])
    store.transition(order["id"], st.CONFIRMED)
    # Late/duplicate ack (buyer's timer fired twice) must NOT downgrade or 409.
    again = store.ack(order["id"])
    assert again["status"] == st.CONFIRMED


def test_order_summary_formats_vnd(store):
    order = store.create("shop_x", "shop-x", _items(), _customer())
    summary = order_summary(order)
    assert "2x Cơm tấm sườn nướng" in summary
    assert "1x Trà đá" in summary
    assert "73.000đ" in summary
