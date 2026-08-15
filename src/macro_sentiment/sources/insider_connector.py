"""İçeriden öğrenenlerin işlemleri — SEC Form 4 (EDGAR).

Şirket yöneticileri, yönetim kurulu üyeleri ve %10+ hissedarlar, hisse alım
satımlarını **2 iş günü içinde** SEC'e Form 4 ile bildirmek zorundadır. Bu
bildirimler herkese açık ve ANAHTARSIZDIR — EDGAR full-text/atom akışından
çekilir.

NEDEN DEĞERLİ
-------------
Yöneticinin kendi şirketinde yaptığı ALIM, kamuya açık en dolaysız "içeriden
iyimserlik" sinyalidir: satış birçok sebeple yapılabilir (vergi, çeşitlendirme,
planlı satış programı), ama alım genelde tek bir sebeple yapılır.

Bu yüzden `insider_pressure` asimetriktir: alımlar satışlardan daha ağır tartılır.

CAPITOL TRADES / KONGRE İŞLEMLERİ — BİLEREK KAPSAM DIŞI
--------------------------------------------------------
Orijinal plan ABD Kongre üyelerinin işlemlerini de (Capitol Trades) istiyordu.
Capitol Trades'in **public API'si yoktur**; veri ancak site kazıyarak ya da
House/Senate STOCK Act açıklama akışlarını ayrıştırarak alınabilir — ikisi de
ayrı bir iş kalemidir ve kırılgandır. Bu sürüm Form 4 ile sınırlıdır ve bunu
gizlemez; Kongre verisi ayrı bir connector olarak eklenecektir.

OFFLINE MOD
-----------
`InsiderConnector(offline_fixtures=[...])` ile ağ olmadan çalışır. Testler
ağsızdır ve bu birinci sınıf bir moddur, sonradan eklenmiş bir kaçamak değil.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import httpx

from ..core.models import RawDocument, SourceType
from .base import BaseConnector, SimpleRateLimit, fetch_with_retry

log = logging.getLogger(__name__)

# EDGAR, kimliği belirtilmiş bir User-Agent ister; aksi halde istekleri reddeder.
EDGAR_UA = "macro-sentiment-agent (research; contact via repository)"
EDGAR_ATOM = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcompany&type=4&dateb=&owner=include&count={count}&output=atom"
)

# Alım, satıştan daha güçlü bir sinyaldir (bkz. modül docstring'i).
BUY_WEIGHT, SELL_WEIGHT = 1.0, 0.45

# KÖK eşleme: `purchase\b` "purchased"a uymaz — Form 4 metinlerinde fiiller
# neredeyse her zaman çekimlidir, o yüzden ek serbest bırakılır.
# `acqui\w*` hem "acquired" hem "acquisition" kapsar.
_BUY_PAT = re.compile(r"\b(?:purchas\w*|acqui\w*|bought|buy)\b", re.I)
_SELL_PAT = re.compile(r"\b(?:sold|sale\w*|sell\w*|dispos\w*)\b", re.I)


def classify_transaction(text: str) -> int:
    """Form 4 metninden işlem yönü: +1 alım, -1 satım, 0 belirsiz.

    Kasıtlı olarak muhafazakâr: ikisi de eşleşirse ya da hiçbiri eşleşmezse 0
    döner. Belirsiz bir bildirimi tahmin etmek, sinyali gürültüyle kirletir.
    """
    buy = bool(_BUY_PAT.search(text))
    sell = bool(_SELL_PAT.search(text))
    if buy == sell:
        return 0
    return 1 if buy else -1


def insider_pressure(transactions) -> float:
    """İşlem listesinden [-1, 1] aralığında işaretli baskı skoru.

    `transactions`: [{"direction": int, "value_usd": float}, ...]
    Ağırlıklandırma asimetriktir; yön yoksa (0) hiç sayılmaz.
    """
    num = den = 0.0
    for t in transactions or []:
        d = int(t.get("direction", 0))
        if d == 0:
            continue
        v = abs(float(t.get("value_usd", 0.0) or 0.0)) or 1.0
        w = BUY_WEIGHT if d > 0 else SELL_WEIGHT
        num += d * w * v
        den += w * v
    if den <= 0:
        return 0.0
    return max(-1.0, min(1.0, num / den))


class InsiderConnector(BaseConnector):
    """SEC Form 4 bildirimlerini `RawDocument` olarak yayınlar."""

    source_id = "insider:sec_form4"
    source_type = SourceType.MARKET

    def __init__(self, *, count: int = 40, timeout: float = 15.0,
                 offline_fixtures: list[dict] | None = None) -> None:
        self.count = count
        self.timeout = timeout
        self.offline_fixtures = offline_fixtures

    def rate_limit(self) -> SimpleRateLimit:
        # EDGAR adil kullanım sınırı: saniyede ~10 istek. Fazlasıyla altında kalıyoruz.
        return SimpleRateLimit(max_calls=30, per_seconds=60.0)

    async def fetch(self, since: datetime) -> list[RawDocument]:
        if self.offline_fixtures is not None:
            return [self._to_document(f) for f in self.offline_fixtures]
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, headers={"User-Agent": EDGAR_UA}
            ) as client:
                resp = await fetch_with_retry(
                    client, "GET", EDGAR_ATOM.format(count=self.count)
                )
            return [d for d in self._parse_atom(resp.text) if d.published_at >= since]
        except Exception as exc:
            # Tek bir kaynağın düşmesi tüm ingest turunu düşürmemeli.
            log.warning("SEC Form 4 çekilemedi, bu tur atlanıyor: %s", exc)
            return []

    # ---------- ayrıştırma ----------
    def _parse_atom(self, xml: str) -> list[RawDocument]:
        docs: list[RawDocument] = []
        for entry in re.findall(r"<entry>(.*?)</entry>", xml, re.S):
            title = self._tag(entry, "title") or ""
            summary = self._tag(entry, "summary") or ""
            updated = self._tag(entry, "updated")
            link = re.search(r'<link[^>]*href="([^"]+)"', entry)
            docs.append(self._to_document({
                "title": title,
                "body": summary or title,
                "url": link.group(1) if link else None,
                "published_at": updated,
            }))
        return docs

    @staticmethod
    def _tag(block: str, name: str) -> str | None:
        m = re.search(rf"<{name}[^>]*>(.*?)</{name}>", block, re.S)
        return re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else None

    def _to_document(self, item: dict) -> RawDocument:
        title = (item.get("title") or "").strip()
        body = (item.get("body") or title).strip()
        published = item.get("published_at")
        if isinstance(published, str):
            try:
                published = datetime.fromisoformat(published.replace("Z", "+00:00"))
            except ValueError:
                published = None
        if not isinstance(published, datetime):
            published = datetime.now(timezone.utc)
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)

        direction = classify_transaction(f"{title} {body}")
        return RawDocument(
            id=self.content_hash(title, body),
            source=self.source_id,
            source_type=self.source_type,
            url=item.get("url"),
            title=title or None,
            body=body,
            lang="en",
            published_at=published,
            fetched_at=datetime.now(timezone.utc),
            content_hash=self.content_hash(title, body),
            raw_meta={
                "filing_type": "4",
                "insider_direction": direction,
                "value_usd": item.get("value_usd"),
                # Kongre verisi bu connector'da YOK — bkz. modül docstring'i.
                "covers_congress": False,
            },
        )
