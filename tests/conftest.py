"""Pytest ortak ayarları — testler için izole SQLite DB ve memory backend."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

# Settings instantiate edilmeden ÖNCE ortamı sabitle.
_TMP_DB = Path(tempfile.gettempdir()) / "msa_test.db"
if _TMP_DB.exists():
    _TMP_DB.unlink()

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB}"
os.environ["QUEUE_BACKEND"] = "memory"
os.environ["USE_FINBERT"] = "false"  # testlerde torch yok → sözlük fallback

FIXTURES = Path(__file__).parent / "fixtures"
