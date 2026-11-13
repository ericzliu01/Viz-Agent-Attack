function render(values, V) {
  const E = V.enc, L = V.labels, ct = V.chart_type;
  const el = document.getElementById("chart");
  el.innerHTML = "<canvas id='cv' width='720' height='400'></canvas>";
  const font = { family: "system-ui, sans-serif", size: 12 };
  Chart.defaults.color = "#52514e"; Chart.defaults.font = font; Chart.defaults.borderColor = "#e1e0d9";
  const axis = (t, extra) => ({ title: { display: true, text: t }, ...(extra || {}) });
  const cfg = { options: { responsive: false, animation: false, plugins: { legend: { position: "right", labels: { boxWidth: 12 } } }, scales: {} } };
  const S = cfg.options.scales;
  if (ct === "scatter") {
    cfg.type = "bubble";
    cfg.data = { datasets: cats(values, V, E.color).map(c => ({ label: c,
      data: values.filter(r => r[E.color] === c).map(r => ({ x: r[E.x], y: r[E.y], r: diameter(r[E.size], V) / 2, v: r[E.size] })),
      backgroundColor: V.palette[c] + "b3", borderWidth: 0 })) };
    S.x = axis(L[E.x], { type: "linear", min: V.x_domain[0], max: V.x_domain[1], ticks: { stepSize: 5 } });
    S.y = axis(L[E.y], { min: V.y_domain[0], max: V.y_domain[1], ticks: { stepSize: V.y_domain[1] - V.y_domain[0] > 300 ? 50 : 20 } });
    cfg.options.plugins.legend.title = { display: true, text: L[E.color], font: { weight: "bold" } };
    cfg.options.plugins.tooltip = { callbacks: { label: c => c.dataset.label + ": " + L[E.x] + " " + c.raw.x + ", " + L[E.y] + " " + c.raw.y + ", " + L[E.size] + " " + c.raw.v } };
  } else if (ct === "grouped_bar") {
    const xs = cats(values, V, E.x);
    cfg.type = "bar";
    cfg.data = { labels: xs, datasets: cats(values, V, E.group).map(g => {
      const rs = xs.map(x => values.find(r => r[E.x] === x && r[E.group] === g));
      return { label: g, data: rs.map(r => r[E.y]), backgroundColor: V.palette[g],
        borderColor: rs.map(r => isHighlighted(V, r) ? "#111111" : "rgba(0,0,0,0)"),
        borderWidth: rs.map(r => isHighlighted(V, r) ? 3 : 0) }; }) };
    S.x = axis(L[E.x]); S.y = axis(L[E.y], { min: V.y_domain[0], max: V.y_domain[1], ticks: { stepSize: 10 } });
    // Legend swatches without the decoy outline.
    cfg.options.plugins.legend.title = { display: true, text: L[E.group], font: { weight: "bold" } };
    cfg.options.plugins.legend.labels.generateLabels = ch => Chart.defaults.plugins.legend.labels.generateLabels(ch).map(it => ({ ...it, lineWidth: 0, strokeStyle: "rgba(0,0,0,0)" }));
  } else if (ct === "line") {
    cfg.type = "line";
    const ds = [];
    for (const c of cats(values, V, E.color)) for (const m of cats(values, V, E.line_style)) {
      const rs = values.filter(r => r[E.color] === c && r[E.line_style] === m).sort((a, b) => a[E.x] - b[E.x]);
      const dash = V.dash[m];
      ds.push({ label: c + ", " + m, data: rs.map(r => ({ x: r[E.x], y: r[E.y] })), borderColor: V.palette[c],
        backgroundColor: V.palette[c], borderDash: dash[1] === 0 ? [] : dash, borderWidth: 2, pointRadius: 0,
        yAxisID: rs.length && isDual(V, rs[0]) ? "y2" : "y" });
    }
    cfg.data = { datasets: ds };
    S.x = axis(L[E.x], { type: "linear", ticks: { stepSize: 2, callback: v => String(v) } });
    S.y = axis(L[E.y], { beginAtZero: true, ticks: { stepSize: V.gridstep } });
    if (V.dual) S.y2 = axis(V.dual.title, { position: "right", min: V.dual.domain[0], max: V.dual.domain[1], grid: { drawOnChartArea: false } });
    // Legend samples drawn with each series' own dash pattern (a small canvas per item).
    const sample = d => { const c = document.createElement("canvas"); c.width = 30; c.height = 10;
      const x = c.getContext("2d"); x.strokeStyle = d.borderColor; x.lineWidth = 2; x.setLineDash(d.borderDash || []);
      x.beginPath(); x.moveTo(0, 5); x.lineTo(30, 5); x.stroke(); return c; };
    cfg.options.plugins.legend = { position: "bottom", title: { display: true, text: L[E.color] + " / " + L[E.line_style], font: { weight: "bold" } },
      labels: { usePointStyle: true, pointStyleWidth: 30, padding: 14, generateLabels: ch => ch.data.datasets.map((d, i) => ({
        text: d.label, datasetIndex: i, pointStyle: sample(d), hidden: !ch.isDatasetVisible(i), fontColor: "#52514e" })) } };
  } else if (ct === "stacked_bar") {
    const xs = cats(values, V, E.x);
    cfg.type = "bar";
    cfg.data = { labels: xs.map(String), datasets: V.stack_order.map(s => ({ label: s,
      data: xs.map(x => values.find(r => r[E.x] === x && r[E.stack] === s)[E.y]), backgroundColor: V.palette[s] })) };
    S.x = axis(L[E.x], { stacked: true }); S.y = axis(L[E.y], { stacked: true, beginAtZero: true });
    cfg.options.plugins.legend.title = { display: true, text: L[E.stack], font: { weight: "bold" } };
  } else if (ct === "heatmap") {
    // Chart.js 4 has no heatmap: draw the cells on two category axes with an inline plugin.
    const xs = cats(values, V, E.x), ys = cats(values, V, E.y);
    cfg.type = "scatter";
    cfg.data = { datasets: [{ label: L[E.color], data: values.map(r => ({ x: r[E.x], y: r[E.y], v: r[E.color] })), pointRadius: 0, pointHitRadius: 20 }] };
    S.x = axis(L[E.x], { type: "category", labels: xs, offset: true, grid: { display: false } });
    S.y = axis(L[E.y], { type: "category", labels: ys, offset: true, grid: { display: false } });
    cfg.options.plugins.legend = { display: false };
    cfg.options.plugins.tooltip = { callbacks: { label: c => c.raw.x + ", " + c.raw.y + ": " + (c.raw.v === null ? "n<10" : c.raw.v + "%") } };
    cfg.plugins = [{ id: "cells", beforeDatasetsDraw(chart) {
      const x = chart.scales.x, y = chart.scales.y, ctx = chart.ctx;
      const w = (x.right - x.left) / xs.length, h = (y.bottom - y.top) / ys.length;
      for (const r of values) {
        const cx = x.getPixelForValue(xs.indexOf(r[E.x])), cy = y.getPixelForValue(ys.indexOf(r[E.y]));
        if (r[E.color] === null) { ctx.fillStyle = "#898781"; ctx.font = "11px system-ui, sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText("n<10", cx, cy); continue; }
        ctx.fillStyle = interp(V.heat.stops, r[E.color]); ctx.fillRect(cx - w / 2 + 1, cy - h / 2 + 1, w - 2, h - 2);
        if (isHighlighted(V, r)) { ctx.strokeStyle = "#e8590c"; ctx.lineWidth = 4; ctx.strokeRect(cx - w / 2 + 2, cy - h / 2 + 2, w - 4, h - 4); }
      }
    } }];
  }
  new Chart(document.getElementById("cv"), cfg);
  htmlLegend(V);
}
