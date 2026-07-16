"""Notify pipeline — created-chain fires immediately; SMS fallback only fires
if the ack-timeout elapses without `seller_seen` (ENGINE-SPEC §8, ARCH §3.2
"SLA số 1"). Uses a 0.1s timeout so the suite stays fast."""

import asyncio

from infra.notify import ConsoleChannel, FCMWebPushStub, NotifyPipeline, SMSStubChannel


def _order():
    return {
        "id": "ord_test1",
        "items": [{"dish_id": "d1", "name": "Cơm sườn", "price": 35000, "qty": 1}],
        "total": 35000,
    }


def test_notify_created_fires_whole_chain_immediately():
    fcm, console = FCMWebPushStub(), ConsoleChannel()
    pipeline = NotifyPipeline(created_chain=[fcm, console])
    pipeline.notify_created("0909000111", _order())
    assert fcm.sent == [("0909000111", "1x Cơm sườn — 35.000đ")]
    assert console.sent == [("0909000111", "1x Cơm sườn — 35.000đ")]


def test_ack_timeout_fires_sms_when_not_seen():
    sms = SMSStubChannel()
    pipeline = NotifyPipeline(fallback_channel=sms, ack_timeout=0.05)

    async def run():
        fired = await pipeline.watch_ack("0909000111", _order(), lambda: False)
        assert fired is True

    asyncio.run(run())
    assert sms.sent == [("0909000111", "1x Cơm sườn — 35.000đ")]


def test_ack_before_timeout_suppresses_sms():
    sms = SMSStubChannel()
    pipeline = NotifyPipeline(fallback_channel=sms, ack_timeout=0.05)

    async def run():
        fired = await pipeline.watch_ack("0909000111", _order(), lambda: True)
        assert fired is False

    asyncio.run(run())
    assert sms.sent == []


def test_ack_timeout_defaults_from_env(monkeypatch):
    monkeypatch.setenv("ACK_TIMEOUT_SECONDS", "0.05")
    pipeline = NotifyPipeline()
    assert pipeline.ack_timeout == 0.05


def test_ack_timeout_env_default_is_120_seconds(monkeypatch):
    monkeypatch.delenv("ACK_TIMEOUT_SECONDS", raising=False)
    pipeline = NotifyPipeline()
    assert pipeline.ack_timeout == 120.0


def test_explicit_ack_timeout_overrides_env(monkeypatch):
    monkeypatch.setenv("ACK_TIMEOUT_SECONDS", "120")
    pipeline = NotifyPipeline(ack_timeout=0.1)
    assert pipeline.ack_timeout == 0.1


def test_race_seller_seen_flips_mid_wait():
    """A realistic race: seller acks WHILE the timer is asleep. The callback
    reads live state, so a flip that lands before the sleep ends must still
    suppress the SMS."""
    sms = SMSStubChannel()
    pipeline = NotifyPipeline(fallback_channel=sms, ack_timeout=0.05)
    state = {"seen": False}

    async def flip_soon():
        await asyncio.sleep(0.01)
        state["seen"] = True

    async def run():
        await asyncio.gather(
            pipeline.watch_ack("0909000111", _order(), lambda: state["seen"]),
            flip_soon(),
        )

    asyncio.run(run())
    assert sms.sent == []
