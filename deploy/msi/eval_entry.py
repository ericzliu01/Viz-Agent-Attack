#!/usr/bin/env python3
"""Thin MSI entrypoint: evaluate a pre-generated Viz-Agent-Attack corpus against
a LOCAL Ollama Qwen3-VL target.

This only EVALUATES an already-generated instances tree (e.g. ``runs/pilot10``,
produced locally with Bedrock). It does NOT generate, so no AWS/Bedrock key is
needed here -- just a running local Ollama server and working Playwright/Chromium.

Resumability is provided entirely by ``pipeline.eval_runner.run_eval``: each
(instance, repetition) trial is appended+flushed to ``<out_dir>/trial_results.csv``
and a rerun on the same ``out_dir`` skips trials already recorded. A requeued
SLURM job therefore just re-runs this same command and continues.

Configuration comes from CLI flags, each defaulting to an env var (so the SLURM
script can set everything through the environment):

    --corpus      CORPUS_DIR     instances tree to evaluate      (required)
    --out         OUT_DIR        results dir (stable == resume)  (required)
    --model       QWEN_MODEL     Ollama model tag   (default qwen3-vl:8b)
    --ollama-url  OLLAMA_URL     Ollama base URL    (default http://127.0.0.1:11434)
    --seed        SEED           base seed          (default 0)
    --repetitions REPETITIONS    reps per instance  (default 1)
"""
import argparse
import os
import socket
import sys
import time
from pathlib import Path


def _env_default(name, fallback=None):
    value = os.environ.get(name)
    return value if value not in (None, "") else fallback


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--corpus", default=_env_default("CORPUS_DIR"),
                   help="Path to the generated instances tree (env: CORPUS_DIR).")
    p.add_argument("--out", default=_env_default("OUT_DIR"),
                   help="Output dir; reuse the SAME path to resume (env: OUT_DIR).")
    p.add_argument("--model", default=_env_default("QWEN_MODEL", "qwen3-vl:8b"),
                   help="Ollama model tag (env: QWEN_MODEL).")
    p.add_argument("--ollama-url",
                   default=_env_default("OLLAMA_URL", "http://127.0.0.1:11434"),
                   help="Ollama base URL (env: OLLAMA_URL).")
    p.add_argument("--seed", type=int, default=int(_env_default("SEED", "0")),
                   help="Base seed; repetition i uses seed+i (env: SEED).")
    p.add_argument("--repetitions", type=int,
                   default=int(_env_default("REPETITIONS", "1")),
                   help="Repetitions per instance (env: REPETITIONS).")
    p.add_argument("--select", default=_env_default("SELECT_FILE"),
                   help="Optional JSON file with an ordered list of instance_ids to "
                        "evaluate (env: SELECT_FILE). Use the SAME file the Bedrock "
                        "runs used (e.g. <corpus>/eval_selection.json) so Qwen scores "
                        "the identical balanced selection. Omit to run the full corpus.")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if not args.corpus:
        sys.exit("ERROR: no corpus dir (pass --corpus or set CORPUS_DIR).")
    if not args.out:
        sys.exit("ERROR: no output dir (pass --out or set OUT_DIR).")

    corpus = Path(args.corpus).resolve()
    out_dir = Path(args.out).resolve()
    if not corpus.is_dir():
        sys.exit(f"ERROR: corpus dir does not exist: {corpus}")

    # eval_runner imports several repo-root modules (memory, run_attack_suite,
    # browser_agent, browser_environment, pipeline.*). Ensure the repo root --
    # two levels above this file (deploy/msi/) -- is importable regardless of cwd.
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    # Imported here (not at module top) so --help works even before deps/paths
    # are set up, and so import errors surface with full context.
    from pipeline.eval_runner import run_eval, _ollama_agent_fn

    agent_fn = _ollama_agent_fn(args.ollama_url, seed=args.seed)

    select = None
    if args.select:
        import json as _json
        sel_path = Path(args.select).resolve()
        if not sel_path.is_file():
            sys.exit(f"ERROR: --select file does not exist: {sel_path}")
        select = _json.loads(sel_path.read_text())
        print(f"[eval_entry] select      : {sel_path} ({len(select)} instance_ids)")

    run_config = {
        "target": "ollama",
        "ollama_url": args.ollama_url,
        "model": args.model,
        "corpus_dir": str(corpus),
        "select_file": str(Path(args.select).resolve()) if args.select else None,
        "hostname": socket.gethostname(),
        "slurm_job_id": os.environ.get("SLURM_JOB_ID", ""),
        "slurm_node": os.environ.get("SLURMD_NODENAME", ""),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }

    print(f"[eval_entry] corpus      : {corpus}")
    print(f"[eval_entry] out_dir     : {out_dir}")
    print(f"[eval_entry] model       : {args.model}")
    print(f"[eval_entry] ollama_url  : {args.ollama_url}")
    print(f"[eval_entry] seed        : {args.seed}")
    print(f"[eval_entry] repetitions : {args.repetitions}")
    print(f"[eval_entry] host/job    : {run_config['hostname']} / "
          f"{run_config['slurm_job_id'] or '(no SLURM_JOB_ID)'}")
    print("[eval_entry] starting run_eval (resumable; already-recorded trials are skipped)...")
    sys.stdout.flush()

    start = time.monotonic()
    rows = run_eval(
        str(corpus),
        str(out_dir),
        model=args.model,
        agent_fn=agent_fn,
        repetitions=args.repetitions,
        seed=args.seed,
        run_config=run_config,
        select=select,
    )
    elapsed = time.monotonic() - start

    csv_path = out_dir / "trial_results.csv"
    total_rows = 0
    if csv_path.exists():
        with open(csv_path, encoding="utf-8") as fh:
            total_rows = max(0, sum(1 for _ in fh) - 1)  # minus header

    print()
    print("=== EVAL SUMMARY ===")
    print(f"  new trials this run : {len(rows)}")
    print(f"  total trials on disk: {total_rows}  ({csv_path})")
    print(f"  elapsed             : {elapsed:.1f}s")
    print(f"  run_config.json     : {out_dir / 'run_config.json'}")
    print(f"  traces              : {out_dir / 'traces'}")
    if not rows:
        print("  (no new trials -- corpus already fully evaluated, or corpus has no instances)")


if __name__ == "__main__":
    main()
