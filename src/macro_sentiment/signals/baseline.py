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


def update_baseline(baseline: Baseline, value: float) -> Baseline:
    """Welford'un çevrimiçi algoritmasıyla tek değer ekleyerek taban çizgisini günceller (Faz 10).

    Tüm seriyi saklamadan kalıcı (mean, std, n) durumunu tutmayı sağlar —
    ``storage/repositories.py::BaselineRepository`` bu değeri DB'de saklar.
    ``compute_baseline`` ile aynı ``pstdev`` (popülasyon std) tanımıyla uyumludur.
    """
    n = baseline.n + 1
    if n == 1:
        return Baseline(mean=value, std=0.0, n=1)
    delta = value - baseline.mean
    new_mean = baseline.mean + delta / n
    m2 = (baseline.std**2) * baseline.n  # önceki toplam kare sapma
    delta2 = value - new_mean
    m2 += delta * delta2
    new_std = (m2 / n) ** 0.5
    return Baseline(mean=new_mean, std=new_std, n=n)
