"""Group orders — office-pantry use case (ARCH §3.3, ENGINE-SPEC §8).

Flow: 1 người quét QR -> POST /group-orders sinh `gid` + share URL `/g/<gid>`
-> mỗi người tự thêm món (POST .../members, tên tự nhập, không login) ->
closer chốt (POST .../close) -> gộp toàn bộ item thành 1 `Order` thật (1 ship)
+ tính lại tiền mỗi người theo ĐÚNG những gì họ order (không chia đều) +
placeholder VietQR hoàn tiền cho người trả hộ (payer = closer).

VietQR is INTERFACE ONLY here — real bank-deeplink QR generation is
`infra/vietqr.py` in a later phase (ARCH §5.4); this just shapes the payload
so the buyer UI and that future module agree on a contract now.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from infra.orders import OrderStore
from infra.storage import Storage

GROUP_ORDERS_COLLECTION = "group_orders"

STATUS_OPEN = "open"
STATUS_CLOSED = "closed"


class GroupOrderError(Exception):
    pass


class GroupOrderNotFoundError(GroupOrderError):
    pass


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _new_gid() -> str:
    return f"g_{uuid.uuid4().hex[:10]}"


def _item_subtotal(items: list[dict[str, Any]]) -> int:
    return sum(int(it["price"]) * int(it["qty"]) for it in items)


class GroupOrderStore:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    def create(self, shop_id: str, shop_slug: str, batch_id: str | None = None) -> dict[str, Any]:
        gid = _new_gid()
        doc: dict[str, Any] = {
            "id": gid,
            "shop_id": shop_id,
            "shop_slug": shop_slug,
            "batch_id": batch_id or "office",
            "status": STATUS_OPEN,
            "members": {},  # name -> {"items": [...], "subtotal": int}
            "order_id": None,
            "created_at": _now(),
            "closed_at": None,
        }
        self.storage.put(GROUP_ORDERS_COLLECTION, gid, doc)
        return doc

    def get(self, gid: str) -> dict[str, Any]:
        doc = self.storage.get(GROUP_ORDERS_COLLECTION, gid)
        if doc is None:
            raise GroupOrderNotFoundError(f"group order {gid!r} không tồn tại")
        return doc

    def add_member_items(
        self, gid: str, member_name: str, items: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Set (replace) one member's item list. A member re-submitting their
        picks (edited quantity, added a drink) simply overwrites their prior
        entry — the group order is a draft until `close()`, not a ledger."""
        doc = self.get(gid)
        if doc["status"] != STATUS_OPEN:
            raise GroupOrderError(f"group order {gid!r} đã chốt, không thêm món được nữa")
        if not member_name or not member_name.strip():
            raise GroupOrderError("cần tên thành viên")
        if not items:
            raise GroupOrderError(f"{member_name}: cần ít nhất 1 món")
        doc["members"][member_name.strip()] = {
            "items": items,
            "subtotal": _item_subtotal(items),
        }
        self.storage.put(GROUP_ORDERS_COLLECTION, gid, doc)
        return doc

    def close(
        self,
        gid: str,
        order_store: OrderStore,
        closer_name: str,
        customer: dict[str, Any],
        variant: str | None = None,
    ) -> dict[str, Any]:
        """Chốt kèo: merge all members' items into ONE real Order (1 ship),
        compute the per-member split (each pays exactly what they ordered —
        NOT an equal division, so totals never leave a rounding remainder),
        and attach a VietQR-placeholder for everyone except the payer.

        Returns {"group_order": <doc>, "order": <order doc>, "split": {...}}.
        """
        doc = self.get(gid)
        if doc["status"] != STATUS_OPEN:
            raise GroupOrderError(f"group order {gid!r} đã chốt rồi")
        if not doc["members"]:
            raise GroupOrderError(f"group order {gid!r} chưa có ai order")
        if closer_name not in doc["members"]:
            raise GroupOrderError(
                f"người chốt {closer_name!r} phải tự order ít nhất 1 món (là người trả hộ)"
            )

        # Merge items across members into one order line list (same dish_id
        # across members collapses into a single qty for the seller ticket).
        merged: dict[str, dict[str, Any]] = {}
        for member in doc["members"].values():
            for it in member["items"]:
                entry = merged.setdefault(
                    it["dish_id"], {"dish_id": it["dish_id"], "name": it["name"], "price": it["price"], "qty": 0}
                )
                entry["qty"] += it["qty"]
        merged_items = list(merged.values())

        order = order_store.create(
            shop_id=doc["shop_id"],
            shop_slug=doc["shop_slug"],
            items=merged_items,
            customer=customer,
            batch_id=doc["batch_id"],
            variant=variant,
            payment_method="cod",
            group_order_id=gid,
        )

        order_total = order["total"]
        split: dict[str, dict[str, Any]] = {}
        for name, member in doc["members"].items():
            amount = member["subtotal"]
            entry: dict[str, Any] = {"amount": amount, "is_payer": name == closer_name}
            if name != closer_name and amount > 0:
                entry["vietqr_placeholder"] = {
                    "payee": closer_name,
                    "amount": amount,
                    "note": f"{gid} {name} tra {closer_name}",
                    "bank": None,  # interface only — infra/vietqr.py fills this in later phase
                    "account": None,
                }
            split[name] = entry
        assert sum(v["amount"] for v in split.values()) == order_total, (
            "per-member split must sum exactly to the order total — no equal-split rounding"
        )

        doc["status"] = STATUS_CLOSED
        doc["order_id"] = order["id"]
        doc["split"] = split
        doc["closed_at"] = _now()
        self.storage.put(GROUP_ORDERS_COLLECTION, gid, doc)
        return {"group_order": doc, "order": order, "split": split}
