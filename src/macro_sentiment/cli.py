"""Macro-Sentiment Agent — komut satırı arayüzü.

Örnekler:
  python -m macro_sentiment.cli run                                  # canlı RSS
  python -m macro_sentiment.cli demo --sample tests/fixtures/sample_feed.xml
  python -m macro_sentiment.cli scores --entity AAPL
  python -m macro_sentiment.cli signals                              # üretilen sinyaller
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
from .sources.rss_connector import RSSConnector
from .storage.db import dispose_db, init_db
from .storage.repositories import DocumentRepository, SentimentRepository, SignalRepository
from .worker.tasks import RAW_TOPIC, ingest_once, nlp_drain


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

    new = await ingest_once(RSSConnector(feeds=s.rss_feeds), queue, dedup, doc_repo, since)
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


def main() -> None:
    p = argparse.ArgumentParser(prog="macro_sentiment.cli")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run", help="Canlı RSS'ten uçtan uca çalıştır")
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

    args = p.parse_args()
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
