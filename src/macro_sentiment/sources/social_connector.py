"""Sosyal medya connector — X (Twitter) / Reddit / StockTwits.

Sosyal akışta bot/spam temizliği ve sarkazm yönetimi kritiktir
(ARCHITECTURE.md §4.3, §6.3). TODO(Faz 2).
"""
from __future__ import annotations

from datetime import datetime

from ..core.models import RawDocument, SourceType
from .base import BaseConnector


class SocialConnector(BaseConnector):
    source_id = "social"
    source_type = SourceType.SOCIAL

    def __init__(self, platform: str, credentials: dict | None = None) -> None:
        self.platform = platform           # "twitter" | "reddit" | "stocktwits"
        self.credentials = credentials or {}

    async def fetch(self, since: datetime) -> list[RawDocument]:
        # TODO(Faz 2): platforma göre filtreli akış/polling; bot filtresi uygula.
        raise NotImplementedError
