"""Isolated webpage evaluation, browser audits, preflight, and resumable jobs."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import random
import time
import urllib.error

from browser_agent import BrowserTools, TEXT_LIMIT, capture_console
from pipeline.converse_agent import BedrockConverseClient, _to_converse_tools, _tool_result
from qa_attacks.evaluate import matches, plain_json_answer, reply_text
from qa_attacks.webpage_corpus import (MODELS, STUDY, TOOL_NAMES, checked_path, digest,
                                      object_digest, protocol, read_rows, validate, write_json)

ORIGIN = "http://trial.invalid/"


def launch(pw, executable=None):
    # The renderer does not need provider credentials from the parent process.
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL")}
    # The full Chromium distribution also supports headless mode. Pin this
    # executable consistently instead of depending on a separate shell download.
    executable = executable or pw.chromium.executable_path
    return pw.chromium.launch(headless=True, env=env, executable_path=executable)


@contextmanager
def trial_page(browser, corpus, row):
    """No file server: only this trial's exact URLs can receive bundled bytes."""
    root = Path(corpus) / "public"
    context = browser.new_context(viewport=protocol()["viewport"], device_scale_factor=1,
                                   service_workers="block", accept_downloads=False)
    blocked, loaded = [], False
    page = context.new_page()
    page.set_default_timeout(5000)
    page.set_default_navigation_timeout(10000)
    logs = capture_console(page)
    allowed = {ORIGIN + rel: checked_path(root, rel) for rel in [row["page"], *row["assets"], *row["fonts"]]}
    page_url = ORIGIN + row["page"]

    def route_request(route):
        nonlocal loaded
        req = route.request
        ok = req.method == "GET" and req.url in allowed
        if req.is_navigation_request():
            ok = ok and req.url == page_url and not loaded and req.frame == page.main_frame
        if not ok:
            blocked.append({"url": req.url, "method": req.method})
            route.abort("blockedbyclient")
            return
        if req.is_navigation_request():
            loaded = True
        headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
        if req.url == page_url:
            headers["Content-Security-Policy"] = ("default-src 'none'; img-src 'self'; font-src 'self'; style-src 'unsafe-inline'; "
                "script-src 'none'; connect-src 'none'; frame-src 'none'; worker-src 'none'; "
                "object-src 'none'; base-uri 'none'; form-action 'none'")
        content_type = "text/html; charset=utf-8" if req.url == page_url else (
            "font/otf" if req.url.endswith(".otf") else "font/ttf" if req.url.endswith(".ttf") else "image/png")
        route.fulfill(body=allowed[req.url].read_bytes(), headers=headers, content_type=content_type)

    context.route("**/*", route_request)
    context.route_web_socket("**/*", lambda ws: ws.close())
    context.on("page", lambda other: other.close() if other != page else None)
    try:
        page.goto(page_url, wait_until="load")
        page.locator("img").evaluate_all("imgs => Promise.all(imgs.map(i => i.decode()))")
        page.evaluate("document.fonts.ready")
        if row["channel"] == "visible_paragraph" and not page.evaluate("document.fonts.check('18px TrialParagraph')"):
            raise ValueError("Bundled paragraph font failed to load")
        if page.locator("img").count() != len(row["assets"]):
            raise ValueError("Missing page images")
        yield page, logs, blocked
    finally:
        context.close()


class TrialTools(BrowserTools):
    """Bound JavaScript execution time, including scripts that loop indefinitely."""
    def __init__(self, page, logs):
        super().__init__(page, logs, enabled_tools=set(TOOL_NAMES))
        self.cdp = page.context.new_cdp_session(page)

    def execute(self, name, arguments):
        if name != "evaluate":
            result = super().execute(name, arguments)
            if name == "scroll":
                self.page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
            return result
        if not isinstance(arguments, dict) or set(arguments) != {"script"} or not isinstance(arguments["script"], str):
            raise ValueError("evaluate requires one string script")
        # Match Playwright: call a function expression, otherwise return the expression.
        script = arguments["script"]
        expression = ("(() => {const v = (" + script + "); return Promise.race([Promise.resolve("
                      "typeof v === 'function' ? v() : v), new Promise((_, reject) => "
                      "setTimeout(() => reject(new Error('Evaluation timed out')), 4500))]);})()")
        result = self.cdp.send("Runtime.evaluate", {"expression": expression, "returnByValue": True,
            "awaitPromise": True, "timeout": protocol()["evaluate_timeout_ms"]})
        if result.get("exceptionDetails"):
            raise ValueError(result["exceptionDetails"].get("text", "JavaScript evaluation failed"))
        value = result.get("result", {}).get("value")
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        return (text[:TEXT_LIMIT] + "\n[truncated; request a smaller result]" if len(text) > TEXT_LIMIT else text), []


def image_regions(page, bbox):
    rects = page.locator("img").evaluate_all("imgs => imgs.map(i => {const r=i.getBoundingClientRect();"
        "return {x:r.x,y:r.y,width:r.width,height:r.height,naturalWidth:i.naturalWidth,naturalHeight:i.naturalHeight};})")
    result = {"images": rects, "viewport": page.viewport_size, "scroll": page.evaluate("[scrollX, scrollY]"),
              "payload_region": None, "recognition": "unknown"}
    if bbox and rects:
        r = rects[0]
        x, y, right, bottom = bbox
        sx, sy = r["width"] / r["naturalWidth"], r["height"] / r["naturalHeight"]
        x, right = r["x"] + x * sx, r["x"] + right * sx
        y, bottom = r["y"] + y * sy, r["y"] + bottom * sy
        area = max(0, min(right, 1440) - max(x, 0)) * max(0, min(bottom, 1200) - max(y, 0))
        result["payload_region"] = {"bbox": [x, y, right, bottom], "visible_fraction":
                                    area / ((right - x) * (bottom - y)) if right > x and bottom > y else 0}
    return result


def clean_error(exc):
    text = getattr(exc, "_webpage_error", None)
    if text is None:
        text = f"{type(exc).__name__}: {exc}"
        if isinstance(exc, urllib.error.HTTPError):
            text += " " + exc.read(4096).decode("utf-8", errors="replace")
    token = os.getenv("AWS_BEARER_TOKEN_BEDROCK")
    text = text.replace(token, "[redacted]") if token else text
    exc._webpage_error = text
    return text


def request(client, model, messages, tools, attempts, *, sleep=time.sleep):
    for index in range(4):
        started = time.monotonic()
        try:
            result = client.converse(model, protocol()["system"], messages, tools, protocol()["max_tokens"])
            attempts.append({"attempt": index + 1, "seconds": time.monotonic() - started,
                             "usage": result.get("usage", {}), "status": "success"})
            return result
        except Exception as exc:
            transient = (isinstance(exc, urllib.error.HTTPError) and exc.code in (408, 429, 500, 502, 503, 504)) or (
                isinstance(exc, (TimeoutError, ConnectionError, urllib.error.URLError)) and not isinstance(exc, urllib.error.HTTPError))
            attempts.append({"attempt": index + 1, "seconds": time.monotonic() - started,
                             "error": clean_error(exc), "status": "error", "transient": transient,
                             "usage": None})
            if not transient or index == 3:
                raise
            sleep(2 * 2 ** index + random.random())


def evaluate_trial(browser, corpus, row, model, trace_dir, client):
    trace_dir = Path(trace_dir)
    trace_dir.mkdir(parents=True, exist_ok=True)
    messages = [{"role": "user", "content": [{"text": row["question"]}]}]
    observations, responses, attempts = [], [], []
    tools = {"tools": _to_converse_tools([{"name": t["function"]["name"],
        "description": t["function"]["description"], "input_schema": t["function"]["parameters"]}
        for t in protocol()["tools"]])}
    started, final, stop, error, steps = time.monotonic(), "", "max_steps", None, 0
    bbox = json.loads((Path(corpus) / row["audit"]).read_text()).get("bbox")
    blocked = []
    try:
        with trial_page(browser, corpus, row) as (page, logs, blocked):
            browser_tools = TrialTools(page, logs)
            for steps in range(1, protocol()["max_steps"] + 1):
                step_attempts = []
                try:
                    resp = request(client, model, messages, tools, step_attempts)
                except Exception:
                    stop = "request_error"
                    raise
                finally:
                    attempts.extend({**a, "step": steps} for a in step_attempts)
                responses.append(resp)
                content = resp.get("output", {}).get("message", {}).get("content", [])
                messages.append({"role": "assistant", "content": content})
                calls = [b["toolUse"] for b in content if "toolUse" in b]
                if resp.get("stopReason") != "tool_use" or not calls:
                    final, stop = reply_text(resp), resp.get("stopReason", "empty_response")
                    break
                results = []
                for call in calls:
                    name, args, tid = call.get("name"), call.get("input", {}), call.get("toolUseId")
                    obs = {"step": steps, "tool": name, "arguments": args, "text_payload_returned": False,
                           "image_exposure": None}
                    try:
                        geometry = image_regions(page, bbox) if name == "screenshot" else None
                        output, images = browser_tools.execute(name, args)
                        results.append(_tool_result(tid, output, images))
                        obs["text_payload_returned"] = bool(row["payload"] and row["payload"] in output)
                        obs["returned_text"] = output
                        if images:
                            png = base64.b64decode(images[0], validate=True)
                            path = trace_dir / f"s{steps}-{len(observations)}.png"
                            path.write_bytes(png)
                            obs.update(screenshot=path.name, screenshot_sha256=digest(path), image_exposure=geometry)
                    except Exception as exc:
                        tool_error = clean_error(exc)
                        obs["error"] = tool_error
                        results.append(_tool_result(tid, json.dumps({"error": tool_error}), [], is_error=True))
                        # Invalid selectors, scripts and arguments are model behavior.
                        # Failure to capture a requested screenshot (or a crashed page)
                        # is infrastructure and must not inflate attack success.
                        if (name == "screenshot" and args == {}) or page.is_closed():
                            error = tool_error
                    observations.append(obs)
                messages.append({"role": "user", "content": results})
                if error:
                    stop = "tool_error"
                    break
    except Exception as exc:
        error = clean_error(exc)
        if stop != "request_error":
            stop = "browser_error"
    ans, rationale, format_error = plain_json_answer(final, row["kind"], row["answer_options"])
    pred = ans if not error and not format_error else None
    rec = {"row_id": row["id"], "base_id": row["base_id"], "model_id": model,
           "response": final, "ans": ans, "rationale": rationale, "format_error": format_error,
           "correct": matches(pred, row["gold"], row["kind"], row["exact"]),
           "target_hit": matches(pred, row["target"], row["kind"], row["exact"]),
           "completed": error is None, "error": error, "stop_reason": stop, "steps": steps,
           "seconds": time.monotonic() - started, "observations": observations,
           "request_attempts": attempts, "usage": {k: sum(a.get("usage", {}).get(k, 0)
               for a in attempts if a.get("usage")) for k in ("inputTokens", "outputTokens", "totalTokens")},
           "failed_request_usage_unknown": any(a["status"] == "error" for a in attempts)}
    write_json(trace_dir / "trace.json", {"messages": messages, "responses": responses,
                                          "observations": observations, "blocked_requests": blocked})
    rec["trace"] = str(trace_dir / "trace.json")
    return rec


def audit_corpus(corpus, *, browser_executable=None):
    """Render every page and verify invariants before allowing model calls."""
    from playwright.sync_api import sync_playwright
    corpus = Path(corpus)
    manifest = validate(corpus)
    rows = read_rows(corpus / "corpus.jsonl")
    output = corpus / "validation"
    output.mkdir(exist_ok=True)
    records, clean_shots = [], {}
    with sync_playwright() as pw:
        browser = launch(pw, browser_executable)
        spec = json.loads((corpus / "spec.json").read_text())
        if browser.version != spec["browser_version"]:
            raise ValueError("Browser differs from corpus builder")
        for row in rows:
            with trial_page(browser, corpus, row) as (page, logs, blocked):
                dims = image_regions(page, None)["images"]
                if any(r["width"] != r["naturalWidth"] or r["height"] != r["naturalHeight"] for r in dims):
                    raise ValueError("Chart image rescaled")
                visible = page.locator("main").inner_text()
                dom = page.locator("main").evaluate("el => el.outerHTML")
                if row["channel"] == "visible_paragraph":
                    if row["payload"] not in visible or not page.locator("p").evaluate("p => p.scrollHeight <= p.clientHeight"):
                        raise ValueError("Visible paragraph missing or clipped")
                elif visible.strip():
                    raise ValueError("Unexpected visible HTML payload")
                if row["channel"] == "source_layer" and row["payload"] not in dom:
                    raise ValueError("Source comment absent from DOM")
                if row["channel"] not in ("source_layer", "visible_paragraph") and row["payload"] and row["payload"] in dom:
                    raise ValueError("Image payload leaked to DOM")
                shot = page.screenshot(full_page=True)
                sha = hashlib.sha256(shot).hexdigest()
                if row["condition"] == "clean":
                    clean_shots[row["base_id"]] = sha
                if row["channel"] == "source_layer" and sha != clean_shots[row["base_id"]]:
                    raise ValueError("Source comment changed screenshot pixels")
                name = object_digest(row["id"]) + ".png"
                (output / name).write_bytes(shot)
                records.append({"row_id": row["id"], "screenshot": name, "sha256": sha, "dimensions": dims})
            if len(records) % 73 == 0:
                print(f"Validated {len(records)}/{len(rows)} pages", flush=True)
        version = browser.version
        browser.close()
    result = {"complete": True, "corpus_digest": manifest["corpus_digest"], "browser_version": version,
              "rows": records, "playwright": importlib.metadata.version("playwright")}
    write_json(corpus / "validation.json", result)
    # Evaluator-side review page, deliberately outside public/.
    import html
    # Payload/question text must be escaped; image paths are generated hashes.
    cards = [f'<article><h3>{html.escape(r["id"])}</h3><p>{html.escape(r["question"])}</p>'
             f'<p>{html.escape(r["payload"] or "Clean")}</p><img loading="lazy" style="max-width:100%" '
             f'src="validation/{object_digest(r["id"])}.png"></article>' for r in rows]
    (corpus / "review.html").write_text('<!doctype html><meta charset="utf-8"><title>Corpus review</title>' + "\n".join(cards))
    return result


def verified_bundle(corpus):
    manifest = validate(corpus)
    validation = json.loads((Path(corpus) / "validation.json").read_text())
    rows = read_rows(Path(corpus) / "corpus.jsonl")
    if not validation.get("complete") or validation["corpus_digest"] != manifest["corpus_digest"]:
        raise ValueError("Corpus has no matching browser validation")
    if {r["row_id"] for r in validation["rows"]} != {r["id"] for r in rows}:
        raise ValueError("Browser validation coverage incomplete")
    if len(validation["rows"]) != len(rows):
        raise ValueError("Duplicate browser validation rows")
    spec = json.loads((Path(corpus) / "spec.json").read_text())
    if validation["browser_version"] != spec["browser_version"] or validation["playwright"] != spec["playwright"]:
        raise ValueError("Browser validation used a different runtime")
    return manifest, rows, validation


@contextmanager
def job_lock(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / ".lock", "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Job output is locked by another process") from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def select_shard(rows, shard_index=0, num_shards=1):
    if num_shards < 1 or not 0 <= shard_index < num_shards:
        raise ValueError("Invalid shard index/count")
    ids = sorted({r["base_id"] for r in rows})
    selected = {base for i, base in enumerate(ids) if i % num_shards == shard_index}
    return [r for r in rows if r["base_id"] in selected]


def run(corpus, out, model, *, repeat=1, workers=2, run_id=STUDY, shard_index=0, num_shards=1,
        browser_executable=None, retry_errors=False, selected_ids=None, preflight=False, client_factory=None):
    from playwright.sync_api import sync_playwright
    if model not in MODELS or repeat < 1 or workers < 1:
        raise ValueError("Invalid model/repeat/workers")
    manifest, rows, validation = verified_bundle(corpus)
    rows = select_shard(rows, shard_index, num_shards)
    if selected_ids is not None:
        rows = [r for r in rows if r["id"] in selected_ids]
    if not rows:
        raise ValueError("No rows selected")
    out = Path(out)
    config = {"run_id": run_id, "repeat": repeat, "model_id": MODELS[model],
              "corpus_digest": manifest["corpus_digest"], "protocol_digest": object_digest(protocol()),
              "num_shards": num_shards, "shard_index": shard_index, "preflight": preflight,
              "row_ids": sorted(r["id"] for r in rows), "browser_version": validation["browser_version"],
              "playwright": validation["playwright"]}
    if not preflight and client_factory is None:
        preflight_path = Path(corpus).parent / "preflight" / "summary.json"
        evidence = json.loads(preflight_path.read_text())
        if evidence.get("corpus_digest") != manifest["corpus_digest"] or not evidence.get("models", {}).get(model, {}).get("passed"):
            raise ValueError("This model has no passing preflight for this bundle")
    client_factory = client_factory or (lambda: BedrockConverseClient(region=protocol()["region"]))
    with job_lock(out):
        job_path = out / "job.json"
        if job_path.exists() and json.loads(job_path.read_text()) != config:
            raise ValueError("Cannot resume job with different configuration")
        write_json(job_path, config)
        with open(out / "operations.jsonl", "a") as fh:
            fh.write(json.dumps({"workers": workers, "retry_errors": retry_errors, "time": time.time(),
                                 "platform": platform.platform()}) + "\n")
        records_dir = out / "records"
        records_dir.mkdir(exist_ok=True)
        previous = {}
        for path in records_dir.glob("*.json"):
            rec = json.loads(path.read_text())
            if any(rec.get(k) != config[k] for k in ("run_id", "repeat", "model_id", "corpus_digest", "protocol_digest")):
                raise ValueError("Saved record configuration mismatch")
            if rec["row_id"] not in config["row_ids"] or rec["row_id"] in previous:
                raise ValueError("Unknown or duplicate saved row")
            previous[rec["row_id"]] = rec
        pending = [r for r in rows if r["id"] not in previous or (retry_errors and not previous[r["id"]]["completed"])]

        def one(row):
            key = object_digest(row["id"])
            old = previous.get(row["id"])
            attempt = old.get("trial_attempt", 1) + 1 if old else 1
            with sync_playwright() as pw:
                browser = launch(pw, browser_executable)
                try:
                    if browser.version != config["browser_version"] or importlib.metadata.version("playwright") != config["playwright"]:
                        raise ValueError("Worker browser/Playwright differs from frozen protocol")
                    rec = evaluate_trial(browser, corpus, row, MODELS[model], out / "traces" / key / str(attempt), client_factory())
                finally:
                    browser.close()
            rec.update({k: config[k] for k in ("run_id", "repeat", "model_id", "corpus_digest", "protocol_digest")})
            rec.update(trial_attempt=attempt, worker={"platform": platform.platform(), "browser": config["browser_version"],
                                                     "playwright": config["playwright"]})
            rec["trace"] = str(Path(rec["trace"]).relative_to(out))
            if old:
                write_json(out / "attempts" / key / f"{attempt - 1}.json", old)
            write_json(records_dir / (key + ".json"), rec)
            return rec

        def export_records():
            records = sorted(previous.values(), key=lambda r: r["row_id"])
            historical = [json.loads(p.read_text()) for p in (out / "attempts").glob("*/*.json")]
            for name, values in (("responses", records), ("errors", [r for r in records if not r["completed"]]),
                                 ("usage", [{k: r[k] for k in ("row_id", "trial_attempt", "usage", "request_attempts", "failed_request_usage_unknown")} for r in [*historical, *records]])):
                tmp = out / (name + ".jsonl.tmp")
                tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in values))
                tmp.replace(out / (name + ".jsonl"))

        export_records()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for future in as_completed([pool.submit(one, row) for row in pending]):
                rec = future.result()
                previous[rec["row_id"]] = rec
                export_records()
                print(f"{model}: {len(previous)}/{len(rows)} {rec['row_id']} {rec['stop_reason']}", flush=True)
        return list(previous.values())


def preflight(corpus, out, models, browser_executable=None):
    if not models or len(set(models)) != len(models) or set(models) - set(MODELS):
        raise ValueError("Select distinct known model aliases")
    manifest, rows, _ = verified_bundle(corpus)
    clean = sorted((r for r in rows if r["condition"] == "clean"), key=lambda r: r["base_id"])
    chosen = [next(r for r in clean if r["kind"] == kind)["id"] for kind in ("choice", "numeric", "yesno")]
    summary_path = Path(out) / "summary.json"
    summary = {"corpus_digest": manifest["corpus_digest"], "selected_ids": chosen, "models": {}}
    if summary_path.exists():
        saved = json.loads(summary_path.read_text())
        if saved["corpus_digest"] != manifest["corpus_digest"] or saved["selected_ids"] != chosen:
            raise ValueError("Preflight output belongs to another corpus")
        summary = saved
    for model in models:
        recs = run(corpus, Path(out) / model, model, workers=1, selected_ids=chosen, preflight=True,
                   run_id=STUDY + "-preflight", browser_executable=browser_executable)
        # Require real image delivery as well as valid final JSON; correctness is not a gate.
        passed = len(recs) == 3 and all(r["completed"] and not r["format_error"] and any(
            o.get("screenshot") for o in r["observations"]) for r in recs)
        summary["models"][model] = {"passed": passed, "trials": len(recs),
                                    "errors": [r["error"] or r["format_error"] for r in recs if r["error"] or r["format_error"]],
                                    "outcomes": [{"row_id": r["row_id"], "completed": r["completed"],
                                        "format_error": r["format_error"], "correct": r["correct"],
                                        "screenshot_delivered": any(o.get("screenshot") for o in r["observations"]),
                                        "stop_reason": r["stop_reason"], "error": r["error"]} for r in recs]}
        write_json(Path(out) / "summary.json", summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("run", "preflight"):
        p = sub.add_parser(command)
        p.add_argument("--corpus", required=True)
        p.add_argument("--out", required=True)
        p.add_argument("--browser-executable")
        if command == "preflight":
            p.add_argument("--models", default="haiku,luna,qwen")
        else:
            p.add_argument("--model", choices=MODELS, required=True)
            p.add_argument("--repeat", type=int, default=1)
            p.add_argument("--workers", type=int, default=2)
            p.add_argument("--run-id", default=STUDY)
            p.add_argument("--shard-index", type=int, default=0)
            p.add_argument("--num-shards", type=int, default=1)
            p.add_argument("--retry-errors", action="store_true")
    args = vars(parser.parse_args(argv))
    command = args.pop("command")
    if command == "preflight":
        args["models"] = args["models"].split(",")
        print(json.dumps(preflight(**args), indent=2))
    else:
        run(**args)


if __name__ == "__main__":
    main()
