"""SocialConnector testleri (Faz 9) — httpx mock, gerçek ağ çağrısı yok.

Roadmap "bitti tanımı": (1) mock akışta bot/spam örnekleri elenir,
(2) sosyal katkı source_breakdown["social"] olarak izole görünür,
(3) anahtarsız/devre dışı durumda offline korunur.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from macro_sentiment.core.models import SentimentScore, SourceType
from macro_sentiment.signals.aggregator import aggregate
from macro_sentiment.sources import social_connector
from macro_sentiment.sources.social_connector import SocialConnector

UTC = timezone.utc


def _stocktwits_payload(now_iso: str) -> dict:
    return {
        "messages": [
            {
                "id": 1,
                "body": "$AAPL earnings look strong this quarter, staying long https://t.co/xyz",
                "created_at": now_iso,
                "user": {"username": "realtrader", "join_date": "2018-01-01T00:00:00Z", "followers": 4200},
            },
            {
                # bot: az önce açılmış hesap, sıfır takipçi -> filter_spam tarafından düşürülmeli
                "id": 2,
                "body": "#pump #moon #buy #now $AAPL #rocket #gains",
                "created_at": now_iso,
                "user": {"username": "bot1234", "join_date": now_iso, "followers": 0},
            },
            {
                "id": 3,
                "body": "$AAPL earnings look strong this quarter, staying long https://t.co/xyz",  # kopya
                "created_at": now_iso,
                "user": {"username": "realtrader2", "join_date": "2019-01-01T00:00:00Z", "followers": 3000},
            },
        ]
    }


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


# ---- parse() — ağsız --------------------------------------------------------------

def test_parse_normalizes_and_strips_urls():
    now_iso = "2026-07-01T12:00:00Z"
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    payload = _stocktwits_payload(now_iso)
    docs = SocialConnector(symbols=["AAPL"]).parse(payload, since=epoch)
    assert len(docs) == 3
    assert all(d.source_type == SourceType.SOCIAL for d in docs)
    assert "https://" not in docs[0].body
    assert docs[0].raw_meta["author_followers"] == 4200


def test_parse_since_filter_excludes_old():
    now_iso = "2026-07-01T12:00:00Z"
    future = datetime(2030, 1, 1, tzinfo=UTC)
    payload = _stocktwits_payload(now_iso)
    docs = SocialConnector(symbols=["AAPL"]).parse(payload, since=future)
    assert docs == []


# ---- fetch() — offline güvenlik / mock ---------------------------------------------

@pytest.mark.asyncio
async def test_fetch_twitter_without_credentials_returns_empty_without_network(monkeypatch):
    def _boom(*a, **kw):
        raise AssertionError("kimlik bilgisi yokken ağa çıkılmamalı")

    monkeypatch.setattr(social_connector.httpx, "AsyncClient", _boom)
    docs = await SocialConnector(platform="twitter", credentials=None).fetch(datetime.now(UTC))
    assert docs == []


@pytest.mark.asyncio
async def test_fetch_reddit_without_credentials_returns_empty():
    docs = await SocialConnector(platform="reddit", credentials=None).fetch(datetime.now(UTC))
    assert docs == []


@pytest.mark.asyncio
async def test_fetch_unknown_platform_returns_empty():
    docs = await SocialConnector(platform="mastodon").fetch(datetime.now(UTC))
    assert docs == []


@pytest.mark.asyncio
async def test_fetch_stocktwits_mocked_filters_bot_and_duplicate(monkeypatch):
    now_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    fake = _FakeAsyncClient([_FakeResponse(200, json_data=_stocktwits_payload(now_iso))])
    monkeypatch.setattr(social_connector.httpx, "AsyncClient", lambda **kw: fake)

    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    docs = await SocialConnector(platform="stocktwits", symbols=["AAPL"]).fetch(epoch)

    # 3 ham mesajdan: bot (yeni hesap+0 takipçi) ve kopya metin düşürülmeli -> 1 kalmalı
    assert len(docs) == 1
    assert docs[0].raw_meta["author_username"] == "realtrader"


@pytest.mark.asyncio
async def test_fetch_stocktwits_swallows_per_symbol_failure(monkeypatch):
    fake = _FakeAsyncClient([httpx.TimeoutException("timeout")] * 3)
    monkeypatch.setattr(social_connector.httpx, "AsyncClient", lambda **kw: fake)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    docs = await SocialConnector(platform="stocktwits", symbols=["AAPL"]).fetch(epoch)
    assert docs == []


# ---- uçtan uca: sosyal katkı source_breakdown'da izole -----------------------------

def test_social_scores_isolated_in_source_breakdown():
    now = datetime.now(UTC)
    news_score = SentimentScore(
        doc_id="n1", entity="AAPL", polarity=0.5, intensity=60.0, confidence=0.8,
        model_version="test", source_type=SourceType.NEWS, created_at=now,
    )
    social_score = SentimentScore(
        doc_id="s1", entity="AAPL", polarity=-0.5, intensity=40.0, confidence=0.6,
        model_version="test", source_type=SourceType.SOCIAL, created_at=now,
    )
    agg = aggregate("AAPL", [news_score, social_score])
    assert agg.source_breakdown["news"] == 0.5
    assert agg.source_breakdown["social"] == -0.5
    # tekil ham değerler karışmadan tutuluyor; genel mean_polarity ayrı hesaplanır
    assert agg.mean_polarity == 0.0
