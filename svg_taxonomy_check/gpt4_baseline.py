"""Score the repo's saved gpt-4-turbo outputs with score.py (calibration against the paper's Table 1)."""
import json, sys
import items as I, score as S
repo = sys.argv[1]; out = sys.argv[2]
rows = []
for chart, cond, task, idx in I.all_items(repo):
    if chart == "line" and cond == "hard_labeled" and task == "derive":
        reply = None; note = "results file has 43 lines for 20 items; unmappable"
    else:
        reply = I.gpt4_output(repo, chart, cond, task, idx); note = ""
    if reply is None:
        rows.append(dict(item=I.item_id(chart, cond, task, idx), chart=chart, cond=cond, task=task, idx=idx, missing=True, note=note)); continue
    try:
        r = S.score(repo, chart, cond, task, idx, reply)
    except Exception as e:
        r = dict(correct=False, strict=False, parsed=False, detail=f"scorer error {e!r}")
    rows.append(dict(item=I.item_id(chart, cond, task, idx), chart=chart, cond=cond, task=task, idx=idx, missing=False, **r))
json.dump(rows, open(out, "w"), indent=1)
