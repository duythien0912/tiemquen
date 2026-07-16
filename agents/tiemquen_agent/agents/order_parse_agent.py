"""Order-parse agent (ENGINE-SPEC §8, ARCH §3.2 "Đặt qua Zalo" reverse path).

Seller pastes the buyer's raw Zalo chat text into the app -> this turns it
into a structured order DRAFT the seller reviews before it becomes a real
order (never auto-submits — same review-gate philosophy as the import agent,
ARCH §3.1).

MOCK mode (no GEMINI_API_KEY): deterministic line-heuristic parser — dish-
name fuzzy match against the shop's own menu + quantities + address/phone
line detection. Zero LLM, zero network (SPEC §10).
REAL mode: `toolable.Toolable` tool-calling loop over the SAME
`OrderDraftAssembler` tools (`add_item`/`set_customer`/`finish`) — mock and
real converge on identical assembly, exactly like `import_agent`.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from agents.tiemquen_agent.tools.order_tools import (
    OrderDraftAssembler,
    _fold,
    _PHONE_RE,
    fuzzy_match_dish,
)
from agents.tiemquen_agent.toolable import Toolable

_PARSE_PROMPT = """Bạn đọc đoạn chat Zalo khách đặt món của quán ăn Việt Nam, và gọi CÁC TOOL
để ghi lại thành order có cấu trúc: add_item cho MỖI món (khớp với tên món trong menu dưới đây,
số lượng nếu có), set_customer cho tên/SĐT/địa chỉ/ghi chú đọc được, rồi finish với confidence 0-100.

MENU QUÁN:
{menu_json}

ĐOẠN CHAT:
{text}"""


def is_mock_mode() -> bool:
    return not os.environ.get("GEMINI_API_KEY")


# --------------------------------------------------------------- mock heuristic

# Three quantity notations, tried in this order:
#   "sườn nướng x2" / "sườn nướng x 2"  -> name THEN glued/spaced x-qty
#   "2x sườn nướng" / "2 x sườn nướng"  -> qty THEN glued x, then a space
#       (the whitespace-before-name requirement is what stops "1 xíu mại..."
#       from being misread as qty=1 with the 'x' of "xíu" eaten as a marker)
#   "2 sườn nướng"                       -> plain leading qty, no x at all
_NAME_QTY_RE = re.compile(r"^\s*(.+?)\s*x\s*(\d+)\s*$", re.IGNORECASE)
_QTY_X_GLUED_RE = re.compile(r"^\s*(\d+)\s*x\s+(.+)$", re.IGNORECASE)
_QTY_PLAIN_RE = re.compile(r"^\s*(\d+)\s+(.+)$")
_SPLIT_RE = re.compile(r"[,;]|\s+(?:v[àa])\s+", re.IGNORECASE)

#: Imperative order-labels / honorific greetings that ride along with the
#: item list ("Chị ơi cho em 2 sườn nướng", "Em đặt: ...") — stripped
#: (anywhere in the line, not just at the start) before segmenting, else
#: "cho"/"chị ơi" would be read as part of a dish name.
_GREETING_RE = re.compile(r"\b(?:chị|anh|shop|em)\s+ơi\b\s*", re.IGNORECASE)
_ORDER_LABEL_RE = re.compile(
    r"\b(?:cho\s+(?:quán|shop|em|anh|chị)|em\s*(?:đặt|lấy|order)|mình\s*(?:đặt|lấy)|order|đặt)\b\s*:?\s*",
    re.IGNORECASE,
)
_NAME_LABEL_RE = re.compile(
    r"^\s*(?:tên|tôi\s*là|mình\s*là|em\s*là|anh\s*là|chị\s*là)\s*:?\s*", re.IGNORECASE
)
_ADDRESS_LABEL_RE = re.compile(r"^\s*(?:địa\s*chỉ|d/c|giao\s*(?:tới|đến)?)\s*:?\s*", re.IGNORECASE)

_ADDRESS_FOLDED_KEYWORDS = ("dia chi", "d/c", "giao ", "toa nha", "chung cu", "duong", "ngo ")
_NAME_FOLDED_KEYWORDS = ("ten ", "toi la", "minh la", "em la", "anh la", "chi la")


def _looks_like_item_segment(seg: str) -> bool:
    """Segment has an explicit qty marker ('2 ...' / '... x2') — worth
    trying against the menu even if the fuzzy match comes back empty
    (surfaces as a warning instead of being silently dropped)."""
    return bool(_NAME_QTY_RE.match(seg) or _QTY_X_GLUED_RE.match(seg) or _QTY_PLAIN_RE.match(seg))


def _parse_item_segment(seg: str) -> tuple[str, int]:
    m = _NAME_QTY_RE.match(seg)
    if m:
        return m.group(1).strip(), int(m.group(2))
    m = _QTY_X_GLUED_RE.match(seg)
    if m:
        return m.group(2).strip(), int(m.group(1))
    m = _QTY_PLAIN_RE.match(seg)
    if m:
        return m.group(2).strip(), int(m.group(1))
    return seg.strip(), 1


def _heuristic_parse(text: str, assembler: OrderDraftAssembler) -> None:
    global_phone = None
    m = _PHONE_RE.search(text)
    if m:
        global_phone = re.sub(r"[^\d+]", "", m.group(0))
        assembler.set_customer(phone=global_phone)

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        folded = _fold(line)

        if _PHONE_RE.search(line):
            # Phone already captured globally — this line is customer info,
            # not an item list, UNLESS it also carries an address keyword.
            if any(kw in folded for kw in _ADDRESS_FOLDED_KEYWORDS):
                addr = _ADDRESS_LABEL_RE.sub("", _PHONE_RE.sub("", line)).strip(" ,.-")
                if addr:
                    assembler.set_customer(address=addr)
            continue

        if any(folded.startswith(kw) for kw in _NAME_FOLDED_KEYWORDS):
            segs = [s.strip() for s in line.split(",")]
            name = _NAME_LABEL_RE.sub("", segs[0]).strip()
            if name:
                assembler.set_customer(name=name)
            if len(segs) > 1:
                addr = ", ".join(segs[1:]).strip()
                if addr:
                    assembler.set_customer(address=addr)
            continue

        if any(kw in folded for kw in _ADDRESS_FOLDED_KEYWORDS):
            addr = _ADDRESS_LABEL_RE.sub("", line).strip()
            if addr:
                assembler.set_customer(address=addr)
            continue

        # Otherwise: try to read it as an item list line.
        stripped = _ORDER_LABEL_RE.sub("", _GREETING_RE.sub("", line))
        for seg in _SPLIT_RE.split(stripped):
            seg = seg.strip()
            if not seg:
                continue
            dish_name, qty = _parse_item_segment(seg)
            if _looks_like_item_segment(seg) or fuzzy_match_dish(dish_name, assembler.dishes) is not None:
                assembler.add_item(dish_name, qty)

    assembler.finish(confidence=70 if assembler.items else 30)


def _mock_parse(text: str, menu_doc: dict[str, Any]) -> dict[str, Any]:
    assembler = OrderDraftAssembler(menu_doc["menu"]["dishes"])
    _heuristic_parse(text, assembler)
    return assembler.envelope()


# ------------------------------------------------------------------- real mode


def _real_parse(text: str, menu_doc: dict[str, Any]) -> dict[str, Any]:
    assembler = OrderDraftAssembler(menu_doc["menu"]["dishes"])
    tool = Toolable(assembler.tools())
    prompt = _PARSE_PROMPT.format(
        menu_json=json.dumps(menu_doc["menu"], ensure_ascii=False), text=text
    )
    tool.run([prompt])
    return assembler.envelope()


# ----------------------------------------------------------------------- entry


def parse_order_text(text: str, menu_doc: dict[str, Any]) -> dict[str, Any]:
    """Zalo chat text (+ the shop's chuẩn menu doc, for dish matching) ->
    order draft envelope `{"items", "customer", "warnings", "confidence"}`.

    Never creates a real order — the seller app reviews/fixes the draft, then
    the existing `POST /orders` call finalizes it (mirrors the import agent's
    review-gate pattern, ARCH §3.1).
    """
    if not text or not text.strip():
        raise ValueError("text rỗng — không có gì để parse")
    if is_mock_mode():
        return _mock_parse(text, menu_doc)
    return _real_parse(text, menu_doc)


__all__ = ["parse_order_text", "is_mock_mode"]
