"""Import agent (ENGINE-SPEC §5, ARCH §3.1) — entry point `import_menu(source)`.

`source` is one of:
  - screenshot path(s): str/Path (or list thereof) ending .png/.jpg/.jpeg/.webp
    -> OCR = ĐƯỜNG CHÍNH. REAL mode: google-genai multimodal (image parts +
       prompt forcing `menu_tools` calls) via `toolable.Toolable`. MOCK mode
       (no GEMINI_API_KEY): replay `data/fixtures/grab_screenshot_toolcalls.json`
       through the SAME assembly path (`toolable.Toolable.replay`).
  - URL: str starting with http(s):// -> best-effort ShopeeFood HTML parse
    (`html_parse.py`, no LLM). Fails -> `ImportFallbackToOCR` propagates to
    the caller (server /import responds telling the seller to screenshot
    instead — ARCH §4.5, import chết không kéo sập tiệm đã publish).
  - anything else: raw pasted menu text -> REAL mode reuses the same tool-
    calling loop (text-only contents); MOCK mode has no dedicated fixture for
    text, so it degrades to a small line-heuristic parser (no model needed).

Every branch converges on the same MenuAssembler.envelope():
`{"menu": <chuẩn §4>, "warnings": [...], "confidence": 0-100}`.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Sequence

from agents.tiemquen_agent.agents.html_parse import ImportFallbackToOCR, parse_shopeefood
from agents.tiemquen_agent.tools.menu_tools import MenuAssembler
from agents.tiemquen_agent.toolable import Toolable

REPO_ROOT = Path(__file__).resolve().parents[3]
GRAB_FIXTURE_PATH = REPO_ROOT / "data" / "fixtures" / "grab_screenshot_toolcalls.json"

_URL_RE = re.compile(r"^https?://", re.IGNORECASE)
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})
_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

_OCR_PROMPT = (
    "Bạn là OCR menu quán ăn Việt Nam. Đọc TOÀN BỘ ảnh chụp màn hình menu "
    "(Grab/ShopeeFood) và gọi CÁC TOOL để ghi lại: set_shop_info (đúng 1 lần), "
    "add_section cho mỗi nhóm món theo đúng thứ tự trên ảnh, add_dish cho MỖI "
    "món đọc được (giá VND, số nguyên, KHÔNG lấy đơn vị nghìn), rồi finish với "
    "confidence 0-100. Giữ nguyên dấu tiếng Việt. Giá mờ/che khuất -> đọc tạm "
    "và ghi cảnh báo vào warnings của finish."
)

_TEXT_PROMPT = (
    "Bạn nhận một đoạn text menu quán ăn Việt Nam (khách paste tay, không phải "
    "ảnh). Gọi CÁC TOOL để ghi lại menu: set_shop_info, add_section, add_dish "
    "cho mỗi món, rồi finish với confidence 0-100."
)


def is_mock_mode() -> bool:
    """No GEMINI_API_KEY -> mock (SPEC §10): screenshot replays the recorded
    fixture, raw text falls back to a line-heuristic parser. Zero network."""
    return not os.environ.get("GEMINI_API_KEY")


def _is_screenshot_source(source: Any) -> bool:
    if isinstance(source, (list, tuple)):
        return bool(source) and all(_is_screenshot_source(s) for s in source)
    if isinstance(source, Path):
        return True
    if isinstance(source, str):
        return not _URL_RE.match(source) and Path(source).suffix.lower() in _IMAGE_SUFFIXES
    return False


def classify_source(source: Any) -> str:
    """'screenshot' | 'url' | 'text' — dispatch key for `import_menu`."""
    if _is_screenshot_source(source):
        return "screenshot"
    if isinstance(source, str) and _URL_RE.match(source):
        return "url"
    return "text"


# ------------------------------------------------------------------ screenshot


def _load_fixture_tool_calls() -> list[dict[str, Any]]:
    with GRAB_FIXTURE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)["tool_calls"]


def import_from_fixture(name: str) -> dict[str, Any]:
    """Dev/demo helper: replay ANY named fixture's recorded tool-calls
    (`data/fixtures/<name>.json`, same shape as `grab_screenshot_toolcalls.json`)
    through the same assembly path — regardless of GEMINI_API_KEY. Backs the
    `/api/import` endpoint's `{"fixture": "<name>"}` form and lets
    scripts/e2e_smoke.py exercise the import -> review -> patch flow without
    needing real image bytes on disk.
    """
    path = REPO_ROOT / "data" / "fixtures" / f"{name}.json"
    if not path.is_file():
        raise FileNotFoundError(f"fixture không tồn tại: {path}")
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    assembler = MenuAssembler(source_type=payload.get("source_type", "ocr_screenshot"))
    tool = Toolable(assembler.tools())
    tool.replay(payload["tool_calls"], message=payload.get("message", ""))
    return assembler.envelope()


def _image_part(path: Path) -> Any:
    from google.genai import types as gtypes  # lazy import: real mode only

    mime = _MIME_BY_SUFFIX.get(path.suffix.lower(), "image/png")
    return gtypes.Part.from_bytes(data=path.read_bytes(), mime_type=mime)


def _import_screenshot(paths: Sequence[str | Path]) -> dict[str, Any]:
    assembler = MenuAssembler(source_type="ocr_screenshot")
    tool = Toolable(assembler.tools())

    if is_mock_mode():
        tool.replay(_load_fixture_tool_calls())
    else:
        contents: list[Any] = [_OCR_PROMPT] + [_image_part(Path(p)) for p in paths]
        tool.run(contents)

    return assembler.envelope()


# ------------------------------------------------------------------------ url


def _import_url(url: str) -> dict[str, Any]:
    """ShopeeFood best-effort HTML parse (ARCH §3.1). No LLM — pure scrape.

    Propagates `ImportFallbackToOCR` on failure so the caller can tell the
    seller to screenshot instead of silently erroring (ARCH §4.5).
    """
    parsed = parse_shopeefood(url)  # raises ImportFallbackToOCR on any failure

    assembler = MenuAssembler(source_type="html_parse", source_url=url)
    assembler.set_shop_info(name=parsed["shop_name"])
    for section in parsed["sections"]:
        sid = re.sub(r"[^a-z0-9]+", "_", section["title"].lower()).strip("_") or "menu"
        assembler.add_section(id=sid, title=section["title"])
        for dish in section["dishes"]:
            assembler.add_dish(
                section_id=sid,
                name=dish["name"],
                price=dish["price"],
                desc=dish.get("desc"),
                image_ref=dish.get("image_url"),
            )
    # HTML parse gives clean structured data but no seller review yet — mid
    # confidence, same as a decent OCR read (ARCH §3.1 review step still runs).
    assembler.finish(confidence=60)
    return assembler.envelope()


# ----------------------------------------------------------------------- text

_TEXT_LINE_RE = re.compile(
    r"^\s*(?P<name>.+?)\s*[-–:]\s*(?P<price>[\d][\d.,]*)\s*(?:đ|d|vnd)?\s*$", re.IGNORECASE
)


def _heuristic_text_parse(text: str) -> dict[str, Any]:
    """Zero-LLM fallback for raw-text import in MOCK mode: lines shaped
    'Tên món - 35.000đ' become dishes; unparseable lines become warnings."""
    assembler = MenuAssembler(source_type="manual")
    assembler.set_shop_info(name="Quán (nhập tay)")
    assembler.add_section(id="menu", title="Menu")
    warnings: list[str] = []
    n_dishes = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        m = _TEXT_LINE_RE.match(line)
        if not m:
            warnings.append(f"không đọc được dòng: {line.strip()!r}")
            continue
        assembler.add_dish(section_id="menu", name=m["name"].strip(), price=m["price"])
        n_dishes += 1
    if n_dishes == 0:
        raise ValueError("không đọc được món nào từ text — thử chụp screenshot")
    assembler.finish(confidence=55, warnings=warnings)
    return assembler.envelope()


def _import_text(text: str) -> dict[str, Any]:
    if is_mock_mode():
        return _heuristic_text_parse(text)

    assembler = MenuAssembler(source_type="manual")
    tool = Toolable(assembler.tools())
    tool.run([_TEXT_PROMPT, text])
    return assembler.envelope()


# --------------------------------------------------------------------- entry


def import_menu(source: str | Path | Sequence[str | Path]) -> dict[str, Any]:
    """Entry point (ENGINE-SPEC §5). See module docstring for `source` shapes.

    Returns envelope `{"menu": <chuẩn §4>, "warnings": [...], "confidence": 0-100}`.
    Raises `ImportFallbackToOCR` for a URL source whose HTML parse failed.
    """
    kind = classify_source(source)
    if kind == "screenshot":
        paths = source if isinstance(source, (list, tuple)) else [source]
        return _import_screenshot(paths)
    if kind == "url":
        return _import_url(source)  # type: ignore[arg-type]  # str, guaranteed by classify_source
    return _import_text(source)  # type: ignore[arg-type]


__all__ = [
    "import_menu",
    "import_from_fixture",
    "classify_source",
    "is_mock_mode",
    "ImportFallbackToOCR",
]
