/* 마크다운 리포트 안의 ```chart JSON 블록을 Chart.js 차트로 바꾼다.
   형식: {"type":"bar|line|stacked","title":"...","unit":"억원","labels":[...],
          "series":[{"name":"매출액","data":[...]},{"name":"영업이익률","data":[...],"type":"line","axis":"right","unit":"%"}]} */
(function () {
  const PALETTE = ['#2f6df6', '#f59e0b', '#10b981', '#ef4444', '#8b5cf6', '#64748b', '#0ea5e9', '#d946ef'];
  const fmt = (v, unit) => v == null ? '' : (Math.abs(v) >= 1000 ? v.toLocaleString('ko-KR', { maximumFractionDigits: 0 }) : v.toLocaleString('ko-KR', { maximumFractionDigits: 1 })) + (unit ? ' ' + unit : '');
  function render(container) {
    if (!window.Chart) return;
    container.querySelectorAll('pre > code.language-chart').forEach(code => {
      let spec; try { spec = JSON.parse(code.textContent); } catch { return; }
      if (!spec || !Array.isArray(spec.labels) || !Array.isArray(spec.series)) return;
      const box = document.createElement('figure'); box.className = 'md-chart';
      box.innerHTML = `${spec.title ? `<figcaption>${spec.title}${spec.unit ? ` <small>(${spec.unit})</small>` : ''}</figcaption>` : ''}<div class="md-chart-box"><canvas></canvas></div>${spec.note ? `<div class="md-chart-note">${spec.note}</div>` : ''}`;
      code.parentElement.replaceWith(box);
      const stacked = spec.type === 'stacked';
      const hasRight = spec.series.some(s => s.axis === 'right');
      const datasets = spec.series.map((s, i) => {
        const c = s.color || PALETTE[i % PALETTE.length], line = (s.type || (spec.type === 'line' ? 'line' : 'bar')) === 'line';
        return { label: s.name, data: s.data.map(v => v == null ? null : +v), type: line ? 'line' : 'bar',
          backgroundColor: line ? c : c + 'cc', borderColor: c, borderWidth: line ? 2 : 0, borderRadius: line ? 0 : 3,
          tension: 0.25, pointRadius: line ? 3 : 0, spanGaps: true, yAxisID: s.axis === 'right' ? 'y2' : 'y', order: line ? 0 : 1, _unit: s.unit || (s.axis === 'right' ? '' : spec.unit || '') };
      });
      new Chart(box.querySelector('canvas'), { type: 'bar', data: { labels: spec.labels, datasets }, options: {
        responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
        plugins: { legend: { display: datasets.length > 1, position: 'bottom', labels: { boxWidth: 10, font: { size: 11 } } },
          tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${fmt(ctx.parsed.y, ctx.dataset._unit)}` } } },
        scales: { x: { stacked, grid: { display: false }, ticks: { font: { size: 11 }, maxRotation: 0, autoSkip: true } },
          y: { stacked, position: 'left', grid: { color: 'rgba(0,0,0,.06)' }, ticks: { font: { size: 11 }, callback: v => fmt(v) } },
          ...(hasRight ? { y2: { position: 'right', grid: { display: false }, ticks: { font: { size: 11 }, callback: v => fmt(v, spec.series.find(s => s.axis === 'right')?.unit || '') } } } : {}) } } });
    });
  }
  window.renderMdCharts = render;
})();
