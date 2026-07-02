"""NewsAPIConnector testleri (Faz 8) — httpx mock, gerçek ağ çağrısı yok."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from macro_sentiment.core.models import SourceType
from macro_sentiment.sources import newsapi_connector
from macro_sentiment.sources.newsapi_connector import NewsAPIConnector

UTC = timezone.utc


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data or {}
        self.request = "req"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("hata", request=self.request, response=self)

    def json(self):
        return self._json


class _FakeAsyncClient:
    """httpx.AsyncClient yerine geçen sahte istemci; gerçek ağ çağrısı yapmaz."""

    def __init__(self, responses, **kwargs):
        self._responses = list(responses)
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


_SAMPLE_PAYLOAD = {
    "status": "ok",
    "totalResults": 2,
    "articles": [
        {
            "source": {"id": "reuters", "name": "Reuters"},
            "title": "Fed warns of downgrade risk amid inflation",
            "description": "The Federal Reserve warns of downgrade risks and weak outlook.",
            "url": "https://example.com/a1",
            "publishedAt": "2026-07-01T12:00:00Z",
        },
        {
            "source": {"id": None, "name": "Example Wire"},
            "title": "Apple beats earnings estimates",
            "description": "Apple reported record quarterly revenue.",
            "url": "https://example.com/a2",
            "publishedAt": "2026-07-02T09:30:00Z",
        },
    ],
}


# ---- parse() — ağsız --------------------------------------------------------------

def test_parse_normalizes_articles():
    docs = NewsAPIConnector(api_key="k").parse(_SAMPLE_PAYLOAD)
    assert len(docs) == 2
    assert all(d.source_type == SourceType.NEWS for d in docs)
    assert docs[0].source == "newsapi:Reuters"
    assert docs[0].url == "https://example.com/a1"
    assert docs[0].published_at.year == 2026


def test_parse_skips_articles_without_body():
    payload = {"articles": [{"source": {"name": "x"}, "title": None, "description": None, "content": None, "url": "u"}]}
    docs = NewsAPIConnector(api_key="k").parse(payload)
    assert docs == []


def test_parse_content_hash_stable():
    docs = NewsAPIConnector(api_key="k").parse(_SAMPLE_PAYLOAD)
    assert all(len(d.content_hash) == 64 for d in docs)


def test_parse_handles_missing_articles_key():
    assert NewsAPIConnector(api_key="k").parse({}) == []


# ---- fetch() — offline güvenlik ----------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_without_key_returns_empty_without_network(monkeypatch):
    def _boom(*a, **kw):
        raise AssertionError("anahtar yokken ağa çıkılmamalı")

    monkeypatch.setattr(newsapi_connector.httpx, "AsyncClient", _boom)
    docs = await NewsAPIConnector(api_key=None).fetch(datetime.now(UTC))
    assert docs == []


@pytest.mark.asyncio
async def test_fetch_with_mocked_client_returns_docs(monkeypatch):
    fake = _FakeAsyncClient([_FakeResponse(200, json_data=_SAMPLE_PAYLOAD)])
    monkeypatch.setattr(newsapi_connector.httpx, "AsyncClient", lambda **kw: fake)
    docs = await NewsAPIConnector(api_key="k").fetch(datetime.now(UTC))
    assert len(docs) == 2
    assert fake.calls and fake.calls[0][0] == "GET"


@pytest.mark.asyncio
async def test_fetch_swallows_persistent_failure(monkeypatch):
    fake = _FakeAsyncClient([httpx.HTTPStatusError("boom", request="r", response=_FakeResponse(404))] * 3)
    monkeypatch.setattr(newsapi_connector.httpx, "AsyncClient", lambda **kw: fake)
    docs = await NewsAPIConnector(api_key="k").fetch(datetime.now(UTC))
    assert docs == []  # kalıcı hata → bu tur atlanır, exception dışa sızmaz
