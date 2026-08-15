"""Konsey (council) — anonim akran değerlendirmesiyle çoklu-model füzyonu.

Desen kaynağı: [karpathy/llm-council](https://github.com/karpathy/llm-council).
Üç aşama:

  1. Soru tüm konsey üyelerine dağıtılır.
  2. **Her üye diğerlerinin cevabını KİMLİKLER GİZLENMİŞ halde sıralar.**
  3. Bir "başkan" (chairman) sıralamaları ve cevapları tek çıktıya sentezler.

Kritik fikir anonimleştirmedir: model kendi çıktısını tanıyamadığı için
kendini kayıramaz. Kimlikler görünürken modeller sistematik olarak kendi
çıktılarını üstün sıralar; anonimleştirme bu yanlılığı yapısal olarak keser.

SINIR — BU KATMAN SAYIYA DOKUNMAZ
----------------------------------
Konsey yalnızca **duyarlılık metni** üzerinde çalışır. Yön kararına, sinyal
eşiklerine veya risk hesabına karışmaz. MIMARI kuralı: LLM karar verici değil
açıklayıcı/yorumlayıcıdır. Burada üretilen tek şey, bir metnin polarite/
belirsizlik okumasının daha iyi bir uzlaşısıdır.

`llm_provider` yoksa modül tamamen deterministik çalışır ve mevcut sözlük/
FinBERT skorlarını anonim akran ağırlıklandırmasıyla birleştirir — yani ağsız
testlerde de gerçek bir davranışı vardır, boş bir kabuk değildir.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# Fikir ayrılığı bu eşiği aşarsa uzlaşı güveni sertçe kısılır.
HARD_DISAGREEMENT = 0.6


@dataclass
class Opinion:
    """Bir konsey üyesinin tek bir metin hakkındaki okuması."""

    member: str                 # model/kaynak adı — SIRALAMADA GİZLENİR
    polarity: float             # [-1, 1]
    confidence: float = 0.5     # [0, 1]
    uncertainty: float = 0.0    # [0, 1]
    rationale: str = ""
    meta: dict = field(default_factory=dict)


def anonymize(opinions: list[Opinion]) -> dict[str, Opinion]:
    """Görüşleri kimlikten arındırılmış kararlı etiketlere eşler.

    Etiket, üye adının hash'inden türetilir; böylece aynı konsey her koşuda
    aynı etiketleri alır (tekrarlanabilirlik) ama etiket modelin kim olduğunu
    ele vermez. Sıra da hash'e göre sabitlenir — liste sırasının kendisi bir
    ipucu olmasın.
    """
    labeled = {}
    for op in opinions:
        h = hashlib.sha256(op.member.encode("utf-8")).hexdigest()[:8]
        labeled[f"uye_{h}"] = op
    return dict(sorted(labeled.items()))


def peer_scores(anon: dict[str, Opinion]) -> dict[str, float]:
    """Anonim akran değerlendirmesi: her görüşe [0,1] güvenilirlik payı.

    Deterministik değerlendirme ölçütü (LLM olmadan da çalışır):
      * **uyum** — görüş, diğerlerinin medyanına ne kadar yakın?
      * **kendi güveni** — ama tek başına yeterli değil; yüksek güvenle
        aykırı duran bir görüş ödüllendirilmez, cezalandırılır.

    Aykırılığın kendisi kötü değildir; *aykırı + aşırı emin* kötüdür.
    """
    if not anon:
        return {}
    labels = list(anon)
    if len(labels) == 1:
        return {labels[0]: 1.0}

    scores = {}
    for lbl in labels:
        others = [anon[o].polarity for o in labels if o != lbl]
        med = sorted(others)[len(others) // 2]
        distance = abs(anon[lbl].polarity - med)
        agreement = max(0.0, 1.0 - distance / 2.0)      # polarite aralığı 2 birim
        conf = max(0.0, min(1.0, anon[lbl].confidence))
        # Aykırı + emin = ceza; aykırı + temkinli = nötr.
        penalty = distance * conf * 0.5
        scores[lbl] = max(0.0, agreement * (0.5 + 0.5 * conf) - penalty)

    total = sum(scores.values())
    if total <= 0:
        return {lbl: 1.0 / len(labels) for lbl in labels}
    return {lbl: v / total for lbl, v in scores.items()}


def chairman_synthesis(opinions: list[Opinion]) -> dict:
    """Konsey uzlaşısı: {polarity, confidence, uncertainty, spread, members, weights}.

    Fikir ayrılığı (spread) yüksekse güven SERT şekilde kısılır — üç model üç
    farklı şey söylüyorsa doğru cevap "emin değiliz"dir, ortalamaları değil.
    """
    if not opinions:
        return {"polarity": 0.0, "confidence": 0.0, "uncertainty": 1.0,
                "spread": 0.0, "members": 0, "weights": {}}

    anon = anonymize(opinions)
    weights = peer_scores(anon)

    polarity = sum(weights[lbl] * anon[lbl].polarity for lbl in anon)
    base_conf = sum(weights[lbl] * anon[lbl].confidence for lbl in anon)
    uncertainty = sum(weights[lbl] * anon[lbl].uncertainty for lbl in anon)

    pols = [op.polarity for op in opinions]
    spread = max(pols) - min(pols)

    confidence = base_conf * (1.0 - spread / 2.0)
    if spread > HARD_DISAGREEMENT:
        # Sert ayrılıkta uzlaşı, en temkinli üyenin altına indirilir.
        confidence = min(confidence, min(op.confidence for op in opinions) * 0.9)

    return {
        "polarity": round(max(-1.0, min(1.0, polarity)), 6),
        "confidence": round(max(0.0, min(1.0, confidence)), 6),
        "uncertainty": round(max(0.0, min(1.0, max(uncertainty, spread / 2.0))), 6),
        "spread": round(spread, 6),
        "members": len(opinions),
        "weights": {k: round(v, 6) for k, v in weights.items()},
    }


def council_route(doc, opinions: list[Opinion] | None = None,
                  *, spread_threshold: float = 0.4) -> bool:
    """LLM'e yönlendirilsin mi? Konsey uyuşmazlığına dayalı karar.

    Eski `route_to_llm` üç satırlık bir sezgiydi (`FED` ya da `len>2000`).
    Sorun: uzunluk zorlukla eşit değildir. Kısa ama çelişkili bir başlık,
    uzun ama rutin bir bültenden çok daha fazla yoruma muhtaçtır.

    Burada ucuz modeller ÖNCE konuşur; **birbirleriyle anlaşamazlarsa** pahalı
    yola çıkılır. Böylece maliyet, kolay vakalarda değil zor vakalarda ödenir.
    Görüş yoksa eski sezgiye düşülür (geriye uyum).
    """
    if not opinions:
        from .router import route_to_llm

        return route_to_llm(doc)

    pols = [op.polarity for op in opinions]
    spread = max(pols) - min(pols)
    weak = min(op.confidence for op in opinions) < 0.35
    return spread >= spread_threshold or weak
