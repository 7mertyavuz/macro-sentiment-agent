"""NewsAPI.org connector (anahtar gerekir) — Faz 8.

``/v2/everything`` uç noktasıyla geniş finansal haber taraması yapar ve ortak
``RawDocument`` şemasına normalize eder. Anahtar yoksa ``fetch()`` ağa hiç
çıkmadan boş liste döner — sistem offline gibi çalışmaya devam eder
(``sources/registry.py::active_connectors`` zaten anahtarsızken bu connector'ı
etkin listeye eklemez, ama doğrudan çağrılırsa da güvenli).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from ..core.models import RawDocument, SourceType
from .base import BaseConnector, SimpleRateLimit, fetch_with_retry

log = logging.getLogger(__name__)

_BASE_URL = "https://newsapi.org/v2/everything"
_DEFAULT_QUERY = (
    '"federal reserve" OR "stock market" OR earnings OR inflation OR '
    "recession OR rally OR selloff OR rate hike OR rate cut"
)


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


class NewsAPIConnector(BaseConnector):
    source_id = "newsapi"
    source_type = SourceType.NEWS

    def __init__(
        self,
        api_key: str | None,
        *,
        query: str = _DEFAULT_QUERY,
        language: str = "en",
        page_size: int = 50,
        timeout: float = 10.0,
    ) -> None:
        self.api_key = api_key
        self.query = query
        self.language = language
        self.page_size = page_size
        self.timeout = timeout

    def rate_limit(self) -> SimpleRateLimit:
        # NewsAPI ücretsiz katman günde ~100 istekle sınırlıdır; ihtiyatlı tavan.
        return SimpleRateLimit(max_calls=80, per_seconds=86400.0)

    async def fetch(self, since: datetime) -> list[RawDocument]:
        if not self.api_key:
            log.info("NEWSAPI_KEY yok; NewsAPIConnector.fetch() ağa çıkmadan atlanıyor.")
            return []
        params = {
            "q": self.query,
            "from": since.astimezone(timezone.utc).isoformat(timespec="seconds"),
            "sortBy": "publishedAt",
            "language": self.language,
            "pageSize": self.page_size,
            "apiKey": self.api_key,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await fetch_with_retry(client, "GET", _BASE_URL, params=params)
            except Exception:
                log.exception("NewsAPI isteği başarısız; bu tur atlanıyor")
                return []
        return self.parse(resp.json())

    def parse(self, payload: dict) -> list[RawDocument]:
        """API JSON gövdesini RawDocument listesine çevirir (ağ gerektirmez — test edilebilir)."""
        now = datetime.now(timezone.utc)
        out: list[RawDocument] = []
        for art in payload.get("articles", []):
            title = art.get("title")
            body = art.get("description") or art.get("content") or title or ""
            if not body or not body.strip():
                continue
            published = _parse_dt(art.get("publishedAt")) or now
            url = art.get("url") or ""
            source_name = (art.get("source") or {}).get("name", "unknown")
            out.append(
                RawDocument(
                    id=url or self.content_hash(title, body),
                    source=f"newsapi:{source_name}",
                    source_type=self.source_type,
                    url=url or None,
                    title=title,
                    body=body,
                    published_at=published,
                    fetched_at=now,
                    content_hash=self.content_hash(title, body),
                    raw_meta={"newsapi_source_id": (art.get("source") or {}).get("id")},
                )
            )
        return out


__all__ = ["NewsAPIConnector"]
