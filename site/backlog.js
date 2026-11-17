/* 수주잔고 페이지 — data/backlog.json (억원) */
const $ = s => document.querySelector(s);
const fmt = (n, d = 0) => n == null || !isFinite(n) ? '—' : n.toLocaleString('ko-KR', { minimumFractionDigits: d, maximumFractionDigits: d });
const sign = n => n == null ? '' : n > 0 ? '+' : '';
const cls = n => n == null ? '' : n > 0 ? 'up' : n < 0 ? 'down' : '';
const kst = iso => { if (!iso) return '—'; const d = new Date(iso); return isNaN(d) ? iso : d.toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }); };
const jo = eok => eok == null ? '—' : Math.abs(eok) >= 1e4 ? `${fmt(eok / 1e4, 2)}조` : `${fmt(eok)}억`;
const PALETTE = ['#d64545', '#2563eb', '#16a34a', '#f59e0b', '#7c3aed', '#0891b2', '#db2777', '#4b5563', '#84cc16', '#ea580c', '#0ea5e9', '#a855f7', '#14b8a6', '#9f1239'];
const GRID = '#eceff3';

let data = null, current = null, chart = null, cmpChart = null;
const qSort = (a, b) => a.localeCompare(b);
const qLabel = k => k.replace('Q', ' Q');
const series = c => Object.keys(c.quarters).sort(qSort).map(k => ({ q: k, ...c.quarters[k] }));
const disclosedSeries = c => series(c).filter(x => x.disclosed && x.backlog_eok != null);

function pctChange(cur, prev) { return prev ? (cur / prev - 1) * 100 : null; }

function overview() {
  const rows = Object.values(data.companies).map(c => {
    const s = disclosedSeries(c);
    if (!s.length) return { c, none: true, pending: !series(c).length, latestQ: series(c).at(-1)?.q };
    const L = s.at(-1), P = s.at(-2), Y = s.find(x => x.q === `${+L.q.slice(0, 4) - 1}${L.q.slice(4)}`);
    return { c, L, qoq: P ? pctChange(L.backlog_eok, P.backlog_eok) : null, yoy: Y ? pctChange(L.backlog_eok, Y.backlog_eok) : null, n: s.length };
  }).sort((a, b) => (b.L?.backlog_eok ?? -1) - (a.L?.backlog_eok ?? -1));
  $('#bl-table').innerHTML = `<table><thead><tr><th>기업</th><th>세그먼트</th><th>기준 분기</th><th>수주잔고</th><th>QoQ</th><th>YoY</th><th>공시 분기 수</th></tr></thead><tbody>${rows.map(r => r.none
    ? `<tr><td><span class="lnk" data-t="${r.c.ticker}">${r.c.name}</span></td><td>${r.c.segment}</td><td>${r.latestQ ? qLabel(r.latestQ) : '—'}</td><td colspan="4" style="color:var(--muted)">${r.pending ? '추출 대기 중' : '수주잔고 미공시'}</td></tr>`
    : `<tr><td><span class="lnk" data-t="${r.c.ticker}">${r.c.name}</span></td><td>${r.c.segment}</td><td>${qLabel(r.L.q)}</td><td><b>${jo(r.L.backlog_eok)}</b></td><td class="${cls(r.qoq)}">${r.qoq == null ? '—' : sign(r.qoq) + fmt(r.qoq, 1) + '%'}</td><td class="${cls(r.yoy)}">${r.yoy == null ? '—' : sign(r.yoy) + fmt(r.yoy, 1) + '%'}</td><td>${r.n}</td></tr>`).join('')}</tbody></table>
    <div class="note">갱신 ${kst(data.collectedAt)} · 기업명을 누르면 아래 차트가 바뀝니다.</div>`;
  $('#bl-table').querySelectorAll('.lnk').forEach(el => el.onclick = () => select(el.dataset.t));
  return rows.map(r => r.c);
}

function chips(order) {
  const el = $('#bl-companies');
  el.innerHTML = order.map(c => `<button class="tab" data-t="${c.ticker}">${c.name}</button>`).join('');
  el.querySelectorAll('.tab').forEach(b => b.onclick = () => select(b.dataset.t));
}

function select(t) {
  current = t;
  document.querySelectorAll('#bl-companies .tab').forEach(b => b.classList.toggle('on', b.dataset.t === t));
  const c = data.companies[t]; const s = series(c), d = disclosedSeries(c);
  $('#bl-title').textContent = `${c.name} 분기별 수주잔고`;
  if (!d.length) {
    $('#bl-stat').innerHTML = `<div class="empty">${s.length ? `${c.name}은(는) 정기보고서에 수주잔고를 공시하지 않습니다 (확인한 보고서 ${s.length}건).` : `${c.name}은(는) 아직 추출 전입니다. 추출이 끝나면 표시됩니다.`}</div>`;
    if (chart) { chart.destroy(); chart = null; }
    $('#bl-note').textContent = ''; $('#bl-detail').innerHTML = ''; return;
  }
  const L = d.at(-1), P = d.at(-2), Y = d.find(x => x.q === `${+L.q.slice(0, 4) - 1}${L.q.slice(4)}`);
  const qoq = P ? pctChange(L.backlog_eok, P.backlog_eok) : null, yoy = Y ? pctChange(L.backlog_eok, Y.backlog_eok) : null;
  $('#bl-stat').innerHTML = `
    <div class="stat"><div class="k">수주잔고 · ${qLabel(L.q)}</div><div class="v">${jo(L.backlog_eok)}</div><div class="s">기준일 ${L.as_of || '—'}</div></div>
    <div class="stat"><div class="k">전분기 대비</div><div class="v ${cls(qoq)}">${qoq == null ? '—' : sign(qoq) + fmt(qoq, 1) + '%'}</div><div class="s">${P ? `${qLabel(P.q)} ${jo(P.backlog_eok)}` : '비교 분기 없음'}</div></div>
    <div class="stat"><div class="k">전년 동기 대비</div><div class="v ${cls(yoy)}">${yoy == null ? '—' : sign(yoy) + fmt(yoy, 1) + '%'}</div><div class="s">${Y ? `${qLabel(Y.q)} ${jo(Y.backlog_eok)}` : '비교 분기 없음'}</div></div>
    ${L.order_total_eok != null ? `<div class="stat"><div class="k">수주총액 / 기납품액</div><div class="v" style="font-size:18px">${jo(L.order_total_eok)} / ${jo(L.delivered_eok)}</div><div class="s">${L.report_nm || ''}</div></div>` : ''}`;
  const labels = d.map(x => qLabel(x.q)), vals = d.map(x => x.backlog_eok);
  const cfg = { type: 'bar', data: { labels, datasets: [{ label: '수주잔고 (억원)', data: vals, backgroundColor: 'rgba(37,99,235,.75)', borderRadius: 4 }] },
    options: { responsive: true, maintainAspectRatio: false, animation: false, plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ` 수주잔고 ${jo(c.parsed.y)}` } } },
      scales: { x: { grid: { display: false }, ticks: { font: { size: 11 } } }, y: { ticks: { callback: v => jo(v), font: { size: 11 } }, grid: { color: GRID } } } } };
  if (chart) { chart.data = cfg.data; chart.options = cfg.options; chart.update('none'); } else chart = new Chart($('#bl-chart'), cfg);
  $('#bl-note').textContent = `${c.segment} · 공시 단위 ${L.unit || '—'} · ${L.note ? '비고: ' + L.note : ''}`;
  $('#bl-detail').innerHTML = `<table><thead><tr><th>분기</th><th>수주잔고</th><th>QoQ</th><th>수주총액</th><th>기납품액</th><th>기준일</th><th>품목별</th><th>원문</th></tr></thead><tbody>${d.slice().reverse().map((x, i, arr) => { const prev = arr[i + 1]; const q = prev ? pctChange(x.backlog_eok, prev.backlog_eok) : null;
    return `<tr><td>${qLabel(x.q)}</td><td><b>${jo(x.backlog_eok)}</b></td><td class="${cls(q)}">${q == null ? '—' : sign(q) + fmt(q, 1) + '%'}</td><td>${jo(x.order_total_eok)}</td><td>${jo(x.delivered_eok)}</td><td>${x.as_of || '—'}</td><td style="white-space:normal;font-size:12px">${(x.items || []).filter(i => i.backlog_eok != null).map(i => `${i.name} ${jo(i.backlog_eok)}`).join(' · ') || '—'}</td><td><a href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${x.rcept_no}" target="_blank" rel="noopener">DART</a></td></tr>`; }).join('')}</tbody></table>`;
}

function compare() {
  const sets = [];
  Object.values(data.companies).forEach((c, i) => {
    const d = disclosedSeries(c); if (d.length < 2) return;
    const base = d[0].backlog_eok; if (!base) return;
    sets.push({ label: c.name, data: d.map(x => ({ x: x.q, y: x.backlog_eok / base * 100 })), borderColor: PALETTE[i % PALETTE.length], borderWidth: 1.8, pointRadius: 2.5, tension: .15, fill: false });
  });
  if (!sets.length) return;
  const allQ = [...new Set(sets.flatMap(s => s.data.map(p => p.x)))].sort(qSort);
  const cfg = { type: 'line', data: { labels: allQ.map(qLabel), datasets: sets.map(s => ({ ...s, data: allQ.map(q => s.data.find(p => p.x === q)?.y ?? null), spanGaps: true })) },
    options: { responsive: true, maintainAspectRatio: false, animation: false, interaction: { mode: 'nearest', intersect: false },
      plugins: { legend: { position: 'bottom', labels: { boxWidth: 10, font: { size: 11 } } }, tooltip: { callbacks: { label: c => ` ${c.dataset.label} ${fmt(c.parsed.y, 0)}` } } },
      scales: { x: { grid: { display: false }, ticks: { font: { size: 11 } } }, y: { ticks: { callback: v => fmt(v), font: { size: 11 } }, grid: { color: GRID } } } } };
  if (cmpChart) { cmpChart.data = cfg.data; cmpChart.update('none'); } else cmpChart = new Chart($('#bl-compare'), cfg);
}

fetch(`data/backlog.json?v=${Math.floor(Date.now() / 60000)}`).then(r => r.json()).then(d => {
  data = d;
  if (!d.companies || !Object.keys(d.companies).length) throw 0;
  const order = overview(); chips(order); compare();
  const first = Object.values(d.companies).find(c => disclosedSeries(c).length) || Object.values(d.companies)[0];
  select(new URLSearchParams(location.search).get('t') || first.ticker);
}).catch(() => { $('#bl-table').innerHTML = '<div class="empty">수주잔고 자료를 아직 추출하지 못했습니다. 첫 추출이 끝나면 표시됩니다.</div>'; });
