"""Normalizasyon yardımcıları — metin temizliği ve dil tespiti.

Kaynağa özel alan eşlemesini her connector kendi `fetch()` metodunda yapıyor;
bu modül yalnızca ortak metin yardımcılarını barındırır.
"""
from __future__ import annotations

import re

_URL_RE = re.compile(r"https?://\S+")
_WHITESPACE_RE = re.compile(r"\s+")
_CASHTAG_KEEP_RE = re.compile(r"^\$[A-Za-z]{1,5}$")


def detect_lang(text: str) -> str:
    """Dil tespiti — şu an SABİT "en" döndürür.

    Bu bir stub'dır ve öyle olduğu açıkça yazılmıştır: kaynaklarımız (RSS,
    NewsAPI, Fed, StockTwits) fiilen İngilizce yayın yapıyor, dolayısıyla
    yanlış bir cevap üretmiyor — ama bir dil TESPİTİ de yapmıyor. Türkçe/çok
    dilli kaynak eklenirse fasttext/langid gerekir.
    """
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


# `normalize()` KALDIRILDI. Fırlatan bir gövde bırakmak tuzaktır: çağıran
# fonksiyonun var olduğunu sanır. Kaynağa özel alan eşlemesini her connector
# kendi `fetch()` metodunda yapıyor (bkz. sources/*_connector.py); ortak bir
# normalize katmanı için gerçek bir ihtiyaç doğmadı. Buradaki yardımcılar
# (detect_lang, strip_social_noise) connector'lar tarafından kullanılıyor.

__all__ = ["detect_lang", "strip_social_noise"]
