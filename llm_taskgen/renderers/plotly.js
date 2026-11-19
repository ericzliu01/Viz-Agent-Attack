function render(values, V) {
  const E = V.enc, L = V.labels, ct = V.chart_type;
  const ax = t => ({ title: { text: t }, gridcolor: "#e1e0d9", zeroline: false, linecolor: "#c9c8c1" });
  const layout = { paper_bgcolor: "#fcfcfb", plot_bgcolor: "#fcfcfb", width: 720, height: 400,
    margin: { l: 70, r: 40, t: 10, b: 60 }, font: { family: "system-ui, sans-serif", size: 12, color: "#52514e" },
    xaxis: ax(L[E.x]), yaxis: ax(L[E.y] || L[E.y]), legend: { title: { text: L[E.color] || "" } } };
  const traces = [];
  if (ct === "scatter") {
    for (const c of cats(values, V, E.color)) {
      const rs = values.filter(r => r[E.color] === c);
      traces.push({ type: "scatter", mode: "markers", name: c, x: rs.map(r => r[E.x]), y: rs.map(r => r[E.y]),
        marker: { color: V.palette[c], opacity: 0.7, size: rs.map(r => diameter(r[E.size], V)), sizemode: "diameter" },
        customdata: rs.map(r => r[E.size]),
        hovertemplate: L[E.x] + ": %{x}<br>" + L[E.y] + ": %{y}<br>" + L[E.size] + ": %{customdata}<extra>%{fullData.name}</extra>" });
    }
    layout.xaxis.range = V.x_domain; layout.yaxis.range = V.y_domain;
    layout.xaxis.dtick = 5; layout.yaxis.dtick = V.y_domain[1] - V.y_domain[0] > 300 ? 50 : 20; layout.xaxis.tick0 = 0; layout.yaxis.tick0 = 0;
  } else if (ct === "grouped_bar") {
    const xs = cats(values, V, E.x);
    for (const g of cats(values, V, E.group)) {
      const rs = xs.map(x => values.find(r => r[E.x] === x && r[E.group] === g));
      traces.push({ type: "bar", name: g, x: xs, y: rs.map(r => r[E.y]), marker: { color: V.palette[g] } });
    }
    layout.barmode = "group"; layout.yaxis.range = V.y_domain; layout.yaxis.dtick = 10; layout.legend.title.text = L[E.group];
    // Decoy outline as shapes, so the legend swatches keep no border.
    const gs = cats(values, V, E.group), bw = 0.8 / gs.length;
    layout.shapes = values.filter(r => isHighlighted(V, r)).map(r => {
      const x0 = xs.indexOf(r[E.x]) - 0.4 + gs.indexOf(r[E.group]) * bw;
      return { type: "rect", xref: "x", yref: "y", x0, x1: x0 + bw, y0: 0, y1: r[E.y], line: { color: "#111111", width: 3 } };
    });
  } else if (ct === "line") {
    for (const c of cats(values, V, E.color)) for (const m of cats(values, V, E.line_style)) {
      const rs = values.filter(r => r[E.color] === c && r[E.line_style] === m).sort((a, b) => a[E.x] - b[E.x]);
      const dash = V.dash[m], dual = rs.length && isDual(V, rs[0]);
      traces.push({ type: "scatter", mode: "lines", name: c + ", " + m, x: rs.map(r => r[E.x]), y: rs.map(r => r[E.y]),
        line: { color: V.palette[c], width: 2, dash: dash[1] === 0 ? "solid" : dash[0] + "px," + dash[1] + "px" },
        yaxis: dual ? "y2" : "y" });
    }
    layout.yaxis.rangemode = "tozero"; layout.yaxis.dtick = 2 * V.gridstep;
    layout.xaxis.dtick = 2; layout.legend.title.text = L[E.color] + " / " + L[E.line_style];
    if (V.dual) { layout.yaxis2 = { ...ax(V.dual.title), overlaying: "y", side: "right", range: V.dual.domain, showgrid: false }; layout.legend.x = 1.12; }
  } else if (ct === "stacked_bar") {
    const xs = cats(values, V, E.x);
    for (const s of V.stack_order) {
      const rs = xs.map(x => values.find(r => r[E.x] === x && r[E.stack] === s));
      traces.push({ type: "bar", name: s, x: xs.map(String), y: rs.map(r => r[E.y]), marker: { color: V.palette[s] } });
    }
    layout.barmode = "stack"; layout.xaxis.type = "category"; layout.legend.title.text = L[E.stack];
  } else if (ct === "heatmap") {
    const xs = cats(values, V, E.x), ys = cats(values, V, E.y), [lo, hi] = V.heat.domain;
    const z = ys.map(y => xs.map(x => { const r = values.find(r => r[E.x] === x && r[E.y] === y); return r ? r[E.color] : null; }));
    traces.push({ type: "heatmap", x: xs, y: ys, z, zmin: lo, zmax: hi, xgap: 2, ygap: 2, hoverongaps: false,
      colorscale: V.heat.stops.map(([v, c]) => [(v - lo) / (hi - lo), c]), showscale: false });
    layout.yaxis.autorange = "reversed"; layout.yaxis.title.text = L[E.y]; layout.margin.l = 130; layout.yaxis.title.standoff = 10; layout.xaxis.title.text = L[E.x];
    layout.xaxis.showgrid = false; layout.yaxis.showgrid = false;
    layout.annotations = [];
    ys.forEach((y, i) => xs.forEach((x, j) => { if (z[i][j] === null) layout.annotations.push({ x, y, text: "n<10", showarrow: false, font: { color: "#898781", size: 11 } }); }));
    if (V.highlight) {
      const j = xs.indexOf(V.highlight[E.x]), i = ys.indexOf(V.highlight[E.y]);
      layout.shapes = [{ type: "rect", x0: j - 0.5, x1: j + 0.5, y0: i - 0.5, y1: i + 0.5, line: { color: "#e8590c", width: 4 } }];
    }
  }
  Plotly.newPlot("chart", traces, layout, { displayModeBar: false, staticPlot: false });
  htmlLegend(V);
}
