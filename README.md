# Macro-Sentiment Agent

Finansal haberleri, Fed kararlarını ve sosyal medyayı API'ler üzerinden okuyup NLP ile analiz eden ve piyasa duyarlılığı sinyalleri üreten otonom ajan.

> Mimari detaylar için: [`ARCHITECTURE.md`](./ARCHITECTURE.md)

## Durum

- **Faz 0** — iskelet + arayüz sözleşmeleri ✅
- **Faz 1 (MVP)** — RSS → NLP (FinBERT/fallback) → DB uçtan uca boru hattı ✅
- **Faz 2** — sinyal motoru (panic / euphoria / fed-tone, baseline z-skor, cooldown) ✅
- **Faz 3** — uyarı kanalları (webhook/Slack/Telegram), canlı dashboard ✅
- **Faz 4** — hibrit NLP: router (FinBERT↔LLM) + LLM hawkish/dovish ✅
- **Faz 5** — çoklu kaynak (Fed/sosyal canlı), backtest, kalibrasyon (planlı)

## Proje yapısı

```
src/macro_sentiment/
  core/        # veri modelleri, sözleşmeler (Protocol), config
  sources/     # Katman 1 — RSS (gerçek) + NewsAPI/Fed/social (stub)
  ingestion/   # Katman 2 — collector, dedup, kuyruk (InMemory + Redis)
  nlp/         # Katman 3 — preprocess, NER-lite, FinBERT + sözlük fallback
  signals/     # Katman 4 — aggregator, baseline, kural/anomali (Faz 2)
  api/         # Katman 5 — FastAPI REST (+ WebSocket/alerts iskeleti)
  storage/     # SQLAlchemy ORM + repository (SQLite dev / Postgres üretim)
  worker/      # boru hattı döngüleri
  cli.py       # komut satırı arayüzü
tests/         # birim + uçtan uca testler (+ fixtures/sample_feed.xml)
```

## Kurulum

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"        # temel + test
pip install -e ".[nlp]"        # FinBERT için (transformers + torch)
cp .env.example .env
```

## Kullanım

```bash
# Çevrimdışı demo (ağ/torch gerektirmez — sözlük fallback ile):
USE_FINBERT=false python -m macro_sentiment.cli demo --sample tests/fixtures/sample_feed.xml

# Üretilen skorları görüntüle:
python -m macro_sentiment.cli scores --entity AAPL

# Üretilen sinyalleri görüntüle:
python -m macro_sentiment.cli signals

# Canlı RSS'ten uçtan uca (ağ gerekir; FinBERT kuruluysa otomatik kullanılır):
python -m macro_sentiment.cli run --hours 24

# REST API + canlı dashboard:
uvicorn macro_sentiment.api.main:app --reload
#   GET /                     → dashboard (sinyaller + duyarlılık, 30sn'de yenilenir)
#   GET /health
#   GET /v1/sentiment/{entity}
#   GET /v1/signals?entity=BTC
```

Örnek demo çıktısı:

```
[parse]  örnek feed'den 3 belge ayrıştırıldı
[ingest] 3 belge kuyruğa alındı
[nlp]    3 skor üretildi (model=lexicon-fallback@1)
[signal] 3 sinyal üretildi
  ⚑ [euphoria] AAPL — coşku: olası tepe/geri çekilme
  ⚑ [panic   ] BTC — aşırı korku: panik satışı riski
  ⚑ [fed_tone] FED — hawkish (şahin) sinyali güçleniyor
```

## Sinyal tipleri

| Tip | Tetikleyici | Çıktı |
|---|---|---|
| `panic` | negatif polarite + yüksek korku | "aşırı korku: panik satışı riski" |
| `euphoria` | yüksek pozitif + açgözlülük | "coşku: olası tepe/geri çekilme" |
| `fed_tone` | FED ton kayması | "hawkish / dovish sinyali" |

Sinyaller anomali-tabanlıdır (baseline z-skoru) ve aynı sinyal cooldown
penceresinde tekrar yayınlanmaz. Eşikler backtest ile kalibre edilmelidir.

## NLP modları

`NLP_MODE` ile duyarlılık motoru seçilir:

| Mod | Davranış |
|---|---|
| `finbert` | Yalnızca yerel FinBERT/sözlük — hızlı, ucuz (varsayılan). |
| `llm` | Yalnızca LLM (Anthropic) — nüanslı, `LLM_API_KEY` gerekir. |
| `hybrid` | Router: rutin metin→FinBERT, Fed/uzun/yüksek-etki→LLM. Maliyet kontrolü. |

LLM yolu Fed metinlerinde **hawkish/dovish** duruşu sorar ve polariteye yansıtır. Anahtar yoksa veya LLM hata verirse otomatik FinBERT'e düşülür.

## Uyarılar

Şiddeti `ALERT_MIN_SEVERITY` eşiğini geçen sinyaller yapılandırılmış kanallara
gönderilir: konsol (her zaman), webhook, Slack, Telegram. `.env` ile etkinleştirin
(`SLACK_WEBHOOK_URL`, `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`, `ALERT_WEBHOOK_URL`).
Bir kanalın hatası diğerlerini etkilemez.

## Yapılandırma (.env)

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./macro_sentiment.db` | Dev SQLite; üretimde `postgresql+asyncpg://…` |
| `QUEUE_BACKEND` | `memory` | `memory` (dev) veya `redis` (üretim) |
| `USE_FINBERT` | `true` | `false` → sözlük fallback (torch gerekmez) |
| `FINBERT_MODEL` | `ProsusAI/finbert` | HuggingFace model adı |
| `RSS_FEEDS` | Yahoo/Investing | Çekilecek RSS akarları |

## Test

```bash
pip install -e ".[dev]"
pytest -q          # 15 test: RSS parse, NLP/fallback, storage, uçtan uca pipeline
```

> Not: SQLite, bazı ağ/sanal dosya sistemlerinde `disk I/O error` verebilir.
> Bu durumda `DATABASE_URL`'i yerel diske (örn. `/tmp/...`) veya Postgres'e yönlendirin.

## Hibrit NLP notu

FinBERT (yerel, hızlı) geniş hacmi tarar. `transformers`/`torch` kurulu değilse
veya `USE_FINBERT=false` ise sistem otomatik olarak sözlük tabanlı fallback'e
düşer; böylece boru hattı her ortamda çalışır. LLM katmanı (nüans/hawkish-dovish)
Faz 2'de eklenir.

## Not

Üretilen sinyaller bilgilendirme amaçlıdır; **yatırım tavsiyesi değildir**.
