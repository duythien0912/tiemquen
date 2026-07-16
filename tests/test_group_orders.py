"""Group orders — office pantry flow (ARCH §3.3). Split math with UNEVEN
per-member totals must sum exactly to the order total (no equal-division
remainder)."""

import pytest

from infra.group_orders import GroupOrderError, GroupOrderNotFoundError, GroupOrderStore
from infra.orders import OrderStore
from infra.storage import LocalJSONStorage


@pytest.fixture()
def stores(tmp_path):
    storage = LocalJSONStorage(tmp_path)
    return GroupOrderStore(storage), OrderStore(storage)


def _item(dish_id, name, price, qty):
    return {"dish_id": dish_id, "name": name, "price": price, "qty": qty}


def test_get_unknown_group_order_raises(stores):
    group_store, _ = stores
    with pytest.raises(GroupOrderNotFoundError):
        group_store.get("g_doesnotexist")


def test_create_defaults_office_batch(stores):
    group_store, _ = stores
    g = group_store.create("shop_x", "shop-x")
    assert g["status"] == "open"
    assert g["batch_id"] == "office"
    assert g["members"] == {}


def test_add_member_items_computes_subtotal(stores):
    group_store, _ = stores
    g = group_store.create("shop_x", "shop-x", batch_id="office-plaza1")
    g = group_store.add_member_items(
        g["id"], "An", [_item("dish_suon_nuong", "Cơm sườn", 35000, 1)]
    )
    assert g["members"]["An"]["subtotal"] == 35000

    # Re-submitting replaces (not appends to) that member's picks.
    g = group_store.add_member_items(
        g["id"], "An", [_item("dish_suon_nuong", "Cơm sườn", 35000, 2)]
    )
    assert g["members"]["An"]["subtotal"] == 70000
    assert len(g["members"]) == 1


def test_add_member_items_requires_name_and_items(stores):
    group_store, _ = stores
    g = group_store.create("shop_x", "shop-x")
    with pytest.raises(GroupOrderError):
        group_store.add_member_items(g["id"], "", [_item("d1", "X", 10000, 1)])
    with pytest.raises(GroupOrderError):
        group_store.add_member_items(g["id"], "An", [])


def test_cannot_add_items_after_close(stores):
    group_store, order_store = stores
    g = group_store.create("shop_x", "shop-x")
    group_store.add_member_items(g["id"], "An", [_item("d1", "Cơm sườn", 35000, 1)])
    group_store.close(g["id"], order_store, "An", {"name": "An", "phone": "0909", "address": "12 X"})
    with pytest.raises(GroupOrderError):
        group_store.add_member_items(g["id"], "Binh", [_item("d1", "Cơm sườn", 35000, 1)])


def test_close_requires_closer_to_be_a_member(stores):
    group_store, order_store = stores
    g = group_store.create("shop_x", "shop-x")
    group_store.add_member_items(g["id"], "An", [_item("d1", "Cơm sườn", 35000, 1)])
    with pytest.raises(GroupOrderError):
        group_store.close(g["id"], order_store, "Binh", {"name": "Binh", "phone": "0909", "address": "12 X"})


def test_close_uneven_split_sums_exactly_to_order_total(stores):
    group_store, order_store = stores
    g = group_store.create("shop_x", "shop-x", batch_id="office-plaza1")
    # Deliberately UNEVEN: 3 members, wildly different subtotals that do not
    # divide evenly by 3 or by any round number.
    group_store.add_member_items(
        g["id"], "An", [_item("dish_suon_nuong", "Cơm sườn nướng", 35000, 1)]  # 35000
    )
    group_store.add_member_items(
        g["id"], "Binh",
        [
            _item("dish_suon_bi_cha", "Cơm sườn bì chả", 45000, 1),
            _item("dish_tra_da", "Trà đá", 3000, 2),
        ],  # 45000 + 6000 = 51000
    )
    group_store.add_member_items(
        g["id"], "Chi", [_item("dish_canh_khoqua", "Canh khổ qua", 15000, 3)]  # 45000
    )
    # 35000 + 51000 + 45000 = 131000 — not evenly divisible by 3 (43666.67)

    result = group_store.close(
        g["id"], order_store, "An", {"name": "An", "phone": "0909111222", "address": "45 Y"}
    )
    order = result["order"]
    split = result["split"]

    assert order["total"] == 131000
    assert sum(v["amount"] for v in split.values()) == order["total"]  # NO rounding remainder
    assert split["An"] == {"amount": 35000, "is_payer": True}
    assert split["Binh"]["amount"] == 51000
    assert split["Binh"]["is_payer"] is False
    assert split["Binh"]["vietqr_placeholder"]["payee"] == "An"
    assert split["Binh"]["vietqr_placeholder"]["amount"] == 51000
    assert split["Chi"]["amount"] == 45000
    assert "vietqr_placeholder" not in split["An"]  # payer doesn't owe themself

    # One real order, one ship — items merged across members.
    merged = {it["dish_id"]: it["qty"] for it in order["items"]}
    assert merged == {
        "dish_suon_nuong": 1,
        "dish_suon_bi_cha": 1,
        "dish_tra_da": 2,
        "dish_canh_khoqua": 3,
    }
    assert order["group_order_id"] == g["id"]
    assert order["batch_id"] == "office-plaza1"  # flyer analytics

    g_final = group_store.get(g["id"])
    assert g_final["status"] == "closed"
    assert g_final["order_id"] == order["id"]


def test_cannot_close_twice(stores):
    group_store, order_store = stores
    g = group_store.create("shop_x", "shop-x")
    group_store.add_member_items(g["id"], "An", [_item("d1", "Cơm sườn", 35000, 1)])
    group_store.close(g["id"], order_store, "An", {"name": "An", "phone": "0909", "address": "12 X"})
    with pytest.raises(GroupOrderError):
        group_store.close(g["id"], order_store, "An", {"name": "An", "phone": "0909", "address": "12 X"})


def test_cannot_close_with_no_members(stores):
    group_store, order_store = stores
    g = group_store.create("shop_x", "shop-x")
    with pytest.raises(GroupOrderError):
        group_store.close(g["id"], order_store, "An", {"name": "An", "phone": "0909", "address": "12 X"})
