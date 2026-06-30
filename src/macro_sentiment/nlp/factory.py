"""Duyarlılık modeli fabrikası — config'e göre finbert / llm / hybrid kurar."""
from __future__ import annotations

import logging

from .hybrid import HybridSentiment
from .llm_provider import build_provider
from .sentiment_finbert import FinBERTSentiment
from .sentiment_llm import LLMSentiment

log = logging.getLogger(__name__)


def build_sentiment_model(settings):
    """nlp_mode'a göre SentimentModel döndürür. LLM anahtarı yoksa FinBERT'e düşer."""
    finbert = FinBERTSentiment(model_name=settings.finbert_model, use_finbert=settings.use_finbert)
    mode = settings.nlp_mode

    if mode == "finbert":
        return finbert

    provider = build_provider(settings)
    if provider is None:
        log.warning("LLM sağlayıcı yok (anahtar eksik); FinBERT kullanılacak.")
        return finbert

    llm = LLMSentiment(provider)
    if mode == "llm":
        return llm
    return HybridSentiment(finbert, llm)  # "hybrid"
