"""Normalizasyon — kaynağa özel ham yanıtı ortak RawDocument şemasına çevirir.

Connector'lar genelde kendi normalize'ını yapar; bu modül ortak yardımcıları
(tarih ayrıştırma, dil tespiti, alan temizliği) toplar. TODO(Faz 1).
"""
from __future__ import annotations

from ..core.models import RawDocument


def detect_lang(text: str) -> str:
    # TODO(Faz 1): hızlı dil tespiti (örn. fasttext/langid).
    return "en"


def normalize(raw_meta: dict, *, source: str) -> RawDocument:
    # TODO(Faz 1): kaynağa özel alan eşleme + temizlik.
    raise NotImplementedError
