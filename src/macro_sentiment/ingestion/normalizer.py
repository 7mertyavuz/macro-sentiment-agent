"""Normalizasyon — kaynağa özel ham yanıtı ortak RawDocument şemasına çevirir.

Connector'lar genelde kendi normalize'ını yapar; bu modül ortak yardımcıları
(tarih ayrıştırma, dil tespiti, alan temizliği) toplar. TODO(Faz 1).
"""
from __future__ import annotations

import re

from ..core.models import RawDocument

_URL_RE = re.compile(r"https?://\S+")
_WHITESPACE_RE = re.compile(r"\s+")
_CASHTAG_KEEP_RE = re.compile(r"^\$[A-Za-z]{1,5}$")


def detect_lang(text: str) -> str:
    # TODO(Faz 1): hızlı dil tespiti (örn. fasttext/langid).
    return "en"


def strip_social_noise(text: str) -> str:
    """Sosyal medya metnini NLP için temizler (Faz 9).

    URL'leri kaldırır (bilgi taşımazlar, model için gürültü); cashtag'leri
    ($AAPL gibi) korur çünkü NER bunlara dayanır; fazla boşluğu sıkıştırır.
    Duygu/anlam taşıyan hashtag/mention'lara dokunmaz — spam sezgisi ayrı
    katmanda (``nlp/spam_filter.py``) ele alınır, burada yalnızca temizlik var.
    """
    if not text:
        return text
    cleaned = _URL_RE.sub("", text)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    return cleaned


def normalize(raw_meta: dict, *, source: str) -> RawDocument:
    # TODO(Faz 1): kaynağa özel alan eşleme + temizlik.
    raise NotImplementedError


__all__ = ["detect_lang", "strip_social_noise", "normalize"]
