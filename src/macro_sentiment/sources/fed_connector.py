"""Fed / merkez bankası connector — FOMC basın açıklamaları — Faz 8.

Basın açıklamaları Fed'in herkese açık RSS akışından çekilir (metin için
anahtar gerekmez). ``fred_api_key`` şu an yalnızca bu connector'ın etkin
kaynak listesine alınıp alınmayacağını belirler (``sources/registry.py::
active_connectors``); ileride FRED takvim API'siyle ek doğrulama/filtre için
kullanılabilir (kapsam dışı — Faz 8'in "bitti" tanımı yalnızca metin çekimini
kapsıyor).

Tutanak/basın metni 'hawkish/dovish' analizi için ``raw_meta`` ile işaretlenir
(ARCHITECTURE.md §4.2); ``SourceType.FED`` zaten ``nlp/router.py`` tarafından
LLM yoluna yönlendirilir, LLM promptu ``stance`` sorar.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from time import mktime

import feedparser
import httpx

from ..core.models import RawDocument, SourceType
from .base import BaseConnector, SimpleRateLimit, fetch_with_retry

log = logging.getLogger(__name__)

_PRESS_RSS_URL = "https://www.federalreserve.gov/feeds/press_monetary.xml"
_FOMC_HINTS = ("fomc", "federal open market committee", "monetary policy")


def _entry_datetime(entry) -> datetime:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime.fromtimestamp(mktime(t), tz=timezone.utc)
    return datetime.now(timezone.utc)


def _entry_body(entry) -> str:
    if entry.get("content"):
        return entry["content"][0].get("value", "") or ""
    return entry.get("summary", "") or entry.get("title", "") or ""


def _doc_kind(title: str | None, body: str) -> str:
    """Metnin FOMC tutanağı/kararı mı yoksa genel basın açıklaması mı olduğunu sezgisel belirler."""
    text = f"{title or ''} {body}".lower()
    return "fomc_minutes" if any(h in text for h in _FOMC_HINTS) else "press_release"


class FedConnector(BaseConnector):
    source_id = "fed"
    source_type = SourceType.FED

    def __init__(
        self,
        fred_api_key: str | None,
        *,
        feed_url: str = _PRESS_RSS_URL,
        timeout: float = 10.0,
    ) -> None:
        self.fred_api_key = fred_api_key
        self.feed_url = feed_url
        self.timeout = timeout

    def rate_limit(self) -> SimpleRateLimit:
        return SimpleRateLimit(max_calls=30, per_seconds=3600.0)

    async def fetch(self, since: datetime) -> list[RawDocument]:
        async with httpx.AsyncClient(
            timeout=self.timeout, follow_redirects=True,
            headers={"User-Agent": "macro-sentiment-agent/0.1"},
        ) as client:
            try:
                resp = await fetch_with_retry(client, "GET", self.feed_url)
            except Exception:
                log.exception("Fed basın akışı çekilemedi; bu tur atlanıyor")
                return []
        return self.parse(resp.content, since=since)

    def parse(self, raw_xml: bytes | str, *, since: datetime) -> list[RawDocument]:
        """Ham RSS içeriğini RawDocument listesine dönüştürür (ağ gerektirmez — test edilebilir).

        FOMC ile ilgili görünen girişler ``raw_meta={"doc_kind": "fomc_minutes"}``
        ile işaretlenir; diğerleri ``"press_release"``.
        """
        parsed = feedparser.parse(raw_xml)
        now = datetime.now(timezone.utc)
        out: list[RawDocument] = []
        for entry in parsed.entries:
            published = _entry_datetime(entry)
            if published <= since:
                continue
            title = entry.get("title")
            body = _entry_body(entry)
            if not body.strip():
                continue
            out.append(
                RawDocument(
                    id=entry.get("id") or entry.get("link") or self.content_hash(title, body),
                    source="fed:press",
                    source_type=self.source_type,
                    url=entry.get("link"),
                    title=title,
                    body=body,
                    published_at=published,
                    fetched_at=now,
                    content_hash=self.content_hash(title, body),
                    raw_meta={"doc_kind": _doc_kind(title, body)},
                )
            )
        return out


__all__ = ["FedConnector"]
