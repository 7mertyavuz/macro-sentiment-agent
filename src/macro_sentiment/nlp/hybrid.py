"""Hibrit duyarlılık modeli (ARCHITECTURE.md §6.1).

Yönlendirme (router) ile maliyet kontrolü: rutin metinler ucuz FinBERT'e,
yüksek-etkili/uzun/Fed metinleri pahalı LLM'e gider. LLM hata verirse FinBERT'e
düşer. core.contracts.SentimentModel uygular.
"""
from __future__ import annotations

import logging

from ..core.models import Entity, RawDocument, SentimentScore
from .router import route_to_llm
from .sentiment_finbert import FinBERTSentiment
from .sentiment_llm import LLMSentiment

log = logging.getLogger(__name__)


class HybridSentiment:
    def __init__(self, finbert: FinBERTSentiment, llm: LLMSentiment | None = None) -> None:
        self.finbert = finbert
        self.llm = llm
        self.model_version = "hybrid@1"

    async def score(self, doc: RawDocument, entities: list[Entity]) -> list[SentimentScore]:
        if self.llm is not None and route_to_llm(doc):
            try:
                return await self.llm.score(doc, entities)
            except Exception:
                log.exception("LLM yolu başarısız; FinBERT'e düşülüyor")
        return await self.finbert.score(doc, entities)
