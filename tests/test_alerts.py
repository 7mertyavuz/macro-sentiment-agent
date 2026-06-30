"""Uyarı kanalları ve dağıtıcı testleri."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from macro_sentiment.api.alerts import AlertDispatcher, format_signal
from macro_sentiment.core.models import Signal, SignalType


def _sig(severity: float) -> Signal:
    return Signal(
        id="s1", entity="BTC", type=SignalType.PANIC, severity=severity, direction=-0.8,
        window="recent", headline="BTC — aşırı korku", created_at=datetime.now(timezone.utc),
    )


class FakeChannel:
    def __init__(self): self.sent = []
    async def send(self, signal): self.sent.append(signal)


class FailingChannel:
    async def send(self, signal): raise RuntimeError("kanal hatası")


def test_format_signal_contains_type_and_headline():
    txt = format_signal(_sig(90))
    assert "PANIC" in txt and "aşırı korku" in txt


@pytest.mark.asyncio
async def test_dispatch_fans_out_to_all_channels():
    a, b = FakeChannel(), FakeChannel()
    d = AlertDispatcher([a, b], min_severity=50)
    sent = await d.dispatch(_sig(90))
    assert sent == 2 and len(a.sent) == 1 and len(b.sent) == 1


@pytest.mark.asyncio
async def test_dispatch_respects_min_severity():
    a = FakeChannel()
    d = AlertDispatcher([a], min_severity=80)
    assert await d.dispatch(_sig(60)) == 0
    assert a.sent == []


@pytest.mark.asyncio
async def test_dispatch_isolates_channel_failure():
    good, bad = FakeChannel(), FailingChannel()
    d = AlertDispatcher([bad, good], min_severity=0)
    sent = await d.dispatch(_sig(90))
    assert sent == 1 and len(good.sent) == 1  # biri patlasa diğeri çalışır
