"""Opt-in real Chromium tests; use RUN_BROWSER_TESTS=1."""
from argparse import Namespace
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from browser_agent import BrowserTools, VIEWPORT, capture_console
from browser_environment import serve_chart
import results_logger
from run_attack_suite import run_trials, attack_trials

FIXTURE = '''<!doctype html><html><body style="height:2000px">
<h1>Test chart</h1><label>Label <input id="entry"></label>
<button id="mark" onclick="this.textContent='clicked'"
 onmouseenter="document.querySelector('#tip').textContent='West: 310'">Mark</button>
<div id="tip"></div><script>console.log('loaded'); window.chartData = [180,310];
setTimeout(() => { throw new Error('fixture error'); }, 0);</script></body></html>'''


@unittest.skipUnless(os.environ.get("RUN_BROWSER_TESTS") == "1", "Set RUN_BROWSER_TESTS=1")
class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.html = Path(self.temp.name) / "chart.html"
        self.html.write_text(FIXTURE)
        (Path(self.temp.name) / "chart.meta.json").write_text('{"secret": "grading-only"}')
        self.context = self.browser.new_context(viewport=VIEWPORT)
        self.page = self.context.new_page()
        self.page.set_default_timeout(1000)
        self.logs = capture_console(self.page)
        self.tools = BrowserTools(self.page, self.logs)

    def tearDown(self):
        self.context.close()
        self.temp.cleanup()

    def test_observations_and_sidecar_isolation(self):
        with serve_chart(self.html) as url:
            self.page.goto(url)
            self.page.wait_for_timeout(50)
            dom, _ = self.tools.execute("dom", {})
            self.assertIn("chartData", dom)
            self.assertNotIn("grading-only", dom)
            aria, _ = self.tools.execute("accessibility", {})
            self.assertIn("Test chart", aria)
            self.assertIn("textbox", aria)
            logs, _ = self.tools.execute("console", {})
            self.assertIn("loaded", logs)
            self.assertIn("fixture error", logs)
            data, _ = self.tools.execute("evaluate", {"script": "window.chartData"})
            self.assertEqual(json.loads(data), [180, 310])
            _, images = self.tools.execute("screenshot", {})
            self.assertTrue(images[0].startswith("iVBOR"))
            for path in ["/", "/chart.meta.json", "/chart.capability_tasks.json", "/../chart.meta.json"]:
                code = self.page.evaluate("async path => (await fetch(path)).status", path)
                self.assertEqual(code, 404)
            with self.assertRaises(Exception):
                self.tools.execute("evaluate", {"script": "() => {throw Error('bad JS')}"})
            self.assertEqual(self.tools.execute("evaluate", {"script": "1+1"})[0], "2")

    def test_interactions_and_context_isolation(self):
        with serve_chart(self.html) as url:
            self.page.goto(url)
            self.tools.execute("hover", {"selector": "#mark"})
            self.assertEqual(self.page.locator("#tip").inner_text(), "West: 310")
            bounds = self.page.locator("#mark").bounding_box()
            self.tools.execute("click", {"x": bounds["x"] + 5, "y": bounds["y"] + 5})
            self.assertEqual(self.page.locator("#mark").inner_text(), "clicked")
            self.tools.execute("click", {"selector": "#entry"})
            self.tools.execute("type", {"text": "hello"})
            self.tools.execute("press", {"key": "End"})
            self.tools.execute("type", {"text": "!"})
            self.assertEqual(self.page.locator("#entry").input_value(), "hello!")
            self.tools.execute("scroll", {"dx": 0, "dy": 500})
            self.tools.execute("wait", {"ms": 100})
            self.assertGreater(self.page.evaluate("scrollY"), 0)
            self.page.evaluate("localStorage.setItem('test', 'previous trial')")
            with self.browser.new_context() as fresh:
                page = fresh.new_page()
                logs = capture_console(page)
                self.assertEqual(logs, [])
                page.goto(url)
                self.assertIsNone(page.evaluate("localStorage.getItem('test')"))
                self.assertEqual(page.locator("#mark").inner_text(), "Mark")

    @unittest.skipUnless(os.environ.get("RUN_CORPUS_TESTS") == "1", "Set RUN_CORPUS_TESTS=1 (uses CDNs)")
    def test_four_libraries_render_clean_and_attack_pages(self):
        for trial in attack_trials(["d3", "plotly", "chartjs", "vega-lite"], limit=1):
            with self.subTest(library=trial["library"], attack=trial["attack_id"]):
                with serve_chart(trial["html_path"]) as url:
                    self.page.goto(url, wait_until="networkidle", timeout=30000)
                    self.page.wait_for_timeout(700)
                    if trial["library"] == "chartjs":
                        self.assertEqual(self.page.evaluate("Chart.getChart('chart').data.labels.length"), 5)
                    elif trial["library"] == "plotly":
                        self.assertEqual(self.page.evaluate("document.querySelector('.js-plotly-plot').data[0].y.length"), 5)
                    elif trial["library"] == "d3":
                        self.assertEqual(self.page.locator("svg path[d$='Z']").count(), 5)
                    else:
                        self.assertGreater(self.page.locator(".vega-embed canvas, .vega-embed svg").count(), 0)
                    text, images = self.tools.execute("screenshot", {})
                    self.assertTrue(images)
                    self.assertTrue(self.tools.execute("dom", {})[0])
                    self.assertTrue(self.tools.execute("accessibility", {})[0])


@unittest.skipUnless(os.environ.get("RUN_BROWSER_TESTS") == "1", "Set RUN_BROWSER_TESTS=1")
class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.html = Path(self.temp.name) / "chart.html"
        self.html.write_text(FIXTURE)

    def tearDown(self):
        self.temp.cleanup()

    def test_runners_log_resume_and_preserve_grading_boundary(self):
        # Run the real runner/browser/CSV path with only model inference scripted.
        attack = {"library": "d3", "attack_id": "attack", "html_path": str(self.html),
                  "question": "Read the tooltip", "ground_truth": "310", "answer_type": "free"}
        baseline = dict(attack, attack_id="attack__clean_baseline")
        capability = dict(attack, attack_id="clean_bar")
        args = Namespace(models=["test-model"], dry_run=False, headed=False,
                         trace_dir=str(Path(self.temp.name) / "traces"),
                         base_url="http://localhost:11434", timeout=10, max_steps=3)
        calls = []
        def post(url, *, json, timeout):
            calls.append(json)
            self.assertNotIn("ground_truth", str(json))
            self.assertNotIn("grading-only", str(json))
            if len(json["messages"]) == 2:
                content = {"role": "assistant", "tool_calls": [{"function": {
                    "name": "screenshot", "arguments": {}}}]}
            else:
                self.assertEqual(json["messages"][-1]["role"], "tool")
                self.assertTrue(json["messages"][-1]["images"])
                content = {"role": "assistant", "content": "310"}
            response = Mock()
            response.json.return_value = {"message": content}
            return response
        csv_path = str(Path(self.temp.name) / "results.csv")
        with patch.object(results_logger, "RESULTS_DIR", self.temp.name), \
             patch.object(results_logger, "RESULTS_CSV", csv_path), \
             patch("browser_agent.requests.post", side_effect=post), redirect_stdout(io.StringIO()):
            run_trials([attack, baseline, capability], args)
            run_trials([attack, baseline, capability], args)
            rows = results_logger.read_rows()
            self.assertEqual(len(rows), 3)
            self.assertEqual(len(calls), 6)
            self.assertTrue(all(r["correct"] == "true" and r["condition"] == "react_browser" for r in rows))
            traces = list(Path(args.trace_dir).glob("*/trace.json"))
            self.assertEqual(len(traces), 3)
            self.assertTrue(all(list(p.parent.glob("*.png")) for p in traces))



if __name__ == "__main__":
    unittest.main()
