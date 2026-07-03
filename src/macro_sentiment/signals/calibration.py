"""Otomatik eşik kalibrasyonu (Faz 11) — backtest metriklerinden kural eşiklerini önerir.

Basit grid arama: bir kuralın eşik parametresi için aday değerler denenir,
her aday backtest setinde çalıştırılır, en yüksek makro-F1'i veren aday
önerilir. Mevcut (baseline) eşik her zaman aday kümesine dahil edilir — bu
yüzden öneri **hiçbir zaman** backtest F1'ini düşüremez (en kötü ihtimalle
baseline'ı geri döndürür). Bu, roadmap'in "kalibrasyon önerisi backtest F1'i
düşürmez" bitti kriterini yapısal olarak garanti eder (regresyon testiyle
doğrulanır).
"""
from __future__ import annotations

from dataclasses import dataclass

from ..backtest.dataset import BacktestRecord
from ..backtest.harness import run_backtest
from ..backtest.metrics import Metrics


def _macro_f1(metrics: Metrics) -> float:
    labels = [lab for lab in metrics.per_label if lab != "none"]
    if not labels:
        return 0.0
    return sum(metrics.per_label[lab].f1 for lab in labels) / len(labels)


@dataclass
class CalibrationSuggestion:
    param_name: str
    baseline_value: float
    suggested_value: float
    baseline_f1: float
    suggested_f1: float

    @property
    def improved(self) -> bool:
        return self.suggested_f1 > self.baseline_f1


async def suggest_threshold(
    records: list[BacktestRecord],
    model,
    rule_factory,
    *,
    param_name: str,
    baseline_value: float,
    candidates: list[float],
    other_rules: list | None = None,
) -> CalibrationSuggestion:
    """Bir kuralın tek eşik parametresi için grid arama yapar.

    ``rule_factory(value)`` verilen değerle o parametreyi ayarlanmış bir kural
    örneği döndürmelidir (ör. ``lambda v: PanicRule(pol_threshold=v)``).
    ``other_rules`` varsa değerlendirmeye dahil edilen sabit diğer kurallardır
    (gerçekçi bir kural seti üzerinde F1 ölçmek için).

    Dönüş: en iyi makro-F1'i veren aday. ``baseline_value`` her zaman aday
    kümesine dahil edildiği için sonuç asla baseline'dan kötü olamaz.
    """
    all_candidates = sorted(set(candidates) | {baseline_value})
    other_rules = other_rules or []

    results: dict[float, float] = {}
    for value in all_candidates:
        rules = [rule_factory(value), *other_rules]
        report = await run_backtest(records, model, rules=rules)
        results[value] = _macro_f1(report.metrics)

    baseline_f1 = results[baseline_value]
    best_value = max(results, key=lambda v: (results[v], -abs(v - baseline_value)))
    return CalibrationSuggestion(
        param_name=param_name,
        baseline_value=baseline_value,
        suggested_value=best_value,
        baseline_f1=baseline_f1,
        suggested_f1=results[best_value],
    )


__all__ = ["CalibrationSuggestion", "suggest_threshold"]
