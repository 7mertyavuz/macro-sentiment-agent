"""Toplayıcı — connector'ları zamanlanmış/sürekli çalıştırır, kuyruğa yayar.

Stream destekleyen kaynaklar (X) sürekli dinlenir; diğerleri polling ile çekilir.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from ..core.contracts import Deduplicator, MessageQueue, SourceConnector

log = logging.getLogger(__name__)

RAW_TOPIC = "raw.documents"


class Collector:
    def __init__(self, connector: SourceConnector, queue: MessageQueue, dedup: Deduplicator) -> None:
        self.connector = connector
        self.queue = queue
        self.dedup = dedup

    async def run_once(self, since: datetime) -> int:
        """Tek çekim döngüsü: çek → dedup → kuyruğa yay. Yeni belge sayısını döndürür.

        Uzun süre `NotImplementedError` fırlatıyordu; pratikte
        `worker/tasks.py::ingest_all_once` bu işi yapıyordu. Fırlatan bir gövde
        bırakmak bir tuzaktır: çağıran, kodun var olduğunu sanır.

        Tek connector'ın hatası turu düşürmez — kaynak başına izole edilir.
        """
        try:
            docs = await self.connector.fetch(since)
        except Exception as exc:
            log.warning("%s çekilemedi, bu tur atlanıyor: %s", self.connector.source_id, exc)
            return 0

        published = 0
        for doc in docs:
            try:
                if await self.dedup.is_duplicate(doc):
                    continue
                await self.dedup.mark_seen(doc)
                await self.queue.publish(RAW_TOPIC, doc.model_dump(mode="json"))
                published += 1
            except Exception as exc:
                # Tek bir belge tüm partiyi düşürmemeli.
                log.warning("Belge yayınlanamadı (%s): %s", getattr(doc, "id", "?"), exc)
        return published

    async def run_forever(self, interval: float) -> None:
        """`interval` saniyede bir `run_once` — iptal edilene kadar."""
        since = datetime.now(timezone.utc) - timedelta(seconds=interval)
        while True:
            started = datetime.now(timezone.utc)
            n = await self.run_once(since)
            log.info("%s: %d yeni belge", self.connector.source_id, n)
            since = started
            await asyncio.sleep(interval)
