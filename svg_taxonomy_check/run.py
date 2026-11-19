"""Run the Xu & Wall SVG taxonomy prompts on Bedrock models.

  python3 svg_taxonomy_check/run.py --repo ~/SVG_taxonomy --model us.anthropic.claude-sonnet-5-5 \
      --indices 0-4 --out results_dir

Prompts are built exactly as the repo's llm/gen_prompt.py builds them (task
description, newline, raw SVG) and sent as one user message, zero-shot, with
no system prompt. Sonnet 5.5 and GPT-6-luna reject `temperature`, so model
defaults are used (the paper used gpt-4-turbo-preview at temperature 0).
Replies are appended to <out>/<model>.jsonl; finished items are skipped on
re-run, so the command can be repeated to resume or retry errors.
Credentials come from the environment (e.g. AWS_BEARER_TOKEN_BEDROCK).
"""
import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import items as I  # noqa: E402
import imgprompts as IP  # noqa: E402


def parse_indices(s):
    out = []
    for part in s.split(","):
        if "-" in part:
            a, b = part.split("-")
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def make_client(region):
    import boto3
    from botocore.config import Config
    return boto3.client("bedrock-runtime", region_name=region,
                        config=Config(read_timeout=900, retries={"max_attempts": 8, "mode": "adaptive"}))


def call(client, model, content, max_tokens):
    t0 = time.time()
    r = client.converse(modelId=model, messages=[{"role": "user", "content": content}],
                        inferenceConfig={"maxTokens": max_tokens})
    texts = [c["text"] for c in r["output"]["message"]["content"] if "text" in c]
    return dict(reply="\n".join(texts), stop=r.get("stopReason"), usage=r.get("usage", {}),
                seconds=round(time.time() - t0, 1))


def content_for(a, prompts, t):
    """Message content: SVG mode = one text block (prompt + raw SVG);
    image mode = the image-mode prompt text, then the PNG."""
    if not a.png_root:
        return [{"text": I.build_prompt(a.repo, prompts, *t)}]
    with open(IP.png_path(a.png_root, a.repo, *t), "rb") as f:
        png = f.read()
    return [{"text": IP.build_image_prompt(t[0], t[1], t[2])},
            {"image": {"format": "png", "source": {"bytes": png}}}]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="checkout of github.com/lebretou/SVG_taxonomy")
    ap.add_argument("--model", required=True)
    ap.add_argument("--indices", default="0-4", help="dataset indices per cell, e.g. 0-4 or 0-19")
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--max-tokens", type=int, default=32000)
    ap.add_argument("--region", default=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-west-2")
    ap.add_argument("--png-root", help="image mode: send the chart as a PNG rendered from the SVG (see imgprompts.py)")
    ap.add_argument("--dry-run", action="store_true", help="list items and prompt sizes, call nothing")
    a = ap.parse_args()

    prompts = I.load_prompts(a.repo)
    todo = I.all_items(a.repo, prompts, parse_indices(a.indices))
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, a.model.replace("/", "_") + (".image" if a.png_root else "") + ".jsonl")
    done = set()
    if os.path.exists(path):
        for line in open(path):
            r = json.loads(line)
            if r.get("error") is None and r.get("stop") not in ("max_tokens",):
                done.add(r["item"])
    todo = [t for t in todo if I.item_id(*t) not in done]
    print(f"{len(done)} done, {len(todo)} to run -> {path}", flush=True)
    if a.dry_run:
        if a.png_root:
            missing = [t for t in todo if not os.path.exists(IP.png_path(a.png_root, a.repo, *t))]
            print(f"image mode: {len(missing)} PNGs missing")
            print(content_for(a, prompts, todo[0])[0]["text"])
            return
        chars = sum(len(I.build_prompt(a.repo, prompts, *t)) for t in todo)
        print(f"prompt chars total {chars:,} (~{chars // 3.5:,.0f} tokens)")
        return

    client = make_client(a.region)
    lock = threading.Lock()
    n_ok = n_err = 0

    def work(t):
        rec = dict(item=I.item_id(*t), chart=t[0], cond=t[1], task=t[2], idx=t[3], model=a.model,
                   mode="image" if a.png_root else "svg")
        try:
            rec.update(call(client, a.model, content_for(a, prompts, t), a.max_tokens), error=None)
        except Exception as e:  # recorded and retried on the next run
            rec.update(reply=None, error=repr(e)[:500])
        return rec

    with ThreadPoolExecutor(a.workers) as ex, open(path, "a") as f:
        futs = [ex.submit(work, t) for t in todo]
        for k, fu in enumerate(as_completed(futs), 1):
            rec = fu.result()
            with lock:
                f.write(json.dumps(rec) + "\n")
                f.flush()
                if rec["error"]:
                    n_err += 1
                else:
                    n_ok += 1
            if k % 20 == 0 or rec["error"]:
                print(f"{k}/{len(todo)} ok={n_ok} err={n_err} last={rec['item']} {rec.get('error') or rec.get('stop')}", flush=True)
    print(f"finished ok={n_ok} err={n_err}")


if __name__ == "__main__":
    main()
