"""Prometheus metrikleri — çekme gecikmesi, kuyruk derinliği, LLM token maliyeti, sinyal/dk.

TODO(Faz 1): prometheus_client Counter/Histogram tanımları + /metrics endpoint.
"""
from __future__ import annotations

# Önerilen metrikler:
#   msa_documents_fetched_total{source}
#   msa_inference_seconds{model}
#   msa_llm_tokens_total{model}
#   msa_signals_emitted_total{type}
#   msa_queue_depth{topic}
