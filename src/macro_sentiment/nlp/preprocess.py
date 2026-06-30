"""Ön işleme — temizleme, dil tespiti, spam/bot filtresi."""
from __future__ import annotations

import html
import re

from ..core.models import RawDocument

_TAG_RE = re.compile(r"<[^>]+>")
_URL_RE = re.compile(r"https?://\S+")
_WS_RE = re.compile(r"\s+")


def clean_text(text: str) -> str:
    """HTML etiketleri/varlıkları ve URL'leri temizler, boşlukları normalize eder."""
    if not text:
        return ""
    text = html.unescape(text)
    text = _TAG_RE.sub(" ", text)
    text = _URL_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def detect_lang(text: str) -> str:
    return "en"  # TODO(Faz 2): fasttext/langid


def is_spam(doc: RawDocument) -> bool:
    return False  # TODO(Faz 2): bot/spam sınıflandırıcı
