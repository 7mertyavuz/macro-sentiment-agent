"""Insider connector, Fama-French proxy, yeni kurallar ve konsey füzyonu."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from macro_sentiment.api.cas_contracts import SentimentState
from macro_sentiment.api.cas_transport import (
    CAS_SCHEMA_VERSION,
    sentiment_state_from_dict,
    sentiment_state_to_dict,
)
from macro_sentiment.api.sentiment_feed import SentimentFeed
from macro_sentiment.nlp.council import (
    Opinion,
    anonymize,
    chairman_synthesis,
    council_route,
    peer_scores,
)
from macro_sentiment.signals.aggregator import WindowAggregate
from macro_sentiment.signals.famafrench import dominant_style, factor_tilt
from macro_sentiment.signals.rules import DEFAULT_RULES, BreakoutRule, NarrativeRule
from macro_sentiment.sources.insider_connector import (
    InsiderConnector,
    classify_transaction,
    insider_pressure,
)
from macro_sentiment.sources.registry import REGISTRY


# ── insider connector ─────────────────────────────────────────────
@pytest.mark.parametrize("text,expected", [
    ("Officer purchased 10,000 shares", 1),
    ("Director sold 5,000 shares", -1),
    ("Shares acquired under plan", 1),
    ("Disposition of common stock", -1),
    ("Form 4 filing", 0),
    ("Purchase and sale reported", 0),      # ikisi de var -> belirsiz
])
def test_transaction_direction_classification(text, expected):
    assert classify_transaction(text) == expected


def test_insider_pressure_is_asymmetric():
    """Alim, satistan daha guclu bir sinyaldir — esit hacimde alim kazanmali."""
    mixed = insider_pressure([{"direction": 1, "value_usd": 100_000},
                              {"direction": -1, "value_usd": 100_000}])
    assert mixed > 0


def test_insider_pressure_bounds_and_neutrality():
    assert insider_pressure([]) == 0.0
    assert insider_pressure([{"direction": 0, "value_usd": 1e9}]) == 0.0
    assert insider_pressure([{"direction": 1, "value_usd": 1}]) == pytest.approx(1.0)
    assert insider_pressure([{"direction": -1, "value_usd": 1}]) == pytest.approx(-1.0)


@pytest.mark.asyncio
async def test_insider_connector_offline_mode_is_networkless():
    conn = InsiderConnector(offline_fixtures=[
        {"title": "CEO purchased 50,000 shares", "body": "Form 4", "url": "http://x",
         "published_at": "2026-08-01T00:00:00Z"},
        {"title": "CFO sold 10,000 shares", "body": "Form 4",
         "published_at": "2026-08-02T00:00:00Z"},
    ])
    docs = await conn.fetch(datetime(2020, 1, 1, tzinfo=timezone.utc))
    assert len(docs) == 2
    assert docs[0].raw_meta["insider_direction"] == 1
    assert docs[1].raw_meta["insider_direction"] == -1
    # Kongre verisi bu connector'da YOK ve bunu acikca soyluyor.
    assert docs[0].raw_meta["covers_congress"] is False


def test_insider_connector_is_registered():
    assert "insider:sec_form4" in REGISTRY


# ── Fama-French proxy ─────────────────────────────────────────────
def test_hawkish_tone_favours_value_over_small_caps():
    """Sahin ton: deger lehine (uzun vadeli nakit akisi iskonto edilir),
    kucuk sirket aleyhine (finansmana bagimli)."""
    t = factor_tilt(polarity=0.0, fed_tone=0.9)
    assert t["hml"] > 0
    assert t["smb"] < 0


def test_risk_appetite_favours_small_caps():
    t = factor_tilt(polarity=0.8, greed=0.7, fear=0.0)
    assert t["smb"] > 0
    assert t["mkt"] > 0


def test_low_confidence_damps_every_tilt():
    strong = factor_tilt(polarity=0.9, fed_tone=0.9, confidence=1.0)
    weak = factor_tilt(polarity=0.9, fed_tone=0.9, confidence=0.1)
    for k in ("mkt", "smb", "hml"):
        assert abs(weak[k]) < abs(strong[k])


def test_tilts_stay_in_range():
    t = factor_tilt(polarity=1.0, fed_tone=1.0, fear=1.0, greed=1.0, uncertainty=1.0)
    assert all(-1.0 <= v <= 1.0 for v in t.values())


def test_dominant_style_labels():
    assert dominant_style({"mkt": 0.0, "smb": 0.0, "hml": 0.0}) == "neutral"
    assert dominant_style(factor_tilt(polarity=0.0, fed_tone=0.95)) == "value"
    assert dominant_style({}) == "neutral"


# ── eksik iki kural ───────────────────────────────────────────────
def _agg(**kw) -> WindowAggregate:
    base = dict(entity="BTC", window="1h", volume=10, mean_polarity=0.0,
                mean_intensity=50.0, mean_fear=0.0, mean_greed=0.0,
                mean_confidence=0.8, mean_uncertainty=0.0, source_breakdown={})
    base.update(kw)
    return WindowAggregate(**base)


def test_default_rules_now_cover_all_five_signal_types():
    """README ve ARCHITECTURE.md 5 sinyal tipi reklam ediyordu; yalnizca 3'u vardi."""
    kinds = {type(r).__name__ for r in DEFAULT_RULES}
    assert {"PanicRule", "EuphoriaRule", "FedToneRule",
            "NarrativeRule", "BreakoutRule"} == kinds


def test_narrative_rule_fires_on_source_disagreement():
    sig = NarrativeRule().evaluate(_agg(
        source_breakdown={"news": 0.6, "social": -0.4}, mean_uncertainty=0.5))
    assert sig is not None and sig.type.value == "narrative"
    assert sig.payload["source_spread"] == pytest.approx(1.0)


def test_narrative_rule_stays_quiet_when_sources_agree():
    assert NarrativeRule().evaluate(_agg(
        source_breakdown={"news": 0.6, "social": 0.55}, mean_uncertainty=0.9)) is None


def test_narrative_rule_needs_uncertainty_too():
    """Ayrisma tek basina yetmez: dusuk belirsizlikte bu bir anlati degisimi degil."""
    assert NarrativeRule().evaluate(_agg(
        source_breakdown={"news": 0.9, "social": -0.9}, mean_uncertainty=0.05)) is None


def test_breakout_rule_fires_on_volume_burst():
    sig = BreakoutRule().evaluate(_agg(volume=20), volume_z=4.0)
    assert sig is not None and sig.type.value == "breakout"
    assert sig.direction == 0.0, "hacim patlamasi bir yon iddiasi tasimaz"


def test_breakout_rule_ignores_normal_volume():
    assert BreakoutRule().evaluate(_agg(volume=20), volume_z=0.5) is None


# ── konsey (anonim akran degerlendirmesi) ─────────────────────────
def _ops(*pairs) -> list[Opinion]:
    return [Opinion(member=m, polarity=p, confidence=c) for m, p, c in pairs]


def test_anonymize_hides_member_identity_but_is_stable():
    ops = _ops(("finbert", 0.5, 0.8), ("llm", 0.3, 0.7))
    a, b = anonymize(ops), anonymize(ops)
    assert list(a) == list(b), "etiketler kosular arasi kararli olmali"
    assert all(not lbl.endswith(("finbert", "llm")) for lbl in a)


def test_confident_outlier_is_penalised_not_rewarded():
    """Aykiri + asiri emin, konseyde agirlik KAYBEDER."""
    ops = _ops(("a", 0.5, 0.9), ("b", 0.55, 0.9), ("c", -0.9, 0.95))
    w = peer_scores(anonymize(ops))
    anon = anonymize(ops)
    outlier = next(lbl for lbl, o in anon.items() if o.polarity < 0)
    assert w[outlier] == min(w.values())


def test_consensus_confidence_collapses_on_hard_disagreement():
    agree = chairman_synthesis(_ops(("a", 0.5, 0.9), ("b", 0.52, 0.9)))
    split = chairman_synthesis(_ops(("a", 0.9, 0.9), ("b", -0.9, 0.9)))
    assert split["confidence"] < agree["confidence"]
    assert split["uncertainty"] > agree["uncertainty"]


def test_consensus_of_agreeing_members_keeps_the_polarity():
    out = chairman_synthesis(_ops(("a", 0.6, 0.8), ("b", 0.62, 0.8), ("c", 0.58, 0.8)))
    assert out["polarity"] == pytest.approx(0.6, abs=0.05)
    assert out["spread"] < 0.1


def test_single_member_council_is_a_passthrough():
    out = chairman_synthesis(_ops(("solo", 0.4, 0.7)))
    assert out["polarity"] == pytest.approx(0.4)
    assert out["members"] == 1


def test_empty_council_makes_no_claim():
    out = chairman_synthesis([])
    assert out["confidence"] == 0.0 and out["uncertainty"] == 1.0


def test_council_route_escalates_only_on_disagreement():
    class _Doc:
        source_type = None
        body = "kisa"

    assert council_route(_Doc(), _ops(("a", 0.5, 0.8), ("b", 0.55, 0.8))) is False
    assert council_route(_Doc(), _ops(("a", 0.6, 0.8), ("b", -0.3, 0.8))) is True


def test_council_route_escalates_when_everyone_is_unsure():
    class _Doc:
        source_type = None
        body = "kisa"

    assert council_route(_Doc(), _ops(("a", 0.1, 0.2), ("b", 0.12, 0.2))) is True


# ── şema 1.1 ──────────────────────────────────────────────────────
def test_schema_version_bumped():
    assert CAS_SCHEMA_VERSION == "1.1"


def test_new_contract_fields_round_trip():
    st = SentimentState(entity="BTC", polarity=0.3, intensity=50.0,
                        emotion={"fear": 0.1, "greed": 0.4, "uncertainty": 0.2},
                        confidence=0.8, fed_tone=None, source_breakdown={"news": 0.3},
                        ts=datetime.now(timezone.utc),
                        insider_pressure=0.42,
                        factor_tilt={"mkt": 0.2, "smb": 0.1, "hml": -0.05})
    back = sentiment_state_from_dict(sentiment_state_to_dict(st))
    assert back.insider_pressure == pytest.approx(0.42)
    assert back.factor_tilt["mkt"] == pytest.approx(0.2)


def test_old_1_0_payload_still_parses():
    """Geriye uyum: 1.0 yuku yeni alanlar olmadan da okunabilmeli."""
    payload = {
        "schema_version": "1.0", "type": "SentimentState", "entity": "BTC",
        "polarity": 0.1, "intensity": 10.0, "emotion": {}, "confidence": 0.5,
        "fed_tone": None, "source_breakdown": {},
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    st = sentiment_state_from_dict(payload)
    assert st.insider_pressure == 0.0 and st.factor_tilt == {}


def test_offline_feed_populates_the_new_fields():
    """Adaptor tarafinda 'alan var mi yok mu' belirsizligi dogmamali."""
    st = SentimentFeed(mode="offline").latest("BTC")
    assert -1.0 <= st.insider_pressure <= 1.0
    assert set(st.factor_tilt) == {"mkt", "smb", "hml"}


def test_offline_feed_stays_deterministic():
    a = SentimentFeed(mode="offline").latest("BTC")
    b = SentimentFeed(mode="offline").latest("BTC")
    assert a.polarity == b.polarity
    assert a.insider_pressure == b.insider_pressure
    assert a.factor_tilt == b.factor_tilt
