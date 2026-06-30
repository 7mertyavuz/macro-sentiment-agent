"""Duman testleri — iskeletin import edilebilirliğini ve temel sözleşmeleri doğrular."""
from __future__ import annotations

from datetime import datetime, timezone

from macro_sentiment.core.models import (
    Emotion,
    RawDocument,
    SignalType,
    SourceType,
)
from macro_sentiment.signals.baseline import Baseline, zscore
from macro_sentiment.sources import REGISTRY, get_connector
from macro_sentiment.sources.base import BaseConnector


def test_registry_has_core_sources():
    assert "rss" in REGISTRY
    assert issubclass(get_connector("rss"), BaseConnector)


def test_content_hash_is_stable():
    h1 = BaseConnector.content_hash("Title", "Body")
    h2 = BaseConnector.content_hash(" title ", " body ")  # normalize edilir
    assert h1 == h2


def test_raw_document_model():
    now = datetime.now(timezone.utc)
    doc = RawDocument(
        id="x1",
        source="rss:test",
        source_type=SourceType.NEWS,
        body="Fed signals caution on rate cuts.",
        published_at=now,
        fetched_at=now,
        content_hash="abc",
    )
    assert doc.lang == "en"


def test_zscore_handles_zero_std():
    assert zscore(5.0, Baseline(mean=5.0, std=0.0)) == 0.0
    assert zscore(8.0, Baseline(mean=5.0, std=1.5)) == 2.0


def test_signal_type_enum():
    assert SignalType.PANIC.value == "panic"
    assert Emotion().fear == 0.0
