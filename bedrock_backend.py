"""AWS Bedrock (Converse API) chat backend for browser_agent.run_agent.

Messages stay in the Ollama format the agent and traces already use; this
module translates them to Converse requests and the reply back into an
Ollama-style assistant message. Credentials come from the environment
(AWS_BEARER_TOKEN_BEDROCK or the usual AWS chain), e.g. `. AWS-API/aws-api-test.env`.
Sonnet 5.5 and GPT-6-luna reject `temperature`, so no sampling settings are
sent and the models use their defaults. Model ids need the cross-region prefix, e.g. us.anthropic.claude-sonnet-5-5
or us.openai.gpt-6-luna (base ids are rejected for on-demand use).
"""
import base64
import io
import json
import os

MAX_IMAGE_SIDE = 1568  # Bedrock rejects larger images
MAX_TOKENS = 4096
CACHE_POINT = {"cachePoint": {"type": "default"}}

_clients = {}


class BedrockError(ValueError):
    """A Bedrock request failed; run_agent records it as a request_error."""


def client(region=None, timeout=180):
    import boto3
    from botocore.config import Config
    region = region or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-west-2"
    key = (region, timeout)
    if key not in _clients:
        _clients[key] = boto3.client("bedrock-runtime", region_name=region, config=Config(
            read_timeout=timeout, retries={"max_attempts": 8, "mode": "adaptive"}))
    return _clients[key]


def supports_cache(model):
    """Converse cache points; only sent where Bedrock accepts them."""
    return "anthropic." in model


def images_in_tool_results(model):
    """GPT models on Bedrock reject images inside toolResult blocks; they get the
    screenshot as an image block in the same user message instead."""
    return "anthropic." in model


def image_bytes(encoded):
    """PNG bytes, downscaled so the longer side is at most MAX_IMAGE_SIDE."""
    data = base64.b64decode(encoded)
    from PIL import Image
    with Image.open(io.BytesIO(data)) as image:
        if max(image.size) <= MAX_IMAGE_SIDE:
            return data
        scale = MAX_IMAGE_SIDE / max(image.size)
        resized = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))))
        out = io.BytesIO()
        resized.save(out, format="PNG")
        return out.getvalue()


def to_converse(messages, tools, cache, tool_images=True):
    """(system, converse_messages, tool_config) from Ollama-format messages and tools."""
    system, converted = [], []
    pending_ids = []  # tool-call ids of the last assistant message, in order

    def add(role, blocks):
        if converted and converted[-1]["role"] == role:
            converted[-1]["content"].extend(blocks)
        else:
            converted.append({"role": role, "content": blocks})

    for message in messages:
        role = message.get("role")
        content = message.get("content") or ""
        if role == "system":
            system.append({"text": content})
        elif role == "user":
            blocks = [{"text": content}] if content.strip() else []
            blocks += [{"image": {"format": "png", "source": {"bytes": image_bytes(i)}}}
                       for i in message.get("images") or []]
            add("user", blocks or [{"text": "(empty)"}])
        elif role == "assistant":
            blocks = [{"text": content}] if content.strip() else []
            pending_ids = []
            for index, call in enumerate(message.get("tool_calls") or []):
                function = call.get("function", {})
                arguments = function.get("arguments", {})
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except ValueError:
                        arguments = {}
                call_id = call.get("id") or f"call_{len(converted)}_{index}"
                call["id"] = call_id  # the matching tool message reuses it
                pending_ids.append(call_id)
                blocks.append({"toolUse": {"toolUseId": call_id, "name": function.get("name", ""),
                                           "input": arguments if isinstance(arguments, dict) else {}}})
            add("assistant", blocks or [{"text": "(no answer)"}])
        elif role == "tool":
            call_id = message.get("tool_call_id") or (pending_ids.pop(0) if pending_ids else "unknown")
            if call_id in pending_ids:
                pending_ids.remove(call_id)
            images = [{"image": {"format": "png", "source": {"bytes": image_bytes(i)}}}
                      for i in message.get("images") or []]
            if tool_images:
                add("user", [{"toolResult": {"toolUseId": call_id,
                                             "content": [{"text": content or "(empty)"}, *images]}}])
            else:
                note = f" (image for tool call {call_id} follows in this message)" if images else ""
                add("user", [{"toolResult": {"toolUseId": call_id,
                                             "content": [{"text": (content or "(empty)") + note}]}},
                             *images])
    for message in converted:  # tool results first in each user turn, other blocks keep their order
        message["content"].sort(key=lambda block: "toolResult" not in block)
    tool_specs = [{"toolSpec": {"name": t["function"]["name"],
                                "description": t["function"].get("description", ""),
                                "inputSchema": {"json": t["function"].get("parameters") or
                                                {"type": "object", "properties": {}}}}}
                  for t in tools or []]
    if cache:
        system.append(CACHE_POINT)
        if tool_specs:
            tool_specs.append(CACHE_POINT)
        if converted:
            converted[-1]["content"].append(CACHE_POINT)
    return system, converted, ({"tools": tool_specs} if tool_specs else None)


def chat(model, messages, tools=None, timeout=180, max_tokens=MAX_TOKENS):
    """One Converse call. Returns (assistant message in Ollama format, usage dict)."""
    from botocore.exceptions import BotoCoreError, ClientError
    system, converted, tool_config = to_converse(messages, tools, supports_cache(model),
                                                 images_in_tool_results(model))
    request = {"modelId": model, "messages": converted, "system": system,
               "inferenceConfig": {"maxTokens": max_tokens}}
    if tool_config:
        request["toolConfig"] = tool_config
    try:
        response = client(timeout=timeout).converse(**request)
    except ClientError as exc:
        error = exc.response.get("Error", {})
        raise BedrockError(f"Bedrock {error.get('Code', 'error')}: {error.get('Message', '')[:300]}") from None
    except BotoCoreError as exc:
        raise BedrockError(f"Bedrock {type(exc).__name__}") from None
    texts, thinking, calls = [], [], []
    for block in response["output"]["message"]["content"]:
        if "text" in block:
            texts.append(block["text"])
        elif "reasoningContent" in block:
            thinking.append(block["reasoningContent"].get("reasoningText", {}).get("text", ""))
        elif "toolUse" in block:
            use = block["toolUse"]
            calls.append({"id": use["toolUseId"],
                          "function": {"name": use["name"], "arguments": use.get("input") or {}}})
    message = {"role": "assistant", "content": "\n".join(texts).strip()}
    if thinking:
        message["thinking"] = "\n".join(thinking).strip()
    if calls:
        message["tool_calls"] = calls
    usage = response.get("usage", {})
    return message, {"input": usage.get("inputTokens", 0), "output": usage.get("outputTokens", 0),
                     "cache_read": usage.get("cacheReadInputTokens", 0),
                     "cache_write": usage.get("cacheWriteInputTokens", 0),
                     "stop_reason": response.get("stopReason")}
