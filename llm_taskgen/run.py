"""Run the llm_taskgen example pages (datasets lx_*) with run_attack_suite's agent.

- The system prompt's answer line is replaced by the fixed A-D answer schema
  (final line 'ANSWER: <letter>'), since these tasks are graded with answer_type "mcq".
- Page-only attacks share one clean baseline per task (attack_id
  clean_<chart>__lx_<task>__clean_baseline); memory attacks keep their own
  baseline, which carries the control memory.

Usage (Bedrock credentials loaded in the shell):
  python -m llm_taskgen.pages
  VIS_RESULTS_DIR=results/llm_examples_sonnet python -m llm_taskgen.run \\
      --models us.anthropic.claude-sonnet-5-5 --backend bedrock --libraries vega-lite,plotly,chartjs,d3 --trials 3
"""
import argparse
import json
from pathlib import Path

import browser_agent
import run_attack_suite as r
from llm_taskgen.answer import TEXT_INSTRUCTION

OLD_ANSWER_LINE = ("When finished, respond with only the final\n"
                   "answer (a short value, name, or choice letter). Do not include an explanation.")


def patch_system_prompt():
    if OLD_ANSWER_LINE not in browser_agent.SYSTEM_PROMPT:
        raise SystemExit("browser_agent.SYSTEM_PROMPT changed; update llm_taskgen/run.py")
    browser_agent.SYSTEM_PROMPT = browser_agent.SYSTEM_PROMPT.replace(
        OLD_ANSWER_LINE, "When finished, give your\nanswer. " + TEXT_INSTRUCTION)


def select_trials(libraries, techniques=None):
    trials, seen = [], set()
    for t in r.attack_trials(libraries):
        ds = t.get("dataset") or ""
        if not ds.startswith("lx_"):
            continue
        technique = t["attack_id"].split("__")[0][len("lx_"):]
        if techniques is not None and technique not in techniques:
            continue
        if t["attack_id"].endswith("__clean_baseline") and t.get("memory") is None:
            if (t["library"], ds) in seen:
                continue
            seen.add((t["library"], ds))
            t = {**t, "attack_id": f"clean_{t['chart_type']}__{ds}__clean_baseline"}
        trials.append(t)
    return trials


def write_trial_metadata(trials, results_dir):
    """Save the answer, bait and technique of every trial next to results.csv, so
    summaries score against what was run, not against pages rebuilt later."""
    path = Path(results_dir) / "trial_metadata.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    old = json.loads(path.read_text()) if path.exists() else {}
    for t in trials:
        technique = t["attack_id"].split("__")[0][len("lx_"):] if t["attack_id"].startswith("lx_") else None
        old[f"{t['library']}|{t['attack_id']}"] = {
            "library": t["library"], "attack_id": t["attack_id"], "task_id": (t.get("dataset") or "")[len("lx_"):],
            "chart_type": t.get("chart_type"), "dataset": t.get("dataset"),
            "ground_truth": t.get("ground_truth"),
            "bait": None if t["attack_id"].startswith("clean_") else t.get("bait"), "technique": technique,
            "memory_control": t["attack_id"].endswith("__clean_baseline")
            and t.get("memory") is not None}
    path.write_text(json.dumps(old, indent=1, sort_keys=True))
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    r.add_agent_arguments(parser)
    parser.add_argument("--techniques", help="Comma-separated technique ids (default: all)")
    parser.add_argument("--limit", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    r.validate_arguments(parser, args)
    techniques = {x.strip() for x in args.techniques.split(",")} if args.techniques else None
    patch_system_prompt()
    trials = select_trials(args.libraries, techniques)
    print(f"{len(trials)} trials per model and trial index", flush=True)
    write_trial_metadata(trials, r.RESULTS_DIR)
    r.run_trials(trials, args)


if __name__ == "__main__":
    main()
