"""Run capability questions on clean charts using the shared ReAct browser agent."""
import argparse
import json
import os

from memory import task_memory_fields
from run_attack_suite import (PAGES_DIR, add_agent_arguments, validate_arguments,
                              run_trials, grade, dataset_name)

CHART_TYPES = ["clean_bar", "clean_line", "clean_scatter", "clean_stacked_bar", "clean_revenue"]


def clean_pages(lib_dir):
    """Clean page ids in a library folder, in CHART_TYPES order: each chart
    type's hand-written page, then its generated dataset pages
    (clean_<type>__<dataset>, from build_dataset_pages.py)."""
    names = os.listdir(lib_dir) if os.path.isdir(lib_dir) else []
    out = []
    for chart_type in CHART_TYPES:
        out.append(chart_type)
        out += sorted(n[: -len(".meta.json")] for n in names
                      if n.startswith(chart_type + "__") and n.endswith(".meta.json"))
    return out


def discover_tasks(libraries, datasets=None):
    """Return a list of task dicts: library, attack_id (the clean page, e.g.
    "clean_bar" or "clean_bar__dummy1"), task_id, task_category, tier,
    question, ground_truth, html_path. Folds in each page's own
    <page>.meta.json question as its Retrieve Value / tier-1 task.
    datasets, if given, keeps only those datasets ("original" for the
    hand-written pages)."""
    tasks = []
    for library in libraries:
        lib_dir = os.path.join(PAGES_DIR, library)
        for chart_type in clean_pages(lib_dir):
            dataset = chart_type.split("__")[1] if "__" in chart_type else None
            if datasets is not None and dataset_name(dataset) not in datasets:
                continue
            meta_path = os.path.join(lib_dir, f"{chart_type}.meta.json")
            html_path = os.path.join(lib_dir, f"{chart_type}.html")
            if not os.path.isfile(meta_path):
                print(f"  [note] no {chart_type}.meta.json for {library} -- skipping this chart type")
                continue
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
            # A page meta may name its question's task (build_real_dataset_pages.py
            # does); otherwise it is the page's Retrieve Value question.
            tasks.append({
                "library": library, "attack_id": chart_type,
                "task_id": meta.get("task_id", "retrieve_value"),
                "task_category": meta.get("task_category", "Retrieve Value"), "tier": meta.get("tier", 1),
                "question": meta["question"], "ground_truth": meta["ground_truth"],
                "answer_type": meta.get("answer_type", "free"), "html_path": html_path,
                **task_memory_fields(meta),
            })

            bank_path = os.path.join(lib_dir, f"{chart_type}.capability_tasks.json")
            if not os.path.isfile(bank_path):
                print(f"  [note] no {chart_type}.capability_tasks.json for {library} yet -- only Retrieve Value tested")
                continue
            with open(bank_path, encoding="utf-8") as f:
                bank = json.load(f)
            for entry in bank:
                tasks.append({
                    "library": library, "attack_id": chart_type, "task_id": entry["task_id"],
                    "task_category": entry["task_category"], "tier": entry["tier"],
                    "question": entry["question"], "ground_truth": entry["ground_truth"],
                    "answer_type": entry.get("answer_type", "free"), "html_path": html_path,
                    **task_memory_fields(entry),
                })
    return tasks


def grade_task(task, response):
    return grade(response, task["ground_truth"], task.get("answer_type", "free"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_agent_arguments(parser)
    parser.add_argument("--limit", type=int, help="Maximum capability questions per library")
    parser.add_argument("--task-ids", help="Comma-separated subset of task_id values to run (default: all)")
    args = parser.parse_args()
    validate_arguments(parser, args)
    task_ids = {t.strip() for t in args.task_ids.split(",") if t.strip()} if args.task_ids else None
    try:
        tasks = []
        for library in args.libraries:
            discovered = discover_tasks([library], args.datasets)
            if task_ids is not None:
                discovered = [t for t in discovered if t["task_id"] in task_ids]
            tasks.extend(discovered[:args.limit] if args.limit else discovered)
        run_trials(tasks, args)
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
