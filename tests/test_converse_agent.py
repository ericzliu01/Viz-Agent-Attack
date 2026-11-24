"""Converse-API agent loop: tool-use round, final answer, request-error handling.
No real Bedrock or browser call; the screenshot test uses the real tool encoder
with a fake page and client."""
import base64

from pipeline import converse_agent as ca


class FakeConverse:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def converse(self, model, system, messages, tool_config, max_tokens):
        self.calls.append({"model": model, "messages": [m for m in messages]})
        return self.responses.pop(0)


def _tool_use(tool_use_id, name, inp=None):
    return {"stopReason": "tool_use", "output": {"message": {"content": [
        {"toolUse": {"toolUseId": tool_use_id, "name": name, "input": inp or {}}}]}}}


def _final(text):
    return {"stopReason": "end_turn", "output": {"message": {"content": [{"text": text}]}}}


def test_converse_agent_runs_tool_loop_then_answers(monkeypatch):
    monkeypatch.setattr(ca, "_execute_tool", lambda name, args, **k: ("observed", []))
    client = FakeConverse([_tool_use("t1", "dom"), _final("B")])
    res = ca.run_converse_agent(object(), "Q?", "m", client=client, console_logs=[])
    assert res.answer == "B" and res.stop_reason == "final"
    assert res.steps == 2 and "dom" in res.tools_used


def test_converse_agent_screenshot_tool_result_carries_image():
    png = b"\x89PNG\r\n\x1a\nfixture"

    class Page:
        def screenshot(self):
            return png

    client = FakeConverse([_tool_use("t1", "screenshot"), _final("A")])
    res = ca.run_converse_agent(Page(), "Q?", "m", client=client, console_logs=[])
    # Bedrock restricts images nested in toolResult for some model families, so the
    # tool result itself must stay text-only, with the image carried by a separate,
    # immediately-following user message that names the tool call it answers.
    messages = client.calls[1]["messages"]
    tr = messages[-2]["content"][0]["toolResult"]
    assert tr.get("status") != "error"
    assert all("image" not in block for block in tr["content"])

    attachment = messages[-1]
    assert attachment["role"] == "user"
    assert "t1" in attachment["content"][0]["text"]
    images = [block["image"] for block in attachment["content"] if "image" in block]
    assert len(images) == 1
    assert images[0]["format"] == "png"
    assert base64.b64decode(images[0]["source"]["bytes"], validate=True) == png
    assert res.answer == "A" and "screenshot" in res.tools_used


def test_image_block_accepts_raw_bytes_for_direct_image_evaluation():
    png = b"\x89PNG\r\n\x1a\nfixture"
    assert base64.b64decode(ca._image_block(png)["image"]["source"]["bytes"]) == png


def test_converse_agent_submit_answer_ends_with_structured_choice(monkeypatch):
    sub = {"stopReason": "tool_use", "output": {"message": {"content": [
        {"toolUse": {"toolUseId": "t1", "name": "submit_answer",
                     "input": {"choice": "c", "explanation": "the bar is tallest"}}}]}}}
    client = FakeConverse([sub])
    res = ca.run_converse_agent(object(), "Q?", "m", client=client, console_logs=[])
    assert res.answer == "C" and res.stop_reason == "submitted"
    assert res.explanation == "the bar is tallest" and "submit_answer" in res.tools_used


def test_converse_agent_request_error_is_a_stop(monkeypatch):
    class Boom:
        def converse(self, *a, **k):
            raise RuntimeError("bedrock down")
    res = ca.run_converse_agent(object(), "Q?", "m", client=Boom(), console_logs=[])
    assert res.stop_reason == "request_error" and "bedrock down" in res.error


def test_to_converse_tools_shape():
    tools = [{"name": "dom", "description": "d", "input_schema": {"type": "object"}}]
    out = ca._to_converse_tools(tools)
    assert out[0]["toolSpec"]["name"] == "dom"
    assert out[0]["toolSpec"]["inputSchema"]["json"] == {"type": "object"}
