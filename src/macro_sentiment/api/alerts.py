"""Uyarı kanalları ve dağıtıcı (ARCHITECTURE.md §8).

Her kanal core.contracts.AlertChannel uygular (async send(signal)).
AlertDispatcher şiddet eşiğine göre filtreler ve kanallara fan-out yapar;
bir kanalın hatası diğerlerini etkilemez.
"""
from __future__ import annotations

import logging

import httpx

from ..core.config import Settings
from ..core.models import Signal

log = logging.getLogger(__name__)


def format_signal(signal: Signal) -> str:
    arrow = "🔻" if signal.direction < 0 else "🔺"
    return (
        f"{arrow} [{signal.type.value.upper()}] {signal.headline}\n"
        f"şiddet={signal.severity:.0f} | yön={signal.direction:+.2f} | {signal.window}"
    )


class ConsoleAlert:
    """Her zaman çalışan varsayılan kanal (stdout)."""

    async def send(self, signal: Signal) -> None:
        print(f"[ALERT] {format_signal(signal)}")


class WebhookAlert:
    def __init__(self, url: str, timeout: float = 5.0) -> None:
        self.url = url
        self.timeout = timeout

    async def send(self, signal: Signal) -> None:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            await client.post(self.url, json=signal.model_dump(mode="json"))


class SlackAlert:
    def __init__(self, webhook_url: str, timeout: float = 5.0) -> None:
        self.webhook_url = webhook_url
        self.timeout = timeout

    async def send(self, signal: Signal) -> None:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            await client.post(self.webhook_url, json={"text": format_signal(signal)})


class TelegramAlert:
    def __init__(self, bot_token: str, chat_id: str, timeout: float = 5.0) -> None:
        self.url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self.chat_id = chat_id
        self.timeout = timeout

    async def send(self, signal: Signal) -> None:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            await client.post(self.url, json={"chat_id": self.chat_id, "text": format_signal(signal)})


class AlertDispatcher:
    def __init__(self, channels: list, min_severity: float = 0.0) -> None:
        self.channels = channels
        self.min_severity = min_severity

    async def dispatch(self, signal: Signal) -> int:
        """Sinyali eşiği geçen kanallara gönderir; gönderilen kanal sayısını döndürür."""
        if signal.severity < self.min_severity:
            return 0
        sent = 0
        for ch in self.channels:
            try:
                await ch.send(signal)
                sent += 1
            except Exception:
                log.exception("Uyarı kanalı başarısız: %s", type(ch).__name__)
        return sent


def build_dispatcher(settings: Settings) -> AlertDispatcher:
    """Config'e göre kanal listesini kurar (Console her zaman dahil)."""
    channels: list = [ConsoleAlert()]
    if settings.alert_webhook_url:
        channels.append(WebhookAlert(settings.alert_webhook_url))
    if settings.slack_webhook_url:
        channels.append(SlackAlert(settings.slack_webhook_url))
    if settings.telegram_bot_token and settings.telegram_chat_id:
        channels.append(TelegramAlert(settings.telegram_bot_token, settings.telegram_chat_id))
    return AlertDispatcher(channels, min_severity=settings.alert_min_severity)
