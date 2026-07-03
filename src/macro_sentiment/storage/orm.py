"""SQLAlchemy ORM tabloları (ARCHITECTURE.md §9).

Zaman serisi tablolar (sentiment_scores, signals) Postgres'te TimescaleDB
hypertable'a dönüştürülebilir; SQLite'ta düz tablo olarak çalışır.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RawDocumentORM(Base):
    __tablename__ = "raw_documents"

    id: Mapped[str] = mapped_column(String(512), primary_key=True)
    source: Mapped[str] = mapped_column(String(256), index=True)
    source_type: Mapped[str] = mapped_column(String(32), index=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    body: Mapped[str] = mapped_column(Text)
    lang: Mapped[str] = mapped_column(String(8), default="en")
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    raw_meta: Mapped[dict] = mapped_column(JSON, default=dict)


class SentimentScoreORM(Base):
    __tablename__ = "sentiment_scores"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    doc_id: Mapped[str] = mapped_column(String(512), index=True)
    entity: Mapped[str] = mapped_column(String(64), index=True)
    polarity: Mapped[float] = mapped_column(Float)
    intensity: Mapped[float] = mapped_column(Float)
    emotion: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence: Mapped[float] = mapped_column(Float)
    model_version: Mapped[str] = mapped_column(String(64))
    source_type: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class SignalORM(Base):
    __tablename__ = "signals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    entity: Mapped[str] = mapped_column(String(64), index=True)
    type: Mapped[str] = mapped_column(String(32), index=True)
    severity: Mapped[float] = mapped_column(Float)
    direction: Mapped[float] = mapped_column(Float)
    window: Mapped[str] = mapped_column(String(64))
    headline: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    # Faz 11: HITL inceleme durumu — None/"pending"/"approved"/"rejected".
    review_status: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)


class FeedbackORM(Base):
    """İnceleme kararlarının kalıcı kaydı (Faz 11) — backtest'e akıtılan geri besleme."""

    __tablename__ = "review_feedback"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    signal_id: Mapped[str] = mapped_column(String(64), index=True)
    entity: Mapped[str] = mapped_column(String(64), index=True)
    signal_type: Mapped[str] = mapped_column(String(32))
    decision: Mapped[str] = mapped_column(String(16))
    realized_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reviewer: Mapped[str | None] = mapped_column(String(64), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class BaselineORM(Base):
    """Varlık×metrik için kalıcı tarihsel taban çizgisi (Faz 10).

    Rolling (mean, std, n) — yeniden başlatmada korunur; ``signals/engine.py``
    her değerlendirmede okur/günceller (Welford, bkz. ``signals/baseline.py``).
    Postgres/TimescaleDB'de düz tablo olarak kalır (hypertable'a çevrilmesi
    gerekmez — düşük hacimli, append-heavy değil, upsert ağırlıklı).
    """

    __tablename__ = "baselines"

    entity: Mapped[str] = mapped_column(String(64), primary_key=True)
    metric: Mapped[str] = mapped_column(String(32), primary_key=True)
    mean: Mapped[float] = mapped_column(Float, default=0.0)
    std: Mapped[float] = mapped_column(Float, default=0.0)
    n: Mapped[int] = mapped_column(default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
