/* 신용잔고 페이지 — data/credit.json (억원) */
const $ = s => document.querySelector(s);
const fmt = (n, d = 0) => n == null || !isFinite(n) ? '—' : n.toLocaleString('ko-KR', { minimumFractionDigits: d, maximumFractionDigits: d });
const sign = n => n == null ? '' : n > 0 ? '+' : '';
const cls = n => n == null ? '' : n > 0 ? 'up' : n < 0 ? 'down' : '';
const kst = iso => { if (!iso) return '—'; const d = new Date(iso); return isNaN(d) ? iso : d.toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }); };
const jo = eok => eok / 1e4;  // 억원 → 조원
const RED = '#d64545', BLUE = '#2563eb', GREEN = '#16a34a', GRID = '#eceff3';

let data = null;
const charts = {};
let iStart = 0, iEnd = 0;   // 전체 데이터 기준 인덱스

function startIndexForMonths(points, m) {
  if (!m) return 0;
  const last = new Date(points.at(-1).date + 'T00:00:00Z');
  last.setUTCMonth(last.getUTCMonth() - m);
  const start = last.toISOString().slice(0, 10);
  const i = points.findIndex(p => p.date >= start);
  return i < 0 ? 0 : i;
}

function line(id, labels, values, color, unitFmt, note) {
  const cfg = { type: 'line', data: { labels, datasets: [{ data: values, borderColor: color, borderWidth: 1.8, pointRadius: 0, tension: .15, fill: false }] },
    options: { responsive: true, maintainAspectRatio: false, animation: false, interaction: { mode: 'index', intersect: false },
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ` ${unitFmt(c.parsed.y)}` } } },
      scales: { x: { ticks: { maxTicksLimit: 8, font: { size: 11 }, callback: (v, i) => labels[i]?.slice(2, 7) }, grid: { display: false } },
        y: { position: 'right', ticks: { callback: v => unitFmt(v), font: { size: 11 } }, grid: { color: GRID } } } } };
  if (charts[id]) { charts[id].data = cfg.data; charts[id].options = cfg.options; charts[id].update('none'); } else charts[id] = new Chart($(id), cfg);
  const lo = Math.min(...values), hi = Math.max(...values), ch = values.at(-1) - values[0];
  $(note).innerHTML = `${labels[0]} → ${labels.at(-1)} · 구간 변화 <b class="${cls(ch)}">${sign(ch)}${unitFmt(ch)}</b> · 최저 ${unitFmt(lo)} · 최고 ${unitFmt(hi)}`;
}

function draw() {
  if (iEnd - iStart < 1) iStart = Math.max(0, iEnd - 1);
  const pts = data.points.slice(iStart, iEnd + 1);
  const labels = pts.map(p => p.date);
  $('#period-note').textContent = `${labels[0]} ~ ${labels.at(-1)} · ${pts.length}영업일`;
  readout(pts);
  line('#chart-deposit', labels, pts.map(p => jo(p.deposit)), RED, v => `${fmt(v, 1)}조`, '#note-deposit');
  line('#chart-credit', labels, pts.map(p => jo(p.credit)), BLUE, v => `${fmt(v, 1)}조`, '#note-credit');
  line('#chart-ratio', labels, pts.map(p => p.credit / p.deposit * 100), GREEN, v => `${fmt(v, 1)}%`, '#note-ratio');
}

function readout(pts) {
  const a = pts[0], x = pts.at(-1);
  $('#sel-start').textContent = a.date; $('#sel-end').textContent = x.date;
  $('#sel-deposit').textContent = `${fmt(jo(x.deposit), 2)}조`;
  $('#sel-credit').textContent = `${fmt(jo(x.credit), 2)}조`;
  $('#sel-ratio').textContent = `${fmt(x.credit / x.deposit * 100, 1)}%`;
  const dd = jo(x.deposit - a.deposit), dc = jo(x.credit - a.credit);
  $('#sel-change').innerHTML = `<span class="${cls(dd)}">${sign(dd)}${fmt(dd, 2)}조</span> / <span class="${cls(dc)}">${sign(dc)}${fmt(dc, 2)}조</span>`;
  const n = data.points.length - 1;
  $('#dual-fill').style.left = `${iStart / n * 100}%`; $('#dual-fill').style.width = `${(iEnd - iStart) / n * 100}%`;
}

function stats() {
  const p = data.points, L = p.at(-1), P = p.at(-2) || L;
  const r = x => x.credit / x.deposit * 100;
  const card = (k, v, d, unit, dd = 1) => `<div class="stat"><div class="k">${k}</div><div class="v">${v} <small>${unit}</small></div><div class="s ${cls(d)}">전일 대비 ${sign(d)}${fmt(d, dd)}${unit === '%' ? '%p' : unit}</div></div>`;
  $('#credit-stat').innerHTML =
    card('고객예탁금', fmt(jo(L.deposit), 2), jo(L.deposit - P.deposit), '조원', 2) +
    card('신용융자 잔고', fmt(jo(L.credit), 2), jo(L.credit - P.credit), '조원', 2) +
    card('신용융자 / 예탁금', fmt(r(L), 1), r(L) - r(P), '%');
  $('#credit-asof').textContent = `기준일 ${L.date} (금융투자협회 집계, 보통 2영업일 지연) · 수집 ${kst(data.collectedAt)}${data.status === 'stale' ? ' · 이전 자료' : ''}`;
  const rows = p.slice(-15).reverse().map((x, i) => { const prev = p[p.length - 1 - i - 1] || x;
    return `<tr><td>${x.date}</td><td>${fmt(jo(x.deposit), 2)}</td><td class="${cls(x.deposit - prev.deposit)}">${sign(x.deposit - prev.deposit)}${fmt(jo(x.deposit - prev.deposit), 2)}</td><td>${fmt(jo(x.credit), 2)}</td><td class="${cls(x.credit - prev.credit)}">${sign(x.credit - prev.credit)}${fmt(jo(x.credit - prev.credit), 2)}</td><td>${fmt(r(x), 1)}%</td></tr>`; }).join('');
  $('#credit-table').innerHTML = `<table><thead><tr><th>날짜</th><th>예탁금 (조)</th><th>전일비</th><th>신용융자 (조)</th><th>전일비</th><th>비율</th></tr></thead><tbody>${rows}</tbody></table>`;
}

/* 구간 슬라이더: 끌면 차트가 즉시 바뀜 */
const sStart = $('#slider-start'), sEnd = $('#slider-end');
let raf = null;
const schedule = () => { if (raf) return; raf = requestAnimationFrame(() => { raf = null; draw(); }); };
const clearTabs = () => document.querySelectorAll('#range .tab').forEach(x => x.classList.remove('on'));
sStart.addEventListener('input', () => { iStart = Math.min(+sStart.value, iEnd - 1); sStart.value = iStart; clearTabs(); schedule(); });
sEnd.addEventListener('input', () => { iEnd = Math.max(+sEnd.value, iStart + 1); sEnd.value = iEnd; clearTabs(); schedule(); });

document.querySelectorAll('#range .tab').forEach(b => b.onclick = () => {
  document.querySelectorAll('#range .tab').forEach(x => x.classList.toggle('on', x === b));
  iEnd = data.points.length - 1; iStart = startIndexForMonths(data.points, +b.dataset.months);
  sStart.value = iStart; sEnd.value = iEnd; draw();
});

fetch(`data/credit.json?v=${Math.floor(Date.now() / 60000)}`).then(r => r.json()).then(d => {
  if (!d?.points?.length) throw 0;
  data = d; stats();
  sStart.max = sEnd.max = d.points.length - 1;
  iEnd = d.points.length - 1; iStart = startIndexForMonths(d.points, 12);
  sStart.value = iStart; sEnd.value = iEnd; draw();
}).catch(() => { $('#credit-stat').innerHTML = '<div class="empty">신용잔고 자료를 아직 수집하지 못했습니다. 다음 수집 때 표시됩니다.</div>'; });
