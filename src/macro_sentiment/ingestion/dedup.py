"""Deduplikasyon — InMemory (dev/test) + Redis (üretim).

MVP: içerik hash'i ile tam-tekrar elemesi. Yakın-tekrar (vektör benzerliği)
Faz 2'de eklenir. core.contracts.Deduplicator uyumlu.
"""
from __future__ import annotations

from ..core.config import get_settings
from ..core.models import RawDocument

SEEN_KEY = "dedup:seen_hashes"
_TTL_SECONDS = 7 * 24 * 3600


class InMemoryDeduplicator:
    def __init__(self) -> None:
        self._seen: set[str] = set()

    async def is_duplicate(self, doc: RawDocument) -> bool:
        return doc.content_hash in self._seen

    async def mark_seen(self, doc: RawDocument) -> None:
        self._seen.add(doc.content_hash)


class RedisDeduplicator:
    def __init__(self, redis_client) -> None:
        self.redis = redis_client

    async def is_duplicate(self, doc: RawDocument) -> bool:
        return bool(await self.redis.sismember(SEEN_KEY, doc.content_hash))

    async def mark_seen(self, doc: RawDocument) -> None:
        await self.redis.sadd(SEEN_KEY, doc.content_hash)
        await self.redis.expire(SEEN_KEY, _TTL_SECONDS)


_dedup = None


def get_deduplicator():
    """Ayarlara göre dedup örneği (singleton)."""
    global _dedup
    if _dedup is None:
        settings = get_settings()
        if settings.queue_backend == "redis":
            import redis.asyncio as aioredis

            _dedup = RedisDeduplicator(aioredis.from_url(settings.redis_url, decode_responses=True))
        else:
            _dedup = InMemoryDeduplicator()
    return _dedup
