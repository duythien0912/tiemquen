"""import_agent.py — mock screenshot replay, URL fallback, raw text, dispatch."""

from __future__ import annotations

import pytest
import requests

from agents.tiemquen_agent.agents import import_agent
from agents.tiemquen_agent.agents.html_parse import ImportFallbackToOCR
from shared.menu_format import validate_menu


@pytest.fixture(autouse=True)
def _force_mock_mode(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


# --------------------------------------------------------------- classify_source


@pytest.mark.parametrize(
    "source,expected",
    [
        ("shot.png", "screenshot"),
        ("shot.JPG", "screenshot"),
        (["a.png", "b.webp"], "screenshot"),
        ("https://shopeefood.vn/shop/abc", "url"),
        ("http://example.com/menu", "url"),
        ("Cơm sườn - 35.000đ\nTrà đá - 3.000đ", "text"),
    ],
)
def test_classify_source(source, expected):
    assert import_agent.classify_source(source) == expected


# ------------------------------------------------------------ mock screenshot


def test_import_menu_screenshot_mock_replays_fixture_to_valid_menu():
    envelope = import_agent.import_menu("data/fixtures/does_not_need_to_exist.png")
    validate_menu(envelope["menu"])
    assert envelope["menu"]["shop"]["name"] == "Cơm Tấm Cô Ba"
    assert envelope["confidence"] == 82
    assert envelope["menu"]["source"]["type"] == "ocr_screenshot"
    # 8 dishes recorded in the fixture across 3 sections.
    assert len(envelope["menu"]["menu"]["dishes"]) == 8


def test_import_menu_screenshot_mock_triggers_price_sanity_warning():
    """The fixture deliberately has a mis-OCR'd price (1.500.000đ) to exercise
    the price-sanity warning path end to end through the real import entrypoint."""
    envelope = import_agent.import_menu("shot.png")
    assert any("Nước sâm" in w or "1,500,000" in w for w in envelope["warnings"])


def test_import_menu_screenshot_accepts_list_of_paths():
    envelope = import_agent.import_menu(["a.png", "b.jpg"])
    assert envelope["confidence"] == 82


def test_import_from_fixture_matches_import_menu_screenshot():
    a = import_agent.import_menu("shot.png")
    b = import_agent.import_from_fixture("grab_screenshot_toolcalls")
    assert a["menu"]["shop"]["name"] == b["menu"]["shop"]["name"]
    assert a["confidence"] == b["confidence"]


def test_import_from_fixture_missing_raises_file_not_found():
    with pytest.raises(FileNotFoundError):
        import_agent.import_from_fixture("khong-ton-tai")


# --------------------------------------------------------------------------- url


def test_import_menu_url_html_parse_success(monkeypatch):
    def fake_parse(url, **kwargs):
        return {
            "shop_name": "Quán Test",
            "sections": [{"title": "Menu", "dishes": [{"name": "Phở bò", "price": 45000}]}],
            "source_url": url,
        }

    monkeypatch.setattr(import_agent, "parse_shopeefood", fake_parse)
    envelope = import_agent.import_menu("https://shopeefood.vn/shop/quan-test")
    validate_menu(envelope["menu"])
    assert envelope["menu"]["shop"]["name"] == "Quán Test"
    assert envelope["menu"]["source"]["type"] == "html_parse"
    dish_id = envelope["menu"]["menu"]["sections"][0]["items"][0]
    assert envelope["menu"]["menu"]["dishes"][dish_id]["price"] == 45000


def test_import_menu_url_html_parse_failure_propagates_fallback_to_ocr(monkeypatch):
    def fake_parse(url, **kwargs):
        raise ImportFallbackToOCR("SPA render phía client, không parse được")

    monkeypatch.setattr(import_agent, "parse_shopeefood", fake_parse)
    with pytest.raises(ImportFallbackToOCR):
        import_agent.import_menu("https://shopeefood.vn/shop/khong-parse-duoc")


def test_html_parse_graceful_failure_on_network_error():
    """No monkeypatch — real html_parse.parse_shopeefood, but the network call
    itself is stubbed via an injected fake session so no real network happens."""
    from agents.tiemquen_agent.agents.html_parse import parse_shopeefood

    class FakeSession:
        def get(self, *a, **k):
            raise requests.ConnectionError("dns lookup failed")

    with pytest.raises(ImportFallbackToOCR):
        parse_shopeefood("https://shopeefood.vn/shop/anything", session=FakeSession())


def test_html_parse_success_with_embedded_next_data():
    """A synthetic Next.js-style hydration payload (`__NEXT_DATA__`) is the
    one shape `html_parse` is written to actually succeed on."""
    from agents.tiemquen_agent.agents.html_parse import parse_shopeefood

    payload = {
        "props": {
            "pageProps": {
                "menu": [
                    {"name": "Phở bò", "price": "45.000đ", "description": "Phở bò tái nạm"},
                    {"name": "Bún chả", "price": 40000, "image": "https://cdn.example.com/buncha.jpg"},
                ]
            }
        }
    }
    html = (
        "<html><head><title>Quán Phở Ngon | ShopeeFood</title>"
        f'<script id="__NEXT_DATA__">{__import__("json").dumps(payload)}</script>'
        "</head><body></body></html>"
    )

    class FakeResponse:
        text = html

        def raise_for_status(self):
            pass

    class FakeSession:
        def get(self, *a, **k):
            return FakeResponse()

    parsed = parse_shopeefood("https://shopeefood.vn/shop/pho-ngon", session=FakeSession())
    assert parsed["shop_name"] == "Quán Phở Ngon"
    names = {d["name"] for d in parsed["sections"][0]["dishes"]}
    assert names == {"Phở bò", "Bún chả"}
    pho = next(d for d in parsed["sections"][0]["dishes"] if d["name"] == "Phở bò")
    assert pho["price"] == 45000
    assert pho["desc"] == "Phở bò tái nạm"


def test_html_parse_graceful_failure_on_no_embedded_json():
    from agents.tiemquen_agent.agents.html_parse import parse_shopeefood

    class FakeResponse:
        text = "<html><head><title>Quán Test</title></head><body>hello</body></html>"

        def raise_for_status(self):
            pass

    class FakeSession:
        def get(self, *a, **k):
            return FakeResponse()

    with pytest.raises(ImportFallbackToOCR):
        parse_shopeefood("https://shopeefood.vn/shop/plain", session=FakeSession())


# -------------------------------------------------------------------------- text


def test_import_menu_text_heuristic_parse():
    text = "Cơm sườn nướng - 35.000đ\nTrà đá - 3.000đ\ndòng rác không parse được"
    envelope = import_agent.import_menu(text)
    validate_menu(envelope["menu"])
    assert envelope["menu"]["source"]["type"] == "manual"
    assert len(envelope["menu"]["menu"]["dishes"]) == 2
    assert any("không đọc được dòng" in w for w in envelope["warnings"])


def test_import_menu_text_no_parseable_lines_raises():
    with pytest.raises(ValueError):
        import_agent.import_menu("hoàn toàn không có giá nào ở đây")
