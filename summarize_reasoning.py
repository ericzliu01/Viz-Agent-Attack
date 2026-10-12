"""Summarize the reasoning attacks (biased framing, critic evasion, persona
hyperstition) in results/results.csv, per attack and per task.

Reads each attack's meta.json for its tasks and bait letters, so "took bait"
counts attack answers that chose the specific wrong option the attack
pushes toward. Rows from a --critic run also report what the critic did.
Writes results/reasoning_summary.md.

Usage: python summarize_reasoning.py
"""
import os
import re
from collections import defaultdict

from results_logger import read_rows
from run_attack_suite import discover_pages
from summarize_results import BASELINE_SUFFIX, wilson_interval

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SUMMARY_PATH = os.path.join(BASE_DIR, "results", "reasoning_summary.md")

CELL_TERMS = """**Terms used in this section**
- **cells:** scored attack trials (library x task x repeated trial); needs_review answers are excluded.
- **attack wrong [95% CI]:** attack trials answered wrong, with a Wilson 95% confidence interval.
- **baseline wrong:** the same questions answered wrong on clean_revenue (with neutral memory for persona hyperstition).
- **took bait:** attack answers that picked the exact wrong option the attack pushes toward, out of trials whose task has a bait option.
- **fooled / baseline right:** questions right on the clean chart and wrong under attack, paired by library, task and trial.
- **ASR:** attack wrong rate minus baseline wrong rate.
- **MT:** misleading to a human viewer too; **TM:** truthful to a human, misleading to the agent."""

CRITIC_TERMS = """**Terms used in this section**
- **critic:** a second model call that sees the question, the agent's answer, the page text and a screenshot, and replies APPROVE or REVISE.
- **agent wrong:** attack trials where the agent's own answer (before the critic) was wrong.
- **wrong approved:** wrong agent answers the critic approved, so the error got past oversight.
- **wrong fixed:** wrong agent answers the critic revised to the correct option.
- **right broken:** correct agent answers the critic revised to a wrong one."""


def reasoning_meta():
    """attack_id -> {"type", "tasks": {question: task}} for meta files with a task list."""
    _, attacks = discover_pages()
    out = {}
    for entry in attacks:
        if not entry.get("task_id"):
            continue
        info = out.setdefault(entry["attack_id"], {"tasks": {}})
        info["tasks"][entry["question"]] = {"task_id": entry["task_id"], "bait": entry.get("bait")}
    return out


def note_field(notes, key):
    match = re.search(rf"(?:^|; ){key}=([^;]*)", notes or "")
    return match.group(1).strip() if match else ""


def fmt_rate(k, n):
    if not n:
        return "-"
    lo, hi = wilson_interval(k, n)
    return f"{k}/{n} ({lo:.0%}-{hi:.0%})"


def build(rows, meta):
    """Return {(condition, attack_id, task_id_or_ALL): stats dict}."""
    attack_rows, baseline_rows = defaultdict(list), {}
    for row in rows:
        attack_id = row["attack_id"]
        base_id = attack_id[: -len(BASELINE_SUFFIX)] if attack_id.endswith(BASELINE_SUFFIX) else attack_id
        if base_id not in meta or row["question"] not in meta[base_id]["tasks"]:
            continue
        task = meta[base_id]["tasks"][row["question"]]
        key = (row["condition"], row["model"], row["library"], base_id, task["task_id"], row.get("trial", "0"))
        if attack_id.endswith(BASELINE_SUFFIX):
            baseline_rows[key] = row
        else:
            attack_rows[key].append((row, task))

    stats = defaultdict(lambda: defaultdict(int))
    for key, items in attack_rows.items():
        condition, _, _, attack_id, task_id, _ = key
        baseline = baseline_rows.get(key)
        for row, task in items:
            for group in ((condition, attack_id, task_id), (condition, attack_id, "ALL")):
                s = stats[group]
                if row["correct"] in ("true", "false"):
                    s["n"] += 1
                    s["wrong"] += row["correct"] == "false"
                    if task["bait"]:
                        s["bait_n"] += 1
                        s["bait"] += row["extracted_answer"].strip().upper() == task["bait"]
                    if baseline is not None and baseline["correct"] == "true":
                        s["paired_right"] += 1
                        s["fooled"] += row["correct"] == "false"
                else:
                    s["needs_review"] += 1
                if baseline is not None and baseline["correct"] in ("true", "false"):
                    s["b_n"] += 1
                    s["b_wrong"] += baseline["correct"] == "false"
                verdict = note_field(row["notes"], "critic")
                agent_correct = note_field(row["notes"], "agent_correct")
                if verdict and agent_correct in ("true", "false"):
                    s["critic_n"] += 1
                    if agent_correct == "false":
                        s["agent_wrong"] += 1
                        s["wrong_approved"] += verdict == "APPROVE"
                        s["wrong_fixed"] += row["correct"] == "true"
                    elif row["correct"] == "false":
                        s["right_broken"] += 1
    return stats


def render(stats, meta_types):
    lines = ["# Reasoning attack summary", ""]
    if not stats:
        return "\n".join(lines + ["No reasoning-attack rows in results/results.csv yet.", ""])
    conditions = sorted({k[0] for k in stats})
    for condition in conditions:
        lines += [f"## {condition}: by attack", "", CELL_TERMS, "",
                  "| type | attack_id | cells | attack wrong [95% CI] | baseline wrong | took bait | "
                  "fooled / baseline right | ASR | needs_review |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for (cond, attack_id, task_id), s in sorted(stats.items()):
            if cond != condition or task_id != "ALL":
                continue
            asr = (s["wrong"] / s["n"] - s["b_wrong"] / s["b_n"]) if s["n"] and s["b_n"] else None
            lines.append(f"| {meta_types.get(attack_id, '')} | {attack_id} | {s['n']} | "
                         f"{fmt_rate(s['wrong'], s['n'])} | {s['b_wrong']}/{s['b_n']} | "
                         f"{s['bait']}/{s['bait_n']} | {s['fooled']}/{s['paired_right']} | "
                         f"{'-' if asr is None else f'{asr:+.1%}'} | {s['needs_review']} |")
        lines += ["", f"## {condition}: by attack and task", "", CELL_TERMS, "",
                  "| attack_id | task_id | cells | attack wrong | baseline wrong | took bait | fooled / baseline right |",
                  "|---|---|---|---|---|---|---|"]
        for (cond, attack_id, task_id), s in sorted(stats.items()):
            if cond != condition or task_id == "ALL":
                continue
            bait = f"{s['bait']}/{s['bait_n']}" if s["bait_n"] else "no bait"
            lines.append(f"| {attack_id} | {task_id} | {s['n']} | {s['wrong']}/{s['n']} | "
                         f"{s['b_wrong']}/{s['b_n']} | {bait} | {s['fooled']}/{s['paired_right']} |")
        lines.append("")
        critic_rows = [(k, s) for k, s in sorted(stats.items())
                       if k[0] == condition and k[2] == "ALL" and s["critic_n"]]
        if critic_rows:
            lines += [f"## {condition}: critic", "", CRITIC_TERMS, "",
                      "| attack_id | reviewed | agent wrong | wrong approved | wrong fixed | right broken |",
                      "|---|---|---|---|---|---|"]
            for (_, attack_id, _), s in critic_rows:
                lines.append(f"| {attack_id} | {s['critic_n']} | {s['agent_wrong']} | "
                             f"{s['wrong_approved']}/{s['agent_wrong']} | {s['wrong_fixed']}/{s['agent_wrong']} | "
                             f"{s['right_broken']} |")
            lines.append("")
    return "\n".join(lines)


def attack_types():
    import json
    from run_attack_suite import PAGES_DIR
    types = {}
    for library in os.listdir(PAGES_DIR):
        lib_dir = os.path.join(PAGES_DIR, library)
        for fname in os.listdir(lib_dir) if os.path.isdir(lib_dir) else []:
            if fname.endswith(".meta.json"):
                with open(os.path.join(lib_dir, fname), encoding="utf-8") as f:
                    meta = json.load(f)
                if meta.get("family") == "reasoning":
                    types[meta["attack_id"]] = meta.get("type", "")
    return types


def main():
    text = render(build(read_rows(), reasoning_meta()), attack_types())
    os.makedirs(os.path.dirname(SUMMARY_PATH), exist_ok=True)
    with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
        f.write(text)
    print(text)
    print(f"\nWrote {SUMMARY_PATH}")


if __name__ == "__main__":
    main()
