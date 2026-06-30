"""Fed / merkez bankası connector — FRED API + FOMC tutanakları.

Tutanak metni 'hawkish/dovish' analizi için NLP katmanına özel işaretle gönderilir
(ARCHITECTURE.md §4.2). TODO(Faz 2).
"""
from __future__ import annotations

from datetime import datetime

from ..core.models import RawDocument, SourceType
from .base import BaseConnector


class FedConnector(BaseConnector):
    source_id = "fed"
    source_type = SourceType.FED

    def __init__(self, fred_api_key: str | None) -> None:
        self.fred_api_key = fred_api_key

    async def fetch(self, since: datetime) -> list[RawDocument]:
        # TODO(Faz 2): FRED takvimi + FOMC press release/tutanak metnini çek.
        #   raw_meta'ya {"doc_kind": "fomc_minutes"} ekleyerek NLP'de hawkish/dovish
        #   ekseninin tetiklenmesini sağla.
        raise NotImplementedError
