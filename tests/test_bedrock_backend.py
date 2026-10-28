import base64
import io
import unittest
from unittest.mock import patch

from PIL import Image

import bedrock_backend
from bedrock_backend import CACHE_POINT, MAX_IMAGE_SIDE, image_bytes, to_converse
from browser_agent import TOOLS, run_agent


def png(width, height):
    out = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(out, format="PNG")
    return base64.b64encode(out.getvalue()).decode("ascii")


class ToConverseTest(unittest.TestCase):
    def test_tool_round_trip_and_alternation(self):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "a", "function": {"name": "screenshot", "arguments": {}}},
                {"id": "b", "function": {"name": "dom", "arguments": '{"selector": "svg"}'}}]},
            {"role": "tool", "tool_name": "screenshot", "tool_call_id": "a", "content": "shot",
             "images": [png(10, 10)]},
            {"role": "tool", "tool_name": "dom", "tool_call_id": "b", "content": "<svg/>"},
            {"role": "user", "content": "repair"},
        ]
        system, converted, tool_config = to_converse(messages, TOOLS, cache=False)
        self.assertEqual(system, [{"text": "sys"}])
        self.assertEqual([m["role"] for m in converted], ["user", "assistant", "user"])
        uses = [b["toolUse"] for b in converted[1]["content"]]
        self.assertEqual([u["toolUseId"] for u in uses], ["a", "b"])
        self.assertEqual(uses[1]["input"], {"selector": "svg"})
        results = [b["toolResult"] for b in converted[2]["content"] if "toolResult" in b]
        self.assertEqual([r["toolUseId"] for r in results], ["a", "b"])
        self.assertIn("image", results[0]["content"][1])
        self.assertEqual(converted[2]["content"][-1], {"text": "repair"})
        self.assertEqual(len(tool_config["tools"]), len(TOOLS))

    def test_calls_without_ids_get_matching_ids(self):
        messages = [{"role": "user", "content": "q"},
                    {"role": "assistant", "content": "", "tool_calls": [
                        {"function": {"name": "screenshot", "arguments": {}}}]},
                    {"role": "tool", "tool_name": "screenshot", "content": "shot"}]
        _, converted, _ = to_converse(messages, TOOLS, cache=False)
        use_id = converted[1]["content"][0]["toolUse"]["toolUseId"]
        self.assertEqual(converted[2]["content"][0]["toolResult"]["toolUseId"], use_id)

    def test_images_outside_tool_results(self):
        messages = [{"role": "user", "content": "q"},
                    {"role": "assistant", "content": "", "tool_calls": [
                        {"id": "a", "function": {"name": "screenshot", "arguments": {}}},
                        {"id": "b", "function": {"name": "dom", "arguments": {}}}]},
                    {"role": "tool", "tool_call_id": "a", "content": "shot", "images": [png(10, 10)]},
                    {"role": "tool", "tool_call_id": "b", "content": "<svg/>"}]
        _, converted, _ = to_converse(messages, TOOLS, cache=False, tool_images=False)
        blocks = converted[2]["content"]
        self.assertEqual([next(iter(b)) for b in blocks], ["toolResult", "toolResult", "image"])
        self.assertEqual(len(blocks[0]["toolResult"]["content"]), 1)
        self.assertIn("image for tool call a", blocks[0]["toolResult"]["content"][0]["text"])

    def test_cache_points(self):
        system, converted, tool_config = to_converse(
            [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}], TOOLS, cache=True)
        self.assertEqual(system[-1], CACHE_POINT)
        self.assertEqual(tool_config["tools"][-1], CACHE_POINT)
        self.assertEqual(converted[-1]["content"][-1], CACHE_POINT)

    def test_large_images_are_downscaled(self):
        with Image.open(io.BytesIO(image_bytes(png(3000, 1000)))) as image:
            self.assertEqual(max(image.size), MAX_IMAGE_SIDE)
        small = png(960, 720)
        self.assertEqual(image_bytes(small), base64.b64decode(small))


class RunAgentBedrockTest(unittest.TestCase):
    def test_final_answer_and_usage(self):
        replies = iter([
            ({"role": "assistant", "content": "", "tool_calls": [
                {"id": "t1", "function": {"name": "wait", "arguments": {"ms": 1}}}]},
             {"input": 10, "output": 2, "cache_read": 0, "cache_write": 100, "stop_reason": "tool_use"}),
            ({"role": "assistant", "content": "42"},
             {"input": 5, "output": 1, "cache_read": 100, "cache_write": 0, "stop_reason": "end_turn"}),
        ])
        page = unittest.mock.Mock()
        with patch.object(bedrock_backend, "chat", side_effect=lambda *a, **k: next(replies)):
            result = run_agent(page, "q", "us.anthropic.claude-sonnet-5-5", console_logs=[],
                               backend="bedrock")
        self.assertEqual((result.answer, result.stop_reason, result.steps), ("42", "final", 2))
        self.assertEqual(result.usage, {"input": 15, "output": 3, "cache_read": 100, "cache_write": 100})
        self.assertEqual(result.messages[3]["tool_call_id"], "t1")

    def test_request_error(self):
        with patch.object(bedrock_backend, "chat", side_effect=bedrock_backend.BedrockError("Bedrock x")):
            result = run_agent(unittest.mock.Mock(), "q", "m", console_logs=[], backend="bedrock")
        self.assertEqual((result.stop_reason, result.error), ("request_error", "Bedrock x"))


if __name__ == "__main__":
    unittest.main()
