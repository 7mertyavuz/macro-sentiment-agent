"""REST uç noktaları — sinyal ve duyarlılık sorguları."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query

from ..core.models import Signal
from ..storage.repositories import SentimentRepository, SignalRepository

router = APIRouter(prefix="/v1", tags=["signals"])


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
