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


# ── NER: sözcük sınırı ve kripto kapsamı ──────────────────────────
def _ner_doc(title: str):
    now = datetime.now(timezone.utc)
    return RawDocument(id="n1", source="rss:test", source_type=SourceType.NEWS,
                       title=title, body="", published_at=now, fetched_at=now,
                       content_hash="h")


@pytest.mark.asyncio
async def test_solana_is_recognised():
    """Sözlükte yalnızca bitcoin/ethereum vardı; 'Solana' geçen her belge
    MARKET'e düşüyordu, yani SOL için duyu haber gelse bile hiç doğmuyordu."""
    from macro_sentiment.nlp.ner import FinancialEntityExtractor

    ents = await FinancialEntityExtractor().extract(_ner_doc("Solana ETF approved"))
    assert {e.ticker for e in ents} == {"SOL"}


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["The console was sold out",
                                  "Whether the method works",
                                  "Canada raises rates",
                                  "Together we resolve this"])
async def test_short_aliases_do_not_match_inside_words(text):
    """Alt-dize eşleşmesi bir yanlış-pozitif makinesidir: sol→console/sold,
    eth→whether/method, ada→Canada. Olmayan bir varlığa üretilen skor GERÇEK
    görünür — sessiz gürültünün en kötü türü."""
    from macro_sentiment.nlp.ner import FinancialEntityExtractor

    ents = await FinancialEntityExtractor().extract(_ner_doc(text))
    assert {e.ticker for e in ents} == {"MARKET"}


@pytest.mark.asyncio
async def test_fomc_maps_to_fed_by_its_own_name():
    """Eskiden 'fed' ⊂ 'Federal Open Market Committee' kazasıyla eşleşiyordu."""
    from macro_sentiment.nlp.ner import FinancialEntityExtractor

    ents = await FinancialEntityExtractor().extract(
        _ner_doc("Federal Open Market Committee statement"))
    assert "FED" in {e.ticker for e in ents}


@pytest.mark.asyncio
async def test_crypto_assets_are_classed_as_crypto():
    from macro_sentiment.core.models import AssetClass
    from macro_sentiment.nlp.ner import FinancialEntityExtractor

    ents = await FinancialEntityExtractor().extract(_ner_doc("Solana and Bitcoin rally"))
    assert all(e.asset_class == AssetClass.CRYPTO for e in ents)


def test_default_feeds_include_crypto_sources():
    """Varsayılan liste yalnızca hisse haberi çekiyordu: BTC/ETH/SOL için tek
    belge bile gelmiyordu ve duyu 'haber yok' diye değil 'kaynak yok' diye
    sessizdi — ikisi dışarıdan ayırt edilemez."""
    from macro_sentiment.core.config import DEFAULT_RSS_FEEDS

    joined = " ".join(DEFAULT_RSS_FEEDS).lower()
    assert any(k in joined for k in ("coindesk", "cointelegraph", "cryptoslate"))
