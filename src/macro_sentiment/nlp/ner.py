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
    "amazon": "AMZN",
    # Kripto. Sözlükte yalnızca bitcoin ve ethereum vardı; Heimdall'ın hasadı
    # SOL'u da izliyor ve "Solana" geçen HER belge MARKET'e düşüyordu — yani
    # SOL için duyu, haber gelse bile hiçbir zaman doğmuyordu. Takma adlar da
    # burada: metinlerde tam ad kadar sık geçiyorlar.
    "bitcoin": "BTC", "btc": "BTC",
    "ethereum": "ETH", "ether": "ETH", "eth": "ETH",
    "solana": "SOL", "sol": "SOL",
    "ripple": "XRP", "xrp": "XRP",
    "cardano": "ADA", "dogecoin": "DOGE", "binance coin": "BNB",
    # FED terimleri AÇIKÇA yazılıyor. Önceki alt-dize eşleşmesi "fed"i
    # "**Fed**eral Open Market Committee" içinde yakalıyordu — yani FOMC
    # belgeleri doğru varlığa, YANLIŞ sebeple bağlanıyordu. Sözcük sınırına
    # geçince o kaza bozuldu ve bir test bunu anında ortaya çıkardı; doğru
    # çözüm sınırı gevşetmek değil, terimleri gerçekten yazmak.
    "federal reserve": "FED", "fed": "FED", "fomc": "FED",
    "federal open market committee": "FED", "central bank": "FED",
    "powell": "FED", "rate decision": "FED",
}
_CRYPTO = {"BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "BNB"}


def _asset_class(ticker: str) -> AssetClass:
    if ticker in _CRYPTO:
        return AssetClass.CRYPTO
    if ticker == "FED":
        return AssetClass.MACRO
    if ticker == "MARKET":
        return AssetClass.INDEX
    return AssetClass.EQUITY


# SÖZCÜK SINIRI ŞART. Alt-dize eşleşmesi kısa takma adlarla bir yanlış-pozitif
# makinesine dönüşür: "sol" → console/solid/sold/resolution, "eth" → whether/
# method/together, "ada" → Canada. Bu, olmayan bir varlığa duyu üretir ve
# üretilen skor gerçek görünür — sessiz gürültünün en kötü türü.
_NAME_RE = re.compile(
    r"\b(" + "|".join(sorted((re.escape(n) for n in _NAME_TO_TICKER), key=len, reverse=True)) + r")\b"
)


class FinancialEntityExtractor:
    async def extract(self, doc: RawDocument) -> list[Entity]:
        text = f"{doc.title or ''} {doc.body}"
        tickers: set[str] = set(_CASHTAG_RE.findall(text))
        for name in _NAME_RE.findall(text.lower()):
            tickers.add(_NAME_TO_TICKER[name])
        if not tickers:
            tickers.add("MARKET")
        return [Entity(id=t, name=t, ticker=t, asset_class=_asset_class(t)) for t in sorted(tickers)]
