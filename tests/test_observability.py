"""Gözlemlenebilirlik testleri (Faz 12) — metrikler + yapılandırılmış log."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from macro_sentiment.api.main import app
from macro_sentiment.core.models import Emotion, SentimentScore, SourceType
from macro_sentiment.ingestion.dedup import InMemoryDeduplicator
from macro_sentiment.ingestion.queue import InMemoryQueue
from macro_sentiment.nlp.sentiment_finbert import FinBERTSentiment
from macro_sentiment.observability import metrics as obs_metrics
from macro_sentiment.observability.logging import bind_correlation_id, get_correlation_id, get_logger
from macro_sentiment.signals.engine import SignalEngine
from macro_sentiment.sources.rss_connector import RSSConnector
from macro_sentiment.storage.db import dispose_db, init_db
from macro_sentiment.storage.repositories import DocumentRepository, SentimentRepository, SignalRepository
from macro_sentiment.worker.tasks import ingest_once
from tests.conftest import FIXTURES


# ---- /metrics HTTP ucu --------------------------------------------------------------

def test_metrics_endpoint_returns_prometheus_text():
    with TestClient(app) as c:
        resp = c.get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]
        assert "msa_" in resp.text  # en az bir tanımlı metrik ailesi


# ---- documents_fetched_total ---------------------------------------------------------

@pytest.mark.asyncio
async def test_ingest_once_increments_documents_fetched_total():
    await init_db()
    queue, dedup, doc_repo = InMemoryQueue(), InMemoryDeduplicator(), DocumentRepository()
    raw = (FIXTURES / "sample_feed.xml").read_bytes()
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)

    class _FixedRSS(RSSConnector):
        async def fetch(self, since):
            return self.parse(raw, feed_url="sample", since=since)

    connector = _FixedRSS(feeds=[])
    before = obs_metrics.documents_fetched_total.labels(source="rss")._value.get()
    new = await ingest_once(connector, queue, dedup, doc_repo, epoch)
    after = obs_metrics.documents_fetched_total.labels(source="rss")._value.get()

    assert new >= 1
    assert after - before == new
    await dispose_db()


# ---- signals_emitted_total ------------------------------------------------------------

def _score(entity, pol, fear=0.0, greed=0.0):
    now = datetime.now(timezone.utc)
    return SentimentScore(
        doc_id=f"d-{entity}-{pol}-{now.timestamp()}", entity=entity, polarity=pol, intensity=90.0,
        emotion=Emotion(fear=fear, greed=greed), confidence=0.8,
        model_version="test", source_type=SourceType.NEWS, created_at=now,
    )


@pytest.mark.asyncio
async def test_engine_increments_signals_emitted_total():
    await init_db()
    sent_repo, sig_repo = SentimentRepository(), SignalRepository()
    for _ in range(3):
        await sent_repo.save(_score("METRICX", -0.9, fear=0.9))

    before = obs_metrics.signals_emitted_total.labels(type="panic", review_status="pending")._value.get()
    engine = SignalEngine(sent_repo=sent_repo, sig_repo=sig_repo)
    sigs = await engine.evaluate_entity("METRICX")
    assert sigs  # en az panic sinyali üretmeli
    after = obs_metrics.signals_emitted_total.labels(type="panic", review_status="pending")._value.get()
    assert after > before
    await dispose_db()


# ---- inference_seconds ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_finbert_score_records_inference_seconds():
    from macro_sentiment.core.models import RawDocument
    from macro_sentiment.nlp.ner import FinancialEntityExtractor

    model = FinBERTSentiment(use_finbert=False)
    doc = RawDocument(
        id="obs1", source="test", source_type=SourceType.NEWS, body="AAPL rallies to a record high",
        published_at=datetime.now(timezone.utc), fetched_at=datetime.now(timezone.utc), content_hash="x" * 64,
    )
    extractor = FinancialEntityExtractor()
    entities = await extractor.extract(doc)

    child = obs_metrics.inference_seconds.labels(model=model.model_version)
    # ``_buckets`` her kova için AYRI (kümülatif olmayan) sayaç tutar — toplam
    # gözlem sayısı tüm kovaların toplamıdır (hangi kovaya düştüğü süreye bağlı).
    count_before = sum(b.get() for b in child._buckets)
    await model.score(doc, entities)
    count_after = sum(b.get() for b in child._buckets)
    assert count_after == count_before + 1


# ---- queue_depth ------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_queue_publish_and_drain_update_queue_depth_gauge():
    queue = InMemoryQueue()
    await queue.publish("obs.topic", {"x": 1})
    depth_after_publish = obs_metrics.queue_depth.labels(topic="obs.topic")._value.get()
    assert depth_after_publish >= 1

    await queue.drain("obs.topic")
    depth_after_drain = obs_metrics.queue_depth.labels(topic="obs.topic")._value.get()
    assert depth_after_drain == 0


# ---- yapılandırılmış log + korelasyon kimliği -------------------------------------------

def test_correlation_id_bind_and_get_roundtrip():
    cid = bind_correlation_id("test-cid-123")
    assert cid == "test-cid-123"
    assert get_correlation_id() == "test-cid-123"


def test_bind_correlation_id_generates_when_not_given():
    cid = bind_correlation_id()
    assert cid and len(cid) == 16
    assert get_correlation_id() == cid


def test_get_logger_returns_usable_logger(capsys):
    bind_correlation_id("log-test-cid")
    log = get_logger("test.observability")
    log.info("olay", key="value")
    # structlog varsayılan olarak stdout'a yazar (PrintLoggerFactory); en azından
    # çağrı exception fırlatmadan tamamlanmalı — configure_logging() çağrılmamış
    # olsa bile structlog güvenli bir varsayılanla çalışır.
