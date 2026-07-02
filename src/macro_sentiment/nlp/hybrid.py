"""Hibrit duyarlılık modeli (ARCHITECTURE.md §6.1).

Yönlendirme (router) ile maliyet kontrolü: rutin metinler ucuz FinBERT'e,
yüksek-etkili/uzun/Fed metinleri pahalı LLM'e gider. LLM hata verirse FinBERT'e
düşer. core.contracts.SentimentModel uygular.

Faz 7 — opt-in füzyon modu: ``fuse_high_impact=True`` verilirse, yüksek-etki
belgelerde (route_to_llm=True) FinBERT + LLM birlikte çalıştırılır ve aynı
varlık için ``nlp.fusion.fuse`` ile güven-ağırlıklı birleştirilir. Varsayılan
``False`` — mevcut davranış (yalnızca LLM veya yalnızca FinBERT) ve mevcut
testler değişmeden korunur (geriye uyum).
"""
from __future__ import annotations

import asyncio
import logging

from ..core.models import Entity, RawDocument, SentimentScore
from .fusion import fuse
from .router import route_to_llm
from .sentiment_finbert import FinBERTSentiment
from .sentiment_llm import LLMSentiment

log = logging.getLogger(__name__)


class HybridSentiment:
    def __init__(
        self,
        finbert: FinBERTSentiment,
        llm: LLMSentiment | None = None,
        *,
        fuse_high_impact: bool = False,
    ) -> None:
        self.finbert = finbert
        self.llm = llm
        self.fuse_high_impact = fuse_high_impact
        self.model_version = "hybrid@1"

    async def score(self, doc: RawDocument, entities: list[Entity]) -> list[SentimentScore]:
        if self.llm is not None and route_to_llm(doc):
            if self.fuse_high_impact:
                try:
                    return await self._score_fused(doc, entities)
                except Exception:
                    log.exception("Füzyon yolu başarısız; yalnızca LLM'e düşülüyor")
            try:
                return await self.llm.score(doc, entities)
            except Exception:
                log.exception("LLM yolu başarısız; FinBERT'e düşülüyor")
        return await self.finbert.score(doc, entities)

    async def _score_fused(self, doc: RawDocument, entities: list[Entity]) -> list[SentimentScore]:
        """Yüksek-etki belgede FinBERT + LLM'i birlikte çalıştırıp varlık başına füzyonlar.

        FinBERT lokal ve ucuzdur; LLM zaten bu belge için ödeniyor (route_to_llm=True),
        bu yüzden ikisini birden çalıştırmak maliyet kontrolünü bozmaz.
        """
        llm_scores, fin_scores = await asyncio.gather(
            self.llm.score(doc, entities), self.finbert.score(doc, entities)
        )
        by_entity: dict[str, list[SentimentScore]] = {}
        for s in (*llm_scores, *fin_scores):
            by_entity.setdefault(s.entity, []).append(s)
        return [fuse(group) for group in by_entity.values()]
