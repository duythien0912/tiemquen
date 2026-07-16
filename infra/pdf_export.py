"""Flyer PDF export — print-ready per format (ARCH §2 "3 format vật lý").

Layout mỗi format (reportlab, đơn vị mm, ảnh 300dpi-capable):
  - hero image full-bleed (từ agents/tiemquen_agent/imagen.py, mock hoặc real)
  - tên tiệm + tagline trên nền panel mờ phía trên
  - 3 món best-seller kèm giá (giá trực tiếp — rẻ hơn sàn, ARCH §3.1)
  - CTA lớn "THÈM? QUÉT."
  - QR batch (URL /t/{slug}?b={batch_id}) góc DƯỚI BÊN PHẢI trong safe zone
    mà prompt imagen đã chừa sẵn — nền trắng, quiet zone chuẩn quét.

Formats: a5 148×210 (nhét túi đơn sàn), a4 210×297 (poster pantry),
sticker 100×100 (tủ lạnh/cạnh màn hình).

`export_flyers(shop_doc, batch_ids)` -> data/media/<slug>/flyer_<fmt>.pdf —
nằm dưới mount /media nên seller PWA tải thẳng qua static URL.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from reportlab.lib.colors import Color, black, white
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from agents.tiemquen_agent import imagen
from infra.qr_batch import qr_url

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEDIA_DIR = REPO_ROOT / "data" / "media"

#: Kích thước trang theo mm (w, h) — ARCH §2.
FORMAT_SIZES_MM: dict[str, tuple[float, float]] = {
    "a5": (148, 210),
    "a4": (210, 297),
    "sticker": (100, 100),
}

CTA_TEXT = "THÈM? QUÉT."

#: Public base URL in lên QR giấy — QR tĩnh phải absolute, giấy không có origin.
DEFAULT_BASE_URL = "https://tiemquen.com"

#: TTF candidates có glyph tiếng Việt (Helvetica built-in thì KHÔNG — mất dấu).
_VN_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
)
_VN_BOLD_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
)

_registered: dict[str, str] = {}


class PDFExportError(Exception):
    pass


def _register_font(logical: str, candidates: tuple[str, ...], fallback: str) -> str:
    """Register the first available Vietnamese-capable TTF under `logical`.
    Falls back to a built-in font (diacritics degrade but export never fails)."""
    if logical in _registered:
        return _registered[logical]
    for path in candidates:
        if Path(path).is_file():
            try:
                pdfmetrics.registerFont(TTFont(logical, path))
                _registered[logical] = logical
                return logical
            except Exception:
                continue
    _registered[logical] = fallback
    return fallback


def _fonts() -> tuple[str, str]:
    regular = _register_font("TQSans", _VN_FONT_CANDIDATES, "Helvetica")
    bold = _register_font("TQSans-Bold", _VN_BOLD_CANDIDATES, regular if regular != "Helvetica" else "Helvetica-Bold")
    return regular, bold


# ------------------------------------------------------------------- helpers


def _fmt_price(price: int) -> str:
    return f"{int(price):,}đ".replace(",", ".")


def best_sellers(menu: dict[str, Any], n: int = 3) -> list[dict[str, Any]]:
    """3 món 'best-seller' cho tờ rơi: theo thứ tự section/menu, bỏ món ẩn/
    hết; ưu tiên món có platform_price (có giá sàn để so = món chạy trên sàn)."""
    picks: list[dict[str, Any]] = []
    seen: set[str] = set()
    dishes = menu["dishes"]
    ordered_ids = [
        dish_id
        for section in menu.get("sections", [])
        for dish_id in section.get("items", [])
        if dish_id in dishes
    ] or list(dishes)
    for prefer_platform in (True, False):
        for dish_id in ordered_ids:
            dish = dishes[dish_id]
            if dish_id in seen or dish.get("hidden") or dish.get("sold_out"):
                continue
            if prefer_platform and not dish.get("platform_price"):
                continue
            picks.append(dish)
            seen.add(dish_id)
            if len(picks) >= n:
                return picks
    return picks


def _qr_image(url: str) -> ImageReader:
    import qrcode

    qr = qrcode.QRCode(border=2)  # quiet zone in the PNG itself
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return ImageReader(buf)


# -------------------------------------------------------------------- export


def export_flyer(
    shop_doc: dict[str, Any],
    fmt: str,
    batch_id: str,
    media_dir: Path | None = None,
    base_url: str = DEFAULT_BASE_URL,
) -> Path:
    """Render 1 flyer PDF -> data/media/<slug>/flyer_<fmt>.pdf."""
    if fmt not in FORMAT_SIZES_MM:
        raise PDFExportError(f"format {fmt!r} không hợp lệ; chọn {sorted(FORMAT_SIZES_MM)}")
    shop = shop_doc["shop"]
    slug = shop["slug"]
    media_base = Path(media_dir or DEFAULT_MEDIA_DIR)
    out_path = media_base / slug / f"flyer_{fmt}.pdf"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    hero = imagen.generate_hero(shop_doc, fmt, media_dir=media_base)
    regular, bold = _fonts()

    w_mm, h_mm = FORMAT_SIZES_MM[fmt]
    W, H = w_mm * mm, h_mm * mm
    sticker = fmt == "sticker"
    c = canvas.Canvas(str(out_path), pagesize=(W, H))
    c.setTitle(f"Tiệm Quen — tờ rơi {fmt.upper()} — {shop['name']}")

    # 1. Hero full-bleed (stretch to page — imagen ratio is near-format already).
    c.drawImage(
        ImageReader(str(hero["path"])), 0, 0, width=W, height=H,
        preserveAspectRatio=False, mask="auto",
    )

    margin = 8 * mm if not sticker else 5 * mm

    # 2. Shop name + tagline on a translucent panel up top.
    name_size = 30 if fmt == "a4" else (24 if fmt == "a5" else 16)
    panel_h = (26 if not sticker else 18) * mm
    c.setFillColor(Color(0, 0, 0, alpha=0.45))
    c.rect(0, H - panel_h, W, panel_h, stroke=0, fill=1)
    c.setFillColor(white)
    c.setFont(bold, name_size)
    c.drawString(margin, H - panel_h + (12 if not sticker else 9) * mm, shop["name"])
    if shop.get("tagline"):
        c.setFont(regular, name_size * 0.42)
        c.drawString(margin, H - panel_h + (5 if not sticker else 3.5) * mm, shop["tagline"])

    # 3. QR batch — bottom-right safe zone (white card + quiet zone).
    qr_side = (0.30 * W) if not sticker else (0.34 * W)
    qr_x, qr_y = W - margin - qr_side, margin
    pad = 1.5 * mm
    c.setFillColor(white)
    c.roundRect(qr_x - pad, qr_y - pad, qr_side + 2 * pad, qr_side + 2 * pad, 2 * mm, stroke=0, fill=1)
    c.drawImage(_qr_image(qr_url(slug, batch_id, base_url)), qr_x, qr_y, qr_side, qr_side)
    c.setFillColor(black)
    c.setFont(regular, 6 if sticker else 7)
    c.drawCentredString(qr_x + qr_side / 2, qr_y + 1.2 * mm, batch_id)

    # 4. Big CTA "THÈM? QUÉT." next to the QR (points the eye at it).
    cta_size = 34 if fmt == "a4" else (26 if fmt == "a5" else 15)
    c.setFont(bold, cta_size)
    c.setFillColor(white)
    cta_y = margin + qr_side * 0.45
    c.drawString(margin, cta_y, CTA_TEXT)
    c.setFont(regular, cta_size * 0.34)
    c.drawString(margin, cta_y - 6 * mm, "Quét mã — đặt 3 chạm, không cần app")

    # 5. 3 best-sellers + giá (panel mờ giữa/dưới, trên CTA).
    dishes = best_sellers(shop_doc["menu"])
    if dishes and not sticker:
        line_h = 9 * mm if fmt == "a4" else 7.5 * mm
        list_h = line_h * len(dishes) + 6 * mm
        list_y = cta_y + 14 * mm
        c.setFillColor(Color(0, 0, 0, alpha=0.45))
        c.rect(0, list_y - 3 * mm, W * 0.66, list_h, stroke=0, fill=1)
        c.setFillColor(white)
        dish_size = 13 if fmt == "a4" else 11
        for i, dish in enumerate(reversed(dishes)):
            y = list_y + i * line_h
            c.setFont(regular, dish_size)
            c.drawString(margin, y, dish["name"])
            c.setFont(bold, dish_size)
            c.drawRightString(W * 0.66 - 4 * mm, y, _fmt_price(dish["price"]))

    c.showPage()
    c.save()
    return out_path


def export_flyers(
    shop_doc: dict[str, Any],
    batch_ids: dict[str, str],
    media_dir: Path | None = None,
    base_url: str = DEFAULT_BASE_URL,
) -> dict[str, Path]:
    """Bộ tờ rơi: {format: batch_id} -> {format: pdf_path}. Mỗi format một
    batch riêng — chính là flyer analytics (ARCH §2: biết tờ dán đâu ra đơn)."""
    if not batch_ids:
        raise PDFExportError("cần ít nhất 1 {format: batch_id}")
    return {
        fmt: export_flyer(shop_doc, fmt, batch_id, media_dir=media_dir, base_url=base_url)
        for fmt, batch_id in batch_ids.items()
    }


__all__ = [
    "CTA_TEXT", "DEFAULT_BASE_URL", "FORMAT_SIZES_MM", "PDFExportError",
    "best_sellers", "export_flyer", "export_flyers",
]
