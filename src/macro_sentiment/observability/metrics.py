"""Prometheus metrikleri (Faz 12) - cekme, model cagrisi/maliyeti, sinyal, kuyruk derinligi.

``prometheus_client`` ile Counter/Histogram/Gauge tanimlanir; ``/metrics`` HTTP
ucu (``api/main.py``) bu modulun ``render()`` ciktisini Prometheus text
formatinda doner. Sayaclar kendi ``CollectorRegistry``'sinde toplanir (global
varsayilan registry'yi kirletmez) - testlerde her modul import edildiginde
sifirdan baslar.

Metrikler kasitli olarak *opsiyonel* enjeksiyon noktalaridir: boru hattinin
hicbir yerinde zorunlu degildir - olcum cagrisi atlansa bile sistem normal
calismaya devam eder.
"""
from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

REGISTRY = CollectorRegistry()

documents_fetched_total = Counter(
    "msa_documents_fetched_total",
    "Kaynak basina cekilen (yeni) belge sayisi",
    ["source"],
    registry=REGISTRY,
)

inference_seconds = Histogram(
    "msa_inference_seconds",
    "Model basina duyarlilik cikarim suresi (saniye)",
    ["model"],
    registry=REGISTRY,
)

llm_tokens_total = Counter(
    "msa_llm_tokens_total",
    "Model basina toplam LLM token kullanimi (maliyet vekili)",
    ["model", "kind"],
    registry=REGISTRY,
)

signals_emitted_total = Counter(
    "msa_signals_emitted_total",
    "Tip ve inceleme durumu basina yayinlanan sinyal sayisi",
    ["type", "review_status"],
    registry=REGISTRY,
)

queue_depth = Gauge(
    "msa_queue_depth",
    "Topic basina bekleyen mesaj sayisi",
    ["topic"],
    registry=REGISTRY,
)

source_fetch_errors_total = Counter(
    "msa_source_fetch_errors_total",
    "Kaynak basina basarisiz cekme turu sayisi",
    ["source"],
    registry=REGISTRY,
)


def render() -> tuple[bytes, str]:
    """Prometheus text-exposition formatinda (payload, content_type) dondurur."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


__all__ = [
    "REGISTRY",
    "documents_fetched_total",
    "inference_seconds",
    "llm_tokens_total",
    "signals_emitted_total",
    "queue_depth",
    "source_fetch_errors_total",
    "render",
]
