"""Varlık çıkarımı (NER-lite, MVP).

cashtag ($AAPL) + ad→ticker sözlüğü; hiçbiri yoksa "MARKET".
Faz 2'de spaCy NER + fuzzy matching.
"""
from __future__ import annotations

import re

from ..core.models import AssetClass, Entity, RawDocument

_CASHTAG_RE = re.compile(r"\$([A-Z]{1,5})\b")

_NAME_TO_TICKER: dict[str, str] = {
    "apple": "AAPL", "microsoft": "MSFT", "nvidia": "NVDA", "tesla": "TSLA",
    "amazon": "AMZN", "bitcoin": "BTC", "ethereum": "ETH",
    "federal reserve": "FED", "fed": "FED",
}
_CRYPTO = {"BTC", "ETH"}


def _asset_class(ticker: str) -> AssetClass:
    if ticker in _CRYPTO:
        return AssetClass.CRYPTO
    if ticker == "FED":
        return AssetClass.MACRO
    if ticker == "MARKET":
        return AssetClass.INDEX
    return AssetClass.EQUITY


class FinancialEntityExtractor:
    async def extract(self, doc: RawDocument) -> list[Entity]:
        text = f"{doc.title or ''} {doc.body}"
        tickers: set[str] = set(_CASHTAG_RE.findall(text))
        lower = text.lower()
        for name, ticker in _NAME_TO_TICKER.items():
            if name in lower:
                tickers.add(ticker)
        if not tickers:
            tickers.add("MARKET")
        return [Entity(id=t, name=t, ticker=t, asset_class=_asset_class(t)) for t in sorted(tickers)]
