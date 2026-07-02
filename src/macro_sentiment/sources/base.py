"""Connector'lar için ortak temel sınıf ve yardımcılar."""
from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime

import httpx

from ..core.models import RawDocument, SourceType

log = logging.getLogger(__name__)


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


async def fetch_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_attempts: int = 3,
    backoff_base: float = 0.5,
    **kwargs,
) -> httpx.Response:
    """Geçici hatalarda (5xx / zaman aşımı) üstel geri çekilmeli yeniden dener.

    4xx hataları (ör. geçersiz anahtar) kalıcı kabul edilir ve hemen fırlatılır
    — tekrar denemek anlamsızdır. ``max_attempts`` denemeden sonra son hatayı
    fırlatır (çağıran taraf bu turu atlayabilir).
    """
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = await client.request(method, url, **kwargs)
            if resp.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"sunucu hatası: {resp.status_code}", request=resp.request, response=resp
                )
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code < 500:
                raise  # 4xx: kalıcı hata, tekrar deneme
            last_exc = exc
        except httpx.TimeoutException as exc:
            last_exc = exc
        if attempt < max_attempts:
            delay = backoff_base * (2 ** (attempt - 1))
            log.warning("İstek başarısız (deneme %d/%d), %.1fs sonra tekrar: %s", attempt, max_attempts, delay, url)
            await asyncio.sleep(delay)
    assert last_exc is not None
    raise last_exc
