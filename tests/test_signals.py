"""Sinyal motoru testleri — kurallar, cooldown ve uçtan uca motor."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from macro_sentiment.core.models import Emotion, SentimentScore, SignalType, SourceType
from macro_sentiment.signals.aggregator import WindowAggregate
from macro_sentiment.signals.baseline import Baseline, compute_baseline, zscore
from macro_sentiment.signals.engine import SignalEngine
from macro_sentiment.signals.rules import EuphoriaRule, FedToneRule, PanicRule
from macro_sentiment.signals.scorer import Cooldown
from macro_sentiment.storage.db import dispose_db, init_db
from macro_sentiment.storage.repositories import SentimentRepository, SignalRepository


def _agg(entity, pol, fear=0.0, greed=0.0, vol=5):
    return WindowAggregate(entity, "recent", vol, pol, 80.0, fear, greed, 0.7)


def _score(entity, pol, fear=0.0, greed=0.0):
    now = datetime.now(timezone.utc)
    return SentimentScore(
        doc_id=f"d-{entity}-{pol}", entity=entity, polarity=pol, intensity=90.0,
        emotion=Emotion(fear=fear, greed=greed), confidence=0.8,
        model_version="test", source_type=SourceType.NEWS, created_at=now,
    )


# --- baseline ---

def test_zscore_and_baseline():
    b = compute_baseline([10, 10, 10, 10, 30])
    assert b.n == 5 and b.std > 0
    assert zscore(30, b) > 0
    assert zscore(5, Baseline(0, 0, 0)) == 0.0  # std=0 güvenli


# --- kurallar ---

def test_panic_rule_fires_on_fear():
    sig = PanicRule().evaluate(_agg("BTC", pol=-0.8, fear=0.9))
    assert sig and sig.type == SignalType.PANIC and sig.severity > 0
    assert "panik" in sig.headline.lower()


def test_panic_rule_silent_when_positive():
    assert PanicRule().evaluate(_agg("BTC", pol=0.5, fear=0.1)) is None


def test_euphoria_rule_fires():
    sig = EuphoriaRule().evaluate(_agg("AAPL", pol=0.8, greed=0.7))
    assert sig and sig.type == SignalType.EUPHORIA


def test_fed_tone_hawkish():
    sig = FedToneRule().evaluate(_agg("FED", pol=-0.6))
    assert sig and sig.type == SignalType.FED_TONE
    assert "hawkish" in sig.headline.lower()


def test_fed_tone_ignores_non_fed():
    assert FedToneRule().evaluate(_agg("AAPL", pol=-0.6)) is None


# --- cooldown ---

def test_cooldown_blocks_repeat():
    cd = Cooldown(cooldown_seconds=3600)
    sig = PanicRule().evaluate(_agg("BTC", pol=-0.8, fear=0.9))
    assert cd.should_emit(sig) is True
    assert cd.should_emit(sig) is False  # aynı (varlık,tip) → susturma


# --- uçtan uca motor ---

@pytest.mark.asyncio
async def test_engine_emits_and_persists():
    await init_db()
    sent_repo, sig_repo = SentimentRepository(), SignalRepository()
    # negatif + korkulu küme (BTC) ve pozitif + açgözlü küme (AAPL)
    for _ in range(3):
        await sent_repo.save(_score("BTC", -0.9, fear=0.9))
        await sent_repo.save(_score("AAPL", 0.8, greed=0.7))

    engine = SignalEngine(sent_repo=sent_repo, sig_repo=sig_repo)
    sigs = await engine.evaluate_entities(["BTC", "AAPL"])
    types = {s.type for s in sigs}
    assert SignalType.PANIC in types
    assert SignalType.EUPHORIA in types

    stored = await sig_repo.query(entity="BTC")
    assert stored and stored[0].type == SignalType.PANIC
    await dispose_db()
