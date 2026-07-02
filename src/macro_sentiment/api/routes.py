"""REST uç noktaları — sinyal ve duyarlılık sorguları."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query

from ..core.models import Signal
from ..storage.repositories import SentimentRepository, SignalRepository
from .cas_transport import CAS_SCHEMA_VERSION, sentiment_state_to_dict, shock_event_to_dict
from .sentiment_feed import SentimentFeed

router = APIRouter(prefix="/v1", tags=["signals"])
cas_router = APIRouter(prefix="/v1/cas", tags=["cas"])


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
