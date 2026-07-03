"""HITL inceleme kuyruğu testleri (Faz 11) — pending→approved/rejected akışı,
dağıtım susturma, katı modda CAS şok filtreleme.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from macro_sentiment.api.main import app
from macro_sentiment.api.sentiment_feed import SentimentFeed
from macro_sentiment.core.models import Emotion, SentimentScore, SignalType, SourceType
from macro_sentiment.signals.engine import SignalEngine
from macro_sentiment.signals.review import APPROVED, PENDING, REJECTED, needs_review
from macro_sentiment.storage.db import dispose_db, init_db
from macro_sentiment.storage.repositories import FeedbackRepository, SentimentRepository, SignalRepository


def _score(entity, pol, fear=0.0, greed=0.0):
    now = datetime.now(timezone.utc)
    return SentimentScore(
        doc_id=f"d-{entity}-{pol}-{now.timestamp()}", entity=entity, polarity=pol, intensity=90.0,
        emotion=Emotion(fear=fear, greed=greed), confidence=0.8,
        model_version="test", source_type=SourceType.NEWS, created_at=now,
    )


class _CountingDispatcher:
    def __init__(self) -> None:
        self.dispatched = []

    async def dispatch(self, signal) -> int:
        self.dispatched.append(signal)
        return 1


# ---- needs_review() — saf fonksiyon ------------------------------------------------

def test_needs_review_threshold():
    from macro_sentiment.core.models import Signal

    now = datetime.now(timezone.utc)
    low = Signal(id="a", entity="X", type=SignalType.PANIC, severity=30.0, direction=-0.5, window="w", headline="h", created_at=now)
    high = Signal(id="b", entity="X", type=SignalType.PANIC, severity=90.0, direction=-0.5, window="w", headline="h", created_at=now)
    assert needs_review(low) is False
    assert needs_review(high) is True


# ---- SignalEngine — yüksek etkili sinyaller dağıtılmaz, DB'de görünür --------------

@pytest.mark.asyncio
async def test_high_severity_signal_marked_pending_and_not_dispatched():
    await init_db()
    sent_repo, sig_repo = SentimentRepository(), SignalRepository()
    for _ in range(5):
        await sent_repo.save(_score("PANICX", -0.95, fear=0.95))  # yüksek şiddet üretir

    dispatcher = _CountingDispatcher()
    engine = SignalEngine(sent_repo=sent_repo, sig_repo=sig_repo, dispatcher=dispatcher)
    sigs = await engine.evaluate_entity("PANICX")

    panic = next(s for s in sigs if s.type == SignalType.PANIC)
    assert panic.severity >= 70.0
    assert panic.review_status == PENDING
    assert dispatcher.dispatched == []  # dağıtılmadı

    stored = await sig_repo.query(entity="PANICX", review_status=PENDING)
    assert stored and stored[0].id == panic.id
    await dispose_db()


@pytest.mark.asyncio
async def test_low_severity_signal_not_pending_and_dispatched():
    await init_db()
    sent_repo, sig_repo = SentimentRepository(), SignalRepository()
    await sent_repo.save(_score("MILDX", -0.4, fear=0.55))  # eşiğin altında şiddet

    dispatcher = _CountingDispatcher()
    engine = SignalEngine(sent_repo=sent_repo, sig_repo=sig_repo, dispatcher=dispatcher)
    sigs = await engine.evaluate_entity("MILDX")

    panic = next((s for s in sigs if s.type == SignalType.PANIC), None)
    if panic is not None:
        assert panic.review_status is None
        assert dispatcher.dispatched  # dağıtıldı
    await dispose_db()


# ---- REST: /v1/review/pending, approve, reject -------------------------------------

@pytest.mark.asyncio
async def test_review_api_pending_approve_reject_flow():
    await init_db()
    sent_repo, sig_repo = SentimentRepository(), SignalRepository()
    for _ in range(5):
        await sent_repo.save(_score("APIX", -0.95, fear=0.95))
    engine = SignalEngine(sent_repo=sent_repo, sig_repo=sig_repo)
    sigs = await engine.evaluate_entity("APIX")
    panic = next(s for s in sigs if s.type == SignalType.PANIC)
    assert panic.review_status == PENDING

    with TestClient(app) as c:
        pending = c.get("/v1/review/pending").json()
        assert any(s["id"] == panic.id for s in pending)

        resp = c.post(f"/v1/review/{panic.id}/approve", params={"reviewer": "mert"})
        assert resp.status_code == 200
        assert resp.json()["review_status"] == APPROVED

        # onaylanan artık pending listesinde olmamalı
        pending_after = c.get("/v1/review/pending").json()
        assert not any(s["id"] == panic.id for s in pending_after)

        resp_404 = c.post("/v1/review/does-not-exist/reject")
        assert resp_404.status_code == 404

    feedback = await FeedbackRepository().all(entity="APIX")
    assert feedback and feedback[0].decision == APPROVED
    assert feedback[0].reviewer == "mert"
    await dispose_db()


@pytest.mark.asyncio
async def test_reject_sets_rejected_status():
    await init_db()
    sent_repo, sig_repo = SentimentRepository(), SignalRepository()
    for _ in range(5):
        await sent_repo.save(_score("REJX", -0.95, fear=0.95))
    engine = SignalEngine(sent_repo=sent_repo, sig_repo=sig_repo)
    sigs = await engine.evaluate_entity("REJX")
    panic = next(s for s in sigs if s.type == SignalType.PANIC)

    with TestClient(app) as c:
        resp = c.post(f"/v1/review/{panic.id}/reject")
        assert resp.json()["review_status"] == REJECTED
    await dispose_db()


# ---- Katı mod: yalnız onaylı sinyaller şok olur ------------------------------------

@pytest.mark.asyncio
async def test_strict_review_mode_excludes_pending_and_rejected_shocks():
    await init_db()
    sent_repo, sig_repo = SentimentRepository(), SignalRepository()
    for _ in range(5):
        await sent_repo.save(_score("STRICTX", -0.95, fear=0.95))
    engine = SignalEngine(sent_repo=sent_repo, sig_repo=sig_repo)
    sigs = await engine.evaluate_entity("STRICTX")
    panic = next(s for s in sigs if s.type == SignalType.PANIC)
    assert panic.review_status == PENDING

    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)

    lenient_feed = SentimentFeed(mode="live", sent_repo=sent_repo, sig_repo=sig_repo, strict_review=False)
    assert any(s.entity == "STRICTX" for s in lenient_feed.shocks(epoch))

    strict_feed = SentimentFeed(mode="live", sent_repo=sent_repo, sig_repo=sig_repo, strict_review=True)
    assert not any(s.entity == "STRICTX" for s in strict_feed.shocks(epoch))

    await SignalRepository().set_review_status(panic.id, APPROVED)
    strict_feed_after = SentimentFeed(mode="live", sent_repo=sent_repo, sig_repo=sig_repo, strict_review=True)
    assert any(s.entity == "STRICTX" for s in strict_feed_after.shocks(epoch))
    await dispose_db()
