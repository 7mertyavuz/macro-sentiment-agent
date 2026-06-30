"""Skor birleştirme + duygu yoğunluğu.

Birden çok modelin (FinBERT + LLM) çıktısını güven-ağırlıklı birleştirir ve
korku/coşku/belirsizlik boyutlarını üretir (ARCHITECTURE.md §6.1 adım 4-5).
"""
from __future__ import annotations

from ..core.models import Emotion, SentimentScore


def fuse(scores: list[SentimentScore]) -> SentimentScore:
    """Aynı (doc, entity) için birden çok model skorunu güven-ağırlıklı birleştir.

    TODO(Faz 2): ağırlıklı ortalama; modeller çelişirse güveni düşür.
    """
    raise NotImplementedError


def derive_emotion(polarity: float, intensity: float, text: str) -> Emotion:
    """Polarite + yoğunluk + sözlük sinyallerinden duygu boyutları türetir.

    TODO(Faz 2): korku/coşku/belirsizlik sözlükleri + model çıktısı.
    """
    raise NotImplementedError
