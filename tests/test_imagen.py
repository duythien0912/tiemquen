"""agents/tiemquen_agent/imagen.py — mock hero generation, cache TTL, prompts."""

import os
import time

import pytest
from PIL import Image

from agents.tiemquen_agent import imagen
from compose.theme import derive_theme
from shared.menu_format import load_demo_fixture


@pytest.fixture(autouse=True)
def _mock_mode(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert imagen.is_mock_mode()


@pytest.fixture()
def fixture():
    return load_demo_fixture()


def test_mock_produces_valid_png_per_format(fixture, tmp_path):
    for fmt, spec in imagen.FORMAT_SPECS.items():
        result = imagen.generate_hero(fixture, fmt, media_dir=tmp_path)
        path = result["path"]
        assert path.is_file() and path.name == f"hero_{fmt}.png"
        assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        with Image.open(path) as img:
            assert img.size == spec["mock_size"]
        assert result["mode"] == "mock" and result["cached"] is False
        assert result["url"] == f"/media/com-tam-co-ba/hero_{fmt}.png"


def test_palette_is_usable_theme_seed(fixture, tmp_path):
    result = imagen.generate_hero(fixture, "a5", media_dir=tmp_path)
    palette = result["palette"]
    assert len(palette) == 4
    derive_theme(palette)  # must not raise — SPEC §6 contract with compose/theme
    # Mock mode echoes the shop's own seeds when present.
    assert palette == [c.upper() for c in fixture["shop"]["theme"]["seed_colors"]]


def test_palette_falls_back_when_shop_has_no_theme(fixture, tmp_path):
    del fixture["shop"]["theme"]
    result = imagen.generate_hero(fixture, "sticker", media_dir=tmp_path)
    assert result["palette"] == imagen.DEFAULT_SEED_COLORS
    derive_theme(result["palette"])


def test_cache_hit_within_ttl(fixture, tmp_path):
    first = imagen.generate_hero(fixture, "a5", media_dir=tmp_path)
    again = imagen.generate_hero(fixture, "a5", media_dir=tmp_path)
    assert again["cached"] is True and again["mode"] == "cache"
    assert again["palette"] == first["palette"]  # persisted next to the PNG
    forced = imagen.generate_hero(fixture, "a5", media_dir=tmp_path, force=True)
    assert forced["cached"] is False


def test_expired_cache_regenerates(fixture, tmp_path):
    first = imagen.generate_hero(fixture, "a5", media_dir=tmp_path)
    old = time.time() - imagen.DEFAULT_TTL_SECONDS - 10
    os.utime(first["path"], (old, old))
    again = imagen.generate_hero(fixture, "a5", media_dir=tmp_path)
    assert again["cached"] is False


def test_cleanup_expired_removes_only_stale_hero_files(fixture, tmp_path):
    fresh = imagen.generate_hero(fixture, "a5", media_dir=tmp_path)
    stale = imagen.generate_hero(fixture, "a4", media_dir=tmp_path)
    old = time.time() - imagen.DEFAULT_TTL_SECONDS - 10
    for suffix in (".png", ".palette.json"):
        p = stale["path"].with_name(f"hero_a4{suffix}")
        os.utime(p, (old, old))
    # A rehosted dish image must never be TTL-cleaned, even when old.
    dish_img = fresh["path"].parent / "dish_suon.jpg"
    dish_img.write_bytes(b"jpeg")
    os.utime(dish_img, (old, old))

    removed = imagen.cleanup_expired(tmp_path)
    assert stale["path"] in removed and len(removed) == 2
    assert fresh["path"].is_file() and dish_img.is_file()
    assert not stale["path"].exists()


def test_unknown_format_raises(fixture, tmp_path):
    with pytest.raises(imagen.ImagenError):
        imagen.generate_hero(fixture, "letter", media_dir=tmp_path)


def test_prompt_repeats_hard_constraints_at_end(fixture):
    prompt = imagen.build_prompt(fixture, "a5")
    assert fixture["shop"]["name"] in prompt
    # SPEC §6: hard constraints AFTER the creative brief, running to the END
    # of the prompt (image models forget mid-prompt context).
    assert prompt.index("RÀNG BUỘC CỨNG") > prompt.index(fixture["shop"]["name"])
    tail = prompt[prompt.index("RÀNG BUỘC CỨNG") :]
    assert "QR" in tail and "palette" in tail  # safe-zone + palette asks in the block
    assert prompt.rstrip().endswith(").")  # ends inside the constraints block
    # Sticker prompt asks square, a5 asks portrait.
    assert "3:4" in prompt
    assert "1:1" in imagen.build_prompt(fixture, "sticker")
