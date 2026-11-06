/* 종목 페이지 — data/prices/{code}.json, data/financials/{code}.json, data/reports/index.json */
const $ = s => document.querySelector(s);
const fmt = (n, d = 0) => n == null || !isFinite(n) ? '—' : n.toLocaleString('ko-KR', { minimumFractionDigits: d, maximumFractionDigits: d });
const sign = n => n == null ? '' : n > 0 ? '+' : '';
const cls = n => n == null ? '' : n > 0 ? 'up' : n < 0 ? 'down' : '';
const kst = iso => { if (!iso) return '—'; const d = new Date(iso); return isNaN(d) ? iso : d.toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }); };
const v = Math.floor(Date.now() / 60000);
const RED = '#d64545', BLUE = '#2563eb', INK = '#111827', GRID = '#eceff3', MUTED = '#9ca3af';
const jo = n => n == null ? '—' : Math.abs(n) >= 1e12 ? `${(n / 1e12).toFixed(1)}조` : `${fmt(n / 1e8)}억`;

const code = new URLSearchParams(location.search).get('code') || '';
if (!/^\d{6}$/.test(code)) { $('#head').innerHTML = '<div class="empty">잘못된 종목코드입니다.</div>'; throw new Error('bad code'); }

let priceData = null, priceChart = null;

async function main() {
  const [wl, p, f, idx] = await Promise.all([
    fetch(`data/watchlist.json?v=${v}`).then(r => r.json()).catch(() => null),
    fetch(`data/prices/${code}.json?v=${v}`).then(r => r.ok ? r.json() : null).catch(() => null),
    fetch(`data/financials/${code}.json?v=${v}`).then(r => r.ok ? r.json() : null).catch(() => null),
    fetch(`data/reports/index.json?v=${v}`).then(r => r.json()).catch(() => []),
  ]);
  const meta = (wl?.kr || []).find(s => s.ticker === code) || { ticker: code, name: p?.name || code };
  document.title = `${meta.name} · AKME Research`;
  drawHead(meta, p);
  priceData = p; drawPrice(0);
  drawFin(f);
  drawReports(idx.filter(r => r.ticker === code));
}

function drawHead(meta, p) {
  const ok = p && ['ok', 'stale'].includes(p.status);
  $('#head').innerHTML = `
    <div>
      <div class="meta">${meta.ticker} · ${meta.market || ''} · ${meta.sector || ''}</div>
      <h1>${meta.name}</h1>
    </div>
    ${ok ? `
    <div class="stock-quote">
      <div class="v ${cls(p.changePercent)}">${fmt(p.price)}<small>원</small></div>
      <div class="c ${cls(p.change)}">${sign(p.change)}${fmt(p.change)} (${sign(p.changePercent)}${fmt(p.changePercent, 2)}%)</div>
      <div class="s">${kst(p.quoteAt)} · ${p.marketStatus === 'OPEN' ? '장중' : '장 마감'}${p.status === 'stale' ? ' · 이전 자료' : ''}</div>
    </div>
    <div class="kv">
      <div><span>시가총액</span><b>${p.marketCap || '—'}</b></div>
      <div><span>PER</span><b>${p.per || '—'}</b></div>
      <div><span>PBR</span><b>${p.pbr || '—'}</b></div>
      <div><span>EPS</span><b>${p.eps || '—'}</b></div>
      <div><span>52주 최고 / 최저</span><b>${p.high52 || '—'} / ${p.low52 || '—'}</b></div>
      <div><span>외국인 비율</span><b>${p.foreignRate || '—'}</b></div>
    </div>` : '<div class="empty">시세는 다음 수집 때 표시됩니다.</div>'}`;
}

function drawPrice(days) {
  const pts = priceData?.points || [];
  const sel = days ? pts.slice(-days) : pts;
  if (sel.length < 2) { $('#price-note').textContent = '일봉 자료가 아직 없습니다.'; return; }
  const up = sel.at(-1).close >= sel[0].close;
  const cfg = { type: 'line', data: { labels: sel.map(p => p.date), datasets: [
      { label: '종가', data: sel.map(p => p.close), yAxisID: 'y', borderColor: up ? RED : BLUE, backgroundColor: up ? 'rgba(214,69,69,.08)' : 'rgba(37,99,235,.08)', fill: 'origin', borderWidth: 1.8, pointRadius: 0, tension: .15 },
      { label: '거래량', data: sel.map(p => p.volume), yAxisID: 'y1', type: 'bar', backgroundColor: 'rgba(107,114,128,.25)', borderWidth: 0 } ] },
    options: { responsive: true, maintainAspectRatio: false, animation: false, interaction: { mode: 'index', intersect: false },
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => c.datasetIndex === 0 ? ` 종가 ${fmt(c.parsed.y)}원` : ` 거래량 ${fmt(c.parsed.y)}` } } },
      scales: { x: { ticks: { maxTicksLimit: 8, font: { size: 11 }, callback: (val, i) => sel[i]?.date.slice(2, 7) }, grid: { display: false } },
        y: { position: 'right', ticks: { callback: val => fmt(val), font: { size: 11 } }, grid: { color: GRID } },
        y1: { position: 'left', display: false, max: Math.max(...sel.map(p => p.volume)) * 4 } } } };
  if (priceChart) { priceChart.data = cfg.data; priceChart.options = cfg.options; priceChart.update(); } else priceChart = new Chart($('#price-chart'), cfg);
  const perf = (sel.at(-1).close / sel[0].close - 1) * 100;
  $('#price-note').innerHTML = `${sel[0].date} → ${sel.at(-1).date} <b class="${cls(perf)}">${sign(perf)}${fmt(perf, 1)}%</b> · 일봉 Yahoo Finance · 갱신 ${kst(priceData.collectedAt)}`;
}
document.querySelectorAll('#range .tab').forEach(b => b.onclick = () => { document.querySelectorAll('#range .tab').forEach(x => x.classList.toggle('on', x === b)); drawPrice(+b.dataset.days); });

function drawFin(f) {
  const q = f?.quarters || {};
  const keys = Object.keys(q).sort().slice(-12);
  if (!keys.length) { $('#fin-note').textContent = 'DART 분기 재무가 아직 수집되지 않았습니다.'; return; }
  const g = (k, l) => q[k]?.[l]?.q ?? null;
  const sales = keys.map(k => g(k, '매출액')), op = keys.map(k => g(k, '영업이익')), ni = keys.map(k => g(k, '당기순이익'));
  const opm = keys.map((k, i) => sales[i] && op[i] != null ? op[i] / sales[i] * 100 : null);
  new Chart($('#fin-chart'), { type: 'bar', data: { labels: keys.map(k => k.replace('Q', ' Q')), datasets: [
      { label: '매출액', data: sales.map(x => x == null ? null : x / 1e8), backgroundColor: 'rgba(17,24,39,.75)', yAxisID: 'y', order: 2 },
      { label: '영업이익', data: op.map(x => x == null ? null : x / 1e8), backgroundColor: 'rgba(37,99,235,.75)', yAxisID: 'y', order: 2 },
      { label: '영업이익률', data: opm, type: 'line', yAxisID: 'y1', borderColor: RED, borderWidth: 2, pointRadius: 3, tension: .2, order: 1 } ] },
    options: { responsive: true, maintainAspectRatio: false, animation: false, interaction: { mode: 'index', intersect: false },
      plugins: { legend: { position: 'top', labels: { boxWidth: 10, font: { size: 11 } } }, tooltip: { callbacks: { label: c => c.dataset.yAxisID === 'y1' ? ` 영업이익률 ${fmt(c.parsed.y, 1)}%` : ` ${c.dataset.label} ${jo(c.parsed.y * 1e8)}` } } },
      scales: { x: { grid: { display: false }, ticks: { font: { size: 11 } } },
        y: { ticks: { callback: val => Math.abs(val) >= 1e4 ? `${fmt(val / 1e4, 0)}조` : `${fmt(val)}억`, font: { size: 11 } }, grid: { color: GRID } },
        y1: { position: 'right', ticks: { callback: val => `${fmt(val, 0)}%`, font: { size: 11 } }, grid: { display: false } } } } });
  const allKeys = Object.keys(q).sort();
  const rows = keys.slice().reverse().map((k, i) => { const j = keys.length - 1 - i;
    const yoy = (l, arr) => { const prevKey = `${+k.slice(0, 4) - 1}${k.slice(4)}`; const prev = q[prevKey]?.[l]?.q; const cur = arr[j];
      if (prev == null || cur == null || prev === 0) return '—'; if (prev < 0) return '흑전/적지'; const r = (cur / prev - 1) * 100; return `<span class="${cls(r)}">${sign(r)}${fmt(r, 1)}%</span>`; };
    return `<tr><td>${k}${q[k].derived ? ' <span class="tag">역산</span>' : ''}</td><td>${jo(sales[j])}</td><td>${yoy('매출액', sales)}</td><td>${jo(op[j])}</td><td>${yoy('영업이익', op)}</td><td>${opm[j] == null ? '—' : fmt(opm[j], 1) + '%'}</td><td>${jo(ni[j])}</td></tr>`; }).join('');
  $('#fin-table').innerHTML = `<table><thead><tr><th>분기</th><th>매출액</th><th>YoY</th><th>영업이익</th><th>YoY</th><th>영업이익률</th><th>순이익</th></tr></thead><tbody>${rows}</tbody></table>`;
  $('#fin-note').textContent = `DART 전체 재무제표(연결 CFS 우선) · 3개월 손익 · Q4는 연간−3분기누적 역산 · 갱신 ${kst(f.updatedAt)}`;
}

function drawReports(list) {
  const el = $('#reports');
  if (!list.length) { el.innerHTML = '<div class="empty">아직 이 종목의 리포트가 없습니다. 실적 공시가 나오면 자동으로 생성됩니다.</div>'; return; }
  el.innerHTML = list.map(r => `<a class="card" href="report.html?f=${encodeURIComponent(r.file)}">
    <div class="meta">${r.published} · ${r.period}${r.source_type === 'auto' ? '<span class="badge">자동 생성</span>' : '<span class="badge">샘플</span>'}</div>
    <div class="title">${r.title}</div><div class="summary">${r.summary}</div></a>`).join('');
}

main().catch(e => { $('#head').innerHTML = '<div class="empty">자료를 불러오지 못했습니다.</div>'; console.error(e); });
