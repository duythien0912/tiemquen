"""Order-parse agent — mock heuristic on 3 representative Zalo chat texts."""

import pytest

from agents.tiemquen_agent.agents.order_parse_agent import is_mock_mode, parse_order_text
from shared.menu_format import load_demo_fixture


@pytest.fixture(autouse=True)
def _force_mock(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert is_mock_mode()


@pytest.fixture()
def menu():
    return load_demo_fixture()


def _items_by_dish(draft):
    return {it["dish_id"]: it["qty"] for it in draft["items"]}


def test_sample_1_greeting_and_va_separator(menu):
    text = (
        "Chị ơi cho em 2 cơm sườn nướng và 1 trà đá\n"
        "Giao tới 45 Điện Biên Phủ, P.Đa Kao nha\n"
        "Sđt em 0909888777"
    )
    draft = parse_order_text(text, menu)
    assert _items_by_dish(draft) == {"dish_suon_nuong": 2, "dish_tra_da": 1}
    assert draft["customer"]["phone"] == "0909888777"
    assert "Điện Biên Phủ" in draft["customer"]["address"]
    assert 0 <= draft["confidence"] <= 100


def test_sample_2_x_notation_and_name_label(menu):
    text = (
        "Em đặt: sườn bì chả x1, gà nướng x2, canh khổ qua\n"
        "Tên Lan, để ở toà nhà Bitexco tầng 5\n"
        "0912345678"
    )
    draft = parse_order_text(text, menu)
    assert _items_by_dish(draft) == {
        "dish_suon_bi_cha": 1,
        "dish_ga_nuong": 2,
        "dish_canh_khoqua": 1,
    }
    assert draft["customer"]["name"] == "Lan"
    assert draft["customer"]["phone"] == "0912345678"
    assert "Bitexco" in draft["customer"]["address"]


def test_sample_3_unmatched_dish_becomes_warning(menu):
    text = (
        "Cho quán 3 chả trứng hấp, 1 xíu mại đặc biệt (hết bán rồi ha)\n"
        "địa chỉ: 88 Bùi Viện, quận 1\n"
        "Chị Hoa - 0987001122"
    )
    draft = parse_order_text(text, menu)
    assert _items_by_dish(draft) == {"dish_cha_trung": 3}
    assert draft["customer"]["phone"] == "0987001122"
    assert "Bùi Viện" in draft["customer"]["address"]
    assert any("xíu mại" in w for w in draft["warnings"]), draft["warnings"]


def test_empty_text_rejected(menu):
    with pytest.raises(ValueError):
        parse_order_text("   ", menu)


def test_no_dishes_at_all_warns_instead_of_crashing(menu):
    draft = parse_order_text("Chào shop, cho hỏi còn bán không?", menu)
    assert draft["items"] == []
    assert any("không đọc được món nào" in w for w in draft["warnings"])
