"""LLM tabanlı duyarlılık — nüans, bağlam ve hawkish/dovish ekseni için.

Yapılandırılmış prompt + JSON çıktısı ile finans bağlamına sabitlenir. Fed
metinlerinde 'stance' (hawkish/dovish) sorulur ve polariteye yansıtılır.
JSON ayrıştırılamazsa sözlük fallback'e düşer. core.contracts.SentimentModel uygular.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..core.models import Emotion, Entity, RawDocument, SentimentScore, SourceType
from ..observability.metrics import inference_seconds
from . import lexicon_fallback
from .fusion import derive_emotion
from .llm_provider import LLMProvider
from .preprocess import clean_text

log = logging.getLogger(__name__)

_SYSTEM = (
    "Sen finansal metin duyarlılık analisti bir uzmansın. Verilen haber/açıklama "
    "metnini değerlendir ve SADECE şu şemada JSON döndür: "
    '{"polarity": -1..1, "intensity": 0..100, "confidence": 0..1, '
    '"fear": 0..1, "greed": 0..1, "uncertainty": 0..1, '
    '"stance": "hawkish|dovish|neutral"}. '
    "uncertainty, metindeki belirsizlik/tahmin/olası dilinin gücünü yansıtır "
    "(ör. kesin rakamlar → düşük, 'olabilir/muhtemelen/belirsiz' → yüksek). "
    "stance yalnızca para politikası/merkez bankası bağlamında anlamlıdır; "
    "hawkish negatif (sıkılaşma), dovish pozitif (gevşeme) eğilimindedir."
)

_MAX_CHARS = 4000


def _user_prompt(doc: RawDocument, entities: list[Entity]) -> str:
    ents = ", ".join(e.ticker or e.name for e in entities) or "MARKET"
    title = doc.title or ""
    body = clean_text(doc.body)[:_MAX_CHARS]
    return f"Varlık(lar): {ents}\nBaşlık: {title}\nMetin: {body}\n\nJSON:"


class LLMSentiment:
    """core.contracts.SentimentModel uygular."""

    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider
        self.model_version = f"llm-{getattr(provider, 'name', 'unknown')}@1"

    async def score(self, doc: RawDocument, entities: list[Entity]) -> list[SentimentScore]:
        try:
            with inference_seconds.labels(model=self.model_version).time():
                data = await self.provider.complete_json(_SYSTEM, _user_prompt(doc, entities))
        except Exception as exc:
            log.warning("LLM çağrısı/parse başarısız (%s); sözlük fallback.", exc)
            data = lexicon_fallback.score_text(clean_text(f"{doc.title or ''}. {doc.body}"))
            data["stance"] = "neutral"

        polarity = float(data.get("polarity", 0.0))
        # Fed bağlamında stance polariteyi netleştirir
        stance = str(data.get("stance", "neutral")).lower()
        if doc.source_type == SourceType.FED and stance in ("hawkish", "dovish"):
            sign = -1.0 if stance == "hawkish" else 1.0
            polarity = sign * max(abs(polarity), 0.4)

        now = datetime.now(timezone.utc)
        text_for_fallback = clean_text(f"{doc.title or ''}. {doc.body}")
        # LLM 'uncertainty' döndürmüşse onu kullan (modelin kendi değerlendirmesi
        # sözlük sezgisinden daha nüanslıdır); dönmemişse/parse hatasında metinden türet.
        uncertainty = (
            float(data["uncertainty"])
            if "uncertainty" in data
            else derive_emotion(polarity, float(data.get("intensity", abs(polarity) * 100)), text_for_fallback).uncertainty
        )
        emotion = Emotion(
            fear=float(data.get("fear", 0.0)),
            greed=float(data.get("greed", 0.0)),
            uncertainty=max(0.0, min(1.0, uncertainty)),
        )
        return [
            SentimentScore(
                doc_id=doc.id,
                entity=ent.ticker or ent.name,
                polarity=max(-1.0, min(1.0, polarity)),
                intensity=max(0.0, min(100.0, float(data.get("intensity", abs(polarity) * 100)))),
                emotion=emotion,
                confidence=max(0.0, min(1.0, float(data.get("confidence", 0.6)))),
                model_version=self.model_version,
                source_type=doc.source_type,
                created_at=now,
            )
            for ent in entities
        ]
