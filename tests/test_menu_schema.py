import copy

import jsonschema
import pytest

from shared.menu_format import load_demo_fixture, validate_menu, validation_errors


@pytest.fixture()
def fixture_doc():
    return copy.deepcopy(load_demo_fixture())


def test_demo_fixture_is_valid(fixture_doc):
    validate_menu(fixture_doc)  # must not raise
    assert validation_errors(fixture_doc) == []


def test_fixture_has_realistic_shape(fixture_doc):
    assert len(fixture_doc["menu"]["sections"]) == 3
    assert len(fixture_doc["menu"]["dishes"]) == 10
    # platform_price higher than direct price (the whole point of thoát sàn)
    for dish in fixture_doc["menu"]["dishes"].values():
        assert dish["platform_price"] > dish["price"]


def test_missing_shop_name_is_invalid(fixture_doc):
    del fixture_doc["shop"]["name"]
    with pytest.raises(jsonschema.ValidationError):
        validate_menu(fixture_doc)


def test_bad_price_type_is_invalid(fixture_doc):
    fixture_doc["menu"]["dishes"]["dish_tra_da"]["price"] = "3000"
    with pytest.raises(jsonschema.ValidationError):
        validate_menu(fixture_doc)


def test_bad_slug_is_invalid(fixture_doc):
    fixture_doc["shop"]["slug"] = "Cơm Tấm!"
    with pytest.raises(jsonschema.ValidationError):
        validate_menu(fixture_doc)


def test_bad_source_type_is_invalid(fixture_doc):
    fixture_doc["source"]["type"] = "carrier_pigeon"
    with pytest.raises(jsonschema.ValidationError):
        validate_menu(fixture_doc)


def test_wrong_seed_color_count_is_invalid(fixture_doc):
    fixture_doc["shop"]["theme"]["seed_colors"] = ["#112233"]
    with pytest.raises(jsonschema.ValidationError):
        validate_menu(fixture_doc)


def test_dangling_dish_reference_is_invalid(fixture_doc):
    fixture_doc["menu"]["sections"][0]["items"].append("dish_khong_ton_tai")
    with pytest.raises(jsonschema.ValidationError):
        validate_menu(fixture_doc)
