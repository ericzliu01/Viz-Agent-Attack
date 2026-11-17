"""One-QA end-to-end evaluation runner over generated pipeline instances.

An instances tree holds, per base question (``<instances_root>/<base>/<cell>/``), a
clean ``TT`` baseline plus one directory per attack variant. Each variant directory
has ``chart.html`` (served), ``spec.json`` (question/options) and ``grader.json``
(correct option, trap target); it may also have a ``workspace/`` (sandboxed file
trap) and a ``memory.json`` (latent-memory corpus).

:func:`run_eval` serves each chart, runs the Bedrock ReAct proxy agent
(``pipeline.bedrock_agent.run_bedrock_agent`` -- a LOCAL PROXY for the real
qwen3-vl target), grades the answer as an A--D multiple choice via
``run_attack_suite.grade``, and writes one ``trial_results.csv`` row per trial plus
a saved trace. Each attack variant is paired with a fresh run of its TT baseline.

Tests inject ``agent_fn`` and ``page_provider`` so no real Bedrock call or browser
launch happens; the defaults wire up the real adapter, ``serve_chart`` and a
Playwright page.
"""
import contextlib
import csv
import json
import tempfile
from pathlib import Path
from uuid import uuid4

from browser_agent import save_trace
from browser_environment import serve_chart
from memory import memory_from_config
from pipeline.bedrock_agent import AGENT_MODEL, run_bedrock_agent
from pipeline.file_tools import copy_workspace
from run_attack_suite import grade

CSV_COLUMNS = ["instance_id", "base_id", "question_id", "cell", "direction",
               "misleader_id", "subtype", "channel", "model", "repetition", "seed",
               "correct_option", "target_option", "predicted_option", "status",
               "latency_ms", "trace_path"]


def _letter(index):
    """0-based option index -> choice letter (0 -> 'A')."""
    return chr(ord("A") + index)


def _mcq_question(question, options):
    """Render *question* with lettered options and a letter-only answer instruction."""
    options = list(options)
    lines = [f"{_letter(i)}) {opt}" for i, opt in enumerate(options)]
    letters = [_letter(i) for i in range(len(options))]
    if len(letters) > 1:
        choices = ", ".join(letters[:-1]) + ", or " + letters[-1]
    else:
        choices = "".join(letters)
    return (f"{question}\n\n" + "\n".join(lines) +
            f"\n\nAnswer with the letter of the correct option only ({choices}).")


def _option_letter(options, value):
    """Letter for an option *value* (e.g. '240' -> 'B'), or '' if not an option."""
    if value is None:
        return ""
    try:
        return _letter(list(options).index(value))
    except ValueError:
        return ""


def _load_instance(instance_dir):
    """Build the instance descriptor from one ``<...>/<cell>/`` directory, or None.

    A directory qualifies only when it has both ``chart.html`` and ``grader.json``.
    """
    instance_dir = Path(instance_dir)
    html_path = instance_dir / "chart.html"
    grader_path = instance_dir / "grader.json"
    spec_path = instance_dir / "spec.json"
    if not (html_path.is_file() and grader_path.is_file()):
        return None
    grader = json.loads(grader_path.read_text())
    spec = json.loads(spec_path.read_text()) if spec_path.is_file() else {}
    options = grader.get("options", spec.get("options", []))
    workspace = instance_dir / "workspace"
    memory_path = instance_dir / "memory.json"
    return {
        "instance_id": grader.get("instance_id", spec.get("instance_id", instance_dir.name)),
        "base_id": grader.get("base_id", spec.get("base_id", "")),
        "question_id": spec.get("question_id", ""),
        "cell": grader.get("cell", spec.get("cell", "")),
        "direction": grader.get("direction", spec.get("direction", "")),
        "misleader_id": grader.get("misleader_id", ""),
        "subtype": grader.get("subtype", ""),
        "channel": grader.get("channel", ""),
        "question": spec.get("question", ""),
        "options": options,
        "correct_option": _letter(grader["correct_index"]) if "correct_index" in grader else "",
        "target_option": _option_letter(options, grader.get("target_option")),
        "html_path": str(html_path),
        "workspace_dir": str(workspace) if workspace.is_dir() else None,
        "memory_path": str(memory_path) if memory_path.is_file() else None,
    }


def discover_pipeline_instances(instances_root):
    """Return ``(clean_by_base, attack_variants)``.

    ``clean_by_base`` maps each ``base_id`` to its ``TT`` clean baseline descriptor;
    ``attack_variants`` is the list of all non-``TT`` descriptors. Directories are
    walked recursively, so any depth of base/variant nesting is supported.
    """
    root = Path(instances_root)
    clean_by_base, attacks = {}, []
    for grader_path in sorted(root.rglob("grader.json")):
        instance = _load_instance(grader_path.parent)
        if instance is None:
            continue
        if instance["cell"] == "TT":
            clean_by_base[instance["base_id"]] = instance
        else:
            attacks.append(instance)
    return clean_by_base, attacks


@contextlib.contextmanager
def _default_page_provider(html_path):
    """Serve ``chart.html`` and yield a Playwright page navigated to it."""
    from playwright.sync_api import sync_playwright
    from browser_agent import VIEWPORT

    with serve_chart(html_path) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport=VIEWPORT)
            page.goto(url, wait_until="networkidle")
            yield page
        finally:
            browser.close()


def _memory_backend(instance):
    if not instance["memory_path"]:
        return None
    config = json.loads(Path(instance["memory_path"]).read_text())
    return memory_from_config(config)


def _run_one(instance, *, model, client, agent_fn, page_provider, out_dir,
             repetition=0, seed=0):
    """Run the agent on one instance, grade it, and return a CSV row dict."""
    backend = _memory_backend(instance)
    with tempfile.TemporaryDirectory() as tmp:
        workspace_dir = None
        if instance["workspace_dir"]:
            workspace_dir = str(copy_workspace(instance["workspace_dir"], Path(tmp) / "workspace"))
        with page_provider(instance["html_path"]) as page:
            result = agent_fn(page, _mcq_question(instance["question"], instance["options"]), model,
                              workspace_dir=workspace_dir, memory_backend=backend,
                              client=client)

    status, predicted = grade(result.answer, instance["correct_option"], answer_type="choice")
    trace_dir = Path(out_dir) / "traces" / uuid4().hex
    trace_path = save_trace(result, trace_dir, {
        "instance_id": instance["instance_id"], "cell": instance["cell"],
        "model": model, "correct_option": instance["correct_option"]})
    return {
        "instance_id": instance["instance_id"],
        "base_id": instance["base_id"],
        "question_id": instance["question_id"],
        "cell": instance["cell"],
        "direction": instance["direction"],
        "misleader_id": instance["misleader_id"],
        "subtype": instance["subtype"],
        "channel": instance["channel"],
        "model": model,
        "repetition": repetition,
        "seed": seed,
        "correct_option": instance["correct_option"],
        "target_option": instance["target_option"],
        "predicted_option": predicted,
        "status": status,
        "latency_ms": result.latency_ms,
        "trace_path": str(trace_path),
    }


def _ollama_agent_fn(base_url="http://localhost:11434", *, seed=0, temperature=0.0,
                     timeout=180):
    """Adapt the real Qwen/Ollama target (``browser_agent.run_agent``) to the eval
    ``agent_fn`` contract. ``run_agent`` takes no ``client``; it is accepted and
    ignored so the same runner drives either the Bedrock proxy or the Ollama target.
    """
    from browser_agent import run_agent

    def agent_fn(page, question, model, *, workspace_dir=None, memory_backend=None,
                 client=None):
        return run_agent(page, question, model, base_url=base_url, timeout=timeout,
                         temperature=temperature, seed=seed,
                         memory_backend=memory_backend, workspace_dir=workspace_dir)

    return agent_fn


def _completed_trials(csv_path):
    """``{(instance_id, repetition)}`` already recorded, for restart/dedup."""
    done = set()
    if not Path(csv_path).exists():
        return done
    with open(csv_path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                done.add((row["instance_id"], int(row.get("repetition", 0) or 0)))
            except (KeyError, ValueError):
                continue
    return done


def run_eval(instances_root, out_dir, *, model=None, client=None, agent_fn=None,
             page_provider=None, repetitions=1, seed=0, run_config=None, select=None):
    """Evaluate every unique instance (attacks + one TT baseline per base) and write
    ``trial_results.csv``.

    Resumable: each (instance, repetition) trial is appended and flushed as it
    completes, and a rerun with the same ``out_dir`` skips trials already recorded, so
    an interrupted MSI run resumes without re-evaluating. Each attack pairs with its
    base's single TT run via ``base_id`` at report time (the baseline is evaluated once
    per base, not once per attack). Returns the rows written *this call* (new trials
    only). ``agent_fn``/``page_provider`` default to the Bedrock proxy and a Playwright
    page; pass :func:`_ollama_agent_fn` as ``agent_fn`` to drive the real Qwen target.
    """
    model = model or AGENT_MODEL
    agent_fn = agent_fn or run_bedrock_agent
    page_provider = page_provider or _default_page_provider
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "trial_results.csv"

    clean_by_base, attacks = discover_pipeline_instances(instances_root)
    if select is not None:
        # Restrict to a chosen set of attack/MT instance_ids (e.g. a stratified sample).
        # An ORDERED list is honored as the run order, so a round-robin-across-strata
        # selection runs balanced -- any prefix (an interrupted run / interim read) is
        # representative, not skewed to whichever stratum happened to come first. The
        # SAME selection evaluates identically across models.
        if isinstance(select, (list, tuple)):
            order = {iid: i for i, iid in enumerate(select)}
            attacks = sorted((a for a in attacks if a["instance_id"] in order),
                             key=lambda a: order[a["instance_id"]])
        else:
            sel = set(select)
            attacks = [a for a in attacks if a["instance_id"] in sel]

    # Interleave each base's single TT baseline right before that base's first attack,
    # so baselines land early (ASR eligibility is available even for a partial run)
    # while the attack order stays balanced.
    planned = []
    seen_bases = set()
    for attack in attacks:
        base_id = attack["base_id"]
        if base_id not in seen_bases:
            baseline = clean_by_base.get(base_id)
            if baseline is not None:
                planned.append(baseline)
            seen_bases.add(base_id)
        planned.append(attack)

    done = _completed_trials(csv_path)
    _write_run_config(out_dir, model=model, seed=seed, repetitions=repetitions,
                      planned=len(planned), run_config=run_config)

    needs_header = (not csv_path.exists()) or csv_path.stat().st_size == 0
    rows = []
    with open(csv_path, "a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        if needs_header:
            writer.writeheader()
            handle.flush()
        for repetition in range(repetitions):
            for instance in planned:
                if (instance["instance_id"], repetition) in done:
                    continue
                row = _run_one(instance, model=model, client=client, agent_fn=agent_fn,
                               page_provider=page_provider, out_dir=out_dir,
                               repetition=repetition, seed=seed + repetition)
                writer.writerow(row)
                handle.flush()
                rows.append(row)
    return rows


def _write_run_config(out_dir, *, model, seed, repetitions, planned, run_config):
    """Record the frozen run configuration beside the results (reproducibility)."""
    import time

    config = {
        "model": model,
        "seed": seed,
        "repetitions": repetitions,
        "planned_instances": planned,
        "written_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    if run_config:
        config.update(run_config)
    (Path(out_dir) / "run_config.json").write_text(json.dumps(config, indent=2))
