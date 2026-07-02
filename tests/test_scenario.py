"""Deterministik senaryo replay testleri — API/torch/DB gerektirmez."""
from __future__ import annotations

from datetime import timedelta

import pytest

from macro_sentiment.api.cas_contracts import SHOCK_KINDS
from macro_sentiment.api.scenario import ScenarioPlayer
from macro_sentiment.api.sentiment_feed import SentimentFeed
from tests.conftest import FIXTURES

SCENARIO = FIXTURES / "scenario.jsonl"


def test_loads_and_is_deterministic():
    p1 = ScenarioPlayer.from_jsonl(SCENARIO)
    p2 = ScenarioPlayer.from_jsonl(SCENARIO)
    s1 = p1.state_at("AAPL", p1.start_ts + timedelta(seconds=700))
    s2 = p2.state_at("AAPL", p2.start_ts + timedelta(seconds=700))
    assert s1 == s2


def test_explicit_sentiment_state_at():
    p = ScenarioPlayer.from_jsonl(SCENARIO)
    st = p.state_at("AAPL", p.start_ts + timedelta(seconds=700))  # t=600 sentiment
    assert st.polarity == pytest.approx(0.62)
    assert st.emotion["greed"] == pytest.approx(0.7)


def test_state_before_any_event_is_neutral():
    p = ScenarioPlayer.from_jsonl(SCENARIO)
    st = p.state_at("AAPL", p.start_ts)  # AAPL ilk olayı t=600
    assert st.polarity == 0.0 and st.intensity == 0.0


def test_explicit_shock_present():
    p = ScenarioPlayer.from_jsonl(SCENARIO)
    shocks = p.shocks_between(p.start_ts, p.end_ts)
    narrative = [s for s in shocks if s.kind == "narrative_shift" and s.entity == "BTC"]
    assert len(narrative) == 1
    assert narrative[0].magnitude == pytest.approx(0.7)
    assert all(s.kind in SHOCK_KINDS for s in shocks)


def test_news_derives_panic_shock_for_btc():
    p = ScenarioPlayer.from_jsonl(SCENARIO)
    shocks = p.shocks_between(p.start_ts, p.end_ts)
    assert any(s.kind == "panic" and s.entity == "BTC" for s in shocks)


def test_shocks_window_is_exclusive_inclusive():
    p = ScenarioPlayer.from_jsonl(SCENARIO)
    # t=900 şoku (start, start+900] içinde; (start+900, ...] içinde değil.
    inside = p.shocks_between(p.start_ts, p.start_ts + timedelta(seconds=900))
    after = p.shocks_between(p.start_ts + timedelta(seconds=900), p.end_ts)
    assert any(s.ts == p.start_ts + timedelta(seconds=900) for s in inside)
    assert all(s.ts != p.start_ts + timedelta(seconds=900) for s in after)


def test_feed_replay_integration():
    p = ScenarioPlayer.from_jsonl(SCENARIO)
    feed = SentimentFeed(mode="offline", scenario=p)
    start = feed.now
    feed.advance(1300)  # tüm olayların ötesine
    st = feed.latest("AAPL")
    # t=1200 news (bullish) en güncel AAPL durumu.
    assert st.polarity > 0
    shocks = feed.shocks(start)
    assert any(s.entity == "BTC" for s in shocks)
