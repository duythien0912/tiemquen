"""Order-parse tools (ENGINE-SPEC §8, ARCH §3.2 "Đặt qua Zalo" reverse path) —
bộ tool model (hoặc heuristic parser) bắt buộc gọi để biến chat text thành
order draft có cấu trúc.

`OrderDraftAssembler` giữ state; các bound method (`add_item`, `set_customer`,
`finish`) là tool functions cho `toolable.Toolable` — CÙNG pattern với
`menu_tools.MenuAssembler` (§5 import agent). MOCK mode gọi các method này
TRỰC TIẾP từ một line-heuristic parser (không cần model); REAL mode bọc qua
`Toolable` để model tool-call.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

#: Tool names exported by this module (1 module / toolable agent — SPEC §3).
TOOLS = ("add_item", "set_customer", "finish")


class OrderParseError(ValueError):
    pass


def _fold(s: str) -> str:
    """Accent-fold + lowercase + punctuation-strip
    ('Cơm sườn (nướng)!' -> 'com suon  nuong  ')."""
    s = s.strip().lower().replace("đ", "d")
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^\w\s]", " ", s)


#: Filler words that ride along in a chat order line ("2 phần cơm sườn nướng
#: nha") but carry no dish-identity signal — stripped before fuzzy matching.
_STOPWORDS = frozenset(
    {
        "phan", "ly", "chen", "to", "hop", "chai", "cai", "them", "nha", "nhe",
        "a", "cho", "e", "em", "chi", "anh", "shop", "quan", "oi", "voi",
        "va", "them", "1", "mot",
    }
)


def _tokens(name: str) -> set[str]:
    return {t for t in _fold(name).split() if t not in _STOPWORDS}


def fuzzy_match_dish(name: str, dishes: dict[str, dict[str, Any]]) -> tuple[str, float] | None:
    """Best-effort dish match: PRECISION of the query against each dish's
    name — how much of what the buyer typed shows up in the dish's name.
    Chat orders are typically an abbreviated fragment of the menu's fuller
    name ("gà nướng" for "Cơm tấm gà nướng mật ong"), so scoring by dish-side
    recall would unfairly punish long, descriptive menu names; precision
    doesn't. Ties (e.g. a 1-token query matching several dishes at 1.0) are
    broken by the SHORTEST dish name (closest overall match), then dish_id,
    for deterministic output.
    """
    query_tokens = _tokens(name)
    if not query_tokens:
        return None
    best: tuple[str, float, int] | None = None  # (dish_id, score, len(dish_tokens))
    for dish_id in sorted(dishes):
        dish_tokens = _tokens(dishes[dish_id]["name"])
        if not dish_tokens:
            continue
        overlap = len(query_tokens & dish_tokens)
        if overlap == 0:
            continue
        score = overlap / len(query_tokens)
        if best is None or (score, -len(dish_tokens)) > (best[1], -best[2]):
            best = (dish_id, score, len(dish_tokens))
    if best is not None and best[1] >= 0.5:
        return best[0], best[1]
    return None


_PHONE_RE = re.compile(r"(?:\+?84|0)(?:[\s.-]?\d){9,10}")


def extract_phone(text: str) -> str | None:
    m = _PHONE_RE.search(text)
    if not m:
        return None
    digits = re.sub(r"[^\d+]", "", m.group(0))
    return digits


class OrderDraftAssembler:
    """Gom tool calls (model hoặc heuristic parser) thành order draft."""

    def __init__(self, dishes: dict[str, dict[str, Any]]) -> None:
        self.dishes = dishes
        self.items: dict[str, dict[str, Any]] = {}  # dish_id -> {name,price,qty}
        self.customer: dict[str, str] = {}
        self.warnings: list[str] = []
        self.confidence: int | None = None
        self.finished = False

    def tools(self) -> list[Any]:
        return [self.add_item, self.set_customer, self.finish]

    def add_item(self, dish_name: str, qty: int = 1) -> str:
        """Thêm 1 món vào đơn, khớp tên món với menu quán.

        Args:
            dish_name: Tên món khách gõ trong chat (có thể viết tắt/thiếu dấu).
            qty: Số lượng, mặc định 1.
        """
        if not dish_name or not dish_name.strip():
            raise ValueError("dish_name không được rỗng")
        qty_n = int(qty)
        if qty_n <= 0:
            raise ValueError(f"qty phải > 0, nhận {qty!r}")

        match = fuzzy_match_dish(dish_name, self.dishes)
        if match is None:
            self.warnings.append(f"không khớp món nào với {dish_name!r} — bỏ qua, cần review tay")
            return f"không khớp món {dish_name!r} với menu"

        dish_id, score = match
        dish = self.dishes[dish_id]
        if dish_id in self.items:
            self.items[dish_id]["qty"] += qty_n
        else:
            self.items[dish_id] = {"dish_id": dish_id, "name": dish["name"], "price": dish["price"], "qty": qty_n}
        if score < 0.75:
            self.warnings.append(
                f"{dish_name!r} khớp mờ với {dish['name']!r} (score={score:.2f}) — kiểm tra lại"
            )
        return f"đã thêm {qty_n}x {dish['name']!r}"

    def set_customer(
        self,
        name: str | None = None,
        phone: str | None = None,
        address: str | None = None,
        note: str | None = None,
    ) -> str:
        """Ghi thông tin khách đọc được từ chat. Có thể gọi nhiều lần, mỗi lần
        set field nào đọc được — field sau đè field trước.

        Args:
            name: Tên khách nếu tự xưng trong chat.
            phone: SĐT khách.
            address: Địa chỉ giao / toà nhà.
            note: Ghi chú thêm (giờ giao, yêu cầu đặc biệt...).
        """
        for field, value in (("name", name), ("phone", phone), ("address", address), ("note", note)):
            if value and value.strip():
                self.customer[field] = value.strip()
        return f"đã ghi thông tin khách: {sorted(self.customer)}"

    def finish(self, confidence: int, warnings: list[str] | None = None) -> str:
        """Gọi CUỐI CÙNG khi đã đọc hết đoạn chat — chốt kết quả parse.

        Args:
            confidence: Độ tin cậy 0-100 cho toàn bộ kết quả parse.
            warnings: Các điểm không chắc, tiếng Việt.
        """
        conf = int(confidence)
        if not 0 <= conf <= 100:
            raise ValueError(f"confidence phải trong 0-100, nhận {confidence!r}")
        self.confidence = conf
        self.warnings += [w for w in (warnings or []) if w]
        self.finished = True
        return f"order draft chốt với confidence {conf}"

    def envelope(self) -> dict[str, Any]:
        """{"items", "customer", "warnings", "confidence"} — seller review UI
        sửa/khớp lại rồi mới POST /orders thật (không tự đặt đơn từ parse)."""
        if not self.items:
            self.warnings.append("không đọc được món nào từ đoạn chat — cần nhập tay")
        confidence = self.confidence
        if confidence is None:
            confidence = 50
            self.warnings.append("chưa gọi finish() — confidence mặc định 50")
        return {
            "items": list(self.items.values()),
            "customer": dict(self.customer),
            "warnings": list(self.warnings),
            "confidence": confidence,
        }
