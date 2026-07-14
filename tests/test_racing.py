"""Racing (compose-time only): first valid wins, losers cancelled."""

import asyncio

import pytest

from compose.racing import RaceError, race_compose, race_count, race_enabled


def test_race_env_flags(monkeypatch):
    monkeypatch.delenv("RACE_ENABLED", raising=False)
    assert race_enabled() is False
    monkeypatch.setenv("RACE_ENABLED", "1")
    assert race_enabled() is True
    monkeypatch.setenv("RACE_COUNT", "5")
    assert race_count() == 5
    monkeypatch.setenv("RACE_COUNT", "rác")
    assert race_count() == 3  # default
    monkeypatch.setenv("RACE_COUNT", "0")
    assert race_count() == 1  # floor


def test_first_valid_wins_and_losers_cancelled():
    started = 0
    cancelled = 0

    async def compose_once():
        nonlocal started, cancelled
        started += 1
        me = started
        try:
            # racer #1 is fast+valid; others would take forever
            await asyncio.sleep(0 if me == 1 else 60)
            return ["ok", me]
        except asyncio.CancelledError:
            cancelled += 1
            raise

    result = asyncio.run(race_compose(compose_once, n=3))
    assert result == ["ok", 1]
    assert started == 3
    assert cancelled == 2  # losers did not run to completion


def test_invalid_results_are_skipped_until_a_valid_one():
    calls = 0

    async def compose_once():
        nonlocal calls
        calls += 1
        me = calls
        await asyncio.sleep(0.01 * me)
        if me < 3:
            raise ValueError(f"racer {me} produced invalid A2UI")
        return "valid"

    assert asyncio.run(race_compose(compose_once, n=3)) == "valid"


def test_all_racers_fail_raises_race_error():
    async def compose_once():
        raise ValueError("hỏng")

    with pytest.raises(RaceError) as exc:
        asyncio.run(race_compose(compose_once, n=3))
    assert len(exc.value.errors) == 3
