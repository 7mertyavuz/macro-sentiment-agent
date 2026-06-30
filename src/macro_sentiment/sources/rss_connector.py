"""RSS/Atom connector — gerçek uygulama (anahtarsız).

httpx ile akarları asenkron indirir, feedparser ile ayrıştırır ve ortak
RawDocument şemasına normalize eder. Tek bir akarın hatası tüm çekimi bozmaz.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from time import mktime

import feedparser
import httpx

from ..core.models import RawDocument, SourceType
from .base import BaseConnector, SimpleRateLimit

log = logging.getLogger(__name__)


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


class RSSConnector(BaseConnector):
    source_id = "rss"
    source_type = SourceType.NEWS

    def __init__(self, feeds: list[str], *, timeout: float = 10.0) -> None:
        self.feeds = feeds
        self.timeout = timeout

    def rate_limit(self) -> SimpleRateLimit:
        return SimpleRateLimit(max_calls=120, per_seconds=60.0)

    async def fetch(self, since: datetime) -> list[RawDocument]:
        """Tüm akarları paralel çeker; `since`'ten yeni girişleri döndürür."""
        async with httpx.AsyncClient(
            timeout=self.timeout, follow_redirects=True,
            headers={"User-Agent": "macro-sentiment-agent/0.1"},
        ) as client:
            results = await asyncio.gather(
                *(self._fetch_one(client, url, since) for url in self.feeds),
                return_exceptions=True,
            )
        docs: list[RawDocument] = []
        for url, res in zip(self.feeds, results):
            if isinstance(res, Exception):
                log.warning("RSS akarı çekilemedi: %s (%s)", url, res)
                continue
            docs.extend(res)
        return docs

    async def _fetch_one(self, client: httpx.AsyncClient, url: str, since: datetime) -> list[RawDocument]:
        resp = await client.get(url)
        resp.raise_for_status()
        return self.parse(resp.content, feed_url=url, since=since)

    def parse(self, raw_xml: bytes | str, *, feed_url: str, since: datetime) -> list[RawDocument]:
        """Ham feed içeriğini RawDocument listesine dönüştürür (ağ gerektirmez — test edilebilir)."""
        parsed = feedparser.parse(raw_xml)
        feed_title = parsed.feed.get("title", feed_url)
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
                    source=f"rss:{feed_title}",
                    source_type=self.source_type,
                    url=entry.get("link"),
                    title=title,
                    body=body,
                    published_at=published,
                    fetched_at=now,
                    content_hash=self.content_hash(title, body),
                    raw_meta={"feed_url": feed_url},
                )
            )
        return out
