"""Zaman penceresi toplama — skorları varlık bazında özetler.

MVP'de verilen skor listesini (genelde son N veya son T içindeki) tek bir
WindowAggregate'e indirger: hacim + ortalama polarite/yoğunluk/duygu.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.models import SentimentScore


@dataclass
class WindowAggregate:
    entity: str
    window: str
    volume: int
    mean_polarity: float
    mean_intensity: float
    mean_fear: float
    mean_greed: float
    mean_confidence: float


def aggregate(entity: str, scores: list[SentimentScore], window: str = "recent") -> WindowAggregate:
    """Skor listesini tek pencere özetine indirger. Boş liste → nötr/sıfır."""
    n = len(scores)
    if n == 0:
        return WindowAggregate(entity, window, 0, 0.0, 0.0, 0.0, 0.0, 0.0)
    inv = 1.0 / n
    return WindowAggregate(
        entity=entity,
        window=window,
        volume=n,
        mean_polarity=round(sum(s.polarity for s in scores) * inv, 4),
        mean_intensity=round(sum(s.intensity for s in scores) * inv, 2),
        mean_fear=round(sum(s.emotion.fear for s in scores) * inv, 4),
        mean_greed=round(sum(s.emotion.greed for s in scores) * inv, 4),
        mean_confidence=round(sum(s.confidence for s in scores) * inv, 4),
    )
