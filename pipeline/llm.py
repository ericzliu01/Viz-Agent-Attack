"""Bedrock LLM wrapper with a spec-hash cache.

The three generation stages and the judge all reach Claude on AWS Bedrock through
this one wrapper. :func:`complete` calls the ``AnthropicBedrockMantle`` client
(the same client and request shape as ``AWS-API/aws-api-test.py``) and caches each
response in one file per ``cache_key`` under ``cache_dir``. The on-disk key folds
in ``model``, so switching a stage's model re-generates only that stage. On a cache
hit the cached text is returned without constructing a client or making any call.

Sonnet 5.5 notes (applied here): no assistant prefill and no forced ``tool_choice``
(both 400 on this model), and ``temperature``/``top_p`` are left unset. Callers get
JSON back by instructing the model in the prompt/system and parsing the reply with
:func:`parse_json_block`; the assistant turn is never prefilled.
"""
import base64
import hashlib
import json
import os
import re
from pathlib import Path

#: Default region when no AWS_REGION / AWS_DEFAULT_REGION is set (matches aws-api-test.py).
DEFAULT_REGION = "us-west-2"

#: max_tokens for a single request. Generous for typical stage outputs; truly large
#: batched outputs would want streaming (see module notes / task report).
MAX_TOKENS = 16384

#: Per-stage Bedrock model IDs, each overridable by env. Callers pass MODELS[stage].
MODELS = {
    "stage1": os.getenv("VIZTRAP_STAGE1_MODEL", "anthropic.claude-sonnet-5-5"),
    "stage2": os.getenv("VIZTRAP_STAGE2_MODEL", "anthropic.claude-sonnet-5-5"),
    "stage3": os.getenv("VIZTRAP_STAGE3_MODEL", "anthropic.claude-sonnet-5-5"),
    "judge": os.getenv("VIZTRAP_JUDGE_MODEL", "anthropic.claude-haiku-5-5"),
}


class LLMFormatError(ValueError):
    """Raised when a model reply contains no parseable JSON object."""


def _cache_path(cache_dir, cache_key, model):
    """One file per (model, cache_key). Folding ``model`` into the on-disk key means
    switching a stage's model re-generates only that stage, even for the same key."""
    digest = hashlib.sha256(f"{model}\x00{cache_key}".encode("utf-8")).hexdigest()
    return Path(cache_dir) / f"{digest}.json"


def _image_block(data):
    """A base64 PNG vision content block, matching aws-api-test.py's image_block."""
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": base64.b64encode(data).decode("ascii"),
        },
    }


def _build_client():
    """The real AnthropicBedrockMantle, constructed exactly as aws-api-test.py does.

    Imported lazily so the module (and its cache/JSON helpers) load without the
    ``anthropic[bedrock]`` extra installed; only a real cache miss needs it.
    """
    from anthropic import AnthropicBedrockMantle

    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or DEFAULT_REGION
    return AnthropicBedrockMantle(
        aws_region=region,
        aws_profile=os.getenv("AWS_PROFILE"),
        default_headers={"anthropic-workspace-id": os.getenv("ANTHROPIC_WORKSPACE_ID", "default")},
        max_retries=0,
        timeout=120.0,
    )


def complete(prompt, *, system, model, cache_key, cache_dir, images=(), client=None):
    """Call Bedrock and return the assistant's text, caching the result.

    ``images`` (PNG bytes) are sent as base64 vision blocks before the text block.
    On a cache hit the cached text is returned without constructing a client or
    making any call. When ``client`` is None (and it is a miss), the real
    ``AnthropicBedrockMantle`` is built; tests inject a mock instead.
    """
    path = _cache_path(cache_dir, cache_key, model)
    if path.exists():
        return json.loads(path.read_text())["text"]

    if client is None:
        client = _build_client()

    content = [_image_block(image) for image in images]
    content.append({"type": "text", "text": prompt})
    message = client.messages.create(
        model=model,
        system=system,
        messages=[{"role": "user", "content": content}],
        max_tokens=MAX_TOKENS,
    )
    text = "\n".join(
        block.text for block in message.content if block.type == "text"
    ).strip()

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"model": model, "cache_key": cache_key, "text": text}))
    return text


def _first_json_object(text):
    """Return the first balanced, brace-delimited JSON object in ``text``, or None.

    Scans for a top-level ``{`` ... ``}`` span (respecting strings/escapes) and
    tries to parse it; a span that is not valid JSON is skipped so later ones can
    still match. Only dict results are accepted.
    """
    depth = 0
    start = None
    in_string = False
    escaped = False
    for i, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = i
            depth += 1
        elif char == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    obj = json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    start = None
                    continue
                if isinstance(obj, dict):
                    return obj
                start = None
    return None


def parse_json_block(text):
    """Extract the JSON object from a model reply, raising LLMFormatError on none.

    Handles prose before/after the JSON and ```json ... ``` fences; a fenced body
    is tried first, then the whole text.
    """
    candidates = []
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        candidates.append(fence.group(1))
    candidates.append(text)
    for candidate in candidates:
        obj = _first_json_object(candidate)
        if obj is not None:
            return obj
    raise LLMFormatError("no JSON object found in model reply")
