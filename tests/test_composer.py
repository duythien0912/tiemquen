"""Mock-mode composer: menu chuẩn -> validated A2UI, variants per ARCH §5.3."""

import copy

import pytest

from agents.tiemquen_agent import a2ui
from compose.composer import VARIANTS, compose, compose_all_variants, is_mock_mode
from shared.menu_format import load_demo_fixture


@pytest.fixture(autouse=True)
def _force_mock(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert is_mock_mode()


@pytest.fixture()
def fixture_doc():
    return load_demo_fixture()


def _components(messages):
    for m in messages:
        if "updateComponents" in m:
            return {c["id"]: c for c in m["updateComponents"]["components"]}
    raise AssertionError("no updateComponents message")


def _data_model(messages):
    return {
        m["updateDataModel"]["path"]: m["updateDataModel"]["value"]
        for m in messages
        if "updateDataModel" in m
    }


def test_compose_produces_valid_messages_no_warnings(fixture_doc):
    messages = compose(fixture_doc)
    # Re-validating the cached output must be a no-op (clean JSON in cache).
    clean, warnings = a2ui.validate_and_repair(messages, catalog=a2ui.load_catalog())
    assert warnings == []
    assert clean == messages
    assert "createSurface" in messages[0]


def test_all_used_components_are_in_catalog(fixture_doc):
    catalog_names = a2ui.catalog_component_names(a2ui.load_catalog())
    for variant in VARIANTS:
        comps = _components(compose(fixture_doc, variant=variant))
        used = {c["component"] for c in comps.values()}
        assert used <= catalog_names
        # the core commerce set is actually present
        assert {"Page", "HeroHeader", "MenuSection", "DishCard", "CartBar",
                "CheckoutForm", "PaymentPicker", "GroupOrderButton"} <= used


def test_prices_and_soldout_are_data_bound(fixture_doc):
    messages = compose(fixture_doc)
    comps = _components(messages)
    data = _data_model(messages)
    cards = [c for c in comps.values() if c["component"] == "DishCard"]
    assert cards
    for card in cards:
        dish_id = card["onPress"]["event"]["context"]["dishId"]["literalString"]
        assert card["price"] == {"path": f"/prices/{dish_id}"}
        assert card["soldOut"] == {"path": f"/soldout/{dish_id}"}
        assert dish_id in data["/prices"]
        assert dish_id in data["/soldout"]
    # fixture flags survive into the data model
    assert data["/soldout"]["dish_canh_khoqua"] is True
    assert data["/prices"]["dish_suon_nuong"] == 35000
    # COD default, VietQR hidden behind trust gate
    assert data["/payment"] == {"selected": "cod", "vietqr_enabled": False}
    assert "/theme" in data


def test_hidden_dishes_are_excluded(fixture_doc):
    doc = copy.deepcopy(fixture_doc)
    doc["menu"]["dishes"]["dish_tra_da"]["hidden"] = True
    messages = compose(doc)
    comps = _components(messages)
    carded = {
        c["onPress"]["event"]["context"]["dishId"]["literalString"]
        for c in comps.values()
        if c["component"] == "DishCard"
    }
    assert "dish_tra_da" not in carded
    assert "dish_tra_da" not in _data_model(messages)["/prices"]


def test_office_variant_promotes_group_order_button(fixture_doc):
    def page_children(variant):
        comps = _components(compose(fixture_doc, variant=variant))
        return comps["root"]["childIds"]["explicitList"]

    office = page_children("office-regular")
    table = page_children("table-regular")
    # office: nút gom đơn nổi gần đầu trang; table: cuối trang (ARCH §5.3)
    assert office.index("group_order") < office.index("cart_bar")
    assert office.index("group_order") <= 2
    assert table.index("group_order") > table.index(
        [c for c in table if c.startswith("section_")][-1]
    )


def test_lunch_variant_reorders_combo_section():
    doc = load_demo_fixture()
    doc = copy.deepcopy(doc)
    # give the fixture a lunch section, last in menu order
    doc["menu"]["sections"].append(
        {"id": "sec_trua", "title": "Combo trưa văn phòng", "items": ["dish_suon_nuong"]}
    )
    def section_order(variant):
        comps = _components(compose(doc, variant=variant))
        root = comps["root"]["childIds"]["explicitList"]
        return [c for c in root if c.startswith("section_")]

    assert section_order("table-lunch")[0] == "section_sec_trua"
    assert section_order("table-regular")[-1] == "section_sec_trua"


def test_compose_all_variants_returns_all_four(fixture_doc):
    variants = compose_all_variants(fixture_doc)
    assert set(variants) == set(VARIANTS) and len(VARIANTS) == 4
    for msgs in variants.values():
        assert "createSurface" in msgs[0]


def test_unknown_variant_rejected(fixture_doc):
    with pytest.raises(ValueError, match="variant"):
        compose(fixture_doc, variant="beach-midnight")
