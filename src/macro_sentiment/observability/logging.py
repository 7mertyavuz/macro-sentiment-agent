"""Yapilandirilmis loglama (structlog) + korelasyon kimlikleri (Faz 12).

``configure_logging()`` structlog'u JSON ciktisi verecek sekilde kurar (uretim
log toplayicilariyla - or. Loki/CloudWatch - uyumlu). Her log kaydina, varsa,
mevcut korelasyon kimligi (``correlation_id`` contextvar) otomatik eklenir -
bir istegin/belgenin islem hatti boyunca (fetch -> NLP -> sinyal) izini surmek
icin ``bind_correlation_id()`` ile ayarlanir.
"""
from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar

import structlog

from ..core.config import get_settings

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def new_correlation_id() -> str:
    """Kisa, okunabilir yeni bir korelasyon kimligi uretir."""
    return uuid.uuid4().hex[:16]


def bind_correlation_id(correlation_id: str | None = None) -> str:
    """Gecerli context icin korelasyon kimligini ayarlar (verilmezse yeni uretir)."""
    cid = correlation_id or new_correlation_id()
    _correlation_id.set(cid)
    return cid


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def _add_correlation_id(logger, method_name, event_dict):
    cid = _correlation_id.get()
    if cid is not None:
        event_dict["correlation_id"] = cid
    return event_dict


def configure_logging() -> None:
    """Uygulama genelinde structlog'u JSON ciktisi verecek sekilde kurar."""
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(message)s")

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_correlation_id,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None):
    """structlog bound logger dondurur (``configure_logging()`` cagrilmamissa da guvenlidir)."""
    return structlog.get_logger(name)


__all__ = [
    "configure_logging",
    "get_logger",
    "new_correlation_id",
    "bind_correlation_id",
    "get_correlation_id",
]
