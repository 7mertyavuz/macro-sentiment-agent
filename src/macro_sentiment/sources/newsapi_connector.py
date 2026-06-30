"""NewsAPI.org connector (anahtar gerekir). TODO(Faz 1)."""
from __future__ import annotations

from datetime import datetime

from ..core.models import RawDocument, SourceType
from .base import BaseConnector


class NewsAPIConnector(BaseConnector):
    source_id = "newsapi"
    source_type = SourceType.NEWS

    def __init__(self, api_key: str | None) -> None:
        self.api_key = api_key

    async def fetch(self, since: datetime) -> list[RawDocument]:
        # TODO(Faz 1): httpx ile /v2/everything?from=since çek, normalize et.
        raise NotImplementedError
