"""Helpers around the chuẩn menu format schema (shared/menu_schema.json)."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema

SCHEMA_PATH = Path(__file__).resolve().parent / "menu_schema.json"
REPO_ROOT = SCHEMA_PATH.parent.parent
DEMO_FIXTURE_PATH = REPO_ROOT / "data" / "fixtures" / "demo_shop.json"


@lru_cache(maxsize=1)
def load_schema() -> dict[str, Any]:
    with SCHEMA_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def validate_menu(doc: dict[str, Any]) -> None:
    """Raise jsonschema.ValidationError if `doc` is not a valid chuẩn menu doc.

    Beyond the JSON Schema, also checks referential integrity:
    every section item must point at an existing dish id.
    """
    jsonschema.validate(instance=doc, schema=load_schema())
    dishes = doc["menu"]["dishes"]
    for section in doc["menu"]["sections"]:
        for dish_id in section["items"]:
            if dish_id not in dishes:
                raise jsonschema.ValidationError(
                    f"section {section['id']!r} references unknown dish {dish_id!r}"
                )


def validation_errors(doc: dict[str, Any]) -> list[str]:
    """Return human-readable errors ([] means valid)."""
    try:
        validate_menu(doc)
    except jsonschema.ValidationError as e:
        return [e.message]
    return []


def load_demo_fixture() -> dict[str, Any]:
    with DEMO_FIXTURE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------- price sanity

#: Khoảng giá món "bình thường" (VND). Ngoài khoảng -> warning (không chặn):
#: OCR hay đọc thiếu/thừa số 0, hoặc model trả giá theo đơn vị nghìn.
PRICE_WARN_MIN = 5_000
PRICE_WARN_MAX = 500_000


def coerce_price(value: Any) -> int:
    """Ép giá về int VND. Nhận int/float/chuỗi kiểu '45,000đ' / '45.000 VND'."""
    if isinstance(value, bool):
        raise ValueError(f"giá không hợp lệ: {value!r}")
    if isinstance(value, (int, float)):
        price = int(round(value))
    elif isinstance(value, str):
        digits = re.sub(r"[^\d]", "", value)
        if not digits:
            raise ValueError(f"giá không hợp lệ: {value!r}")
        price = int(digits)
    else:
        raise ValueError(f"giá không hợp lệ: {value!r}")
    if price < 0:
        raise ValueError(f"giá âm: {price}")
    return price


def price_sanity_warnings(name: str, price: int) -> list[str]:
    """Cảnh báo giá ngoài khoảng PRICE_WARN_MIN..PRICE_WARN_MAX (VND)."""
    if price < PRICE_WARN_MIN or price > PRICE_WARN_MAX:
        return [
            f"giá {price:,}đ của {name!r} ngoài khoảng "
            f"{PRICE_WARN_MIN:,}–{PRICE_WARN_MAX:,}đ — kiểm tra lại"
        ]
    return []


# --------------------------------------------------------------- review edits


class MenuEditError(ValueError):
    """Edit review không áp dụng được (op lạ, dish/section không tồn tại...)."""


def new_dish_id(name: str, existing: set[str] | dict[str, Any]) -> str:
    """Sinh dish_id chuẩn từ tên món, tránh đụng id đã có: dish_com_suon(_2)."""
    base = re.sub(r"[^a-z0-9]+", "_", _fold_vn(name)).strip("_") or "mon"
    dish_id = f"dish_{base}"
    n = 1
    while dish_id in existing:
        n += 1
        dish_id = f"dish_{base}_{n}"
    return dish_id


def _fold_vn(s: str) -> str:
    import unicodedata

    s = s.strip().lower().replace("đ", "d")
    s = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn")


def apply_menu_edits(doc: dict[str, Any], edits: list[dict[str, Any]]) -> list[str]:
    """Áp các edit review của seller (ARCH §3.1) lên chuẩn menu doc, in place.

    Ops: set_price {dish_id, price} · hide_dish {dish_id, hidden?=true}
       · add_dish {section_id, name, price, desc?, direct_only?, image_url?}
       · retitle_section {section_id, title}.
    Trả về list warnings (price sanity). Lỗi cấu trúc -> MenuEditError.
    Caller chịu trách nhiệm validate + persist + RECOMPOSE (đổi structure).
    """
    menu = doc["menu"]
    dishes: dict[str, Any] = menu["dishes"]
    sections = {s["id"]: s for s in menu["sections"]}
    warnings: list[str] = []

    for i, edit in enumerate(edits):
        if not isinstance(edit, dict) or "op" not in edit:
            raise MenuEditError(f"edit #{i} thiếu 'op': {edit!r}")
        op = edit["op"]

        if op == "set_price":
            dish = dishes.get(edit.get("dish_id", ""))
            if dish is None:
                raise MenuEditError(f"set_price: món {edit.get('dish_id')!r} không tồn tại")
            price = coerce_price(edit.get("price"))
            dish["price"] = price
            warnings += price_sanity_warnings(dish["name"], price)

        elif op == "hide_dish":
            dish = dishes.get(edit.get("dish_id", ""))
            if dish is None:
                raise MenuEditError(f"hide_dish: món {edit.get('dish_id')!r} không tồn tại")
            dish["hidden"] = bool(edit.get("hidden", True))

        elif op == "add_dish":
            section = sections.get(edit.get("section_id", ""))
            if section is None:
                raise MenuEditError(
                    f"add_dish: section {edit.get('section_id')!r} không tồn tại"
                )
            name = edit.get("name")
            if not name:
                raise MenuEditError("add_dish: thiếu 'name'")
            price = coerce_price(edit.get("price"))
            dish_id = new_dish_id(name, dishes)
            entry: dict[str, Any] = {
                "name": name,
                "price": price,
                "direct_only": bool(edit.get("direct_only", False)),
                "hidden": False,
                "sold_out": False,
                "almost_out": False,
            }
            if edit.get("desc"):
                entry["desc"] = edit["desc"]
            if edit.get("image_url"):
                entry["image_url"] = edit["image_url"]
            dishes[dish_id] = entry
            section["items"].append(dish_id)
            warnings += price_sanity_warnings(name, price)

        elif op == "retitle_section":
            section = sections.get(edit.get("section_id", ""))
            if section is None:
                raise MenuEditError(
                    f"retitle_section: section {edit.get('section_id')!r} không tồn tại"
                )
            title = edit.get("title")
            if not title:
                raise MenuEditError("retitle_section: thiếu 'title'")
            section["title"] = title

        else:
            raise MenuEditError(f"op không hỗ trợ: {op!r}")

    return warnings
