"""Worker görevleri — boru hattını birbirine bağlar.

Akış (Faz 1 MVP):
  RSS → raw.documents (kuyruk) → NLP/FinBERT → sentiment_scores (DB)

Fonksiyonlar hem tek-seferlik (test/demo) hem sürekli (üretim) kullanılabilir.
"""
from __future__ import annotations

import logging
from datetime import datetime

from ..core.contracts import Deduplicator, MessageQueue, SentimentModel, SourceConnector
from ..core.models import RawDocument
from ..nlp.ner import FinancialEntityExtractor
from ..storage.repositories import DocumentRepository, SentimentRepository

log = logging.getLogger(__name__)

RAW_TOPIC = "raw.documents"


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
