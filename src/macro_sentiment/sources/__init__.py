"""Katman 1 — Veri kaynakları.

Her connector `core.contracts.SourceConnector` Protocol'ünü uygular.
Yeni bir kaynak eklemek için yeni bir connector yazmak yeterlidir; çekirdek değişmez.

Mevcut connector'lar:
    rss        — RSS/Atom akarları (anahtarsız, referans uygulama)
    newsapi    — NewsAPI.org (anahtar gerekir)
    fed        — FRED + FOMC tutanakları
    social     — X (Twitter) / Reddit / StockTwits
"""
from .registry import REGISTRY, get_connector

__all__ = ["REGISTRY", "get_connector"]
