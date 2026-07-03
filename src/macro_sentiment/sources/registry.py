"""Connector kayıt defteri — source_id ile connector çözümleme."""
from __future__ import annotations

from .base import BaseConnector
from .fed_connector import FedConnector
from .newsapi_connector import NewsAPIConnector
from .rss_connector import RSSConnector
from .social_connector import SocialConnector

# source_id -> connector sınıfı
REGISTRY: dict[str, type[BaseConnector]] = {
    RSSConnector.source_id: RSSConnector,
    NewsAPIConnector.source_id: NewsAPIConnector,
    FedConnector.source_id: FedConnector,
    SocialConnector.source_id: SocialConnector,
}


def get_connector(source_id: str) -> type[BaseConnector]:
    """source_id için connector sınıfını döndürür."""
    if source_id not in REGISTRY:
        raise KeyError(f"Bilinmeyen kaynak: {source_id}. Mevcut: {list(REGISTRY)}")
    return REGISTRY[source_id]


def active_connectors(settings) -> list[BaseConnector]:
    """Ayarlara göre etkin connector örneklerini oluşturur (Faz 8-9).

    RSS her zaman etkindir (anahtarsız). NewsAPI/Fed yalnızca ilgili anahtar
    ayarlandıysa listeye eklenir; anahtar yoksa sessizce atlanır — sistem
    offline gibi çalışmaya devam eder. StockTwits anahtarsız/herkese açıktır
    ama gürültülü/riskli bir kaynak olduğu için açık onay (``stocktwits_enabled``)
    gerektirir — varsayılan kapalı. Twitter/Reddit resmi anahtar gerektirir;
    henüz uygulanmadıkları için (bkz. ``social_connector.py`` TODO) burada
    eklenmezler.
    """
    connectors: list[BaseConnector] = [RSSConnector(feeds=settings.rss_feeds)]
    if settings.newsapi_key:
        connectors.append(NewsAPIConnector(settings.newsapi_key))
    if settings.fred_api_key:
        connectors.append(FedConnector(settings.fred_api_key))
    if getattr(settings, "stocktwits_enabled", False):
        connectors.append(SocialConnector(platform="stocktwits", symbols=settings.social_symbols))
    return connectors
