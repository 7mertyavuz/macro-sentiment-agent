"""Backtest harness ve metrik testleri (ağ/torch/DB gerektirmez)."""
from __future__ import annotations

import pytest

from macro_sentiment.backtest.dataset import load_jsonl
from macro_sentiment.backtest.harness import run_backtest
from macro_sentiment.backtest.metrics import compute_metrics
from macro_sentiment.nlp.sentiment_finbert import FinBERTSentiment
from tests.conftest import FIXTURES


def test_compute_metrics_basic():
    pairs = [("panic", "panic"), ("panic", "none"), ("none", "none"), ("euphoria", "euphoria")]
    m = compute_metrics(pairs)
    assert m.n == 4 and m.accuracy == 0.75
    assert m.per_label["panic"].precision == 0.5   # 1 tp, 1 fp
    assert m.per_label["panic"].recall == 1.0      # 1 tp, 0 fn


def test_load_jsonl_parses_records():
    recs = load_jsonl(FIXTURES / "backtest.jsonl")
    assert len(recs) == 6
    assert {r.expected for r in recs} == {"euphoria", "panic", "fed_tone", "none"}


@pytest.mark.asyncio
async def test_backtest_accuracy_on_fixture():
    recs = load_jsonl(FIXTURES / "backtest.jsonl")
    report = await run_backtest(recs, FinBERTSentiment(use_finbert=False))
    # Sözlük modeli + kurallar bu küratörlü sette yüksek isabet vermeli
    assert report.metrics.accuracy >= 0.8
    # panik ve coşku doğru yakalanmalı
    d = {x["id"]: x for x in report.details}
    assert d["bt2"]["predicted"] == "panic"
    assert d["bt1"]["predicted"] == "euphoria"
    assert d["bt3"]["predicted"] == "fed_tone"
