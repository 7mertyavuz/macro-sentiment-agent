"""Mesaj kuyruğu — InMemory (dev/test) + Redis Streams (üretim).

core.contracts.MessageQueue uyumlu. Topic isimleri katmanlar arası sözleşmedir:
  raw.documents  — ingestion → nlp
  scored.events  — nlp → signals
  signals        — signals → api/alerts
"""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import AsyncIterator

from ..core.config import get_settings
from ..observability.metrics import queue_depth


class InMemoryQueue:
    """Tek süreç içi kuyruk (asyncio.Queue tabanlı). Test ve dev için."""

    def __init__(self) -> None:
        self._topics: dict[str, asyncio.Queue] = defaultdict(asyncio.Queue)

    async def publish(self, topic: str, message: dict) -> None:
        await self._topics[topic].put(message)
        queue_depth.labels(topic=topic).set(self._topics[topic].qsize())

    async def consume(self, topic: str, group: str = "default") -> AsyncIterator[dict]:
        q = self._topics[topic]
        while True:
            yield await q.get()

    async def drain(self, topic: str) -> list[dict]:
        """Topic'teki bekleyen tüm mesajları toplar (demo/test için bloklamaz)."""
        q = self._topics[topic]
        out: list[dict] = []
        while not q.empty():
            out.append(q.get_nowait())
        queue_depth.labels(topic=topic).set(q.qsize())
        return out

    def qsize(self, topic: str) -> int:
        return self._topics[topic].qsize()


class RedisStreamQueue:
    """Redis Streams tabanlı kuyruk (XADD / XREADGROUP). Üretim için."""

    def __init__(self, redis_client) -> None:
        self.redis = redis_client

    async def publish(self, topic: str, message: dict) -> None:
        await self.redis.xadd(topic, {"data": json.dumps(message)})

    async def consume(self, topic: str, group: str = "default") -> AsyncIterator[dict]:
        try:
            await self.redis.xgroup_create(topic, group, id="0", mkstream=True)
        except Exception:
            pass  # grup zaten var
        consumer = f"{group}-1"
        while True:
            resp = await self.redis.xreadgroup(group, consumer, {topic: ">"}, count=10, block=5000)
            for _stream, entries in resp or []:
                for entry_id, fields in entries:
                    yield json.loads(fields["data"])
                    await self.redis.xack(topic, group, entry_id)


_queue = None


def get_queue():
    """Ayarlara göre kuyruk örneği (singleton)."""
    global _queue
    if _queue is None:
        settings = get_settings()
        if settings.queue_backend == "redis":
            import redis.asyncio as aioredis

            _queue = RedisStreamQueue(aioredis.from_url(settings.redis_url, decode_responses=True))
        else:
            _queue = InMemoryQueue()
    return _queue
