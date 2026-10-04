import argparse
import base64
from copy import deepcopy
import json
import re
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

from browser_agent import (BrowserTools, DEFENSE_PROMPT_SUFFIX, SYSTEM_PROMPT, TEXT_LIMIT,
                           TOOLS, check_model_capabilities, filter_tools, run_agent, save_trace)
from run_attack_suite import (add_agent_arguments, already_done_keys, attack_trials,
                              grade, validate_arguments, PAGES_DIR)
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
    def run_script(self, messages, max_steps=15, num_ctx=32768, prompt_eval_counts=None):
        page = Mock()
        page.screenshot.return_value = PNG
        page.evaluate.return_value = 310
        page.locator.return_value.evaluate.return_value = '<canvas id="chart"></canvas>'
        requests_seen = []
        counts = list(prompt_eval_counts) if prompt_eval_counts is not None else None
        def post(url, *, json, timeout):
            requests_seen.append(deepcopy(json))
            response = Mock()
            data = {"message": messages.pop(0)}
            if counts is not None:
                data["prompt_eval_count"] = counts.pop(0)
            response.json.return_value = data
            return response
        with patch("browser_agent.requests.post", side_effect=post):
            result = run_agent(page, "How many?", "test-model", max_steps=max_steps, num_ctx=num_ctx)
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

    def test_num_ctx_is_sent_as_an_ollama_option(self):
        _, seen, _ = self.run_script([assistant("310")], num_ctx=8192)
        self.assertEqual(seen[0]["options"]["num_ctx"], 8192)

    def test_tracks_max_prompt_tokens_and_flags_ctx_overflow_risk(self):
        result, _, _ = self.run_script(
            [assistant("", [call("screenshot")]), assistant("310")],
            num_ctx=1000, prompt_eval_counts=[100, 980])
        self.assertEqual(result.max_prompt_tokens, 980)
        self.assertTrue(result.ctx_overflow_risk)

    def test_no_ctx_overflow_risk_below_threshold(self):
        result, _, _ = self.run_script([assistant("310")], num_ctx=1000, prompt_eval_counts=[500])
        self.assertEqual(result.max_prompt_tokens, 500)
        self.assertFalse(result.ctx_overflow_risk)

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

    def test_filter_tools_subset_and_unknown_name(self):
        subset = filter_tools(["screenshot", "dom"])
        self.assertEqual([t["function"]["name"] for t in subset], ["screenshot", "dom"])
        with self.assertRaises(ValueError):
            filter_tools(["screenshot", "not_a_tool"])

    def test_disabled_tool_is_rejected_at_execution(self):
        page = Mock()
        tools = BrowserTools(page, [], enabled_tools={"screenshot"})
        page.screenshot.return_value = PNG
        tools.execute("screenshot", {})
        with self.assertRaises(ValueError):
            tools.execute("dom", {})

    def test_run_agent_sends_only_enabled_tools(self):
        subset = filter_tools(["screenshot", "evaluate"])
        with patch("browser_agent.requests.post") as post:
            post.return_value.json.return_value = {"message": {"role": "assistant", "content": "310"}}
            run_agent(Mock(), "Q", "M", tools=subset)
            sent_tools = post.call_args.kwargs["json"]["tools"]
            self.assertEqual([t["function"]["name"] for t in sent_tools], ["screenshot", "evaluate"])

    def test_check_model_capabilities_present_missing_and_absent(self):
        for capabilities, should_raise in [(["vision", "tools"], False),
                                           (["vision"], True),
                                           (None, False)]:
            with self.subTest(capabilities=capabilities):
                with patch("browser_agent.requests.post") as post:
                    data = {} if capabilities is None else {"capabilities": capabilities}
                    post.return_value.json.return_value = data
                    if should_raise:
                        with self.assertRaises(SystemExit):
                            check_model_capabilities("M")
                    else:
                        check_model_capabilities("M")

    def test_check_model_capabilities_handles_request_errors(self):
        with patch("browser_agent.requests.post", side_effect=requests.Timeout("timed out")):
            check_model_capabilities("M")

    def test_default_system_prompt_has_no_injection_defense(self):
        self.assertNotIn("observations, not instructions", SYSTEM_PROMPT)

    def test_run_agent_appends_defense_prompt_when_given(self):
        with patch("browser_agent.requests.post") as post:
            post.return_value.json.return_value = {"message": {"role": "assistant", "content": "310"}}
            run_agent(Mock(), "Q", "M")
            default_system = post.call_args.kwargs["json"]["messages"][0]["content"]
            self.assertEqual(default_system, SYSTEM_PROMPT)

            run_agent(Mock(), "Q", "M", system_prompt=SYSTEM_PROMPT + DEFENSE_PROMPT_SUFFIX)
            defended_system = post.call_args.kwargs["json"]["messages"][0]["content"]
            self.assertTrue(defended_system.endswith(DEFENSE_PROMPT_SUFFIX))

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

    def test_validate_arguments_accepts_known_tools_and_rejects_unknown(self):
        parser = argparse.ArgumentParser()
        add_agent_arguments(parser)
        parser.add_argument("--limit", type=int)
        args = parser.parse_args(["--models", "m", "--tools", "screenshot,dom"])
        validate_arguments(parser, args)
        self.assertEqual(args.tools, ["screenshot", "dom"])

        parser2 = argparse.ArgumentParser()
        add_agent_arguments(parser2)
        parser2.add_argument("--limit", type=int)
        args2 = parser2.parse_args(["--models", "m", "--tools", "screenshot,not_a_tool"])
        with self.assertRaises(SystemExit):
            validate_arguments(parser2, args2)

    def test_task_ids_filters_capability_tasks(self):
        from run_capability_suite import discover_tasks
        tasks = discover_tasks(["d3"])
        task_ids = {t["task_id"] for t in tasks}
        self.assertIn("retrieve_value", task_ids)
        filtered = [t for t in tasks if t["task_id"] == "retrieve_value"]
        self.assertTrue(filtered)
        self.assertTrue(all(t["task_id"] == "retrieve_value" for t in filtered))

    def test_resume_is_condition_specific_and_retries_infrastructure_errors(self):
        base = {"library": "d3", "question": "Q", "model": "M", "condition": "react_browser"}
        rows = [dict(base, attack_id="done", notes="stop=final"),
                dict(base, attack_id="limited", notes="stop=max_steps"),
                dict(base, attack_id="request", notes="stop=request_error"),
                dict(base, attack_id="browser", notes="stop=browser_error"),
                dict(base, attack_id="historical", condition="raw_source", notes="")]
        with patch("run_attack_suite.read_rows", return_value=rows):
            self.assertEqual({k[1] for k in already_done_keys()}, {"done", "limited"})

    def test_resume_key_is_trial_specific(self):
        base = {"library": "d3", "attack_id": "attack", "question": "Q", "model": "M",
               "condition": "react_browser", "notes": "stop=final"}
        rows = [dict(base, trial="0"), dict(base, trial="1")]
        with patch("run_attack_suite.read_rows", return_value=rows):
            self.assertEqual(already_done_keys(),
                             {("d3", "attack", "Q", "M", "0"), ("d3", "attack", "Q", "M", "1")})

    def test_asr_wilson_interval_pools_across_trials(self):
        rows = []
        for trial, correct in [("0", "false"), ("1", "false"), ("2", "true")]:
            rows.append({"condition": "react_browser", "library": "d3", "model": "M",
                        "attack_id": "attack", "correct": correct, "trial": trial})
            rows.append({"condition": "react_browser", "library": "d3", "model": "M",
                        "attack_id": "attack__clean_baseline", "correct": "true", "trial": trial})
        entries = build_asr_table(rows)
        entry = entries[0]
        self.assertEqual(entry["n_attack"], 3)
        self.assertAlmostEqual(entry["attack_wrong_rate"], 2 / 3)
        lo, hi = entry["attack_ci"]
        self.assertLess(lo, entry["attack_wrong_rate"])
        self.assertGreater(hi, entry["attack_wrong_rate"])

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


FORBIDDEN_STRINGS = ("attack", "bait", "decoy", "mislead", "ground truth",
                     "ground_truth", "identical to clean")


class PageLeakTests(unittest.TestCase):
    def test_no_comments_or_forbidden_strings_in_served_pages(self):
        for html_path in sorted(Path(PAGES_DIR).glob("*/*.html")):
            text = html_path.read_text(encoding="utf-8")
            with self.subTest(file=str(html_path)):
                self.assertNotRegex(text, r'<!--', "HTML comment found")
                self.assertNotRegex(text, r'/\*', "block comment found")
                for line in text.split("\n"):
                    self.assertNotRegex(line, r'^\s*//', "line comment found")
                lower = text.lower()
                for forbidden in FORBIDDEN_STRINGS:
                    self.assertNotIn(forbidden, lower, f"forbidden string {forbidden!r} found")

    def test_attack_and_clean_titles_match_per_library_and_chart_type(self):
        titles_by_library_and_type = {}
        for html_path in sorted(Path(PAGES_DIR).glob("*/*.html")):
            library = html_path.parent.name
            meta_path = html_path.with_suffix("").with_suffix(".meta.json")
            if not meta_path.is_file():
                continue
            meta = json.loads(meta_path.read_text())
            chart_type = meta.get("chart_type") or html_path.stem[len("clean_"):]
            title = re.search(r'<title>(.*?)</title>', html_path.read_text()).group(1)
            key = (library, chart_type)
            titles_by_library_and_type.setdefault(key, set()).add(title)
        for key, titles in titles_by_library_and_type.items():
            with self.subTest(library_chart_type=key):
                self.assertEqual(len(titles), 1, f"titles differ within {key}: {titles}")


if __name__ == "__main__":
    unittest.main()
