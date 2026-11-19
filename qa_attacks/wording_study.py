"""Run the predeclared wording study, using credentials already in the environment.

python -m qa_attacks.wording_study --raw .../raw --out .../wording-round2
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, wait
import json
from pathlib import Path
import threading
import time

from qa_attacks.chartgalaxy import load
from qa_attacks.evaluate import run
from qa_attacks.wording import (CHANNELS, DEV_IDS, MODELS, MODES, TEMPLATES,
                                build, digest, results, save_json, select_finalists)


def evaluate(root, workers=2):
    from pipeline.converse_agent import BedrockConverseClient

    class MeteredClient(BedrockConverseClient):
        def __init__(self, mode):
            super().__init__()
            self.mode = mode

        def converse(self, *args, **kwargs):
            start = time.monotonic()
            response = super().converse(*args, **kwargs)
            with lock, (root / "usage.jsonl").open("a") as stream:
                stream.write(json.dumps({"model": args[0] if args else kwargs["model"],
                    "mode": self.mode, "seconds": time.monotonic() - start,
                    "usage": response.get("usage"), "stopReason": response.get("stopReason")}) + "\n")
            return response

    lock = threading.Lock()
    expected = len((root / "attacked.jsonl").read_text().splitlines()) * len(MODELS) * len(MODES)
    for attempt in range(2):
        with ThreadPoolExecutor(max_workers=4) as pool:
            pending = {pool.submit(run, root, [model], workers=workers,
                                   client=MeteredClient(mode), mode=mode)
                       for model in MODELS for mode in MODES}
            while pending:
                done, pending = wait(pending, timeout=30)
                for future in done:
                    future.result()
                count = sum(len(p.read_text().splitlines()) for p in root.glob("eval/*/*.jsonl"))
                print(f"{root.name}: {count}/{expected} responses saved", flush=True)
        try:
            data = results(root)
            save_json(root / "metrics.json", data)
            return data
        except ValueError:
            if attempt:
                raise


def study(raw, out, workers=2):
    raw, out = Path(raw), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    validation_ids = [i.id for i in load(raw) if i.id not in DEV_IDS]
    plan = {"development_ids": list(DEV_IDS), "validation_ids": validation_ids,
            "models": list(MODELS), "modes": list(MODES), "channels": list(CHANNELS),
            "styles": list(TEMPLATES), "expected_responses": 1324,
            "development": "All ten styles; one call per question/condition/model/mode",
            "selection": "Top two non-direct styles per channel by macro clean-and-control-correct targeted ASR; alphabetical ties; retain direct baseline",
            "repeat": "One further independent call for each development finalist, clean image and neutral control; identical images",
            "validation": "One call on each of the remaining 19 questions for frozen finalists, direct baseline, clean image and neutral controls",
            "primary_metric": "Targeted wrong-answer rate conditional on same-run clean correctness; additionally require channel-matched neutral-control correctness",
            "temperature": "provider default", "victim_seed": None,
            "reasoning_measurement": "Observable final answer and brief rationale only; no claim about private reasoning",
            "action_measurement": "submit_answer arguments only; tool mode forces the tool call; no external actions",
            "gradient_optimization": False, "raw_sha256": digest(raw / "test.jsonl"),
            "runner_sha256": digest(__file__)}
    if (out / "plan.json").exists() and json.loads((out / "plan.json").read_text()) != plan:
        raise ValueError("Predeclared study plan changed; choose a new output directory")
    save_json(out / "plan.json", plan)
    development = out / "development"
    build(raw, development, DEV_IDS)
    evaluate(development, workers)
    selection = select_finalists(development)
    selection_path = out / "selection.json"
    if selection_path.exists() and json.loads(selection_path.read_text()) != selection:
        raise ValueError("Frozen selection changed")
    save_json(selection_path, selection)
    print("Frozen selection: " + json.dumps(selection["selection"]), flush=True)
    for phase, ids in (("repeat", DEV_IDS), ("validation", validation_ids)):
        root = out / phase
        build(raw, root, ids, selection["selection"], phase)
        evaluate(root, workers)
    print("Study complete; metrics.json is available in each phase directory.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--workers", type=int, default=2, help="Workers per model/mode; four groups run concurrently")
    args = parser.parse_args()
    study(args.raw, args.out, args.workers)


if __name__ == "__main__":
    main()
