"""A Bedrock ReAct adapter: the SAME browser tool loop as ``browser_agent.run_agent``,
but driving Claude on AWS Bedrock with the Anthropic Messages tool-use protocol
instead of Ollama's ``/api/chat``.

This is a LOCAL PROVING PROXY for the agent-under-test, NOT the real target. The
real benchmark target is ``qwen3-vl:8b`` served by Ollama on the MSI host; this
module lets the whole evaluation loop run end to end on a laptop (no Ollama, no
MSI) by substituting a cheap hosted Claude (default ``us.anthropic.claude-haiku-5-5``)
for that target. Results from this proxy prove the plumbing; they are not the
benchmark's reported agent behaviour.

The request shape mirrors ``AWS-API/aws-api-test.py`` and ``pipeline/llm.py``: an
``AnthropicBedrockMantle`` client, ``messages.create`` with ``tools`` of the shape
``{name, description, input_schema}``, ``tool_use`` blocks in the assistant turn,
and ``tool_result`` blocks (screenshots as ``image`` blocks) in the following user
turn. No assistant prefill and no forced ``tool_choice`` (both 400 on these models).
"""
import base64
import json
import os
import time

import browser_agent
from browser_agent import (AgentResult, BrowserTools, SYSTEM_PROMPT, TOOLS,
                           capture_console)

#: Agent-under-test proxy model. Overridable by env; default kept cheap on purpose.
#: Inference-profile ID (``us.`` prefix) -- 5-series models are INFERENCE_PROFILE-only
#: on Bedrock and the bare foundation-model ID 404s on direct runtime invocation.
AGENT_MODEL = os.getenv("VIZTRAP_AGENT_MODEL", "us.anthropic.claude-haiku-5-5")

#: Browser tools exposed to the proxy agent -- the read-only inspection subset that
#: the ReAct loop needs to read a chart. (The browser can also act, but the proving
#: QAs only require observation.)
BROWSER_TOOL_NAMES = ("screenshot", "dom", "accessibility", "console", "evaluate")

#: Default answer budget per turn. Chart answers are short; raise if a model needs
#: more room for intermediate reasoning text.
MAX_TOKENS = 1024


def _anthropic_tool(spec):
    """Translate one ``browser_agent.tool`` spec into Anthropic tool schema.

    ``browser_agent`` tools are Ollama function specs
    ``{"type": "function", "function": {name, description, parameters}}``; Anthropic
    wants ``{name, description, input_schema}`` with ``parameters`` as the schema.
    """
    function = spec["function"]
    return {
        "name": function["name"],
        "description": function["description"],
        "input_schema": function["parameters"],
    }


def anthropic_tools(*, memory_backend=None, workspace_dir=None):
    """Build the Anthropic tool list for this trial.

    Always includes the read-only browser inspection tools. Adds ``search_memory``
    when a memory backend is present and ``list_files``/``read_file`` when a
    workspace is present -- the same gating as ``browser_agent.run_agent``.
    """
    from pipeline.file_tools import WORKSPACE_TOOLS

    specs = [spec for spec in TOOLS if spec["function"]["name"] in BROWSER_TOOL_NAMES]
    if memory_backend is not None:
        specs.append(browser_agent.MEMORY_TOOL)
    if workspace_dir is not None:
        specs.extend(WORKSPACE_TOOLS)
    specs.append(browser_agent.SUBMIT_ANSWER_TOOL)  # structured final answer
    return [_anthropic_tool(spec) for spec in specs]


def _image_block(encoded):
    """A base64 PNG image content block (matches pipeline.llm._image_block)."""
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                        "data": encoded}}


def _assistant_turn(content):
    """Serialize response content blocks into a plain, JSON-serializable dict turn.

    We rebuild dicts from block attributes (rather than ``model_dump``) so the turn
    stays JSON-serializable for trace saving and so test doubles need only expose
    ``.type`` / ``.text`` / ``.id`` / ``.name`` / ``.input``.
    """
    blocks = []
    for block in content:
        if block.type == "text":
            blocks.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            blocks.append({"type": "tool_use", "id": block.id,
                           "name": block.name, "input": block.input})
    return {"role": "assistant", "content": blocks}


def _execute_tool(name, arguments, *, browser_tools, enabled_names,
                  memory_backend, workspace_dir):
    """Run one tool call, returning ``(content, images)`` like browser execution.

    Mirrors the ``search_memory`` / ``list_files`` / ``read_file`` branches of
    ``browser_agent.run_agent`` so memory and workspace traps are reachable here too.
    """
    from pipeline.file_tools import FileWorkspace

    if name == "search_memory":
        if name not in enabled_names or memory_backend is None:
            raise ValueError("Tool not enabled for this run: search_memory")
        if not isinstance(arguments, dict) or set(arguments) != {"query"}:
            raise ValueError("search_memory requires exactly one argument: query")
        return json.dumps(memory_backend.search(arguments["query"]), ensure_ascii=False), []
    if name in ("list_files", "read_file"):
        if name not in enabled_names or workspace_dir is None:
            raise ValueError(f"Tool not enabled for this run: {name}")
        workspace = FileWorkspace(workspace_dir)
        if name == "list_files":
            if not isinstance(arguments, dict) or arguments:
                raise ValueError("list_files takes no arguments")
            return json.dumps(workspace.list_files(), ensure_ascii=False), []
        if not isinstance(arguments, dict) or set(arguments) != {"path"}:
            raise ValueError("read_file requires exactly one argument: path")
        return workspace.read_file(arguments["path"]), []
    return browser_tools.execute(name, arguments)


def _tool_result_block(tool_use_id, content, images, is_error=False):
    """A ``tool_result`` block; screenshots become image blocks alongside the text."""
    if images:
        body = [{"type": "text", "text": content}, *(_image_block(i) for i in images)]
    else:
        body = content
    block = {"type": "tool_result", "tool_use_id": tool_use_id, "content": body}
    if is_error:
        block["is_error"] = True
    return block


def _create_with_retry(client, *, model, system, messages, tools, max_tokens,
                       attempts=4, base_delay=2.0):
    """messages.create with exponential backoff + jitter on transient exceptions.

    Retries on any client exception (throttling, dropped connections) -- the
    unambiguous transient signal -- so concurrency-induced ``request_error`` trials
    resolve to real answers. An empty but successful response is left as-is (that is
    a valid terminal the caller records as ``empty_response``); such cases are
    re-run by the low-concurrency retry pass instead. Raises the last exception if
    every attempt raised.
    """
    import time, random
    last_exc = None
    for i in range(attempts):
        try:
            return client.messages.create(
                model=model, system=system, messages=messages,
                tools=tools, max_tokens=max_tokens)
        except Exception as exc:  # noqa: BLE001 -- transient; retry with backoff
            last_exc = exc
            if i < attempts - 1:
                time.sleep(base_delay * (2 ** i) + random.uniform(0, 1))
    raise last_exc


def run_bedrock_agent(page, question, model=None, *, workspace_dir=None,
                      memory_backend=None, max_steps=15, client=None,
                      system_prompt=None, console_logs=None, max_tokens=MAX_TOKENS):
    """Run the ReAct browser loop against Claude on Bedrock; return an AgentResult.

    ``client`` is built lazily via ``pipeline.llm._build_client`` on first use when
    not injected (standard ``AnthropicBedrock`` by default; Mantle is opt-in).
    Tests inject a mock client -- no real Bedrock or browser call is made.
    """
    if max_steps < 1:
        raise ValueError("max_steps must be positive")
    start = time.monotonic()
    model = model or AGENT_MODEL
    system = system_prompt if system_prompt is not None else SYSTEM_PROMPT

    tools = anthropic_tools(memory_backend=memory_backend, workspace_dir=workspace_dir)
    enabled_names = {tool["name"] for tool in tools}
    browser_tools = BrowserTools(
        page, console_logs if console_logs is not None else capture_console(page),
        enabled_tools=enabled_names & set(BROWSER_TOOL_NAMES))

    messages = [{"role": "user", "content": question}]
    result = AgentResult(messages=messages)

    if client is None:
        from pipeline.llm import _build_client
        client = _build_client()

    for step in range(1, max_steps + 1):
        result.steps = step
        try:
            response = _create_with_retry(
                client, model=model, system=system, messages=messages,
                tools=tools, max_tokens=max_tokens)
        except Exception as exc:  # noqa: BLE001 -- surface any client error as a stop
            result.stop_reason, result.error = "request_error", str(exc)
            break

        messages.append(_assistant_turn(response.content))
        tool_calls = [b for b in response.content if b.type == "tool_use"]

        # Treat a turn with no tool calls as the final answer. This also guards the
        # malformed edge case stop_reason=="tool_use" with zero tool_use blocks:
        # appending an empty user turn would 400 the next create call and abort the
        # trial, so we stop here instead.
        if response.stop_reason != "tool_use" or not tool_calls:
            answer = "\n".join(b.text for b in response.content if b.type == "text").strip()
            result.answer = answer
            result.stop_reason = "final" if answer else "empty_response"
            break

        # A structured final answer ends the trial immediately.
        submit = next((browser_agent.submitted_answer(b.name, b.input) for b in tool_calls
                       if b.name == "submit_answer"), None)
        if submit is not None:
            result.answer, result.explanation = submit
            result.stop_reason = "submitted"
            if "submit_answer" not in result.tools_used:
                result.tools_used.append("submit_answer")
            break

        tool_results = []
        for block in tool_calls:
            try:
                content, images = _execute_tool(
                    block.name, block.input, browser_tools=browser_tools,
                    enabled_names=enabled_names, memory_backend=memory_backend,
                    workspace_dir=workspace_dir)
                tool_results.append(_tool_result_block(block.id, content, images))
                if block.name not in result.tools_used:
                    result.tools_used.append(block.name)
            except Exception as exc:  # noqa: BLE001 -- tool errors are observations
                tool_results.append(_tool_result_block(
                    block.id, json.dumps({"error": str(exc)}), [], is_error=True))
        messages.append({"role": "user", "content": tool_results})

    result.latency_ms = int((time.monotonic() - start) * 1000)
    return result
