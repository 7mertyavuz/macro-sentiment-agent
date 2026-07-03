"""HITL (human-in-the-loop) inceleme kuyruğu (Faz 11).

Yüksek-etki sinyaller (``severity >= REVIEW_SEVERITY_THRESHOLD``) dağıtım
öncesi insan onayı bekler: ``SignalEngine`` bunları DB'ye yazar (görünür kalır)
ama ``AlertDispatcher.dispatch()`` çağırmaz. Onay/ret ``api/routes.py``'deki
``/v1/review/*`` uçlarından yapılır; karar ``FeedbackRepository`` üzerinden
kalıcı geri besleme deposuna akar (bkz. ``signals/calibration.py``).
"""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from ..core.models import Signal

REVIEW_SEVERITY_THRESHOLD = 70.0

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"


def needs_review(signal: Signal, threshold: float = REVIEW_SEVERITY_THRESHOLD) -> bool:
    """Bir sinyalin dağıtım öncesi insan onayı gerektirip gerektirmediğini belirler."""
    return signal.severity >= threshold


class ReviewFeedback(BaseModel):
    """Bir inceleme kararının kalıcı kaydı — geri besleme/backtest için."""

    signal_id: str
    entity: str
    signal_type: str
    decision: str = Field(..., description="'approved' | 'rejected'")
    realized_label: str | None = Field(
        None, description="Gerçekleşen piyasa sonucu etiketi (opsiyonel, sonradan eklenebilir)"
    )
    reviewer: str | None = None
    note: str | None = None
    decided_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


__all__ = ["REVIEW_SEVERITY_THRESHOLD", "PENDING", "APPROVED", "REJECTED", "needs_review", "ReviewFeedback"]
