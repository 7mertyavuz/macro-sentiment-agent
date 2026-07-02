"""nlp.fusion testleri (Faz 7) — füzyon, belirsizlik türetme, olumsuzlama, sarkazm.

Ağ/torch/DB gerektirmez; tamamı deterministik.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from macro_sentiment.core.models import Emotion, SentimentScore, SourceType
from macro_sentiment.nlp import lexicon_fallback
from macro_sentiment.nlp.fusion import (
    derive_emotion,
    detect_sarcasm,
    fuse,
    negation_adjusted_polarity,
)
from tests.conftest import FIXTURES

UTC = timezone.utc


def _score(polarity, confidence, entity="BTC", fear=0.0, greed=0.0, uncertainty=0.0,
           model_version="m@1", intensity=50.0) -> SentimentScore:
    return SentimentScore(
        doc_id="d1", entity=entity, polarity=polarity, intensity=intensity,
        emotion=Emotion(fear=fear, greed=greed, uncertainty=uncertainty),
        confidence=confidence, model_version=model_version,
        source_type=SourceType.NEWS, created_at=datetime.now(UTC),
    )


# ---- fuse() ------------------------------------------------------------------------

def test_fuse_single_score_passthrough():
    s = _score(0.5, 0.8)
    assert fuse([s]) is s


def test_fuse_empty_raises():
    with pytest.raises(ValueError):
        fuse([])


def test_fuse_agrees_confidence_close_to_inputs():
    a = _score(0.6, 0.8, greed=0.5)
    b = _score(0.65, 0.85, greed=0.55)
    out = fuse([a, b])
    assert out.polarity == pytest.approx((0.6 * 0.8 + 0.65 * 0.85) / (0.8 + 0.85), abs=1e-3)
    assert out.confidence >= min(a.confidence, b.confidence) * 0.9  # anlaşma → güven düşmüyor


def test_fuse_disagreement_confidence_below_min_input():
    a = _score(0.9, 0.9, model_version="finbert@1")
    b = _score(-0.9, 0.8, model_version="llm@1")
    out = fuse([a, b])
    assert out.confidence < min(a.confidence, b.confidence)
    assert out.model_version.startswith("fusion(")


def test_fuse_disagreement_raises_uncertainty():
    a = _score(1.0, 0.9, uncertainty=0.1)
    b = _score(-1.0, 0.9, uncertainty=0.1)
    out = fuse([a, b])
    assert out.emotion.uncertainty > 0.1  # çelişki belirsizliği yükseltir


def test_fuse_preserves_entity_and_doc():
    a = _score(0.5, 0.7, entity="AAPL")
    b = _score(0.4, 0.6, entity="AAPL")
    out = fuse([a, b])
    assert out.entity == "AAPL" and out.doc_id == "d1"


# ---- derive_emotion() ---------------------------------------------------------------

def test_derive_emotion_high_conviction_low_uncertainty():
    e = derive_emotion(polarity=0.9, intensity=90.0, text="Stocks rally to record high on strong growth")
    assert e.uncertainty < 0.4


def test_derive_emotion_weak_conviction_high_uncertainty():
    e = derive_emotion(
        polarity=0.05, intensity=10.0,
        text="Markets could possibly rise or fall depending on unclear guidance, risk remains",
    )
    assert e.uncertainty > 0.5


def test_derive_emotion_has_variance_across_inputs():
    texts = [
        ("Apple beats earnings with record revenue", 0.8, 80.0),
        ("Fed may possibly consider uncertain, unclear rate moves", 0.05, 20.0),
        ("Bitcoin plunges amid panic selloff", -0.8, 80.0),
        ("Analysts cautious, mixed and ambiguous risky outlook", 0.0, 15.0),
    ]
    uncertainties = [derive_emotion(p, i, t).uncertainty for t, p, i in texts]
    assert len(set(uncertainties)) > 1  # sabit değil, gerçek varyans var
    assert max(uncertainties) - min(uncertainties) > 0.1


def test_derive_emotion_fear_greed_follow_polarity_sign():
    fear_case = derive_emotion(-0.8, 80.0, "crash")
    greed_case = derive_emotion(0.8, 80.0, "rally")
    assert fear_case.fear > fear_case.greed
    assert greed_case.greed > greed_case.fear


# ---- negation-lite --------------------------------------------------------------------

def test_negation_softens_or_flips_polarity():
    base = 0.6
    adjusted = negation_adjusted_polarity(base, "not good, not strong, not a good sign at all")
    assert adjusted < base  # yoğun olumsuzlama işareti aşağı çeker


def test_negation_no_effect_without_negation_words():
    base = 0.6
    assert negation_adjusted_polarity(base, "great strong quarter") == base


# ---- sarcasm-lite -----------------------------------------------------------------------

def test_detect_sarcasm_marker_phrase():
    assert detect_sarcasm("Sure thing, this stock will totally moon lol") is True


def test_detect_sarcasm_excessive_caps_and_exclaim():
    assert detect_sarcasm("GREAT!!! Just GREAT!!! love losing money!!!") is True


def test_detect_sarcasm_false_for_plain_text():
    assert detect_sarcasm("Apple reported strong quarterly earnings today") is False


# ---- lexicon_fallback entegrasyonu (Faz 7 alanları mevcut mu) --------------------------

def test_lexicon_score_text_has_uncertainty_key():
    r = lexicon_fallback.score_text("surge rally record profit beats")
    assert "uncertainty" in r and 0.0 <= r["uncertainty"] <= 1.0


def test_lexicon_negation_reduces_positive_polarity():
    plain = lexicon_fallback.score_text("beats profit growth strong record")
    negated = lexicon_fallback.score_text(
        "not a beats, not profit, not growth, not strong, not a record quarter at all no gains"
    )
    assert negated["polarity"] < plain["polarity"]


def test_lexicon_sarcasm_lowers_confidence():
    plain = lexicon_fallback.score_text("surge rally record profit beats growth")
    sarcastic = lexicon_fallback.score_text("Sure thing, surge rally record profit beats growth lol")
    assert sarcastic["confidence"] < plain["confidence"]


# ---- kalibrasyon spot-check (roadmap "bitti tanımı") -----------------------------------

def test_emotion_labeled_fixture_uncertainty_direction():
    rows = [json.loads(l) for l in (FIXTURES / "emotion_labeled.jsonl").read_text().splitlines()
            if l.strip() and not l.startswith("#")]
    low_group = [lexicon_fallback.score_text(r["text"])["uncertainty"]
                 for r in rows if r["expect_uncertainty"] == "low"]
    high_group = [lexicon_fallback.score_text(r["text"])["uncertainty"]
                  for r in rows if r["expect_uncertainty"] == "high"]
    assert low_group and high_group
    assert (sum(high_group) / len(high_group)) > (sum(low_group) / len(low_group))
