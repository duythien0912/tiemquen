"""A2UI protocol: builders + parse + validate/REPAIR (ENGINE-SPEC §1)."""

import pytest

from agents.tiemquen_agent import a2ui
from agents.tiemquen_agent.a2ui import (
    A2UIValidationError,
    make_create_surface,
    make_delete_surface,
    make_update_components,
    make_update_data_model,
    parse_a2ui,
    validate_and_repair,
)


def _minimal_components():
    return [
        {"id": "root", "component": "Page", "childIds": {"explicitList": ["hero"]}},
        {"id": "hero", "component": "HeroHeader", "shopName": {"literalString": "Cô Ba"}},
    ]


def _valid_messages():
    return [
        make_create_surface("shop_menu"),
        make_update_components("shop_menu", _minimal_components()),
        make_update_data_model("shop_menu", "/prices", {"d1": 35000}),
    ]


# ---------------------------------------------------------------------- builders


def test_builders_shapes():
    assert make_create_surface("s") == {
        "version": "v0.9",
        "createSurface": {"surfaceId": "s", "catalogId": "tiemquen_emenu_v1"},
    }
    upd = make_update_components("s", _minimal_components())
    assert upd["updateComponents"]["root"] == "root"
    assert make_update_data_model("s", "/x", 1) == {
        "version": "v0.9",
        "updateDataModel": {"surfaceId": "s", "path": "/x", "value": 1},
    }
    assert make_delete_surface("s") == {"version": "v0.9", "deleteSurface": {"surfaceId": "s"}}


def test_valid_payload_passes_with_no_warnings():
    clean, warnings = validate_and_repair(_valid_messages())
    assert warnings == []
    assert len(clean) == 3


# ------------------------------------------------------------------------ parse


def test_parse_a2ui_tag_wrapper_and_fence_and_bare():
    body = '[{"version":"v0.9","createSurface":{"surfaceId":"s","catalogId":"c"}}]'
    assert parse_a2ui(f"blah <a2ui-json>{body}</a2ui-json> blah")[0]["createSurface"]
    assert parse_a2ui(f"```json\n{body}\n```")[0]["createSurface"]
    assert parse_a2ui(body)[0]["createSurface"]
    # single object -> wrapped into a list
    assert isinstance(parse_a2ui('{"createSurface":{"surfaceId":"s"}}'), list)


def test_parse_a2ui_garbage_raises():
    with pytest.raises(A2UIValidationError):
        parse_a2ui("chào bạn, đây không phải JSON")


# ------------------------------------------------------------------ repair cases


def test_repair_missing_version_injected():
    msgs = _valid_messages()
    del msgs[1]["version"]
    clean, warnings = validate_and_repair(msgs)
    assert all(m["version"] == "v0.9" for m in clean)
    assert any("missing version" in w for w in warnings)


def test_repair_infer_action_key_update_components():
    msgs = [
        make_create_surface("shop_menu"),
        {  # no action key — payload shape says updateComponents
            "version": "v0.9",
            "surfaceId": "shop_menu",
            "root": "root",
            "components": _minimal_components(),
        },
    ]
    clean, warnings = validate_and_repair(msgs)
    assert "updateComponents" in clean[1]
    assert any("inferred 'updateComponents'" in w for w in warnings)


def test_repair_infer_action_key_create_surface():
    msgs = [
        {"surfaceId": "shop_menu", "catalogId": "tiemquen_emenu_v1"},  # -> createSurface
        make_update_components("shop_menu", _minimal_components()),
    ]
    clean, warnings = validate_and_repair(msgs)
    assert "createSurface" in clean[0]
    assert any("inferred 'createSurface'" in w for w in warnings)


def test_repair_infer_action_key_update_data_model():
    msgs = _valid_messages()[:2] + [
        {"version": "v0.9", "surfaceId": "shop_menu", "path": "/soldout/d1", "value": True}
    ]
    clean, warnings = validate_and_repair(msgs)
    assert clean[2]["updateDataModel"]["path"] == "/soldout/d1"
    assert any("inferred 'updateDataModel'" in w for w in warnings)


def test_uninferable_action_key_raises():
    with pytest.raises(A2UIValidationError):
        validate_and_repair([{"version": "v0.9", "mystery": 1}])


def test_repair_auto_prepend_create_surface():
    msgs = [make_update_components("shop_menu", _minimal_components())]
    clean, warnings = validate_and_repair(msgs)
    assert "createSurface" in clean[0]
    assert clean[0]["createSurface"]["surfaceId"] == "shop_menu"
    assert any("auto-prepended" in w for w in warnings)
    # createSurface is only prepended once for the surface
    assert sum(1 for m in clean if "createSurface" in m) == 1


def test_repair_missing_surface_id_defaulted():
    msgs = [{"version": "v0.9", "updateDataModel": {"path": "/x", "value": 1}}]
    clean, warnings = validate_and_repair(msgs)
    assert clean[-1]["updateDataModel"]["surfaceId"] == a2ui.DEFAULT_SURFACE_ID
    assert any("missing surfaceId" in w for w in warnings)


# ---------------------------------------------------------- flat-wire component


def test_component_without_id_dropped_with_warning():
    comps = _minimal_components() + [{"component": "Badge", "text": {"literalString": "x"}}]
    msgs = [make_create_surface("s"), make_update_components("s", comps)]
    clean, warnings = validate_and_repair(msgs)
    ids = [c.get("id") for c in clean[1]["updateComponents"]["components"]]
    assert None not in ids and len(ids) == 2
    assert any("without id/component" in w for w in warnings)


def test_missing_root_raises():
    comps = [{"id": "hero", "component": "HeroHeader", "shopName": {"literalString": "x"}}]
    msgs = [make_create_surface("s"), make_update_components("s", comps, root="root")]
    with pytest.raises(A2UIValidationError, match="root"):
        validate_and_repair(msgs)


def test_bare_child_list_and_pointer_repaired():
    comps = [
        {"id": "root", "component": "Page", "childIds": ["sec"]},  # bare list
        {"id": "sec", "component": "MenuSection", "title": {"literalString": "Cơm"},
         "childIds": "/sections/sec/items"},  # bare pointer
    ]
    msgs = [make_create_surface("s"), make_update_components("s", comps)]
    clean, warnings = validate_and_repair(msgs)
    got = {c["id"]: c for c in clean[1]["updateComponents"]["components"]}
    assert got["root"]["childIds"] == {"explicitList": ["sec"]}
    assert got["sec"]["childIds"] == {"dataBinding": "/sections/sec/items"}
    assert len(warnings) == 2


def test_dangling_child_refs_pruned_with_warning():
    comps = [
        {"id": "root", "component": "Page", "childIds": {"explicitList": ["hero", "ghost"]}},
        {"id": "hero", "component": "HeroHeader", "shopName": {"literalString": "x"},
         "childId": "khong-ton-tai"},
    ]
    msgs = [make_create_surface("s"), make_update_components("s", comps)]
    clean, warnings = validate_and_repair(msgs)
    got = {c["id"]: c for c in clean[1]["updateComponents"]["components"]}
    assert got["root"]["childIds"] == {"explicitList": ["hero"]}
    assert "childId" not in got["hero"]
    assert any("ghost" in w for w in warnings)
    assert any("khong-ton-tai" in w for w in warnings)


def test_raw_literals_wrapped_into_leaf_shapes():
    comps = [
        {"id": "root", "component": "Page", "childIds": {"explicitList": ["d"]}},
        {"id": "d", "component": "DishCard", "name": "Cơm sườn", "price": 35000,
         "soldOut": False, "image": "/prices/x-not-image",
         "onPress": {"event": {"name": "add_to_cart", "context": {}}}},
    ]
    msgs = [make_create_surface("s"), make_update_components("s", comps)]
    clean, warnings = validate_and_repair(msgs)
    d = {c["id"]: c for c in clean[1]["updateComponents"]["components"]}["d"]
    assert d["name"] == {"literalString": "Cơm sườn"}
    assert d["price"] == {"literalNumber": 35000}
    assert d["soldOut"] == {"literalBoolean": False}
    assert d["image"] == {"path": "/prices/x-not-image"}  # leading / -> path bind
    assert len(warnings) == 4


def test_malformed_event_dropped():
    comps = [
        {"id": "root", "component": "Page", "childIds": {"explicitList": []}},
    ]
    comps[0]["onPress"] = {"event": {"context": {}}}  # missing name
    msgs = [make_create_surface("s"), make_update_components("s", comps)]
    clean, warnings = validate_and_repair(msgs)
    root = clean[1]["updateComponents"]["components"][0]
    assert "onPress" not in root
    assert any("malformed event" in w for w in warnings)


def test_component_type_not_in_catalog_raises():
    catalog = a2ui.load_catalog()
    comps = [{"id": "root", "component": "SpaceShip"}]
    msgs = [make_create_surface("s"), make_update_components("s", comps)]
    with pytest.raises(A2UIValidationError, match="SpaceShip"):
        validate_and_repair(msgs, catalog=catalog)


def test_update_data_model_bad_path_raises():
    msgs = [make_create_surface("s"),
            {"version": "v0.9", "updateDataModel": {"surfaceId": "s", "path": "no-slash", "value": 1}}]
    with pytest.raises(A2UIValidationError, match="path"):
        validate_and_repair(msgs)


def test_catalog_loads_and_has_all_spec_components():
    catalog = a2ui.load_catalog()
    names = a2ui.catalog_component_names(catalog)
    assert names == {
        "Page", "MenuSection", "HeroHeader", "Badge", "DishCard", "ComboCard",
        "ReorderCard", "CartBar", "GroupOrderButton", "ReviewStrip",
        "CheckoutForm", "PaymentPicker", "OrderStatus",
    }
    for name, schema in catalog["components"].items():
        assert schema["type"] == "object", name
        assert schema["description"], name
        assert "properties" in schema and "required" in schema, name
