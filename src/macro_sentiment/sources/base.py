"""Connector'lar için ortak temel sınıf ve yardımcılar."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from ..core.models import RawDocument, SourceType


@dataclass
class SimpleRateLimit:
    """Basit token-bucket politikası (core.contracts.RateLimitPolicy uyumlu)."""

    max_calls: int = 60
    per_seconds: float = 60.0


class BaseConnector:
    """Connector'lar için yardımcılar içeren temel sınıf.

    Alt sınıflar `source_id` tanımlamalı ve `fetch()` metodunu uygulamalıdır.
    """

    source_id: str = "base"
    source_type: SourceType = SourceType.NEWS

    def rate_limit(self) -> SimpleRateLimit:
        return SimpleRateLimit()

    async def fetch(self, since: datetime) -> list[RawDocument]:  # pragma: no cover
        raise NotImplementedError

    @staticmethod
    def content_hash(title: str | None, body: str) -> str:
        """Dedup için kararlı içerik hash'i üretir."""
        payload = f"{(title or '').strip().lower()}|{body.strip().lower()}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
