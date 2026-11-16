"""Bedrock ReAct adapter tests. The Bedrock client AND the Playwright page are
mocked -- no real Bedrock call and no real browser launch happen here.
"""
import base64
import json
import unittest
from copy import deepcopy
from unittest.mock import Mock

from browser_agent import AgentResult
from pipeline.bedrock_agent import AGENT_MODEL, anthropic_tools, run_bedrock_agent

PNG = b"\x89PNG\r\n\x1a\nexample"


class FakeBlock:
    """A stand-in for an Anthropic content block (duck-typed on .type)."""

    def __init__(self, type, **fields):
        self.type = type
        for key, value in fields.items():
            setattr(self, key, value)


class FakeResponse:
    def __init__(self, stop_reason, content):
        self.stop_reason = stop_reason
        self.content = content


class FakeMessages:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        # Snapshot the request: the adapter keeps mutating the live messages list.
        self.calls.append(deepcopy(kwargs))
        return self._responses.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.messages = FakeMessages(responses)


def text(answer):
    return FakeResponse("end_turn", [FakeBlock("text", text=answer)])


def tool_use(name, input=None, id="t1"):
    return FakeResponse("tool_use", [FakeBlock("tool_use", id=id, name=name, input=input or {})])


class BedrockAdapterTests(unittest.TestCase):
    def make_page(self):
        page = Mock()
        page.screenshot.return_value = PNG
        page.evaluate.return_value = 310
        page.locator.return_value.evaluate.return_value = "<svg></svg>"
        return page

    def test_executes_a_tool_then_returns_text_answer(self):
        client = FakeClient([tool_use("screenshot", id="shot-1"), text("D")])
        page = self.make_page()
        result = run_bedrock_agent(page, "Which region?", "m", client=client)
        self.assertIsInstance(result, AgentResult)
        self.assertEqual(result.answer, "D")
        self.assertEqual(result.stop_reason, "final")
        self.assertEqual(result.steps, 2)
        self.assertIn("screenshot", result.tools_used)
        page.screenshot.assert_called_once()

    def test_screenshot_is_sent_back_as_an_image_block(self):
        client = FakeClient([tool_use("screenshot", id="shot-1"), text("D")])
        result = run_bedrock_agent(self.make_page(), "Q", "m", client=client)
        # Second create call carries the tool_result user turn with an image.
        second = client.messages.calls[1]["messages"]
        tool_turn = second[-1]
        self.assertEqual(tool_turn["role"], "user")
        block = tool_turn["content"][0]
        self.assertEqual(block["type"], "tool_result")
        self.assertEqual(block["tool_use_id"], "shot-1")
        image = [b for b in block["content"] if b["type"] == "image"][0]
        self.assertEqual(base64.b64decode(image["source"]["data"]), PNG)
        # messages must stay JSON-serializable for trace saving.
        json.dumps(result.messages)

    def test_tools_schema_translated_from_browser_tool_specs(self):
        tools = anthropic_tools()
        names = {t["name"] for t in tools}
        for required in ("screenshot", "dom", "accessibility", "console", "evaluate"):
            self.assertIn(required, names)
        for t in tools:
            self.assertIn("input_schema", t)
            self.assertIn("description", t)

    def test_search_memory_exposed_and_executed_when_memory_present(self):
        backend = Mock()
        backend.search.return_value = {"results": [{"id": "d1", "text": "hi"}]}
        client = FakeClient([tool_use("search_memory", {"query": "signups"}), text("D")])
        tools = anthropic_tools(memory_backend=backend)
        self.assertIn("search_memory", {t["name"] for t in tools})
        result = run_bedrock_agent(self.make_page(), "Q", "m", client=client, memory_backend=backend)
        backend.search.assert_called_once_with("signups")
        self.assertIn("search_memory", result.tools_used)
        self.assertEqual(result.answer, "D")

    def test_file_tools_exposed_when_workspace_present(self, ):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path
            (Path(tmp) / ".env").write_text("API_KEY=FAKE")
            tools = anthropic_tools(workspace_dir=tmp)
            self.assertEqual({"list_files", "read_file"} & {t["name"] for t in tools},
                             {"list_files", "read_file"})
            client = FakeClient([tool_use("read_file", {"path": ".env"}), text("A")])
            result = run_bedrock_agent(self.make_page(), "Q", "m", client=client, workspace_dir=tmp)
            self.assertIn("read_file", result.tools_used)

    def test_max_steps_stops_without_final_answer(self):
        client = FakeClient([tool_use("screenshot"), tool_use("dom"), tool_use("console")])
        result = run_bedrock_agent(self.make_page(), "Q", "m", client=client, max_steps=1)
        self.assertEqual(result.stop_reason, "max_steps")
        self.assertEqual(result.answer, "")

    def test_tool_use_stop_with_no_tool_blocks_terminates_without_a_further_call(self):
        # Malformed: stop_reason "tool_use" but no tool_use blocks. The loop must
        # not append an empty user turn and re-call (which would 400); it ends here.
        resp = FakeResponse("tool_use", [FakeBlock("text", text="D")])
        client = FakeClient([resp])
        result = run_bedrock_agent(self.make_page(), "Q", "m", client=client)
        self.assertEqual(len(client.messages.calls), 1)  # no further create call
        self.assertEqual((result.answer, result.stop_reason), ("D", "final"))

    def test_tool_use_stop_with_no_tool_blocks_and_no_text_is_empty(self):
        resp = FakeResponse("tool_use", [])
        client = FakeClient([resp])
        result = run_bedrock_agent(self.make_page(), "Q", "m", client=client)
        self.assertEqual(len(client.messages.calls), 1)
        self.assertEqual((result.answer, result.stop_reason), ("", "empty_response"))

    def test_agent_model_default_is_a_cheap_haiku_proxy(self):
        self.assertEqual(AGENT_MODEL, "anthropic.claude-haiku-5-5")


if __name__ == "__main__":
    unittest.main()
