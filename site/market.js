/* 시장 현황 페이지 — data/market.json, data/indicators.json, data/sentiment.json 렌더링 */
const $ = s => document.querySelector(s);
const fmt = (n, d = 0) => n == null || !isFinite(n) ? '—' : n.toLocaleString('ko-KR', { minimumFractionDigits: d, maximumFractionDigits: d });
const sign = n => n == null ? '' : n > 0 ? '+' : '';
const cls = n => n == null ? '' : n > 0 ? 'up' : n < 0 ? 'down' : '';
const kst = iso => { if (!iso) return '—'; const d = new Date(iso); return isNaN(d) ? iso : d.toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }); };
const bust = u => `${u}?v=${Math.floor(Date.now() / 60000)}`;
const COLORS = { up: '#d64545', down: '#2563eb', line: '#111827', grid: '#eceff3', muted: '#6b7280' };

/* ---------- 1. 외국인 수급 × 지수 ---------- */
let marketData = null, activeMarket = 'KOSPI', flowChart = null;

async function loadMarket() {
  try {
    const r = await fetch(bust('data/market.json'), { cache: 'no-store' });
    marketData = await r.json();
  } catch { marketData = null; }
  drawMarket();
}

function drawMarket() {
  const m = marketData?.markets?.[activeMarket];
  const stat = $('#flow-stat'), note = $('#flow-note');
  if (!m || !['ok', 'stale'].includes(m.status) || !m.points?.length) {
    stat.innerHTML = '<div class="empty">수급 자료를 아직 확인하지 못했습니다. 다음 수집 때 다시 시도합니다.</div>';
    if (flowChart) { flowChart.destroy(); flowChart = null; }
    note.textContent = '';
    return;
  }
  const last = m.points.at(-1).foreignNet;
  stat.innerHTML = `
    <div class="stat"><div class="k">외국인 누적 순매수</div><div class="v ${cls(last)}">${sign(last)}${fmt(last)} <small>억원</small></div><div class="s">${m.date} ${m.points.at(-1).time} 기준</div></div>
    <div class="stat"><div class="k">${m.name}</div><div class="v ${cls(m.changePercent)}">${fmt(m.price, 2)} <small>${sign(m.changePercent)}${fmt(m.changePercent, 2)}%</small></div><div class="s">${kst(m.priceTime)} · ${m.marketStatus === 'OPEN' ? '장중' : '장 마감'}${m.status === 'stale' ? ' · 이전 자료' : ''}</div></div>`;
  note.textContent = `갱신 ${kst(m.collectedAt)} · ${marketData.source}`;

  const labels = m.prices.map(p => p.time);
  const flowMap = new Map(m.points.map(p => [p.time, p.foreignNet]));
  let carry = null;
  const flows = labels.map(t => { if (flowMap.has(t)) carry = flowMap.get(t); return carry; });
  const ctx = $('#flow-chart').getContext('2d');
  const cfg = {
    type: 'line',
    data: { labels, datasets: [
      { label: '외국인 순매수 (억원)', data: flows, yAxisID: 'y', borderColor: last >= 0 ? COLORS.up : COLORS.down, backgroundColor: (last >= 0 ? 'rgba(214,69,69,.10)' : 'rgba(37,99,235,.10)'), fill: 'origin', borderWidth: 2, pointRadius: 0, tension: .2, spanGaps: true },
      { label: m.name, data: m.prices.map(p => p.price), yAxisID: 'y1', borderColor: COLORS.line, borderWidth: 1.5, pointRadius: 0, tension: .2 }
    ] },
    options: { responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false }, animation: false,
      plugins: { legend: { position: 'top', labels: { boxWidth: 10, font: { size: 11 } } }, tooltip: { callbacks: { label: c => c.datasetIndex === 0 ? ` 외국인 ${sign(c.parsed.y)}${fmt(c.parsed.y)}억` : ` ${m.name} ${fmt(c.parsed.y, 2)}` } } },
      scales: { x: { ticks: { maxTicksLimit: 8, font: { size: 11 } }, grid: { display: false } },
        y: { position: 'left', ticks: { callback: v => fmt(v), font: { size: 11 } }, grid: { color: COLORS.grid } },
        y1: { position: 'right', ticks: { callback: v => fmt(v, 0), font: { size: 11 } }, grid: { display: false } } } }
  };
  if (flowChart) { flowChart.data = cfg.data; flowChart.options = cfg.options; flowChart.update(); } else flowChart = new Chart(ctx, cfg);
}

document.querySelectorAll('[data-market]').forEach(b => b.onclick = () => {
  activeMarket = b.dataset.market;
  document.querySelectorAll('[data-market]').forEach(x => x.classList.toggle('on', x === b));
  drawMarket();
});

/* ---------- 2. 주요 지표 ---------- */
async function loadIndicators() {
  const el = $('#ind-grid');
  try {
    const d = await (await fetch(bust('data/indicators.json'), { cache: 'no-store' })).json();
    const items = d.items.filter(i => ['ok', 'stale'].includes(i.status));
    if (!items.length) throw 0;
    el.innerHTML = items.map(i => `
      <div class="ind">
        <div class="k">${i.name} <span class="tag">${i.delayLabel || ''}${i.status === 'stale' ? ' · 이전' : ''}</span></div>
        <div class="v ${cls(i.changePercent)}">${fmt(i.price, i.digits)}<small>${i.unit === '%' ? '%' : ''}</small></div>
        <div class="c ${cls(i.change)}">${i.change == null ? '' : `${sign(i.change)}${fmt(i.change, i.unit === '%' ? 3 : i.digits)}`} ${i.changePercent == null ? '' : `(${sign(i.changePercent)}${fmt(i.changePercent, 2)}%)`}</div>
        <canvas class="spark" data-id="${i.id}" height="36"></canvas>
        <div class="p">${['1w', '1m', '3m'].map(k => `<span>${k === '1w' ? '1주' : k === '1m' ? '1개월' : '3개월'} <b class="${cls(i.perf?.[k])}">${i.perf?.[k] == null ? '—' : sign(i.perf[k]) + fmt(i.perf[k], 1) + '%'}</b></span>`).join('')}</div>
        <div class="s">${kst(i.quoteAt)}</div>
      </div>`).join('');
    items.forEach(i => spark(el.querySelector(`canvas[data-id="${i.id}"]`), (i.points || []).map(p => p.close)));
    $('#ind-note').textContent = `갱신 ${kst(d.collectedAt)} · ${d.source}`;
  } catch { el.innerHTML = '<div class="empty">주요 지표를 아직 불러오지 못했습니다.</div>'; }
}

function spark(canvas, vals) {
  if (!canvas || vals.length < 2) return;
  const up = vals.at(-1) >= vals[0];
  new Chart(canvas.getContext('2d'), { type: 'line', data: { labels: vals.map((_, i) => i), datasets: [{ data: vals, borderColor: up ? COLORS.up : COLORS.down, borderWidth: 1.5, pointRadius: 0, tension: .3, fill: false }] },
    options: { responsive: true, maintainAspectRatio: false, animation: false, plugins: { legend: { display: false }, tooltip: { enabled: false } }, scales: { x: { display: false }, y: { display: false } } } });
}

/* ---------- 3. 심리·보조지표 ---------- */
async function loadSentiment() {
  const el = $('#sent-grid');
  try {
    const d = await (await fetch(bust('data/sentiment.json'), { cache: 'no-store' })).json();
    const items = d.items.filter(i => ['ok', 'stale'].includes(i.status));
    if (!items.length) throw 0;
    const rate = r => ({ 'extreme fear': '극단적 공포', fear: '공포', neutral: '중립', greed: '탐욕', 'extreme greed': '극단적 탐욕' }[r] || r || '');
    el.innerHTML = items.map(i => `
      <div class="ind">
        <div class="k">${i.name}${i.status === 'stale' ? ' <span class="tag">이전</span>' : ''}</div>
        <div class="v">${fmt(i.value, i.digits)}${i.rating ? ` <small class="tag">${rate(i.rating)}</small>` : ''}</div>
        <div class="c ${cls(i.change)}">${i.change == null ? '' : `${sign(i.change)}${fmt(i.change, i.digits)} 전일 대비`}</div>
        <canvas class="spark" data-id="${i.id}" height="36"></canvas>
        <div class="p">${Object.entries(i.comparisons || {}).map(([k, v]) => `<span>${{ '1w': '1주 전', '1m': '1개월 전', '1y': '1년 전' }[k]} <b>${fmt(v, i.digits)}</b></span>`).join('')}</div>
        <div class="s">${i.subtitle || ''} · ${i.asOf}</div>
      </div>`).join('');
    items.forEach(i => spark(el.querySelector(`canvas[data-id="${i.id}"]`), (i.points || []).slice(-90).map(p => p.value)));
    $('#sent-note').textContent = `갱신 ${kst(d.collectedAt)} · CNN Business / 세인트루이스 연준 FRED. 발표 주기가 달라 카드별 기준일을 확인하세요.`;
  } catch { el.innerHTML = '<div class="empty">보조지표를 아직 불러오지 못했습니다.</div>'; }
}

/* ---------- init ---------- */
function refreshAll() { loadMarket(); loadIndicators(); loadSentiment(); }
document.querySelectorAll('[data-refresh]').forEach(b => b.onclick = refreshAll);
refreshAll();
setInterval(() => { if (!document.hidden) loadMarket(); }, 5 * 60 * 1000);
