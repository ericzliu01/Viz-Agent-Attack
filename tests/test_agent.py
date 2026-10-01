import base64
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

from browser_agent import BrowserTools, TEXT_LIMIT, run_agent, save_trace
from run_attack_suite import already_done_keys, attack_trials, grade
from run_capability_suite import discover_tasks, grade_task
from summarize_results import build_asr_table

PNG = b'\x89PNG\r\n\x1a\nexample'


def call(name, arguments=None, call_id=None):
    value = {"function": {"name": name, "arguments": arguments or {}}}
    if call_id:
        value["id"] = call_id
    return value


def assistant(content="", calls=None):
    return {"role": "assistant", "content": content, "tool_calls": calls or []}


class AgentTests(unittest.TestCase):
    def run_script(self, messages, max_steps=15):
        page = Mock()
        page.screenshot.return_value = PNG
        page.evaluate.return_value = 310
        page.locator.return_value.evaluate.return_value = '<canvas id="chart"></canvas>'
        requests_seen = []
        def post(url, *, json, timeout):
            requests_seen.append(deepcopy(json))
            response = Mock()
            response.json.return_value = {"message": messages.pop(0)}
            return response
        with patch("browser_agent.requests.post", side_effect=post):
            result = run_agent(page, "How many?", "test-model", max_steps=max_steps)
        return result, requests_seen, page

    def test_multimodal_tool_result_and_final_only(self):
        result, seen, _ = self.run_script([
            assistant("intermediate 999", [call("screenshot", call_id="shot-1")]),
            assistant(calls=[call("evaluate", {"script": "chart.data"})]),
            assistant("310"),
        ])
        self.assertEqual((result.answer, result.stop_reason, result.steps), ("310", "final", 3))
        self.assertEqual(len(seen[0]["messages"]), 2)
        image_message = seen[1]["messages"][-1]
        self.assertEqual(image_message["role"], "tool")
        self.assertEqual(image_message["tool_name"], "screenshot")
        self.assertEqual(image_message["tool_call_id"], "shot-1")
        self.assertEqual(base64.b64decode(image_message["images"][0]), PNG)
        self.assertEqual(sum(m["role"] == "user" for m in result.messages), 1)
        self.assertTrue(seen[0]["tools"])
        self.assertEqual(grade(result.answer, "310")[0], "true")

    def test_multiple_tools_execute_in_order_and_errors_are_observations(self):
        result, seen, page = self.run_script([
            assistant(calls=[call("unknown"), call("evaluate", {"script": "310"}), call("dom")]),
            assistant("310"),
        ])
        outputs = [m for m in seen[1]["messages"] if m["role"] == "tool"]
        self.assertEqual([m["tool_name"] for m in outputs], ["unknown", "evaluate", "dom"])
        self.assertIn("error", outputs[0]["content"])
        self.assertEqual(outputs[1]["content"], "310")
        self.assertEqual(result.stop_reason, "final")
        page.evaluate.assert_called_once_with("310")

    def test_limits_and_empty_response_never_grade_intermediate_content(self):
        result, _, _ = self.run_script([assistant("310", [call("screenshot")])], max_steps=1)
        self.assertEqual((result.answer, result.stop_reason), ("", "max_steps"))
        result, _, _ = self.run_script([assistant()])
        self.assertEqual((result.answer, result.stop_reason), ("", "empty_response"))

    def test_request_error_and_malformed_response(self):
        with patch("browser_agent.requests.post", side_effect=requests.Timeout("timed out")):
            result = run_agent(Mock(), "Q", "M")
        self.assertEqual((result.answer, result.stop_reason), ("", "request_error"))
        self.assertIn("timed out", result.error)
        for data in ([], {}, {"message": None}, {"error": "model does not support tools"}):
            with self.subTest(data=data), patch("browser_agent.requests.post") as post:
                post.return_value.json.return_value = data
                self.assertEqual(run_agent(Mock(), "Q", "M").stop_reason, "request_error")

    def test_validation_and_truncation(self):
        page = Mock()
        tools = BrowserTools(page, [])
        for name, args in [("click", {}), ("click", {"selector": "button", "x": 1}),
                           ("hover", {"x": 1}), ("wait", {"ms": -1}),
                           ("wait", {"ms": 10001}), ("scroll", {"dx": True, "dy": 0}),
                           ("dom", {"selector": 42}), ("dom", {"extra": "bad"}),
                           ("evaluate", {})]:
            with self.subTest(name=name, args=args), self.assertRaises(ValueError):
                tools.execute(name, args)
        page.evaluate.return_value = "a" * (TEXT_LIMIT + 1)
        self.assertIn("[truncated", tools.execute("evaluate", {"script": "longText"})[0])

    def test_trace_stores_png_without_mutating_model_history(self):
        result, _, _ = self.run_script([assistant(calls=[call("screenshot")]), assistant("310")])
        original = deepcopy(result.messages)
        with tempfile.TemporaryDirectory() as temp:
            path = save_trace(result, temp, {"model": "test"})
            saved = json.loads(path.read_text())
            message = next(m for m in saved["messages"] if m.get("image_files"))
            self.assertEqual((Path(temp) / message["image_files"][0]).read_bytes(), PNG)
            self.assertNotIn("images", message)
            self.assertEqual(saved["config"]["model"], "test")
        self.assertEqual(result.messages, original)


class ExperimentTests(unittest.TestCase):
    def test_pairing_and_task_grading(self):
        trials = attack_trials(["d3", "plotly", "chartjs", "vega-lite"], limit=1)
        self.assertEqual(len(trials), 8)
        for attack, baseline in zip(trials[::2], trials[1::2]):
            self.assertEqual(baseline["attack_id"], attack["attack_id"] + "__clean_baseline")
            self.assertEqual(baseline["question"], attack["question"])
            self.assertEqual(baseline["ground_truth"], attack["ground_truth"])
            self.assertTrue(Path(baseline["html_path"]).name.startswith("clean_"))
        tasks = discover_tasks(["d3"])
        choice = next(t for t in tasks if t["answer_type"] == "choice")
        self.assertEqual(grade_task(choice, choice["ground_truth"])[0], "true")
        self.assertEqual(grade_task(choice, "This is a chart")[0], "needs_review")
        self.assertEqual(grade("cannot determine", "310")[0], "needs_review")

    def test_resume_is_condition_specific_and_retries_infrastructure_errors(self):
        base = {"library": "d3", "question": "Q", "model": "M", "condition": "react_browser"}
        rows = [dict(base, attack_id="done", notes="stop=final"),
                dict(base, attack_id="limited", notes="stop=max_steps"),
                dict(base, attack_id="request", notes="stop=request_error"),
                dict(base, attack_id="browser", notes="stop=browser_error"),
                dict(base, attack_id="historical", condition="raw_source", notes="")]
        with patch("run_attack_suite.read_rows", return_value=rows):
            self.assertEqual({k[1] for k in already_done_keys()}, {"done", "limited"})

    def test_asr_keeps_historical_conditions_separate(self):
        rows = []
        for condition, correct in [("react_browser", "false"), ("raw_source", "true")]:
            for attack_id in ["attack", "attack__clean_baseline"]:
                rows.append({"condition": condition, "library": "d3", "model": "M",
                             "attack_id": attack_id,
                             "correct": "true" if attack_id.endswith("baseline") else correct})
        entries = build_asr_table(rows)
        self.assertEqual({e["condition"]: e["asr"] for e in entries},
                         {"react_browser": 1.0, "raw_source": 0.0})


if __name__ == "__main__":
    unittest.main()
