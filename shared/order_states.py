"""Order state machine states (ENGINE-SPEC §8).

Happy path:  created -> seller_seen -> confirmed -> delivering -> done
Off-ramps:   cancelled (any active state), no_show_flagged (quán nhận đơn mà không giao).

Notify pipeline hooks on `created` (FCM push -> 120s no ack -> SMS).
Buyer polls for `seller_seen` to show "quán đã thấy đơn".
"""

from __future__ import annotations

CREATED = "created"
SELLER_SEEN = "seller_seen"
CONFIRMED = "confirmed"
DELIVERING = "delivering"
DONE = "done"
CANCELLED = "cancelled"
NO_SHOW_FLAGGED = "no_show_flagged"

#: All states, happy path first.
ORDER_STATES: tuple[str, ...] = (
    CREATED,
    SELLER_SEEN,
    CONFIRMED,
    DELIVERING,
    DONE,
    CANCELLED,
    NO_SHOW_FLAGGED,
)

#: States an order can never leave.
TERMINAL_STATES: frozenset[str] = frozenset({DONE, CANCELLED, NO_SHOW_FLAGGED})

#: Allowed transitions: current state -> set of next states.
TRANSITIONS: dict[str, frozenset[str]] = {
    CREATED: frozenset({SELLER_SEEN, CANCELLED}),
    SELLER_SEEN: frozenset({CONFIRMED, CANCELLED}),
    CONFIRMED: frozenset({DELIVERING, CANCELLED, NO_SHOW_FLAGGED}),
    DELIVERING: frozenset({DONE, NO_SHOW_FLAGGED}),
    DONE: frozenset(),
    CANCELLED: frozenset(),
    NO_SHOW_FLAGGED: frozenset(),
}

#: State whose entry must trigger the seller-notify pipeline (SLA số 1).
NOTIFY_ON_ENTER = CREATED


def is_valid_transition(current: str, nxt: str) -> bool:
    """Return True if moving `current` -> `nxt` is allowed."""
    return nxt in TRANSITIONS.get(current, frozenset())


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES
