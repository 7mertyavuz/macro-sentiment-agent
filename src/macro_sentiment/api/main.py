"""FastAPI uygulama giriş noktası.

Çalıştırma: uvicorn macro_sentiment.api.main:app --reload
  GET /                     → canlı dashboard
  GET /health
  GET /v1/signals, /v1/sentiment/{entity}
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from .. import __version__
from ..observability.logging import configure_logging
from ..storage.db import dispose_db, init_db
from .dashboard import DASHBOARD_HTML
from .routes import router as signals_router


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


@app.get("/", response_class=HTMLResponse, tags=["ui"])
async def dashboard() -> str:
    return DASHBOARD_HTML


@app.get("/health", tags=["system"])
async def health() -> dict:
    return {"status": "ok", "version": __version__}
