"""Deterministik senaryo replay'i (cas-market-simulator için).

Simülatörün tekrarlanabilir deney yapabilmesi için *scriptli* bir haber/olay
zaman çizelgesini (JSONL) deterministik olarak oynatır. Hiçbir API/RPC/anahtar
çağrılmaz — mevcut ``backtest`` harness'iyle aynı sözlük-tabanlı modeli kullanır
ve JSONL formatını onunla paylaşır.

JSONL satır formatı (her satır bir olay)
----------------------------------------
Ortak alan: ``t`` — senaryo başlangıcından itibaren saniye (varsayılan 0).
``type`` alanı olayın türünü belirler:

* ``news``      — {t, type:"news", title, body, source_type?, entity?}
    Sözlük modeliyle skorlanır; hem SentimentState hem (kural tetiklenirse)
    ShockEvent üretebilir. backtest.jsonl ile alan-uyumludur.
* ``sentiment`` — {t, type:"sentiment", entity, polarity, intensity, fear,
    greed, uncertainty, confidence, fed_tone?, source_breakdown?}
    Doğrudan bir SentimentState olarak enjekte edilir.
* ``shock``     — {t, type:"shock", kind, entity, magnitude, decay_halflife_s?}
    Doğrudan bir ShockEvent olarak enjekte edilir.

Örnek: ``{"t":0,"type":"news","title":"Fed warns on inflation","body":"...","source_type":"fed","entity":"FED"}``

Şema doğrulama (Faz 6): her satır Pydantic modeliyle doğrulanır; bozuk/eksik
alanlı satırlar satır numarasıyla birlikte anlaşılır ``ValueError`` fırlatır.
``# yorum`` ve boş satır toleransı korunur.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from ..core.models import RawDocument, SourceType
from ..signals.aggregator import aggregate
from .cas_contracts import SHOCK_KINDS, SentimentState, ShockEvent
from .sentiment_feed import DECAY_HALFLIFE_S, _SIGNAL_KIND_MAP, _run, aggregate_to_state

_EPOCH = datetime(2000, 1, 1, tzinfo=timezone.utc)  # sabit deterministik başlangıç


# ---- JSONL satır şema doğrulama (Faz 6) ------------------------------------------
# Her olay tipi için Pydantic modeli: bozuk/eksik alanlı satırlar için satır
# numarasıyla birlikte anlaşılır hata mesajı üretir. Geçerli senaryolar aynen çalışır.

class _NewsRow(BaseModel):
    t: float = 0.0
    type: Literal["news"] = "news"
    title: str | None = None
    body: str = ""
    source_type: str = "news"
    entity: str | None = None


class _SentimentRow(BaseModel):
    t: float = 0.0
    type: Literal["sentiment"]
    entity: str
    polarity: float = 0.0
    intensity: float = 0.0
    fear: float = 0.0
    greed: float = 0.0
    uncertainty: float = 0.0
    confidence: float = 0.5
    fed_tone: float | None = None
    source_breakdown: dict = Field(default_factory=dict)


class _ShockRow(BaseModel):
    t: float = 0.0
    type: Literal["shock"]
    kind: str
    entity: str
    magnitude: float = 0.5
    decay_halflife_s: float | None = None
    meta: dict = Field(default_factory=dict)

    @field_validator("kind")
    @classmethod
    def _valid_kind(cls, v: str) -> str:
        if v not in SHOCK_KINDS:
            raise ValueError(f"geçersiz şok türü {v!r} (geçerli: {SHOCK_KINDS})")
        return v


_ROW_MODELS: dict[str, type[BaseModel]] = {
    "news": _NewsRow,
    "sentiment": _SentimentRow,
    "shock": _ShockRow,
}


def validate_row(row: dict, line_no: int | None = None) -> dict:
    """Bir senaryo JSONL satırını doğrular; doğrulanmış (varsayılanlı) dict döner.

    Bilinmeyen ``type`` veya şema ihlali durumunda ``ValueError`` fırlatır;
    mesaj mevcutsa satır numarasını içerir.
    """
    etype = row.get("type", "news")
    loc = f"satır {line_no}: " if line_no is not None else ""
    model = _ROW_MODELS.get(etype)
    if model is None:
        raise ValueError(f"{loc}bilinmeyen senaryo olay tipi: {etype!r}")
    try:
        validated = model.model_validate(row)
    except ValidationError as e:
        raise ValueError(f"{loc}geçersiz senaryo satırı ({etype}): {e}") from e
    return validated.model_dump()


def _neutral_state(entity: str, ts: datetime) -> SentimentState:
    return SentimentState(
        entity=entity, polarity=0.0, intensity=0.0,
        emotion={"fear": 0.0, "greed": 0.0, "uncertainty": 0.0},
        confidence=0.0, fed_tone=None, source_breakdown={}, ts=ts,
    )


class ScenarioPlayer:
    """Önceden hesaplanmış deterministik durum/şok zaman çizelgesi."""

    def __init__(
        self,
        start_ts: datetime,
        states: list[tuple[datetime, SentimentState]],
        shocks: list[ShockEvent],
    ) -> None:
        self.start_ts = start_ts
        # (ts, state) artan sıralı; state_at ikili arama yerine lineer tarar (küçük N).
        self._states = sorted(states, key=lambda x: x[0])
        self._shocks = sorted(shocks, key=lambda s: s.ts)

    # ---- Yükleme ----------------------------------------------------------
    @classmethod
    def from_jsonl(cls, path: str | Path, start_ts: datetime | None = None) -> "ScenarioPlayer":
        start = start_ts or _EPOCH
        rows = []
        for line_no, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"satır {line_no}: geçersiz JSON: {e}") from e
            rows.append(validate_row(raw, line_no=line_no))
        return cls.from_events(rows, start_ts=start)

    @classmethod
    def from_events(cls, rows: list[dict], start_ts: datetime | None = None) -> "ScenarioPlayer":
        start = start_ts or _EPOCH
        states: list[tuple[datetime, SentimentState]] = []
        shocks: list[ShockEvent] = []

        # "news" olaylarını toplu ve deterministik skorla (API yok).
        news_rows = [(i, r) for i, r in enumerate(rows) if r.get("type", "news") == "news"]
        news_out = _run(_score_news(news_rows, start)) if news_rows else {}

        for i, r in enumerate(rows):
            etype = r.get("type", "news")
            ts = start + timedelta(seconds=float(r.get("t", 0)))
            if etype == "sentiment":
                states.append((ts, _row_to_state(r, ts)))
            elif etype == "shock":
                shocks.append(_row_to_shock(r, ts))
            elif etype == "news":
                st, sh = news_out.get(i, ([], []))
                states.extend((ts, s) for s in st)
                shocks.extend(sh)
            else:
                raise ValueError(f"Bilinmeyen senaryo olay tipi: {etype!r}")
        return cls(start, states, shocks)

    # ---- Sorgu ------------------------------------------------------------
    def state_at(self, entity: str, clock: datetime) -> SentimentState:
        """clock anında (dahil) o varlık için en güncel durumu döndürür."""
        latest: SentimentState | None = None
        for ts, st in self._states:
            if ts <= clock and st.entity == entity:
                latest = st
            elif ts > clock:
                break
        return latest if latest is not None else _neutral_state(entity, clock)

    def shocks_between(self, since: datetime, clock: datetime) -> list[ShockEvent]:
        """(since, clock] aralığındaki şokları zaman sırasıyla döndürür."""
        return [s for s in self._shocks if since < s.ts <= clock]

    @property
    def end_ts(self) -> datetime:
        last = self.start_ts
        for ts, _ in self._states:
            last = max(last, ts)
        for s in self._shocks:
            last = max(last, s.ts)
        return last


def _row_to_state(r: dict, ts: datetime) -> SentimentState:
    return SentimentState(
        entity=r["entity"],
        polarity=float(r.get("polarity", 0.0)),
        intensity=float(r.get("intensity", 0.0)),
        emotion={
            "fear": float(r.get("fear", 0.0)),
            "greed": float(r.get("greed", 0.0)),
            "uncertainty": float(r.get("uncertainty", 0.0)),
        },
        confidence=float(r.get("confidence", 0.5)),
        fed_tone=(None if r.get("fed_tone") is None else float(r["fed_tone"])),
        source_breakdown=dict(r.get("source_breakdown", {})),
        ts=ts,
    )


def _row_to_shock(r: dict, ts: datetime) -> ShockEvent:
    kind = r["kind"]
    if kind not in SHOCK_KINDS:
        raise ValueError(f"Geçersiz şok türü: {kind!r} (geçerli: {SHOCK_KINDS})")
    dh = r.get("decay_halflife_s")
    return ShockEvent(
        kind=kind,
        entity=r["entity"],
        magnitude=max(0.0, min(1.0, float(r.get("magnitude", 0.5)))),
        decay_halflife_s=float(dh) if dh is not None else DECAY_HALFLIFE_S[kind],
        ts=ts,
        meta=dict(r.get("meta", {})),
    )


async def _score_news(
    news_rows: list[tuple[int, dict]], start: datetime
) -> dict[int, tuple[list[SentimentState], list[ShockEvent]]]:
    """News olaylarını sözlük modeliyle skorlar; state + (tetiklenen) şokları üretir."""
    from ..nlp.ner import FinancialEntityExtractor
    from ..nlp.sentiment_finbert import FinBERTSentiment
    from ..signals.rules import DEFAULT_RULES

    model = FinBERTSentiment(use_finbert=False)  # deterministik, ağ yok
    extractor = FinancialEntityExtractor()
    out: dict[int, tuple[list[SentimentState], list[ShockEvent]]] = {}

    for idx, r in news_rows:
        ts = start + timedelta(seconds=float(r.get("t", 0)))
        doc = RawDocument(
            id=f"scn-{idx}", source="scenario",
            source_type=SourceType(r.get("source_type", "news")),
            title=r.get("title"), body=r.get("body", ""),
            published_at=ts, fetched_at=ts, content_hash=f"scn-{idx}",
        )
        entities = await extractor.extract(doc)
        scores = await model.score(doc, entities)
        if r.get("entity"):
            scores = [s for s in scores if s.entity == r["entity"]] or scores

        by_entity: dict[str, list] = {}
        for s in scores:
            by_entity.setdefault(s.entity, []).append(s)

        states: list[SentimentState] = []
        shocks: list[ShockEvent] = []
        for entity, ent_scores in by_entity.items():
            agg = aggregate(entity, ent_scores, window="scenario")
            states.append(aggregate_to_state(agg, ts=ts))
            for rule in DEFAULT_RULES:
                sig = rule.evaluate(agg)
                if not sig:
                    continue
                kind = _SIGNAL_KIND_MAP.get(sig.type.value)
                if kind is None:
                    continue
                shocks.append(
                    ShockEvent(
                        kind=kind, entity=entity,
                        magnitude=max(0.0, min(1.0, sig.severity / 100.0)),
                        decay_halflife_s=DECAY_HALFLIFE_S[kind], ts=ts,
                        meta={"severity": sig.severity, "trigger": "news"},
                    )
                )
        out[idx] = (states, shocks)
    return out


__all__ = ["ScenarioPlayer", "validate_row"]
