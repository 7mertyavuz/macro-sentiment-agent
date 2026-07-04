"""FastAPI uygulama giriş noktası.

Çalıştırma: uvicorn macro_sentiment.api.main:app --reload
  GET /                     → canlı dashboard
  GET /health
  GET /metrics              → Prometheus metrikleri (Faz 12)
  GET /v1/signals, /v1/sentiment/{entity}
  GET /v1/cas/sentiment/{entity}, /v1/cas/shocks?since=...
  GET /v1/review/pending, POST /v1/review/{id}/approve|reject
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse

from .. import __version__
from ..observability import metrics as obs_metrics
from ..observability.logging import configure_logging
from ..storage.db import dispose_db, init_db
from .dashboard import DASHBOARD_HTML
from .routes import cas_router, review_router, router as signals_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    await init_db()
    yield
    await dispose_db()


app = FastAPI(
    title="Macro-Sentiment Agent",
    version=__version__,
    description="Finansal duyarlılık sinyalleri API'si",
    lifespan=lifespan,
)
app.include_router(signals_router)
app.include_router(cas_router)
app.include_router(review_router)


@app.get("/", response_class=HTMLResponse, tags=["ui"])
async def dashboard() -> str:
    return DASHBOARD_HTML


@app.get("/health", tags=["system"])
async def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.get("/metrics", tags=["system"])
async def metrics() -> Response:
    payload, content_type = obs_metrics.render()
    return Response(content=payload, media_type=content_type)
