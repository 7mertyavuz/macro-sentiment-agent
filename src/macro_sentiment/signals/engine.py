"""Sinyal motoru orkestrasyonu (ARCHITECTURE.md §7-8).

Akış: skorları yükle → pencere topla → baseline (hacim z-skoru) → kuralları
çalıştır → cooldown filtresi → DB'ye yaz → (opsiyonel) uyarı dağıt.

Faz 10: hacim taban çizgisi artık bellek içi olmak zorunda değil —
``BaselineRepository`` ile kalıcıdır (yeniden başlatmada korunur). Geriye
uyum: ``volume_baseline`` açıkça verilirse (eski çağrı biçimi) DB'ye hiç
dokunulmaz — eski testler/çağıranlar aynen çalışmaya devam eder. Verilmezse
motor taban çizgisini otomatik yükler, z-skor için kullanır ve mevcut hacimle
günceller (Welford, tek geçiş — tüm geçmiş seriyi saklamaz).
"""
from __future__ import annotations

import logging

from ..storage.repositories import BaselineRepository, SentimentRepository, SignalRepository
from .aggregator import aggregate
from .baseline import Baseline, zscore
from .review import PENDING, needs_review
from .rules import DEFAULT_RULES
from .scorer import Cooldown

log = logging.getLogger(__name__)

VOLUME_METRIC = "volume"


class SignalEngine:
    def __init__(
        self,
        sent_repo: SentimentRepository | None = None,
        sig_repo: SignalRepository | None = None,
        rules=None,
        cooldown: Cooldown | None = None,
        dispatcher=None,
        window_size: int = 50,
        baseline_repo: BaselineRepository | None = None,
    ) -> None:
        self.sent_repo = sent_repo or SentimentRepository()
        self.sig_repo = sig_repo or SignalRepository()
        self.rules = rules if rules is not None else DEFAULT_RULES
        self.cooldown = cooldown or Cooldown()
        self.dispatcher = dispatcher
        self.window_size = window_size
        self.baseline_repo = baseline_repo or BaselineRepository()

    async def evaluate_entity(self, entity: str, volume_baseline: Baseline | None = None) -> list:
        scores = await self.sent_repo.recent_for_entity(entity, limit=self.window_size)
        if not scores:
            return []
        agg = aggregate(entity, scores, window="recent")

        persist_baseline = volume_baseline is None
        if persist_baseline:
            volume_baseline = await self.baseline_repo.get(entity, VOLUME_METRIC)
        vol_z = zscore(float(agg.volume), volume_baseline) if volume_baseline else 0.0

        emitted = []
        for rule in self.rules:
            sig = rule.evaluate(agg, vol_z)
            if sig and self.cooldown.should_emit(sig):
                if needs_review(sig):
                    # Faz 11: yüksek-etki sinyal — DB'de görünür ama dağıtılmaz.
                    # İnsan onayı (api/routes.py::/v1/review/{id}/approve) sonrası
                    # ayrıca dağıtılabilir; motor kendisi otomatik dağıtmaz.
                    sig = sig.model_copy(update={"review_status": PENDING})
                    await self.sig_repo.save(sig)
                else:
                    await self.sig_repo.save(sig)
                    if self.dispatcher is not None:
                        await self.dispatcher.dispatch(sig)
                emitted.append(sig)
                log.info("Sinyal: %s (review_status=%s)", sig.headline, sig.review_status)

        if persist_baseline:
            await self.baseline_repo.update(entity, VOLUME_METRIC, float(agg.volume))
        return emitted

    async def evaluate_entities(self, entities: list[str]) -> list:
        out = []
        for e in entities:
            out.extend(await self.evaluate_entity(e))
        return out
