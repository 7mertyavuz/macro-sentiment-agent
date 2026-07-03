"""Sosyal medya connector — X (Twitter) / Reddit / StockTwits (Faz 9).

Sosyal akışta bot/spam temizliği ve sarkazm yönetimi kritiktir
(ARCHITECTURE.md §4.3, §6.3).

StockTwits'in sembol akışı (``/api/2/streams/symbol/{symbol}.json``) herkese
açıktır ve anahtar gerektirmez — Fed RSS'e benzer şekilde ilk gerçek canlı
sosyal kaynak burada. Twitter/Reddit resmi API'leri OAuth/anahtar gerektirir;
bu fazda anahtarsızken (varsayılan) ağa hiç çıkmadan boş liste döner —
sistem offline gibi çalışmaya devam eder. Gerçek Twitter/Reddit entegrasyonu
kapsam dışı bırakıldı (TODO, ayrı bir faz/PR).

Bot/spam filtresi ``nlp/spam_filter.py::filter_spam`` ile ``fetch()`` içinde
otomatik uygulanır — sert botlar/kopya metinler düşürülür, şüpheliler
``raw_meta["spam_suspicious"]`` ile işaretlenir.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from ..core.models import RawDocument, SourceType
from ..ingestion.normalizer import strip_social_noise
from ..nlp.spam_filter import filter_spam
from .base import BaseConnector, SimpleRateLimit, fetch_with_retry

log = logging.getLogger(__name__)

_STOCKTWITS_URL = "https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"
_DEFAULT_SYMBOLS = ["AAPL", "MSFT", "TSLA", "BTC.X", "SPY"]


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _account_age_days(join_date: str | None, now: datetime) -> float | None:
    joined = _parse_dt(join_date)
    if joined is None:
        return None
    return max((now - joined).total_seconds() / 86400.0, 0.0)


class SocialConnector(BaseConnector):
    source_id = "social"
    source_type = SourceType.SOCIAL

    def __init__(
        self,
        platform: str = "stocktwits",
        credentials: dict | None = None,
        *,
        symbols: list[str] | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.platform = platform           # "stocktwits" | "twitter" | "reddit"
        self.credentials = credentials or {}
        self.symbols = symbols or _DEFAULT_SYMBOLS
        self.timeout = timeout

    def rate_limit(self) -> SimpleRateLimit:
        # Sosyal akış en gürültülü/riskli kaynak — agresif tavan (roadmap Faz 9).
        return SimpleRateLimit(max_calls=200, per_seconds=3600.0)

    async def fetch(self, since: datetime) -> list[RawDocument]:
        if self.platform == "stocktwits":
            docs = await self._fetch_stocktwits(since)
        elif self.platform in ("twitter", "reddit"):
            if not self.credentials:
                log.info(
                    "%s için kimlik bilgisi yok; SocialConnector.fetch() ağa çıkmadan atlanıyor.",
                    self.platform,
                )
                return []
            # TODO: gerçek Twitter/Reddit OAuth entegrasyonu (ayrı faz).
            log.info("%s connector'ı henüz uygulanmadı; boş liste dönüyor.", self.platform)
            return []
        else:
            log.warning("Bilinmeyen sosyal platform: %s", self.platform)
            return []
        return filter_spam(docs)

    async def _fetch_stocktwits(self, since: datetime) -> list[RawDocument]:
        out: list[RawDocument] = []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for symbol in self.symbols:
                url = _STOCKTWITS_URL.format(symbol=symbol)
                try:
                    resp = await fetch_with_retry(client, "GET", url)
                except Exception:
                    log.warning("StockTwits isteği başarısız (%s); bu sembol atlanıyor", symbol)
                    continue
                out.extend(self.parse(resp.json(), since=since))
        return out

    def parse(self, payload: dict, *, since: datetime) -> list[RawDocument]:
        """StockTwits JSON gövdesini RawDocument listesine çevirir (ağ gerektirmez — test edilebilir)."""
        now = datetime.now(timezone.utc)
        out: list[RawDocument] = []
        for msg in payload.get("messages", []):
            body_raw = msg.get("body") or ""
            body = strip_social_noise(body_raw)
            if not body:
                continue
            created = _parse_dt(msg.get("created_at")) or now
            if created <= since:
                continue
            user = msg.get("user") or {}
            msg_id = str(msg.get("id") or self.content_hash(None, body_raw))
            raw_meta = {
                "author_username": user.get("username"),
                "author_account_age_days": _account_age_days(user.get("join_date"), now),
                "author_followers": user.get("followers"),
            }
            out.append(
                RawDocument(
                    id=f"stocktwits:{msg_id}",
                    source="social:stocktwits",
                    source_type=self.source_type,
                    url=f"https://stocktwits.com/message/{msg_id}",
                    title=None,
                    body=body,
                    published_at=created,
                    fetched_at=now,
                    content_hash=self.content_hash(None, body_raw),
                    raw_meta=raw_meta,
                )
            )
        return out


__all__ = ["SocialConnector"]
