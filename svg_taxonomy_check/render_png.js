// Render the benchmark SVGs used by indices 0..N-1 to PNG (white background, 2x scale).
//   node svg_taxonomy_check/render_png.js ~/SVG_taxonomy out/png [N=5]
// Output keeps the repo's relative paths, e.g. out/png/images/bar/easy_labeled/bar_data_0.png
const { chromium } = require('playwright');
const fs = require('fs'), path = require('path');
(async () => {
  const [repo, out, nArg] = process.argv.slice(2);
  const n = Number(nArg || 5), files = [];
  for (const c of ['scatter', 'line', 'bar'])
    for (const cond of ['easy_unlabeled', 'easy_labeled', 'hard_unlabeled', 'hard_labeled'])
      for (let i = 0; i < n; i++) {
        files.push(`images/${c}/${cond}/${c}_data_${i}.svg`);
        files.push(`images/${c}/${cond}_distribution/data_${i}.svg`);
      }
  const b = await chromium.launch();
  const p = await b.newPage({ deviceScaleFactor: 2, viewport: { width: 576, height: 384 } });
  let k = 0;
  for (const f of files) {
    if (!fs.existsSync(path.join(repo, f))) continue;
    const svg = fs.readFileSync(path.join(repo, f), 'utf8').replace(/<\?xml[^>]*>|<!DOCTYPE[^>]*>/gs, '');
    await p.setContent(`<html><body style="margin:0;background:#fff">${svg}</body></html>`);
    const o = path.join(out, f.replace(/\.svg$/, '.png'));
    fs.mkdirSync(path.dirname(o), { recursive: true });
    await (await p.$('svg')).screenshot({ path: o });
    k++;
  }
  await b.close();
  console.log(`rendered ${k} PNGs to ${out}`);
})();
