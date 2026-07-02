"""Worker görevleri — boru hattını birbirine bağlar.

Akış (Faz 1 MVP):
  RSS → raw.documents (kuyruk) → NLP/FinBERT → sentiment_scores (DB)

Faz 8: birden çok kaynak (RSS + NewsAPI + Fed) tek turda (``ingest_all_once``)
veya kaynak başına sürekli döngüde (``poll_connector_forever``) çekilebilir.

Fonksiyonlar hem tek-seferlik (test/demo) hem sürekli (üretim) kullanılabilir.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from ..core.contracts import Deduplicator, MessageQueue, SentimentModel, SourceConnector
from ..core.models import RawDocument
from ..nlp.ner import FinancialEntityExtractor
from ..storage.repositories import DocumentRepository, SentimentRepository

log = logging.getLogger(__name__)

RAW_TOPIC = "raw.documents"

# source_id -> Settings alan adı (poll aralığı, saniye). Bilinmeyen kaynaklar
# için poll_connector_forever varsayılan olarak poll_interval_news kullanır.
POLL_INTERVAL_FIELDS: dict[str, str] = {
    "rss": "poll_interval_news",
    "newsapi": "poll_interval_news",
    "fed": "poll_interval_fed",
    "social": "poll_interval_social",
}


async def ingest_once(
    connector: SourceConnector,
    queue: MessageQueue,
    dedup: Deduplicator,
    doc_repo: DocumentRepository,
    since: datetime,
) -> int:
    """Kaynaktan çek → dedup → ham depo + kuyruğa yay. Yeni belge sayısını döndürür."""
    docs = await connector.fetch(since)
    new = 0
    for doc in docs:
        if await dedup.is_duplicate(doc):
            continue
        await dedup.mark_seen(doc)
        await doc_repo.save(doc)
        await queue.publish(RAW_TOPIC, doc.model_dump(mode="json"))
        new += 1
    log.info("ingest_once: %d çekildi, %d yeni", len(docs), new)
    return new


async def ingest_all_once(
    connectors: list[SourceConnector],
    queue: MessageQueue,
    dedup: Deduplicator,
    doc_repo: DocumentRepository,
    since: datetime,
) -> int:
    """Birden çok kaynaktan sırayla çeker; toplam yeni belge sayısını döndürür.

    Bir kaynağın hatası (ör. NewsAPI kota aşımı, Fed akışı geçici erişilemez)
    diğer kaynakları etkilemez — o kaynak atlanır, döngü devam eder.
    """
    total = 0
    for connector in connectors:
        source_id = getattr(connector, "source_id", connector.__class__.__name__)
        try:
            total += await ingest_once(connector, queue, dedup, doc_repo, since)
        except Exception:
            log.exception("Kaynak çekimi başarısız (%s); bu tur atlanıyor", source_id)
    return total


async def poll_connector_forever(
    connector: SourceConnector,
    queue: MessageQueue,
    dedup: Deduplicator,
    doc_repo: DocumentRepository,
    interval_s: float,
) -> None:
    """Tek bir connector'ı sürekli olarak ``interval_s`` aralıklarla çeker (üretim).

    Bir turdaki hata döngüyü durdurmaz; bir sonraki turda tekrar denenir.
    Birden çok kaynağı paralel çalıştırmak için her biri için ayrı bir
    ``asyncio.create_task(poll_connector_forever(...))`` çağrılır.
    """
    source_id = getattr(connector, "source_id", connector.__class__.__name__)
    since = datetime.now(timezone.utc)
    while True:
        try:
            new = await ingest_once(connector, queue, dedup, doc_repo, since)
            since = datetime.now(timezone.utc)
            if new:
                log.info("poll[%s]: %d yeni belge", source_id, new)
        except Exception:
            log.exception("poll[%s]: tur başarısız", source_id)
        await asyncio.sleep(interval_s)


async def process_document(
    raw: dict,
    model: SentimentModel,
    extractor: FinancialEntityExtractor,
    sent_repo: SentimentRepository,
) -> int:
    """Tek ham belgeyi NLP'den geçirip skorları DB'ye yazar. Skor sayısını döndürür."""
    doc = RawDocument.model_validate(raw)
    entities = await extractor.extract(doc)
    scores = await model.score(doc, entities)
    for s in scores:
        await sent_repo.save(s)
    return len(scores)


async def nlp_drain(queue, model: SentimentModel, sent_repo: SentimentRepository) -> int:
    """Kuyruktaki tüm bekleyen belgeleri işler (InMemoryQueue.drain ile; demo/test)."""
    extractor = FinancialEntityExtractor()
    items = await queue.drain(RAW_TOPIC)
    total = 0
    for raw in items:
        total += await process_document(raw, model, extractor, sent_repo)
    log.info("nlp_drain: %d belge, %d skor", len(items), total)
    return total


async def nlp_consumer_forever(queue, model: SentimentModel, sent_repo: SentimentRepository) -> None:
    """Sürekli tüketici (üretim): raw.documents kuyruğunu dinler."""
    extractor = FinancialEntityExtractor()
    async for raw in queue.consume(RAW_TOPIC, group="nlp"):
        try:
            await process_document(raw, model, extractor, sent_repo)
        except Exception:
            log.exception("Belge işlenemedi; atlanıyor")
