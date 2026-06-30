"""Toplayıcı — connector'ları zamanlanmış/sürekli çalıştırır, kuyruğa yayar.

Stream destekleyen kaynaklar (X) sürekli dinlenir; diğerleri polling ile çekilir.
"""
from __future__ import annotations

from datetime import datetime

from ..core.contracts import Deduplicator, MessageQueue, SourceConnector

RAW_TOPIC = "raw.documents"


class Collector:
    def __init__(self, connector: SourceConnector, queue: MessageQueue, dedup: Deduplicator) -> None:
        self.connector = connector
        self.queue = queue
        self.dedup = dedup

    async def run_once(self, since: datetime) -> int:
        """Tek çekim döngüsü: çek → dedup → kuyruğa yay. İşlenen yeni belge sayısını döndürür.

        TODO(Faz 1):
          - connector.fetch(since) çağır, rate-limit'e uy (token-bucket + backoff).
          - her belge için dedup.is_duplicate kontrolü; yeniyse mark_seen + publish.
          - ham belgeyi storage'a yaz (backfill için).
          - hata yönetimi + dead-letter.
        """
        raise NotImplementedError

    async def run_forever(self, interval: float) -> None:
        """Polling döngüsü (interval saniyede bir run_once). TODO(Faz 1)."""
        raise NotImplementedError
