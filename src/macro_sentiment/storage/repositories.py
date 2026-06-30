"""Repository'ler — model nesneleri ile veritabanı arasında CRUD soyutlaması."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from ..core.models import RawDocument, SentimentScore, Signal
from .db import get_sessionmaker
from .orm import RawDocumentORM, SentimentScoreORM, SignalORM


class DocumentRepository:
    async def save(self, doc: RawDocument) -> None:
        async with get_sessionmaker()() as session:
            await session.merge(RawDocumentORM(**doc.model_dump()))
            await session.commit()

    async def exists(self, doc_id: str) -> bool:
        async with get_sessionmaker()() as session:
            return (await session.get(RawDocumentORM, doc_id)) is not None


class SentimentRepository:
    async def save(self, score: SentimentScore) -> None:
        async with get_sessionmaker()() as session:
            data = score.model_dump()
            data["emotion"] = score.emotion.model_dump()
            data["source_type"] = score.source_type.value
            session.add(SentimentScoreORM(**data))
            await session.commit()

    async def recent_for_entity(self, entity: str, limit: int = 100) -> list[SentimentScore]:
        async with get_sessionmaker()() as session:
            stmt = (
                select(SentimentScoreORM)
                .where(SentimentScoreORM.entity == entity)
                .order_by(SentimentScoreORM.created_at.desc())
                .limit(limit)
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [SentimentScore.model_validate(r, from_attributes=True) for r in rows]

    async def distinct_entities(self) -> list[str]:
        async with get_sessionmaker()() as session:
            rows = (await session.execute(select(SentimentScoreORM.entity).distinct())).scalars().all()
            return list(rows)


class SignalRepository:
    async def save(self, signal: Signal) -> None:
        async with get_sessionmaker()() as session:
            data = signal.model_dump()
            data["type"] = signal.type.value
            await session.merge(SignalORM(**data))
            await session.commit()

    async def query(self, entity: str | None = None, since: datetime | None = None, limit: int = 50) -> list[Signal]:
        async with get_sessionmaker()() as session:
            stmt = select(SignalORM).order_by(SignalORM.created_at.desc()).limit(limit)
            if entity:
                stmt = stmt.where(SignalORM.entity == entity)
            if since:
                stmt = stmt.where(SignalORM.created_at >= since)
            rows = (await session.execute(stmt)).scalars().all()
            return [Signal.model_validate(r, from_attributes=True) for r in rows]
