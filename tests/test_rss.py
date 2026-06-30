"""RSS connector ayrıştırma testleri (ağ gerektirmez)."""
from __future__ import annotations

from datetime import datetime, timezone

from macro_sentiment.core.models import SourceType
from macro_sentiment.sources.rss_connector import RSSConnector
from tests.conftest import FIXTURES


def _docs():
    raw = (FIXTURES / "sample_feed.xml").read_bytes()
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    return RSSConnector(feeds=[]).parse(raw, feed_url="sample", since=epoch)


def test_parse_yields_documents():
    docs = _docs()
    assert len(docs) == 3
    assert all(d.source_type == SourceType.NEWS for d in docs)
    assert all(d.body.strip() for d in docs)


def test_published_at_is_parsed():
    docs = _docs()
    assert any(d.published_at.year == 2026 for d in docs)


def test_since_filter_excludes_old():
    raw = (FIXTURES / "sample_feed.xml").read_bytes()
    future = datetime(2030, 1, 1, tzinfo=timezone.utc)
    docs = RSSConnector(feeds=[]).parse(raw, feed_url="sample", since=future)
    assert docs == []


def test_content_hash_present_and_stable():
    docs = _docs()
    assert all(len(d.content_hash) == 64 for d in docs)
