"""Sözlük tabanlı yedek duyarlılık skorlayıcı (torch gerektirmez).

FinBERT (transformers/torch) kurulu değilken pipeline'ın uçtan uca çalışmasını
sağlar. Üretim doğruluğu için değil; geliştirme/test ve dayanıklılık içindir.

Faz 7: olumsuzlama-lite (negation) polariteyi düzeltir, belirsizlik artık
``derive_emotion`` ile metinden türetilir (sabit 0.0 değil), sarkazm ipucu
tespit edilirse güven düşürülür.
"""
from __future__ import annotations

import re

from .fusion import derive_emotion, detect_sarcasm, negation_adjusted_polarity

_POS = {
    "beat", "beats", "surge", "surges", "soar", "rally", "gain", "gains", "profit",
    "growth", "upgrade", "bullish", "record", "strong", "rise", "rises", "jump",
    "optimism", "outperform", "boost",
}
_NEG = {
    "miss", "misses", "plunge", "plunges", "fall", "falls", "drop", "drops", "loss",
    "losses", "downgrade", "bearish", "weak", "decline", "slump", "fear", "fears",
    "crash", "selloff", "recession", "cut", "cuts", "warn", "warns", "default",
}
_FEAR = {"fear", "fears", "panic", "crash", "selloff", "plunge", "recession", "default"}
_GREED = {"surge", "soar", "rally", "record", "bullish", "euphoria", "boom"}

_WORD_RE = re.compile(r"[a-z]+")


def score_text(text: str) -> dict:
    """Metin için {polarity[-1,1], intensity[0,100], confidence, fear, greed,
    uncertainty} döndürür.

    Faz 7: ham polarite olumsuzlama-lite ile düzeltilir; belirsizlik metinden
    türetilir (``derive_emotion``); sarkazm ipucu bulunursa güven düşürülür.
    """
    words = _WORD_RE.findall(text.lower())
    if not words:
        return {
            "polarity": 0.0, "intensity": 0.0, "confidence": 0.3,
            "fear": 0.0, "greed": 0.0, "uncertainty": 0.5,
        }
    pos = sum(w in _POS for w in words)
    neg = sum(w in _NEG for w in words)
    fear = sum(w in _FEAR for w in words)
    greed = sum(w in _GREED for w in words)
    total = pos + neg
    polarity = 0.0 if total == 0 else (pos - neg) / total
    hits = total / max(len(words), 1)
    intensity = min(100.0, hits * 400)  # yoğunluk ~ duygu yüklü kelime oranı
    confidence = 0.3 + min(0.4, total * 0.1)  # MVP fallback için ılımlı güven
    n = max(len(words), 1)

    polarity = negation_adjusted_polarity(polarity, text)
    if detect_sarcasm(text):
        confidence *= 0.6

    emotion = derive_emotion(polarity, intensity, text)

    return {
        "polarity": round(polarity, 4),
        "intensity": round(intensity, 2),
        "confidence": round(confidence, 3),
        "fear": round(max(min(1.0, fear / n * 20), 0.0) if fear else emotion.fear, 3),
        "greed": round(max(min(1.0, greed / n * 20), 0.0) if greed else emotion.greed, 3),
        "uncertainty": emotion.uncertainty,
    }
