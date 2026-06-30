"""Sınıflandırma metrikleri — etiket bazında precision/recall/F1 + genel accuracy."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LabelMetrics:
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    support: int = 0


@dataclass
class Metrics:
    accuracy: float
    per_label: dict[str, LabelMetrics] = field(default_factory=dict)
    n: int = 0


def _f1(p: float, r: float) -> float:
    return 0.0 if (p + r) == 0 else 2 * p * r / (p + r)


def compute_metrics(pairs: list[tuple[str, str]]) -> Metrics:
    """pairs: (predicted, expected) listesi. Tüm etiketler için metrik döndürür."""
    labels = sorted({lab for pair in pairs for lab in pair})
    correct = sum(1 for pred, exp in pairs if pred == exp)
    per: dict[str, LabelMetrics] = {}
    for lab in labels:
        tp = sum(1 for pred, exp in pairs if pred == lab and exp == lab)
        fp = sum(1 for pred, exp in pairs if pred == lab and exp != lab)
        fn = sum(1 for pred, exp in pairs if pred != lab and exp == lab)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        per[lab] = LabelMetrics(
            precision=round(precision, 4), recall=round(recall, 4),
            f1=round(_f1(precision, recall), 4), support=tp + fn,
        )
    n = len(pairs)
    return Metrics(accuracy=round(correct / n, 4) if n else 0.0, per_label=per, n=n)
