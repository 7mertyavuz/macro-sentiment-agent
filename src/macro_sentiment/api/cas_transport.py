"""CAS taşıma katmanı — serileştirme, sürümleme, şok sönümleme (Faz 6).

Simülatör muhtemelen ayrı bir süreç/repo olarak çalışır; bu yüzden
``SentimentState``/``ShockEvent`` süreçler-arası (JSON üzerinden) taşınabilir
olmalıdır. Bu modül üç şeyi sağlar:

* ``to_dict``/``from_dict`` round-trip serileştirme + sözleşme ``schema_version``.
* ``decayed_magnitude(shock, at_ts)`` — şokun zaman içindeki sönümlenmiş
  büyüklüğünü hesaplayan saf fonksiyon (simülatör ve iç tüketiciler ortak kullanır).

Hiçbir ağ/DB çağrısı yapmaz; yalnızca stdlib kullanır (gevşek bağlılık kuralı).
"""
from __future__ import annotations

from datetime import datetime, timezone

from .cas_contracts import SentimentState, ShockEvent

# Sözleşme şeması sürümü. Alan eklenirse/anlamı değişirse artırılır.
CAS_SCHEMA_VERSION = "1.0"


def _to_iso(ts: datetime) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).isoformat()


def _from_iso(s: str) -> datetime:
    ts = datetime.fromisoformat(s)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


# ---- SentimentState -----------------------------------------------------------

def sentiment_state_to_dict(state: SentimentState) -> dict:
    """``SentimentState`` -> JSON-uyumlu dict (``schema_version`` dahil)."""
    return {
        "schema_version": CAS_SCHEMA_VERSION,
        "type": "SentimentState",
        "entity": state.entity,
        "polarity": state.polarity,
        "intensity": state.intensity,
        "emotion": dict(state.emotion),
        "confidence": state.confidence,
        "fed_tone": state.fed_tone,
        "source_breakdown": dict(state.source_breakdown),
        "ts": _to_iso(state.ts),
    }


def sentiment_state_from_dict(d: dict) -> SentimentState:
    """JSON-uyumlu dict -> ``SentimentState``. ``schema_version`` alanı yok sayılır
    (ileri uyum: bilinmeyen ek alanlar hata vermez)."""
    return SentimentState(
        entity=d["entity"],
        polarity=float(d["polarity"]),
        intensity=float(d["intensity"]),
        emotion=dict(d.get("emotion", {})),
        confidence=float(d["confidence"]),
        fed_tone=(None if d.get("fed_tone") is None else float(d["fed_tone"])),
        source_breakdown=dict(d.get("source_breakdown", {})),
        ts=_from_iso(d["ts"]),
    )


# ---- ShockEvent -----------------------------------------------------------------

def shock_event_to_dict(shock: ShockEvent) -> dict:
    """``ShockEvent`` -> JSON-uyumlu dict (``schema_version`` dahil)."""
    return {
        "schema_version": CAS_SCHEMA_VERSION,
        "type": "ShockEvent",
        "kind": shock.kind,
        "entity": shock.entity,
        "magnitude": shock.magnitude,
        "decay_halflife_s": shock.decay_halflife_s,
        "ts": _to_iso(shock.ts),
        "meta": dict(shock.meta),
    }


def shock_event_from_dict(d: dict) -> ShockEvent:
    """JSON-uyumlu dict -> ``ShockEvent``."""
    return ShockEvent(
        kind=d["kind"],
        entity=d["entity"],
        magnitude=float(d["magnitude"]),
        decay_halflife_s=float(d["decay_halflife_s"]),
        ts=_from_iso(d["ts"]),
        meta=dict(d.get("meta", {})),
    )


# ---- Şok sönümleme ---------------------------------------------------------------

def decayed_magnitude(shock: ShockEvent, at_ts: datetime) -> float:
    """``at_ts`` anında şokun sönümlenmiş büyüklüğü.

    ``magnitude * 0.5 ** (dt / halflife)`` — dt = at_ts - shock.ts (saniye).

    * ``dt <= 0`` (şoktan önce/anında sorgu) → sönüm yok, ham ``magnitude`` döner.
    * ``decay_halflife_s <= 0`` ve ``dt > 0`` → anında sıfıra düşmüş sayılır.
    * Sonuç her zaman ``[0, magnitude]`` aralığında (clamp).
    """
    if at_ts.tzinfo is None:
        at_ts = at_ts.replace(tzinfo=timezone.utc)
    shock_ts = shock.ts if shock.ts.tzinfo is not None else shock.ts.replace(tzinfo=timezone.utc)
    dt = (at_ts - shock_ts).total_seconds()
    if dt <= 0:
        return shock.magnitude
    if shock.decay_halflife_s <= 0:
        return 0.0
    value = shock.magnitude * (0.5 ** (dt / shock.decay_halflife_s))
    return max(0.0, min(shock.magnitude, value))


__all__ = [
    "CAS_SCHEMA_VERSION",
    "sentiment_state_to_dict",
    "sentiment_state_from_dict",
    "shock_event_to_dict",
    "shock_event_from_dict",
    "decayed_magnitude",
]
