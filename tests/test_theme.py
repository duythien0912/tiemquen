"""Theme derivation: 4 seed hex -> palette, WCAG >= 4.5, deterministic."""

import pytest

from compose.theme import (
    MIN_CONTRAST,
    TEXT_PAIRS,
    ThemeError,
    contrast_ratio,
    derive_theme,
    validate_palette,
)

FIXTURE_SEEDS = ["#B7410E", "#F5E6C8", "#2F4A34", "#FFB84C"]  # demo_shop theme

PALETTE_KEYS = {
    "bg", "surface", "text", "text_muted", "text_faint",
    "accent", "accent_text", "success", "warn",
}


def test_contrast_ratio_known_values():
    assert contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert contrast_ratio("#FFFFFF", "#FFFFFF") == pytest.approx(1.0)
    # symmetric
    assert contrast_ratio("#B7410E", "#F5E6C8") == contrast_ratio("#F5E6C8", "#B7410E")


def test_derive_theme_full_palette_and_deterministic():
    p1 = derive_theme(FIXTURE_SEEDS)
    p2 = derive_theme(FIXTURE_SEEDS)
    assert p1 == p2  # pure function of seeds
    assert set(p1) == PALETTE_KEYS
    for v in p1.values():
        assert v.startswith("#") and len(v) == 7


@pytest.mark.parametrize(
    "seeds",
    [
        FIXTURE_SEEDS,
        ["#000000", "#000000", "#000000", "#000000"],  # degenerate: all black
        ["#FFFFFF", "#FFFFFF", "#FFFFFF", "#FFFFFF"],  # degenerate: all white
        ["#777777", "#787878", "#767676", "#757575"],  # mid-gray dead zone
        ["#FF0000", "#00FF00", "#0000FF", "#FFFF00"],  # loud primaries
        ["#101820", "#F2AA4C", "#997950", "#FEE715"],
    ],
)
def test_all_text_pairs_meet_wcag(seeds):
    palette = derive_theme(seeds)
    assert validate_palette(palette) == []
    for fg, bg in TEXT_PAIRS:
        assert contrast_ratio(palette[fg], palette[bg]) >= MIN_CONTRAST


def test_wrong_seed_count_rejected():
    with pytest.raises(ThemeError):
        derive_theme(["#FFFFFF"])


def test_bad_hex_rejected():
    with pytest.raises(ThemeError):
        derive_theme(["#GGGGGG", "#000000", "#000000", "#000000"])


def test_short_hex_accepted():
    palette = derive_theme(["#B41", "#FEC", "#243", "#FB4"])
    assert validate_palette(palette) == []
