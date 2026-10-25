#!/usr/bin/env python3
"""Standalone AnthropicBedrockMantle smoke tests; see README.md."""

import argparse
import base64
import json
import os
from pathlib import Path
import re
import sys


def image_block(path):
    data = Path(path).read_bytes()
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        media_type = "image/png"
    elif data.startswith(b"\xff\xd8\xff"):
        media_type = "image/jpeg"
    else:
        raise ValueError("The vision test accepts PNG or JPEG files only.")
    return {"type": "image", "source": {"type": "base64", "media_type": media_type,
            "data": base64.b64encode(data).decode("ascii")}}


def run_test(client, model_id, mode, image_path=None):
    """One request for text/vision; two for a harmless local tool round trip."""
    if mode == "vision":
        content = [image_block(image_path), {"type": "text", "text":
                   "Describe the attached image briefly. Mention its chart type if it is a chart."}]
    else:
        prompt = "Reply with exactly: AWS API test OK"
        if mode == "tools":
            prompt = "Call get_test_value once, then report the returned value. Do not guess."
        content = [{"type": "text", "text": prompt}]

    messages = [{"role": "user", "content": content}]
    request = {"model": model_id, "messages": messages, "max_tokens": 512}
    if mode == "tools":
        request["tools"] = [{
            "name": "get_test_value",
            "description": "Return a fixed value for this API connectivity test.",
            "input_schema": {"type": "object", "properties": {},
                             "additionalProperties": False},
        }]

    responses = [client.messages.create(**request)]
    if mode == "tools":
        message = responses[0]
        calls = [block for block in message.content if block.type == "tool_use"]
        if message.stop_reason != "tool_use" or len(calls) != 1:
            raise ValueError("Model did not request exactly one tool call; tool test failed.")
        call = calls[0]
        if call.name != "get_test_value" or call.input != {}:
            raise ValueError("Unexpected tool or input; nothing was executed.")
        # No model-supplied code runs: only this hard-coded local fixture.
        messages.extend([
            {"role": "assistant", "content": [block.model_dump(exclude_none=True)
                                               for block in message.content]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": call.id,
                                          "content": json.dumps({"value": 42})}]},
        ])
        responses.append(client.messages.create(**request))

    final = responses[-1]
    answer = "\n".join(block.text for block in final.content if block.type == "text").strip()
    if not answer or final.stop_reason != "end_turn":
        raise ValueError("Model did not finish with a text answer; check model support/settings.")
    if mode == "tools" and not re.search(r"\b42\b", answer):
        raise ValueError("Model did not report the tool's value (42); tool test failed.")
    return answer, [response.usage.model_dump(exclude_none=True) for response in responses]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("text", "vision", "tools"), default="text")
    parser.add_argument("--image", help="PNG/JPEG path, required for --mode vision")
    parser.add_argument("--model", default=os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-haiku-4-5"))
    parser.add_argument("--region", default=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-west-2")
    parser.add_argument("--profile", default=os.getenv("AWS_PROFILE"))
    parser.add_argument("--workspace", default=os.getenv("ANTHROPIC_WORKSPACE_ID", "default"))
    args = parser.parse_args(argv)
    if args.mode == "vision" and not args.image:
        parser.error("--mode vision requires --image")
    if args.image and args.mode != "vision":
        parser.error("--image requires --mode vision")

    try:
        from anthropic import AnthropicBedrockMantle, AnthropicError, APIStatusError
        from botocore.exceptions import BotoCoreError
    except ImportError:
        print('Install/upgrade: python -m pip install -U "anthropic[bedrock]"', file=sys.stderr)
        return 1

    try:
        with AnthropicBedrockMantle(
            aws_region=args.region,
            aws_profile=args.profile,
            default_headers={"anthropic-workspace-id": args.workspace},
            max_retries=0,
            timeout=120.0,
        ) as client:
            answer, usage = run_test(client, args.model, args.mode, args.image)
    except (AnthropicError, BotoCoreError) as exc:
        # Do not print credentials, headers, or full SDK request/error objects.
        status = f" (HTTP {exc.status_code})" if isinstance(exc, APIStatusError) else ""
        print(f"AWS/SDK error: {type(exc).__name__}{status}. See README.md.", file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        detail = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print(f"Test failed: {detail}", file=sys.stderr)
        return 1

    print(f"PASS: {args.mode} response received ({len(usage)} request(s)).")
    print(answer)
    print("Token usage per request:", json.dumps(usage))
    if args.mode == "vision":
        print("Manually verify the description; PASS is not an accuracy grade.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
