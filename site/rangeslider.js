/* 공용 구간 슬라이더 (바 하나, 손잡이 둘). 왼쪽 = 시작, 오른쪽 = 끝.
   const rs = makeRangeSlider(el, { labels: [...날짜], onChange: (i0, i1) => {} }); rs.set(i0, i1); */
function makeRangeSlider(root, opts) {
  root.classList.add('rs');
  root.innerHTML = `<div class="rs-track"><div class="rs-fill"></div></div>
    <div class="rs-handle" role="slider" tabindex="0" aria-label="시작"><span class="rs-tip"></span></div>
    <div class="rs-handle" role="slider" tabindex="0" aria-label="끝"><span class="rs-tip"></span></div>`;
  const track = root.querySelector('.rs-track'), fill = root.querySelector('.rs-fill');
  const [ha, hb] = root.querySelectorAll('.rs-handle');
  let labels = opts.labels || [], a = 0, b = Math.max(1, labels.length - 1), raf = null;
  const n = () => Math.max(1, labels.length - 1);
  const place = () => {
    const pa = a / n() * 100, pb = b / n() * 100;
    fill.style.left = `${pa}%`; fill.style.width = `${pb - pa}%`;
    ha.style.left = `${pa}%`; hb.style.left = `${pb}%`;
    ha.querySelector('.rs-tip').textContent = (labels[a] || '').slice(2); hb.querySelector('.rs-tip').textContent = (labels[b] || '').slice(2);
  };
  const emit = () => { place(); if (raf) return; raf = requestAnimationFrame(() => { raf = null; opts.onChange?.(a, b); }); };
  const idxFromX = x => { const r = root.getBoundingClientRect(); return Math.round(Math.min(1, Math.max(0, (x - r.left) / r.width)) * n()); };
  const bind = (el, which) => {
    el.addEventListener('pointerdown', e => {
      e.preventDefault(); el.setPointerCapture(e.pointerId); el.classList.add('drag');
      const move = ev => { const i = idxFromX(ev.clientX); if (which === 'a') a = Math.min(i, b - 1); else b = Math.max(i, a + 1); emit(); };
      const up = () => { el.classList.remove('drag'); el.removeEventListener('pointermove', move); el.removeEventListener('pointerup', up); el.removeEventListener('pointercancel', up); };
      el.addEventListener('pointermove', move); el.addEventListener('pointerup', up); el.addEventListener('pointercancel', up);
    });
    el.addEventListener('keydown', e => { const d = e.key === 'ArrowLeft' ? -1 : e.key === 'ArrowRight' ? 1 : 0; if (!d) return; e.preventDefault();
      if (which === 'a') a = Math.max(0, Math.min(a + d, b - 1)); else b = Math.min(n(), Math.max(b + d, a + 1)); emit(); });
  };
  bind(ha, 'a'); bind(hb, 'b');
  track.addEventListener('pointerdown', e => { const i = idxFromX(e.clientX); if (Math.abs(i - a) < Math.abs(i - b)) a = Math.min(i, b - 1); else b = Math.max(i, a + 1); emit(); });
  return {
    set(i0, i1, silent) { a = Math.max(0, i0); b = Math.min(n(), i1); if (b - a < 1) a = Math.max(0, b - 1); place(); if (!silent) opts.onChange?.(a, b); },
    setLabels(l) { labels = l; b = Math.min(b, n()); place(); },
    get() { return [a, b]; },
  };
}
/* months 전 ~ 끝 인덱스 */
function startIndexForMonths(dates, m) {
  if (!m || !dates.length) return 0;
  const last = new Date(dates.at(-1) + 'T00:00:00Z'); last.setUTCMonth(last.getUTCMonth() - m);
  const s = last.toISOString().slice(0, 10); const i = dates.findIndex(d => d >= s); return i < 0 ? 0 : i;
}
