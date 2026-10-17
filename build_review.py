"""Generate review.html: a browsable list of every implemented task with its
clean baseline and attacked chart side by side (per library).

Usage: python build_review.py   ->  writes tasks/review.html and tasks/tasks.json.
Open review.html in a browser (needs internet: chart pages load libs from CDNs).
"""
import json
from pathlib import Path

ROOT = Path(__file__).parent
PAGES = ROOT / "pages"
OUT = ROOT / "tasks"
LIBS = ["d3", "plotly", "chartjs", "vega-lite"]
CHARTS = ["bar", "line", "scatter", "stacked_bar"]
CATEGORY_ORDER = [
    "Retrieve Value", "Find Anomalies", "Find Extremum", "Filter", "Determine Range",
    "Sort", "Compute Derived Value", "Characterize Distribution", "Correlate",
]
TIER = {"Retrieve Value": 1, "Find Anomalies": 1, "Find Extremum": 2, "Filter": 2,
        "Determine Range": 2, "Sort": 3, "Compute Derived Value": 3,
        "Characterize Distribution": 3, "Correlate": 3}


def load(p):
    return json.loads(p.read_text())


def build():
    tasks = []
    ref = "d3"  # question text/answer are identical across libraries
    for chart in CHARTS:
        clean = f"clean_{chart}"
        bank = load(PAGES / ref / f"{clean}.capability_tasks.json")
        meta = load(PAGES / ref / f"{clean}.meta.json")
        entries = [{"task_id": "retrieve_value", "category": "Retrieve Value", "question": meta["question"],
                    "answer": meta["ground_truth"], "source": f"{clean}.meta.json"}]
        entries += [{"task_id": t["task_id"], "category": t["task_category"], "question": t["question"],
                     "answer": t["ground_truth"], "source": f"{clean}.capability_tasks.json"}
                    for t in bank]
        attacks = {}
        for f in sorted((PAGES / ref).glob(f"attack_{chart}_*.meta.json")):
            m = load(f)
            attacks[m["question"]] = (m["attack_id"], m["description"])
        for e in entries:
            e["chart"] = chart
            e["clean"] = clean
            hit = attacks.get(e["question"])
            e["attack"] = hit[0] if hit else None
            e["attack_desc"] = hit[1] if hit else None
            tasks.append(e)
    tasks.sort(key=lambda t: (CATEGORY_ORDER.index(t["category"]), CHARTS.index(t["chart"])))
    for i, t in enumerate(tasks, 1):
        t["n"] = i
        t["tier"] = TIER[t["category"]]
    return tasks


HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Viz-Agent-Attack Task Review</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#1b1f24;--mut:#5b6672;--line:#dde1e6;--acc:#2457c5;--bad:#b3261e;--badbg:#fdecea;--ok:#1e7b3a;--okbg:#e8f5ec}
@media(prefers-color-scheme:dark){:root{--bg:#14171b;--card:#1c2127;--ink:#e6e9ed;--mut:#9aa5b1;--line:#2d343c;--acc:#7da3f5;--bad:#f2a29c;--badbg:#3a1f1d;--ok:#8fd4a3;--okbg:#17301f}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,system-ui,"Segoe UI",sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--card);border-bottom:1px solid var(--line);padding:12px 20px}
h1{font-size:17px;margin:0 0 8px}
.bar{display:flex;flex-wrap:wrap;gap:8px 18px;align-items:center}
.grp{display:flex;gap:4px;align-items:center}
.grp>span{color:var(--mut);font-size:12px;margin-right:2px}
button.chip{border:1px solid var(--line);background:var(--bg);color:var(--ink);border-radius:999px;padding:3px 11px;cursor:pointer;font:inherit;font-size:13px}
button.chip[aria-pressed=true]{background:var(--acc);border-color:var(--acc);color:#fff}
#count{color:var(--mut);margin-left:auto}
main{max-width:1500px;margin:0 auto;padding:16px 20px 60px}
h2{font-size:14px;text-transform:uppercase;letter-spacing:.05em;color:var(--mut);margin:26px 0 8px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;margin:0 0 10px}
.head{display:flex;gap:12px;align-items:flex-start;padding:12px 14px;cursor:pointer}
.n{color:var(--mut);min-width:26px;font-variant-numeric:tabular-nums}
.q{flex:1}
.q b{font-weight:600}
.meta{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px;font-size:12px}
.tag{border-radius:4px;padding:1px 7px;background:var(--bg);border:1px solid var(--line);color:var(--mut)}
.tag.atk{background:var(--badbg);color:var(--bad);border-color:transparent;font-family:ui-monospace,Menlo,monospace}
.tag.ans{background:var(--okbg);color:var(--ok);border-color:transparent}
.body{display:none;border-top:1px solid var(--line);padding:12px 14px}
.card.open .body{display:block}
.card.open .caret{transform:rotate(90deg)}
.caret{color:var(--mut);transition:transform .1s;margin-top:2px}
.panes{display:grid;gap:12px;grid-template-columns:1fr 1fr}
.panes.one{grid-template-columns:minmax(0,1fr)}
@media(max-width:900px){.panes{grid-template-columns:1fr}}
.pane{min-width:0}
.pane h4{margin:0 0 4px;font-size:12px;display:flex;justify-content:space-between;gap:8px}
.pane h4 a{color:var(--acc);font-weight:400;text-decoration:none}
.pane.atk h4 span{color:var(--bad)}
iframe{width:100%;height:470px;border:1px solid var(--line);border-radius:6px;background:#fff}
.desc{margin:10px 0 0;color:var(--mut);font-size:13px}
.empty{padding:40px;text-align:center;color:var(--mut)}
</style></head><body>
<header>
<h1>Viz-Agent-Attack — implemented tasks <span style="font-weight:400;color:var(--mut)">(baseline vs. attacked)</span></h1>
<div class="bar">
 <div class="grp" id="f-lib"><span>Library</span></div>
 <div class="grp" id="f-chart"><span>Chart</span></div>
 <div class="grp" id="f-tier"><span>Tier</span></div>
 <div class="grp" id="f-atk"><span>Show</span></div>
 <div class="grp"><button class="chip" id="expand">Expand all attacked</button><button class="chip" id="collapse">Collapse all</button></div>
 <div id="count"></div>
</div></header>
<main id="list"></main>
<script>
const TASKS=__DATA__, LIBS=__LIBS__, HTML=__PAGES__;
const st={lib:'d3',chart:'all',tier:'all',atk:'all'};
const opts={lib:LIBS.map(l=>[l,l]),chart:[['all','all'],['bar','bar'],['line','line'],['scatter','scatter'],['stacked_bar','stacked bar']],
 tier:[['all','all'],['1','1 Easy'],['2','2 Medium'],['3','3 Hard']],atk:[['all','all tasks'],['atk','attacked only']]};
function chips(key){const el=document.getElementById('f-'+key);
 opts[key].forEach(([v,label])=>{const b=document.createElement('button');b.className='chip';b.textContent=label;b.dataset.v=v;
  b.onclick=()=>{st[key]=v;sync();render()};el.appendChild(b)})}
function sync(){for(const k in opts)document.querySelectorAll('#f-'+k+' .chip').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.v===st[k])))}
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function pane(kind,label,file){const url='../pages/'+st.lib+'/'+file;
 return `<div class="pane ${kind}"><h4><span>${label}</span><a href="${url}" target="_blank" rel="noopener">${esc(file)} ↗</a></h4><iframe data-src="${url}" title="${esc(label)}"></iframe></div>`}
function fill(card){const t=TASKS[card.dataset.i];
 let h=pane('base','Clean baseline',t.clean+'.html');
 if(t.attack)h+=pane('atk','Attacked · '+t.attack,'attack_'+t.attack.replace(/^/,'')+'.html');
 card.querySelector('.panes').innerHTML=h;card.querySelector('.panes').className='panes'+(t.attack?'':' one');
 card.querySelectorAll('iframe').forEach(f=>{f.srcdoc=HTML[f.dataset.src.slice(9)]});card.dataset.lib=st.lib}
function toggle(card,force){const open=force??!card.classList.contains('open');card.classList.toggle('open',open);
 if(open&&card.dataset.lib!==st.lib)fill(card)}
let lastCat='';
function render(){const root=document.getElementById('list');root.innerHTML='';let shown=0,cat='';
 TASKS.forEach((t,i)=>{
  if(st.chart!=='all'&&t.chart!==st.chart)return; if(st.tier!=='all'&&String(t.tier)!==st.tier)return; if(st.atk==='atk'&&!t.attack)return;
  if(t.category!==cat){cat=t.category;const h=document.createElement('h2');h.textContent=cat+' · tier '+t.tier;root.appendChild(h)}
  const c=document.createElement('div');c.className='card';c.dataset.i=i;
  c.innerHTML=`<div class="head"><span class="caret">▸</span><span class="n">${t.n}</span><div class="q"><b>${esc(t.question)}</b>
   <div class="meta"><span class="tag ans">answer: ${esc(t.answer)}</span><span class="tag">${esc(t.clean)}</span>
   ${t.attack?`<span class="tag atk">ATTACK ${esc(t.attack)}</span>`:'<span class="tag">no attack</span>'}
   <span class="tag">source: ${esc(t.source)}</span></div></div></div>
   <div class="body"><div class="panes"></div>${t.attack_desc?`<p class="desc"><b>Attack:</b> ${esc(t.attack_desc)}</p>`:''}</div>`;
  c.querySelector('.head').onclick=()=>toggle(c);root.appendChild(c);shown++});
 if(!shown)root.innerHTML='<div class="empty">No tasks match these filters.</div>';
 document.getElementById('count').textContent=shown+' of '+TASKS.length+' tasks · '+TASKS.filter(t=>t.attack).length+' attacked';}
['lib','chart','tier','atk'].forEach(chips);sync();render();
document.getElementById('expand').onclick=()=>document.querySelectorAll('.card').forEach(c=>{if(TASKS[c.dataset.i].attack)toggle(c,true)});
document.getElementById('collapse').onclick=()=>document.querySelectorAll('.card.open').forEach(c=>c.classList.remove('open'));
</script></body></html>
"""

if __name__ == "__main__":
    data = build()
    OUT.mkdir(exist_ok=True)
    tasks_json = [{"id": f"{t['chart']}_{t['task_id']}", "viz_type": t["chart"],
                   "question": t["question"], "answer": t["answer"]} for t in data]
    (OUT / "tasks.json").write_text(json.dumps(tasks_json, indent=2, ensure_ascii=False) + "\n")
    pages = {f"{lib}/{t}.html": (PAGES / lib / f"{t}.html").read_text()
             for lib in LIBS for t in {x for d in data for x in (d["clean"], d["attack"]) if x and True}
             for t in [t if t.startswith("clean_") else "attack_" + t]}
    # embed every chart page so review.html works from file:// or any static viewer
    safe = json.dumps(pages).replace("</", "<\\/")
    out = HTML.replace("__DATA__", json.dumps(data)).replace("__LIBS__", json.dumps(LIBS)).replace("__PAGES__", safe)
    (OUT / "review.html").write_text(out)
    print(f"wrote review.html: {len(data)} tasks, {sum(1 for t in data if t['attack'])} attacked")
