"""nlp/spam_filter.py testleri (Faz 9) — saf fonksiyonlar, ağ/durum bağımlılığı yok."""
from __future__ import annotations

from datetime import datetime, timezone

from macro_sentiment.core.models import RawDocument, SourceType
from macro_sentiment.nlp.spam_filter import evaluate, filter_spam

UTC = timezone.utc
NOW = datetime(2026, 7, 1, tzinfo=UTC)


def _doc(body: str, *, doc_id: str = "d1", raw_meta: dict | None = None) -> RawDocument:
    return RawDocument(
        id=doc_id,
        source="social:stocktwits",
        source_type=SourceType.SOCIAL,
        body=body,
        published_at=NOW,
        fetched_at=NOW,
        content_hash="x" * 64,
        raw_meta=raw_meta or {},
    )


def test_hard_bot_flagged_new_account_no_followers():
    doc = _doc("$AAPL to the moon!", raw_meta={"author_account_age_days": 0.5, "author_followers": 1})
    v = evaluate(doc)
    assert v.is_bot is True
    assert v.reasons


def test_established_account_not_bot():
    doc = _doc("$AAPL earnings look solid this quarter", raw_meta={"author_account_age_days": 900, "author_followers": 5000})
    v = evaluate(doc)
    assert v.is_bot is False
    assert v.is_suspicious is False


def test_soft_suspicious_young_account_flagged_not_dropped():
    doc = _doc("$TSLA breaking out", raw_meta={"author_account_age_days": 10, "author_followers": 500})
    v = evaluate(doc)
    assert v.is_bot is False
    assert v.is_suspicious is True


def test_high_hashtag_ratio_flagged_suspicious():
    doc = _doc("#buy #now #moon #pump #AAPL #rocket $AAPL", raw_meta={"author_account_age_days": 900, "author_followers": 5000})
    v = evaluate(doc)
    assert v.is_suspicious is True


def test_no_meta_defaults_to_not_bot_not_suspicious():
    doc = _doc("$AAPL neutral comment")
    v = evaluate(doc)
    assert v.is_bot is False
    assert v.is_suspicious is False


def test_duplicate_text_detected_across_batch():
    seen: set[str] = set()
    doc1 = _doc("Same exact message about $AAPL", doc_id="a")
    doc2 = _doc("same exact message about $AAPL", doc_id="b")  # sadece case farkı
    v1 = evaluate(doc1, seen_texts=seen)
    v2 = evaluate(doc2, seen_texts=seen)
    assert v1.is_duplicate is False
    assert v2.is_duplicate is True
    assert v2.is_bot is True


# ---- filter_spam() — akış seviyesinde ----------------------------------------------

def test_filter_spam_drops_hard_bots():
    bot = _doc("spam spam spam", doc_id="bot", raw_meta={"author_account_age_days": 0.1, "author_followers": 0})
    good = _doc("$AAPL solid quarter", doc_id="good", raw_meta={"author_account_age_days": 900, "author_followers": 1000})
    out = filter_spam([bot, good])
    ids = [d.id for d in out]
    assert "bot" not in ids
    assert "good" in ids


def test_filter_spam_tags_suspicious_without_dropping():
    borderline = _doc("$TSLA thoughts?", doc_id="b1", raw_meta={"author_account_age_days": 5, "author_followers": 200})
    out = filter_spam([borderline])
    assert len(out) == 1
    assert out[0].raw_meta.get("spam_suspicious") is True


def test_filter_spam_drops_duplicates_keeps_first():
    d1 = _doc("Buy $AAPL now", doc_id="d1")
    d2 = _doc("buy $aapl now", doc_id="d2")
    out = filter_spam([d1, d2])
    assert [d.id for d in out] == ["d1"]


def test_filter_spam_preserves_order_for_survivors():
    docs = [
        _doc("first $AAPL note", doc_id="1", raw_meta={"author_account_age_days": 900, "author_followers": 1000}),
        _doc("second $MSFT note", doc_id="2", raw_meta={"author_account_age_days": 900, "author_followers": 1000}),
        _doc("third $TSLA note", doc_id="3", raw_meta={"author_account_age_days": 900, "author_followers": 1000}),
    ]
    out = filter_spam(docs)
    assert [d.id for d in out] == ["1", "2", "3"]


def test_filter_spam_empty_list():
    assert filter_spam([]) == []
