"""SentimentFeed adaptörü testleri (CAS köprüsü) — ağ/torch/DB gerektirmez."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from macro_sentiment.api.cas_contracts import SHOCK_KINDS, SentimentState, ShockEvent
from macro_sentiment.api.sentiment_feed import (
    DECAY_HALFLIFE_S,
    SentimentFeed,
    aggregate_to_state,
)
from macro_sentiment.core.models import (
    Emotion,
    SentimentScore,
    Signal,
    SignalType,
    SourceType,
)
from macro_sentiment.signals.aggregator import aggregate

UTC = timezone.utc


def _score(entity, pol, src=SourceType.NEWS, fear=0.0, greed=0.0, unc=0.0, conf=0.8):
    return SentimentScore(
        doc_id="d1", entity=entity, polarity=pol, intensity=50.0,
        emotion=Emotion(fear=fear, greed=greed, uncertainty=unc),
        confidence=conf, model_version="test@1", source_type=src,
        created_at=datetime.now(UTC),
    )


# ---- offline sentetik --------------------------------------------------------

def test_offline_synthetic_valid_and_deterministic():
    feed = SentimentFeed(mode="offline")
    a = feed.latest("BTC")
    b = feed.latest("BTC")
    assert isinstance(a, SentimentState)
    assert -1.0 <= a.polarity <= 1.0 and 0.0 <= a.intensity <= 100.0
    assert set(a.emotion) == {"fear", "greed", "uncertainty"}
    assert 0.0 <= a.confidence <= 1.0
    # Aynı dakika içinde deterministik.
    assert a.polarity == b.polarity and a.intensity == b.intensity


def test_offline_shocks_empty_without_scenario():
    feed = SentimentFeed(mode="offline")
    assert feed.shocks(datetime.now(UTC) - timedelta(hours=1)) == []


def test_invalid_mode_raises():
    with pytest.raises(ValueError):
        SentimentFeed(mode="bogus")


# ---- fed_tone işaret çevrimi -------------------------------------------------

def test_fed_tone_sign_flip_hawkish():
    # İç konvansiyon: negatif polarite = hawkish. Sözleşme: hawkish = +1.
    scores = [_score("FED", -0.6, src=SourceType.FED)]
    state = aggregate_to_state(aggregate("FED", scores))
    assert state.fed_tone is not None and state.fed_tone > 0  # hawkish → pozitif


def test_fed_tone_none_for_non_fed():
    state = aggregate_to_state(aggregate("BTC", [_score("BTC", -0.6)]))
    assert state.fed_tone is None


def test_source_breakdown_grouping():
    scores = [
        _score("BTC", -0.8, src=SourceType.NEWS),
        _score("BTC", -0.2, src=SourceType.SOCIAL),
    ]
    state = aggregate_to_state(aggregate("BTC", scores))
    assert set(state.source_breakdown) == {"news", "social"}
    assert state.source_breakdown["news"] == pytest.approx(-0.8)


# ---- live mod (enjekte edilmiş sahte repolar) --------------------------------

class _FakeSentRepo:
    def __init__(self, scores):
        self._scores = scores

    async def recent_for_entity(self, entity, limit=50):
        return [s for s in self._scores if s.entity == entity][:limit]


class _FakeSigRepo:
    def __init__(self, signals):
        self._signals = signals

    async def query(self, entity=None, since=None, limit=50):
        rows = self._signals
        if since is not None:
            rows = [s for s in rows if s.created_at >= since]
        return rows[:limit]


@pytest.mark.asyncio
async def test_live_latest_from_repo():
    scores = [_score("BTC", -0.5, fear=0.7, unc=0.3), _score("BTC", -0.3, fear=0.5)]
    feed = SentimentFeed(mode="live", sent_repo=_FakeSentRepo(scores))
    st = feed.latest("BTC")
    assert st.entity == "BTC"
    assert st.polarity == pytest.approx(-0.4, abs=1e-6)
    assert st.emotion["fear"] == pytest.approx(0.6, abs=1e-6)


@pytest.mark.asyncio
async def test_live_shocks_map_and_filter():
    now = datetime.now(UTC)

    def sig(t, sev):
        return Signal(id="s", entity="BTC", type=t, severity=sev, direction=-0.5,
                      window="w", headline="h", payload={}, created_at=now)

    signals = [
        sig(SignalType.PANIC, 80),
        sig(SignalType.NARRATIVE, 60),
        sig(SignalType.BREAKOUT, 90),  # sözleşme dışı → düşürülmeli
    ]
    feed = SentimentFeed(mode="live", sig_repo=_FakeSigRepo(signals))
    shocks = feed.shocks(now - timedelta(hours=1))
    kinds = {s.kind for s in shocks}
    assert kinds == {"panic", "narrative_shift"}  # breakout yok
    assert all(isinstance(s, ShockEvent) for s in shocks)
    panic = next(s for s in shocks if s.kind == "panic")
    assert panic.magnitude == pytest.approx(0.8)
    assert panic.decay_halflife_s == DECAY_HALFLIFE_S["panic"]


def test_decay_map_covers_all_kinds():
    assert set(DECAY_HALFLIFE_S) == set(SHOCK_KINDS)
