"""Katman 3 — NLP & Sentiment motoru (sistemin kalbi).

Akış: preprocess → ner → router → (finbert | llm) → fusion → emotion → scored.events
Hibrit strateji: yerel FinBERT geniş hacmi tarar; LLM yalnızca nüans/yüksek-etki
metinlerinde devreye girer (maliyet kontrolü).
"""
