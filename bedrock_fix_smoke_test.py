#!/usr/bin/env python3
"""Local Bedrock smoke test for the three 2026-11-18 ASR-audit fixes on
``fix/chartspread-asr-bugs``: the answer-position shuffle, the console-listener
timing fix, and the screenshot-delivery fix for Converse models (Luna/Qwen).

Makes REAL Bedrock calls (costs money and needs network access to
bedrock-runtime) -- this is a manual, opt-in smoke test, not a pytest and not
part of the automated suite. It evaluates a handful of trials, not the full
corpus, and writes no results.csv; it just prints PASS/FAIL per check.

Needs:
  - AWS_BEARER_TOKEN_BEDROCK (and optionally AWS_REGION, default us-west-2) in
    the environment -- see AWS-API/aws-api-test.env.example.
  - playwright installed with Chromium (`pip install playwright &&
    playwright install chromium`) for the console/screenshot checks.
  - duckdb installed for the shuffle check (`pip install duckdb`).

Usage:
    python bedrock_fix_smoke_test.py                       # all checks, both models
    python bedrock_fix_smoke_test.py --model haiku          # Haiku only (known-good control)
    python bedrock_fix_smoke_test.py --model luna           # Luna only (the one that was broken)
    python bedrock_fix_smoke_test.py --skip shuffle         # skip the generation-side check
    python bedrock_fix_smoke_test.py --check console        # just the console check
"""
import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MODEL_IDS = {
    "haiku": os.getenv("SMOKE_HAIKU_MODEL", "us.anthropic.claude-haiku-5-5"),
    "luna": os.getenv("SMOKE_LUNA_MODEL", "us.openai.gpt-5.6-luna"),
}

CONSOLE_MARKER = "VIZTRAP-CONSOLE-SMOKE-9f3c2a"
CONSOLE_HTML = f"""<!doctype html><html><head>
<script>console.log("{CONSOLE_MARKER}");</script>
</head><body><p>console fix smoke test page</p></body></html>"""

# A single flat-colored swatch: nothing in the DOM/text states the color, so a
# correct answer can only come from the model actually having seen the image.
SWATCH_COLOR_NAME = "blue"
SCREENSHOT_HTML = """<!doctype html><html><head><style>
body { margin: 0; }
#swatch { width: 400px; height: 300px; background: #1f6fd6; }
</style></head><body><div id="swatch"></div></body></html>"""


def _agent_fn(model_key):
    if model_key == "haiku":
        from pipeline.bedrock_agent import run_bedrock_agent
        return run_bedrock_agent
    if model_key == "luna":
        from pipeline.converse_agent import run_converse_agent
        return run_converse_agent
    raise ValueError(f"Unknown model key: {model_key!r}")


def _run_against_page(model_key, html, question, *, max_steps=6):
    """Serve ``html`` locally, run the real agent loop against a real Bedrock
    model, and return (AgentResult, messages_json) -- the latter for grepping
    ground-truth tool content regardless of the model's paraphrase."""
    from browser_environment import serve_chart
    from browser_agent import capture_console
    from playwright.sync_api import sync_playwright

    agent_fn = _agent_fn(model_key)
    model_id = MODEL_IDS[model_key]

    with tempfile.TemporaryDirectory() as tmp:
        html_path = Path(tmp) / "chart.html"
        html_path.write_text(html)
        with serve_chart(str(html_path)) as url, sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                page = browser.new_page(viewport={"width": 960, "height": 720})
                logs = capture_console(page)
                page.goto(url, wait_until="networkidle")
                result = agent_fn(page, question, model_id, console_logs=logs,
                                  max_steps=max_steps)
            finally:
                browser.close()
    return result, json.dumps(result.messages)


def check_console(model_key):
    """Fix 2: the console tool must actually see a startup console.log, and the
    model (asked to read and quote it) must report the marker text."""
    print(f"\n=== console fix -- {model_key} ({MODEL_IDS[model_key]}) ===")
    question = ("Call the console tool. Then reply with exactly the text of the "
                "one console message you found, and nothing else.")
    result, raw = _run_against_page(model_key, CONSOLE_HTML, question)
    marker_in_tool_traffic = CONSOLE_MARKER in raw
    marker_in_answer = CONSOLE_MARKER in (result.answer or "")
    print(f"  stop_reason={result.stop_reason} tools_used={result.tools_used}")
    print(f"  marker reached the model (tool traffic): {marker_in_tool_traffic}")
    print(f"  marker in the model's final answer      : {marker_in_answer}")
    ok = marker_in_tool_traffic
    if result.stop_reason == "request_error":
        print(f"  error: {result.error}")
    print("  PASS" if ok else "  FAIL -- console marker never reached the model")
    return ok


def _only_screenshot_tool():
    """Restrict the agent to just the screenshot tool for this trial: no
    dom/evaluate (which would let the model read the swatch's hex code straight
    from HTML/CSS source instead of actually looking at the image) and no
    submit_answer (which would let it reply with a multiple-choice letter
    instead of a free-text color word)."""
    from unittest.mock import patch

    def only_screenshot(*, memory_backend=None, workspace_dir=None):
        from pipeline.bedrock_agent import TOOLS, _anthropic_tool
        return [_anthropic_tool(spec) for spec in TOOLS
                if spec["function"]["name"] == "screenshot"]

    return (patch("pipeline.bedrock_agent.anthropic_tools", only_screenshot),
            patch("pipeline.converse_agent.anthropic_tools", only_screenshot))


def check_screenshot(model_key):
    """Fix 1 (Luna/Converse only, but run for both as a control): the model
    must receive and actually describe the swatch color from the image, not
    the DOM/HTML (which never states the color). Tool set is pinned to just
    `screenshot` so there's no DOM-reading or multiple-choice escape hatch."""
    print(f"\n=== screenshot fix -- {model_key} ({MODEL_IDS[model_key]}) ===")
    question = ("Take a screenshot. Then reply with exactly one word: the CSS "
                "color name closest to the color of the rectangle you see.")
    patches = _only_screenshot_tool()
    for p in patches:
        p.start()
    try:
        result, raw = _run_against_page(model_key, SCREENSHOT_HTML, question)
    finally:
        for p in patches:
            p.stop()
    had_tool_error = '"status": "error"' in raw or '"is_error": true' in raw
    # The real delivery check: an image block actually present in the transcript,
    # not just that the screenshot tool ran without raising.
    image_sent = '"image"' in raw
    color_in_answer = SWATCH_COLOR_NAME in (result.answer or "").lower()
    print(f"  stop_reason={result.stop_reason} tools_used={result.tools_used}")
    print(f"  image block present in message transcript: {image_sent}")
    print(f"  any tool-result error recorded            : {had_tool_error}")
    print(f"  model answer                              : {result.answer!r}")
    if result.stop_reason == "request_error":
        print(f"  error: {result.error}")
    ok = image_sent and not had_tool_error and color_in_answer
    print("  PASS" if ok else "  FAIL -- image not delivered/seen by the model")
    return ok


def check_shuffle(num_seeds=6):
    """Fix 3: across several (csv, task_type) seeds, correct_index must not
    land at 0 every time. Uses a real stage1 Bedrock call per seed (cheap --
    text only, no chart rendering)."""
    print(f"\n=== answer-shuffle fix ({num_seeds} real stage1_qa calls) ===")
    from pipeline.generate import stage1_qa

    csv_text = (
        "year,region,count\n"
        "2021,North,34\n2022,South,61\n2023,East,48\n2024,West,90\n"
    )
    task_types = ["filter", "find_extremum", "sort", "determine_range",
                  "retrieve_value", "correlate"][:num_seeds]
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / "smoke.csv"
        csv_path.write_text(csv_text)
        cache_dir = Path(tmp) / "cache"
        indices = []
        for task_type in task_types:
            try:
                qa = stage1_qa(str(csv_path), task_type, examples={}, cache_dir=str(cache_dir))
            except Exception as exc:  # noqa: BLE001 -- report and keep going
                print(f"  {task_type}: generation dropped ({exc})")
                continue
            idx = qa["options"].index(qa["answer"])
            indices.append(idx)
            print(f"  {task_type:24s} correct_index={idx}  options={qa['options']}")
    ok = bool(indices) and set(indices) != {0}
    print("  PASS" if ok else "  FAIL -- correct_index was 0 for every seed (or nothing generated)")
    return ok


CHECKS = {"console": check_console, "screenshot": check_screenshot}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default="haiku,luna",
                        help="Comma-separated subset of haiku,luna (default: both).")
    parser.add_argument("--check", default="console,screenshot,shuffle",
                        help="Comma-separated subset of console,screenshot,shuffle.")
    parser.add_argument("--skip", default="",
                        help="Comma-separated checks to drop from --check.")
    args = parser.parse_args(argv)

    if not os.environ.get("AWS_BEARER_TOKEN_BEDROCK"):
        sys.exit("ERROR: AWS_BEARER_TOKEN_BEDROCK is not set. "
                 "See AWS-API/aws-api-test.env.example.")

    models = [m.strip() for m in args.model.split(",") if m.strip()]
    checks = {c.strip() for c in args.check.split(",") if c.strip()}
    checks -= {c.strip() for c in args.skip.split(",") if c.strip()}
    for m in models:
        if m not in MODEL_IDS:
            sys.exit(f"ERROR: unknown --model {m!r}; choose from {sorted(MODEL_IDS)}")

    start = time.monotonic()
    results = {}
    if "shuffle" in checks:
        results["shuffle"] = check_shuffle()
    for model_key in models:
        for check_name, fn in CHECKS.items():
            if check_name in checks:
                results[f"{check_name}:{model_key}"] = fn(model_key)

    print(f"\n=== summary ({time.monotonic() - start:.1f}s) ===")
    for name, ok in results.items():
        print(f"  {'PASS' if ok else 'FAIL':4s}  {name}")
    if not all(results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
