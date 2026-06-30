"""API uç noktası smoke testleri (TestClient)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from macro_sentiment.api.main import app


def test_health_and_dashboard_and_endpoints():
    with TestClient(app) as c:
        assert c.get("/health").json()["status"] == "ok"
        assert "Macro-Sentiment" in c.get("/").text
        assert c.get("/v1/signals").status_code == 200
        body = c.get("/v1/sentiment/BTC").json()
        assert body["entity"] == "BTC" and "count" in body
