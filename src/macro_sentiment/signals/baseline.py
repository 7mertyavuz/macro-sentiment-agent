"""Taban çizgisi ve z-skor — tarihsel normalden sapmayı ölçer.

Sinyal mutlak değerden değil, anomaliden doğar (ARCHITECTURE.md §7.1).
MVP'de baseline, geçmiş pencere sayımlarından (hacim) hesaplanır.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass


@dataclass
class Baseline:
    """Bir metrik için tarihsel (ortalama, std) ve örnek sayısı."""

    mean: float = 0.0
    std: float = 0.0
    n: int = 0


def zscore(value: float, baseline: Baseline) -> float:
    """Değerin taban çizgisinden kaç std uzakta olduğunu döndürür (std=0 → 0)."""
    if baseline.std <= 0:
        return 0.0
    return (value - baseline.mean) / baseline.std


def compute_baseline(series: list[float]) -> Baseline:
    """Sayısal seriden (ortalama, std) taban çizgisi üretir."""
    if len(series) < 2:
        return Baseline(mean=(series[0] if series else 0.0), std=0.0, n=len(series))
    return Baseline(mean=statistics.fmean(series), std=statistics.pstdev(series), n=len(series))
