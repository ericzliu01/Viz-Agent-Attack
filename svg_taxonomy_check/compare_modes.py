"""Compare SVG-text and image runs of the same items.

  python3 svg_taxonomy_check/compare_modes.py --repo ~/SVG_taxonomy --out out_dir \
      --svg svg_dir/us.anthropic.claude-sonnet-5-5.jsonl svg_dir/us.openai.gpt-6-luna.jsonl \
      --image img_dir/us.anthropic.claude-sonnet-5-5.image.jsonl img_dir/us.openai.gpt-6-luna.image.jsonl

Writes <out>/scored_image.csv and <out>/compare.md: overall, by task x chart,
by condition (label x size), for both modes and both models, plus the strict
rule. "Same-format tasks" are the four whose answer format did not change
(retrieval, derive, range, distribution).
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
import score_image as SI  # noqa: E402

SHORT = {"us.anthropic.claude-sonnet-5-5": "Sonnet 5.5", "us.openai.gpt-6-luna": "GPT-6-luna"}
SAME = ("retrieval", "derive", "range", "distribution")
COND = {"easy_labeled": "small, labeled", "easy_unlabeled": "small, unlabeled",
        "hard_labeled": "medium, labeled", "hard_unlabeled": "medium, unlabeled"}


def load(p):
    last = {}
    for line in open(p):
        r = json.loads(line)
        last[r["item"]] = r
    return last


def frac(c, n):
    return f"{c}/{n} ({100 * c / n:.0f}%)" if n else "-"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--svg", nargs="+", required=True)
    ap.add_argument("--image", nargs="+", required=True)
    a = ap.parse_args()
    rows = []
    for mode, paths, fn in (("svg", a.svg, S.score), ("image", a.image, SI.score)):
        for p in paths:
            run = load(p)
            for iid, r in run.items():
                chart, cond, task, idx = iid.split("/")
                idx = int(idx)
                if r.get("error"):
                    res = dict(correct=False, strict=False, parsed=False, detail="error: " + r["error"][:80])
                else:
                    res = fn(a.repo, chart, cond, task, idx, r.get("reply"))
                extra = {}
                if mode == "svg" and task == "retrieval" and not r.get("error"):
                    alt = S.score(a.repo, chart, cond, task, idx, SI.answer_text(r.get("reply")))
                    extra["svg_retrieval_via_answer_text"] = int(alt["correct"])
                if "loose_10pct" in res:
                    extra["cluster_loose_10pct"] = int(res["loose_10pct"])
                rows.append(dict(mode=mode, model=SHORT.get(r["model"], r["model"]), item=iid, chart=chart,
                                 cond=cond, task=task, idx=idx, correct=int(res["correct"]),
                                 strict=int(res.get("strict", False)), parsed=int(res.get("parsed", True)),
                                 stop=r.get("stop"), detail=res.get("detail", ""),
                                 svg_retrieval_via_answer_text=extra.get("svg_retrieval_via_answer_text", ""),
                                 cluster_loose_10pct=extra.get("cluster_loose_10pct", "")))
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "scored_modes.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    models = sorted({r["model"] for r in rows}, key=lambda m: list(SHORT.values()).index(m) if m in SHORT.values() else 9)
    cols = [(m, mode) for m in models for mode in ("svg", "image")]
    head = "| " + " | ".join(f"{m} {'SVG text' if mode == 'svg' else 'image'}" for m, mode in cols) + " |"

    def agg(filt, key="correct"):
        c, n = defaultdict(int), defaultdict(int)
        for r in rows:
            if filt(r):
                c[(r["model"], r["mode"])] += r[key]
                n[(r["model"], r["mode"])] += 1
        return [frac(c[k], n[k]) for k in cols]

    L = ["# SVG text vs image: Xu & Wall benchmark", ""]
    L += ["## Overall", "", "| Items | " + head[2:], "|---" * (len(cols) + 1) + "|"]
    L.append("| All tasks | " + " | ".join(agg(lambda r: True)) + " |")
    L.append("| Same-format tasks | " + " | ".join(agg(lambda r: r["task"] in SAME)) + " |")
    L.append("| Changed-format tasks | " + " | ".join(agg(lambda r: r["task"] not in SAME)) + " |")
    L.append("| All tasks, strict rule | " + " | ".join(agg(lambda r: True, "strict")) + " |")
    L += ["", "## By task and chart", "", "| Task | Chart | " + head[2:], "|---" * (len(cols) + 2) + "|"]
    for task in I.TASK_ORDER:
        for chart in I.CHARTS:
            if not any(r["task"] == task and r["chart"] == chart for r in rows):
                continue
            mark = "" if task in SAME else " *"
            L.append(f"| {I.TASKS[task][2]}{mark} | {chart} | " +
                     " | ".join(agg(lambda r, t=task, c=chart: r["task"] == t and r["chart"] == c)) + " |")
    L += ["", "\\* answer format changed in image mode (text instead of SVG).", ""]
    L += ["## By condition", "", "| Condition | " + head[2:], "|---" * (len(cols) + 1) + "|"]
    for cond in ("easy_labeled", "easy_unlabeled", "hard_labeled", "hard_unlabeled"):
        L.append(f"| {COND[cond]} | " + " | ".join(agg(lambda r, c=cond: r["cond"] == c)) + " |")
    for lab in ("labeled", "unlabeled"):
        L.append(f"| all {lab} | " + " | ".join(agg(lambda r, l=lab: I.label_of(r["cond"]) == l)) + " |")
    L += ["", "## By chart and size", "", "| Chart | Size | " + head[2:], "|---" * (len(cols) + 2) + "|"]
    for chart in I.CHARTS:
        for size in ("easy", "hard"):
            L.append(f"| {chart} | {'small' if size == 'easy' else 'medium'} | " +
                     " | ".join(agg(lambda r, c=chart, z=size: r["chart"] == c and I.size_of(r["cond"]) == z)) + " |")
    L += ["", "## Scatter tasks by label (image run misses on scatter)", "", "| Task | Labels | " + head[2:], "|---" * (len(cols) + 2) + "|"]
    for task in ("retrieval", "filter", "extreme", "cluster"):
        for lab in ("labeled", "unlabeled"):
            L.append(f"| {I.TASKS[task][2]} | {lab} | " + " | ".join(
                agg(lambda r, t=task, l=lab: r["chart"] == "scatter" and r["task"] == t and I.label_of(r["cond"]) == l)) + " |")
    L += ["", "## Same-format tasks by label", "", "| Task | Labels | " + head[2:], "|---" * (len(cols) + 2) + "|"]
    for task in SAME:
        for lab in ("labeled", "unlabeled"):
            L.append(f"| {I.TASKS[task][2]} | {lab} | " +
                     " | ".join(agg(lambda r, t=task, l=lab: r["task"] == t and I.label_of(r["cond"]) == l)) + " |")
    flips = [r for r in rows if r["svg_retrieval_via_answer_text"] != "" and r["svg_retrieval_via_answer_text"] != r["correct"]]
    L += ["", f"SVG-text Retrieve Value items whose score changes if read through the image parser (answer_text): {len(flips)}"
          + "".join(f"; {r['model']} {r['item']} {r['correct']}->{r['svg_retrieval_via_answer_text']}" for r in flips)]
    for m in models:
        cl = [r for r in rows if r["model"] == m and r["mode"] == "image" and r["task"] == "cluster"]
        if cl:
            L.append(f"Image Cluster, {m}: every-point rule {sum(r['correct'] for r in cl)}/{len(cl)}, "
                     f"10%-unlisted variant {sum(r['cluster_loose_10pct'] or 0 for r in cl)}/{len(cl)}")
    unp = defaultdict(int)
    for r in rows:
        if not r["parsed"]:
            unp[(r["model"], r["mode"])] += 1
    L += ["", "Unparsed replies: " + ", ".join(f"{m} {mode} {unp[(m, mode)]}" for m, mode in cols)]
    open(os.path.join(a.out, "compare.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
