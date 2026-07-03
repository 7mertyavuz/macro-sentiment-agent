"""Otomatik eşik kalibrasyonu testleri (Faz 11) — regresyon: öneri backtest F1'i düşürmez."""
from __future__ import annotations

import pytest

from macro_sentiment.backtest.dataset import BacktestRecord, load_jsonl
from macro_sentiment.backtest.harness import run_backtest
from macro_sentiment.nlp.sentiment_finbert import FinBERTSentiment
from macro_sentiment.signals.calibration import suggest_threshold
from macro_sentiment.signals.rules import EuphoriaRule, FedToneRule, PanicRule
from tests.conftest import FIXTURES

# Sözlük fallback ile doğrulanmış (score_text) küçük, kontrollü set:
# "borderline" polarite tam -0.333 çıkar — -0.35 eşiğinde (skip: pol > eşik ise
# atlanır) kaçırılır, -0.2 gibi daha gevşek bir eşikte yakalanır. "strong" her
# eşikte ateşler, "none" hiçbirinde ateşlemez (sahte pozitif riski yok).
_CALIBRATION_RECORDS = [
    BacktestRecord(id="p1", body="crash panic plunge", expected="panic"),
    BacktestRecord(id="p2", body="stock gain fear falls", expected="panic"),
    BacktestRecord(id="n1", body="shares steady modest update", expected="none"),
]


@pytest.mark.asyncio
async def test_suggest_threshold_never_regresses_f1():
    recs = load_jsonl(FIXTURES / "backtest.jsonl")
    model = FinBERTSentiment(use_finbert=False)

    suggestion = await suggest_threshold(
        recs, model,
        rule_factory=lambda v: PanicRule(pol_threshold=v),
        param_name="panic.pol_threshold",
        baseline_value=-0.35,
        candidates=[-0.6, -0.5, -0.35, -0.2, -0.1],
        other_rules=[EuphoriaRule(), FedToneRule()],
    )
    assert suggestion.suggested_f1 >= suggestion.baseline_f1  # regresyon yok


@pytest.mark.asyncio
async def test_suggest_threshold_returns_baseline_when_it_is_already_optimal():
    """Aday kümesi baseline'dan daha iyisini içermiyorsa, öneri baseline'ı döndürmeli."""
    recs = load_jsonl(FIXTURES / "backtest.jsonl")
    model = FinBERTSentiment(use_finbert=False)

    baseline_report = await run_backtest(recs, model, rules=[PanicRule(), EuphoriaRule(), FedToneRule()])
    baseline_labels = [lab for lab in baseline_report.metrics.per_label if lab != "none"]
    baseline_f1 = sum(baseline_report.metrics.per_label[lab].f1 for lab in baseline_labels) / len(baseline_labels)

    suggestion = await suggest_threshold(
        recs, model,
        rule_factory=lambda v: PanicRule(pol_threshold=v),
        param_name="panic.pol_threshold",
        baseline_value=-0.35,
        candidates=[-0.35],  # yalnızca baseline aday
        other_rules=[EuphoriaRule(), FedToneRule()],
    )
    assert suggestion.suggested_value == -0.35
    assert suggestion.suggested_f1 == pytest.approx(baseline_f1)


@pytest.mark.asyncio
async def test_suggest_threshold_can_improve_on_a_deliberately_bad_baseline():
    """Sınır durumlu bir kaydı kaçıran kısıtlayıcı bir eşikten daha iyi bir aday bulunabilmeli.

    ``-0.35`` (mevcut varsayılan eşik) bu sette "borderline" panik örneğini
    kaçırır (polarite -0.333, eşikten daha az negatif → atlanır) → macro-F1
    düşük kalır. ``-0.2`` gibi biraz daha gevşek bir eşik onu yakalar ve hâlâ
    "none" örneğinde yanlış pozitif üretmez → F1 yükselir.
    """
    model = FinBERTSentiment(use_finbert=False)

    suggestion = await suggest_threshold(
        _CALIBRATION_RECORDS, model,
        rule_factory=lambda v: PanicRule(pol_threshold=v),
        param_name="panic.pol_threshold",
        baseline_value=-0.35,
        candidates=[-0.6, -0.35, -0.3, -0.2, -0.1],
        other_rules=[EuphoriaRule(), FedToneRule()],
    )
    assert suggestion.baseline_f1 == pytest.approx(0.6667, abs=1e-3)
    assert suggestion.improved is True
    assert suggestion.suggested_f1 == pytest.approx(1.0)
    assert suggestion.suggested_value != -0.35
