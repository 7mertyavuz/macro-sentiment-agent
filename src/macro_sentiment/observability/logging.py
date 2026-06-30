"""Yapılandırılmış loglama (structlog)."""
from __future__ import annotations

import logging

from ..core.config import get_settings


def configure_logging() -> None:
    """Uygulama genelinde log seviyesini ayarlar. TODO(Faz 1): structlog JSON işlemcileri."""
    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
