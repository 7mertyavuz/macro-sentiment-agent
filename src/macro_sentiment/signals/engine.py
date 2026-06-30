"""Sinyal motoru orkestrasyonu (ARCHITECTURE.md §7-8).

Akış: skorları yükle → pencere topla → baseline (hacim z-skoru) → kuralları
çalıştır → cooldown filtresi → DB'ye yaz → (opsiyonel) uyarı dağıt.
"""
from __future__ import annotations

import logging

from ..storage.repositories import SentimentRepository, SignalRepository
from .aggregator import aggregate
from .baseline import Baseline, zscore
from .rules import DEFAULT_RULES
from .scorer import Cooldown

log = logging.getLogger(__name__)


class SignalEngine:
    def __init__(
        self,
        sent_repo: SentimentRepository | None = None,
        sig_repo: SignalRepository | None = None,
        rules=None,
        cooldown: Cooldown | None = None,
        dispatcher=None,
        window_size: int = 50,
    ) -> None:
        self.sent_repo = sent_repo or SentimentRepository()
        self.sig_repo = sig_repo or SignalRepository()
        self.rules = rules if rules is not None else DEFAULT_RULES
        self.cooldown = cooldown or Cooldown()
        self.dispatcher = dispatcher
        self.window_size = window_size

    async def evaluate_entity(self, entity: str, volume_baseline: Baseline | None = None) -> list:
        scores = await self.sent_repo.recent_for_entity(entity, limit=self.window_size)
        if not scores:
            return []
        agg = aggregate(entity, scores, window="recent")
        vol_z = zscore(float(agg.volume), volume_baseline) if volume_baseline else 0.0

        emitted = []
        for rule in self.rules:
            sig = rule.evaluate(agg, vol_z)
            if sig and self.cooldown.should_emit(sig):
                await self.sig_repo.save(sig)
                if self.dispatcher is not None:
                    await self.dispatcher.dispatch(sig)
                emitted.append(sig)
                log.info("Sinyal: %s", sig.headline)
        return emitted

    async def evaluate_entities(self, entities: list[str]) -> list:
        out = []
        for e in entities:
            out.extend(await self.evaluate_entity(e))
        return out
