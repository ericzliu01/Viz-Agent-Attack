"""Summarise llm_taskgen example runs: clean accuracy, attacked accuracy, bait rate
(ASR in the ASB sense: attacked trials answering the bait / attacked trials) and
unscored rate, per model and per attack.

Usage: python -m llm_taskgen.summarize results/llm_examples_sonnet/results.csv [more.csv ...]
"""
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "pages" / "vega-lite"


def metas():
    out = {}
    for p in PAGES.glob("attack_lx_*.meta.json"):
        m = json.loads(p.read_text())
        out[m["attack_id"]] = m
    return out


def pct(a, b):
    return f"{a}/{b} ({100 * a / b:.0f}%)" if b else "0/0"


def main(paths):
    meta = metas()
    rows = [r for p in paths for r in csv.DictReader(open(p, encoding="utf-8")) if "lx_" in r["attack_id"]]
    by_model = defaultdict(list)
    for r in rows:
        by_model[r["model"]].append(r)
    lines = []
    for model, rs in sorted(by_model.items()):
        clean = [r for r in rs if r["attack_id"].endswith("__clean_baseline")]
        att = [r for r in rs if not r["attack_id"].endswith("__clean_baseline")]
        lines.append(f"## {model}\n")
        lines.append(f"- Clean: correct {pct(sum(r['correct'] == 'true' for r in clean), len(clean))}, "
                     f"unscored {pct(sum(r['correct'] == 'needs_review' for r in clean), len(clean))}")
        bait_hits = sum(r["extracted_answer"] == meta[r["attack_id"]]["bait"] for r in att)
        lines.append(f"- Attacked: correct {pct(sum(r['correct'] == 'true' for r in att), len(att))}, "
                     f"bait (ASR) {pct(bait_hits, len(att))}, "
                     f"unscored {pct(sum(r['correct'] == 'needs_review' for r in att), len(att))}\n")
        lines.append("| Attack | Channel | Task | Clean correct | Attacked correct | Bait | Unscored |")
        lines.append("|---|---|---|---|---|---|---|")
        for aid in sorted({r["attack_id"] for r in att}):
            m = meta[aid]
            a = [r for r in att if r["attack_id"] == aid]
            base = [r for r in rs if r["attack_id"] in (f"{aid}__clean_baseline",
                    f"clean_{m['chart_type']}__{m['dataset']}__clean_baseline")]
            lines.append(f"| {m['technique']} | {m['channel']} | {m['task_id']} | "
                         f"{pct(sum(r['correct'] == 'true' for r in base), len(base))} | "
                         f"{pct(sum(r['correct'] == 'true' for r in a), len(a))} | "
                         f"{pct(sum(r['extracted_answer'] == m['bait'] for r in a), len(a))} | "
                         f"{pct(sum(r['correct'] == 'needs_review' for r in a), len(a))} |")
        lines.append("")
    print("\n".join(lines))


if __name__ == "__main__":
    main(sys.argv[1:])
