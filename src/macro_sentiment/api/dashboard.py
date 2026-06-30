"""Basit canlı dashboard — son sinyaller ve varlık duyarlılığı.

FastAPI tarafından GET / üzerinde sunulur; /v1/signals ve /v1/sentiment
uçlarını JS ile çekip 30 sn'de bir yeniler.
"""
from __future__ import annotations

DASHBOARD_HTML = """<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Macro-Sentiment Agent</title>
<style>
  :root { color-scheme: dark; }
  body { font-family: -apple-system, system-ui, sans-serif; margin: 0; background:#0e1117; color:#e6edf3; }
  header { padding: 16px 24px; border-bottom: 1px solid #21262d; display:flex; align-items:center; gap:12px; }
  header h1 { font-size: 18px; margin: 0; font-weight: 600; }
  .muted { color:#8b949e; font-size: 13px; }
  main { padding: 24px; max-width: 920px; margin: 0 auto; }
  .card { background:#161b22; border:1px solid #21262d; border-radius:10px; padding:16px; margin-bottom:20px; }
  table { width:100%; border-collapse: collapse; font-size: 14px; }
  th, td { text-align:left; padding:8px 10px; border-bottom:1px solid #21262d; }
  th { color:#8b949e; font-weight:500; }
  .tag { padding:2px 8px; border-radius:6px; font-size:12px; font-weight:600; }
  .panic { background:#3d1418; color:#ff7b72; }
  .euphoria { background:#1a3a1f; color:#7ee787; }
  .fed_tone { background:#1c2a4d; color:#79c0ff; }
  .sev { font-variant-numeric: tabular-nums; }
  input { background:#0d1117; border:1px solid #30363d; color:#e6edf3; padding:6px 10px; border-radius:6px; }
  button { background:#238636; border:0; color:#fff; padding:6px 14px; border-radius:6px; cursor:pointer; }
  .row { display:flex; gap:10px; align-items:center; }
</style>
</head>
<body>
<header>
  <h1>📊 Macro-Sentiment Agent</h1>
  <span class="muted" id="updated">yükleniyor…</span>
</header>
<main>
  <div class="card">
    <h3>Aktif Sinyaller</h3>
    <table><thead><tr><th>Zaman</th><th>Tip</th><th>Şiddet</th><th>Başlık</th></tr></thead>
    <tbody id="signals"><tr><td colspan="4" class="muted">…</td></tr></tbody></table>
  </div>
  <div class="card">
    <h3>Varlık Duyarlılığı</h3>
    <div class="row" style="margin-bottom:12px">
      <input id="entity" value="BTC" placeholder="ticker (örn. AAPL)"/>
      <button onclick="loadSentiment()">Sorgula</button>
    </div>
    <div id="sentiment" class="muted">—</div>
  </div>
</main>
<script>
async function loadSignals() {
  const r = await fetch('/v1/signals?limit=25'); const data = await r.json();
  const tb = document.getElementById('signals');
  if (!data.length) { tb.innerHTML = '<tr><td colspan="4" class="muted">Henüz sinyal yok</td></tr>'; }
  else tb.innerHTML = data.map(s => {
    const t = new Date(s.created_at).toLocaleString('tr-TR');
    return `<tr><td class="muted">${t}</td>
      <td><span class="tag ${s.type}">${s.type}</span></td>
      <td class="sev">${s.severity.toFixed(0)}</td>
      <td>${s.headline}</td></tr>`;
  }).join('');
  document.getElementById('updated').textContent = 'son güncelleme: ' + new Date().toLocaleTimeString('tr-TR');
}
async function loadSentiment() {
  const e = document.getElementById('entity').value.trim().toUpperCase();
  const r = await fetch('/v1/sentiment/' + e); const d = await r.json();
  const el = document.getElementById('sentiment');
  if (!d.count) { el.innerHTML = `<span class="muted">${e}: kayıt yok</span>`; return; }
  const sign = d.avg_polarity >= 0 ? '🔺' : '🔻';
  el.innerHTML = `<b>${e}</b> — ortalama polarite ${sign} <b>${d.avg_polarity.toFixed(2)}</b>
    <span class="muted">(${d.count} skor)</span>`;
}
loadSignals(); loadSentiment();
setInterval(loadSignals, 30000);
</script>
</body>
</html>"""
