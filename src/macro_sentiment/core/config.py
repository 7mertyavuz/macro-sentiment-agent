"""Ortam tabanlı uygulama ayarları (.env üzerinden)."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_RSS_FEEDS: list[str] = [
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=AAPL&region=US&lang=en-US",
    "https://www.investing.com/rss/news_25.rss",
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"

    database_url: str = "sqlite+aiosqlite:///./macro_sentiment.db"

    queue_backend: str = "memory"   # "memory" | "redis"
    redis_url: str = "redis://localhost:6379/0"

    rss_feeds: list[str] = DEFAULT_RSS_FEEDS
    newsapi_key: str | None = None
    twitter_bearer_token: str | None = None
    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    fred_api_key: str | None = None

    finbert_model: str = "ProsusAI/finbert"
    use_finbert: bool = True
    nlp_mode: str = "finbert"   # "finbert" | "llm" | "hybrid"

    llm_provider: str = "anthropic"
    llm_api_key: str | None = None
    llm_model: str = "claude-sonnet-4-6"

    # Uyarı kanalları (Faz 3) — boşsa kanal devre dışı
    alert_min_severity: float = 60.0
    alert_webhook_url: str | None = None
    slack_webhook_url: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    poll_interval_news: int = 60
    poll_interval_social: int = 30


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
