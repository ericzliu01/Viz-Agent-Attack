"""Evaluate frozen corpora with a shared plain-JSON protocol; never reselect attacks.

python -m qa_attacks.json_study --root runs/qa_attacks/chartgalaxy \
    --out runs/qa_attacks/chartgalaxy/json-round1
Credentials must already be present in the environment.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, wait
import hashlib
import json
from pathlib import Path
import shutil
import threading
import time

from qa_attacks.evaluate import JSON_PROTOCOL, MAX_TOKENS, SYSTEMS, run

MODELS = ("us.anthropic.claude-haiku-5-5", "us.openai.gpt-5.6-luna")
SOURCES = {"development": "wording-round2/development",
           "validation": "wording-round2/validation",
           "cotta-50": "cotta-b32-50-cpu",
           "cotta-300": "cotta-b32-300-classification"}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def prepare(root, out):
    root, out = Path(root).resolve(), Path(out).resolve()
    corpora = {}
    for name, relative in SOURCES.items():
        source = root / relative
        rows = read_rows(source / "attacked.jsonl")
        files = {"attacked.jsonl"} | {p for r in rows for p in r["images"]}
        corpora[name] = {"source": str(source), "rows": len(rows),
                         "files": {p: digest(source / p) for p in sorted(files)}}
    plan = {"protocol": JSON_PROTOCOL, "system": SYSTEMS["json"], "models": list(MODELS),
            "tool_config": None, "max_tokens": MAX_TOKENS, "temperature": "provider default",
            "victim_seed": None, "corpora": corpora,
            "expected_responses": sum(c["rows"] for c in corpora.values()) * len(MODELS),
            "selection": "Reuse frozen images, prompts, wrong targets and finalists; no reselection",
            "scoring": "Only ans. Invalid completed replies count as failures, not retries. Report clean-correct and clean+control-correct ASR.",
            "code": {p: digest(Path(__file__).parent / p)
                     for p in ("evaluate.py", "answers.py", "json_study.py")}}
    out.mkdir(parents=True, exist_ok=True)
    path = out / "plan.json"
    if path.exists() and json.loads(path.read_text()) != plan:
        raise ValueError("Plan or inputs changed; use a fresh output directory")
    path.write_text(json.dumps(plan, indent=2) + "\n")
    for name, corpus in corpora.items():
        for relative, expected in corpus["files"].items():
            dest = out / name / relative
            if not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(Path(corpus["source"]) / relative, dest)
            if digest(dest) != expected:
                raise ValueError(f"Changed copied input: {dest}")
    return plan


def study(root, out, workers=4):
    from pipeline.converse_agent import BedrockConverseClient

    plan = prepare(root, out)
    out = Path(out)
    lock = threading.Lock()

    class MeteredClient(BedrockConverseClient):
        def __init__(self, corpus):
            super().__init__()
            self.corpus = corpus

        def converse(self, *args, **kwargs):
            start = time.monotonic()
            response = super().converse(*args, **kwargs)
            with lock, (out / "usage.jsonl").open("a") as stream:
                stream.write(json.dumps({"corpus": self.corpus,
                    "model": args[0] if args else kwargs["model"],
                    "seconds": time.monotonic() - start, "usage": response.get("usage"),
                    "stopReason": response.get("stopReason")}) + "\n")
            return response

    # Each model works through corpora in the same sequence, with bounded concurrency.
    def model_run(model):
        for name in SOURCES:
            for attempt in range(2):
                run(out / name, [model], workers=workers, client=MeteredClient(name), mode="json")
                path = out / name / "eval/json" / f"{model}.jsonl"
                records = read_rows(path)
                expected_ids = {r["id"] for r in read_rows(out / name / "attacked.jsonl")}
                if len(records) == len(expected_ids) and {r["id"] for r in records} == expected_ids:
                    break
                if attempt:
                    raise ValueError(f"Missing or duplicate responses: {path}")

    with ThreadPoolExecutor(max_workers=len(MODELS)) as pool:
        pending = {pool.submit(model_run, model) for model in MODELS}
        while pending:
            done, pending = wait(pending, timeout=30)
            for future in done:
                future.result()
            count = sum(len(read_rows(p)) for p in out.glob("*/eval/json/*.jsonl"))
            print(f"Plain JSON: {count}/{plan['expected_responses']} replies saved", flush=True)
    print("Complete; all frozen corpora evaluated with the same JSON protocol.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--workers", type=int, default=4, help="Concurrent calls per model")
    args = parser.parse_args()
    study(args.root, args.out, args.workers)
