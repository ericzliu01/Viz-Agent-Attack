"""Score run.py output and compare with the repo's saved gpt-4-turbo outputs.

  python3 svg_taxonomy_check/summarize.py --repo ~/SVG_taxonomy --out results_dir \
      results_dir/us.anthropic.claude-sonnet-5-5.jsonl results_dir/us.openai.gpt-6-luna.jsonl

Writes <out>/scored.csv (one row per model x item) and <out>/summary.md
(tables per task x condition x chart, on the same item indices for every model).
"""
import argparse
import csv
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import items as I  # noqa: E402
import score as S  # noqa: E402

GPT4 = "gpt-4-turbo (repo outputs)"
SHORT = {"us.anthropic.claude-sonnet-5-5": "Sonnet 5.5", "us.openai.gpt-6-luna": "GPT-6-luna"}
COND_LABEL = {"easy_labeled": "small, labeled", "easy_unlabeled": "small, unlabeled",
              "hard_labeled": "medium, labeled", "hard_unlabeled": "medium, unlabeled"}
# Unmappable gpt-4 cells: line/hard_labeled/derive has 43 lines for 20 items.
GPT4_SKIP = {("line", "hard_labeled", "derive")}


def load_runs(paths):
    runs = {}
    for p in paths:
        last = {}
        for line in open(p):
            r = json.loads(line)
            last[r["item"]] = r  # later attempts win
        model = next(iter(last.values()))["model"] if last else os.path.basename(p)
        runs[SHORT.get(model, model)] = last
    return runs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("runs", nargs="+")
    a = ap.parse_args()
    runs = load_runs(a.runs)
    ids = sorted(set().union(*[set(r) for r in runs.values()]))
    keys = [tuple(i.split("/")[:3]) + (int(i.split("/")[3]),) for i in ids]

    scored = []
    models = [GPT4] + list(runs)
    for chart, cond, task, idx in keys:
        iid = I.item_id(chart, cond, task, idx)
        for m in models:
            if m == GPT4:
                reply = None if (chart, cond, task) in GPT4_SKIP else I.gpt4_output(a.repo, chart, cond, task, idx)
                if reply is None:
                    continue
                meta = {}
            else:
                rec = runs[m].get(iid)
                if rec is None or rec.get("error"):
                    scored.append(dict(model=m, item=iid, chart=chart, cond=cond, task=task, idx=idx,
                                       correct=False, strict=False, parsed=False, status="error",
                                       detail=(rec or {}).get("error", "missing")))
                    continue
                reply = rec["reply"]
                meta = dict(stop=rec.get("stop"), out_tokens=rec.get("usage", {}).get("outputTokens"))
            try:
                r = S.score(a.repo, chart, cond, task, idx, reply)
            except Exception as e:
                r = dict(correct=False, strict=False, parsed=False, detail=f"scorer error {e!r}")
            status = "truncated" if meta.get("stop") == "max_tokens" else ("ok" if r["parsed"] else "unparsed")
            scored.append(dict(model=m, item=iid, chart=chart, cond=cond, task=task, idx=idx, status=status, **meta, **r))

    os.makedirs(a.out, exist_ok=True)
    cols = ["model", "item", "chart", "cond", "task", "idx", "status", "correct", "strict", "parsed",
            "point_rate", "alt_one_based", "stop", "out_tokens", "detail"]
    with open(os.path.join(a.out, "scored.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(scored)

    # aggregate on items every model has (gpt-4 missing cells are shown as '-')
    agg = defaultdict(lambda: [0, 0, 0, 0])  # correct, strict, parsed, n
    for r in scored:
        for k in [(r["model"], r["task"], r["cond"], r["chart"]), (r["model"], r["task"], "all", r["chart"]),
                  (r["model"], r["task"], "all", "all"), (r["model"], "all", "all", "all")]:
            a_ = agg[k]
            a_[0] += bool(r["correct"])
            a_[1] += bool(r["strict"])
            a_[2] += bool(r["parsed"])
            a_[3] += 1

    def cell(m, t, c, ch, i=0):
        v = agg.get((m, t, c, ch))
        if not v or not v[3]:
            return "-"
        return f"{v[i]}/{v[3]}"

    L = ["# Xu & Wall SVG taxonomy re-run: scores", "",
         f"Items: {len(keys)} (indices {sorted(set(k[3] for k in keys))} of each chart x condition x task cell). "
         "Cells are correct/n under the primary rule; gpt-4-turbo is scored from the repo's saved outputs for the same items.", ""]
    L.append("## Overall")
    L.append("")
    L.append("| Model | Correct | Strict | Parsed |")
    L.append("|---|---|---|---|")
    for m in models:
        L.append(f"| {m} | {cell(m, 'all', 'all', 'all')} | {cell(m, 'all', 'all', 'all', 1)} | {cell(m, 'all', 'all', 'all', 2)} |")
    L.append("")
    L.append("## Per task (all four conditions pooled)")
    L.append("")
    L.append("| Task | Chart | " + " | ".join(models) + " |")
    L.append("|---|---|" + "---|" * len(models))
    for t in I.TASK_ORDER:
        for ch in I.CHARTS:
            if not any(agg.get((m, t, "all", ch)) for m in models):
                continue
            L.append(f"| {I.TASKS[t][2]} | {ch} | " + " | ".join(cell(m, t, "all", ch) for m in models) + " |")
    L.append("")
    L.append("## Per task x condition x chart")
    L.append("")
    L.append("| Task | Condition | Chart | " + " | ".join(models) + " |")
    L.append("|---|---|---|" + "---|" * len(models))
    for t in I.TASK_ORDER:
        for c in I.CONDITIONS:
            for ch in I.CHARTS:
                if not any(agg.get((m, t, c, ch)) for m in models):
                    continue
                L.append(f"| {I.TASKS[t][2]} | {COND_LABEL[c]} | {ch} | " + " | ".join(cell(m, t, c, ch) for m in models) + " |")
    L.append("")
    L.append("## Scoring rules")
    L.append("")
    for t in I.TASK_ORDER:
        L.append(f"- **{I.TASKS[t][2]}**: {S.RULES[t]}.")
    L.append("- Numeric tolerance: primary 2% of the true data range on that axis; strict 0.011 (labels print 2 decimals).")
    L.append("")
    L.append("## Reply status counts")
    L.append("")
    st = defaultdict(lambda: defaultdict(int))
    for r in scored:
        st[r["model"]][r["status"]] += 1
    for m in models:
        L.append(f"- {m}: " + ", ".join(f"{k} {v}" for k, v in sorted(st[m].items())))
    open(os.path.join(a.out, "summary.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L[:12]))


if __name__ == "__main__":
    main()
