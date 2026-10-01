"""Multi-modal trial runner: gives a vision model BOTH the rendered screenshot
AND the raw HTML source together, letting it cross-reference visual and textual
information to answer questions about the chart.

This is condition "multimodal_combined" -- it extends "vision_screenshot"
(run_vlm_suite.py) by also injecting the full HTML into the prompt, and extends
"raw_source" (run_attack_suite.py) by also providing the rendered image.

Research question: does access to both modalities help a model resist
vis-attacks that exploit discrepancies between what the HTML says and what the
rendered chart shows?

Hover targeting, timing overrides, and unsupported attacks are identical to
run_vlm_suite.py; see that file's docstring for details.

Setup: same as run_vlm_suite.py (Playwright + a vision-capable Ollama model).

Usage:
  python run_multimodal_suite.py --models llava:13b --libraries d3
  python run_multimodal_suite.py --headed --save-screenshots ./mm_debug
  python run_multimodal_suite.py
"""
import argparse
import base64
import os
import time

import requests
from playwright.sync_api import sync_playwright

from results_logger import append_row
from run_attack_suite import already_done_keys, discover_pages, grade
from run_vlm_suite import (
    HOVER_TARGETS, HOVER_FNS, TIMING_OVERRIDES, UNSUPPORTED,
    VIEWPORT, DEFAULT_WAIT_MS, capture_screenshot,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OLLAMA_URL = "http://localhost:11434/api/generate"

DEFAULT_MODELS = ["llava:13b", "llama3.2-vision", "qwen2.5vl"]
DEFAULT_LIBRARIES = ["d3", "plotly", "chartjs", "vega-lite"]

CONDITION = "multimodal_combined"

PROMPT_TEMPLATE = """You are looking at a data visualization. You have been given a screenshot of the rendered page (the image attached) and its underlying HTML source (below).

--- BEGIN HTML SOURCE ---
{html}
--- END HTML SOURCE ---

Question: {question}

Use both the screenshot and the HTML source together to answer. Do not prioritize one over the other. Answer with just the final answer (a short value, e.g. a number or a single word/name). Do not explain your reasoning.
"""


def call_ollama_vision(model, prompt, image_b64, timeout):
    start = time.time()
    resp = requests.post(
        OLLAMA_URL,
        json={"model": model, "prompt": prompt, "images": [image_b64], "stream": False},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    latency_ms = int((time.time() - start) * 1000)
    return data.get("response", ""), latency_ms


def run_trial(page, library, attack_id, real_attack_id, html_path, question, ground_truth,
              model, timeout, done_keys, save_dir, answer_type="free"):
    key = (library, attack_id, question, model)
    if key in done_keys:
        print(f"  [skip] {library}/{attack_id} x {model} (already logged)")
        return

    try:
        png_bytes, hover_note = capture_screenshot(page, library, real_attack_id, html_path)
    except Exception as exc:
        append_row({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "library": library, "attack_id": attack_id, "condition": CONDITION,
            "model": model, "question": question, "ground_truth": ground_truth,
            "response": "", "extracted_answer": "", "correct": "needs_review",
            "latency_ms": 0, "notes": f"screenshot_error: {exc}",
        })
        done_keys.add(key)
        print(f"  [needs_review] {library}/{attack_id} x {model} (screenshot_error: {exc})")
        return

    if save_dir:
        os.makedirs(save_dir, exist_ok=True)
        safe_model = model.replace(":", "-")
        out_path = os.path.join(save_dir, f"{library}__{attack_id}__{safe_model}.png")
        with open(out_path, "wb") as f:
            f.write(png_bytes)

    with open(html_path, encoding="utf-8") as f:
        html_source = f.read()

    image_b64 = base64.b64encode(png_bytes).decode("ascii")
    prompt = PROMPT_TEMPLATE.format(html=html_source, question=question)

    try:
        response, latency_ms = call_ollama_vision(model, prompt, image_b64, timeout)
        notes = hover_note
    except requests.RequestException as exc:
        response, latency_ms, notes = "", 0, f"request_error: {exc}"

    if notes.startswith("request_error"):
        correct, extracted = "needs_review", ""
    else:
        correct, extracted = grade(response, ground_truth, answer_type)

    append_row({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "library": library,
        "attack_id": attack_id,
        "condition": CONDITION,
        "model": model,
        "question": question,
        "ground_truth": ground_truth,
        "response": response,
        "extracted_answer": extracted,
        "correct": correct,
        "latency_ms": latency_ms,
        "notes": notes,
    })
    done_keys.add(key)
    print(f"  [{correct}] {library}/{attack_id} x {model}" + (f" ({notes})" if notes else ""))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS),
                         help="Comma-separated Ollama vision-model tags (e.g. llava:13b,llama3.2-vision)")
    parser.add_argument("--libraries", default=",".join(DEFAULT_LIBRARIES),
                         help="Comma-separated library names (subset of d3,plotly,chartjs,vega-lite)")
    parser.add_argument("--timeout", type=float, default=180.0,
                         help="Per-request timeout in seconds (multimodal prompts are longer than vision-only)")
    parser.add_argument("--limit", type=int, default=None,
                         help="Max attacks per library (for a small pilot run); default is all")
    parser.add_argument("--headed", action="store_true",
                         help="Run Chromium with a visible window instead of headless (for debugging hover targeting)")
    parser.add_argument("--save-screenshots", default=None, metavar="DIR",
                         help="Also write every captured PNG to this directory for manual inspection")
    args = parser.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    libraries = {l.strip() for l in args.libraries.split(",") if l.strip()}

    clean_by_key, attacks = discover_pages()
    attacks = [a for a in attacks if a["library"] in libraries]
    if args.limit is not None:
        capped = []
        seen_per_library = {}
        for attack in attacks:
            count = seen_per_library.get(attack["library"], 0)
            if count >= args.limit:
                continue
            seen_per_library[attack["library"]] = count + 1
            capped.append(attack)
        attacks = capped

    skipped = [a for a in attacks if (a["library"], a["attack_id"]) in UNSUPPORTED]
    attacks = [a for a in attacks if (a["library"], a["attack_id"]) not in UNSUPPORTED]
    if skipped:
        print("Skipping (multi-step interaction not automated):")
        for a in skipped:
            reason = UNSUPPORTED[(a["library"], a["attack_id"])]
            print(f"  - {a['library']}/{a['attack_id']}: {reason}")

    done_keys = already_done_keys(CONDITION)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        page = browser.new_page(viewport=VIEWPORT)

        for model in models:
            print(f"=== model: {model} ===")
            for attack in attacks:
                library = attack["library"]

                run_trial(
                    page, library, attack["attack_id"], attack["attack_id"], attack["html_path"],
                    attack["question"], attack["ground_truth"], model,
                    args.timeout, done_keys, args.save_screenshots, attack["answer_type"],
                )

                clean = clean_by_key.get((library, attack["chart_type"]))
                if clean is not None:
                    run_trial(
                        page, library, f"{attack['attack_id']}__clean_baseline", attack["attack_id"],
                        clean["html_path"], attack["question"], attack["ground_truth"], model,
                        args.timeout, done_keys, args.save_screenshots, attack["answer_type"],
                    )

        browser.close()


if __name__ == "__main__":
    main()
