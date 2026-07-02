"""CAS taşıma katmanı testleri (Faz 6) — serileştirme, decay, streaming, HTTP.

Ağ/torch/gerçek DB bağlantısı gerektirmez (offline yol).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from macro_sentiment.api.cas_contracts import SentimentState, ShockEvent
from macro_sentiment.api.cas_transport import (
    CAS_SCHEMA_VERSION,
    decayed_magnitude,
    sentiment_state_from_dict,
    sentiment_state_to_dict,
    shock_event_from_dict,
    shock_event_to_dict,
)
from macro_sentiment.api.main import app
from macro_sentiment.api.scenario import ScenarioPlayer
from macro_sentiment.api.sentiment_feed import SentimentFeed
from tests.conftest import FIXTURES

UTC = timezone.utc
SCENARIO = FIXTURES / "scenario.jsonl"


def _state(**overrides) -> SentimentState:
    base = dict(
        entity="BTC", polarity=-0.4, intensity=55.0,
        emotion={"fear": 0.6, "greed": 0.1, "uncertainty": 0.3},
        confidence=0.7, fed_tone=None,
        source_breakdown={"news": -0.4}, ts=datetime.now(UTC),
    )
    base.update(overrides)
    return SentimentState(**base)


def _shock(**overrides) -> ShockEvent:
    base = dict(
        kind="panic", entity="BTC", magnitude=0.8,
        decay_halflife_s=1800.0, ts=datetime.now(UTC), meta={"severity": 80},
    )
    base.update(overrides)
    return ShockEvent(**base)


# ---- Round-trip serileştirme -----------------------------------------------------

def test_sentiment_state_round_trip():
    st = _state()
    d = sentiment_state_to_dict(st)
    assert d["schema_version"] == CAS_SCHEMA_VERSION
    back = sentiment_state_from_dict(d)
    assert back == st


def test_shock_event_round_trip():
    sh = _shock()
    d = shock_event_to_dict(sh)
    assert d["schema_version"] == CAS_SCHEMA_VERSION
    back = shock_event_from_dict(d)
    assert back == sh


def test_sentiment_state_round_trip_fed_tone_none():
    st = _state(entity="AAPL", fed_tone=None)
    d = sentiment_state_to_dict(st)
    assert d["fed_tone"] is None
    assert sentiment_state_from_dict(d).fed_tone is None


def test_from_dict_ignores_unknown_fields():
    st = _state()
    d = sentiment_state_to_dict(st)
    d["extra_future_field"] = "ignored"
    assert sentiment_state_from_dict(d) == st


# ---- Şok sönümleme ----------------------------------------------------------------

def test_decayed_magnitude_halves_at_halflife():
    ts = datetime.now(UTC)
    sh = _shock(magnitude=0.8, decay_halflife_s=1000.0, ts=ts)
    val = decayed_magnitude(sh, ts + timedelta(seconds=1000))
    assert val == pytest.approx(0.4, abs=1e-9)


def test_decayed_magnitude_no_decay_before_shock():
    ts = datetime.now(UTC)
    sh = _shock(magnitude=0.8, ts=ts)
    assert decayed_magnitude(sh, ts - timedelta(seconds=100)) == pytest.approx(0.8)
    assert decayed_magnitude(sh, ts) == pytest.approx(0.8)


def test_decayed_magnitude_zero_halflife_drops_instantly():
    ts = datetime.now(UTC)
    sh = _shock(magnitude=0.8, decay_halflife_s=0.0, ts=ts)
    assert decayed_magnitude(sh, ts + timedelta(seconds=1)) == 0.0


def test_decayed_magnitude_monotonic_decreasing():
    ts = datetime.now(UTC)
    sh = _shock(magnitude=0.9, decay_halflife_s=600.0, ts=ts)
    v1 = decayed_magnitude(sh, ts + timedelta(seconds=300))
    v2 = decayed_magnitude(sh, ts + timedelta(seconds=1200))
    assert 0.0 <= v2 < v1 < sh.magnitude


# ---- Streaming (offline + scenario) ------------------------------------------------

@pytest.mark.asyncio
async def test_stream_offline_scenario_yields_states_and_shocks():
    player = ScenarioPlayer.from_jsonl(SCENARIO)
    feed = SentimentFeed(mode="offline", scenario=player)
    kinds = set()
    async for item in feed.stream(["BTC", "AAPL"], from_ts=player.start_ts, step_s=300.0):
        kinds.add(type(item).__name__)
    assert "SentimentState" in kinds
    assert "ShockEvent" in kinds


@pytest.mark.asyncio
async def test_stream_offline_scenario_terminates():
    player = ScenarioPlayer.from_jsonl(SCENARIO)
    feed = SentimentFeed(mode="offline", scenario=player)
    count = 0
    async for _ in feed.stream(["BTC"], from_ts=player.start_ts, step_s=300.0):
        count += 1
        assert count < 10_000  # sonsuz döngü koruması
    assert count > 0


@pytest.mark.asyncio
async def test_stream_offline_without_scenario_single_snapshot():
    feed = SentimentFeed(mode="offline")
    items = [item async for item in feed.stream(["BTC", "FED"])]
    assert len(items) == 2
    assert all(isinstance(i, SentimentState) for i in items)


@pytest.mark.asyncio
async def test_stream_respects_max_steps():
    player = ScenarioPlayer.from_jsonl(SCENARIO)
    feed = SentimentFeed(mode="offline", scenario=player)
    items = [
        item
        async for item in feed.stream(["BTC"], from_ts=player.start_ts, step_s=60.0, max_steps=2)
    ]
    assert len(items) >= 1


# ---- Senaryo şema doğrulama ---------------------------------------------------------

def test_broken_scenario_line_gives_clear_error(tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"t": 0, "type": "shock", "kind": "not_a_kind", "entity": "BTC"}\n')
    with pytest.raises(ValueError, match=r"1:"):
        ScenarioPlayer.from_jsonl(bad)


def test_broken_scenario_missing_required_field(tmp_path):
    bad = tmp_path / "bad2.jsonl"
    bad.write_text('{"t": 0, "type": "sentiment"}\n')  # entity eksik
    with pytest.raises(ValueError, match=r"1:"):
        ScenarioPlayer.from_jsonl(bad)


def test_broken_scenario_invalid_json(tmp_path):
    bad = tmp_path / "bad3.jsonl"
    bad.write_text("{not valid json\n")
    with pytest.raises(ValueError, match=r"1:"):
        ScenarioPlayer.from_jsonl(bad)


def test_valid_scenario_still_works_with_comments_and_blanks(tmp_path):
    good = tmp_path / "good.jsonl"
    good.write_text(
        "# yorum satırı\n"
        "\n"
        '{"t": 0, "type": "shock", "kind": "panic", "entity": "BTC", "magnitude": 0.5}\n'
    )
    player = ScenarioPlayer.from_jsonl(good)
    # shocks_between alt sınır hariç (since, clock]; t=0 şokunu görmek için
    # başlangıçtan bir tık önceden sorgula (mevcut sınır davranışı korunur).
    shocks = player.shocks_between(player.start_ts - timedelta(seconds=1), player.end_ts)
    assert len(shocks) == 1 and shocks[0].kind == "panic"


def test_existing_fixture_scenario_unaffected():
    # Regresyon: mevcut fixture, yeni doğrulama katmanıyla da aynı sonucu üretmeli.
    player = ScenarioPlayer.from_jsonl(SCENARIO)
    shocks = player.shocks_between(player.start_ts, player.end_ts)
    assert any(s.kind == "narrative_shift" and s.entity == "BTC" for s in shocks)


# ---- HTTP köprüsü -------------------------------------------------------------------

def test_cas_sentiment_endpoint_returns_json_without_keys():
    with TestClient(app) as c:
        r = c.get("/v1/cas/sentiment/BTC")
        assert r.status_code == 200
        body = r.json()
        assert body["entity"] == "BTC"
        assert body["schema_version"] == CAS_SCHEMA_VERSION
        assert body["mode"] in ("live", "offline")


def test_cas_shocks_endpoint_returns_json_without_keys():
    with TestClient(app) as c:
        r = c.get("/v1/cas/shocks")
        assert r.status_code == 200
        body = r.json()
        assert "shocks" in body and isinstance(body["shocks"], list)
        assert body["schema_version"] == CAS_SCHEMA_VERSION


def test_cas_shocks_endpoint_accepts_since_param():
    with TestClient(app) as c:
        since = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        r = c.get("/v1/cas/shocks", params={"since": since})
        assert r.status_code == 200
