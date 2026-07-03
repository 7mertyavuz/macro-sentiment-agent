"""Kalıcı taban çizgisi testleri (Faz 10) — BaselineRepository + SignalEngine.

Roadmap "bitti tanımı": (1) baseline DB'den okunur/yazılır, yeniden başlatmada
korunur, (2) rolling z-score sinyal şiddetini etkiler, (3) SQLite dev testleri
yeşil kalır (bu dosyanın kendisi SQLite üzerinde çalışır).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from macro_sentiment.core.models import Emotion, SentimentScore, SignalType, SourceType
from macro_sentiment.signals.baseline import Baseline
from macro_sentiment.signals.engine import VOLUME_METRIC, SignalEngine
from macro_sentiment.signals.scorer import Cooldown
from macro_sentiment.storage.db import dispose_db, init_db
from macro_sentiment.storage.repositories import BaselineRepository, SentimentRepository, SignalRepository


def _score(entity, pol, fear=0.0, greed=0.0):
    now = datetime.now(timezone.utc)
    return SentimentScore(
        doc_id=f"d-{entity}-{pol}-{now.timestamp()}", entity=entity, polarity=pol, intensity=90.0,
        emotion=Emotion(fear=fear, greed=greed), confidence=0.8,
        model_version="test", source_type=SourceType.NEWS, created_at=now,
    )


# ---- BaselineRepository — okuma/yazma -----------------------------------------------

@pytest.mark.asyncio
async def test_get_unseen_entity_returns_default_baseline():
    await init_db()
    repo = BaselineRepository()
    b = await repo.get("UNKNOWN_ENTITY_X", VOLUME_METRIC)
    assert b == Baseline(0.0, 0.0, 0)
    await dispose_db()


@pytest.mark.asyncio
async def test_update_persists_and_get_reflects_it():
    await init_db()
    repo = BaselineRepository()
    b1 = await repo.update("AAPL", VOLUME_METRIC, 10.0)
    assert b1.n == 1 and b1.mean == 10.0

    b2 = await repo.update("AAPL", VOLUME_METRIC, 20.0)
    assert b2.n == 2
    assert b2.mean == pytest.approx(15.0)

    read_back = await repo.get("AAPL", VOLUME_METRIC)
    assert read_back.n == 2
    assert read_back.mean == pytest.approx(15.0)
    await dispose_db()


@pytest.mark.asyncio
async def test_baseline_survives_restart():
    """Aynı DATABASE_URL ile dispose_db() + init_db() bir 'yeniden başlatma'yı simüle eder."""
    await init_db()
    repo = BaselineRepository()
    await repo.update("MSFT", VOLUME_METRIC, 5.0)
    await repo.update("MSFT", VOLUME_METRIC, 7.0)
    await dispose_db()

    # "yeniden başlatma" — yeni engine/session, aynı dosya
    await init_db()
    repo2 = BaselineRepository()
    restored = await repo2.get("MSFT", VOLUME_METRIC)
    assert restored.n == 2
    assert restored.mean == pytest.approx(6.0)
    await dispose_db()


@pytest.mark.asyncio
async def test_different_metrics_are_independent():
    await init_db()
    repo = BaselineRepository()
    await repo.update("BTC", "volume", 100.0)
    await repo.update("BTC", "intensity", 50.0)
    vol = await repo.get("BTC", "volume")
    inten = await repo.get("BTC", "intensity")
    assert vol.mean == pytest.approx(100.0)
    assert inten.mean == pytest.approx(50.0)
    await dispose_db()


# ---- SignalEngine — otomatik kalıcı baseline + rolling z-skor -----------------------

@pytest.mark.asyncio
async def test_engine_without_explicit_baseline_persists_volume():
    await init_db()
    sent_repo, sig_repo = SentimentRepository(), SignalRepository()
    for _ in range(3):
        await sent_repo.save(_score("ENGN", -0.9, fear=0.9))

    engine = SignalEngine(sent_repo=sent_repo, sig_repo=sig_repo)
    await engine.evaluate_entity("ENGN")  # volume_baseline verilmedi -> otomatik kalıcı yol

    baseline = await BaselineRepository().get("ENGN", VOLUME_METRIC)
    assert baseline.n == 1
    assert baseline.mean == pytest.approx(3.0)  # bu turda 3 skor -> volume=3
    await dispose_db()


@pytest.mark.asyncio
async def test_engine_explicit_baseline_does_not_touch_db():
    """Geriye uyum: volume_baseline açıkça verilirse DB'ye dokunulmaz (eski davranış)."""
    await init_db()
    sent_repo, sig_repo = SentimentRepository(), SignalRepository()
    await sent_repo.save(_score("LEGACY", -0.9, fear=0.9))

    engine = SignalEngine(sent_repo=sent_repo, sig_repo=sig_repo)
    manual_baseline = Baseline(mean=1.0, std=0.5, n=10)
    await engine.evaluate_entity("LEGACY", volume_baseline=manual_baseline)

    baseline = await BaselineRepository().get("LEGACY", VOLUME_METRIC)
    assert baseline == Baseline(0.0, 0.0, 0)  # yazılmadı
    await dispose_db()


@pytest.mark.asyncio
async def test_rolling_zscore_influences_signal_severity_across_runs():
    """Hacim taban çizgisi zamanla oturunca, ani bir hacim artışı yüksek z-skor -> daha şiddetli sinyal verir."""
    await init_db()
    sent_repo, sig_repo = SentimentRepository(), SignalRepository()
    # Cooldown=0 -> her turda tekrar tekrar aynı (varlık,tip) sinyali yayınlanabilir
    # (bu test yalnızca hacim z-skorunu izliyor, susturma davranışını değil).
    engine = SignalEngine(sent_repo=sent_repo, sig_repo=sig_repo, cooldown=Cooldown(cooldown_seconds=0))

    # Taban çizgisini düşük/istikrarlı hacimle ısıt (birkaç tur, sabit hacim=2).
    for _ in range(5):
        sent_repo_scores = [_score("ROLL", -0.9, fear=0.9) for _ in range(2)]
        for s in sent_repo_scores:
            await sent_repo.save(s)
        await engine.evaluate_entity("ROLL")

    baseline_before_spike = await BaselineRepository().get("ROLL", VOLUME_METRIC)
    assert baseline_before_spike.n == 5

    # Ani hacim patlaması: aynı entity için çok daha fazla skor ekle.
    for _ in range(20):
        await sent_repo.save(_score("ROLL", -0.9, fear=0.9))

    sigs = await engine.evaluate_entity("ROLL")
    panic = next(s for s in sigs if s.type == SignalType.PANIC)
    assert panic.payload["volume_z"] > 0  # hacim patlaması pozitif z-skor üretmeli
    await dispose_db()
