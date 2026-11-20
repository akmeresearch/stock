/* AI 지표: 메모리 현물·계약가, 추이, 전망, 리서치 요약 */
(() => {
  const $ = s => document.querySelector(s);
  const v = Math.floor(Date.now() / 60000);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmt = (n, d = 2) => n == null ? '—' : (+n).toLocaleString('ko-KR', { maximumFractionDigits: d, minimumFractionDigits: n >= 100 ? 0 : d });
  const sgn = n => n == null ? '' : n > 0 ? '+' : '';
  const cls = n => n > 0 ? 'up' : n < 0 ? 'down' : '';
  const PAL = ['#2f6df6', '#f59e0b', '#10b981', '#ef4444', '#8b5cf6', '#0ea5e9', '#64748b', '#d946ef'];
  const SHORT = { 'DDR5 16Gb (2Gx8) 4800/5600': 'DDR5 16Gb', 'DDR5 16Gb (2Gx8) eTT': 'DDR5 16Gb eTT', 'DDR4 16Gb (2Gx8) 3200': 'DDR4 16Gb', 'DDR4 16Gb (2Gx8) eTT': 'DDR4 16Gb eTT',
    'DDR4 8Gb (1Gx8) 3200': 'DDR4 8Gb', 'DDR4 8Gb (1Gx8) eTT': 'DDR4 8Gb eTT', 'DDR3 4Gb 512Mx8 1600/1866': 'DDR3 4Gb', '512Gb TLC': 'NAND 512Gb TLC 웨이퍼', '256Gb TLC': 'NAND 256Gb TLC 웨이퍼',
    '128Gb TLC': 'NAND 128Gb TLC 웨이퍼', 'DDR5 RDIMM 32GB 4800/5600': 'DDR5 RDIMM 32GB (서버 모듈)', 'DDR5 UDIMM 16GB 4800/5600': 'DDR5 UDIMM 16GB', 'DDR4 UDIMM 16GB 3200': 'DDR4 UDIMM 16GB', 'GDDR6 8Gb': 'GDDR6 8Gb', 'GDDR5 8Gb': 'GDDR5 8Gb' };
  const short = k => SHORT[k] || k;
  let P = null, O = null, trendChart = null, fcChart = null;
  let trendSel = new Set(), trendMonths = 6, fcMarket = 'DRAM';

  /* ---------- 관련 종목 ---------- */
  async function related() {
    const list = [['005930', '삼성전자'], ['000660', 'SK하이닉스'], ['MU', 'Micron'], ['NVDA', 'NVIDIA']];
    const out = [];
    for (const [t, name] of list) {
      try {
        const p = await (await fetch(`data/prices/${t}.json?v=${v}`)).json();
        const usd = p.currency === 'USD';
        out.push(`<a class="ai-rel" href="stock.html?code=${t}"><span>${name}</span><b class="${cls(p.changePercent)}">${usd ? '$' + fmt(p.price, 2) : fmt(p.price, 0)}</b><small class="${cls(p.changePercent)}">${sgn(p.changePercent)}${fmt(p.changePercent, 2)}%</small></a>`);
      } catch {}
    }
    try {
      const ind = await (await fetch(`data/indicators.json?v=${v}`)).json();
      for (const id of ['sox', 'nasdaq']) {
        const it = (ind.items || []).find(x => x.id === id); if (!it || it.price == null) continue;
        out.push(`<span class="ai-rel"><span>${it.name}</span><b class="${cls(it.changePercent)}">${fmt(it.price, 0)}</b><small class="${cls(it.changePercent)}">${sgn(it.changePercent)}${fmt(it.changePercent, 2)}%</small></span>`);
      }
    } catch {}
    $('#related').innerHTML = out.join('');
  }

  /* ---------- 현물가 카드 ---------- */
  function spark(canvas, vals) {
    if (!vals.length) return;
    const up = vals[vals.length - 1] >= vals[0];
    new Chart(canvas, { type: 'line', data: { labels: vals.map((_, i) => i), datasets: [{ data: vals, borderColor: up ? '#d93025' : '#1a73e8', borderWidth: 1.5, pointRadius: 0, tension: .3 }] },
      options: { responsive: true, maintainAspectRatio: false, animation: false, plugins: { legend: { display: false }, tooltip: { enabled: false } }, scales: { x: { display: false }, y: { display: false } } } });
  }
  function spotCards() {
    const items = P.items || {}, keys = (P.keyItems || []).filter(k => items[k]);
    const spot = Object.keys(items).filter(k => /spot$/.test(items[k].group) && !keys.includes(k));
    const all = [...keys, ...spot];
    $('#spot-cards').innerHTML = all.map(k => {
      const it = items[k], h = it.history, last = h[h.length - 1], prev = h.length > 1 ? h[h.length - 2] : null;
      const chg = last[2] != null ? last[2] : (prev ? (last[1] / prev[1] - 1) * 100 : null);
      const wk = h.filter(x => x[0] >= dayShift(last[0], -7))[0], mo = h.filter(x => x[0] >= dayShift(last[0], -30))[0];
      const pc = (a, b) => (a && b && a[1] && a[0] !== b[0]) ? `${sgn(b[1] / a[1] - 1)}${fmt((b[1] / a[1] - 1) * 100, 1)}%` : '—';
      return `<div class="ind ai-ind" data-k="${esc(k)}">
        <div class="meta">${esc(it.label)}</div>
        <div class="title">${esc(short(k))}</div>
        <div class="v">$${fmt(last[1], last[1] >= 100 ? 1 : 3)}</div>
        <div class="c ${cls(chg)}">${chg == null ? '—' : `${sgn(chg)}${fmt(chg, 2)}%`} <small>세션</small></div>
        <div class="p"><span>1주 <b class="${cls(parseFloat(pc(wk, last)))}">${pc(wk, last)}</b></span><span>1개월 <b class="${cls(parseFloat(pc(mo, last)))}">${pc(mo, last)}</b></span><span>${last[0]}</span></div>
        <div class="spark"><canvas></canvas></div></div>`;
    }).join('') || '<div class="empty">아직 수집된 현물가가 없습니다.</div>';
    all.forEach((k, i) => spark($('#spot-cards').children[i].querySelector('canvas'), items[k].history.slice(-60).map(x => x[1])));
    $('#spot-cards').addEventListener('click', e => { const c = e.target.closest('.ai-ind'); if (!c) return; toggleTrend(c.dataset.k, true); });
  }
  const dayShift = (d, n) => { const t = new Date(d + 'T00:00:00Z'); t.setUTCDate(t.getUTCDate() + n); return t.toISOString().slice(0, 10); };

  /* ---------- 추이 차트 ---------- */
  function trendButtons() {
    const items = P.items || {};
    const cands = [...(P.keyItems || []), ...Object.keys(items).filter(k => /spot$/.test(items[k].group))].filter((k, i, a) => items[k] && a.indexOf(k) === i);
    $('#trend-items').innerHTML = cands.map(k => `<button class="tab${trendSel.has(k) ? ' on' : ''}" data-k="${esc(k)}">${esc(short(k))}</button>`).join('');
  }
  function toggleTrend(k, only) {
    if (only) trendSel = new Set([k]); else if (trendSel.has(k)) { if (trendSel.size > 1) trendSel.delete(k); } else trendSel.add(k);
    trendButtons(); drawTrend();
  }
  $('#trend-items').addEventListener('click', e => { const b = e.target.closest('.tab'); if (b) toggleTrend(b.dataset.k, false); });
  $('#trend-period').addEventListener('click', e => { const b = e.target.closest('.tab'); if (!b) return; trendMonths = +b.dataset.m; document.querySelectorAll('#trend-period .tab').forEach(t => t.classList.toggle('on', t === b)); drawTrend(); });
  $('#trend-norm').addEventListener('change', drawTrend);
  function drawTrend() {
    const items = P.items || {}, norm = $('#trend-norm').checked;
    const since = trendMonths ? dayShift(new Date().toISOString().slice(0, 10), -30 * trendMonths) : '0000';
    const sel = [...trendSel].filter(k => items[k]);
    const dates = [...new Set(sel.flatMap(k => items[k].history.filter(h => h[0] >= since).map(h => h[0])))].sort();
    const toX = d => Date.parse(d + 'T00:00:00Z') / 864e5, fromX = x => new Date(Math.round(x) * 864e5).toISOString().slice(2, 10);
    const datasets = sel.map((k, i) => {
      const hs = items[k].history.filter(h => h[0] >= since);
      const first = hs[0]?.[1] || 1;
      return { label: short(k), data: hs.map(h => ({ x: toX(h[0]), y: norm ? h[1] / first * 100 : h[1], src: h[4] })), borderColor: PAL[i % PAL.length], backgroundColor: PAL[i % PAL.length], borderWidth: 2, pointRadius: hs.length > 80 ? 0 : 2.5, tension: .2, spanGaps: true, yAxisID: norm || sel.length === 1 ? 'y' : (i === 0 ? 'y' : 'y2') };
    });
    const multi = !norm && sel.length > 1;
    const cfg = { type: 'line', data: { datasets }, options: { responsive: true, maintainAspectRatio: false, parsing: false, interaction: { mode: 'nearest', axis: 'x', intersect: false },
      plugins: { legend: { position: 'bottom', labels: { boxWidth: 10, font: { size: 11 } } }, tooltip: { callbacks: { title: it => fromX(it[0].parsed.x), label: c => `${c.dataset.label}: ${norm ? fmt(c.parsed.y, 1) : '$' + fmt(c.parsed.y, 3)}${c.raw.src === 'weekly' ? ' (주간 기사)' : ''}` } } },
      scales: { x: { type: 'linear', grid: { display: false }, ticks: { maxTicksLimit: 10, font: { size: 11 }, callback: x => fromX(x) } },
        y: { position: 'left', grid: { color: 'rgba(0,0,0,.06)' }, ticks: { font: { size: 11 }, callback: x => norm ? x : '$' + fmt(x, 1) } },
        ...(multi ? { y2: { position: 'right', grid: { display: false }, ticks: { font: { size: 11 }, callback: x => '$' + fmt(x, 1) } } } : {}) } } };
    if (trendChart) { trendChart.data = cfg.data; trendChart.options = cfg.options; trendChart.update(); } else trendChart = new Chart($('#trend'), cfg);
    const n = sel.reduce((a, k) => a + items[k].history.filter(h => h[0] >= since).length, 0);
    const wk = sel.some(k => items[k].history.some(h => h[4] === 'weekly'));
    $('#trend-note').textContent = `${dates.length}일 · ${n}개 관측${wk ? ' · 일부 구간은 TrendForce 주간 기사에서 백필(주 1점)' : ''}${multi ? ' · 두 번째 품목은 오른쪽 축' : ''}`;
  }

  /* ---------- 계약가 ---------- */
  function contract() {
    const items = P.items || {}, groups = P.groups || {};
    const gids = ['dram_contract', 'nand_contract', 'ssd_contract'];
    $('#contract').innerHTML = gids.map(g => {
      const ks = Object.keys(items).filter(k => items[k].group === g); if (!ks.length) return '';
      return `<div class="ai-table"><div class="ai-table-h">${esc(groups[g] || g)}</div><table><thead><tr><th>품목</th><th>평균</th><th>고/저</th><th>변동</th><th>기준</th></tr></thead><tbody>` +
        ks.map(k => { const h = items[k].history, l = h[h.length - 1]; const hl = l[3] || []; return `<tr><td>${esc(k)}</td><td><b>$${fmt(l[1], 2)}</b></td><td>${hl[0] != null ? `${fmt(hl[0], 2)} / ${fmt(hl[1], 2)}` : '—'}</td><td class="${cls(l[2])}">${l[2] == null ? '—' : sgn(l[2]) + fmt(l[2], 2) + '%'}</td><td>${l[0]}</td></tr>`; }).join('') + '</tbody></table></div>';
    }).join('') || '<div class="empty">계약가 미수집</div>';
    const s = P.sessions || {};
    const lu = [...(s.dram?.lastUpdate || []), ...(s.nand?.lastUpdate || [])];
    $('#asof').textContent = `수집 ${(P.updatedAt || '').slice(0, 16).replace('T', ' ')} · TrendForce 세션 ${lu[0] || ''}`;
  }

  /* ---------- 전망 ---------- */
  function forecastTabs() {
    const ms = [...new Set((O.forecasts || []).map(f => f.market))];
    if (!ms.includes(fcMarket)) fcMarket = ms[0];
    $('#fc-market').innerHTML = ms.map(m => `<button class="tab${m === fcMarket ? ' on' : ''}" data-m="${esc(m)}">${esc(m)}</button>`).join('');
  }
  $('#fc-market').addEventListener('click', e => { const b = e.target.closest('.tab'); if (!b) return; fcMarket = b.dataset.m; forecastTabs(); drawForecast(); });
  const qkey = p => { const m = /(\d)Q(\d\d)/.exec(p); return m ? `20${m[2]}Q${m[1]}` : p; };
  function drawForecast() {
    const fs = (O.forecasts || []).filter(f => f.market === fcMarket && /QoQ|YoY|ASP|현물/.test(f.metric || '') && (f.low != null || f.high != null));
    const periods = [...new Set(fs.map(f => f.period))].sort((a, b) => qkey(a).localeCompare(qkey(b)));
    const segs = [...new Set(fs.map(f => f.segment))];
    const datasets = segs.map((s, i) => ({ label: s, data: periods.map(p => { const f = fs.find(x => x.segment === s && x.period === p); if (!f) return null; const lo = f.low ?? f.high, hi = f.high ?? f.low; return (lo + hi) / 2; }),
      backgroundColor: PAL[i % PAL.length] + 'cc', borderRadius: 3, _rng: periods.map(p => { const f = fs.find(x => x.segment === s && x.period === p); return f ? f.text : ''; }) }));
    const cfg = { type: 'bar', data: { labels: periods, datasets }, options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: 'bottom', labels: { boxWidth: 10, font: { size: 11 } } }, tooltip: { callbacks: { label: c => `${c.dataset.label}: ${c.dataset._rng[c.dataIndex] || fmt(c.parsed.y, 1) + '%'}` } } },
      scales: { x: { grid: { display: false } }, y: { grid: { color: 'rgba(0,0,0,.06)' }, ticks: { callback: x => x + '%' } } } } };
    if (fcChart) { fcChart.data = cfg.data; fcChart.options = cfg.options; fcChart.update(); } else fcChart = new Chart($('#forecast'), cfg);
    const rows = (O.forecasts || []).filter(f => f.market === fcMarket).sort((a, b) => qkey(a.period).localeCompare(qkey(b.period)) || a.segment.localeCompare(b.segment, 'ko'));
    $('#fc-table').innerHTML = `<div class="ai-table"><table><thead><tr><th>세그먼트</th><th>기간</th><th>지표</th><th>전망</th><th>이전</th><th>출처</th></tr></thead><tbody>` +
      rows.map(f => `<tr><td>${esc(f.segment)}</td><td>${esc(f.period)}</td><td>${esc(f.metric)}</td><td><b>${esc(f.text)}</b></td><td class="muted">${esc(f.prev || '')}</td><td><a href="${esc(f.url)}" target="_blank" rel="noopener">${esc(f.source)} ${esc(f.date)}</a></td></tr>`).join('') + '</tbody></table></div>';
  }

  /* ---------- 요약 ---------- */
  function research() {
    $('#summary').innerHTML = O.summary_md ? marked.parse(O.summary_md) : '<div class="empty">요약 미생성</div>';
    const block = (title, arr, dir) => arr?.length ? `<div class="ai-pt"><div class="ai-table-h">${title}</div><ul>${arr.map(x => `<li>${dir && x.direction ? `<span class="badge dir-${esc(x.direction)}">${{ up: '상승 요인', down: '하락 요인', mixed: '혼재' }[x.direction] || x.direction}</span> ` : ''}${esc(x.text)} <a class="src" href="${esc(x.url)}" target="_blank" rel="noopener">(${esc(x.source)} ${esc(x.date)})</a></li>`).join('')}</ul></div>` : '';
    $('#points').innerHTML = block('HBM', O.hbm) + block('가격 변수', O.drivers, true) + block('현물 시장 코멘트', O.spot_view);
    $('#sources').innerHTML = (O.sources || []).map(s => `<li><a href="${esc(s.url)}" target="_blank" rel="noopener">[${esc(s.source)}] ${esc(s.date)} ${esc(s.title)}</a></li>`).join('');
    const upd = O.updatedAt ? ` · 전망 갱신 ${O.updatedAt.slice(0, 10)}` : '';
    $('#asof').textContent += upd;
  }

  /* ---------- 시작 ---------- */
  (async () => {
    related();
    try { P = await (await fetch(`data/memory_prices.json?v=${v}`)).json(); } catch { P = { items: {} }; }
    try { O = await (await fetch(`data/memory_outlook.json?v=${v}`)).json(); } catch { O = { forecasts: [] }; }
    if (!Object.keys(P.items || {}).length) {
      $('#spot-cards').innerHTML = '<div class="empty">현물가가 아직 수집되지 않았습니다. 평일 11:40 · 18:40에 갱신됩니다.</div>';
    } else {
      spotCards();
      trendSel = new Set((P.keyItems || []).filter(k => P.items[k]).slice(0, 1));
      if (!trendSel.size) trendSel = new Set(Object.keys(P.items).slice(0, 1));
      trendButtons(); drawTrend(); contract();
    }
    if ((O.forecasts || []).length) { forecastTabs(); drawForecast(); }
    else $('#fc-table').innerHTML = '<div class="empty">전망 자료가 아직 없습니다. 매주 월요일 아침 갱신됩니다.</div>';
    research();
  })();
})();
