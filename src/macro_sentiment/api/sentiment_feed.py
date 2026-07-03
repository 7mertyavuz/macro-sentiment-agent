"""SentimentFeed — cas-market-simulator adaptörü (Katman 1 + Katman 2 köprüsü).

Bu sınıf `00-ORTAK-SOZLESME.md`'deki `SentimentFeed` protokolünü uygular ve
reponun iç modellerini (`SentimentScore`/`Signal`/`WindowAggregate`) sözleşme
tiplerine (`SentimentState`/`ShockEvent`) çevirir. Çekirdek boru hattına
(Faz 0–5) dokunmaz; yalnızca üstüne oturan bir adaptördür.

Modlar
------
* ``offline`` — harici API/DB/anahtar gerekmez. İki alt-yol:
    - ``scenario`` verilirse: JSONL zaman çizelgesini *deterministik* oynatır.
    - verilmezse: varlık adından türetilen deterministik sentetik durum üretir.
  Her iki yol da hiçbir ağ çağrısı yapmaz (simülasyon/replay için birinci sınıf).
* ``live`` — DB'deki gerçek skor/sinyalleri kullanır (SentimentRepository +
  SignalRepository), pencere toplar ve sözleşme tiplerine çevirir.

Önemli çeviri kuralları
-----------------------
* ``fed_tone`` işaret çevrimi: sözleşmede hawkish=+1/dovish=-1; iç kural ise
  ``polarity < 0``'ı hawkish sayar. Bu yüzden ``fed_tone = -mean_polarity``.
* Çift sayım: SentimentState *ham/temiz* duyarlılığı taşır; ağırlıklandırma
  kararı tüketen motora bırakılır (ön-ağırlık uygulanmaz).
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone

from ..signals.aggregator import WindowAggregate, aggregate
from .cas_contracts import SHOCK_KINDS, SentimentState, ShockEvent

# Sinyal tipinden şok yarılanma süresi (saniye). Panik hızlı söner, Fed tonu uzun.
DECAY_HALFLIFE_S: dict[str, float] = {
    "panic": 1800.0,          # 30 dk
    "euphoria": 2700.0,       # 45 dk
    "fed_tone": 14400.0,      # 4 saat
    "narrative_shift": 21600.0,  # 6 saat
}

# İç SignalType.value -> sözleşme ShockEvent.kind eşlemesi.
# ("breakout" sözleşmede karşılıksız; şok olarak enjekte edilmez.)
_SIGNAL_KIND_MAP: dict[str, str] = {
    "panic": "panic",
    "euphoria": "euphoria",
    "fed_tone": "fed_tone",
    "narrative": "narrative_shift",
}


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _run(coro):
    """Senkron sözleşme metotlarından async repo çağrısını köprüler."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Zaten bir olay döngüsü içindeysek ayrı bir döngüde çalıştır.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, coro).result()


def aggregate_to_state(agg: WindowAggregate, ts: datetime | None = None) -> SentimentState:
    """Bir WindowAggregate'i sözleşmedeki SentimentState'e çevirir."""
    src = dict(agg.source_breakdown or {})
    fed_tone: float | None = None
    if agg.entity == "FED" or "fed" in src:
        # İşaret çevrimi: iç konvansiyonda negatif polarite = hawkish (+1).
        base = src.get("fed", agg.mean_polarity)
        fed_tone = _clamp(-base, -1.0, 1.0)
    return SentimentState(
        entity=agg.entity,
        polarity=_clamp(agg.mean_polarity, -1.0, 1.0),
        intensity=_clamp(agg.mean_intensity, 0.0, 100.0),
        emotion={
            "fear": _clamp(agg.mean_fear, 0.0, 1.0),
            "greed": _clamp(agg.mean_greed, 0.0, 1.0),
            "uncertainty": _clamp(agg.mean_uncertainty, 0.0, 1.0),
        },
        confidence=_clamp(agg.mean_confidence, 0.0, 1.0),
        fed_tone=fed_tone,
        source_breakdown=src,
        ts=ts or datetime.now(timezone.utc),
    )


def _synthetic_state(entity: str, ts: datetime) -> SentimentState:
    """Varlık adından türetilen deterministik sentetik durum (API yok).

    Aynı (entity, dakika) için aynı çıktı — simülatör tekrarlanabilir deney yapar.
    """
    seed = f"{entity}|{ts.replace(second=0, microsecond=0).isoformat()}"
    h = hashlib.sha256(seed.encode()).digest()

    def unit(i: int) -> float:  # 0..1 deterministik
        return h[i] / 255.0

    polarity = round(2 * unit(0) - 1, 4)          # [-1,1]
    intensity = round(100 * unit(1), 2)           # 0..100
    fear = round(unit(2) * (1 if polarity < 0 else 0.4), 4)
    greed = round(unit(3) * (1 if polarity > 0 else 0.4), 4)
    uncertainty = round(unit(4), 4)
    confidence = round(0.4 + 0.6 * unit(5), 4)
    fed_tone = _clamp(-polarity, -1.0, 1.0) if entity == "FED" else None
    return SentimentState(
        entity=entity, polarity=polarity, intensity=intensity,
        emotion={"fear": fear, "greed": greed, "uncertainty": uncertainty},
        confidence=confidence, fed_tone=fed_tone,
        source_breakdown={"news": polarity}, ts=ts,
    )


class SentimentFeed:
    """Sözleşme uyumlu duyarlılık/şok akışı adaptörü.

    Parameters
    ----------
    mode:
        ``"offline"`` (varsayılan) veya ``"live"``.
    scenario:
        offline modda deterministik replay için bir ``ScenarioPlayer`` (veya
        ``from_jsonl`` ile yüklenmiş). Verilirse dahili saat senaryoyu oynatır.
    sent_repo / sig_repo:
        live modda kullanılacak repository'ler (test için enjekte edilebilir).
    window_size:
        live modda pencere başına çekilecek skor sayısı.
    strict_review:
        ``True`` ise (Faz 11) ``live`` modda ``"pending"``/``"rejected"``
        durumundaki sinyaller şok olarak enjekte edilmez — yalnızca onaylı
        (``"approved"``) veya hiç incelemeye girmemiş (``None`` — düşük etkili)
        sinyaller şoka çevrilir. Varsayılan ``False`` — geriye uyum (eski
        davranış: tüm sinyaller şok olur).
    """

    def __init__(
        self,
        mode: str = "offline",
        *,
        scenario=None,
        sent_repo=None,
        sig_repo=None,
        window_size: int = 50,
        strict_review: bool = False,
    ) -> None:
        if mode not in ("offline", "live"):
            raise ValueError(f"Geçersiz mod: {mode!r} (offline|live)")
        self.mode = mode
        self.scenario = scenario
        self.window_size = window_size
        self.strict_review = strict_review
        self._sent_repo = sent_repo
        self._sig_repo = sig_repo
        # Replay saati: offline+scenario modunda ilerletilir.
        self._clock: datetime = scenario.start_ts if scenario is not None else datetime.now(timezone.utc)

    # ---- Replay saat kontrolü (yalnızca offline+scenario) -----------------
    @property
    def now(self) -> datetime:
        return self._clock

    def advance(self, seconds: float) -> datetime:
        """Dahili replay saatini ``seconds`` kadar ilerletir ve yeni zamanı döndürür."""
        self._clock = self._clock + timedelta(seconds=seconds)
        return self._clock

    def seek(self, ts: datetime) -> None:
        """Replay saatini mutlak bir zamana taşır."""
        self._clock = ts

    # ---- Sözleşme: SentimentFeed protokolü --------------------------------
    def latest(self, entity: str) -> SentimentState:
        if self.mode == "live":
            scores = _run(self._repo_sent().recent_for_entity(entity, limit=self.window_size))
            agg = aggregate(entity, scores, window="recent")
            return aggregate_to_state(agg, ts=datetime.now(timezone.utc))
        # offline
        if self.scenario is not None:
            return self.scenario.state_at(entity, self._clock)
        return _synthetic_state(entity, self._clock)

    def shocks(self, since: datetime) -> list[ShockEvent]:
        if self.mode == "live":
            signals = _run(self._repo_sig().query(since=since, limit=200))
            if self.strict_review:
                signals = [s for s in signals if s.review_status in (None, "approved")]
            out: list[ShockEvent] = []
            for sig in sorted(signals, key=lambda s: s.created_at):
                kind = _SIGNAL_KIND_MAP.get(sig.type.value)
                if kind is None:  # sözleşme dışı (örn. breakout) → enjekte etme
                    continue
                out.append(
                    ShockEvent(
                        kind=kind,
                        entity=sig.entity,
                        magnitude=_clamp(sig.severity / 100.0, 0.0, 1.0),
                        decay_halflife_s=DECAY_HALFLIFE_S[kind],
                        ts=sig.created_at,
                        meta={"severity": sig.severity, "direction": sig.direction},
                    )
                )
            return out
        # offline
        if self.scenario is not None:
            return self.scenario.shocks_between(since, self._clock)
        return []

    # ---- Sözleşme: streaming (push) ----------------------------------------
    async def stream(
        self,
        entities: list[str],
        from_ts: datetime | None = None,
        *,
        step_s: float = 60.0,
        max_steps: int | None = None,
    ):
        """State/şok akışını yayınlayan async jeneratör (pull API'nin yanı sıra).

        * ``offline`` + ``scenario``: replay saatini ``step_s`` adımlarla
          senaryo sonuna kadar ilerletir; her adımda o adımda oluşan şokları ve
          ardından her varlık için güncel ``latest()`` durumunu yayınlar.
          Deterministik, ağ/uyku yok — ``max_steps`` verilmezse senaryo bitince durur.
        * ``offline`` + senaryosuz: tek kare sentetik durum yayınlar, sonra durur
          (sonsuz sentetik akış anlamsız — deterministik snapshot yeterli).
        * ``live``: ``from_ts``'ten itibaren periyodik olarak (``step_s`` saniyede
          bir, ``asyncio.sleep`` ile) yeni şokları + güncel durumları yayınlar.
          ``max_steps`` verilmezse çağıran taraf jeneratörü kapatana kadar sürer.
        """
        since = from_ts if from_ts is not None else self._clock

        if self.mode == "offline" and self.scenario is not None:
            self.seek(since)
            end = self.scenario.end_ts
            prev = self._clock
            steps = 0
            while self._clock < end:
                now = self.advance(step_s)
                for sh in self.shocks(prev):
                    yield sh
                for entity in entities:
                    yield self.latest(entity)
                prev = now
                steps += 1
                if max_steps is not None and steps >= max_steps:
                    return
            return

        if self.mode == "offline":
            # Senaryosuz: sonsuz sentetik akış anlamsız; tek deterministik kare.
            for entity in entities:
                yield self.latest(entity)
            return

        # live
        prev = since
        steps = 0
        while True:
            now = datetime.now(timezone.utc)
            for sh in self.shocks(prev):
                yield sh
            for entity in entities:
                yield self.latest(entity)
            prev = now
            steps += 1
            if max_steps is not None and steps >= max_steps:
                return
            await asyncio.sleep(step_s)

    # ---- Yardımcılar ------------------------------------------------------
    def _repo_sent(self):
        if self._sent_repo is None:
            from ..storage.repositories import SentimentRepository

            self._sent_repo = SentimentRepository()
        return self._sent_repo

    def _repo_sig(self):
        if self._sig_repo is None:
            from ..storage.repositories import SignalRepository

            self._sig_repo = SignalRepository()
        return self._sig_repo


__all__ = ["SentimentFeed", "aggregate_to_state", "DECAY_HALFLIFE_S", "SHOCK_KINDS"]
