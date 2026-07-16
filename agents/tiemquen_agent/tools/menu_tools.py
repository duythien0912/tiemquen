"""Menu import tools (ENGINE-SPEC §5) — bộ tool OCR model bắt buộc gọi.

`MenuAssembler` giữ state; các bound method (`set_shop_info`, `add_section`,
`add_dish`, `finish`) là tool functions cho `toolable.Toolable` (docstring =
spec model-facing, signature sinh schema). Cuối cùng `envelope()` gom về
chuẩn menu format (shared/menu_schema.json) + warnings + confidence.

Price sanity: VND, ngoài 5.000–500.000đ -> warning (shared/menu_format.py).
"""

from __future__ import annotations

import datetime
import re
from typing import Any

from infra.publish import slugify
from shared.menu_format import (
    coerce_price,
    new_dish_id,
    price_sanity_warnings,
    validate_menu,
)

#: Tool names exported by this module (1 module / toolable agent — SPEC §3).
TOOLS = ("set_shop_info", "add_section", "add_dish", "finish")

_SECTION_ID_RE = re.compile(r"[^a-z0-9_]+")


class MenuAssemblyError(ValueError):
    pass


def _clean_section_id(raw: str) -> str:
    sid = _SECTION_ID_RE.sub("_", slugify(raw).replace("-", "_")).strip("_")
    return sid or "section"


class MenuAssembler:
    """Gom tool calls của model thành chuẩn menu doc (SPEC §4)."""

    def __init__(
        self, source_type: str = "ocr_screenshot", source_url: str | None = None
    ) -> None:
        self.source_type = source_type
        self.source_url = source_url
        self.shop_info: dict[str, str] = {}
        self.sections: list[dict[str, Any]] = []  # giữ thứ tự xuất hiện
        self._sections_by_id: dict[str, dict[str, Any]] = {}
        self.dishes: dict[str, dict[str, Any]] = {}
        self.warnings: list[str] = []
        self.confidence: int | None = None
        self.finished = False

    # ------------------------------------------------------------ tool functions

    def tools(self) -> list[Any]:
        """Bound tool functions cho Toolable (thứ tự = thứ tự khai báo cho model)."""
        return [self.set_shop_info, self.add_section, self.add_dish, self.finish]

    def set_shop_info(
        self,
        name: str,
        phone: str | None = None,
        address: str | None = None,
        hours: str | None = None,
    ) -> str:
        """Ghi thông tin quán đọc được từ menu. Gọi ĐÚNG 1 LẦN, TRƯỚC các tool khác.

        Args:
            name: Tên quán, giữ nguyên dấu tiếng Việt.
            phone: Số điện thoại quán nếu thấy trên ảnh.
            address: Địa chỉ quán nếu thấy.
            hours: Giờ mở cửa dạng chữ, ví dụ '06:00-14:00'.
        """
        if not name or not name.strip():
            raise ValueError("name không được rỗng")
        if self.shop_info.get("name"):
            self.warnings.append("set_shop_info gọi nhiều lần — lấy lần cuối")
        self.shop_info = {"name": name.strip()}
        if phone:
            cleaned = re.sub(r"[^0-9+]", "", phone)
            if re.fullmatch(r"[0-9+][0-9 .-]{5,19}", cleaned):
                self.shop_info["phone"] = cleaned
            else:
                self.warnings.append(f"SĐT {phone!r} không hợp lệ — bỏ qua")
        if address and address.strip():
            self.shop_info["address"] = address.strip()
        if hours and hours.strip():
            self.shop_info["hours"] = hours.strip()
        return f"đã ghi thông tin quán {name!r}"

    def add_section(self, id: str, title: str) -> str:
        """Thêm một section (nhóm món) của menu, theo thứ tự hiển thị trên ảnh.

        Args:
            id: ID section ngắn không dấu, ví dụ 'com_tam', 'nuoc_uong'.
            title: Tiêu đề section đúng như trên menu, giữ dấu tiếng Việt.
        """
        if not title or not title.strip():
            raise ValueError("title không được rỗng")
        sid = _clean_section_id(id or title)
        if sid in self._sections_by_id:
            self.warnings.append(f"section {sid!r} khai báo trùng — gộp làm một")
            self._sections_by_id[sid]["title"] = title.strip()
            return f"section {sid!r} đã có, cập nhật title"
        section = {"id": sid, "title": title.strip(), "items": []}
        self.sections.append(section)
        self._sections_by_id[sid] = section
        return f"đã thêm section {sid!r}"

    def add_dish(
        self,
        section_id: str,
        name: str,
        price: int,
        desc: str | None = None,
        image_ref: str | None = None,
    ) -> str:
        """Thêm một món vào section. Gọi 1 lần cho MỖI món đọc được.

        Args:
            section_id: ID section đã add_section trước đó.
            name: Tên món đúng như trên menu.
            price: Giá VND dạng số nguyên (ví dụ 45000 cho 45.000đ). KHÔNG lấy đơn vị nghìn.
            desc: Mô tả ngắn của món nếu có.
            image_ref: Tham chiếu ảnh món nếu có (URL hoặc path).
        """
        if not name or not name.strip():
            raise ValueError("name không được rỗng")
        name = name.strip()
        price_vnd = coerce_price(price)
        self.warnings += price_sanity_warnings(name, price_vnd)

        sid = _clean_section_id(section_id)
        section = self._sections_by_id.get(sid)
        if section is None:  # model quên add_section — tự tạo, cảnh báo
            self.warnings.append(
                f"món {name!r} chỉ tới section {sid!r} chưa khai báo — tự tạo"
            )
            section = {"id": sid, "title": section_id.strip() or sid, "items": []}
            self.sections.append(section)
            self._sections_by_id[sid] = section

        dish_id = new_dish_id(name, self.dishes)
        dish: dict[str, Any] = {
            "name": name,
            "price": price_vnd,
            "direct_only": False,
            "hidden": False,
            "sold_out": False,
            "almost_out": False,
        }
        if desc and desc.strip():
            dish["desc"] = desc.strip()
        if image_ref and image_ref.strip():
            # Raw ref — infra/media.py rehost về /media/<shop>/ sau khi build.
            dish["image_url"] = image_ref.strip()
        self.dishes[dish_id] = dish
        section["items"].append(dish_id)
        return f"đã thêm món {dish_id!r} vào section {sid!r} (giá {price_vnd:,}đ)"

    def finish(self, confidence: int, warnings: list[str] | None = None) -> str:
        """Gọi CUỐI CÙNG khi đã đọc hết menu — chốt kết quả import.

        Args:
            confidence: Độ tin cậy 0-100 cho toàn bộ kết quả OCR (chữ mờ/che khuất thì thấp).
            warnings: Các điểm không chắc (giá đọc mờ, món bị cắt ảnh...), tiếng Việt.
        """
        conf = int(confidence)
        if not 0 <= conf <= 100:
            raise ValueError(f"confidence phải trong 0-100, nhận {confidence!r}")
        self.confidence = conf
        self.warnings += [w for w in (warnings or []) if w]
        self.finished = True
        return f"import chốt với confidence {conf}"

    # ---------------------------------------------------------------- assembly

    def build(self) -> dict[str, Any]:
        """Gom state thành chuẩn menu doc (SPEC §4) + validate schema."""
        name = self.shop_info.get("name")
        if not name:
            raise MenuAssemblyError("model chưa gọi set_shop_info(name=...)")
        if not self.dishes:
            raise MenuAssemblyError("không đọc được món nào (add_dish chưa gọi)")

        slug = slugify(name)
        shop: dict[str, Any] = {
            "id": f"shop_{slug.replace('-', '')}",
            "slug": slug,
            "name": name,
        }
        for field in ("phone", "address", "hours"):
            if self.shop_info.get(field):
                shop[field] = self.shop_info[field]

        confidence = self.confidence
        if confidence is None:
            confidence = 50
            self.warnings.append("model không gọi finish() — confidence mặc định 50")

        source: dict[str, Any] = {
            "type": self.source_type,
            "imported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "confidence": confidence,
        }
        if self.source_url:
            source["url"] = self.source_url

        doc = {
            "shop": shop,
            "menu": {
                "sections": [s for s in self.sections if s["items"]],
                "dishes": self.dishes,
            },
            "source": source,
        }
        validate_menu(doc)  # mọi nguồn import đổ về đúng chuẩn, fail sớm ở đây
        return doc

    def envelope(self) -> dict[str, Any]:
        """Envelope trả về UI review (SPEC §5): {menu, warnings, confidence}."""
        doc = self.build()
        return {
            "menu": doc,
            "warnings": list(self.warnings),
            "confidence": doc["source"]["confidence"],
        }
