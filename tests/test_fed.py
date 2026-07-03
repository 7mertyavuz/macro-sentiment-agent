"""FedConnector testleri (Faz 8) — httpx mock, gerçek ağ çağrısı yok.

Ayrıca FOMC metninin fed_tone'u doğru yönde etkilediğini gösteren uçtan uca
mini bir test içerir (roadmap "bitti tanımı").
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from macro_sentiment.api.sentiment_feed import aggregate_to_state
from macro_sentiment.core.models import SourceType
from macro_sentiment.nlp.ner import FinancialEntityExtractor
from macro_sentiment.nlp.sentiment_finbert import FinBERTSentiment
from macro_sentiment.signals.aggregator import aggregate
from macro_sentiment.sources import fed_connector
from macro_sentiment.sources.fed_connector import FedConnector

UTC = timezone.utc

_FOMC_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>Federal Reserve Press Releases</title>
<item>
  <title>Federal Open Market Committee statement</title>
  <link>https://www.federalreserve.gov/newsevents/pressreleases/monetary20260701a.htm</link>
  <description>The FOMC decided to maintain the target range and warns of downgrade risks, citing weak outlook and elevated inflation concerns.</description>
  <pubDate>Wed, 01 Jul 2026 14:00:00 GMT</pubDate>
  <guid>fomc-20260701</guid>
</item>
<item>
  <title>Agency Information Collection Activities</title>
  <link>https://www.federalreserve.gov/newsevents/pressreleases/other20260630a.htm</link>
  <description>Routine administrative notice regarding information collection.</description>
  <pubDate>Tue, 30 Jun 2026 10:00:00 GMT</pubDate>
  <guid>other-20260630</guid>
</item>
</channel></rss>
"""


class _FakeResponse:
    def __init__(self, status_code=200, content=b""):
        self.status_code = status_code
        self.content = content
        self.request = "req"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("hata", request=self.request, response=self)


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

def test_parse_tags_fomc_doc_kind():
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    docs = FedConnector(fred_api_key=None).parse(_FOMC_RSS, since=epoch)
    assert len(docs) == 2
    fomc = next(d for d in docs if "Open Market" in (d.title or ""))
    other = next(d for d in docs if "Agency" in (d.title or ""))
    assert fomc.raw_meta["doc_kind"] == "fomc_minutes"
    assert other.raw_meta["doc_kind"] == "press_release"
    assert all(d.source_type == SourceType.FED for d in docs)


def test_parse_since_filter_excludes_old():
    future = datetime(2030, 1, 1, tzinfo=UTC)
    docs = FedConnector(fred_api_key=None).parse(_FOMC_RSS, since=future)
    assert docs == []


# ---- fetch() — offline güvenlik / mock ----------------------------------------------

@pytest.mark.asyncio
async def test_fetch_with_mocked_client_returns_docs(monkeypatch):
    fake = _FakeAsyncClient([_FakeResponse(200, content=_FOMC_RSS.encode())])
    monkeypatch.setattr(fed_connector.httpx, "AsyncClient", lambda **kw: fake)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    docs = await FedConnector(fred_api_key=None).fetch(epoch)
    assert len(docs) == 2
    assert fake.calls and fake.calls[0][0] == "GET"


@pytest.mark.asyncio
async def test_fetch_swallows_failure_and_returns_empty(monkeypatch):
    fake = _FakeAsyncClient([httpx.TimeoutException("timeout")] * 5)
    monkeypatch.setattr(fed_connector.httpx, "AsyncClient", lambda **kw: fake)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    docs = await FedConnector(fred_api_key=None).fetch(epoch)
    assert docs == []


# ---- uçtan uca mini test: FOMC metni fed_tone'u doğru yönde etkiler -----------------

@pytest.mark.asyncio
async def test_fomc_hawkish_text_moves_fed_tone_positive():
    """Hawkish (sıkılaşma) sinyalli bir FOMC metni sözleşmede fed_tone > 0 vermeli.

    İç konvansiyon: negatif polarite = hawkish (bkz. sentiment_feed.aggregate_to_state
    docstring'i); sözleşme ise hawkish=+1 ister, bu yüzden fed_tone = -mean_polarity.
    """
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    docs = FedConnector(fred_api_key=None).parse(_FOMC_RSS, since=epoch)
    doc = next(d for d in docs if d.raw_meta["doc_kind"] == "fomc_minutes")

    extractor = FinancialEntityExtractor()
    entities = await extractor.extract(doc)
    model = FinBERTSentiment(use_finbert=False)  # torch yok → sözlük fallback, deterministik
    scores = await model.score(doc, entities)
    fed_scores = [s for s in scores if s.entity == "FED"]
    assert fed_scores
    # Metin "warns"/"downgrade"/"weak" gibi negatif lexicon kelimeleri içeriyor →
    # iç konvansiyonda hawkish → polarite negatif olmalı.
    assert fed_scores[0].polarity < 0

    agg = aggregate("FED", fed_scores)
    state = aggregate_to_state(agg)
    assert state.fed_tone is not None and state.fed_tone > 0  # hawkish → sözleşmede pozitif
