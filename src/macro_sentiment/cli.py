"""Macro-Sentiment Agent — komut satırı arayüzü.

Örnekler:
  python -m macro_sentiment.cli run                                  # canlı RSS
  python -m macro_sentiment.cli demo --sample tests/fixtures/sample_feed.xml
  python -m macro_sentiment.cli scores --entity AAPL
  python -m macro_sentiment.cli signals                              # üretilen sinyaller
  python -m macro_sentiment.cli feed --entities FED BTC AAPL         # CAS SentimentState
  python -m macro_sentiment.cli replay --scenario tests/fixtures/scenario.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .core.config import get_settings
from .ingestion.dedup import get_deduplicator
from .ingestion.queue import get_queue
from .nlp.factory import build_sentiment_model
from .api.alerts import build_dispatcher
from .signals.engine import SignalEngine
from .sources.registry import active_connectors
from .sources.rss_connector import RSSConnector
from .storage.db import dispose_db, init_db
from .storage.repositories import DocumentRepository, SentimentRepository, SignalRepository
from .worker.tasks import RAW_TOPIC, ingest_all_once, nlp_drain
from .backtest.dataset import load_jsonl
from .backtest.harness import run_backtest


def _model():
    return build_sentiment_model(get_settings())


async def _score_and_signal(sent_repo: SentimentRepository) -> None:
    """NLP sonrası: sinyal motorunu (uyarı dağıtıcıyla) çalıştırır.

    Eşiği geçen sinyaller yapılandırılmış kanallara (console + webhook/Slack/
    Telegram) gönderilir; konsol çıktısı ConsoleAlert'ten gelir.
    """
    entities = await sent_repo.distinct_entities()
    dispatcher = build_dispatcher(get_settings())
    engine = SignalEngine(sent_repo=sent_repo, sig_repo=SignalRepository(), dispatcher=dispatcher)
    sigs = await engine.evaluate_entities(entities)
    print(f"[signal] {len(sigs)} sinyal üretildi ({len(entities)} varlık değerlendirildi)")


async def _ingest_docs(docs, dedup, doc_repo, queue) -> int:
    new = 0
    for doc in docs:
        if await dedup.is_duplicate(doc):
            continue
        await dedup.mark_seen(doc)
        await doc_repo.save(doc)
        await queue.publish(RAW_TOPIC, doc.model_dump(mode="json"))
        new += 1
    return new


async def cmd_run(args) -> None:
    s = get_settings()
    await init_db()
    queue, dedup = get_queue(), get_deduplicator()
    doc_repo, sent_repo = DocumentRepository(), SentimentRepository()
    since = datetime.now(timezone.utc) - timedelta(hours=args.hours)

    # Faz 8: RSS her zaman etkin; NewsAPI/Fed yalnızca ilgili anahtar varsa eklenir.
    connectors = active_connectors(s)
    print(f"[kaynak] etkin: {', '.join(c.source_id for c in connectors)}")
    new = await ingest_all_once(connectors, queue, dedup, doc_repo, since)
    print(f"[ingest] {new} yeni belge kuyruğa alındı")
    scored = await nlp_drain(queue, _model(), sent_repo)
    print(f"[nlp]    {scored} skor üretildi (model={_model().model_version})")
    await _score_and_signal(sent_repo)
    await dispose_db()


async def cmd_demo(args) -> None:
    await init_db()
    queue, dedup = get_queue(), get_deduplicator()
    doc_repo, sent_repo = DocumentRepository(), SentimentRepository()

    raw_xml = Path(args.sample).read_bytes()
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    docs = RSSConnector(feeds=[]).parse(raw_xml, feed_url=args.sample, since=epoch)
    print(f"[parse]  örnek feed'den {len(docs)} belge ayrıştırıldı")

    new = await _ingest_docs(docs, dedup, doc_repo, queue)
    print(f"[ingest] {new} belge kuyruğa alındı")
    scored = await nlp_drain(queue, _model(), sent_repo)
    print(f"[nlp]    {scored} skor üretildi (model={_model().model_version})")
    await _score_and_signal(sent_repo)
    await dispose_db()


async def cmd_scores(args) -> None:
    await init_db()
    rows = await SentimentRepository().recent_for_entity(args.entity, limit=args.limit)
    if not rows:
        print(f"'{args.entity}' için skor bulunamadı.")
    for s in rows:
        print(
            f"  {s.created_at:%Y-%m-%d %H:%M}  {s.entity:6s}  pol={s.polarity:+.2f}  "
            f"yoğ={s.intensity:5.1f}  güven={s.confidence:.2f}  korku={s.emotion.fear:.2f}  [{s.model_version}]"
        )
    await dispose_db()


async def cmd_signals(args) -> None:
    await init_db()
    rows = await SignalRepository().query(entity=args.entity, limit=args.limit)
    if not rows:
        print("Sinyal bulunamadı.")
    for s in rows:
        print(f"  {s.created_at:%Y-%m-%d %H:%M}  [{s.type.value:8s}] şiddet={s.severity:5.1f}  {s.headline}")
    await dispose_db()


async def cmd_backtest(args) -> None:
    records = load_jsonl(args.dataset)
    report = await run_backtest(records, _model())
    m = report.metrics
    print(f"[backtest] {m.n} kayıt | accuracy={m.accuracy:.2%}")
    print(f"{'etiket':10s} {'precision':>9s} {'recall':>7s} {'f1':>6s} {'n':>4s}")
    for lab, lm in sorted(m.per_label.items()):
        print(f"{lab:10s} {lm.precision:9.2f} {lm.recall:7.2f} {lm.f1:6.2f} {lm.support:4d}")
    if args.verbose:
        print("\n--- yanlışlar ---")
        for d in report.details:
            if not d["correct"]:
                print(f"  {d['id']}: tahmin={d['predicted']} beklenen={d['expected']}")


async def cmd_feed(args) -> None:
    """SentimentFeed adaptörünün ürettiği SentimentState'i gösterir (CAS köprüsü)."""
    from .api.sentiment_feed import SentimentFeed

    if args.mode == "live":
        await init_db()
    feed = SentimentFeed(mode=args.mode)
    for entity in args.entities:
        st = feed.latest(entity)
        ft = "None" if st.fed_tone is None else f"{st.fed_tone:+.2f}"
        print(
            f"  {entity:6s}  pol={st.polarity:+.2f}  yoğ={st.intensity:5.1f}  "
            f"güven={st.confidence:.2f}  korku={st.emotion['fear']:.2f}  "
            f"açgöz={st.emotion['greed']:.2f}  belirsiz={st.emotion['uncertainty']:.2f}  "
            f"fed_tone={ft}  kaynak={st.source_breakdown}"
        )
    if args.mode == "live":
        await dispose_db()


async def cmd_replay(args) -> None:
    """JSONL senaryosunu deterministik oynatır; adım adım state + şok basar (API yok)."""
    from .api.scenario import ScenarioPlayer
    from .api.sentiment_feed import SentimentFeed

    player = ScenarioPlayer.from_jsonl(args.scenario)
    feed = SentimentFeed(mode="offline", scenario=player)
    entities = args.entities or ["FED", "BTC", "AAPL"]
    prev = feed.now
    total_s = (player.end_ts - player.start_ts).total_seconds()
    steps = max(1, int(total_s // args.step) + 1)
    print(f"[replay] senaryo {total_s:.0f}s | adım={args.step}s | {steps} kare")
    for _ in range(steps):
        now = feed.advance(args.step)
        for sh in feed.shocks(prev):
            print(f"  t+{(sh.ts - player.start_ts).total_seconds():5.0f}s  ŞOK [{sh.kind:15s}] "
                  f"{sh.entity:6s} mag={sh.magnitude:.2f} half={sh.decay_halflife_s:.0f}s")
        for entity in entities:
            st = feed.latest(entity)
            if st.polarity == 0.0 and st.intensity == 0.0:
                continue
            print(f"  t+{(now - player.start_ts).total_seconds():5.0f}s  {entity:6s} "
                  f"pol={st.polarity:+.2f} yoğ={st.intensity:5.1f}")
        prev = now


def main() -> None:
    p = argparse.ArgumentParser(prog="macro_sentiment.cli")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run", help="Canlı kaynaklardan uçtan uca çalıştır")
    pr.add_argument("--hours", type=int, default=24)
    pr.set_defaults(func=cmd_run)

    pd = sub.add_parser("demo", help="Çevrimdışı örnek feed ile demo")
    pd.add_argument("--sample", required=True)
    pd.set_defaults(func=cmd_demo)

    ps = sub.add_parser("scores", help="Bir varlığın skorlarını listele")
    ps.add_argument("--entity", default="MARKET")
    ps.add_argument("--limit", type=int, default=20)
    ps.set_defaults(func=cmd_scores)

    pg = sub.add_parser("signals", help="Üretilmiş sinyalleri listele")
    pg.add_argument("--entity", default=None)
    pg.add_argument("--limit", type=int, default=20)
    pg.set_defaults(func=cmd_signals)

    pb = sub.add_parser("backtest", help="Etiketli veriyle sinyal isabetini ölç")
    pb.add_argument("--dataset", required=True, help="Etiketli JSONL dosyası")
    pb.add_argument("--verbose", action="store_true")
    pb.set_defaults(func=cmd_backtest)

    pf = sub.add_parser("feed", help="CAS SentimentFeed (SentimentState) çıktısını göster")
    pf.add_argument("--entities", nargs="+", default=["FED", "BTC", "AAPL"])
    pf.add_argument("--mode", choices=["offline", "live"], default="offline")
    pf.set_defaults(func=cmd_feed)

    prp = sub.add_parser("replay", help="JSONL senaryosunu deterministik oynat (CAS)")
    prp.add_argument("--scenario", required=True, help="Senaryo JSONL dosyası")
    prp.add_argument("--step", type=float, default=300.0, help="Kare adımı (saniye)")
    prp.add_argument("--entities", nargs="+", default=None)
    prp.set_defaults(func=cmd_replay)

    args = p.parse_args()
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
