"""cas-market-simulator ortak sözleşme tipleri (00-ORTAK-SOZLESME.md).

Bu modül, hibrit CAS sisteminin `SentimentState` ve `ShockEvent` veri tiplerini
bu reponun tarafında birebir yeniden tanımlar. Amaç *gevşek bağlılık*: repo,
simülatör paketine kod bağımlılığı taşımaz; yalnızca aynı veri sözleşmesini
üretir. Ortak sözleşme değişirse yalnızca bu dosya güncellenir.

Not: Bu tipler kasıtlı olarak ince ve bağımsızdır (yalnızca stdlib). İç Pydantic
modelleri (`core.models`) ile karıştırılmaz; adaptör katmanı (`sentiment_feed`)
iç modelleri bu tiplere çevirir.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# Sözleşmede tanımlı geçerli şok türleri.
SHOCK_KINDS = ("panic", "euphoria", "fed_tone", "narrative_shift")


@dataclass
class SentimentState:
    """Katman 1 köprüsü — yeni indikatör motoruna beslenen anlatı/makro durumu.

    Alanlar 00-ORTAK-SOZLESME.md'deki sözleşmeyle birebir aynıdır.
    """

    entity: str
    polarity: float                 # [-1,+1] genel duyarlılık
    intensity: float                # 0..100 şiddet
    emotion: dict                   # {"fear","greed","uncertainty"} her biri 0..1
    confidence: float               # 0..1
    fed_tone: float | None          # hawkish(+1)/dovish(-1) ekseni; yoksa None
    source_breakdown: dict          # {"news","social","fed"} -> polarite
    ts: datetime


@dataclass
class ShockEvent:
    """Katman 2 — simülasyona 'dışsal şok' olarak enjekte edilen olay."""

    kind: str                       # "panic" | "euphoria" | "fed_tone" | "narrative_shift"
    entity: str
    magnitude: float                # 0..1 (şok büyüklüğü)
    decay_halflife_s: float         # şokun yarılanma süresi (sönümlenme)
    ts: datetime
    meta: dict = field(default_factory=dict)  # ek bağlam (opsiyonel; sözleşmeyi bozmaz)
