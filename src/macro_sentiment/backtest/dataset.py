"""Etiketli backtest veri kümesi (JSONL).

Her satır bir belge + beklenen sinyal etiketi içerir:
  {"id","title","body","source_type","entity"(ops.),"expected": "panic|euphoria|fed_tone|none"}
"""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from ..core.models import SourceType

VALID_LABELS = {"panic", "euphoria", "fed_tone", "none"}


class BacktestRecord(BaseModel):
    id: str
    title: str | None = None
    body: str
    source_type: SourceType = SourceType.NEWS
    entity: str | None = None         # değerlendirmeyi tek varlığa sabitler (ops.)
    expected: str                     # VALID_LABELS

    def model_post_init(self, __context) -> None:
        if self.expected not in VALID_LABELS:
            raise ValueError(f"Geçersiz etiket: {self.expected} (geçerli: {VALID_LABELS})")


def load_jsonl(path: str | Path) -> list[BacktestRecord]:
    records: list[BacktestRecord] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(BacktestRecord.model_validate_json(line))
    return records
