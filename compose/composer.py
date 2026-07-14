"""Composer — menu chuẩn + theme + variant -> validated A2UI message list.

ENGINE-SPEC §1/§2/§7 + ARCH §5.3. LLM chỉ chạy Ở ĐÂY (compose-time):
- MOCK MODE (không có GEMINI_API_KEY): template composer thuần deterministic,
  build đủ surface từ menu chuẩn — không network. Mọi module chạy được không
  có key (SPEC §10).
- REAL MODE: google-genai (gemini-flash-latest), catalog JSON nhét vào prompt,
  output bọc <a2ui-json> -> parse -> validate/repair -> retry 1 lần với
  correction prompt nếu hỏng. Racing (compose/racing.py) chỉ dùng ở mode này.

Variants per ARCH §5.3 (compose sẵn, buyer chọn bằng rule KHÔNG LLM):
  batch office|table  ×  daypart lunch|regular  -> 4 bản, cache riêng.
"""

from __future__ import annotations

import json
import os
import unicodedata
from typing import Any

from agents.tiemquen_agent import a2ui
from compose.theme import derive_theme

GEMINI_MODEL = "gemini-flash-latest"
SURFACE_ID = a2ui.DEFAULT_SURFACE_ID  # "shop_menu"

BATCHES = ("office", "table")
DAYPARTS = ("lunch", "regular")
VARIANTS = tuple(f"{b}-{d}" for b in BATCHES for d in DAYPARTS)
# ("office-lunch", "office-regular", "table-lunch", "table-regular")


def is_mock_mode() -> bool:
    """No GEMINI_API_KEY -> deterministic template composer, zero network."""
    return not os.environ.get("GEMINI_API_KEY")


def _split_variant(variant: str) -> tuple[str, str]:
    batch, _, daypart = variant.partition("-")
    if batch not in BATCHES or daypart not in DAYPARTS:
        raise ValueError(f"unknown variant {variant!r}; expected one of {VARIANTS}")
    return batch, daypart


# ------------------------------------------------------------------- mock mode


def _fold(s: str) -> str:
    """Accent-fold + lowercase for section-title matching ('Trưa' -> 'trua')."""
    s = s.lower().replace("đ", "d")
    s = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn")


def _is_lunch_section(section: dict[str, Any]) -> bool:
    t = _fold(section.get("title", ""))
    return "combo" in t or "trua" in t


def _order_sections(sections: list[dict[str, Any]], daypart: str) -> list[dict[str, Any]]:
    """Lunch variant: section combo/trưa lên đầu (ARCH §5.3). Stable otherwise."""
    if daypart != "lunch":
        return list(sections)
    return sorted(sections, key=lambda s: 0 if _is_lunch_section(s) else 1)


def _template_compose(
    menu_doc: dict[str, Any], theme: dict[str, str], variant: str
) -> list[dict[str, Any]]:
    """Deterministic template composer — the full buyer surface from the menu."""
    batch, daypart = _split_variant(variant)
    shop = menu_doc["shop"]
    menu = menu_doc["menu"]
    dishes: dict[str, Any] = menu["dishes"]

    lit = lambda s: {"literalString": s}  # noqa: E731

    components: list[dict[str, Any]] = []
    page_children: list[str] = []

    # Hero
    components.append(
        {
            "id": "hero",
            "component": "HeroHeader",
            "shopName": lit(shop["name"]),
            **({"tagline": lit(shop["tagline"])} if shop.get("tagline") else {}),
            **({"hours": lit(shop["hours"])} if shop.get("hours") else {}),
        }
    )
    page_children.append("hero")

    if shop.get("direct_discount_pct"):
        components.append(
            {
                "id": "badge_direct",
                "component": "Badge",
                "text": lit(f"Đặt thẳng rẻ hơn app -{shop['direct_discount_pct']}%"),
                "kind": lit("success"),
            }
        )
        page_children.append("badge_direct")

    group_btn = {
        "id": "group_order",
        "component": "GroupOrderButton",
        "label": lit("Gom đơn cả phòng — ship 1 lần"),
        "onPress": {"event": {"name": "start_group_order", "context": {}}},
    }
    components.append(group_btn)
    if batch == "office":  # office batch -> promote ngay dưới hero (ARCH §5.3)
        page_children.append("group_order")

    # Sections + DishCards (skip hidden dishes; prices/soldout BIND DataModel).
    # Card id is section-scoped: the same dish may appear in several sections
    # (vd combo trưa tái dùng món thường) — component ids must stay unique.
    visible_ids: list[str] = []
    for section in _order_sections(menu["sections"], daypart):
        card_ids: list[str] = []
        for dish_id in section["items"]:
            dish = dishes.get(dish_id)
            if dish is None or dish.get("hidden"):
                continue
            if dish_id not in visible_ids:
                visible_ids.append(dish_id)
            card_id = f"card_{section['id']}_{dish_id}"
            card_ids.append(card_id)
            card: dict[str, Any] = {
                "id": card_id,
                "component": "DishCard",
                "name": lit(dish["name"]),
                "price": {"path": f"/prices/{dish_id}"},
                "soldOut": {"path": f"/soldout/{dish_id}"},
                "almostOut": {"path": f"/almostout/{dish_id}"},
                "onPress": {
                    "event": {"name": "add_to_cart", "context": {"dishId": {"literalString": dish_id}}}
                },
            }
            if dish.get("desc"):
                card["note"] = lit(dish["desc"])
            if dish.get("platform_price"):
                card["comparePrice"] = {"literalNumber": dish["platform_price"]}
            if dish.get("image_url"):
                card["image"] = lit(dish["image_url"])
            components.append(card)
        if not card_ids:
            continue
        sec_comp_id = f"section_{section['id']}"
        components.append(
            {
                "id": sec_comp_id,
                "component": "MenuSection",
                "title": lit(section["title"]),
                "childIds": {"explicitList": card_ids},
            }
        )
        page_children.append(sec_comp_id)

    if batch == "table":  # batch quán -> nút gom đơn cuối trang
        page_children.append("group_order")

    # Checkout: COD mặc định, VietQR ẩn sau cờ DataModel (trust gate).
    components.append(
        {
            "id": "payment",
            "component": "PaymentPicker",
            "codLabel": lit("Tiền mặt khi nhận (COD)"),
            "vietqrEnabled": {"path": "/payment/vietqr_enabled"},
            "vietqrLabel": lit("Chuyển khoản VietQR"),
            "selected": {"path": "/payment/selected"},
        }
    )
    components.append(
        {
            "id": "checkout",
            "component": "CheckoutForm",
            "title": lit("Đặt món"),
            "nameLabel": lit("Tên của bạn"),
            "phoneLabel": lit("Số điện thoại"),
            "addressLabel": lit("Địa chỉ / toà nhà"),
            "noteLabel": lit("Ghi chú cho quán"),
            "onSubmit": {"event": {"name": "submit_order", "context": {}}},
        }
    )
    page_children += ["payment", "checkout"]

    components.append(
        {
            "id": "cart_bar",
            "component": "CartBar",
            "total": {"path": "/cart/total"},
            "itemCount": {"path": "/cart/count"},
            "label": lit("Đặt món"),
            "onCheckout": {"event": {"name": "open_checkout", "context": {}}},
        }
    )
    page_children.append("cart_bar")

    components.insert(
        0, {"id": "root", "component": "Page", "childIds": {"explicitList": page_children}}
    )

    messages = [
        a2ui.make_create_surface(SURFACE_ID),
        a2ui.make_update_components(SURFACE_ID, components),
        a2ui.make_update_data_model(
            SURFACE_ID, "/prices", {d: dishes[d]["price"] for d in visible_ids}
        ),
        a2ui.make_update_data_model(
            SURFACE_ID, "/soldout", {d: bool(dishes[d].get("sold_out")) for d in visible_ids}
        ),
        a2ui.make_update_data_model(
            SURFACE_ID, "/almostout", {d: bool(dishes[d].get("almost_out")) for d in visible_ids}
        ),
        a2ui.make_update_data_model(
            SURFACE_ID,
            "/payment",
            {"selected": "cod", "vietqr_enabled": False},
        ),
        a2ui.make_update_data_model(SURFACE_ID, "/cart", {"total": 0, "count": 0}),
        a2ui.make_update_data_model(SURFACE_ID, "/theme", theme),
    ]
    return messages


# ------------------------------------------------------------------- real mode

_COMPOSE_PROMPT = """Bạn là composer UI cho Tiệm Quen. Sinh A2UI JSON (protocol v0.9) cho trang order của quán.

PROTOCOL: output là 1 JSON list các message. Mỗi message: {{"version":"v0.9", <đúng 1 action key>}}.
Action keys: createSurface | updateComponents | updateDataModel.
- Message đầu: createSurface với surfaceId "shop_menu", catalogId "{catalog_id}".
- updateComponents: component list PHẲNG, tree nối bằng id; root có id "root" (Page).
- Leaf value: {{"path":"/x"}} bind DataModel hoặc {{"literalString"|"literalNumber"|"literalBoolean": ...}}.
- Event: {{"event":{{"name":"...","context":{{...}}}}}}.
- GIÁ và HẾT MÓN bắt buộc bind DataModel: price -> /prices/<dish_id>, soldOut -> /soldout/<dish_id>
  (đổi giá/hết món chỉ patch data, không recompose).

COMPONENT CATALOG (JSON Schema per component — chỉ dùng các component này):
{catalog_json}

MENU CHUẨN CỦA QUÁN:
{menu_json}

THEME PALETTE (đưa vào updateDataModel /theme):
{theme_json}

VARIANT: {variant} — {variant_hint}

Yêu cầu: HeroHeader đầu trang; mỗi section menu -> MenuSection chứa DishCard;
CartBar sticky; CheckoutForm (COD mặc định qua PaymentPicker); GroupOrderButton.
Bọc TOÀN BỘ output trong <a2ui-json> và </a2ui-json>. Không giải thích gì thêm."""

_VARIANT_HINTS = {
    "office-lunch": "tờ rơi văn phòng, giờ trưa: GroupOrderButton nổi ngay dưới hero, section combo/trưa lên đầu",
    "office-regular": "tờ rơi văn phòng: GroupOrderButton nổi ngay dưới hero",
    "table-lunch": "QR tại bàn, giờ trưa: section combo/trưa lên đầu, GroupOrderButton cuối trang",
    "table-regular": "QR tại bàn: menu đủ, GroupOrderButton cuối trang",
}

_CORRECTION_PROMPT = """Output trước của bạn KHÔNG parse/validate được:
{error}

Sửa lại và trả về ĐÚNG A2UI JSON list theo protocol đã mô tả,
bọc trong <a2ui-json>...</a2ui-json>. Không giải thích."""


def _llm_compose_once(
    menu_doc: dict[str, Any],
    theme: dict[str, str],
    variant: str,
    catalog: dict[str, Any],
) -> list[dict[str, Any]]:
    """One real Gemini compose call: prompt -> parse -> validate/repair.

    Retry ĐÚNG 1 LẦN với correction prompt khi output hỏng (SPEC §3 base_agent).
    """
    from google import genai  # lazy: real mode only

    client = genai.Client()
    prompt = _COMPOSE_PROMPT.format(
        catalog_id=catalog.get("catalogId", a2ui.DEFAULT_CATALOG_ID),
        catalog_json=json.dumps(catalog, ensure_ascii=False),
        menu_json=json.dumps(menu_doc, ensure_ascii=False),
        theme_json=json.dumps(theme, ensure_ascii=False),
        variant=variant,
        variant_hint=_VARIANT_HINTS[variant],
    )
    contents: list[Any] = [prompt]
    last_error: Exception | None = None
    for _attempt in range(2):  # first try + 1 correction retry
        response = client.models.generate_content(model=GEMINI_MODEL, contents=contents)
        text = response.text or ""
        try:
            messages = a2ui.parse_a2ui(text)
            clean, _warnings = a2ui.validate_and_repair(messages, catalog=catalog)
            return clean
        except a2ui.A2UIValidationError as e:
            last_error = e
            contents = [prompt, text, _CORRECTION_PROMPT.format(error=e)]
    raise a2ui.A2UIValidationError(f"compose failed after retry: {last_error}")


# ----------------------------------------------------------------- entry points


def compose(
    menu_doc: dict[str, Any],
    theme: dict[str, str] | None = None,
    variant: str = "table-regular",
) -> list[dict[str, Any]]:
    """menu chuẩn (+ theme, variant) -> VALIDATED A2UI message list.

    theme=None -> derive from shop.theme.seed_colors (compose/theme.py).
    """
    _split_variant(variant)  # fail fast on unknown variant
    if theme is None:
        theme = derive_theme(menu_doc["shop"]["theme"]["seed_colors"])
    catalog = a2ui.load_catalog()

    if is_mock_mode():
        messages = _template_compose(menu_doc, theme, variant)
    else:
        from compose.racing import race_enabled, race_sync

        if race_enabled():
            messages = race_sync(lambda: _llm_compose_once(menu_doc, theme, variant, catalog))
        else:
            messages = _llm_compose_once(menu_doc, theme, variant, catalog)

    # Template output goes through the SAME validator as LLM output — the
    # cache only ever holds clean JSON (buyer page never re-validates).
    clean, warnings = a2ui.validate_and_repair(messages, catalog=catalog)
    if is_mock_mode() and warnings:
        raise a2ui.A2UIValidationError(f"template composer produced warnings: {warnings}")
    return clean


def compose_all_variants(
    menu_doc: dict[str, Any], theme: dict[str, str] | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Compose cả 4 biến thể ARCH §5.3 — cache riêng từng bản."""
    if theme is None:
        theme = derive_theme(menu_doc["shop"]["theme"]["seed_colors"])
    return {v: compose(menu_doc, theme, v) for v in VARIANTS}
