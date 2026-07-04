# Operasyon Runbook — Macro-Sentiment Agent

> Karar destek / araştırma amaçlıdır — **yatırım tavsiyesi değildir**.

Bu doküman Faz 12 (gözlemlenebilirlik & operasyonel sertleştirme) kapsamında
eklendi: dağıtım öncesi kontrol listesi, geri alma (rollback) notları ve
temel operasyon bilgisi.

## Mimari özet

```
kaynaklar (RSS/NewsAPI/Fed/StockTwits) → ingestion (dedup+kuyruk) → NLP
  (FinBERT/LLM/füzyon) → signals (kurallar+baseline+HITL) → api (REST+CAS köprüsü)
```

Dev: SQLite + bellek-içi kuyruk (anahtarsız, ağsız çalışır). Üretim:
Postgres/TimescaleDB + Redis Streams (`docker-compose.yml`).

## Dağıtım öncesi kontrol listesi

- [ ] `pytest -q` yeşil (tüm testler; offline/ağsız).
- [ ] `ruff check src tests` ve `ruff format --check src tests` temiz.
- [ ] `python scripts/check_secrets.py` temiz — commit'e sızmış anahtar yok.
- [ ] `pip-audit` çalıştırıldı; kritik CVE'ler değerlendirildi (CI'da rapor
      edilir, otomatik engellemez — bkz. `.github/workflows/ci.yml`).
- [ ] `.env` üretim değerleriyle dolduruldu; `.env.example` ile karşılaştırıldı
      (yeni alan eklendiyse ikisi de güncel mi?).
- [ ] `DATABASE_URL` üretimde Postgres/TimescaleDB'ye işaret ediyor (SQLite
      yalnızca dev/test).
- [ ] `QUEUE_BACKEND=redis` üretimde ayarlı (bellek-içi kuyruk tek süreç
      için, yatay ölçek için Redis gerekir).
- [ ] `ALERT_MIN_SEVERITY` ve `REVIEW_SEVERITY_THRESHOLD` (Faz 11,
      `signals/review.py`) mevcut kalibrasyonla tutarlı.
- [ ] `/health` ve `/metrics` uçları erişilebilir (deploy sonrası smoke test).
- [ ] "Yatırım tavsiyesi değildir" ibaresi dashboard/README/API dokümanlarında
      duruyor (değişmez ilke, tüm fazlarda korunur).

## Dağıtım

```bash
docker compose up -d db redis
docker compose run --rm api python -c "import asyncio; from macro_sentiment.storage.db import init_db; asyncio.run(init_db())"
docker compose up -d api worker
curl -sf http://localhost:8000/health
curl -sf http://localhost:8000/metrics | head -5
```

## Geri alma (rollback) tetikleyicileri

Aşağıdakilerden biri gözlemlenirse dağıtımı geri al (önceki imaj/tag'e dön):

- `/health` 5xx döndürüyor veya `msa_source_fetch_errors_total` beklenmedik
  şekilde artıyor (bkz. `/metrics`).
- `msa_signals_emitted_total` aniden sıfıra düşüyor (boru hattı kırık
  olabilir — sessiz veri kaybı, en tehlikeli senaryo).
- HITL inceleme kuyruğu (`GET /v1/review/pending`) beklenmedik şekilde
  büyüyor ve boşalmıyor (dağıtım/dispatcher regresyonu belirtisi).
- Backtest F1 (`signals/calibration.py` ile periyodik kalibrasyon
  kontrolünde) önceki sürüme göre anlamlı düşüş gösteriyor.

Rollback adımı: `docker compose up -d --no-deps api worker` ile önceki imaj
tag'ine dön; DB şeması yalnızca `Base.metadata.create_all` ile eklemeli
büyüdüğü için (Alembic henüz yok, TODO) geri alma genelde şema geriye
uyumludur — riskli değişiklikler (ör. sütun kaldırma) ayrıca değerlendirilmeli.

## Gözlemlenebilirlik

`GET /metrics` (Prometheus text formatı) şu metrikleri sağlar:

| Metrik | Tip | Açıklama |
|---|---|---|
| `msa_documents_fetched_total{source}` | Counter | Kaynak başına çekilen yeni belge |
| `msa_source_fetch_errors_total{source}` | Counter | Kaynak başına başarısız çekme turu |
| `msa_inference_seconds{model}` | Histogram | Model başına duyarlılık çıkarım süresi |
| `msa_signals_emitted_total{type,review_status}` | Counter | Tip+inceleme durumu başına sinyal |
| `msa_queue_depth{topic}` | Gauge | Bellek-içi kuyrukta bekleyen mesaj sayısı |
| `msa_llm_tokens_total{model,kind}` | Counter | Tanımlı; gerçek sağlayıcı kullanım verisi döndürene kadar henüz enjekte edilmiyor (TODO) |

Loglar `observability/logging.py::configure_logging()` ile yapılandırılmış
JSON olarak basılır; her kayıt varsa `correlation_id` içerir
(`bind_correlation_id()` ile bir istek/belge işlem hattı boyunca ayarlanabilir).

## Bilinen sınırlamalar / TODO

- `mypy` CI'da `continue-on-error: true` — tip hataları henüz PR'ı engellemiyor
  (kademeli sıkılaştırma planlanıyor).
- `ruff format --check` de aynı şekilde `continue-on-error: true` — mevcut kod
  tabanı (Faz 0-11) henüz ruff'ın varsayılan format kurallarıyla uyumlu değil;
  toplu bir yeniden biçimlendirme PR'ı ayrıca yapılmalı (bu, davranış
  değiştirmeyen ama büyük bir diff'tir — özellik PR'larından ayrı tutuldu).
  `ruff check` (lint) engelleyicidir ve temizdir.
- `pip-audit` da aynı şekilde rapor amaçlı; kritik bulgularda manuel triage.
- Alembic migration'ları yok — şema `create_all` ile eklemeli büyüyor.
- `msa_llm_tokens_total` tanımlı ama henüz beslenmiyor (LLMProvider protokolü
  kullanım/token verisini dışa vermiyor).
