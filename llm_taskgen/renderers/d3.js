function render(values, V) {
  const E = V.enc, L = V.labels, ct = V.chart_type;
  const W = 760, H = 400, m = { l: 70, r: ct === "line" ? (V.dual ? 250 : 190) : 170, t: 10, b: 50 }, iw = W - m.l - m.r, ih = H - m.t - m.b;
  const svg = d3.select("#chart").append("svg").attr("width", W).attr("height", H)
    .attr("font-family", "system-ui, sans-serif").attr("font-size", 12);
  const g = svg.append("g").attr("transform", `translate(${m.l},${m.t})`);
  const axisStyle = s => s.call(a => a.selectAll("text").attr("fill", "#52514e")).call(a => a.selectAll("line,path").attr("stroke", "#c9c8c1"));
  const xTitle = t => svg.append("text").attr("x", m.l + iw / 2).attr("y", H - 10).attr("text-anchor", "middle").attr("fill", "#52514e").attr("font-weight", 600).text(t);
  const yTitle = (t, x = 16) => svg.append("text").attr("transform", `translate(${x},${m.t + ih / 2}) rotate(-90)`).attr("text-anchor", "middle").attr("fill", "#52514e").attr("font-weight", 600).text(t);
  const grid = (y, ticks) => g.append("g").selectAll("line").data(y.ticks(ticks)).join("line").attr("x1", 0).attr("x2", iw).attr("y1", y).attr("y2", y).attr("stroke", "#e1e0d9");
  const legend = (title, items) => {  // items: [[label, color, dash]]
    const lg = svg.append("g").attr("transform", `translate(${W - m.r + (V.dual ? 60 : 20)},${m.t + 10})`);
    lg.append("text").attr("font-weight", 600).attr("fill", "#52514e").text(title);
    items.forEach(([lab, col, dash], i) => {
      const it = lg.append("g").attr("transform", `translate(0,${18 + i * 18})`);
      if (dash !== undefined) it.append("line").attr("x1", 0).attr("x2", 22).attr("y1", -4).attr("y2", -4).attr("stroke", col).attr("stroke-width", 2).attr("stroke-dasharray", dash);
      else it.append("rect").attr("y", -10).attr("width", 12).attr("height", 12).attr("fill", col);
      it.append("text").attr("x", 28).attr("fill", "#52514e").text(lab);
    });
  };
  const tip = (sel, f) => hoverTip(sel, typeof f === "function" ? f : () => f);
  if (ct === "scatter") {
    const x = d3.scaleLinear().domain(V.x_domain).range([0, iw]);
    const y = d3.scaleLinear().domain(V.y_domain).range([ih, 0]);
    grid(y, 8);
    g.append("g").attr("transform", `translate(0,${ih})`).call(d3.axisBottom(x)).call(axisStyle);
    g.append("g").call(d3.axisLeft(y)).call(axisStyle);
    g.append("g").selectAll("circle").data(values).join("circle").attr("cx", r => x(r[E.x])).attr("cy", r => y(r[E.y]))
      .attr("r", r => diameter(r[E.size], V) / 2).attr("fill", r => V.palette[r[E.color]]).attr("fill-opacity", 0.7)
      .call(s => tip(s, r => `${r[E.color]}: ${L[E.x]} ${r[E.x]}, ${L[E.y]} ${r[E.y]}, ${L[E.size]} ${r[E.size]}`));
    xTitle(L[E.x]); yTitle(L[E.y]);
    legend(L[E.color], cats(values, V, E.color).map(c => [c, V.palette[c]]));
  } else if (ct === "grouped_bar") {
    const xs = cats(values, V, E.x), gs = cats(values, V, E.group);
    const x0 = d3.scaleBand().domain(xs).range([0, iw]).padding(0.2), x1 = d3.scaleBand().domain(gs).range([0, x0.bandwidth()]);
    const y = d3.scaleLinear().domain(V.y_domain).range([ih, 0]);
    grid(y, 10);
    g.append("g").attr("transform", `translate(0,${ih})`).call(d3.axisBottom(x0)).call(axisStyle);
    g.append("g").call(d3.axisLeft(y)).call(axisStyle);
    g.append("g").selectAll("rect").data(values).join("rect").attr("x", r => x0(r[E.x]) + x1(r[E.group])).attr("width", x1.bandwidth())
      .attr("y", r => y(r[E.y])).attr("height", r => ih - y(r[E.y])).attr("fill", r => V.palette[r[E.group]])
      .attr("stroke", r => isHighlighted(V, r) ? "#111111" : "none").attr("stroke-width", r => isHighlighted(V, r) ? 3 : 0)
      .call(s => tip(s, r => `${r[E.x]}, ${r[E.group]}: ${r[E.y]}`));
    xTitle(L[E.x]); yTitle(L[E.y]);
    legend(L[E.group], gs.map(c => [c, V.palette[c]]));
  } else if (ct === "line") {
    const x = d3.scaleLinear().domain(d3.extent(values, r => r[E.x])).range([0, iw]);
    const prim = values.filter(r => !isDual(V, r));
    const y = d3.scaleLinear().domain([0, d3.max(prim, r => r[E.y])]).nice().range([ih, 0]);
    grid(y, 12);
    g.append("g").attr("transform", `translate(0,${ih})`).call(d3.axisBottom(x).tickFormat(d3.format("d")).ticks(12)).call(axisStyle);
    g.append("g").call(d3.axisLeft(y).ticks(12)).call(axisStyle);
    const y2 = V.dual ? d3.scaleLinear().domain(V.dual.domain).range([ih, 0]) : null;
    if (y2) { g.append("g").attr("transform", `translate(${iw},0)`).call(d3.axisRight(y2)).call(axisStyle); yTitle(V.dual.title, m.l + iw + 50); }
    const series = d3.groups(values, r => r[E.color], r => r[E.line_style]);
    for (const [c, ms] of series) for (const [mm, rs] of ms) {
      const yy = isDual(V, rs[0]) ? y2 : y, dash = V.dash[mm];
      g.append("path").datum(rs.sort((a, b) => a[E.x] - b[E.x])).attr("fill", "none").attr("stroke", V.palette[c]).attr("stroke-width", 2)
        .attr("stroke-dasharray", dash[1] === 0 ? null : dash.join(",")).attr("d", d3.line().x(r => x(r[E.x])).y(r => yy(r[E.y])))
        .call(s => tip(s, `${c}, ${mm}`));
    }
    xTitle(L[E.x]); yTitle(L[E.y]);
    // Two legends, as in Vega-Lite: color = country, dash = measure.
    legend(L[E.color], cats(values, V, E.color).map(c => [c, V.palette[c], "none"]));
    const n = cats(values, V, E.color).length, lg2 = svg.append("g").attr("transform", `translate(${W - m.r + (V.dual ? 60 : 20)},${m.t + 10 + 18 * (n + 2)})`);
    lg2.append("text").attr("font-weight", 600).attr("fill", "#52514e").text(L[E.line_style]);
    cats(values, V, E.line_style).forEach((mm, i) => {
      const it = lg2.append("g").attr("transform", `translate(0,${18 + i * 18})`);
      it.append("line").attr("x1", 0).attr("x2", 22).attr("y1", -4).attr("y2", -4).attr("stroke", "#52514e").attr("stroke-width", 2)
        .attr("stroke-dasharray", V.dash[mm][1] === 0 ? "none" : V.dash[mm].join(","));
      it.append("text").attr("x", 28).attr("fill", "#52514e").text(mm);
    });
  } else if (ct === "stacked_bar") {
    const xs = cats(values, V, E.x);
    const wide = xs.map(xv => Object.fromEntries([["_x", xv], ...V.stack_order.map(s => [s, values.find(r => r[E.x] === xv && r[E.stack] === s)[E.y]])]));
    const stack = d3.stack().keys(V.stack_order)(wide);
    const x = d3.scaleBand().domain(xs).range([0, iw]).padding(0.15);
    const y = d3.scaleLinear().domain([0, d3.max(stack[stack.length - 1], d => d[1])]).nice().range([ih, 0]);
    grid(y, 6);
    g.append("g").attr("transform", `translate(0,${ih})`).call(d3.axisBottom(x)).call(axisStyle);
    g.append("g").call(d3.axisLeft(y).ticks(6)).call(axisStyle);
    for (const layer of stack) g.append("g").selectAll("rect").data(layer).join("rect").attr("x", d => x(d.data._x)).attr("width", x.bandwidth())
      .attr("y", d => y(d[1])).attr("height", d => y(d[0]) - y(d[1])).attr("fill", V.palette[layer.key])
      .call(s => tip(s, d => `${d.data._x}, ${layer.key}: ${d.data[layer.key]}`));
    xTitle(L[E.x]); yTitle(L[E.y]);
    legend(L[E.stack], [...V.stack_order].map(s => [s, V.palette[s]]));
  } else if (ct === "heatmap") {
    const xs = cats(values, V, E.x), ys = cats(values, V, E.y);
    m.l = 120;
    g.attr("transform", `translate(${m.l},${m.t})`);
    const w = W - m.l - m.r;
    const x = d3.scaleBand().domain(xs).range([0, w]), y = d3.scaleBand().domain(ys).range([0, ih - 60]);
    g.append("g").attr("transform", `translate(0,${ih - 60})`).call(d3.axisBottom(x)).call(axisStyle);
    g.append("g").call(d3.axisLeft(y)).call(axisStyle);
    g.append("g").selectAll("rect").data(values.filter(r => r[E.color] !== null)).join("rect")
      .attr("x", r => x(r[E.x]) + 1).attr("y", r => y(r[E.y]) + 1).attr("width", x.bandwidth() - 2).attr("height", y.bandwidth() - 2)
      .attr("fill", r => interp(V.heat.stops, r[E.color])).call(s => tip(s, r => `${r[E.x]}, ${r[E.y]}: ${r[E.color]}%`));
    g.append("g").selectAll("text").data(values.filter(r => r[E.color] === null)).join("text").attr("x", r => x(r[E.x]) + x.bandwidth() / 2)
      .attr("y", r => y(r[E.y]) + y.bandwidth() / 2 + 4).attr("text-anchor", "middle").attr("fill", "#898781").attr("font-size", 11).text("n<10");
    const hl = values.find(r => isHighlighted(V, r));
    if (hl) g.append("rect").attr("x", x(hl[E.x]) + 2).attr("y", y(hl[E.y]) + 2).attr("width", x.bandwidth() - 4).attr("height", y.bandwidth() - 4)
      .attr("fill", "none").attr("stroke", "#e8590c").attr("stroke-width", 4);
    svg.append("text").attr("x", m.l + w / 2).attr("y", m.t + ih - 20).attr("text-anchor", "middle").attr("fill", "#52514e").attr("font-weight", 600).text(L[E.x]);
    yTitle(L[E.y], 14);
  }
  htmlLegend(V);
}
