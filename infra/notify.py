"""Notify pipeline (ENGINE-SPEC §8, ARCH §3.2 "SLA số 1").

On `created`: push through the channel chain `[FCMWebPushStub, ConsoleChannel]`
(both fire immediately — FCM is the real-world primary, Console is the dev
stand-in for "seller app open in a tab", so both always get the ping in dev).
Separately, an ack-timeout watcher sleeps `ACK_TIMEOUT_SECONDS` (env, default
120; tests use 0.1) then — only if the order hasn't reached `seller_seen`
yet — fires `SMSStubChannel` as the fallback.

All three channels implement the same `Channel` interface
(`send(target, message)`), so a real FCM/SMS adapter drops in later without
touching `NotifyPipeline` — see ARCH §5.4 "adapter thay được, không đổi giao
diện".
"""

from __future__ import annotations

import asyncio
import os
from abc import ABC, abstractmethod
from typing import Any, Callable

from infra.orders import order_summary

ACK_TIMEOUT_ENV = "ACK_TIMEOUT_SECONDS"
DEFAULT_ACK_TIMEOUT_SECONDS = 120.0


def default_ack_timeout() -> float:
    return float(os.environ.get(ACK_TIMEOUT_ENV, DEFAULT_ACK_TIMEOUT_SECONDS))


class Channel(ABC):
    """One notify transport. `target` = seller phone number (SMS/FCM key)."""

    @abstractmethod
    def send(self, target: str, message: str) -> None: ...


class FCMWebPushStub(Channel):
    """Stub for the real-world primary channel (FCM web push to the seller
    app tab). Dev/MVP: no GCP project wired up yet — logs what WOULD be sent
    so the shape of the call site never has to change when it's real."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, target: str, message: str) -> None:
        self.sent.append((target, message))
        print(f"[fcm-stub] push -> seller {target}: {message}")


class ConsoleChannel(Channel):
    """Dev stand-in for "seller has the dashboard open in a tab" — always
    fires alongside FCM so nothing is silently swallowed in mock mode."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, target: str, message: str) -> None:
        self.sent.append((target, message))
        print(f"[console] notify seller {target}: {message}")


class SMSStubChannel(Channel):
    """Fallback fired by the ack-timeout watcher. Pilot's ACTUAL primary
    channel per ARCH §5.4 (~700đ/tin) — real Viettel/ESMS adapter drops in
    here later behind the same `send()` signature."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, target: str, message: str) -> None:
        self.sent.append((target, message))
        print(f"SMS to {target}: {message}")


class NotifyPipeline:
    """Wires the created-chain + ack-timeout watcher together.

    Framework-agnostic: `watch_ack` is a plain coroutine so tests can
    `asyncio.run(...)` it directly, and FastAPI can hand it to
    `BackgroundTasks.add_task` without any adapter shim.
    """

    def __init__(
        self,
        created_chain: list[Channel] | None = None,
        fallback_channel: Channel | None = None,
        ack_timeout: float | None = None,
    ) -> None:
        self.created_chain: list[Channel] = created_chain or [FCMWebPushStub(), ConsoleChannel()]
        self.fallback_channel: Channel = fallback_channel or SMSStubChannel()
        self._ack_timeout = ack_timeout

    @property
    def ack_timeout(self) -> float:
        # Read the env lazily (not at __init__ time) so tests can set
        # ACK_TIMEOUT_SECONDS via monkeypatch before the first order fires.
        return self._ack_timeout if self._ack_timeout is not None else default_ack_timeout()

    def notify_created(self, seller_phone: str, order: dict[str, Any]) -> None:
        """SPEC §8: fire on `created`, synchronously, through the whole chain."""
        message = order_summary(order)
        for channel in self.created_chain:
            channel.send(seller_phone, message)

    async def watch_ack(
        self,
        seller_phone: str,
        order: dict[str, Any],
        is_seller_seen: Callable[[], bool],
    ) -> bool:
        """Sleep `ack_timeout`; if `is_seller_seen()` is still False, fire the
        SMS fallback. Returns True if the fallback fired (handy for tests)."""
        await asyncio.sleep(self.ack_timeout)
        if is_seller_seen():
            return False
        self.fallback_channel.send(seller_phone, order_summary(order))
        return True
