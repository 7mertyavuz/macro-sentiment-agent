# CAS Yol Haritası — macro-sentiment-agent

> Karar destek / araştırma — **yatırım tavsiyesi değildir**.

Bu doküman, `macro-sentiment-agent`'ın `cas-market-simulator` hibrit planındaki
gelişimini fazlara ayırır. Faz 0–5 + **CAS köprüsü** (SentimentFeed, ShockEvent,
deterministik replay) tamamlandı. Aşağıdaki fazlar bunun üzerine, **eklemeli**
(mevcut testleri kırmadan) inşa edilir.

## Değişmez ilkeler (tüm fazlar)

1. **Simülasyon/replay birinci sınıf:** `offline` yol hiçbir API/RPC/anahtar çağırmaz; deterministik kalır.
2. **Gevşek bağlılık:** simülatöre yalnızca veri tipleriyle bağlanılır (`api/cas_contracts.py`). Kod bağımlılığı eklenmez.
3. **Geriye uyum:** mevcut testler yeşil kalır; yeni yetenek ek olarak gelir (varsayılanlı alan/param).
4. **Zaman:** tüm damgalar UTC, tz-aware `datetime`.
5. **Maliyet kontrolü:** hibrit NLP router (rutin→FinBERT, yüksek-etki→LLM) korunur.
6. **Çift sayım engeli:** SentimentState ham/temiz sinyal taşır; ağırlık kararı tüketen motora bırakılır.
7. **Konum ibaresi:** "yatırım tavsiyesi değildir" her arayüz/dokümanda korunur.

---

## Faz 6 — CAS köprüsü sağlamlaştırma & taşıma katmanı
**Amaç:** Simülatör muhtemelen ayrı bir süreç/repo. Köprüyü süreçler-arası
tüketilebilir hale getir; şok sönümleme ve senaryo doğrulamayı tamamla.
Harici anahtar gerektirmez → önce bu.

### Kapsam
- **Serileştirme:** `SentimentState`/`ShockEvent` için `to_dict()`/`from_dict()` + JSON şeması. Sözleşme **sürüm alanı** (`schema_version`) ekle.
- **Şok sönümleme yardımcısı:** `decayed_magnitude(shock, at_ts)` = `magnitude * 0.5**(dt/halflife)`; simülatörün ve iç tüketicilerin ortak kullanımı için saf fonksiyon.
- **Streaming/push API:** pull (`latest`/`shocks`) yanına async jeneratör `stream(entities, from_ts)` — replay saatini adımlayıp olayları yayınlar.
- **Senaryo şema doğrulama:** JSONL satırları için Pydantic doğrulayıcı + net hata mesajları; `# yorum` ve boş satır toleransı (mevcut davranış korunur).
- **HTTP köprüsü (opsiyonel, offline-güvenli):** `GET /v1/cas/sentiment/{entity}` ve `GET /v1/cas/shocks?since=...` → JSON. Var olan FastAPI app'e eklenir; DB yoksa offline moda düşer.

### Dokunulan / yeni dosyalar
- Yeni: `api/cas_transport.py` (serileştirme + decay), `tests/test_cas_transport.py`.
- Değişen: `api/sentiment_feed.py` (+`stream`), `api/scenario.py` (+şema doğrulama), `api/routes.py` (+CAS uçları), `README.md`.

### Bitti tanımı
- `to_dict/from_dict` round-trip testleri geçer; `schema_version` mevcut.
- `decayed_magnitude` yarılanma süresinde tam yarıya iner (birim test).
- Bozuk senaryo satırı anlaşılır hata verir; geçerli senaryo aynen çalışır.
- CAS HTTP uçları offline modda anahtarsız JSON döndürür.
- **Efor:** ~S/M. **Bağımlılık:** yok. **Risk:** düşük.

---

## Faz 7 — NLP kalite: füzyon + gerçek duygu/belirsizlik
**Amaç:** `nlp/fusion.py` şu an `NotImplementedError`. SentimentState'in
`emotion` ve `confidence` kalitesi doğrudan indikatör motorunu besler → önceliklidir.

### Kapsam
- **`fuse(scores)`:** aynı (doc, entity) için çoklu model (FinBERT + LLM) çıktısını güven-ağırlıklı birleştir; modeller çelişirse güveni düşür.
- **`derive_emotion(polarity, intensity, text)`:** korku/coşku/**belirsizlik** sözlükleri + model çıktısından duygu boyutları. `uncertainty` artık sıfır varsayılan değil, gerçek sinyal.
- **Negation & sarkazm ipuçları (lite):** temel olumsuzlama ("not good") ve sosyal-medya sarkazm bayrağı; güveni ayarlar.
- **Kalibrasyon:** backtest'e emotion/uncertainty doğruluğu için küçük etiketli set.

### Dokunulan / yeni dosyalar
- Değişen: `nlp/fusion.py` (implement), `nlp/hybrid.py`/`router.py` (fuse çağrısı), `signals/aggregator.py` (uncertainty zaten hazır).
- Yeni: `tests/test_fusion.py`, `tests/fixtures/emotion_labeled.jsonl`.

### Bitti tanımı
- `fuse`/`derive_emotion` NotImplementedError'dan çıkar; deterministik testler geçer.
- Çelişen modellerde birleşik güven < min(girdiler) (test).
- Belirsizlik ekseni backtest'te anlamlı (>0 varyans, spot kontrol).
- **Efor:** ~M. **Bağımlılık:** Faz 6 (SentimentState kalitesi tüketilecek). **Risk:** orta (sözlük kalibrasyonu).

---

## Faz 8 — Canlı kaynaklar I: NewsAPI + FRED/FOMC (Fed)
**Amaç:** `live` modu gerçek veriyle doldur. `fed_connector`/`newsapi_connector`
şu an stub. `fed_tone` ekseni FOMC metniyle güçlenir.

### Kapsam
- **NewsAPIConnector.fetch:** `httpx` ile `/v2/everything?from=since`; normalize → `RawDocument`; rate-limit politikası (token-bucket) + retry/backoff.
- **FedConnector.fetch:** FRED takvimi + FOMC press release/tutanak metni; `raw_meta={"doc_kind":"fomc_minutes"}` ile NLP'de hawkish/dovish tetikleme.
- **Kayıt & registry:** `sources/registry.py`'ye canlı kaynakları anahtar varsa ekle; anahtar yoksa sessizce atla (offline bozulmaz).
- **Zamanlama:** `worker/tasks.py` polling döngüsüne yeni kaynaklar; `POLL_INTERVAL_*` config.

### Dokunulan / yeni dosyalar
- Değişen: `sources/newsapi_connector.py`, `sources/fed_connector.py`, `sources/registry.py`, `worker/tasks.py`.
- Yeni: `tests/test_newsapi.py`, `tests/test_fed.py` (httpx mock; **ağ yok**).

### Bitti tanımı
- Mock'lu testlerde iki connector normalize `RawDocument` üretir (gerçek ağ çağrısı yok).
- Anahtar yokken sistem offline gibi çalışır (test).
- FOMC metni `fed_tone`'u doğru yönde etkiler (uçtan uca mini test).
- **Efor:** ~M/L. **Bağımlılık:** anahtarlar (NEWSAPI_KEY, FRED_API_KEY). **Risk:** orta (dış API şeması/limitler).

---

## Faz 9 — Canlı kaynaklar II: Sosyal + bot/spam & sarkazm
**Amaç:** X/Reddit/StockTwits akışı; sosyal gürültü yönetimi kritik.

### Kapsam
- **SocialConnector.fetch:** platforma göre filtreli polling/stream; kimlik bilgisi yoksa atla.
- **Bot/spam filtresi:** hesap yaşı/etkileşim/kopya-metin sezgileri; şüpheli içeriği düşür veya güveni azalt.
- **Kaynak ağırlığı:** `source_breakdown`'da sosyal polariteyi ayrı tut; ham veriyi motora bırak (çift sayım engeli).
- **Hız/kota:** agresif rate-limit + backoff; maliyet/limit koruması.

### Dokunulan / yeni dosyalar
- Değişen: `sources/social_connector.py`, `ingestion/normalizer.py` (sosyal temizlik), `registry.py`.
- Yeni: `nlp/spam_filter.py`, `tests/test_social.py`, `tests/test_spam_filter.py`.

### Bitti tanımı
- Mock akışta bot/spam örnekleri elenir (test).
- Sosyal katkı `source_breakdown["social"]` olarak izole görünür.
- Anahtarsız durumda offline korunur.
- **Efor:** ~L. **Bağımlılık:** Faz 8 pattern'i, sosyal anahtarlar. **Risk:** yüksek (platform API kısıtları, sarkazm).

---

## Faz 10 — Ölçek & kalıcılık: TimescaleDB + tarihsel baseline
**Amaç:** Anomali sinyali tarihsel normalden doğar; kalıcı rolling baseline gerekir.
Hacim ve ölçek için TimescaleDB.

### Kapsam
- **TimescaleDB/Postgres:** hypertable'lar (sentiment_scores, signals); retention + downsampling (sürekli agregatlar).
- **Tarihsel baseline kalıcılığı:** varlık×metrik için rolling (mean,std) sakla; `signals/baseline.py` bunu okur (şu an bellek içi).
- **Rolling z-score:** motor gerçek tarihsel baseline'a göre değerlendirir; eşikler daha anlamlı.
- **Geriye uyum:** SQLite dev yolu korunur; TimescaleDB opsiyonel `DATABASE_URL`.

### Dokunulan / yeni dosyalar
- Değişen: `storage/orm.py`, `storage/db.py`, `storage/repositories.py`, `signals/engine.py`/`baseline.py`.
- Yeni: `storage/migrations/` (Alembic), `tests/test_baseline_persistence.py`.

### Bitti tanımı
- Baseline DB'den okunur/yazılır; yeniden başlatmada korunur (test).
- Rolling z-score sinyal şiddetini etkiler (test).
- SQLite dev testleri hâlâ yeşil.
- **Efor:** ~L. **Bağımlılık:** çalışan Postgres/Timescale. **Risk:** orta (migration, ortam).

---

## Faz 11 — HITL & kalibrasyon döngüsü
**Amaç:** Yüksek-etki sinyaller enjeksiyon/dağıtım öncesi insan onayı; geri
beslemeyle otomatik eşik kalibrasyonu.

### Kapsam
- **İnceleme kuyruğu:** `severity >= X` sinyalleri "pending review" durumuna al; onay/ret API + dashboard aksiyonları.
- **Geri besleme deposu:** onay/ret + gerçekleşen sonuç etiketleri; backtest setine akıtılır.
- **Otomatik eşik kalibrasyonu:** backtest metriklerinden kural eşiklerini öner/güncelle (grid/bayes-lite).
- **CAS etkisi:** onaylanmamış sinyaller `shocks()`'a düşmez (opsiyonel katı mod).

### Dokunulan / yeni dosyalar
- Değişen: `signals/engine.py`, `api/routes.py`/`dashboard.py`, `backtest/*`.
- Yeni: `signals/review.py`, `tests/test_review.py`, `tests/test_calibration.py`.

### Bitti tanımı
- Pending→approved/rejected akışı test edilir.
- Kalibrasyon önerisi backtest F1'i düşürmez (regresyon testi).
- Katı modda yalnız onaylı sinyaller şok olur.
- **Efor:** ~L. **Bağımlılık:** Faz 10 (geçmiş veri). **Risk:** orta.

---

## Faz 12 — Gözlemlenebilirlik & operasyonel sertleştirme
**Amaç:** Üretim güveni: metrikler, sağlık, CI, güvenlik.

### Kapsam
- **Metrikler:** feed/shock throughput, model çağrı sayısı/maliyeti, kaynak gecikmeleri (`observability/metrics.py` genişlet, Prometheus uçları).
- **Yapılandırılmış log & izleme:** korelasyon kimlikleri; hata oranları.
- **CI:** GitHub Actions — pytest + ruff + mypy; py3.11 matrisi; kapsam raporu.
- **Güvenlik:** anahtar sızıntısı taraması, bağımlılık denetimi, rate-limit doğrulama.
- **Dağıtım:** `docker-compose` (Timescale + Redis), deploy checklist + rollback notları.

### Dokunulan / yeni dosyalar
- Değişen: `observability/*`, `Dockerfile`, `docker-compose.yml`, `pyproject.toml`.
- Yeni: `.github/workflows/ci.yml`, `docs/RUNBOOK.md`.

### Bitti tanımı
- CI PR'larda yeşil; ruff+mypy temiz.
- Temel metrikler `/metrics`'te görünür.
- **Efor:** ~M. **Bağımlılık:** yok (paralel yürütülebilir). **Risk:** düşük.

---

## Önerilen sıra ve gerekçe

| Sıra | Faz | Neden burada |
|---|---|---|
| 1 | **Faz 6** | Anahtarsız, deterministik; köprüyü gerçekten tüketilebilir yapar (simülatör ayrı süreç). |
| 2 | **Faz 7** | SentimentState kalitesi = motorun girdi kalitesi; dış bağımlılık yok. |
| 3 | **Faz 8** | İlk gerçek canlı veri; `fed_tone`'u güçlendirir. |
| 4 | **Faz 10** | Canlı veri gelince tarihsel baseline anlam kazanır (8'den sonra mantıklı). |
| 5 | **Faz 9** | Sosyal en gürültülü/riskli; pattern oturunca. |
| 6 | **Faz 11** | Geçmiş veri + kalibrasyon olgunlaşınca. |
| — | **Faz 12** | Diğerlerine paralel, süreklidir. |

## Her faz için ortak "tamam" kontrol listesi
- [ ] Yeni + mevcut testler yeşil (offline, ağsız).
- [ ] `offline`/replay yolu hâlâ API çağırmıyor.
- [ ] Geriye uyum: eski imzalar/testler korunuyor.
- [ ] README/docs güncellendi; "yatırım tavsiyesi değildir" duruyor.
- [ ] UTC tz-aware zaman; sözleşme tipleri değişmediyse `schema_version` sabit.
