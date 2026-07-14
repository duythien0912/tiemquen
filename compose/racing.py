"""Racing — compose-time ONLY (ENGINE-SPEC §7, ARCH §5.1).

Bắn N compose call GIỐNG NHAU, lấy bản valid đầu tiên, huỷ phần còn lại.
Chỉ dùng ở REAL MODE (LLM output nondeterministic — race để giảm tail latency
+ né output hỏng). KHÔNG race tool-calling (side effects) và KHÔNG race đường
buyer (đường buyer không có LLM call nào để race).

Env: RACE_ENABLED=1 bật, RACE_COUNT=N (default 3).
"""

from __future__ import annotations

import asyncio
import os
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")

DEFAULT_RACE_COUNT = 3


def race_enabled() -> bool:
    return os.environ.get("RACE_ENABLED", "").lower() in {"1", "true", "yes", "on"}


def race_count() -> int:
    try:
        n = int(os.environ.get("RACE_COUNT", DEFAULT_RACE_COUNT))
    except ValueError:
        return DEFAULT_RACE_COUNT
    return max(1, n)


class RaceError(Exception):
    """All N racers failed. Carries the individual errors."""

    def __init__(self, errors: list[BaseException]) -> None:
        super().__init__(f"all {len(errors)} compose racers failed: {errors!r}")
        self.errors = errors


async def race_compose(
    compose_once: Callable[[], Awaitable[T]], n: int | None = None
) -> T:
    """Run `compose_once` N times concurrently; first VALID result wins.

    - `compose_once` must be a zero-arg coroutine factory that either returns a
      validated result or raises (e.g. A2UIValidationError).
    - Losers are cancelled as soon as a winner lands.
    - If every racer raises, RaceError aggregates the failures.
    """
    n = race_count() if n is None else max(1, n)
    tasks = [asyncio.ensure_future(compose_once()) for _ in range(n)]
    errors: list[BaseException] = []
    try:
        for fut in asyncio.as_completed(tasks):
            try:
                return await fut
            except asyncio.CancelledError:  # racer cancelled from outside
                raise
            except Exception as e:  # invalid output -> keep waiting on the rest
                errors.append(e)
        raise RaceError(errors)
    finally:
        for t in tasks:  # cancel losers (and stragglers on failure)
            if not t.done():
                t.cancel()
        # Let cancellations propagate so no task leaks past return.
        await asyncio.gather(*tasks, return_exceptions=True)


def race_sync(compose_once_sync: Callable[[], T], n: int | None = None) -> T:
    """Race a BLOCKING compose function from sync code (thread-per-racer)."""

    async def _runner() -> T:
        async def one() -> T:
            return await asyncio.to_thread(compose_once_sync)

        return await race_compose(one, n)

    return asyncio.run(_runner())
