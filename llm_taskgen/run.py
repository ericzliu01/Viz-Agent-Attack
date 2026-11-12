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
    r.run_trials(trials, args)


if __name__ == "__main__":
    main()
