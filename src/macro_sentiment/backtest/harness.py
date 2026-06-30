"""Backtest harness — etiketli kayıtları NLP + sinyal kurallarından geçirir.

Her kayıt için tek-belge penceresi oluşturup kuralları çalıştırır, en yüksek
şiddetli sinyal tipini 'tahmin' kabul eder (sinyal yoksa 'none') ve beklenenle
karşılaştırır. DB gerektirmez — tamamen bellek içi, deterministik.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..core.models import RawDocument
from ..nlp.ner import FinancialEntityExtractor
from ..signals.aggregator import aggregate
from ..signals.rules import DEFAULT_RULES
from .dataset import BacktestRecord
from .metrics import Metrics, compute_metrics


@dataclass
class BacktestReport:
    metrics: Metrics
    pairs: list[tuple[str, str]] = field(default_factory=list)   # (predicted, expected)
    details: list[dict] = field(default_factory=list)


def _record_to_doc(rec: BacktestRecord) -> RawDocument:
    now = datetime.now(timezone.utc)
    return RawDocument(
        id=rec.id, source="backtest", source_type=rec.source_type,
        title=rec.title, body=rec.body, published_at=now, fetched_at=now,
        content_hash=rec.id,
    )


async def _predict(rec: BacktestRecord, model, extractor, rules) -> str:
    doc = _record_to_doc(rec)
    entities = await extractor.extract(doc)
    scores = await model.score(doc, entities)
    if rec.entity:  # değerlendirmeyi tek varlığa sabitle
        scores = [s for s in scores if s.entity == rec.entity] or scores

    best_label, best_sev = "none", -1.0
    by_entity: dict[str, list] = {}
    for s in scores:
        by_entity.setdefault(s.entity, []).append(s)
    for entity, ent_scores in by_entity.items():
        agg = aggregate(entity, ent_scores, window="backtest")
        for rule in rules:
            sig = rule.evaluate(agg)
            if sig and sig.severity > best_sev:
                best_label, best_sev = sig.type.value, sig.severity
    return best_label


async def run_backtest(records: list[BacktestRecord], model, rules=None) -> BacktestReport:
    rules = rules if rules is not None else DEFAULT_RULES
    extractor = FinancialEntityExtractor()
    pairs: list[tuple[str, str]] = []
    details: list[dict] = []
    for rec in records:
        predicted = await _predict(rec, model, extractor, rules)
        pairs.append((predicted, rec.expected))
        details.append({"id": rec.id, "predicted": predicted, "expected": rec.expected,
                        "correct": predicted == rec.expected})
    return BacktestReport(metrics=compute_metrics(pairs), pairs=pairs, details=details)
