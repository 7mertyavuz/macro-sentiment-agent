"""Skor birleştirme + duygu yoğunluğu (Faz 7).

Birden çok modelin (FinBERT + LLM) çıktısını güven-ağırlıklı birleştirir ve
korku/coşku/belirsizlik boyutlarını üretir (ARCHITECTURE.md §6.1 adım 4-5).

Bu modül saf/deterministiktir: ağ/DB çağrısı yapmaz, yalnızca stdlib + mevcut
``core.models`` tiplerini kullanır.
"""
from __future__ import annotations

import re

from ..core.models import Emotion, SentimentScore

# ---- Belirsizlik / olumsuzlama / alay (sarkazm) sözlükleri --------------------------
# Sözlükler kasıtlı olarak küçük ve İngilizce+Türkçe karışık: finans haberlerinde
# her iki dilde de "may/might/could/belirsiz/olası" gibi kelimeler sık geçer.

_UNCERTAINTY_WORDS = {
    "may", "might", "could", "possibly", "uncertain", "uncertainty", "unclear",
    "volatile", "volatility", "risk", "risks", "risky", "unpredictable",
    "mixed", "cautious", "caution", "ambiguous", "unknown", "pending",
    "speculat", "rumor", "rumour", "reportedly", "allegedly", "tbd",
    "belirsiz", "belirsizlik", "olası", "olabilir", "riskli", "spekülasyon",
}

_NEGATION_WORDS = {
    "not", "no", "never", "without", "hardly", "barely", "n't",
    "isn't", "wasn't", "won't", "don't", "doesn't", "didn't", "aren't",
    "değil", "yok", "değildi",
}

_SARCASM_MARKERS = {
    "lol", "lmao", "rofl", "yeah right", "sure thing", "totally", "/s",
    "as if", "great job", "wow really",
}

_WORD_RE = re.compile(r"[a-zçğıöşü']+", re.IGNORECASE)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _words(text: str) -> list[str]:
    return _WORD_RE.findall((text or "").lower())


# ---- Negation-lite -------------------------------------------------------------------

def negation_adjusted_polarity(polarity: float, text: str, *, window: int = 3) -> float:
    """Basit olumsuzlama sezgisi: bir olumsuzlama kelimesinden sonraki ``window``
    kelime içinde duygu yüklü bir kelime varsa polaritenin işaretini yumuşat/çevir.

    Tam bir bağımlılık ayrıştırıcısı değil — kaba bir düzeltme katsayısıdır.
    Yalnızca olumsuzlama yoğunluğu belirginse (>=1 vuruş) etkin olur.
    """
    words = _words(text)
    if not words:
        return polarity
    hits = sum(1 for w in words if w in _NEGATION_WORDS or w.endswith("n't"))
    if hits == 0:
        return polarity
    # Yoğun olumsuzlama (metnin >%3'ü) işareti tersine çevirmeye yakın bir baskı uygular;
    # hafif olumsuzlama yalnızca büyüklüğü hafifletir.
    density = hits / max(len(words), 1)
    if density >= 0.08:
        return round(-polarity * 0.6, 4)
    return round(polarity * max(0.3, 1.0 - density * 4), 4)


def detect_sarcasm(text: str) -> bool:
    """Sosyal medyada sık görülen kaba sarkazm ipuçlarını yakalar (lite).

    Tam bir sınıflandırıcı değildir; yalnızca güveni düşürmek için bir bayrak.
    """
    if not text:
        return False
    lower = text.lower()
    if any(marker in lower for marker in _SARCASM_MARKERS):
        return True
    # Aşırı ünlem + tamamı büyük harf kelime kombinasyonu (ör. "GREAT!!! just great!!!")
    exclaim = text.count("!")
    caps_words = sum(1 for w in text.split() if len(w) > 2 and w.isupper())
    return exclaim >= 3 and caps_words >= 1


# ---- Duygu türetme --------------------------------------------------------------------

def derive_emotion(polarity: float, intensity: float, text: str) -> Emotion:
    """Polarite + yoğunluk + sözlük sinyallerinden duygu boyutları türetir.

    * ``fear``/``greed``: polarite yönü + yoğunluğa dayalı taban değer, metindeki
      belirsizlik/olumsuzlama yoğunluğuyla hafifçe ayarlanır.
    * ``uncertainty``: iki bileşenin karışımı —
        (a) metindeki belirsizlik kelime yoğunluğu (sözlük vuruşu),
        (b) düşük "kanaat" (conviction): polarite sıfıra yakın ve/veya yoğunluk
            düşükse model kararsız demektir → taban belirsizlik yüksek.
      Artık sabit 0.0 değil; her iki bileşen de metne/skora göre değişir.
    """
    words = _words(text)
    n = max(len(words), 1)

    unc_hits = sum(1 for w in words if any(w.startswith(u) for u in _UNCERTAINTY_WORDS))
    lexical_uncertainty = min(1.0, unc_hits / n * 12.0)

    conviction = _clamp01(abs(polarity)) * _clamp01(intensity / 100.0)
    baseline_uncertainty = 1.0 - conviction  # kanaat zayıfsa taban belirsizlik yüksek

    uncertainty = _clamp01(0.55 * lexical_uncertainty + 0.45 * baseline_uncertainty)

    fear_base = _clamp01(max(0.0, -polarity) * _clamp01(intensity / 100.0))
    greed_base = _clamp01(max(0.0, polarity) * _clamp01(intensity / 100.0))

    return Emotion(
        fear=round(fear_base, 4),
        greed=round(greed_base, 4),
        uncertainty=round(uncertainty, 4),
    )


# ---- Skor füzyonu ----------------------------------------------------------------------

def fuse(scores: list[SentimentScore]) -> SentimentScore:
    """Aynı (doc, entity) için birden çok model skorunu güven-ağırlıklı birleştir.

    * Ağırlıklı ortalama: her boyut (polarity/intensity/emotion) girdi
      güvenleriyle ağırlıklandırılır.
    * Çelişki tespiti: polarite işaretleri belirgin şekilde zıtsa (yayılım
      geniş), birleşik güven ``min(girdi güvenleri)``'nin altına çekilir —
      "modeller aynı fikirde değilse buna daha az güven" ilkesi.
    * Belirsizlik: çelişki payı, ağırlıklı ortalama belirsizliğe eklenir
      (modeller anlaşamıyorsa durum zaten belirsizdir).
    """
    if not scores:
        raise ValueError("fuse() en az bir SentimentScore gerektirir")
    if len(scores) == 1:
        return scores[0]

    weights = [max(s.confidence, 1e-6) for s in scores]
    wsum = sum(weights)

    def wavg(get) -> float:
        return sum(get(s) * w for s, w in zip(scores, weights)) / wsum

    polarity = wavg(lambda s: s.polarity)
    intensity = wavg(lambda s: s.intensity)
    fear = wavg(lambda s: s.emotion.fear)
    greed = wavg(lambda s: s.emotion.greed)
    uncertainty = wavg(lambda s: s.emotion.uncertainty)
    base_confidence = wavg(lambda s: s.confidence)

    polarities = [s.polarity for s in scores]
    spread = max(polarities) - min(polarities)          # [0, 2] aralığında
    disagreement = _clamp01(spread / 2.0)                # [0, 1]'e normalize

    confidence = base_confidence * (1.0 - disagreement)
    min_input_confidence = min(s.confidence for s in scores)
    if spread > 0.5:  # belirgin çelişki: işaretler ayrışıyor/uzak
        confidence = min(confidence, min_input_confidence * 0.9)

    versions = "+".join(sorted({s.model_version for s in scores}))

    return SentimentScore(
        doc_id=scores[0].doc_id,
        entity=scores[0].entity,
        polarity=round(max(-1.0, min(1.0, polarity)), 4),
        intensity=round(max(0.0, min(100.0, intensity)), 2),
        emotion=Emotion(
            fear=round(_clamp01(fear), 4),
            greed=round(_clamp01(greed), 4),
            uncertainty=round(_clamp01(max(uncertainty, disagreement)), 4),
        ),
        confidence=round(_clamp01(confidence), 4),
        model_version=f"fusion({versions})",
        source_type=scores[0].source_type,
        created_at=max(s.created_at for s in scores),
    )


__all__ = [
    "fuse",
    "derive_emotion",
    "negation_adjusted_polarity",
    "detect_sarcasm",
]
