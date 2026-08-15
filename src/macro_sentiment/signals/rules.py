"""Sinyal kuralları / anomali dedektörleri (ARCHITECTURE.md §7.2).

Her kural bir WindowAggregate (+ opsiyonel hacim z-skoru) alır ve eşik/anomali
sağlanırsa Signal üretir. Eşikler MVP varsayılanıdır; backtest ile kalibre edilir.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from ..core.models import Signal, SignalType
from .aggregator import WindowAggregate


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


class PanicRule:
    """Negatif polarite + yüksek korku → panik/korku sinyali.

    Hacim z-skoru yüksekse (haber patlaması) şiddet artar.
    """

    def __init__(self, pol_threshold: float = -0.35, fear_threshold: float = 0.5, min_volume: int = 1) -> None:
        self.pol_threshold = pol_threshold
        self.fear_threshold = fear_threshold
        self.min_volume = min_volume

    def evaluate(self, agg: WindowAggregate, volume_z: float = 0.0) -> Signal | None:
        if agg.volume < self.min_volume:
            return None
        if agg.mean_polarity > self.pol_threshold or agg.mean_fear < self.fear_threshold:
            return None
        severity = _clamp(60 * abs(agg.mean_polarity) + 30 * agg.mean_fear + 10 * min(1.0, max(0.0, volume_z) / 3))
        return Signal(
            id=_new_id(), entity=agg.entity, type=SignalType.PANIC,
            severity=round(severity, 1), direction=agg.mean_polarity, window=agg.window,
            headline=f"{agg.entity} — aşırı korku: negatif haber baskın, panik satışı riski",
            payload={"mean_polarity": agg.mean_polarity, "mean_fear": agg.mean_fear,
                     "volume": agg.volume, "volume_z": round(volume_z, 2)},
            created_at=datetime.now(timezone.utc),
        )


class EuphoriaRule:
    """Aşırı pozitif polarite + yüksek açgözlülük → coşku/tepe sinyali."""

    def __init__(self, pol_threshold: float = 0.45, greed_threshold: float = 0.45, min_volume: int = 1) -> None:
        self.pol_threshold = pol_threshold
        self.greed_threshold = greed_threshold
        self.min_volume = min_volume

    def evaluate(self, agg: WindowAggregate, volume_z: float = 0.0) -> Signal | None:
        if agg.volume < self.min_volume:
            return None
        if agg.mean_polarity < self.pol_threshold or agg.mean_greed < self.greed_threshold:
            return None
        severity = _clamp(60 * agg.mean_polarity + 30 * agg.mean_greed + 10 * min(1.0, max(0.0, volume_z) / 3))
        return Signal(
            id=_new_id(), entity=agg.entity, type=SignalType.EUPHORIA,
            severity=round(severity, 1), direction=agg.mean_polarity, window=agg.window,
            headline=f"{agg.entity} — coşku (euphoria): olası tepe/geri çekilme",
            payload={"mean_polarity": agg.mean_polarity, "mean_greed": agg.mean_greed, "volume": agg.volume},
            created_at=datetime.now(timezone.utc),
        )


class FedToneRule:
    """FED varlığında ton kayması → hawkish (negatif) / dovish (pozitif) sinyali."""

    def __init__(self, threshold: float = 0.25, min_volume: int = 1) -> None:
        self.threshold = threshold
        self.min_volume = min_volume

    def evaluate(self, agg: WindowAggregate, volume_z: float = 0.0) -> Signal | None:
        if agg.entity != "FED" or agg.volume < self.min_volume:
            return None
        if abs(agg.mean_polarity) < self.threshold:
            return None
        tone = "hawkish (şahin)" if agg.mean_polarity < 0 else "dovish (güvercin)"
        severity = _clamp(50 + 50 * abs(agg.mean_polarity))
        return Signal(
            id=_new_id(), entity=agg.entity, type=SignalType.FED_TONE,
            severity=round(severity, 1), direction=agg.mean_polarity, window=agg.window,
            headline=f"FED — ton kayması: {tone} sinyali güçleniyor",
            payload={"mean_polarity": agg.mean_polarity, "tone": tone, "volume": agg.volume},
            created_at=datetime.now(timezone.utc),
        )


class NarrativeRule:
    """Anlatı değişimi: kaynaklar birbirine ters düştüğünde + belirsizlik yüksekken.

    `SignalType.NARRATIVE` README ve ARCHITECTURE.md'de aylardır reklam
    ediliyordu ve `_SIGNAL_KIND_MAP` onu `narrative_shift` şokuna eşliyordu,
    ama üreten KURAL YOKTU — yani bu şok türü hiç doğmuyordu.

    Tespit mantığı: bir anlatının değiştiği an, piyasanın hikâyeyi henüz tek
    şekilde okumadığı andır. Bu iki gözlemde görünür:
      1. `source_breakdown` içinde kaynaklar arası polarite AYRIŞMASI
         (haber olumlu derken sosyal olumsuz, ya da tersi),
      2. yüksek `mean_uncertainty`.
    Tek başına güçlü ve tek yönlü bir polarite anlatı değişimi değil, mevcut
    anlatının teyididir — o zaten Panic/Euphoria kurallarının işi.
    """

    def __init__(self, spread_threshold: float = 0.5, uncertainty_threshold: float = 0.35,
                 min_volume: int = 2, min_sources: int = 2) -> None:
        self.spread_threshold = spread_threshold
        self.uncertainty_threshold = uncertainty_threshold
        self.min_volume = min_volume
        self.min_sources = min_sources

    def evaluate(self, agg: WindowAggregate, volume_z: float = 0.0) -> Signal | None:
        breakdown = agg.source_breakdown or {}
        if agg.volume < self.min_volume or len(breakdown) < self.min_sources:
            return None

        values = [float(v) for v in breakdown.values()]
        spread = max(values) - min(values)
        if spread < self.spread_threshold:
            return None
        if agg.mean_uncertainty < self.uncertainty_threshold:
            return None

        # Yön, en yüksek hacimli değil en UÇ kaynaktan alınır: anlatıyı çeken
        # taraf odur. Şiddet ayrışma + belirsizlikle ölçeklenir.
        pull = max(values, key=abs)
        severity = _clamp(40 * min(1.0, spread) + 40 * agg.mean_uncertainty
                          + 20 * min(1.0, max(0.0, volume_z) / 3))
        return Signal(
            id=_new_id(), entity=agg.entity, type=SignalType.NARRATIVE,
            severity=round(severity, 1), direction=round(pull, 4), window=agg.window,
            headline=f"{agg.entity} — anlatı değişimi: kaynaklar ayrışıyor, hikâye yeniden yazılıyor",
            payload={"source_spread": round(spread, 4), "sources": breakdown,
                     "mean_uncertainty": agg.mean_uncertainty, "volume": agg.volume,
                     "volume_z": round(volume_z, 2)},
            created_at=datetime.now(timezone.utc),
        )


class BreakoutRule:
    """Olağandışı aktivite: hacim kendi taban çizgisinden belirgin sapmış.

    `SignalType.BREAKOUT` da reklam edilip üretilmiyordu. Diğer kurallardan
    farkı YÖN NÖTR olmasıdır: "bir şey oluyor" der, "yukarı/aşağı" demez.
    Bu yüzden `sentiment_feed` onu bilerek şok olarak enjekte ETMEZ — yönsüz
    bir şok, simülasyona sahte bir sürüklenme eklemekten başka işe yaramaz.
    """

    def __init__(self, z_threshold: float = 2.5, min_volume: int = 3) -> None:
        self.z_threshold = z_threshold
        self.min_volume = min_volume

    def evaluate(self, agg: WindowAggregate, volume_z: float = 0.0) -> Signal | None:
        if agg.volume < self.min_volume or volume_z < self.z_threshold:
            return None
        severity = _clamp(40 + 20 * min(3.0, volume_z))
        return Signal(
            id=_new_id(), entity=agg.entity, type=SignalType.BREAKOUT,
            severity=round(severity, 1),
            # Yön nötr: hacim patlaması bir yön iddiası taşımaz.
            direction=0.0, window=agg.window,
            headline=f"{agg.entity} — olağandışı aktivite: haber akışı tabanın {volume_z:.1f}σ üstünde",
            payload={"volume": agg.volume, "volume_z": round(volume_z, 2),
                     "mean_polarity": agg.mean_polarity},
            created_at=datetime.now(timezone.utc),
        )


DEFAULT_RULES = [PanicRule(), EuphoriaRule(), FedToneRule(), NarrativeRule(), BreakoutRule()]
