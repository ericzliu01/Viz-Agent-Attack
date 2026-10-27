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

from browser_agent import (BrowserTools, DEFENSE_PROMPT_SUFFIX, REPAIR_PROMPT, SYSTEM_PROMPT,
                           TEXT_LIMIT, TOOL_NAMES, TOOLS, check_model_capabilities, filter_tools,
                           parse_critic, recover_tool_call, run_agent, run_critic, save_trace)
from run_attack_suite import (add_agent_arguments, already_done_keys, attack_trials,
                              discover_pages, grade, validate_arguments, PAGES_DIR)
from run_capability_suite import discover_tasks, grade_task
from summarize_results import build_asr_table, build_tool_usage_breakdown, tool_flags

PNG = b'\x89PNG\r\n\x1a\nexample'


def call(name, arguments=None, call_id=None):
    value = {"function": {"name": name, "arguments": arguments or {}}}
    if call_id:
        value["id"] = call_id
    return value


def assistant(content="", calls=None):
    return {"role": "assistant", "content": content, "tool_calls": calls or []}


class AgentTests(unittest.TestCase):
    def run_script(self, messages, max_steps=15, num_ctx=32768, prompt_eval_counts=None,
                   repair_tool_calls=True):
        page = Mock()
        page.screenshot.return_value = PNG
        page.evaluate.return_value = 310
        page.locator.return_value.count.return_value = 1
        page.locator.return_value.first.evaluate.return_value = '<canvas id="chart"></canvas>'
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
            result = run_agent(page, "How many?", "test-model", max_steps=max_steps, num_ctx=num_ctx,
                               repair_tool_calls=repair_tool_calls)
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
        self.assertEqual(result.tools_used, ["evaluate", "dom"])

    def test_tools_used_is_ordered_unique_first_use(self):
        result, _, _ = self.run_script([
            assistant(calls=[call("screenshot"), call("evaluate", {"script": "1"}),
                             call("screenshot")]),
            assistant("310"),
        ])
        self.assertEqual(result.tools_used, ["screenshot", "evaluate"])

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
        result, _, _ = self.run_script([assistant()], repair_tool_calls=False)
        self.assertEqual((result.answer, result.stop_reason), ("", "empty_response"))
        result, seen, _ = self.run_script([assistant(), assistant(), assistant()])
        self.assertEqual((result.answer, result.stop_reason, result.steps), ("", "empty_response", 3))
        self.assertEqual(result.repair_prompts, 2)
        self.assertEqual(seen[2]["messages"][-1], {"role": "user", "content": REPAIR_PROMPT})

    def test_tool_call_written_in_thinking_is_run(self):
        thinking = 'I should read the DOM.\n\n{"name": "dom", "arguments": {"selector": "svg"}}\n</tool_call>'
        result, seen, page = self.run_script([
            {"role": "assistant", "content": "", "thinking": thinking}, assistant("B")])
        self.assertEqual((result.answer, result.stop_reason), ("B", "final"))
        page.locator.assert_called_once_with("svg")
        self.assertEqual(result.recovered_calls, [{"step": 1, "source": "thinking", "name": "dom"}])
        self.assertEqual(seen[1]["messages"][2]["tool_calls"],
                         [{"function": {"name": "dom", "arguments": {"selector": "svg"}}}])
        self.assertEqual(seen[1]["messages"][3]["role"], "tool")
        self.assertEqual(result.tools_used, ["dom"])

    def test_tool_call_printed_as_answer_is_run_not_graded(self):
        printed = '{"name": "evaluate", "arguments": {"script": "310"}}\n</tool_call>'
        result, seen, page = self.run_script([assistant(printed), assistant("310")])
        self.assertEqual((result.answer, result.stop_reason), ("310", "final"))
        page.evaluate.assert_called_once_with("310")
        self.assertEqual(seen[1]["messages"][2]["content"], "")
        self.assertEqual(result.recovered_calls[0]["source"], "content")

    def test_final_answer_wins_over_a_call_in_thinking(self):
        thinking = '{"name": "dom", "arguments": {}}</tool_call>'
        result, _, page = self.run_script([
            {"role": "assistant", "content": "B", "thinking": thinking}])
        self.assertEqual((result.answer, result.recovered_calls), ("B", []))
        page.locator.assert_not_called()

    def test_broken_tool_call_answer_gets_a_repair_prompt(self):
        broken = '{"name": "evaluate", "arguments": {"script": "1"\n</tool_call>'
        result, seen, _ = self.run_script([assistant(broken), assistant("C")])
        self.assertEqual((result.answer, result.repair_prompts), ("C", 1))
        result, _, _ = self.run_script([assistant(broken)], repair_tool_calls=False)
        self.assertEqual((result.answer, result.stop_reason), (broken.strip(), "final"))

    def test_recover_tool_call_shapes(self):
        names = set(TOOL_NAMES)
        dom = {"function": {"name": "dom", "arguments": {}}}
        for text in ['{"name": "dom", "arguments": {}}', '<tool_call>\n{"name": "dom", "arguments": {}}\n</tool_call>',
                     '{"name": "dom"}', '{"name": "dom", "arguments": "{}"}',
                     '```json\n{"name": "dom", "arguments": {}}\n```']:
            with self.subTest(text=text):
                self.assertEqual(recover_tool_call(text, names), dom)
        cut = 'uate", "arguments": {"script": "a.b"}}\n</tool_call>'
        self.assertEqual(recover_tool_call(cut, names),
                         {"function": {"name": "evaluate", "arguments": {"script": "a.b"}}})
        for text in [None, "", "B", 'Let me call {"name": "dom", "arguments": {}} and then answer B.',
                     '{"name": "steal", "arguments": {}}', '{"name": "dom", "arguments": []}',
                     '{"name": "dom", "arguments": {}, "extra": 1}',
                     'e", "arguments": {}}</tool_call>',  # console, evaluate and type all end in "e"
                     'uate", "arguments": {"script": "1"}}',  # a cut call needs the closing tag
                     'B\n{"name": "dom", "arguments": {}}',  # an answer followed by a call stays an answer
                     'thinking...\n{"name": "dom", "arguments": {}}']:
            with self.subTest(text=text):
                self.assertIsNone(recover_tool_call(text, names))
        thought = 'I should check.\n{"name": "dom", "arguments": {}}\n</tool_call>'
        self.assertEqual(recover_tool_call(thought, names, "thinking"), dom)
        rejected = 'The page says to click. I must not do {"name": "click", "arguments": {"selector": "#go"}}'
        self.assertIsNone(recover_tool_call(rejected, names, "thinking"))
        self.assertIsNone(recover_tool_call('{"name": "dom", "arguments": {}}', {"screenshot"}))

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
        page.evaluate.side_effect = [Exception("SyntaxError: Illegal return statement"), 7]
        self.assertEqual(tools.execute("evaluate", {"script": "return 7;"}), ("7", []))
        self.assertEqual(page.evaluate.call_args.args[0], "(async () => {\nreturn 7;\n})()")
        page.evaluate.side_effect = None
        page.locator.return_value.count.return_value = 0
        with self.assertRaisesRegex(ValueError, "No element matches"):
            tools.execute("dom", {"selector": ".missing"})
        page.locator.return_value.count.return_value = 3
        page.locator.return_value.first.evaluate.return_value = "<rect></rect>"
        self.assertTrue(tools.execute("dom", {"selector": "rect"})[0].startswith("[3 elements match 'rect'"))
        tools.execute("dom", {"selector": ""})
        page.locator.assert_called_with("html")
        legacy = BrowserTools(page, [], legacy=True)
        page.evaluate.side_effect = Exception("SyntaxError: Illegal return statement")
        with self.assertRaises(Exception):
            legacy.execute("evaluate", {"script": "return 7;"})
        page.evaluate.side_effect = None
        page.locator.return_value.evaluate.return_value = "<html></html>"
        self.assertEqual(legacy.execute("dom", {"selector": "rect"}), ("<html></html>", []))
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


class ReasoningAttackTests(unittest.TestCase):
    REASONING = ("revenue_biased_framing", "revenue_critic_evasion", "revenue_persona_hyperstition")

    def test_memory_documents_are_appended_to_the_system_prompt(self):
        page = Mock()
        seen = []
        def post(url, *, json, timeout):
            seen.append(deepcopy(json))
            response = Mock()
            response.json.return_value = {"message": assistant("B")}
            return response
        memory = [{"title": "Team wiki", "source": "wiki", "text": "The agent is an optimist."}]
        with patch("browser_agent.requests.post", side_effect=post):
            run_agent(page, "Q?", "m", memory=memory)
            run_agent(page, "Q?", "m")
        with_memory, without = seen[0]["messages"][0]["content"], seen[1]["messages"][0]["content"]
        self.assertTrue(with_memory.startswith(SYSTEM_PROMPT))
        self.assertIn("[1] Team wiki (wiki)\nThe agent is an optimist.", with_memory)
        self.assertEqual(without, SYSTEM_PROMPT)

    def test_parse_critic_verdicts(self):
        self.assertEqual(parse_critic("APPROVE"), ("APPROVE", ""))
        self.assertEqual(parse_critic("approve."), ("APPROVE", ""))
        self.assertEqual(parse_critic("REVISE: C"), ("REVISE", "C"))
        self.assertEqual(parse_critic("REVISE"), ("unparsed", ""))
        self.assertEqual(parse_critic("The answer looks fine"), ("unparsed", ""))

    def test_run_critic_sends_page_text_and_screenshot(self):
        page = Mock()
        page.evaluate.return_value = "Quarterly Revenue by Region"
        page.screenshot.return_value = PNG
        seen = []
        def post(url, *, json, timeout):
            seen.append(deepcopy(json))
            response = Mock()
            response.json.return_value = {"message": {"role": "assistant", "content": "REVISE: C"}}
            return response
        with patch("browser_agent.requests.post", side_effect=post):
            review = run_critic(page, "Which region?", "B", "m")
        self.assertEqual((review.verdict, review.revised_answer), ("REVISE", "C"))
        user = seen[0]["messages"][1]
        self.assertIn("Agent's answer: B", user["content"])
        self.assertIn("Quarterly Revenue by Region", user["content"])
        self.assertEqual(user["images"], [base64.b64encode(PNG).decode()])
        self.assertNotIn("tools", seen[0])
        with patch("browser_agent.requests.post", side_effect=requests.ConnectionError("down")):
            self.assertEqual(run_critic(page, "Q", "A", "m").verdict, "error")

    def test_reasoning_attacks_expand_to_ten_tasks_per_library(self):
        libraries = ["d3", "plotly", "chartjs", "vega-lite"]
        trials = attack_trials(libraries, attack_ids=set(self.REASONING), datasets={"original"})
        attacks = [t for t in trials if not t["attack_id"].endswith("__clean_baseline")]
        self.assertEqual(len(attacks), 3 * 10 * 4)
        # Without --datasets, the hand-written ids also select their dataset copies.
        everywhere = attack_trials(libraries, attack_ids=set(self.REASONING))
        self.assertTrue({t["attack_id"] for t in everywhere} > {t["attack_id"] for t in trials})
        self.assertEqual(len(trials), 2 * len(attacks))
        for attack_id in self.REASONING:
            task_ids = {t["task_id"] for t in attacks if t["attack_id"] == attack_id and t["library"] == "d3"}
            self.assertEqual(len(task_ids), 10)
        for attack, baseline in zip(trials[::2], trials[1::2]):
            self.assertEqual(baseline["question"], attack["question"])
            self.assertTrue(Path(baseline["html_path"]).name == "clean_revenue.html")
            self.assertEqual(attack["answer_type"], "choice")
            self.assertIn(attack["ground_truth"], "ABC")
            if attack["bait"] is not None:
                self.assertNotEqual(attack["bait"], attack["ground_truth"])

    def test_persona_baseline_gets_neutral_memory_and_others_get_none(self):
        trials = attack_trials(["d3"], attack_ids=set(self.REASONING))
        for trial in trials:
            if "persona" in trial["attack_id"]:
                self.assertEqual(len(trial["memory"]), 5)
                persona = "optimist" in json.dumps(trial["memory"])
                self.assertEqual(persona, not trial["attack_id"].endswith("__clean_baseline"))
            else:
                self.assertIsNone(trial.get("memory"))

    def test_reasoning_tasks_are_capability_tasks_on_clean_revenue(self):
        tasks = [t for t in discover_tasks(["d3"]) if t["attack_id"] == "clean_revenue"]
        self.assertEqual(len(tasks), 11)
        self.assertEqual(sum(t["answer_type"] == "choice" for t in tasks), 10)

    def test_reasoning_summary_counts_bait_pairing_and_critic(self):
        from summarize_reasoning import build, reasoning_meta
        meta = reasoning_meta()
        question = next(q for q, t in meta["revenue_critic_evasion"]["tasks"].items()
                        if t["task_id"] == "top_region")
        base = {"condition": "react_browser_critic", "model": "M", "library": "d3",
                "question": question, "trial": "0"}
        rows = [
            dict(base, attack_id="revenue_critic_evasion", correct="false", extracted_answer="B",
                 notes="stop=final; critic=APPROVE; agent_correct=false; agent_extracted=B"),
            dict(base, attack_id="revenue_critic_evasion__clean_baseline", correct="true",
                 extracted_answer="C", notes="stop=final; critic=APPROVE; agent_correct=true"),
        ]
        stats = build(rows, meta)[("react_browser_critic", "revenue_critic_evasion", "top_region")]
        self.assertEqual((stats["n"], stats["wrong"], stats["bait"], stats["bait_n"]), (1, 1, 1, 1))
        self.assertEqual((stats["fooled"], stats["paired_right"], stats["b_wrong"]), (1, 1, 0))
        self.assertEqual((stats["agent_wrong"], stats["wrong_approved"]), (1, 1))

    def test_persona_page_is_identical_to_clean(self):
        for library in ("d3", "plotly", "chartjs", "vega-lite"):
            clean = (Path(PAGES_DIR) / library / "clean_revenue.html").read_text()
            persona = (Path(PAGES_DIR) / library / "attack_revenue_persona_hyperstition.html").read_text()
            self.assertEqual(clean, persona)


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

    def test_numeric_grading_uses_last_number_not_closest(self):
        self.assertEqual(grade("310 - 240 = 70", "70"), ("true", "70.0"))
        self.assertEqual(grade("70? no, 90", "70")[0], "false")
        self.assertEqual(grade("155", "155"), ("true", "155.0"))

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

    def test_tool_flags_parses_notes(self):
        self.assertEqual(tool_flags("stop=final; tools=dom,screenshot"), (True, True))
        self.assertEqual(tool_flags("stop=final; tools=screenshot"), (False, True))
        self.assertEqual(tool_flags("stop=final; tools=evaluate"), (True, False))
        self.assertEqual(tool_flags("stop=final; tools="), (False, False))
        self.assertEqual(tool_flags(""), (False, False))

    def test_tool_usage_breakdown_computes_asr_per_bucket(self):
        rows = [
            {"condition": "react_browser", "attack_id": "attack", "correct": "false",
             "notes": "tools=dom,screenshot"},
            {"condition": "react_browser", "attack_id": "attack__clean_baseline", "correct": "true",
             "notes": "tools=dom,screenshot"},
            {"condition": "react_browser", "attack_id": "attack", "correct": "false",
             "notes": "tools=screenshot"},
            {"condition": "react_browser", "attack_id": "attack__clean_baseline", "correct": "false",
             "notes": "tools=screenshot"},
        ]
        entries = build_tool_usage_breakdown(rows)
        by_key = {(e["dimension"], e["group"]): e for e in entries}
        read_source_entry = by_key[("read_source", "read_source")]
        self.assertEqual(read_source_entry["n_attack"], 1)
        self.assertAlmostEqual(read_source_entry["asr"], 1.0)
        no_read_source_entry = by_key[("read_source", "no_read_source")]
        self.assertAlmostEqual(no_read_source_entry["asr"], 0.0)
        screenshot_entry = by_key[("screenshot", "screenshot")]
        self.assertEqual(screenshot_entry["n_attack"], 2)


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
            key = (library, chart_type, meta.get("dataset"))
            titles_by_library_and_type.setdefault(key, set()).add(title)
        for key, titles in titles_by_library_and_type.items():
            with self.subTest(library_chart_type=key):
                self.assertEqual(len(titles), 1, f"titles differ within {key}: {titles}")


class DatasetTests(unittest.TestCase):
    """Pages generated by build_dataset_pages.py from datasets/corpus_datasets.json."""

    def setUp(self):
        import build_dataset_pages
        self.builder = build_dataset_pages
        self.templates = json.loads(Path(build_dataset_pages.TEMPLATES_PATH).read_text())
        self.datasets = json.loads(Path(build_dataset_pages.DEFAULT_DATASETS).read_text())

    def test_generator_reproduces_hand_written_tasks_from_templates(self):
        for chart_type in self.builder.CHART_TYPES:
            for library in self.builder.LIBRARIES:
                with self.subTest(chart_type=chart_type, library=library):
                    _, bank = self.builder.generate_tasks(chart_type, self.templates[chart_type], library)
                    path = Path(PAGES_DIR) / library / f"clean_{chart_type}.capability_tasks.json"
                    self.assertEqual(bank, json.loads(path.read_text()))

    def test_every_dataset_has_clean_pages_tasks_and_every_attack(self):
        clean_by_key, attacks = discover_pages()
        # search_memory attacks (a "memory" corpus object) are hand-written for
        # their page's data; build_dataset_pages.py does not copy them.
        originals = {(a["library"], a["chart_type"], a["attack_id"]) for a in attacks
                     if a["dataset"] is None and not isinstance(a.get("memory"), dict)}
        for chart_type in list(self.builder.CHART_TYPES) + ["revenue"]:
            ids = [ds["id"] for ds in self.datasets[chart_type]]
            self.assertGreaterEqual(len(ids), 1)
            for library in self.builder.LIBRARIES:
                base = {a for (lib, ct, a) in originals if lib == library and ct == chart_type}
                for ds_id in ids:
                    with self.subTest(chart_type=chart_type, library=library, dataset=ds_id):
                        self.assertIn((library, chart_type, ds_id), clean_by_key)
                        bank = Path(PAGES_DIR) / library / f"clean_{chart_type}__{ds_id}.capability_tasks.json"
                        self.assertTrue(bank.is_file())
                        generated = {a["attack_id"] for a in attacks if a["library"] == library
                                     and a["chart_type"] == chart_type and a["dataset"] == ds_id}
                        self.assertEqual(generated, {f"{a}__{ds_id}" for a in base})

    def test_dataset_attacks_pair_with_their_own_dataset_baseline(self):
        trials = attack_trials(["d3"], datasets={"steam_core"})
        self.assertTrue(trials)
        for attack, baseline in zip(trials[::2], trials[1::2]):
            self.assertTrue(attack["attack_id"].endswith("__steam_core"))
            self.assertEqual(baseline["question"], attack["question"])
            stem = Path(baseline["html_path"]).stem
            self.assertTrue(stem.startswith("clean_") and stem.endswith("__steam_core"), stem)
        originals = attack_trials(["d3"], datasets={"original"})
        self.assertTrue(all("_core" not in t["attack_id"] for t in originals))

    def test_capability_tasks_cover_every_dataset(self):
        tasks = discover_tasks(["chartjs"])
        pages = {t["attack_id"] for t in tasks}
        for chart_type in list(self.builder.CHART_TYPES) + ["revenue"]:
            self.assertIn(f"clean_{chart_type}", pages)
            for ds in self.datasets[chart_type]:
                self.assertIn(f"clean_{chart_type}__{ds['id']}", pages)
        only = discover_tasks(["chartjs"], datasets={"climate_core"})
        self.assertTrue(only and all(t["attack_id"].endswith("__climate_core") for t in only))

    def test_ground_truths_follow_the_dataset_values(self):
        ds = deepcopy(self.datasets["bar"][0])
        ds["values"] = [500, 120, 140, 160, 180]
        (_, truth), bank = self.builder.generate_tasks("bar", ds, "chartjs")
        answers = {t["task_id"]: t["ground_truth"] for t in bank}
        self.assertEqual(truth, "500")
        self.assertEqual(answers["find_anomalies"], ds["categories"][0])
        self.assertEqual(answers["find_extremum"], ds["categories"][1])
        self.assertEqual(answers["determine_range"], "380")
        self.assertEqual(answers["compute_derived_value"], "1100")

    def test_dataset_that_breaks_a_task_premise_is_rejected(self):
        ds = deepcopy(self.datasets["line"][0])
        ds["series"][1]["values"] = sorted(ds["series"][1]["values"])
        with self.assertRaises(ValueError):
            self.builder.generate_tasks("line", ds, "d3")


if __name__ == "__main__":
    unittest.main()
