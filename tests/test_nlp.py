"""NLP testleri — sözlük fallback skorlayıcı ve varlık çıkarımı."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from macro_sentiment.core.models import RawDocument, SourceType
from macro_sentiment.nlp import lexicon_fallback
from macro_sentiment.nlp.ner import FinancialEntityExtractor
from macro_sentiment.nlp.preprocess import clean_text
from macro_sentiment.nlp.sentiment_finbert import FinBERTSentiment


def _doc(title: str, body: str) -> RawDocument:
    now = datetime.now(timezone.utc)
    return RawDocument(
        id="t1", source="rss:test", source_type=SourceType.NEWS,
        title=title, body=body, published_at=now, fetched_at=now, content_hash="h",
    )


def test_clean_text_strips_html_and_urls():
    assert clean_text("<b>Hi</b> see https://x.com now") == "Hi see now"


def test_lexicon_positive_vs_negative():
    pos = lexicon_fallback.score_text("surge rally record profit beats")
    neg = lexicon_fallback.score_text("plunge crash recession losses selloff")
    assert pos["polarity"] > 0
    assert neg["polarity"] < 0
    assert neg["fear"] > 0


@pytest.mark.asyncio
async def test_entity_extraction_cashtag_and_name():
    ext = FinancialEntityExtractor()
    ents = await ext.extract(_doc("Apple beats", "Strong quarter for $NVDA and Apple"))
    tickers = {e.ticker for e in ents}
    assert "AAPL" in tickers and "NVDA" in tickers


@pytest.mark.asyncio
async def test_entity_defaults_to_market():
    ext = FinancialEntityExtractor()
    ents = await ext.extract(_doc("Generic headline", "no tickers here"))
    assert ents[0].ticker == "MARKET"


@pytest.mark.asyncio
async def test_finbert_fallback_scores_document():
    model = FinBERTSentiment(use_finbert=False)  # torch yok → fallback
    ext = FinancialEntityExtractor()
    doc = _doc("Bitcoin plunges", "recession fears trigger selloff and losses for $BTC")
    scores = await model.score(doc, await ext.extract(doc))
    assert scores and scores[0].polarity < 0
    assert scores[0].model_version == "lexicon-fallback@1"
