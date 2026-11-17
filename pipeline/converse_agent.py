"""A Bedrock **Converse API** ReAct adapter -- the same browser tool loop as
``run_bedrock_agent``, but driving NON-Anthropic Bedrock models (e.g. OpenAI
``us.openai.gpt-5.6-luna``) through the model-agnostic Converse protocol instead of the
Anthropic Messages API.

Converse differs from Anthropic Messages: tools go in ``toolConfig`` as ``toolSpec``
entries, tool calls come back as ``toolUse`` content blocks, and results are returned as
``toolResult`` blocks (screenshots as ``image`` blocks, base64 over the REST wire). The
tool-execution logic itself is shared with ``pipeline.bedrock_agent`` (``_execute_tool``,
``anthropic_tools``), so both adapters expose the identical browser/memory/workspace tools.

Auth is the same ``AWS_BEARER_TOKEN_BEDROCK`` used elsewhere; requests go straight to the
``bedrock-runtime`` Converse endpoint. Tests inject a client exposing ``converse(...)``.
"""
import base64
import json
import os
import time
import urllib.error
import urllib.request

from browser_agent import AgentResult, BrowserTools, SYSTEM_PROMPT, capture_console
from pipeline.bedrock_agent import (BROWSER_TOOL_NAMES, MAX_TOKENS, anthropic_tools,
                                    _execute_tool)

#: Default Converse agent-under-test. Overridable by env.
AGENT_MODEL = os.getenv("VIZTRAP_CONVERSE_MODEL", "us.openai.gpt-5.6-luna")
DEFAULT_REGION = "us-west-2"


class BedrockConverseClient:
    """Minimal Bedrock Converse client: one HTTPS POST per turn, bearer-token auth."""

    def __init__(self, region=None, token=None, timeout=120):
        self.region = region or os.getenv("AWS_REGION") or DEFAULT_REGION
        self.token = token or os.environ["AWS_BEARER_TOKEN_BEDROCK"]
        self.timeout = timeout

    def converse(self, model, system, messages, tool_config, max_tokens):
        url = f"https://bedrock-runtime.{self.region}.amazonaws.com/model/{model}/converse"
        body = {"messages": messages, "inferenceConfig": {"maxTokens": max_tokens}}
        if system:
            body["system"] = [{"text": system}]
        if tool_config:
            body["toolConfig"] = tool_config
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(), method="POST",
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read())


def _to_converse_tools(tools):
    """Anthropic-style ``{name, description, input_schema}`` -> Converse ``toolSpec``."""
    return [
        {"toolSpec": {"name": t["name"], "description": t["description"],
                      "inputSchema": {"json": t["input_schema"]}}}
        for t in tools
    ]


def _image_block(png):
    """A Converse PNG image block (REST wants base64-encoded bytes)."""
    return {"image": {"format": "png", "source": {"bytes": base64.b64encode(png).decode()}}}


def _tool_result(tool_use_id, content, images, is_error=False):
    body = [{"text": content}] + ([_image_block(i) for i in images] if images else [])
    block = {"toolResult": {"toolUseId": tool_use_id, "content": body}}
    if is_error:
        block["toolResult"]["status"] = "error"
    return block


def run_converse_agent(page, question, model=None, *, workspace_dir=None, memory_backend=None,
                       max_steps=15, client=None, system_prompt=None, console_logs=None,
                       max_tokens=MAX_TOKENS):
    """Run the ReAct browser loop against a Bedrock Converse model; return an AgentResult.

    Matches the eval ``agent_fn`` contract, so the same runner drives it. ``client`` is a
    :class:`BedrockConverseClient` (built lazily when not injected); tests inject a double
    exposing ``converse(...)`` so no real Bedrock or browser call is made.
    """
    if max_steps < 1:
        raise ValueError("max_steps must be positive")
    start = time.monotonic()
    model = model or AGENT_MODEL
    system = system_prompt if system_prompt is not None else SYSTEM_PROMPT

    tools = anthropic_tools(memory_backend=memory_backend, workspace_dir=workspace_dir)
    enabled_names = {t["name"] for t in tools}
    tool_config = {"tools": _to_converse_tools(tools)} if tools else None
    browser_tools = BrowserTools(
        page, console_logs if console_logs is not None else capture_console(page),
        enabled_tools=enabled_names & set(BROWSER_TOOL_NAMES))

    messages = [{"role": "user", "content": [{"text": question}]}]
    result = AgentResult(messages=messages)
    if client is None:
        client = BedrockConverseClient()

    for step in range(1, max_steps + 1):
        result.steps = step
        try:
            resp = client.converse(model, system, messages, tool_config, max_tokens)
        except Exception as exc:  # noqa: BLE001 -- surface any client error as a stop
            result.stop_reason, result.error = "request_error", str(exc)
            break

        content = resp.get("output", {}).get("message", {}).get("content", []) or []
        messages.append({"role": "assistant", "content": content})
        tool_uses = [b["toolUse"] for b in content if isinstance(b, dict) and "toolUse" in b]

        if resp.get("stopReason") != "tool_use" or not tool_uses:
            answer = "\n".join(b["text"] for b in content
                               if isinstance(b, dict) and "text" in b).strip()
            result.answer = answer
            result.stop_reason = "final" if answer else "empty_response"
            break

        tool_results = []
        for tu in tool_uses:
            name, args, tuid = tu.get("name"), tu.get("input", {}), tu.get("toolUseId")
            try:
                out, images = _execute_tool(
                    name, args, browser_tools=browser_tools, enabled_names=enabled_names,
                    memory_backend=memory_backend, workspace_dir=workspace_dir)
                tool_results.append(_tool_result(tuid, out, images))
                if name not in result.tools_used:
                    result.tools_used.append(name)
            except Exception as exc:  # noqa: BLE001 -- tool errors are observations
                tool_results.append(_tool_result(tuid, json.dumps({"error": str(exc)}), [],
                                                 is_error=True))
        messages.append({"role": "user", "content": tool_results})

    result.latency_ms = int((time.monotonic() - start) * 1000)
    return result
