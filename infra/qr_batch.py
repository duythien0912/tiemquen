"""Flyer batch registry — mỗi batch in = 1 mã QR riêng (ARCH §2 flyer analytics).

Batch doc (collection "batches"):
    {"id", "shop_id", "shop_slug", "format" (a5|a4|sticker),
     "location_tag", "created_at"}

QR trên tờ rơi trỏ `/t/{slug}?b={batch_id}` — buyer/context_rules.js đọc `?b=`
để chọn variant (office vs table) VÀ gửi nguyên batch_id kèm mọi order
(infra/orders.py đã lưu `batch_id`), nên analytics ở đây chỉ là một query
đếm ngược trên orders: batch nào dán ở đâu ra bao nhiêu đơn.

`batch_id` nhúng location_tag đã slugify (vd "office-plaza1-a5-3f2a") để
context_rules.classifyBatch() nhận ra chữ "office"/"van phong" mà không cần
tra cứu server (buyer path zero round-trip thừa, ENGINE-SPEC §9).
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from infra.publish import slugify
from infra.storage import Storage

BATCHES_COLLECTION = "batches"

#: 3 format vật lý (ARCH §2): A5 túi đơn sàn, A4 pantry/cửa quán, sticker vuông.
FLYER_FORMATS: tuple[str, ...] = ("a5", "a4", "sticker")


class BatchError(Exception):
    pass


class BatchNotFoundError(BatchError):
    pass


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def qr_url(shop_slug: str, batch_id: str, base_url: str = "") -> str:
    """URL in lên tờ rơi: `<base>/t/{slug}?b={batch_id}` (ENGINE-SPEC §9)."""
    return f"{base_url.rstrip('/')}/t/{shop_slug}?b={batch_id}"


class BatchStore:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    def create_batch(
        self, shop_id: str, shop_slug: str, fmt: str, location_tag: str
    ) -> dict[str, Any]:
        if fmt not in FLYER_FORMATS:
            raise BatchError(f"format {fmt!r} không hợp lệ; chọn một trong {FLYER_FORMATS}")
        loc = slugify(location_tag or "")
        if not loc:
            raise BatchError("cần location_tag (dán ở đâu — vd 'office plaza 1', 'cửa quán')")
        batch_id = f"{loc}-{fmt}-{uuid.uuid4().hex[:4]}"
        doc: dict[str, Any] = {
            "id": batch_id,
            "shop_id": shop_id,
            "shop_slug": shop_slug,
            "format": fmt,
            "location_tag": location_tag,
            "created_at": _now(),
        }
        self.storage.put(BATCHES_COLLECTION, batch_id, doc)
        return doc

    def get(self, batch_id: str) -> dict[str, Any]:
        doc = self.storage.get(BATCHES_COLLECTION, batch_id)
        if doc is None:
            raise BatchNotFoundError(f"batch {batch_id!r} không tồn tại")
        return doc

    def list_by_shop(self, shop_slug: str) -> list[dict[str, Any]]:
        out = []
        for key in self.storage.list(BATCHES_COLLECTION):
            doc = self.storage.get(BATCHES_COLLECTION, key)
            if doc and doc.get("shop_slug") == shop_slug:
                out.append(doc)
        return sorted(out, key=lambda b: b["created_at"])

    def delete(self, batch_id: str) -> bool:
        return self.storage.delete(BATCHES_COLLECTION, batch_id)


# ------------------------------------------------------------------ analytics


def _parse_ts(ts: str) -> datetime.datetime:
    dt = datetime.datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def orders_per_batch(
    storage: Storage,
    shop_slug: str,
    since: str | datetime.datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """Đơn-theo-batch (ARCH §3.4 growth loop: 'seller thấy batch nào ra đơn').

    Returns {batch_id: {"orders": n, "revenue": total_vnd, "last_order_at": ts}}
    over all orders of `shop_slug` created at/after `since` (ISO string or
    datetime; None = từ đầu). Orders without a flyer batch land under the
    "direct" key (infra/orders.DEFAULT_BATCH_ID).
    """
    from infra.orders import ORDERS_COLLECTION  # local import: avoid cycle risk

    cutoff: datetime.datetime | None = None
    if since is not None:
        cutoff = _parse_ts(since) if isinstance(since, str) else since
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=datetime.timezone.utc)

    stats: dict[str, dict[str, Any]] = {}
    for key in storage.list(ORDERS_COLLECTION):
        order = storage.get(ORDERS_COLLECTION, key)
        if not order or order.get("shop_slug") != shop_slug:
            continue
        created_at = order.get("created_at", "")
        if cutoff is not None and _parse_ts(created_at) < cutoff:
            continue
        batch_id = order.get("batch_id") or "direct"
        entry = stats.setdefault(
            batch_id, {"orders": 0, "revenue": 0, "last_order_at": created_at}
        )
        entry["orders"] += 1
        entry["revenue"] += int(order.get("total", 0))
        entry["last_order_at"] = max(entry["last_order_at"], created_at)
    return stats


__all__ = [
    "BATCHES_COLLECTION", "FLYER_FORMATS", "BatchError", "BatchNotFoundError",
    "BatchStore", "orders_per_batch", "qr_url",
]
