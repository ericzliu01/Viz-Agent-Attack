// Browser smoke check for llm_taskgen pages (run by tests/test_llm_taskgen.py).
// Usage: NODE_PATH=$(npm root -g) node llm_taskgen/browser_check.js <pages_dir> <examples.json> [--all]
// Default sample: every clean page in every library, plus every page-carrier TM page in Plotly
// (the library with the largest injected <head>). Exits 1 on any failure.
const { chromium } = require("playwright");
const fs = require("fs"), path = require("path");
const [ROOT_ARG, EXAMPLES] = process.argv.slice(2), ROOT = path.resolve(ROOT_ARG), ALL = process.argv.includes("--all");
const TEXT_LIMIT = 30000;  // browser_agent.TEXT_LIMIT: the 'dom' tool's cut-off
const ex = JSON.parse(fs.readFileSync(EXAMPLES));
const claims = {};
for (const c of ex.examples) for (const t of c.tasks) for (const a of t.attacks)
  if (a.claim_text) claims[`attack_lx_${a.technique}__lx_${t.task_id}.html`] = [a.technique, a.claim_text];
const PAGE_CARRIERS = ["dom_injection", "css_hidden_text", "alt_text_bias", "aria_deception", "automation_cloak"];

(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 960, height: 720 } });
  const fails = [];
  let n = 0;
  for (const lib of ["vega-lite", "plotly", "chartjs", "d3"]) {
    for (const f of fs.readdirSync(path.join(ROOT, lib)).filter(f => f.includes("lx_") && f.endsWith(".html")).sort()) {
      const tm = claims[f];
      const wanted = ALL || f.startsWith("clean_") || (lib === "plotly" && tm && PAGE_CARRIERS.includes(tm[0]));
      if (!wanted) continue;
      n++;
      const p = await ctx.newPage(), errs = [];
      p.on("pageerror", e => errs.push(String(e)));
      await p.goto("file://" + path.join(ROOT, lib, f));
      await p.waitForTimeout(900);
      const r = await p.evaluate(() => ({
        html: document.documentElement.outerHTML,
        marks: document.querySelectorAll("#chart svg path, #chart svg rect, #chart svg circle, #chart canvas").length,
        titles: document.querySelectorAll("#chart title").length,
        // Per-mark labels read "Field: value; Field: value"; axis and legend summaries are allowed.
        markAria: [...document.querySelectorAll("#chart [aria-label]")].filter(e => /:\s*[^;]+;/.test(e.getAttribute("aria-label"))).length,
      }));
      const bad = m => fails.push(`${lib}/${f}: ${m}`);
      if (errs.length) bad("page errors " + errs.join("; "));
      if (r.marks < 1) bad("no marks drawn");
      if (/application\/json/.test(r.html)) bad("data/view script still in the DOM");
      if (r.titles) bad(`${r.titles} <title> elements in the chart`);
      if (r.markAria) bad(`${r.markAria} per-mark aria-labels inside the chart`);
      if (r.html.indexOf("<body") > TEXT_LIMIT) bad("body starts after the dom tool cut-off");
      if (tm && PAGE_CARRIERS.includes(tm[0])) {
        const at = r.html.indexOf(tm[1].slice(0, 30).replace(/&/g, "&amp;").replace(/'/g, "&#x27;"));
        const atRaw = r.html.indexOf(tm[1].slice(0, 30));
        const pos = at >= 0 ? at : atRaw;
        if (pos < 0 || pos > TEXT_LIMIT) bad(`claim at ${pos}, outside the dom tool window`);
      }
      await p.close();
    }
  }
  await b.close();
  console.log(`${n} pages checked, ${fails.length} failures`);
  fails.forEach(f => console.log("FAIL " + f));
  process.exit(fails.length ? 1 : 0);
})();
