"""Repository'ler — model nesneleri ile veritabanı arasında CRUD soyutlaması."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from ..core.models import RawDocument, SentimentScore, Signal
from ..signals.baseline import Baseline, update_baseline
from ..signals.review import ReviewFeedback
from .db import get_sessionmaker
from .orm import BaselineORM, FeedbackORM, RawDocumentORM, SentimentScoreORM, SignalORM


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

    async def query(
        self,
        entity: str | None = None,
        since: datetime | None = None,
        limit: int = 50,
        review_status: str | None = "__any__",
    ) -> list[Signal]:
        """``review_status`` verilmezse (``"__any__"`` sentinel) filtrelenmez — geriye uyum.

        Belirli bir değer (ör. ``"pending"``) verilirse yalnızca o durumdaki
        sinyaller döner (Faz 11 inceleme kuyruğu).
        """
        async with get_sessionmaker()() as session:
            stmt = select(SignalORM).order_by(SignalORM.created_at.desc()).limit(limit)
            if entity:
                stmt = stmt.where(SignalORM.entity == entity)
            if since:
                stmt = stmt.where(SignalORM.created_at >= since)
            if review_status != "__any__":
                stmt = stmt.where(SignalORM.review_status == review_status)
            rows = (await session.execute(stmt)).scalars().all()
            return [Signal.model_validate(r, from_attributes=True) for r in rows]

    async def set_review_status(self, signal_id: str, status: str) -> Signal | None:
        """Bir sinyalin inceleme durumunu günceller (Faz 11); bulunamazsa None döner."""
        async with get_sessionmaker()() as session:
            row = await session.get(SignalORM, signal_id)
            if row is None:
                return None
            row.review_status = status
            await session.commit()
            await session.refresh(row)
            return Signal.model_validate(row, from_attributes=True)


class FeedbackRepository:
    """İnceleme kararlarının kalıcı deposu (Faz 11) — backtest setine akıtılabilir."""

    async def save(self, feedback: ReviewFeedback) -> None:
        async with get_sessionmaker()() as session:
            data = feedback.model_dump()
            session.add(FeedbackORM(**data))
            await session.commit()

    async def all(self, entity: str | None = None) -> list[ReviewFeedback]:
        async with get_sessionmaker()() as session:
            stmt = select(FeedbackORM).order_by(FeedbackORM.decided_at.desc())
            if entity:
                stmt = stmt.where(FeedbackORM.entity == entity)
            rows = (await session.execute(stmt)).scalars().all()
            return [ReviewFeedback.model_validate(r, from_attributes=True) for r in rows]


class BaselineRepository:
    """Varlık×metrik için kalıcı (mean, std, n) taban çizgisi (Faz 10).

    ``signals/baseline.py::update_baseline`` (Welford çevrimiçi algoritması) ile
    tek değer eklenerek güncellenir; tüm geçmiş seri saklanmaz. Yeniden
    başlatmada ``BaselineORM`` tablosundan okunarak korunur.
    """

    async def get(self, entity: str, metric: str) -> Baseline:
        async with get_sessionmaker()() as session:
            row = await session.get(BaselineORM, (entity, metric))
            if row is None:
                return Baseline()
            return Baseline(mean=row.mean, std=row.std, n=row.n)

    async def update(self, entity: str, metric: str, value: float) -> Baseline:
        """Mevcut taban çizgisini okur, ``value`` ile günceller ve DB'ye yazar."""
        current = await self.get(entity, metric)
        updated = update_baseline(current, value)
        async with get_sessionmaker()() as session:
            await session.merge(
                BaselineORM(
                    entity=entity,
                    metric=metric,
                    mean=updated.mean,
                    std=updated.std,
                    n=updated.n,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()
        return updated
