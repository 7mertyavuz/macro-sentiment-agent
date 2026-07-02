"""LLM/hibrit NLP testleri — mock sağlayıcı, router, hibrit seçim, fallback."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from macro_sentiment.core.models import Entity, AssetClass, RawDocument, SourceType
from macro_sentiment.nlp.hybrid import HybridSentiment
from macro_sentiment.nlp.llm_provider import MockLLMProvider, _extract_json
from macro_sentiment.nlp.router import route_to_llm
from macro_sentiment.nlp.sentiment_finbert import FinBERTSentiment
from macro_sentiment.nlp.sentiment_llm import LLMSentiment


def _doc(body, *, title="t", stype=SourceType.NEWS) -> RawDocument:
    now = datetime.now(timezone.utc)
    return RawDocument(id="d1", source="s", source_type=stype, title=title, body=body,
                       published_at=now, fetched_at=now, content_hash="h")


def _ents():
    return [Entity(id="MARKET", name="MARKET", ticker="MARKET", asset_class=AssetClass.INDEX)]


def test_extract_json_tolerates_code_fence():
    assert _extract_json('```json\n{"a": 1}\n```')["a"] == 1


# --- router ---

def test_router_sends_fed_and_long_to_llm():
    assert route_to_llm(_doc("kısa", stype=SourceType.FED)) is True
    assert route_to_llm(_doc("x" * 2500)) is True
    assert route_to_llm(_doc("kısa haber")) is False


# --- LLM sentiment ---

@pytest.mark.asyncio
async def test_llm_uses_provider_json():
    prov = MockLLMProvider({"polarity": 0.7, "intensity": 80, "confidence": 0.9,
                            "fear": 0.0, "greed": 0.6, "stance": "neutral"})
    out = await LLMSentiment(prov).score(_doc("Apple beats"), _ents())
    assert out[0].polarity == 0.7 and out[0].model_version == "llm-mock@1"


@pytest.mark.asyncio
async def test_llm_fed_hawkish_is_negative():
    prov = MockLLMProvider({"polarity": 0.1, "stance": "hawkish", "fear": 0.3,
                            "greed": 0.0, "intensity": 50, "confidence": 0.8})
    out = await LLMSentiment(prov).score(_doc("FOMC minutes", stype=SourceType.FED), _ents())
    assert out[0].polarity < 0  # hawkish → negatif


@pytest.mark.asyncio
async def test_llm_falls_back_on_provider_error():
    class Boom:
        name = "boom"
        async def complete_json(self, s, u): raise RuntimeError("ağ hatası")
    out = await LLMSentiment(Boom()).score(_doc("plunge crash recession losses"), _ents())
    assert out[0].polarity < 0  # sözlük fallback negatif metni yakalar


# --- hibrit ---

@pytest.mark.asyncio
async def test_hybrid_routes_fed_to_llm_and_news_to_finbert():
    llm = LLMSentiment(MockLLMProvider({"polarity": -0.5, "stance": "hawkish",
                       "fear": 0.4, "greed": 0.0, "intensity": 70, "confidence": 0.8}))
    hybrid = HybridSentiment(FinBERTSentiment(use_finbert=False), llm)

    fed = await hybrid.score(_doc("FOMC minutes", stype=SourceType.FED), _ents())
    assert fed[0].model_version.startswith("llm-")        # Fed → LLM

    news = await hybrid.score(_doc("Apple surge beats record"), _ents())
    assert news[0].model_version == "lexicon-fallback@1"  # kısa haber → FinBERT


@pytest.mark.asyncio
async def test_hybrid_falls_back_when_llm_raises():
    class FailingLLM:
        model_version = "llm-x@1"
        async def score(self, doc, ents): raise RuntimeError("patladı")
    hybrid = HybridSentiment(FinBERTSentiment(use_finbert=False), FailingLLM())
    out = await hybrid.score(_doc("recession crash", stype=SourceType.FED), _ents())
    assert out[0].model_version == "lexicon-fallback@1"  # hata → FinBERT


# --- Faz 7: opt-in füzyon modu -----------------------------------------------------

@pytest.mark.asyncio
async def test_hybrid_default_does_not_fuse():
    """fuse_high_impact varsayılan False → eski davranış (yalnızca LLM) korunur."""
    llm = LLMSentiment(MockLLMProvider({"polarity": -0.5, "stance": "hawkish",
                       "fear": 0.4, "greed": 0.0, "intensity": 70, "confidence": 0.8}))
    hybrid = HybridSentiment(FinBERTSentiment(use_finbert=False), llm)
    out = await hybrid.score(_doc("FOMC minutes", stype=SourceType.FED), _ents())
    assert out[0].model_version.startswith("llm-")
    assert not out[0].model_version.startswith("fusion(")


@pytest.mark.asyncio
async def test_hybrid_fuse_high_impact_combines_finbert_and_llm():
    llm = LLMSentiment(MockLLMProvider({"polarity": -0.5, "stance": "hawkish",
                       "fear": 0.4, "greed": 0.0, "intensity": 70, "confidence": 0.8}))
    hybrid = HybridSentiment(
        FinBERTSentiment(use_finbert=False), llm, fuse_high_impact=True,
    )
    out = await hybrid.score(_doc("Fed warns of downgrade risk", stype=SourceType.FED), _ents())
    assert out[0].model_version.startswith("fusion(")
    assert "llm-" in out[0].model_version and "lexicon-fallback" in out[0].model_version


@pytest.mark.asyncio
async def test_hybrid_fuse_high_impact_skips_low_impact_docs():
    """Rutin (düşük etkili) belgeler füzyon modunda bile yalnızca FinBERT'e gider."""
    llm = LLMSentiment(MockLLMProvider({"polarity": 0.5, "stance": "neutral",
                       "fear": 0.0, "greed": 0.4, "intensity": 60, "confidence": 0.8}))
    hybrid = HybridSentiment(
        FinBERTSentiment(use_finbert=False), llm, fuse_high_impact=True,
    )
    out = await hybrid.score(_doc("Apple surge beats record"), _ents())
    assert out[0].model_version == "lexicon-fallback@1"
