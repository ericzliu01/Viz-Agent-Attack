"""Summarize results/results.csv into a capability-by-task-tier table --
the Amar, Eagan & Stasko (2005) task-accuracy analog of Xu & Wall (2024),
computed across vis-attack's own charts, models, and conditions
(react_browser and historical single-turn conditions).

Unlike summarize_results.py (which computes ASR = wrong_rate(attack) -
wrong_rate(clean baseline)), this script only looks at rows whose
attack_id is one of the 4 standardized clean chart types (CHART_TYPES) and
reports raw accuracy, since there is no attack variant here -- it answers
"how good is this model/condition at this *kind* of task on an honest
chart", not "how much did an attack degrade it".

Task/tier metadata isn't stored in results.csv -- it's looked up by
question text from pages/<library>/<chart_type>.capability_tasks.json (+
each chart type's own <chart_type>.meta.json Retrieve Value question) at
report time, so run_capability_suite.py never had to touch the results.csv
schema.

Usage: python summarize_capability.py
"""
import json
import os
from collections import defaultdict

from results_logger import read_rows
from run_attack_suite import PAGES_DIR
from run_capability_suite import CHART_TYPES
from summarize_results import fmt_table, md_table

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SUMMARY_PATH = os.path.join(BASE_DIR, "results", "capability_summary.md")

TIER_LABELS = {1: "1 - Easy", 2: "2 - Medium", 3: "3 - Hard"}


def build_task_lookup():
    """question text -> (library, task_category, tier). Folds in each chart
    type's own <chart_type>.meta.json Retrieve Value question plus any
    <chart_type>.capability_tasks.json bank present."""
    lookup = {}
    for library in sorted(os.listdir(PAGES_DIR)):
        lib_dir = os.path.join(PAGES_DIR, library)
        if not os.path.isdir(lib_dir):
            continue
        for chart_type in CHART_TYPES:
            meta_path = os.path.join(lib_dir, f"{chart_type}.meta.json")
            if os.path.isfile(meta_path):
                with open(meta_path, encoding="utf-8") as f:
                    meta = json.load(f)
                lookup[meta["question"]] = (library, "Retrieve Value", 1)

            bank_path = os.path.join(lib_dir, f"{chart_type}.capability_tasks.json")
            if os.path.isfile(bank_path):
                with open(bank_path, encoding="utf-8") as f:
                    bank = json.load(f)
                for entry in bank:
                    lookup[entry["question"]] = (library, entry["task_category"], entry["tier"])
    return lookup


def accuracy(rows):
    scored = [r for r in rows if r["correct"] in ("true", "false")]
    needs_review = sum(1 for r in rows if r["correct"] == "needs_review")
    if not scored:
        return None, 0, needs_review
    correct = sum(1 for r in scored if r["correct"] == "true")
    return correct / len(scored), len(scored), needs_review


def main():
    rows = read_rows()
    lookup = build_task_lookup()
    if not lookup:
        print("No capability_tasks.json files found yet -- nothing to summarize.")
        return

    capability_rows = []
    for row in rows:
        if row["attack_id"] not in CHART_TYPES:
            continue
        task = lookup.get(row["question"])
        if task is None:
            continue
        library, task_category, tier = task
        capability_rows.append({**row, "task_category": task_category, "tier": tier})

    if not capability_rows:
        print("No results.csv rows match a known capability question yet -- run run_capability_suite.py first.")
        return

    by_task = defaultdict(list)
    by_tier = defaultdict(list)
    for r in capability_rows:
        # attack_id doubles as the chart type (clean_bar/clean_line/clean_scatter/
        # clean_stacked_bar) here -- keep it in the key so e.g. Find Extremum on
        # a bar chart isn't blended with Find Extremum on a scatter plot.
        by_task[(r["condition"], r["model"], r["library"], r["attack_id"], r["task_category"], r["tier"])].append(r)
        by_tier[(r["condition"], r["model"], r["tier"])].append(r)

    task_entries = []
    for key, group in by_task.items():
        condition, model, library, chart_type, task_category, tier = key
        acc, n, nr = accuracy(group)
        if acc is None:
            continue
        task_entries.append((condition, model, library, chart_type, task_category, tier, acc, n, nr))
    task_entries.sort(key=lambda e: (e[0], e[1], e[5], -e[6]))

    tier_entries = []
    for key, group in by_tier.items():
        condition, model, tier = key
        acc, n, nr = accuracy(group)
        if acc is None:
            continue
        tier_entries.append((condition, model, tier, acc, n, nr))
    tier_entries.sort(key=lambda e: (e[0], e[1], e[2]))

    sections = []

    headers1 = ["condition", "model", "library", "chart_type", "task", "tier", "accuracy", "n", "needs_review"]
    rows1 = [(c, m, lib, ct, tc, TIER_LABELS[t], f"{acc:.1%}", n, nr) for c, m, lib, ct, tc, t, acc, n, nr in task_entries]
    print("\n== Accuracy by task ==")
    print(fmt_table(headers1, rows1))
    sections.append("## Accuracy by task\n\n" + md_table(headers1, rows1))

    headers2 = ["condition", "model", "tier", "mean accuracy", "n", "needs_review"]
    rows2 = [(c, m, TIER_LABELS[t], f"{acc:.1%}", n, nr) for c, m, t, acc, n, nr in tier_entries]
    print("\n== Mean accuracy by tier ==")
    print(fmt_table(headers2, rows2))
    sections.append("## Mean accuracy by tier\n\n" + md_table(headers2, rows2))

    os.makedirs(os.path.dirname(SUMMARY_PATH), exist_ok=True)
    with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
        f.write("# vis-attack capability baseline (Amar et al. task taxonomy)\n\n")
        f.write("\n\n".join(sections))
        f.write("\n")
    print(f"\nWrote {SUMMARY_PATH}")


if __name__ == "__main__":
    main()
