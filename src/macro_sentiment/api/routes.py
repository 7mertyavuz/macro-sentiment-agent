"""REST uç noktaları — sinyal ve duyarlılık sorguları."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from ..core.models import Signal
from ..signals.review import APPROVED, PENDING, REJECTED, ReviewFeedback
from ..storage.repositories import FeedbackRepository, SentimentRepository, SignalRepository
from .cas_transport import CAS_SCHEMA_VERSION, sentiment_state_to_dict, shock_event_to_dict
from .sentiment_feed import SentimentFeed

router = APIRouter(prefix="/v1", tags=["signals"])
cas_router = APIRouter(prefix="/v1/cas", tags=["cas"])
review_router = APIRouter(prefix="/v1/review", tags=["review"])


@router.get("/signals", response_model=list[Signal])
async def list_signals(
    entity: str | None = Query(None, description="Varlık/ticker filtresi"),
    since: datetime | None = Query(None),
    limit: int = Query(50, le=500),
) -> list[Signal]:
    return await SignalRepository().query(entity=entity, since=since, limit=limit)


@router.get("/sentiment/{entity}")
async def get_sentiment(entity: str, limit: int = Query(50, le=500)) -> dict:
    scores = await SentimentRepository().recent_for_entity(entity, limit=limit)
    if not scores:
        return {"entity": entity, "count": 0, "avg_polarity": None, "scores": []}
    avg = sum(s.polarity for s in scores) / len(scores)
    return {
        "entity": entity,
        "count": len(scores),
        "avg_polarity": round(avg, 4),
        "scores": [s.model_dump(mode="json") for s in scores],
    }


# ---- CAS köprüsü HTTP uçları (Faz 6) -------------------------------------------
# DB'ye erişilemezse (bağlantı hatası, tablo yok, ...) sessizce offline moda
# düşer; her iki uç da anahtar/DB olmadan geçerli JSON döndürür.

@cas_router.get("/sentiment/{entity}")
async def cas_sentiment(entity: str) -> dict:
    try:
        state = SentimentFeed(mode="live").latest(entity)
        mode = "live"
    except Exception:
        state = SentimentFeed(mode="offline").latest(entity)
        mode = "offline"
    return {"mode": mode, **sentiment_state_to_dict(state)}


@cas_router.get("/shocks")
async def cas_shocks(
    since: datetime | None = Query(None, description="ISO8601; varsayılan son 24 saat"),
) -> dict:
    since_ts = since or (datetime.now(timezone.utc) - timedelta(hours=24))
    if since_ts.tzinfo is None:
        since_ts = since_ts.replace(tzinfo=timezone.utc)
    try:
        shocks = SentimentFeed(mode="live").shocks(since_ts)
        mode = "live"
    except Exception:
        shocks = SentimentFeed(mode="offline").shocks(since_ts)
        mode = "offline"
    return {
        "mode": mode,
        "schema_version": CAS_SCHEMA_VERSION,
        "since": since_ts.isoformat(),
        "shocks": [shock_event_to_dict(s) for s in shocks],
    }


# ---- HITL inceleme kuyruğu (Faz 11) --------------------------------------------
# Yüksek-etki sinyaller (bkz. signals/review.py::needs_review) motor tarafından
# "pending" olarak kaydedilir ama dağıtılmaz. Bu uçlar insan onay/ret akışını
# sağlar; karar FeedbackRepository'ye yazılır (backtest/kalibrasyon için).

@review_router.get("/pending", response_model=list[Signal])
async def list_pending(limit: int = Query(50, le=500)) -> list[Signal]:
    return await SignalRepository().query(review_status=PENDING, limit=limit)


async def _decide(signal_id: str, decision: str, reviewer: str | None, note: str | None) -> Signal:
    sig = await SignalRepository().set_review_status(signal_id, decision)
    if sig is None:
        raise HTTPException(status_code=404, detail=f"Sinyal bulunamadı: {signal_id}")
    await FeedbackRepository().save(
        ReviewFeedback(
            signal_id=sig.id, entity=sig.entity, signal_type=sig.type.value,
            decision=decision, reviewer=reviewer, note=note,
        )
    )
    return sig


@review_router.post("/{signal_id}/approve", response_model=Signal)
async def approve_signal(signal_id: str, reviewer: str | None = None, note: str | None = None) -> Signal:
    return await _decide(signal_id, APPROVED, reviewer, note)


@review_router.post("/{signal_id}/reject", response_model=Signal)
async def reject_signal(signal_id: str, reviewer: str | None = None, note: str | None = None) -> Signal:
    return await _decide(signal_id, REJECTED, reviewer, note)
