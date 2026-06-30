"""Uçtan uca pipeline testi: feed → kuyruk → NLP → DB → sorgu (ağ/torch gerektirmez)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from macro_sentiment.ingestion.dedup import InMemoryDeduplicator
from macro_sentiment.ingestion.queue import InMemoryQueue
from macro_sentiment.nlp.sentiment_finbert import FinBERTSentiment
from macro_sentiment.sources.rss_connector import RSSConnector
from macro_sentiment.storage.db import dispose_db, init_db
from macro_sentiment.storage.repositories import DocumentRepository, SentimentRepository
from macro_sentiment.worker.tasks import RAW_TOPIC, nlp_drain
from tests.conftest import FIXTURES


@pytest.mark.asyncio
async def test_end_to_end_pipeline():
    await init_db()
    queue, dedup = InMemoryQueue(), InMemoryDeduplicator()
    doc_repo, sent_repo = DocumentRepository(), SentimentRepository()

    raw = (FIXTURES / "sample_feed.xml").read_bytes()
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    docs = RSSConnector(feeds=[]).parse(raw, feed_url="sample", since=epoch)
    assert len(docs) == 3

    for doc in docs:
        assert not await dedup.is_duplicate(doc)
        await dedup.mark_seen(doc)
        await doc_repo.save(doc)
        await queue.publish(RAW_TOPIC, doc.model_dump(mode="json"))

    # dedup ikinci kez aynı belgeyi elemeli
    assert await dedup.is_duplicate(docs[0])

    scored = await nlp_drain(queue, FinBERTSentiment(use_finbert=False), sent_repo)
    assert scored >= 3  # her belge en az bir varlık

    aapl = await sent_repo.recent_for_entity("AAPL")
    btc = await sent_repo.recent_for_entity("BTC")
    assert aapl and aapl[0].polarity > 0      # "surge/beats/record" → pozitif
    assert btc and btc[0].polarity < 0        # "plunge/recession/selloff" → negatif
    await dispose_db()
