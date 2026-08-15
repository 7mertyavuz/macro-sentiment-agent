"""Fama-French 3 faktör proxy'si — makro akıştan stil eğilimi.

Fama & French'in bulgusu: hisse getirilerinin kesitsel farkı büyük ölçüde üç
faktörle açıklanır — piyasa (MKT), büyüklük (SMB: küçük eksi büyük) ve değer
(HML: yüksek eksi düşük defter/piyasa).

Gerçek faktörler getiri panelinden hesaplanır; bizim elimizde getiri paneli
YOK, haber/makro akışı var. Bu yüzden burada üretilen şey bir **proxy**dir:
"mevcut makro ortam hangi stili destekliyor?" sorusuna metinden çıkarılmış bir
eğilim skoru. Gerçek faktör yükü DEĞİLDİR ve öyle sunulmamalıdır.

MANTIK
------
* **SMB (küçük şirket eğilimi)** — risk iştahı ve gevşek finansal koşullarla
  artar. Küçük şirketler finansmana daha bağımlıdır; şahin Fed ve korku
  onları orantısız vurur.
* **HML (değer eğilimi)** — yüksek faiz / şahin ton değer lehinedir: büyüme
  hisselerinin değeri uzak vadeli nakit akışında toplandığı için iskonto
  oranına çok daha duyarlıdır.
* **MKT (piyasa yönü)** — genel polarite ve güven.

Çıktı `SentimentState.factor_tilt` alanına gider ve Heimdall'da H2 kesitsel
faktör grubuna beslenir.
"""
from __future__ import annotations

_TILT_KEYS = ("mkt", "smb", "hml")


def _clip(x: float) -> float:
    return max(-1.0, min(1.0, float(x)))


def factor_tilt(*, polarity: float = 0.0, fed_tone: float | None = None,
                fear: float = 0.0, greed: float = 0.0,
                uncertainty: float = 0.0, confidence: float = 1.0) -> dict:
    """Makro/duyarlılık okumalarından {mkt, smb, hml} eğilim skorları, her biri [-1,1].

    `fed_tone` konvansiyonu: **pozitif = şahin (hawkish)**. Bu işaret
    `cas_contracts` ile aynıdır; burada bir kez daha çevrilmez.

    `confidence` tüm çıktıyı ölçekler: emin olunmayan bir okuma stil eğilimi
    iddia etmemelidir.
    """
    tone = 0.0 if fed_tone is None else _clip(fed_tone)
    conf = max(0.0, min(1.0, float(confidence)))
    risk_appetite = _clip(polarity + 0.5 * (greed - fear))

    mkt = _clip(0.7 * _clip(polarity) + 0.3 * risk_appetite - 0.3 * tone)
    # Küçük şirketler: risk iştahını sever, şahin tonu ve belirsizliği sevmez.
    smb = _clip(0.6 * risk_appetite - 0.5 * tone - 0.3 * _clip(uncertainty))
    # Değer: şahin ton ve yüksek faiz ortamı lehine; coşkulu büyüme ortamında aleyhte.
    hml = _clip(0.7 * tone - 0.4 * risk_appetite)

    return {k: round(v * conf, 6) for k, v in (("mkt", mkt), ("smb", smb), ("hml", hml))}


def tilt_from_state(state) -> dict:
    """`SentimentState` benzeri bir nesneden eğilim hesaplar (tolerant okuma)."""
    emotion = getattr(state, "emotion", None) or {}
    return factor_tilt(
        polarity=float(getattr(state, "polarity", 0.0) or 0.0),
        fed_tone=getattr(state, "fed_tone", None),
        fear=float(emotion.get("fear", 0.0) or 0.0),
        greed=float(emotion.get("greed", 0.0) or 0.0),
        uncertainty=float(emotion.get("uncertainty", 0.0) or 0.0),
        confidence=float(getattr(state, "confidence", 1.0) or 0.0),
    )


def dominant_style(tilt: dict) -> str:
    """En baskın stil etiketi — okunabilir özet için."""
    if not tilt:
        return "neutral"
    key = max(_TILT_KEYS, key=lambda k: abs(float(tilt.get(k, 0.0))))
    v = float(tilt.get(key, 0.0))
    if abs(v) < 0.15:
        return "neutral"
    names = {"mkt": ("risk-on", "risk-off"), "smb": ("small-cap", "large-cap"),
             "hml": ("value", "growth")}
    return names[key][0 if v > 0 else 1]
