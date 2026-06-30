"""Yönlendirme — her belgeyi ucuz (FinBERT) veya pahalı (LLM) yola gönderir.

Maliyet kontrolünün anahtarı (ARCHITECTURE.md §6.1 adım 3).
"""
from __future__ import annotations

from ..core.models import RawDocument, SourceType


def route_to_llm(doc: RawDocument) -> bool:
    """Belge LLM'e mi gitmeli? (Faz 2'de aktif olur.)

    Sezgisel kurallar:
      - Fed tutanağı / kazanç çağrısı gibi yüksek-etki metinler → LLM
      - uzun ve karmaşık metinler → LLM
      - kısa rutin başlıklar → FinBERT
    """
    if doc.source_type == SourceType.FED:
        return True
    if len(doc.body) > 2000:
        return True
    return False
