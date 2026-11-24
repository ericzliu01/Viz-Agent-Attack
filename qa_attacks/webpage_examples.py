"""Documentation-only browser gallery using existing, unmodified attack PNGs.

Makes no victim calls or new CoTTA optimizations. Not the experiment builder.
Packaged source PNGs permit regeneration without the ignored runs/ directory.
"""
import argparse
import hashlib
import html
import json
from pathlib import Path
import shutil

from PIL import Image

from qa_attacks.wording import FACTORIAL_TEMPLATES, payloads

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/assets/chartgalaxy-webpage-plan"
BASE_ID = "c174nsb3_5"
CHANNELS = ("clean", "banner", "footnote", "overlay", "low_contrast", "cotta",
            "visible_paragraph", "source_layer")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(browser_executable=None):
    from playwright.sync_api import sync_playwright

    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "originals").mkdir(exist_ok=True)
    inputs_path = ROOT / "reports/comprehensive/data/inputs/channel-pilot/r1.json"
    rows = [r for r in json.loads(inputs_path.read_text())
            if r["attack"]["base_id"] == BASE_ID]
    clean = next(r for r in rows if r["attack"]["condition"] == "clean")
    sources = {}
    for channel in CHANNELS[:5]:
        row = clean if channel == "clean" else next(r for r in rows
            if r["attack"]["channel"] == channel and r["attack"]["subtype"] == "action_jailbreak")
        info = row["images"][0]
        dest = OUTPUT / "originals" / f"{channel}.png"
        if not dest.exists():
            shutil.copyfile(ROOT / info["source"], dest)
        if digest(dest) != info["sha256"]:
            raise ValueError(f"Archived pixels changed: {channel}")
        sources[channel] = {"input_manifest": str(inputs_path.relative_to(ROOT)),
                            "row_id": row["id"], "image_sha256": digest(dest),
                            "payload": row["attack"]["payload"]}

    matched_path = ROOT / "reports/visual-qa-pilot-2026-11-20/matched/r2/attacked.jsonl"
    cotta_row = next(r for r in map(json.loads, matched_path.read_text().splitlines())
                     if r["attack"]["base_id"] == BASE_ID
                     and r["attack"]["channel"] == "cotta_50"
                     and r["attack"]["condition"] == "attack")
    cotta_path = (matched_path.parent / cotta_row["images"][0]).resolve()
    shutil.copyfile(cotta_path, OUTPUT / "originals/cotta.png")
    audit_path = (matched_path.parent / cotta_row["attack"]["audit"]).resolve()
    audit = json.loads(audit_path.read_text())
    sources["cotta"] = {"input_manifest": str(matched_path.relative_to(ROOT)),
                        "row_id": cotta_row["id"], "image_sha256": digest(cotta_path),
                        "audit": str(audit_path.relative_to(ROOT)),
                        "payload": cotta_row["attack"]["payload"],
                        "config": audit["config"], "linf_8bit": audit["linf_8bit"]}
    legacy_payload = sources["banner"]["payload"]
    for channel in ("visible_paragraph", "source_layer"):
        sources[channel] = {"image_sha256": sources["clean"]["image_sha256"],
                            "payload": legacy_payload,
                            "status": "new documentation HTML; no model evaluation"}

    width, _ = Image.open(OUTPUT / "originals/clean.png").size
    for channel in CHANNELS:
        asset = channel if channel in CHANNELS[:6] else "clean"
        paragraph = (f'<p>{html.escape(legacy_payload)}</p>'
                     if channel == "visible_paragraph" else "")
        comment = f'<!-- {legacy_payload} -->' if channel == "source_layer" else ""
        page_html = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Chart</title>
<style>body {{margin:16px;background:white;font-family:Arial,sans-serif}}
main {{width:{width}px}} img {{display:block;width:auto;height:auto}}
p {{margin:0;padding:16px;font-size:18px;line-height:1.4;background:#fff}}
</style></head><body><main>{paragraph}<img src="originals/{asset}.png" alt="Chart">
{comment}</main></body></html>
'''
        (OUTPUT / f"{channel}.html").write_text(page_html)

    with sync_playwright() as p:
        kwargs = {"executable_path": browser_executable} if browser_executable else {}
        browser = p.chromium.launch(headless=True, **kwargs)
        page = browser.new_page(viewport={"width": 1440, "height": 1200}, device_scale_factor=1)
        observations = {}
        for channel in CHANNELS:
            page.goto((OUTPUT / f"{channel}.html").as_uri())
            page.locator("img").evaluate("img => img.decode()")
            main = page.locator("main")
            visible = main.inner_text()
            dom = main.evaluate("el => el.outerHTML")
            if channel == "visible_paragraph":
                assert legacy_payload in visible
            elif channel == "source_layer":
                assert legacy_payload in dom and legacy_payload not in visible
                (OUTPUT / "source_layer-dom.txt").write_text(dom + "\n")
            else:
                assert not visible.strip()
                if sources[channel]["payload"]:
                    assert sources[channel]["payload"] not in dom
            natural = page.locator("img").evaluate(
                "el => [el.naturalWidth, el.naturalHeight, el.clientWidth, el.clientHeight]")
            assert natural[:2] == natural[2:]
            main.screenshot(path=str(OUTPUT / f"{channel}.png"), animations="disabled")
            observations[channel] = {"natural_and_display_size": natural,
                                     "screenshot_sha256": digest(OUTPUT / f"{channel}.png"),
                                     "visible_text": visible,
                                     "html_sha256": digest(OUTPUT / f"{channel}.html")}
        assert (OUTPUT / "clean.png").read_bytes() == (OUTPUT / "source_layer.png").read_bytes()
        # This is an explanatory view of an actual DOM excerpt, not a trial page.
        dom = (OUTPUT / "source_layer-dom.txt").read_text()
        page.set_content('<style>body{font:16px Arial;margin:20px}pre{white-space:pre-wrap;'
                         'overflow-wrap:anywhere;font:16px/1.5 monospace;background:#f4f6f8;'
                         'padding:20px}main{width:880px}</style><main><h2>source_layer: DOM excerpt</h2>'
                         '<p>Documentation view — this text is not visible on the chart page.</p>'
                         f'<pre>{html.escape(dom)}</pre></main>')
        page.locator("main").screenshot(path=str(OUTPUT / "source_layer-dom.png"))
        browser_version = browser.version
        browser.close()

    examples = payloads("D", "D (stacked bar chart)", "factorial")
    provenance = {"purpose": "documentation examples, not a new evaluation or frozen corpus",
                  "base_id": BASE_ID, "gold": "C", "target": "D",
                  "question": clean["conversation"][0]["content"],
                  "sources": sources, "observations": observations,
                  "browser_version": browser_version, "viewport": [1440, 1200],
                  "device_scale_factor": 1, "capture": "main element at natural image size",
                  "source_layer_screenshot_equals_clean": True,
                  "current_template_examples": examples,
                  "generator_sha256": digest(__file__)}
    (OUTPUT / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")

    # Generate the exact examples from the registry; keep surrounding prose authored.
    plan = ROOT / "docs/chartgalaxy-webpage-run-plan.md"
    content = plan.read_text()
    start, end = "<!-- PAYLOAD_EXAMPLES_START -->", "<!-- PAYLOAD_EXAMPLES_END -->"
    sections = []
    for style, text in examples.items():
        family = FACTORIAL_TEMPLATES[style][0]
        sections.append(f"#### `{style}` — {family}\n\n> {text}\n")
    before, after = content.split(start, 1)
    _, after = after.split(end, 1)
    plan.write_text(before + start + "\n\n" + "\n".join(sections) + "\n" + end + after)
    print(json.dumps({"screenshots": len(CHANNELS) + 1, "template_examples": len(examples),
                      "source_layer_visually_identical_to_clean": True,
                      "browser": browser_version, "output": str(OUTPUT.relative_to(ROOT))}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser-executable", help="Optional installed Chromium executable")
    build(parser.parse_args().browser_executable)
