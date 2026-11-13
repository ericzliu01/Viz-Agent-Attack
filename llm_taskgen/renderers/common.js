// Shared helpers for the llm_taskgen renderers. V is the view config built in pages.py.
function cats(values, V, f) { return V.order[f] || [...new Set(values.map(r => r[f]))]; }
function hexToRgb(h) { const n = parseInt(h.slice(1), 16); return [n >> 16 & 255, n >> 8 & 255, n & 255]; }
function interp(stops, v) {
  // stops: [[value, hex], ...] in data units, ascending
  if (v <= stops[0][0]) return stops[0][1];
  for (let i = 1; i < stops.length; i++) {
    if (v <= stops[i][0]) {
      const [v0, c0] = stops[i - 1], [v1, c1] = stops[i], t = (v - v0) / (v1 - v0 || 1);
      const a = hexToRgb(c0), b = hexToRgb(c1);
      return "rgb(" + a.map((x, k) => Math.round(x + (b[k] - x) * t)).join(",") + ")";
    }
  }
  return stops[stops.length - 1][1];
}
function diameter(v, V) {  // marker area proportional to the size field, 3-18 px diameter
  const [dmin, dmax] = V.size_px;
  return Math.sqrt(dmin * dmin + (dmax * dmax - dmin * dmin) * Math.max(0, v) / V.size_max);
}
function htmlLegend(V) {
  // Size legend (scatter) and color gradient legend (heatmap), as plain HTML under the chart.
  const box = document.getElementById("legend-extra");
  if (V.chart_type === "scatter") {
    const steps = []; for (let s = 0; s <= Math.floor(V.size_max); s++) steps.push(s);
    box.innerHTML = "<div class='lg-title'>" + V.labels[V.enc.size] + "</div>" + steps.map(s => {
      const d = diameter(s, V);
      return "<span class='lg-item'><span class='lg-dot' style='width:" + d + "px;height:" + d + "px'></span>" + s + "</span>";
    }).join("");
  } else if (V.chart_type === "heatmap") {
    const [lo, hi] = V.heat.domain, grad = V.heat.stops.map(([v, c]) => c + " " + (100 * (v - lo) / (hi - lo)) + "%").join(",");
    const ticks = []; for (let t = lo; t <= hi; t += (hi - lo) / 5) ticks.push(t);
    box.innerHTML = "<div class='lg-title'>" + V.labels[V.enc.color] + "</div><span class='lg-grad' style='background:linear-gradient(90deg," +
      grad + ")'>" + ticks.map(t => "<span class='lg-tick' style='left:" + (100 * (t - lo) / (hi - lo)) + "%'>" + Math.round(t) + "</span>").join("") + "</span>";
  }
}
function isHighlighted(V, row) {
  const h = V.highlight; if (!h) return false;
  return Object.entries(h).every(([k, v]) => row[k] === v);
}
function isDual(V, row) {
  const d = V.dual; if (!d) return false;
  return Object.entries(d.filter).every(([k, v]) => row[k] === v);
}
function hoverTip(sel, textFn) {
  // Hover tooltip like the other libraries': a div that exists only while the pointer is on a mark.
  const card = document.querySelector(".card");
  sel.on("mouseenter", (ev, d) => {
    const t = document.createElement("div"); t.className = "tip"; t.textContent = textFn(d);
    const r = card.getBoundingClientRect(); t.style.left = (ev.clientX - r.left + 12) + "px"; t.style.top = (ev.clientY - r.top + 12) + "px";
    card.appendChild(t);
  }).on("mouseleave", () => document.querySelectorAll(".card .tip").forEach(e => e.remove()));
}
