"""Katmanlar arası arayüz sözleşmeleri (Protocol'ler).

Her somut bileşen bu Protocol'leri uygular; çekirdek soyutlamaya bağımlıdır,
somut uygulamaya değil (bağımlılık tersine çevirme).
"""
from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from .models import Entity, RawDocument, SentimentScore, Signal


class RateLimitPolicy(Protocol):
    """Kaynak başına çekme kotası (token-bucket parametreleri)."""

    max_calls: int
    per_seconds: float


@runtime_checkable
class SourceConnector(Protocol):
    """Katman 1 — Veri kaynağı connector'ı. Yeni kaynak = yeni connector."""

    source_id: str

    async def fetch(self, since: datetime) -> list[RawDocument]:
        """`since` zamanından sonraki yeni belgeleri çeker ve normalize eder."""
        ...

    def rate_limit(self) -> RateLimitPolicy:
        ...


@runtime_checkable
class Deduplicator(Protocol):
    """Katman 2 — Tekrar eden belgeleri eler (hash + vektör benzerliği)."""

    async def is_duplicate(self, doc: RawDocument) -> bool: ...
    async def mark_seen(self, doc: RawDocument) -> None: ...


@runtime_checkable
class MessageQueue(Protocol):
    """Katmanlar arası asenkron iletişim (Redis Streams → Kafka)."""

    async def publish(self, topic: str, message: dict) -> None: ...
    async def consume(self, topic: str, group: str): ...  # async iterator


@runtime_checkable
class EntityExtractor(Protocol):
    """Katman 3 — Metinden finansal varlık/ticker çıkarır."""

    async def extract(self, doc: RawDocument) -> list[Entity]: ...


@runtime_checkable
class SentimentModel(Protocol):
    """Katman 3 — Duyarlılık modeli (FinBERT, LLM, vb.)."""

    model_version: str

    async def score(self, doc: RawDocument, entities: list[Entity]) -> list[SentimentScore]:
        ...


@runtime_checkable
class SignalRule(Protocol):
    """Katman 4 — Toplanan skorlardan sinyal üreten kural/dedektör."""

    async def evaluate(self, entity: str, window_scores: list[SentimentScore]) -> Signal | None:
        ...


@runtime_checkable
class AlertChannel(Protocol):
    """Katman 5 — Sinyalleri dış kanala (Slack/Telegram/webhook) iletir."""

    async def send(self, signal: Signal) -> None: ...
