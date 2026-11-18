"""Benchmark items of the Xu & Wall SVG taxonomy repo (lebretou/SVG_taxonomy).

One item = chart type x condition x task x dataset index. The prompt is built
exactly as the repo's llm/gen_prompt.py does: the task description from
llm/prompts.json, a newline, then the raw SVG file.
"""
import csv
import json
import os
import re

CHARTS = {"scatter": "Scatter Plot", "line": "Line Plot", "bar": "Bar Plot"}
CONDITIONS = ["easy_unlabeled", "easy_labeled", "hard_unlabeled", "hard_labeled"]
# task key -> (prompts.json name, results/ folder name, Amar et al. task name)
TASKS = {
    "retrieval": ("Data Extraction", "retrieval", "Retrieve Value"),
    "filter": ("Filtering", "filter", "Filter"),
    "derive": ("Compute Value", "derive", "Compute Derived Value"),
    "extreme": ("Find Extremum", "extreme", "Find Extremum"),
    "sort": ("Sort", "sort", "Sort"),
    "range": ("Determine Range", "range", "Determine Range"),
    "distribution": ("Characterize Distribution", "distribution", "Characterize Distribution"),
    "anomaly": ("Find Anomalies", "anomaly", "Find Anomalies"),
    "cluster": ("Clustering", "cluster", "Cluster"),
    "correlate": ("Correlate", "correlate", "Correlate"),
}
TASK_ORDER = list(TASKS)


def load_prompts(repo):
    with open(os.path.join(repo, "llm", "prompts.json")) as f:
        return json.load(f)


def label_of(cond):
    return "labeled" if cond.endswith("_labeled") else "unlabeled"


def size_of(cond):
    return cond.split("_")[0]


def image_path(repo, chart, cond, task, idx):
    if task == "distribution":
        return os.path.join(repo, "images", chart, cond + "_distribution", f"data_{idx}.svg")
    return os.path.join(repo, "images", chart, cond, f"{chart}_data_{idx}.svg")


def dataset_path(repo, chart, cond, task, idx):
    size = size_of(cond)
    if task == "distribution":
        return os.path.join(repo, "dataset", chart, size + "_distri", f"data_{idx}.csv")
    return os.path.join(repo, "dataset", chart, size, f"{chart}_data_{idx}.csv")


def read_rows(path):
    with open(path) as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["X"] = float(r["X"])
        r["Y"] = float(r["Y"])
    return rows


def distribution_key(repo, chart, cond):
    text = open(os.path.join(repo, "dataset", chart, size_of(cond) + "_distri", "key.txt")).read()
    return {int(i): k for k, i in re.findall(r"(normal|uniform|binomial) distribution: data_(\d+)", text)}


def all_items(repo, prompts=None, indices=range(20)):
    """Every (chart, cond, task, idx) that has a prompt in prompts.json."""
    prompts = prompts or load_prompts(repo)
    out = []
    for chart, pname in CHARTS.items():
        for cond in CONDITIONS:
            for task in TASK_ORDER:
                if TASKS[task][0] not in prompts[pname][label_of(cond)]:
                    continue
                for idx in indices:
                    out.append((chart, cond, task, idx))
    return out


def build_prompt(repo, prompts, chart, cond, task, idx):
    desc = prompts[CHARTS[chart]][label_of(cond)][TASKS[task][0]]
    with open(image_path(repo, chart, cond, task, idx)) as f:
        svg = f.read()
    return f"{desc}\n{svg}"


def item_id(chart, cond, task, idx):
    return f"{chart}/{cond}/{task}/{idx}"


def gpt4_output(repo, chart, cond, task, idx):
    """The repo's saved gpt-4-turbo output for an item, or None.

    Per-item files for SVG/CSV tasks; one line per item in a .txt file for
    derive, range and distribution (the *_o.txt file is the run with answer
    options, which matches prompts.json).
    """
    folder = os.path.join(repo, "results", chart, TASKS[task][1], cond)
    if not os.path.isdir(folder):
        return None
    if task in ("derive", "range", "distribution"):
        name = f"{chart}_{TASKS[task][1]}" + ("_o" if task == "distribution" else "") + ".txt"
        p = os.path.join(folder, name)
        if not os.path.exists(p):
            return None
        lines = [l for l in open(p).read().split("\n")]
        # trailing newline yields an empty last element
        while lines and lines[-1] == "":
            lines.pop()
        return lines[idx] if idx < len(lines) else None
    files = [f for f in os.listdir(folder) if re.search(rf"_{idx}\.(svg|csv)$", f) and not f.startswith("plot_")]
    if not files:
        return None
    return open(os.path.join(folder, files[0])).read()
