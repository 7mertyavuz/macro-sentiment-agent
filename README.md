<div align="center">

# 📊 Macro-Sentiment Agent

### Finansal haber · Fed · sosyal medya → NLP → **piyasa duyarlılığı sinyalleri**

Metin akışını gerçek zamanlı okuyup **işlenebilir duyarlılık sinyalleri** üreten otonom analiz ajanı.
Karar destek üretir — **işlem yapmaz, yatırım tavsiyesi vermez.**

<br>

[![CI](https://github.com/7mertyavuz/macro-sentiment-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/7mertyavuz/macro-sentiment-agent/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%20|%203.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white)
![Tests](https://img.shields.io/badge/tests-151%20passed-2ea44f?logo=pytest&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-blue)

</div>

---

## 🎯 Ne işe yarar?

Piyasayı hareket ettiren bilgi, fiyat verisinden **önce metin olarak** ortaya çıkar: haber başlıkları, Fed tutanakları, şirket açıklamaları, sosyal medya akışları. Bu ajan metni sürekli okur, NLP ile analiz eder ve şu tip sinyalleri üretir:

```text
⚑ [panic   ] BTC — aşırı korku: son 1 saatte negatif haber yoğunluğu arttı
⚑ [euphoria] NVDA — sosyal medya coşkusu zirvede; olası tepe sinyali
⚑ [fed_tone] FED — hawkish tonu güçleniyor; duyarlılık -0.62
```

Her sinyal **yön · şiddet (0–100) · güven skoru · kaynak dağılımı · zaman damgası** taşır.

---

## 🏗️ Mimari

Olay güdümlü, gevşek bağlı **5 katman**:

```mermaid
flowchart LR
    subgraph SRC["1 · Kaynaklar"]
        N["📰 Haber / NewsAPI"]
        F["🏛️ Fed RSS"]
        S["💬 StockTwits"]
    end
    subgraph ING["2 · Ingestion"]
        C["Connector'lar"]
        D["dedup"]
        Q["Kuyruk"]
    end
    subgraph NLP["3 · NLP Motoru"]
        PRE["ön işleme"]
        SENT["hibrit sentiment"]
        FUSE["füzyon"]
    end
    subgraph SIG["4 · Sinyal Motoru"]
        BASE["baseline z-skor"]
        RULE["kural / anomali"]
        REV["HITL inceleme"]
    end
    subgraph OUT["5 · Sunum"]
        API["REST / WS API"]
        ALERT["uyarılar"]
        CAS["CAS köprüsü"]
    end

    SRC --> C --> D --> Q --> PRE --> SENT --> FUSE --> BASE --> RULE --> REV --> API
    RULE --> ALERT
    API --> CAS
```

---

## 📦 Başlıca Özellikler

| Özellik | Açıklama |
|---|---|
| 🧠 **Hibrit NLP** | FinBERT (yerel) + LLM (nüans) + sözlük fallback |
| 📡 **Çoklu kaynak** | RSS · NewsAPI · Fed · StockTwits; anahtar yoksa sessizce atlanır |
| 🔗 **CAS köprüsü** | `SentimentState` + `ShockEvent` sözleşmeleri |
| 🚨 **Anomali sinyalleri** | Kalıcı baseline (Welford) + cooldown |
| 👤 **HITL** | Yüksek-etki sinyalleri onay bekler |
| 🔭 **Gözlemlenebilirlik** | `/metrics`, yapılandırılmış log, CI, Docker Compose |

---

## ⚡ Hızlı Başlangıç

```bash
python -m venv .venv
pip install -e ".[dev]"
cp .env.example .env

# Çevrimdışı demo
USE_FINBERT=false python -m macro_sentiment.cli demo --sample tests/fixtures/sample_feed.xml

# REST API
uvicorn macro_sentiment.api.main:app --reload
```

---

## 🔗 cas-market-simulator Entegrasyonu

Bu repo, CAS planında iki rol üstlenir:

- **Sentiment sensörü** → `SentimentState` (polarity, emotion, fed_tone)
- **Dışsal şok enjektörü** → `ShockEvent` (panic, euphoria, fed_tone)

```mermaid
flowchart TD
    MSA["macro-sentiment-agent"] -->|SentimentState| SIM["cas-market-simulator"]
    MSA -->|ShockEvent| SIM
```

---

## ⚖️ Sorumluluk Reddi

Üretilen sinyaller bilgilendirme amaçlıdır ve **yatırım tavsiyesi değildir.** Sistem karar destek üretir; otomatik emir göndermez.

## 📄 Lisans

MIT — bkz. [LICENSE](LICENSE).
