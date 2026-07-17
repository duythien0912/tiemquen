"""Imagen service — hero/flyer background + 4-seed palette (ENGINE-SPEC §6).

REAL mode (GEMINI_API_KEY set): 1 call `generate_content` multimodal,
`response_modalities=["TEXT","IMAGE"]` — ảnh nền + palette JSON (4 seed hex)
về CÙNG một response. Sanitize pre-pass bằng model rẻ (flash-lite) lọc prompt
trước call đắt; hard constraints lặp lại Ở CUỐI prompt (model ảnh quên context
giữa prompt dài); retry đúng 1 lần nếu trả text không pixel.

MOCK mode (không có key — mặc định dev/test/CI): Pillow vẽ placeholder
(gradient 2 seed color + noise + tên tiệm + ô safe-zone QR) để TOÀN BỘ đường
flyer (imagen -> pdf_export -> seller PWA) chạy offline, zero network.

Cache: PNG + palette JSON ra `data/media/<slug>/hero_<fmt>.png` (static URL
qua mount /media) với TTL — `cleanup_expired()` dọn file hết hạn.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from compose.theme import derive_theme

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MEDIA_DIR = REPO_ROOT / "data" / "media"

GEMINI_IMAGE_MODEL = "gemini-2.5-flash-image"
GEMINI_SANITIZE_MODEL = "gemini-flash-lite-latest"

#: Cache TTL: hero đắt tiền nhưng không bất biến (menu/mùa đổi) — 7 ngày.
DEFAULT_TTL_SECONDS = 7 * 24 * 3600

#: Fallback seeds khi model không trả palette hợp lệ và shop chưa có theme.
DEFAULT_SEED_COLORS = ["#B7410E", "#F5E6C8", "#2F4A34", "#FFB84C"]

#: Per-format spec: Gemini aspect ratio + mock render size (px).
#: A5/A4 đều portrait ~1:1.414 -> "3:4" là ratio portrait gần nhất Gemini hỗ
#: trợ (PDF full-bleed crop phần dư); sticker vuông = "1:1".
FORMAT_SPECS: dict[str, dict[str, Any]] = {
    "a5": {"aspect_ratio": "3:4", "mock_size": (1240, 1754)},
    "a4": {"aspect_ratio": "3:4", "mock_size": (1240, 1754)},
    "sticker": {"aspect_ratio": "1:1", "mock_size": (1000, 1000)},
}

_HEX_RE = re.compile(r"#[0-9a-fA-F]{6}")


class ImagenError(Exception):
    pass


def is_mock_mode() -> bool:
    """No GEMINI_API_KEY -> Pillow placeholder, zero network (SPEC §10)."""
    return not os.environ.get("GEMINI_API_KEY")


# -------------------------------------------------------------------- prompts


def _hard_constraints(fmt: str) -> str:
    spec = FORMAT_SPECS[fmt]
    return (
        "RÀNG BUỘC CỨNG (tuân thủ tuyệt đối, lặp lại vì quan trọng):\n"
        f"- Ảnh nền tờ rơi, tỷ lệ {spec['aspect_ratio']}"
        f" ({'vuông' if fmt == 'sticker' else 'dọc/portrait'}).\n"
        "- KHÔNG chữ, KHÔNG số, KHÔNG logo, KHÔNG watermark trong ảnh — mọi"
        " text (tên quán, giá, CTA 'THÈM? QUÉT.') được in đè bằng code sau.\n"
        "- Góc DƯỚI BÊN PHẢI: vùng trống sáng, phẳng, đồng nhất (~30% chiều"
        " rộng) làm safe-zone đặt mã QR — không chi tiết, không hoạ tiết.\n"
        "- Phần TRÊN ảnh thoáng, ít chi tiết để đặt tên quán + 3 món best-seller.\n"
        "- Không người thật, không thương hiệu/nhãn hàng nhận diện được.\n"
        "- Kèm theo ảnh, trả THÊM một đoạn text JSON đúng dạng"
        ' {"palette": ["#RRGGBB", "#RRGGBB", "#RRGGBB", "#RRGGBB"]} — 4 màu'
        " seed lấy từ chính ảnh, tương phản đủ làm theme web (1 màu nền sáng,"
        " 1 màu chữ tối, 2 màu nhấn)."
    )


def build_prompt(shop_doc: dict[str, Any], fmt: str) -> str:
    shop = shop_doc["shop"]
    dishes = list(shop_doc.get("menu", {}).get("dishes", {}).values())
    dish_names = ", ".join(d["name"] for d in dishes[:5]) or "món ăn Việt Nam"
    usage = {
        "a5": "tờ rơi A5 nhét túi giao đồ ăn",
        "a4": "poster A4 dán pantry văn phòng",
        "sticker": "sticker vuông dán tủ lạnh",
    }[fmt]
    return (
        f"Vẽ ảnh nền {usage} cho quán ăn Việt Nam tên \"{shop['name']}\""
        f" ({shop.get('tagline', '')}). Món tiêu biểu: {dish_names}."
        " Phong cách: ấm áp, ngon mắt, chụp món ăn kiểu editorial, ánh sáng"
        " tự nhiên, màu đất nung + xanh lá — nhìn là thèm.\n\n"
        + _hard_constraints(fmt)  # hard constraints REPEATED at the END (SPEC §6)
    )


def _sanitize_prompt(prompt: str) -> str:
    """Pre-pass qua model rẻ: lọc tên riêng/nhãn hàng/nội dung không an toàn
    khỏi prompt trước call ảnh đắt (SPEC §6). Best-effort — lỗi thì giữ nguyên."""
    try:
        from google import genai

        client = genai.Client()
        resp = client.models.generate_content(
            model=GEMINI_SANITIZE_MODEL,
            contents=(
                "Viết lại prompt sinh ảnh sau cho an toàn: bỏ tên thương hiệu"
                " bên thứ ba, tên người thật, nội dung nhạy cảm; GIỮ NGUYÊN"
                " các dòng 'RÀNG BUỘC CỨNG'. Chỉ trả prompt đã lọc.\n\n"
                + prompt
            ),
        )
        text = (resp.text or "").strip()
        # Sanity: the cheap model must not have eaten the hard constraints.
        return text if text and "RÀNG BUỘC CỨNG" in text else prompt
    except Exception:
        return prompt


# ------------------------------------------------------------------ real mode


def _extract_image_and_palette(response: Any) -> tuple[bytes | None, list[str] | None]:
    image_bytes: bytes | None = None
    palette: list[str] | None = None
    for candidate in getattr(response, "candidates", None) or []:
        for part in getattr(candidate.content, "parts", None) or []:
            inline = getattr(part, "inline_data", None)
            if inline is not None and getattr(inline, "data", None) and image_bytes is None:
                image_bytes = inline.data
            text = getattr(part, "text", None)
            if text and palette is None:
                found = _HEX_RE.findall(text)
                if len(found) >= 4:
                    palette = [c.upper() for c in found[:4]]
    return image_bytes, palette


def _generate_real(shop_doc: dict[str, Any], fmt: str) -> tuple[bytes, list[str] | None]:
    from google import genai
    from google.genai import types as gtypes

    client = genai.Client()
    prompt = _sanitize_prompt(build_prompt(shop_doc, fmt))

    config = gtypes.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"])
    try:  # aspect ratio per format — older SDKs lack ImageConfig; prompt còn ratio
        config = gtypes.GenerateContentConfig(
            response_modalities=["TEXT", "IMAGE"],
            image_config=gtypes.ImageConfig(aspect_ratio=FORMAT_SPECS[fmt]["aspect_ratio"]),
        )
    except (AttributeError, TypeError):
        pass

    contents: list[Any] = [prompt]
    for attempt in range(2):  # 1 retry nếu trả text không pixel (SPEC §6)
        response = client.models.generate_content(
            model=GEMINI_IMAGE_MODEL, contents=contents, config=config
        )
        image_bytes, palette = _extract_image_and_palette(response)
        if image_bytes:
            return image_bytes, palette
        contents = [
            prompt,
            "Lần trước bạn chỉ trả text, KHÔNG có ảnh. Trả đúng 1 ảnh"
            " (inline image) + đoạn JSON palette như yêu cầu.",
        ]
    raise ImagenError(f"model không trả pixel nào sau 2 lần cho format {fmt!r}")


# ------------------------------------------------------------------ mock mode


def _parse_hex(color: str) -> tuple[int, int, int]:
    s = color.lstrip("#")
    return tuple(int(s[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _generate_mock(shop_doc: dict[str, Any], fmt: str) -> tuple[bytes, list[str]]:
    """Pillow placeholder: gradient 2 seed + noise (để PNG/PDF có size thật).
    KHÔNG vẽ chữ/ô safe-zone lên mock — pdf_export in đè toàn bộ text + thẻ QR
    trắng của nó, mọi watermark mock đều lộ ra thành 'chữ ma' trên flyer thật
    (đã dính: tên tiệm mờ + '[mock hero]' + ô kem lệch sau thẻ QR)."""
    import io

    from PIL import Image

    seeds = (
        shop_doc.get("shop", {}).get("theme", {}).get("seed_colors")
        or DEFAULT_SEED_COLORS
    )
    w, h = FORMAT_SPECS[fmt]["mock_size"]
    top, bottom = _parse_hex(seeds[0]), _parse_hex(seeds[2])

    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):  # vertical gradient seed[0] -> seed[2]
        t = y / max(h - 1, 1)
        row = tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        for x in range(w):
            px[x, y] = row
    # Noise overlay: makes the PNG incompressible enough to behave like a real
    # photo downstream (PDF size checks, transfer timing) without network.
    noise = Image.effect_noise((w, h), 24).convert("RGB")
    img = Image.blend(img, noise, 0.12)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), list(seeds)


# --------------------------------------------------------------- cache + API


def hero_paths(shop_slug: str, fmt: str, media_dir: Path | None = None) -> tuple[Path, Path]:
    base = Path(media_dir or DEFAULT_MEDIA_DIR) / shop_slug
    return base / f"hero_{fmt}.png", base / f"hero_{fmt}.palette.json"


def _safe_palette(palette: list[str] | None, shop_doc: dict[str, Any]) -> list[str]:
    """Contrast-check qua derive_theme (SPEC §6) — palette hỏng thì rơi về
    seed của shop rồi về default, không bao giờ trả palette không dùng được."""
    for cand in (palette, shop_doc.get("shop", {}).get("theme", {}).get("seed_colors")):
        if cand and len(cand) == 4:
            try:
                derive_theme(list(cand))  # raises ThemeError on bad hex
                return [c.upper() for c in cand]
            except Exception:
                continue
    return list(DEFAULT_SEED_COLORS)


def generate_hero(
    shop_doc: dict[str, Any],
    fmt: str,
    media_dir: Path | None = None,
    force: bool = False,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> dict[str, Any]:
    """Hero/flyer background cho 1 format -> cached PNG + palette.

    Returns {"path", "url", "palette", "cached", "mode"}. Cache hit = PNG còn
    trong TTL (trừ khi `force`); palette persist cạnh PNG nên cache hit vẫn
    trả đủ palette.
    """
    if fmt not in FORMAT_SPECS:
        raise ImagenError(f"format {fmt!r} không hợp lệ; chọn một trong {sorted(FORMAT_SPECS)}")
    slug = shop_doc["shop"]["slug"]
    png_path, palette_path = hero_paths(slug, fmt, media_dir)

    if not force and png_path.is_file():
        age = time.time() - png_path.stat().st_mtime
        if age < ttl_seconds:
            palette = None
            if palette_path.is_file():
                try:
                    palette = json.loads(palette_path.read_text())["palette"]
                except (ValueError, KeyError):
                    palette = None
            return {
                "path": png_path,
                "url": f"/media/{slug}/{png_path.name}",
                "palette": _safe_palette(palette, shop_doc),
                "cached": True,
                "mode": "cache",
            }

    if is_mock_mode():
        image_bytes, palette = _generate_mock(shop_doc, fmt)
        mode = "mock"
    else:
        image_bytes, palette = _generate_real(shop_doc, fmt)
        mode = "real"

    safe = _safe_palette(palette, shop_doc)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    png_path.write_bytes(image_bytes)
    palette_path.write_text(json.dumps({"palette": safe}, ensure_ascii=False))
    return {
        "path": png_path,
        "url": f"/media/{slug}/{png_path.name}",
        "palette": safe,
        "cached": False,
        "mode": mode,
    }


def cleanup_expired(
    media_dir: Path | None = None, ttl_seconds: int = DEFAULT_TTL_SECONDS
) -> list[Path]:
    """TTL cleanup (SPEC §6): xoá hero PNG/palette hết hạn dưới media_dir.
    CHỈ đụng file `hero_*` do module này sinh — ảnh món rehost (infra/media.py)
    và flyer PDF không có TTL. Returns list các file đã xoá."""
    base = Path(media_dir or DEFAULT_MEDIA_DIR)
    if not base.is_dir():
        return []
    now = time.time()
    removed: list[Path] = []
    for pattern in ("*/hero_*.png", "*/hero_*.palette.json"):
        for path in base.glob(pattern):
            if now - path.stat().st_mtime >= ttl_seconds:
                path.unlink()
                removed.append(path)
    return removed


__all__ = [
    "DEFAULT_SEED_COLORS", "DEFAULT_TTL_SECONDS", "FORMAT_SPECS", "ImagenError",
    "build_prompt", "cleanup_expired", "generate_hero", "hero_paths", "is_mock_mode",
]
