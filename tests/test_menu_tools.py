"""menu_tools.py — MenuAssembler assembly + price sanity warnings."""

from __future__ import annotations

import pytest

from agents.tiemquen_agent.tools.menu_tools import MenuAssemblyError, MenuAssembler
from shared.menu_format import validate_menu


def test_full_assembly_produces_valid_chuan_menu():
    a = MenuAssembler(source_type="ocr_screenshot")
    a.set_shop_info(name="Cơm Tấm Cô Ba", phone="0909123456", hours="06:00-14:00")
    a.add_section(id="com_tam", title="Cơm tấm")
    a.add_dish(section_id="com_tam", name="Cơm sườn nướng", price=35000, desc="Ngon")
    a.finish(confidence=90)

    envelope = a.envelope()
    validate_menu(envelope["menu"])  # must not raise
    assert envelope["confidence"] == 90
    assert envelope["warnings"] == []
    assert envelope["menu"]["shop"]["slug"] == "com-tam-co-ba"
    dish_id = envelope["menu"]["menu"]["sections"][0]["items"][0]
    assert envelope["menu"]["menu"]["dishes"][dish_id]["price"] == 35000


def test_price_sanity_warning_below_min():
    a = MenuAssembler()
    a.set_shop_info(name="Quán X")
    a.add_section(id="s", title="Món")
    a.add_dish(section_id="s", name="Trà đá", price=1000)  # below 5,000 VND floor
    a.finish(confidence=80)
    warnings = a.envelope()["warnings"]
    assert any("1,000" in w or "Trà đá" in w for w in warnings)


def test_price_sanity_warning_above_max():
    a = MenuAssembler()
    a.set_shop_info(name="Quán X")
    a.add_section(id="s", title="Món")
    a.add_dish(section_id="s", name="Nước sâm", price=1_500_000)  # above 500k ceiling
    a.finish(confidence=80)
    warnings = a.envelope()["warnings"]
    assert any("Nước sâm" in w for w in warnings)


def test_price_within_range_no_warning():
    a = MenuAssembler()
    a.set_shop_info(name="Quán X")
    a.add_section(id="s", title="Món")
    a.add_dish(section_id="s", name="Cơm thường", price=35000)
    a.finish(confidence=80)
    assert a.envelope()["warnings"] == []


def test_build_without_shop_info_raises():
    a = MenuAssembler()
    a.add_section(id="s", title="Món")
    with pytest.raises(MenuAssemblyError):
        a.build()


def test_build_without_dishes_raises():
    a = MenuAssembler()
    a.set_shop_info(name="Quán X")
    with pytest.raises(MenuAssemblyError):
        a.build()


def test_finish_confidence_out_of_range_raises():
    a = MenuAssembler()
    with pytest.raises(ValueError):
        a.finish(confidence=150)


def test_add_dish_before_add_section_autocreates_with_warning():
    a = MenuAssembler()
    a.set_shop_info(name="Quán X")
    a.add_dish(section_id="chua_khai_bao", name="Món lạ", price=20000)
    a.finish(confidence=70)
    envelope = a.envelope()
    assert any("chưa khai báo" in w for w in envelope["warnings"])
    assert len(envelope["menu"]["menu"]["sections"]) == 1
