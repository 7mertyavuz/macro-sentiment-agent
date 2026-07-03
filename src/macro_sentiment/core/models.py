"""Sistem genelinde paylaşılan veri modelleri (ARCHITECTURE.md §9).

Bu modeller katmanlar arası sözleşmenin temelidir; kuyruk mesajları ve
veritabanı kayıtları bunlara göre serileştirilir.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class AssetClass(str, Enum):
    EQUITY = "equity"
    CRYPTO = "crypto"
    FX = "fx"
    COMMODITY = "commodity"
    INDEX = "index"
    MACRO = "macro"


class SourceType(str, Enum):
    NEWS = "news"
    FED = "fed"
    SOCIAL = "social"
    MARKET = "market"


class RawDocument(BaseModel):
    """Bir kaynaktan çekilen, normalize edilmiş ham metin belgesi (Katman 2 çıktısı)."""

    id: str = Field(..., description="Kaynak-içi benzersiz kimlik veya içerik hash'i")
    source: str = Field(..., description="Connector source_id, örn. 'rss:reuters'")
    source_type: SourceType
    url: str | None = None
    title: str | None = None
    body: str
    lang: str = "en"
    published_at: datetime
    fetched_at: datetime
    content_hash: str = Field(..., description="Dedup için içerik hash'i")
    raw_meta: dict = Field(default_factory=dict)


class Entity(BaseModel):
    """Bir metnin işaret ettiği finansal varlık (NER + sözlük eşleme sonucu)."""

    id: str
    name: str
    ticker: str | None = None
    asset_class: AssetClass
    aliases: list[str] = Field(default_factory=list)


class Emotion(BaseModel):
    """Duygu yoğunluğu boyutları (ARCHITECTURE.md §6.1)."""

    fear: float = 0.0
    greed: float = 0.0
    uncertainty: float = 0.0


class SentimentScore(BaseModel):
    """Bir belge + varlık çifti için duyarlılık skoru (Katman 3 çıktısı)."""

    doc_id: str
    entity: str
    polarity: float = Field(..., ge=-1.0, le=1.0, description="-1 negatif … +1 pozitif")
    intensity: float = Field(..., ge=0.0, le=100.0)
    emotion: Emotion = Field(default_factory=Emotion)
    confidence: float = Field(..., ge=0.0, le=1.0)
    model_version: str
    source_type: SourceType
    created_at: datetime


class SignalType(str, Enum):
    PANIC = "panic"            # aşırı korku / panik satışı
    EUPHORIA = "euphoria"      # aşırı coşku / tepe riski
    FED_TONE = "fed_tone"      # hawkish/dovish kayması
    NARRATIVE = "narrative"    # anlatı değişimi
    BREAKOUT = "breakout"      # olağandışı aktivite


class Signal(BaseModel):
    """Sinyal motorunun ürettiği eyleme-dönük uyarı (Katman 4 çıktısı)."""

    id: str
    entity: str
    type: SignalType
    severity: float = Field(..., ge=0.0, le=100.0)
    direction: float = Field(..., ge=-1.0, le=1.0)
    window: str = Field(..., description="ISO 8601 aralığı, örn. '.../PT1H'")
    headline: str = Field(..., description="İnsan-okunur özet, örn. 'BTC — aşırı korku'")
    payload: dict = Field(default_factory=dict)
    created_at: datetime
    # Faz 11: HITL inceleme durumu. None = inceleme gerektirmedi (varsayılan,
    # eski davranış); "pending" = onay bekliyor (dağıtılmadı); "approved" /
    # "rejected" = insan kararı verildi. Varsayılanlı olduğu için mevcut
    # çağıranlar/testler etkilenmez (geriye uyum).
    review_status: str | None = None
