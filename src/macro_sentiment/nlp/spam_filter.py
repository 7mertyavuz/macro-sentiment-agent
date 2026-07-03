"""Bot/spam sezgileri — sosyal medya akışı için gürültü yönetimi (Faz 9).

Gerçek bot tespiti (ML sınıflandırıcı, davranışsal graf analizi) kapsam dışı;
burada MVP sezgileri var: hesap yaşı, takipçi sayısı, kopya/near-duplicate
metin ve promosyon yoğunluğu (hashtag/mention oranı). Sezgiler ``raw_meta``
üzerinden okunur — connector'lar bu alanları platform payload'ından doldurur.

İki seviyeli davranış (roadmap: "şüpheli içeriği düşür veya güveni azalt"):
- **Sert bot** (çok yeni hesap + neredeyse hiç takipçi, veya kopya metin):
  akıştan tamamen düşürülür.
- **Şüpheli** (sınırda sezgiler): düşürülmez ama ``raw_meta["spam_suspicious"]
  = True`` ile işaretlenir; NLP katmanı isterse güveni azaltmak için kullanır.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.models import RawDocument

# Sert eşikler — bunların TÜMÜ sağlanırsa bot kabul edilir.
_HARD_MIN_ACCOUNT_AGE_DAYS = 2
_HARD_MAX_FOLLOWERS = 3

# Yumuşak (şüpheli) eşikler — herhangi biri sağlanırsa işaretlenir.
_SOFT_MIN_ACCOUNT_AGE_DAYS = 30
_SOFT_MIN_FOLLOWERS = 10
_SOFT_MAX_HASHTAG_RATIO = 0.3  # kelime başına hashtag oranı


@dataclass
class SpamVerdict:
    is_bot: bool           # sert eşik — akıştan düşürülmeli
    is_suspicious: bool    # yumuşak eşik — güven azaltılmalı
    is_duplicate: bool     # bu turda daha önce görülen (near-)aynı metin
    reasons: list[str]


def _hashtag_ratio(text: str) -> float:
    words = text.split()
    if not words:
        return 0.0
    tags = sum(1 for w in words if w.startswith("#") or w.startswith("@"))
    return tags / len(words)


def _normalized_text(text: str) -> str:
    """Kopya tespiti için kaba normalizasyon (boşluk/büyük-küçük harf)."""
    return " ".join(text.lower().split())


def evaluate(doc: RawDocument, *, seen_texts: set[str] | None = None) -> SpamVerdict:
    """Tek bir belge için bot/spam sezgilerini uygular.

    ``seen_texts`` verilirse (aynı fetch turundaki normalize metin kümesi),
    kopya/near-duplicate içerik de tespit edilir ve kümeye eklenir.
    """
    meta = doc.raw_meta or {}
    reasons: list[str] = []

    account_age_days = meta.get("author_account_age_days")
    followers = meta.get("author_followers")

    is_bot = False
    if account_age_days is not None and followers is not None:
        if account_age_days < _HARD_MIN_ACCOUNT_AGE_DAYS and followers <= _HARD_MAX_FOLLOWERS:
            is_bot = True
            reasons.append(f"yeni hesap ({account_age_days}g) + düşük takipçi ({followers})")

    is_suspicious = False
    if account_age_days is not None and account_age_days < _SOFT_MIN_ACCOUNT_AGE_DAYS:
        is_suspicious = True
        reasons.append(f"genç hesap ({account_age_days}g)")
    if followers is not None and followers < _SOFT_MIN_FOLLOWERS:
        is_suspicious = True
        reasons.append(f"az takipçi ({followers})")
    if _hashtag_ratio(doc.body) > _SOFT_MAX_HASHTAG_RATIO:
        is_suspicious = True
        reasons.append("yüksek hashtag/mention yoğunluğu")

    is_duplicate = False
    if seen_texts is not None:
        norm = _normalized_text(doc.body)
        if norm and norm in seen_texts:
            is_duplicate = True
            is_bot = True  # kopya metin sert eşiğe eşdeğer kabul edilir
            reasons.append("kopya/near-duplicate metin")
        elif norm:
            seen_texts.add(norm)

    return SpamVerdict(is_bot=is_bot, is_suspicious=is_suspicious, is_duplicate=is_duplicate, reasons=reasons)


def filter_spam(docs: list[RawDocument]) -> list[RawDocument]:
    """Sert botları/kopyaları düşürür; şüphelileri ``raw_meta`` içinde işaretler.

    Girdi sırası korunur. Saf fonksiyon — ağ veya durum bağımlılığı yok, bu
    yüzden testte deterministiktir.
    """
    seen_texts: set[str] = set()
    out: list[RawDocument] = []
    for doc in docs:
        verdict = evaluate(doc, seen_texts=seen_texts)
        if verdict.is_bot:
            continue
        if verdict.is_suspicious:
            new_meta = dict(doc.raw_meta or {})
            new_meta["spam_suspicious"] = True
            new_meta["spam_reasons"] = verdict.reasons
            doc = doc.model_copy(update={"raw_meta": new_meta})
        out.append(doc)
    return out


__all__ = ["SpamVerdict", "evaluate", "filter_spam"]
