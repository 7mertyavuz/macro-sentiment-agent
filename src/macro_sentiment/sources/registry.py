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
