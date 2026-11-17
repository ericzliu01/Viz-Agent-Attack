"""Bedrock LLM wrapper: spec-hash cache, vision blocks, and JSON extraction.

The Bedrock client is always mocked (as ``tests/test_agent.py`` mocks
``requests.post``); no test makes a real network call. One test drives a cache
hit with ``client=None`` to prove a hit needs no client at all -- which also
keeps the suite runnable without ``anthropic`` installed.
"""
import base64
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pipeline.llm import MODELS, LLMFormatError, complete, parse_json_block


def fake_message(text="generated"):
    """A stand-in for anthropic's Message: a list of typed content blocks."""
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason="end_turn",
    )


def make_client(text="generated"):
    client = Mock()
    client.messages.create.return_value = fake_message(text)
    return client


def test_cache_miss_calls_client_then_hit_is_served_from_cache(tmp_path):
    client = make_client()
    first = complete("p", system="s", model="m", cache_key="k", cache_dir=tmp_path, client=client)
    second = complete("p", system="s", model="m", cache_key="k", cache_dir=tmp_path, client=client)
    assert first == second == "generated"
    assert client.messages.create.call_count == 1


def test_changing_model_busts_cache(tmp_path):
    client = make_client()
    complete("p", system="s", model="m1", cache_key="k", cache_dir=tmp_path, client=client)
    complete("p", system="s", model="m2", cache_key="k", cache_dir=tmp_path, client=client)
    assert client.messages.create.call_count == 2


def test_different_prompt_same_key_does_not_collide(tmp_path):
    client = make_client()
    complete("prompt one", system="s", model="m", cache_key="k", cache_dir=tmp_path, client=client)
    complete("prompt two", system="s", model="m", cache_key="k", cache_dir=tmp_path, client=client)
    assert client.messages.create.call_count == 2
    assert len(list(tmp_path.glob("*.json"))) == 2


def test_different_system_same_key_does_not_collide(tmp_path):
    client = make_client()
    complete("p", system="system one", model="m", cache_key="k", cache_dir=tmp_path, client=client)
    complete("p", system="system two", model="m", cache_key="k", cache_dir=tmp_path, client=client)
    assert client.messages.create.call_count == 2
    assert len(list(tmp_path.glob("*.json"))) == 2


def test_different_images_same_key_does_not_collide(tmp_path):
    client = make_client()
    complete("p", system="s", model="m", cache_key="k", cache_dir=tmp_path,
             images=[b"\x89PNG\r\n\x1a\nAAA"], client=client)
    complete("p", system="s", model="m", cache_key="k", cache_dir=tmp_path,
             images=[b"\x89PNG\r\n\x1a\nBBB"], client=client)
    assert client.messages.create.call_count == 2


def test_empty_response_is_not_cached(tmp_path):
    client = make_client(text="")
    assert complete("p", system="s", model="m", cache_key="k", cache_dir=tmp_path, client=client) == ""
    assert complete("p", system="s", model="m", cache_key="k", cache_dir=tmp_path, client=client) == ""
    assert client.messages.create.call_count == 2
    assert list(tmp_path.glob("*.json")) == []


def test_corrupt_cache_entry_is_treated_as_miss(tmp_path):
    client = make_client("fresh")
    complete("p", system="s", model="m", cache_key="k", cache_dir=tmp_path, client=client)
    cache_file = next(tmp_path.glob("*.json"))
    cache_file.write_text("{ truncated")  # simulate a crash mid-write
    assert complete("p", system="s", model="m", cache_key="k", cache_dir=tmp_path,
                    client=client) == "fresh"
    assert client.messages.create.call_count == 2


def test_cache_hit_constructs_no_client(tmp_path):
    complete("p", system="s", model="m", cache_key="k", cache_dir=tmp_path,
             client=make_client("cached"))
    # client=None would build the real AnthropicBedrockMantle on a miss; a hit must not.
    assert complete("p", system="s", model="m", cache_key="k", cache_dir=tmp_path,
                    client=None) == "cached"


def test_images_are_sent_as_base64_vision_blocks_before_text(tmp_path):
    client = make_client()
    png = b"\x89PNG\r\n\x1a\nfake"
    complete("p", system="s", model="m", cache_key="img", cache_dir=tmp_path,
             images=[png], client=client)
    content = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert content[0]["type"] == "image"
    assert content[0]["source"]["media_type"] == "image/png"
    assert base64.b64decode(content[0]["source"]["data"]) == png
    assert content[-1] == {"type": "text", "text": "p"}


def test_system_prompt_is_passed_through(tmp_path):
    client = make_client()
    complete("p", system="be terse", model="m", cache_key="k", cache_dir=tmp_path, client=client)
    assert client.messages.create.call_args.kwargs["system"] == "be terse"


def test_parse_json_block_extracts_object():
    assert parse_json_block('noise {"a":1} tail') == {"a": 1}


def test_parse_json_block_handles_json_fence():
    assert parse_json_block('here:\n```json\n{"a": 1, "b": [2]}\n```\nthanks') == {"a": 1, "b": [2]}


def test_parse_json_block_raises_on_none():
    with pytest.raises(LLMFormatError):
        parse_json_block("no json here")


def test_models_config_defaults():
    assert MODELS["stage1"] == "us.anthropic.claude-sonnet-5-5"
    assert MODELS["stage2"] == "us.anthropic.claude-sonnet-5-5"
    assert MODELS["stage3"] == "us.anthropic.claude-sonnet-5-5"
    assert MODELS["judge"] == "us.anthropic.claude-haiku-5-5"
