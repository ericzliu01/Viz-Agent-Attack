"""Converse-API agent loop: tool-use round, final answer, request-error handling.
No real Bedrock or browser call -- the converse client and tool execution are faked."""
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


def test_converse_agent_screenshot_tool_result_carries_image(monkeypatch):
    seen = {}
    monkeypatch.setattr(ca, "_execute_tool", lambda name, args, **k: ("shot", [b"PNG"]))
    client = FakeConverse([_tool_use("t1", "screenshot"), _final("A")])
    res = ca.run_converse_agent(object(), "Q?", "m", client=client, console_logs=[])
    # The second converse call must carry the tool result with an image block.
    tr = client.calls[1]["messages"][-1]["content"][0]["toolResult"]
    kinds = {k for block in tr["content"] for k in block}
    assert "image" in kinds and res.answer == "A"


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
