"""Sinyal susturma (cooldown) ve bileşik şiddet yardımcıları.

Aynı (varlık, tip) sinyali cooldown penceresi içinde tekrar yayınlanmaz
(ARCHITECTURE.md §7.1). MVP'de in-memory; üretimde Redis'e taşınır.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..core.models import Signal


class Cooldown:
    def __init__(self, cooldown_seconds: int = 1800) -> None:
        self.cooldown = timedelta(seconds=cooldown_seconds)
        self._last: dict[tuple[str, str], datetime] = {}

    def should_emit(self, signal: Signal) -> bool:
        key = (signal.entity, signal.type.value)
        now = datetime.now(timezone.utc)
        last = self._last.get(key)
        if last is not None and now - last < self.cooldown:
            return False
        self._last[key] = now
        return True
