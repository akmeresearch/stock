/* 종목 스크린: 전체 상장종목 + 사용자 클래스(S~P)·메모.
   base   = data/screen.json (GitHub에 저장된 것)
   dirty  = localStorage 'akme_screen_dirty' (아직 GitHub에 안 올린 변경, 저장 성공 시 비움)
   표시값 = dirty > base > (ETF면 'P') */
(() => {
  const REPO = 'akmeresearch/stock', PATH = 'data/screen.json';
  const CLASSES = ['S', 'A', 'B', 'C', 'D', 'F', 'P'];
  const RANK = Object.fromEntries(CLASSES.map((c, i) => [c, i]));
  const LS_DIRTY = 'akme_screen_dirty', LS_TOKEN = 'akme_gh_token';
  const LS_SIZE = 'akme_screen_size';
  const v = Math.floor(Date.now() / 60000);
  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const ls = { get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
               set(k, val) { try { localStorage.setItem(k, JSON.stringify(val)); } catch {} },
               del(k) { try { localStorage.removeItem(k); } catch {} } };

  let listing = [], base = {}, dirty = ls.get(LS_DIRTY, {});
  let sortKey = 'cls', sortDir = 1, view = [], page = 1, size = +ls.get(LS_SIZE, 10) || 10;

  const entry = code => dirty[code] ?? base[code] ?? null;
  const clsOf = s => { const e = entry(s.code); return e && 'c' in e ? e.c : (s.etf ? 'P' : ''); };
  const memoOf = s => (entry(s.code)?.m) ?? '';
  const rank = s => { const c = clsOf(s); return c in RANK ? RANK[c] : CLASSES.length; };

  function setDirty(code, patch) {
    const cur = { ...(base[code] || {}), ...(dirty[code] || {}), ...patch };
    dirty[code] = cur; ls.set(LS_DIRTY, dirty); stats();
  }

  /* ---------- 데이터 ---------- */
  async function load() {
    const [l, b] = await Promise.all([
      fetch(`data/listing.json?v=${v}`).then(r => r.ok ? r.json() : Promise.reject(r.status)),
      fetch(`data/screen.json?v=${v}`).then(r => r.ok ? r.json() : { items: {} }).catch(() => ({ items: {} })),
    ]);
    listing = l.items || []; base = b.items || {};
    const upd = l.updatedAt ? ` · 목록 ${l.updatedAt.slice(0, 10)}` : '';
    $('stats').dataset.upd = upd;
    apply();
  }

  /* ---------- 필터·정렬·렌더 ---------- */
  function apply() {
    const q = $('q').value.trim().toLowerCase(), mk = $('mk').value, cf = $('cf').value, showP = cf === 'P' || $('showp').checked;
    view = listing.filter(s => {
      if (!showP && clsOf(s) === 'P') return false;   // P(Pass)는 기본 숨김
      if (mk === 'ETF' ? !s.etf : mk ? s.market !== mk : false) return false;
      if (cf === '_none' ? clsOf(s) !== '' : cf === '_memo' ? !memoOf(s) : cf ? clsOf(s) !== cf : false) return false;
      if (q && !(s.name.toLowerCase().includes(q) || s.code.includes(q) || (s.sector || '').toLowerCase().includes(q))) return false;
      return true;
    });
    const col = (a, b) => a.localeCompare(b, 'ko');
    view.sort((a, b) => {
      let d = 0;
      if (sortKey === 'cls') d = rank(a) - rank(b);
      else if (sortKey === 'sector') d = col(a.sector || '힣', b.sector || '힣');
      else d = col(a.name, b.name);
      return (d || col(a.name, b.name)) * (d ? sortDir : 1);
    });
    document.querySelectorAll('th.sortable').forEach(th => th.classList.toggle('on', th.dataset.k === sortKey));
    document.querySelector('th.on')?.setAttribute('data-dir', sortDir > 0 ? '▲' : '▼');
    page = Math.min(page, pages()) || 1; renderPage(); stats();
  }
  const pages = () => Math.max(1, Math.ceil(view.length / size));
  function goto(n) { page = Math.max(1, Math.min(pages(), n)); renderPage(); window.scrollTo({ top: $('pager-top').offsetTop - 70, behavior: 'smooth' }); }

  function row(s) {
    const c = clsOf(s), m = memoOf(s), d = dirty[s.code] ? ' dirty' : '';
    return `<tr data-code="${s.code}" class="c-${c || 'none'}${d}">
      <td class="sc-name"><a class="lnk" href="https://m.stock.naver.com/domestic/stock/${s.code}/total" target="_blank" rel="noopener">${esc(s.name)}</a>
        <div class="sc-meta">${s.code} · ${esc(s.market)}${s.products ? ' · ' + esc(s.products) : ''}</div></td>
      <td class="sc-sector">${esc(s.sector || '—')}</td>
      <td class="sc-cls"><select class="cls" data-code="${s.code}">
        <option value="">—</option>${CLASSES.map(x => `<option value="${x}"${x === c ? ' selected' : ''}>${x}</option>`).join('')}
      </select></td>
      <td class="sc-memo"><input class="memo" data-code="${s.code}" value="${esc(m)}" placeholder="메모" maxlength="200"></td>
    </tr>`;
  }

  function renderPage() {
    const slice = view.slice((page - 1) * size, page * size);
    $('rows').innerHTML = slice.length ? slice.map(row).join('') : '<tr><td colspan="4" class="empty">조건에 맞는 종목이 없습니다.</td></tr>';
    const n = pages(), from = view.length ? (page - 1) * size + 1 : 0, to = Math.min(view.length, page * size);
    for (const el of document.querySelectorAll('.sc-pager')) {
      el.innerHTML = `<button class="btn pg" data-go="1" ${page <= 1 ? 'disabled' : ''}>«</button>
        <button class="btn pg" data-go="${page - 1}" ${page <= 1 ? 'disabled' : ''}>‹ 이전</button>
        <span class="pg-info"><input class="pg-num" type="number" min="1" max="${n}" value="${page}"> / ${n.toLocaleString()} 페이지
          <small>(${from.toLocaleString()}–${to.toLocaleString()} / ${view.length.toLocaleString()})</small></span>
        <button class="btn pg" data-go="${page + 1}" ${page >= n ? 'disabled' : ''}>다음 ›</button>
        <button class="btn pg" data-go="${n}" ${page >= n ? 'disabled' : ''}>»</button>
        <select class="sc-select pg-size">${[10, 25, 50, 100].map(x => `<option value="${x}"${x === size ? ' selected' : ''}>${x}개씩</option>`).join('')}</select>`;
    }
  }
  document.addEventListener('click', e => { const b = e.target.closest('button.pg'); if (b && !b.disabled) goto(+b.dataset.go); });
  document.addEventListener('change', e => {
    if (e.target.classList.contains('pg-num')) goto(+e.target.value || 1);
    if (e.target.classList.contains('pg-size')) { size = +e.target.value; ls.set(LS_SIZE, size); page = 1; renderPage(); }
  });
  document.addEventListener('keydown', e => {
    if (e.target.classList.contains('pg-num') && e.key === 'Enter') { e.preventDefault(); goto(+e.target.value || 1); }
  });

  function stats() {
    const cnt = Object.fromEntries(CLASSES.map(c => [c, 0])); let none = 0;
    for (const s of listing) { const c = clsOf(s); c ? cnt[c]++ : none++; }
    const nd = Object.keys(dirty).length;
    $('stats').innerHTML = `<span>${listing.length.toLocaleString()}종목</span>` +
      CLASSES.map(c => `<span class="chip c-${c}">${c} ${cnt[c].toLocaleString()}</span>`).join('') +
      `<span class="chip">미분류 ${none.toLocaleString()}</span>` +
      (nd ? `<span class="chip warn">미저장 ${nd}</span>` : '<span class="chip ok">저장됨</span>') +
      `<span class="sc-upd">${$('stats').dataset.upd || ''}</span>`;
    $('save').disabled = !nd; $('save').textContent = nd ? `GitHub에 저장 (${nd})` : 'GitHub에 저장';
  }

  /* ---------- 입력 ---------- */
  const rows = $('rows');
  rows.addEventListener('change', e => {
    const t = e.target, code = t.dataset.code; if (!code) return;
    if (t.classList.contains('cls')) { setDirty(code, { c: t.value }); const tr = t.closest('tr'); tr.className = `c-${t.value || 'none'} dirty`; }
    else if (t.classList.contains('memo')) { setDirty(code, { m: t.value.trim() }); t.closest('tr').classList.add('dirty'); }
  });
  let deb;
  rows.addEventListener('input', e => {
    const t = e.target; if (!t.classList.contains('memo')) return;
    clearTimeout(deb); deb = setTimeout(() => { setDirty(t.dataset.code, { m: t.value.trim() }); t.closest('tr').classList.add('dirty'); }, 600);
  });
  // 메모에서 Enter → 다음 행 메모로
  rows.addEventListener('keydown', e => {
    if (e.key !== 'Enter' || !e.target.classList.contains('memo')) return;
    e.preventDefault(); e.target.blur();
    const nx = e.target.closest('tr').nextElementSibling?.querySelector('.memo');
    if (nx) nx.focus(); else if (page < pages()) { goto(page + 1); $('rows').querySelector('.memo')?.focus(); }
  });
  ['q', 'mk', 'cf', 'showp'].forEach(id => $(id).addEventListener('input', () => { page = 1; apply(); }));
  document.querySelectorAll('th.sortable').forEach(th => th.addEventListener('click', () => {
    if (sortKey === th.dataset.k) sortDir = -sortDir; else { sortKey = th.dataset.k; sortDir = 1; }
    apply();
  }));

  /* ---------- 저장 (GitHub Contents API) ---------- */
  const token = () => ls.get(LS_TOKEN, '');
  $('token').addEventListener('click', () => {
    const t = prompt('GitHub 토큰 (fine-grained, 저장소 stock 의 Contents: Read and write 권한).\n비우면 삭제합니다.', token() || '');
    if (t === null) return;
    t.trim() ? ls.set(LS_TOKEN, t.trim()) : ls.del(LS_TOKEN);
    alert(t.trim() ? '토큰을 이 브라우저에 저장했습니다.' : '토큰을 삭제했습니다.');
  });

  const b64 = s => { const u = new TextEncoder().encode(s); let b = ''; for (let i = 0; i < u.length; i += 8192) b += String.fromCharCode.apply(null, u.subarray(i, i + 8192)); return btoa(b); };
  const unb64 = s => new TextDecoder().decode(Uint8Array.from(atob(s.replace(/\n/g, '')), c => c.charCodeAt(0)));

  async function save() {
    if (!token()) { alert('먼저 ⚙ 버튼으로 GitHub 토큰을 넣어주세요.'); return; }
    const btn = $('save'); btn.disabled = true; btn.textContent = '저장 중…';
    try {
      const h = { Authorization: `Bearer ${token()}`, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28' };
      const url = `https://api.github.com/repos/${REPO}/contents/${PATH}`;
      // 최신 파일을 먼저 읽어 다른 기기에서 저장한 내용과 합친다
      let sha, remote = {};
      const g = await fetch(`${url}?ref=main&t=${Date.now()}`, { headers: h });
      if (g.ok) { const j = await g.json(); sha = j.sha; try { remote = JSON.parse(unb64(j.content)).items || {}; } catch {} }
      else if (g.status !== 404) throw new Error(`읽기 실패 ${g.status}`);
      const merged = { ...remote, ...dirty };
      for (const k of Object.keys(merged)) { const e = merged[k]; if (!e || ((e.c ?? '') === '' && !(e.m || ''))) delete merged[k]; }
      const items = Object.fromEntries(Object.keys(merged).sort().map(k => [k, merged[k]]));
      const body = { message: `screen: ${new Date().toISOString().slice(0, 16).replace('T', ' ')} ${Object.keys(dirty).length}건`, branch: 'main',
                     content: b64(JSON.stringify({ updatedAt: new Date().toISOString(), count: Object.keys(items).length, items }, null, 1) + '\n') };
      if (sha) body.sha = sha;
      const p = await fetch(url, { method: 'PUT', headers: { ...h, 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (!p.ok) throw new Error(`저장 실패 ${p.status}: ${(await p.json().catch(() => ({}))).message || ''}`);
      base = items; dirty = {}; ls.del(LS_DIRTY);
      document.querySelectorAll('tr.dirty').forEach(tr => tr.classList.remove('dirty'));
      stats();
    } catch (e) { alert(String(e.message || e)); stats(); }
  }
  $('save').addEventListener('click', save);

  /* ---------- 내보내기 / 가져오기 ---------- */
  $('export').addEventListener('click', () => {
    const items = {}; for (const s of listing) { const e = entry(s.code); if (e && ((e.c ?? '') !== '' || e.m)) items[s.code] = { ...e, name: s.name }; }
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([JSON.stringify({ exportedAt: new Date().toISOString(), items }, null, 1)], { type: 'application/json' }));
    a.download = `akme-screen-${new Date().toISOString().slice(0, 10)}.json`; a.click();
  });
  $('import').addEventListener('click', () => $('file').click());
  $('file').addEventListener('change', async e => {
    const f = e.target.files[0]; if (!f) return;
    try {
      const j = JSON.parse(await f.text()); const items = j.items || j; let n = 0;
      for (const [code, e2] of Object.entries(items)) { if (typeof e2 !== 'object') continue; const p = {}; if ('c' in e2) p.c = e2.c; if ('m' in e2) p.m = e2.m; if (Object.keys(p).length) { setDirty(code, p); n++; } }
      alert(`${n}건을 불러왔습니다. 'GitHub에 저장'을 누르면 사이트에 반영됩니다.`); apply();
    } catch { alert('JSON 파일을 읽지 못했습니다.'); }
    e.target.value = '';
  });

  load().catch(err => { $('rows').innerHTML = `<tr><td colspan="4" class="empty">종목 목록을 아직 수집하지 못했습니다 (${esc(err)}). 잠시 후 다시 열어주세요.</td></tr>`; });
})();
