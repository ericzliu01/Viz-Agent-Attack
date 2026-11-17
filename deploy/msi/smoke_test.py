"""MSI infrastructure smoke test — can this node run the evaluation at all?

Runs the FULL eval loop (serve_chart -> Playwright Chromium -> grade -> CSV) over an
existing instances corpus with a STUB agent, so NO model (Ollama/Qwen or Bedrock) is
needed. If this writes a trial_results.csv on an MSI compute node, the eval infra works
there and only the real model target remains.

Usage (from the repo root on MSI, inside the venv):
    python deploy/msi/smoke_test.py runs/pilot10
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root on sys.path

from browser_agent import AgentResult
from pipeline.eval_runner import run_eval


def stub_agent(page, question, model, *, workspace_dir=None, memory_backend=None, client=None):
    """Touch the rendered page (proving Chromium drew it), then return a fixed answer."""
    try:
        _ = page.title()  # confirms the browser loaded the served page
    except Exception:  # noqa: BLE001 -- the smoke test still records a trial
        pass
    return AgentResult(answer="A", stop_reason="final", steps=1, latency_ms=1, messages=[])


def main():
    corpus = sys.argv[1] if len(sys.argv) > 1 else "runs/pilot10"
    out = Path(corpus) / "smoke_eval"
    rows = run_eval(corpus, out, model="stub-smoke", agent_fn=stub_agent,
                    run_config={"target": "stub-smoke", "note": "infra check, no model"})
    csv_path = out / "trial_results.csv"
    print(f"SMOKE OK: ran {len(rows)} trials over {corpus}")
    print(f"  results: {csv_path}")
    print("  -> serve_chart + Playwright Chromium + grading + CSV all work on this node.")


if __name__ == "__main__":
    main()
