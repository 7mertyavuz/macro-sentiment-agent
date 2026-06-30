"""FinBERT tabanlı duyarlılık modeli — gerçek inference + sözlük fallback.

`ProsusAI/finbert` HuggingFace pipeline ile çalışır. transformers/torch kurulu
değilse veya use_finbert=False ise sözlük fallback'e düşer; böylece pipeline
her ortamda uçtan uca çalışır (ARCHITECTURE.md §6.1).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..core.models import Emotion, Entity, RawDocument, SentimentScore
from . import lexicon_fallback
from .preprocess import clean_text

log = logging.getLogger(__name__)

_MAX_CHARS = 1500


class FinBERTSentiment:
    """core.contracts.SentimentModel uygular."""

    def __init__(self, model_name: str = "ProsusAI/finbert", use_finbert: bool = True) -> None:
        self.model_name = model_name
        self.use_finbert = use_finbert
        self._pipeline = None
        self._loaded = False
        self.model_version = f"{model_name}@hf" if use_finbert else "lexicon-fallback@1"

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.use_finbert:
            log.info("FinBERT devre dışı; sözlük fallback kullanılıyor.")
            return
        try:
            from transformers import pipeline

            self._pipeline = pipeline("text-classification", model=self.model_name, top_k=None)
            log.info("FinBERT yüklendi: %s", self.model_name)
        except Exception as exc:
            log.warning("FinBERT yüklenemedi (%s); sözlük fallback'e geçiliyor.", exc)
            self._pipeline = None
            self.model_version = "lexicon-fallback@1"

    def _infer(self, text: str) -> dict:
        if self._pipeline is None:
            return lexicon_fallback.score_text(text)
        scores = self._pipeline(text[:_MAX_CHARS])[0]
        probs = {d["label"].lower(): float(d["score"]) for d in scores}
        pos, neg, neu = probs.get("positive", 0.0), probs.get("negative", 0.0), probs.get("neutral", 0.0)
        return {
            "polarity": round(pos - neg, 4),
            "intensity": round((pos + neg) * 100.0, 2),
            "confidence": round(max(pos, neg, neu), 4),
            "fear": round(neg, 4),
            "greed": round(pos, 4),
        }

    async def score(self, doc: RawDocument, entities: list[Entity]) -> list[SentimentScore]:
        self._ensure_loaded()
        text = clean_text(f"{doc.title or ''}. {doc.body}")
        r = self._infer(text)
        now = datetime.now(timezone.utc)
        emotion = Emotion(fear=r["fear"], greed=r["greed"], uncertainty=0.0)
        return [
            SentimentScore(
                doc_id=doc.id,
                entity=ent.ticker or ent.name,
                polarity=r["polarity"],
                intensity=r["intensity"],
                emotion=emotion,
                confidence=r["confidence"],
                model_version=self.model_version,
                source_type=doc.source_type,
                created_at=now,
            )
            for ent in entities
        ]
