"""Order store + state machine (ENGINE-SPEC §8, ARCH §3.2/§3.3).

Order doc shape (persisted via Storage, collection "orders"):
    {"id", "shop_id", "shop_slug", "batch_id", "variant",
     "items": [{"dish_id","name","price","qty"}], "total",
     "customer": {"name","phone","address","note"},
     "payment_method", "group_order_id", "status",
     "created_at", "seller_seen_at", "confirmed_at", "delivering_at",
     "done_at", "cancelled_at", "no_show_flagged_at",
     "history": [{"from","to","at"}, ...]}

State machine transitions are the single source of truth in
`shared.order_states` — this module only enforces + persists them (thin
wrapper), so the table lives in exactly one place. `batch_id` is stored on
every order (defaults to "direct" when the buyer didn't arrive via a
QR-tagged flyer) for flyer/batch analytics per the task spec.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from infra.storage import Storage
from shared import order_states as st

ORDERS_COLLECTION = "orders"

DEFAULT_BATCH_ID = "direct"

#: Buyer/seller-facing status message per state (ARCH §3.2 "quán đã thấy đơn").
STATUS_MESSAGES: dict[str, str] = {
    st.CREATED: "Đơn đã gửi tới quán, đang chờ quán xác nhận",
    st.SELLER_SEEN: "Quán đã thấy đơn 👀",
    st.CONFIRMED: "Quán đã xác nhận đơn",
    st.DELIVERING: "Quán đang giao tới bạn",
    st.DONE: "Đơn đã hoàn tất",
    st.CANCELLED: "Đơn đã bị huỷ",
    st.NO_SHOW_FLAGGED: "Quán chưa giao đơn này — đã ghi nhận",
}


class OrderError(Exception):
    pass


class OrderNotFoundError(OrderError):
    pass


class OrderTransitionError(OrderError):
    """Raised on an illegal state-machine move (SPEC §8 transition table)."""

    def __init__(self, current: str, attempted: str) -> None:
        self.current = current
        self.attempted = attempted
        super().__init__(f"cannot move order from {current!r} to {attempted!r}")


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _new_order_id() -> str:
    return f"ord_{uuid.uuid4().hex[:12]}"


def compute_total(items: list[dict[str, Any]]) -> int:
    return sum(int(it["price"]) * int(it["qty"]) for it in items)


def order_summary(order: dict[str, Any]) -> str:
    """Human summary for notify channels (SMS/console): '2x Cơm sườn, 1x Trà đá — 73.000đ'."""
    parts = [f"{it['qty']}x {it['name']}" for it in order.get("items", [])]
    total = order.get("total", 0)
    return f"{', '.join(parts)} — {total:,}đ".replace(",", ".")


class OrderStore:
    """Storage-backed order CRUD + state-machine transitions."""

    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    def create(
        self,
        shop_id: str,
        shop_slug: str,
        items: list[dict[str, Any]],
        customer: dict[str, Any],
        batch_id: str | None = None,
        variant: str | None = None,
        payment_method: str = "cod",
        group_order_id: str | None = None,
    ) -> dict[str, Any]:
        if not items:
            raise OrderError("order cần ít nhất 1 món")
        order_id = _new_order_id()
        now = _now()
        order: dict[str, Any] = {
            "id": order_id,
            "shop_id": shop_id,
            "shop_slug": shop_slug,
            "batch_id": batch_id or DEFAULT_BATCH_ID,
            "variant": variant,
            "items": items,
            "total": compute_total(items),
            "customer": customer,
            "payment_method": payment_method,
            "group_order_id": group_order_id,
            "status": st.CREATED,
            "created_at": now,
            "seller_seen_at": None,
            "confirmed_at": None,
            "delivering_at": None,
            "done_at": None,
            "cancelled_at": None,
            "no_show_flagged_at": None,
            "history": [{"from": None, "to": st.CREATED, "at": now}],
        }
        self.storage.put(ORDERS_COLLECTION, order_id, order)
        return order

    def get(self, order_id: str) -> dict[str, Any]:
        doc = self.storage.get(ORDERS_COLLECTION, order_id)
        if doc is None:
            raise OrderNotFoundError(f"order {order_id!r} không tồn tại")
        return doc

    def list_by_shop(self, shop_slug: str) -> list[dict[str, Any]]:
        out = []
        for order_id in self.storage.list(ORDERS_COLLECTION):
            doc = self.storage.get(ORDERS_COLLECTION, order_id)
            if doc and doc.get("shop_slug") == shop_slug:
                out.append(doc)
        return sorted(out, key=lambda o: o["created_at"])

    def transition(self, order_id: str, next_state: str) -> dict[str, Any]:
        """Move `order_id` to `next_state`. Raises OrderTransitionError if the
        move isn't in `shared.order_states.TRANSITIONS`."""
        order = self.get(order_id)
        current = order["status"]
        if next_state not in st.ORDER_STATES:
            raise OrderError(f"unknown state {next_state!r}")
        if not st.is_valid_transition(current, next_state):
            raise OrderTransitionError(current, next_state)
        now = _now()
        order["status"] = next_state
        order[f"{next_state}_at"] = now
        order["history"].append({"from": current, "to": next_state, "at": now})
        self.storage.put(ORDERS_COLLECTION, order_id, order)
        return order

    def ack(self, order_id: str) -> dict[str, Any]:
        """Seller ack (SLA #1): created -> seller_seen. Idempotent if already
        seen-or-later; raises if the order is in an off-ramp state."""
        order = self.get(order_id)
        if order["status"] == st.CREATED:
            return self.transition(order_id, st.SELLER_SEEN)
        # Already past `created` (seen/confirmed/.../done) or a terminal
        # off-ramp — ack is a no-op, not an error, so a slow double-tap from
        # the seller app (or a race with the ack-timeout watcher) never 409s.
        return order

    def is_seller_seen(self, order_id: str) -> bool:
        """True once the order has left `created` (used by the ack-timeout
        watcher to decide whether the SMS fallback should still fire)."""
        try:
            return self.get(order_id)["status"] != st.CREATED
        except OrderNotFoundError:
            return True  # deleted/missing — don't page anyone about it
