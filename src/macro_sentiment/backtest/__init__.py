"""Backtest — etiketli geçmiş veriyle sinyal isabetini ölçer (ARCHITECTURE.md §11 Faz 2/3).

Pipeline'ı (NLP → sinyal kuralları) çevrimdışı replay eder, üretilen sinyal tipini
beklenen etiketle karşılaştırır ve precision/recall/F1/accuracy raporu üretir.
Eşiklerin kalibrasyonu için temel araç.
"""
from .harness import BacktestReport, run_backtest
from .dataset import BacktestRecord, load_jsonl

__all__ = ["BacktestRecord", "load_jsonl", "BacktestReport", "run_backtest"]
