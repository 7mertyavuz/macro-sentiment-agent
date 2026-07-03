# Macro-Sentiment Agent

Finansal haberleri, Fed kararlarını ve sosyal medyayı API'ler üzerinden okuyup NLP ile analiz eden ve piyasa duyarlılığı sinyalleri üreten otonom ajan.

> Mimari detaylar için: [`ARCHITECTURE.md`](./ARCHITECTURE.md)

## Durum

- **Faz 0** — iskelet + arayüz sözleşmeleri ✅
- **Faz 1 (MVP)** — RSS → NLP (FinBERT/fallback) → DB uçtan uca boru hattı ✅
- **Faz 2** — sinyal motoru (panic / euphoria / fed-tone, baseline z-skor, cooldown) ✅
- **Faz 3** — uyarı kanalları (webhook/Slack/Telegram), canlı dashboard ✅
- **Faz 4** — hibrit NLP: router (FinBERT↔LLM) + LLM hawkish/dovish ✅
- **Faz 5** — backtest harness (precision/recall/F1, eşik kalibrasyonu) ✅
- **CAS köprüsü** — `SentimentFeed` adaptörü + `ShockEvent` akışı + deterministik senaryo replay'i (cas-market-simulator entegrasyonu) ✅
- **Faz 6** — CAS köprüsü sağlamlaştırma: serileştirme (`to_dict`/`from_dict` + `schema_version`), şok sönümleme, `stream()` push API, senaryo şema doğrulama, `/v1/cas/*` HTTP uçları ✅
- **Faz 7** — NLP kalitesi: skor füzyonu (`fuse`), gerçek `emotion.uncertainty` (artık sabit 0.0 değil), olumsuzlama-lite, sarkazm-lite ✅
- **Faz 8** — canlı kaynaklar I: NewsAPI (`/v2/everything`) + Fed basın açıklamaları (RSS, FOMC etiketleme), anahtar yoksa sessizce atlanır ✅
- **Faz 9** — canlı kaynaklar II: StockTwits (anahtarsız, açık onayla), bot/spam sezgileri, sosyal metin temizliği; Twitter/Reddit anahtarsızken sessizce atlanır ✅
- **Faz 10+** — TimescaleDB ölçek, HITL kalibrasyon döngüsü, gözlemlenebilirlik — bkz. [`docs/CAS-ROADMAP.md`](./docs/CAS-ROADMAP.md)

## Proje yapısı

```
src/macro_sentiment/
  core/        # veri modelleri, sözleşmeler (Protocol), config
  sources/     # Katman 1 — RSS + NewsAPI + Fed + StockTwits (gerçek); Twitter/Reddit (stub)
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

# Backtest — etiketli veriyle sinyal isabetini ölç:
python -m macro_sentiment.cli backtest --dataset tests/fixtures/backtest.jsonl --verbose

# Canlı kaynaklardan uçtan uca — RSS + (anahtar varsa) NewsAPI/Fed (ağ gerekir):
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

## Backtest

Etiketli geçmiş haberleri (`JSONL`) pipeline'dan geçirip üretilen sinyal tipini
beklenen etiketle karşılaştırır; etiket bazında precision/recall/F1 ve genel
accuracy raporlar. Eşik kalibrasyonunun temelidir.

```
[backtest] 6 kayıt | accuracy=100.00%
etiket     precision  recall     f1    n
panic           1.00    1.00   1.00    1
euphoria        1.00    1.00   1.00    2
```

Veri formatı: her satır `{id, title, body, source_type, entity, expected}` (`expected` ∈ panic|euphoria|fed_tone|none).

## cas-market-simulator entegrasyonu

Bu repo, hibrit CAS (Complex Adaptive System) planında iki rol üstlenir ve
`cas-market-simulator`'a **yalnızca veri tipleriyle** bağlanır (gevşek bağlılık;
simülatör paketine kod bağımlılığı yoktur). Sözleşme tipleri
[`api/cas_contracts.py`](./src/macro_sentiment/api/cas_contracts.py) içinde
ortak sözleşmeyle birebir yeniden tanımlıdır.

**Katman 1 — sentiment sensörü.** `SentimentFeed.latest(entity)` iç NLP+sinyal
çıktısını sözleşmedeki `SentimentState`'e çevirir (polarity, intensity,
emotion{fear,greed,uncertainty}, confidence, fed_tone, source_breakdown). Ham/temiz
duyarlılık verilir; ağırlıklandırma kararı tüketen indikatör motoruna bırakılır
(çift sayım engeli).

**Katman 2 — dışsal şok enjektörü.** `SentimentFeed.shocks(since)`, üretilen
sinyalleri (panic/euphoria/fed_tone/narrative) simülasyona enjekte edilebilir
`ShockEvent`'lere çevirir: `magnitude` (0..1, sinyal şiddetinden) ve
`decay_halflife_s` (panik 30 dk, fed_tone 4 saat, …).

> **fed_tone işaret çevrimi:** Sözleşmede hawkish `+1` / dovish `-1`. İç
> konvansiyon negatif polariteyi hawkish sayar; adaptör bu yüzden işareti çevirir.

### Modlar

| Mod | Davranış |
|---|---|
| `offline` (varsayılan) | Harici API/DB/anahtar yok. Senaryo verilirse deterministik replay; verilmezse varlık adından türetilen deterministik sentetik durum. |
| `live` | DB'deki gerçek skor/sinyalleri okur, pencere toplar ve sözleşme tiplerine çevirir. |

### Deterministik senaryo replay'i

Simülatörün tekrarlanabilir deney yapabilmesi için scriptli bir JSONL zaman
çizelgesi deterministik olarak oynatılır (hiçbir API çağrısı yok). Format,
`backtest` harness'iyle alan paylaşır.

```bash
# CAS SentimentState çıktısı (offline sentetik):
python -m macro_sentiment.cli feed --entities FED BTC AAPL

# Senaryoyu adım adım oynat (state + enjekte edilen şoklar):
python -m macro_sentiment.cli replay --scenario tests/fixtures/scenario.jsonl --step 300
```

Programatik kullanım:

```python
from macro_sentiment.api.scenario import ScenarioPlayer
from macro_sentiment.api.sentiment_feed import SentimentFeed

player = ScenarioPlayer.from_jsonl("tests/fixtures/scenario.jsonl")
feed = SentimentFeed(mode="offline", scenario=player)
feed.advance(600)                     # replay saatini ilerlet
state = feed.latest("AAPL")           # -> SentimentState
shocks = feed.shocks(player.start_ts) # -> list[ShockEvent]
```

**Senaryo JSONL formatı** — her satır bir olay; `t` = başlangıçtan saniye,
`type` ∈ `news | sentiment | shock`:

```jsonl
{"t": 0,   "type": "news",      "title": "Fed warns on inflation", "body": "...", "source_type": "fed", "entity": "FED"}
{"t": 300, "type": "news",      "title": "Bitcoin plunges", "body": "panic selloff...", "entity": "BTC"}
{"t": 600, "type": "sentiment", "entity": "AAPL", "polarity": 0.62, "intensity": 74, "greed": 0.7}
{"t": 900, "type": "shock",     "kind": "narrative_shift", "entity": "BTC", "magnitude": 0.7}
```

`news` olayları sözlük modeliyle skorlanır (deterministik); `sentiment`/`shock`
olayları doğrudan enjekte edilir.

## Test

```bash
pip install -e ".[dev]"
pytest -q          # 15 test: RSS parse, NLP/fallback, storage, uçtan uca pipeline
```

> Not: SQLite, bazı ağ/sanal dosya sistemlerinde `disk I/O error` verebilir.
> Bu durumda `DATABASE_URL`'i yerel diske (örn. `/tmp/...`) veya Postgres'e yönlendirin.

## CAS köprüsü — taşıma katmanı, streaming, HTTP uçları (Faz 6)

CAS köprüsü (yukarıdaki `SentimentFeed`/`ShockEvent`/senaryo replay) süreçler
arası **tüketilebilir** hale getirildi: simülatör muhtemelen ayrı bir
süreç/repo olarak çalışacağı için serileştirme, sönümleme, push API ve
HTTP uçları eklendi. Hiçbiri harici anahtar gerektirmez; `offline` yol
deterministik kalır.

**Serileştirme** — [`api/cas_transport.py`](./src/macro_sentiment/api/cas_transport.py)
`SentimentState`/`ShockEvent` için `to_dict()`/`from_dict()` round-trip sağlar;
her çıktı bir `schema_version` alanı taşır (şu an `"1.0"`). Bilinmeyen ek
alanlar `from_dict` tarafından yok sayılır (ileri uyum).

```python
from macro_sentiment.api.cas_transport import sentiment_state_to_dict, sentiment_state_from_dict

d = sentiment_state_to_dict(state)   # JSON-uyumlu dict, schema_version dahil
state2 = sentiment_state_from_dict(d)
assert state2 == state
```

**Şok sönümleme** — `decayed_magnitude(shock, at_ts)` = `magnitude * 0.5 ** (dt/halflife)`;
şoktan önceki sorgularda ham `magnitude`, `decay_halflife_s<=0` durumunda anında
sıfır döner. Simülatörün ve iç tüketicilerin ortak kullanımı için saf fonksiyon.

**Streaming (push) API** — pull (`latest`/`shocks`) yanında async jeneratör:

```python
async for event in feed.stream(["FED", "BTC"], from_ts=player.start_ts, step_s=300.0):
    ...  # SentimentState veya ShockEvent
```

`offline`+senaryo modunda replay saatini adım adım ilerletip senaryo bitene
kadar yayınlar (deterministik, ağ yok); senaryosuz `offline`'da tek kare
sentetik durum verir; `live` modda `asyncio.sleep` ile periyodik yayın yapar.

**Senaryo şema doğrulama** — JSONL satırları artık Pydantic modelleriyle
doğrulanır (`api/scenario.py`); bozuk/eksik alanlı satırlar satır numarasıyla
birlikte anlaşılır hata verir, `# yorum` ve boş satır toleransı korunur.

**HTTP köprüsü** — mevcut FastAPI uygulamasına eklendi, DB'ye erişilemezse
(anahtar/DB yoksa) sessizce `offline` moda düşer:

```
GET /v1/cas/sentiment/{entity}   → SentimentState (JSON, schema_version dahil)
GET /v1/cas/shocks?since=...     → {mode, schema_version, since, shocks: [...]}
```

## Canlı kaynaklar — NewsAPI + Fed (Faz 8)

`live` modunu gerçek veriyle dolduran ilk iki connector: `sources/newsapi_connector.py`
ve `sources/fed_connector.py`. İkisi de anahtarsız/DB'siz ortamda sistemi
bozmaz — anahtar yoksa sessizce devre dışı kalır.

**NewsAPIConnector** — `NEWSAPI_KEY` ile `/v2/everything`'i geniş bir finans
sorgusuyla (`"federal reserve" OR "stock market" OR earnings OR ...`) tarar,
`publishedAt`/`from=since` ile son haberleri çeker, `RawDocument`'a normalize
eder. Anahtar yoksa `fetch()` **ağa hiç çıkmadan** boş liste döner.

**FedConnector** — Fed'in herkese açık basın açıklaması RSS akışını
(`federalreserve.gov/feeds/press_monetary.xml`) çeker; metin için anahtar
gerekmez. FOMC ile ilgili görünen girişler `raw_meta={"doc_kind": "fomc_minutes"}`
ile işaretlenir (diğerleri `"press_release"`) — bu bilgi NLP katmanında
hawkish/dovish tetiklemesi için kullanılabilir. `FRED_API_KEY`, bu connector'ın
etkin kaynak listesine alınıp alınmayacağını belirler (`registry.active_connectors`).

**Dayanıklılık** — her iki connector da `sources/base.py::fetch_with_retry`
ile geçici hatalarda (5xx/zaman aşımı) üstel geri çekilmeli 3 deneme yapar;
4xx (ör. geçersiz anahtar) hemen pes eder. Bir kaynağın hatası diğerlerini
etkilemez (`worker/tasks.py::ingest_all_once`).

```bash
# .env içinde NEWSAPI_KEY ve/veya FRED_API_KEY tanımlıysa otomatik etkinleşir:
python -m macro_sentiment.cli run --hours 24
#   [kaynak] etkin: rss, newsapi, fed   (yalnızca anahtarı olanlar listelenir)
```

Sürekli (üretim) polling için: `worker/tasks.py::poll_connector_forever(connector, ...)`
her kaynağı kendi `POLL_INTERVAL_*` aralığıyla (`POLL_INTERVAL_NEWS`,
`POLL_INTERVAL_FED`) ayrı bir `asyncio.Task` olarak çalıştırabilir.

## Canlı kaynaklar — sosyal + bot/spam filtresi (Faz 9)

`sources/social_connector.py` — **StockTwits** sembol akışı
(`/api/2/streams/symbol/{symbol}.json`) herkese açık ve anahtarsızdır; Fed RSS'e
benzer şekilde ilk gerçek canlı sosyal kaynak. Gürültülü/riskli bir kaynak
olduğu için varsayılan **kapalı** — `.env`'de `STOCKTWITS_ENABLED=true` ile açık
onay gerekir (`SOCIAL_SYMBOLS` ile taranacak semboller ayarlanır). Twitter/Reddit
resmi OAuth gerektirir; bu fazda anahtarsızken (varsayılan) `fetch()` **ağa hiç
çıkmadan** boş liste döner — gerçek entegrasyonları kapsam dışı bırakıldı.

**Bot/spam filtresi** (`nlp/spam_filter.py`) her StockTwits turunda otomatik
uygulanır: çok yeni hesap + neredeyse hiç takipçi, veya kopya/near-duplicate
metin → akıştan **düşürülür**; sınırda şüpheli sinyaller (genç hesap, az
takipçi, yüksek hashtag/mention yoğunluğu) düşürülmez ama
`raw_meta["spam_suspicious"] = True` ile işaretlenir.

**Metin temizliği** (`ingestion/normalizer.py::strip_social_noise`) URL'leri
kaldırır, fazla boşluğu sıkıştırır; cashtag'lere ($AAPL) dokunmaz (NER bunlara
dayanır).

**Çift sayım engeli** — sosyal skorlar `signals/aggregator.py::source_breakdown`
içinde `"social"` anahtarı altında haber/Fed'den ayrı tutulur; ağırlık kararı
tüketen motora bırakılır (değişmez ilke #6).

```bash
# .env içinde STOCKTWITS_ENABLED=true ise otomatik etkinleşir:
python -m macro_sentiment.cli run --hours 24
#   [kaynak] etkin: rss, newsapi, fed, social
```

## NLP kalitesi — füzyon, gerçek belirsizlik, olumsuzlama/sarkazm (Faz 7)

`nlp/fusion.py`'deki `NotImplementedError` gerçek implementasyonlara dönüştürüldü.

**`derive_emotion(polarity, intensity, text)`** — `emotion.uncertainty` artık
sabit `0.0` değil: metindeki belirsizlik kelimeleri ("may/might/could/unclear/
risky/belirsiz/olası" …) ve zayıf "kanaat" (polarite sıfıra yakın ve/veya
yoğunluk düşükse) birlikte gerçek bir belirsizlik sinyali üretir. `fear`/`greed`
polarite yönü + yoğunluğa göre taban değer alır. Hem sözlük fallback (`lexicon_fallback`)
hem FinBERT hem LLM yolu bu fonksiyonu kullanır (LLM önce kendi `uncertainty`
alanını döndürmeyi dener; dönmezse metinden türetilir).

**`fuse(scores)`** — aynı (doc, entity) için birden çok model çıktısını güven-
ağırlıklı birleştirir. Modeller çelişirse (polarite işaretleri belirgin
şekilde zıtsa) birleşik güven `min(girdi güvenleri)`'nin altına çekilir ve
belirsizlik yükselir — "modeller aynı fikirde değilse buna daha az güven"
ilkesi. `HybridSentiment(..., fuse_high_impact=True)` opt-in parametresiyle
yüksek-etki belgelerde (Fed/uzun metin) FinBERT + LLM birlikte çalıştırılıp
füzyonlanır; varsayılan `False` — mevcut davranış (yalnızca LLM veya yalnızca
FinBERT) ve testler değişmeden korunur.

**Olumsuzlama-lite** — `negation_adjusted_polarity` yoğun olumsuzlama
("not good", "not a beats") tespit edildiğinde polariteyi yumuşatır/çevirir.
**Sarkazm-lite** — `detect_sarcasm`, sosyal medyada sık görülen ipuçlarını
("lol", "sure thing", aşırı ünlem + BÜYÜK HARF) yakalayıp güveni düşürür.
İkisi de tam bir NLP çözümü değil, ucuz ve deterministik bir sezgi katmanıdır.

```python
from macro_sentiment.nlp.fusion import fuse, derive_emotion

e = derive_emotion(polarity=0.05, intensity=15.0, text="Markets could possibly rise or fall, risk remains")
# e.uncertainty yüksek (zayıf kanaat + belirsizlik kelimeleri)

merged = fuse([finbert_score, llm_score])  # aynı (doc, entity) için
```

## Hibrit NLP notu

FinBERT (yerel, hızlı) geniş hacmi tarar. `transformers`/`torch` kurulu değilse
veya `USE_FINBERT=false` ise sistem otomatik olarak sözlük tabanlı fallback'e
düşer; böylece boru hattı her ortamda çalışır. LLM katmanı (nüans/hawkish-dovish)
Faz 2'de eklenir.

## Not

Üretilen sinyaller bilgilendirme amaçlıdır; **yatırım tavsiyesi değildir**.
