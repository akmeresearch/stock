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
  const L = m.points.at(-1), last = L.foreignNet;
  const card = (k, v) => `<div class="stat"><div class="k">${k}</div><div class="v ${cls(v)}">${v == null ? '—' : sign(v) + fmt(v)} <small>억원</small></div><div class="s">${m.date} ${L.time} 누적</div></div>`;
  stat.innerHTML = card('외국인 순매수', L.foreignNet) + card('개인 순매수', L.indivNet) + card('기관 순매수', L.instNet) +
    `<div class="stat"><div class="k">${m.name}</div><div class="v ${cls(m.changePercent)}">${fmt(m.price, 2)} <small>${sign(m.changePercent)}${fmt(m.changePercent, 2)}%</small></div><div class="s">${kst(m.priceTime)} · ${m.marketStatus === 'OPEN' ? '장중' : '장 마감'}${m.status === 'stale' ? ' · 이전 자료' : ''}</div></div>`;
  note.textContent = `갱신 ${kst(m.collectedAt)} · ${marketData.source}`;

  const labels = m.prices.map(p => p.time);
  const series = key => { const map = new Map(m.points.map(p => [p.time, p[key]])); let carry = null; return labels.map(t => { if (map.has(t) && map.get(t) != null) carry = map.get(t); return carry; }); };
  const ctx = $('#flow-chart').getContext('2d');
  const cfg = {
    type: 'line',
    data: { labels, datasets: [
      { label: '외국인', data: series('foreignNet'), yAxisID: 'y', borderColor: COLORS.up, backgroundColor: 'rgba(214,69,69,.08)', fill: 'origin', borderWidth: 2, pointRadius: 0, tension: .2, spanGaps: true },
      { label: '개인', data: series('indivNet'), yAxisID: 'y', borderColor: '#16a34a', borderWidth: 1.6, pointRadius: 0, tension: .2, spanGaps: true },
      { label: '기관', data: series('instNet'), yAxisID: 'y', borderColor: COLORS.down, borderWidth: 1.6, pointRadius: 0, tension: .2, spanGaps: true },
      { label: m.name, data: m.prices.map(p => p.price), yAxisID: 'y1', borderColor: COLORS.line, borderWidth: 1.2, borderDash: [4, 3], pointRadius: 0, tension: .2 }
    ] },
    options: { responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false }, animation: false,
      plugins: { legend: { position: 'top', labels: { boxWidth: 10, font: { size: 11 } } }, tooltip: { callbacks: { label: c => c.dataset.yAxisID === 'y' ? ` ${c.dataset.label} ${sign(c.parsed.y)}${fmt(c.parsed.y)}억` : ` ${m.name} ${fmt(c.parsed.y, 2)}` } } },
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
        <div class="spark"><canvas data-id="${i.id}"></canvas></div>
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
        <div class="spark"><canvas data-id="${i.id}"></canvas></div>
        <div class="p">${Object.entries(i.comparisons || {}).map(([k, v]) => `<span>${{ '1w': '1주 전', '1m': '1개월 전', '1y': '1년 전' }[k]} <b>${fmt(v, i.digits)}</b></span>`).join('')}</div>
        <div class="s">${i.subtitle || ''} · ${i.asOf}</div>
      </div>`).join('');
    items.forEach(i => spark(el.querySelector(`canvas[data-id="${i.id}"]`), (i.points || []).slice(-90).map(p => p.value)));
    $('#sent-note').textContent = `갱신 ${kst(d.collectedAt)} · CNN Business / 세인트루이스 연준 FRED. 발표 주기가 달라 카드별 기준일을 확인하세요.`;
  } catch { el.innerHTML = '<div class="empty">보조지표를 아직 불러오지 못했습니다.</div>'; }
}

/* ---------- 0. 야간선물 · GDR/ADR · 코인 ---------- */
let ovData = null;
async function loadOverseas() {
  try { ovData = await (await fetch(bust('data/overseas.json'), { cache: 'no-store' })).json(); } catch { ovData = null; }
  drawOverseas();
}
function drawOverseas() {
  const el = $('#ov-grid'), d = ovData;
  if (!d) { el.innerHTML = '<div class="empty">자료를 아직 수집하지 못했습니다.</div>'; return; }
  const cards = [];
  const nf = d.nightFutures || {};
  if (['ok', 'stale'].includes(nf.status)) {
    cards.push(`<div class="ind ov-card">
      <div class="k">코스피200 야간선물 <span class="tag">${nf.code || ''}${nf.status === 'stale' ? ' · 이전' : ''}</span></div>
      <div class="v ${cls(nf.changePercent)}">${fmt(nf.price, 2)}</div>
      <div class="c ${cls(nf.change)}">${sign(nf.change)}${fmt(nf.change, 2)} (${sign(nf.changePercent)}${fmt(nf.changePercent, 2)}%)</div>
      <div class="p"><span>고 <b>${fmt(nf.high, 2)}</b></span><span>저 <b>${fmt(nf.low, 2)}</b></span>${nf.basis != null ? `<span>베이시스 <b>${fmt(nf.basis, 2)}</b></span>` : ''}${nf.volume != null ? `<span>거래량 <b>${fmt(nf.volume)}</b></span>` : ''}</div>
      <div class="s">KRX 야간시장 18:00~06:00 · 한국투자증권 · ${kst(nf.collectedAt)}</div></div>`);
  } else {
    cards.push(`<div class="ind ov-card"><div class="k">코스피200 야간선물</div><div class="empty" style="padding:12px 0">시세 확인 중 — 야간시장(18:00~06:00) 개장 후 표시됩니다.</div></div>`);
  }
  for (const g of d.depositary || []) {
    if (!['ok', 'stale'].includes(g.status)) continue;
    cards.push(`<div class="ind ov-card">
      <div class="k">${g.name} <span class="tag">${g.venue}${g.status === 'stale' ? ' · 이전' : ''}</span></div>
      <div class="v ${cls(g.changePercent)}">${g.currency === 'EUR' ? '€' : '$'}${fmt(g.price, 2)}</div>
      <div class="c ${cls(g.change)}">${sign(g.change)}${fmt(g.change, 2)} (${sign(g.changePercent)}${fmt(g.changePercent, 2)}%)</div>
      <div class="p">${g.impliedKrw ? `<span>원화 환산 <b>${fmt(g.impliedKrw)}원</b></span><span>국내 종가 <b>${fmt(g.krxPrice)}원</b></span><span>프리미엄 <b class="${cls(g.premiumPct)}">${sign(g.premiumPct)}${fmt(g.premiumPct, 1)}%</b></span>` : ''}</div>
      <div class="s">1단위 = 보통주 ${g.sharesPerUnit}주 · Yahoo Finance ${g.asOf} · 환율 ${fmt(g.fxToKrw, 1)}원/${g.currency}</div></div>`);
  }
  el.innerHTML = cards.join('') + `<div id="crypto-cards" class="crypto-row"></div>`;
  drawCrypto(d.crypto);
  $('#ov-note').textContent = `GDR/ADR 프리미엄 = (해외가 × 환율 ÷ 주당 환산) ÷ 국내 종가 − 1. 코인은 업비트 KRW 시세를 브라우저에서 10초마다 직접 갱신하며, 김치프리미엄은 코인베이스 USD × 환율 대비.`;
}
const CRYPTO = { BTC: '비트코인', ETH: '이더리움', XRP: '리플', SOL: '솔라나' };
function drawCrypto(c) {
  const el = $('#crypto-cards'); if (!el) return;
  const items = c?.items || {};
  el.innerHTML = Object.entries(CRYPTO).map(([sym, name]) => { const x = items[sym]; if (!x) return '';
    return `<div class="ind ov-card" data-sym="${sym}">
      <div class="k">${name} <span class="tag">${sym}</span></div>
      <div class="v ${cls(x.changePct24h)}" data-f="krw">${fmt(x.krw)}<small>원</small></div>
      <div class="c ${cls(x.changePct24h)}" data-f="chg">${sign(x.changePct24h)}${fmt(x.changePct24h, 2)}% <small>24h</small></div>
      <div class="p"><span>USD <b data-f="usd">${x.usd ? '$' + fmt(x.usd, x.usd < 10 ? 3 : 0) : '—'}</b></span><span>김프 <b data-f="kp" class="${cls(x.kimchiPremiumPct)}">${x.kimchiPremiumPct == null ? '—' : sign(x.kimchiPremiumPct) + fmt(x.kimchiPremiumPct, 1) + '%'}</b></span></div>
      <div class="s" data-f="t">업비트 · ${kst(c.collectedAt)}</div></div>`; }).join('');
}
async function liveCrypto() {
  if (document.hidden || !ovData) return;
  try {
    const syms = Object.keys(CRYPTO);
    const [up, bn] = await Promise.all([
      fetch('https://api.upbit.com/v1/ticker?markets=' + syms.map(s => 'KRW-' + s).join(',')).then(r => r.json()),
      Promise.all(syms.map(s => fetch(`https://api.coinbase.com/v2/prices/${s}-USD/spot`).then(r => r.json()).then(j => [s, +j.data.amount]).catch(() => [s, null]))),
    ]);
    const usd = Object.fromEntries(bn);
    const now = new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    for (const t of up) {
      const sym = t.market.split('-')[1], card = document.querySelector(`.ov-card[data-sym="${sym}"]`); if (!card) continue;
      const chg = t.signed_change_rate * 100, u = usd[sym], kp = u && ovData.usdkrw ? (t.trade_price / (u * ovData.usdkrw) - 1) * 100 : null;
      card.querySelector('[data-f=krw]').innerHTML = `${fmt(t.trade_price)}<small>원</small>`; card.querySelector('[data-f=krw]').className = `v ${cls(chg)}`;
      card.querySelector('[data-f=chg]').innerHTML = `${sign(chg)}${fmt(chg, 2)}% <small>24h</small>`; card.querySelector('[data-f=chg]').className = `c ${cls(chg)}`;
      if (u) card.querySelector('[data-f=usd]').textContent = '$' + fmt(u, u < 10 ? 3 : 0);
      const kpEl = card.querySelector('[data-f=kp]'); kpEl.textContent = kp == null ? '—' : sign(kp) + fmt(kp, 1) + '%'; kpEl.className = cls(kp);
      card.querySelector('[data-f=t]').textContent = `업비트 실시간 · ${now}`;
    }
  } catch { /* 네트워크 실패 시 스냅샷 유지 */ }
}

/* ---------- init ---------- */
function refreshAll() { loadOverseas(); loadMarket(); loadIndicators(); loadSentiment(); }
document.querySelectorAll('[data-refresh]').forEach(b => b.onclick = refreshAll);
refreshAll();
setInterval(() => { if (!document.hidden) { loadMarket(); loadOverseas(); } }, 5 * 60 * 1000);
setInterval(liveCrypto, 10 * 1000); setTimeout(liveCrypto, 1500);
