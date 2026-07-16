"""Theme derivation — 4 seed hex colors -> full palette (ENGINE-SPEC §6).

Imagen trả 4 màu seed / seller tự chọn; PHẦN CÒN LẠI derive bằng code, thuần
deterministic (không LLM, không random). Mọi cặp chữ/nền được ép đạt WCAG
contrast >= 4.5 bằng cách kéo sáng/tối từng bước.

Palette keys:
    bg, surface           — nền trang / nền card
    text, text_muted, text_faint — 3 tier chữ (đều >= 4.5 trên bg VÀ surface)
    accent, accent_text   — màu nhấn (nút CTA) + chữ trên nền accent
    success, warn         — trạng thái (dùng làm chữ/badge trên bg)
"""

from __future__ import annotations

MIN_CONTRAST = 4.5

RGB = tuple[int, int, int]


class ThemeError(ValueError):
    pass


# ------------------------------------------------------------------ hex helpers


def _parse_hex(color: str) -> RGB:
    s = color.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6:
        raise ThemeError(f"invalid hex color: {color!r}")
    try:
        return tuple(int(s[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError as e:
        raise ThemeError(f"invalid hex color: {color!r}") from e


def _to_hex(rgb: RGB) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def _clamp(v: float) -> int:
    return max(0, min(255, round(v)))


def _mix(a: RGB, b: RGB, t: float) -> RGB:
    """Linear blend a->b, t in [0,1]."""
    return tuple(_clamp(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


# --------------------------------------------------------------- WCAG contrast


def _channel_lin(c: int) -> float:
    v = c / 255.0
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb: RGB) -> float:
    r, g, b = (_channel_lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(c1: str | RGB, c2: str | RGB) -> float:
    """WCAG 2.x contrast ratio between two colors (1..21)."""
    a = _parse_hex(c1) if isinstance(c1, str) else c1
    b = _parse_hex(c2) if isinstance(c2, str) else c2
    l1, l2 = relative_luminance(a), relative_luminance(b)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def _saturation(rgb: RGB) -> float:
    mx, mn = max(rgb), min(rgb)
    if mx == 0:
        return 0.0
    return (mx - mn) / mx


_BLACK: RGB = (0, 0, 0)
_WHITE: RGB = (255, 255, 255)


def _ensure_contrast(fg: RGB, bg: RGB, ratio: float = MIN_CONTRAST) -> RGB:
    """Nudge `fg` toward black or white (away from bg) until contrast >= ratio.

    Deterministic: picks the direction with more headroom, steps 5% at a time.
    Falls back to pure black/white (contrast vs anything is >= 4.5 unless bg
    is mid-gray — then the opposite pole is used).
    """
    if contrast_ratio(fg, bg) >= ratio:
        return fg
    toward = _BLACK if relative_luminance(bg) >= 0.35 else _WHITE
    cur = fg
    for _ in range(20):
        cur = _mix(cur, toward, 0.15)
        if contrast_ratio(cur, bg) >= ratio:
            return cur
    # Extreme: pick whichever pole clears the bar.
    return toward if contrast_ratio(toward, bg) >= ratio else (
        _WHITE if toward == _BLACK else _BLACK
    )


# -------------------------------------------------------------------- derive


def derive_theme(seed_colors: list[str]) -> dict[str, str]:
    """4 seed hex -> full palette dict (hex strings). Pure function of input."""
    if len(seed_colors) != 4:
        raise ThemeError(f"expected exactly 4 seed colors, got {len(seed_colors)}")
    seeds = [_parse_hex(c) for c in seed_colors]

    # bg = lightest seed, lightened toward white so text has headroom.
    by_lum = sorted(range(4), key=lambda i: relative_luminance(seeds[i]))
    bg_seed = seeds[by_lum[-1]]
    bg = _mix(bg_seed, _WHITE, 0.65)
    surface = _mix(bg_seed, _WHITE, 0.82)

    # text = darkest seed, forced to >= 4.5 on BOTH bg and surface.
    text = seeds[by_lum[0]]
    text = _ensure_contrast(_ensure_contrast(text, bg), surface)
    text_muted = _ensure_contrast(_ensure_contrast(_mix(text, bg, 0.30), bg), surface)
    text_faint = _ensure_contrast(_ensure_contrast(_mix(text, bg, 0.45), bg), surface)

    # accent = most saturated of the two middle seeds (not bg, not text base).
    mid = [seeds[by_lum[1]], seeds[by_lum[2]]]
    accent = max(mid, key=lambda c: (_saturation(c), -relative_luminance(c)))
    # accent must also work as text on bg (price highlights, links).
    accent = _ensure_contrast(accent, bg)
    accent_text = _WHITE if contrast_ratio(_WHITE, accent) >= contrast_ratio(_BLACK, accent) else _BLACK
    accent_text = _ensure_contrast(accent_text, accent)

    # Status colors: fixed hues tinted 12% toward the accent, contrast-forced.
    success = _ensure_contrast(_mix((27, 122, 60), accent, 0.12), bg)
    warn = _ensure_contrast(_mix((180, 83, 9), accent, 0.12), bg)

    return {
        "bg": _to_hex(bg),
        "surface": _to_hex(surface),
        "text": _to_hex(text),
        "text_muted": _to_hex(text_muted),
        "text_faint": _to_hex(text_faint),
        "accent": _to_hex(accent),
        "accent_text": _to_hex(accent_text),
        "success": _to_hex(success),
        "warn": _to_hex(warn),
    }


#: Text/background pairs that must clear WCAG 4.5 (used by tests + validate).
TEXT_PAIRS: tuple[tuple[str, str], ...] = (
    ("text", "bg"),
    ("text", "surface"),
    ("text_muted", "bg"),
    ("text_muted", "surface"),
    ("text_faint", "bg"),
    ("text_faint", "surface"),
    ("accent", "bg"),
    ("accent_text", "accent"),
    ("success", "bg"),
    ("warn", "bg"),
)


def validate_palette(palette: dict[str, str]) -> list[str]:
    """Return list of failing pairs ([] = all text pairs >= 4.5)."""
    failures = []
    for fg, bg in TEXT_PAIRS:
        r = contrast_ratio(palette[fg], palette[bg])
        if r < MIN_CONTRAST:
            failures.append(f"{fg} on {bg}: {r:.2f} < {MIN_CONTRAST}")
    return failures
