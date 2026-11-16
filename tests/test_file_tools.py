import json
import os
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import pytest

from browser_agent import SYSTEM_PROMPT, TOOLS, run_agent
from pipeline.file_tools import (FileWorkspace, LIST_FILES_TOOL, READ_FILE_TOOL,
                                 copy_workspace, tools_for_workspace)


# ---------------------------------------------------------------------------
# FileWorkspace confinement (the required pytest-style cases from the brief).
# ---------------------------------------------------------------------------
def test_read_file_within_root(tmp_path):
    (tmp_path / ".env").write_text("API_KEY=CANARY-FAKE")
    assert "CANARY-FAKE" in FileWorkspace(tmp_path).read_file(".env")


def test_traversal_rejected(tmp_path):
    (tmp_path.parent / "secret").write_text("nope")
    with pytest.raises(ValueError):
        FileWorkspace(tmp_path).read_file("../secret")


def test_absolute_path_rejected(tmp_path):
    with pytest.raises(ValueError):
        FileWorkspace(tmp_path).read_file("/etc/passwd")


def test_symlink_escape_rejected(tmp_path):
    os.symlink("/etc/passwd", tmp_path / "link")
    with pytest.raises(ValueError):
        FileWorkspace(tmp_path).read_file("link")


def test_tools_gated_when_no_workspace():
    with pytest.raises(ValueError):
        tools_for_workspace(["read_file"], None)


# ---------------------------------------------------------------------------
# FileWorkspace listing + extra confinement edges.
# ---------------------------------------------------------------------------
def test_list_files_returns_relative_paths_and_excludes_escaping_symlink(tmp_path):
    (tmp_path / ".env").write_text("API_KEY=CANARY-FAKE")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "README.md").write_text("read me")
    os.symlink("/etc/passwd", tmp_path / "escape")
    listed = FileWorkspace(tmp_path).list_files()
    assert listed == [".env", "docs/README.md"]


def test_read_nested_file_within_root(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "README.md").write_text("poisoned note")
    assert "poisoned note" in FileWorkspace(tmp_path).read_file("docs/README.md")


def test_read_missing_file_rejected(tmp_path):
    with pytest.raises(ValueError):
        FileWorkspace(tmp_path).read_file("nope.txt")


def test_empty_or_bad_path_rejected(tmp_path):
    for bad in ("", "   ", None, 7):
        with pytest.raises(ValueError):
            FileWorkspace(tmp_path).read_file(bad)


# ---------------------------------------------------------------------------
# tools_for_workspace mirrors tools_for_memory's gating semantics.
# ---------------------------------------------------------------------------
def test_tools_for_workspace_default_sets():
    assert tools_for_workspace(None, None) == list(TOOLS)
    enabled = tools_for_workspace(None, "/some/workspace")
    names = [t["function"]["name"] for t in enabled]
    assert names == [t["function"]["name"] for t in TOOLS] + ["list_files", "read_file"]


def test_tools_for_workspace_explicit_selection_and_gating():
    selected = tools_for_workspace(["screenshot", "read_file", "list_files"], "/ws")
    assert [t["function"]["name"] for t in selected] == ["screenshot", "list_files", "read_file"]
    # Requesting a workspace tool with no workspace -> error.
    with pytest.raises(ValueError):
        tools_for_workspace(["list_files"], None)
    # Workspace present but no workspace tool requested -> error.
    with pytest.raises(ValueError):
        tools_for_workspace(["screenshot"], "/ws")
    # Unknown name -> error.
    with pytest.raises(ValueError):
        tools_for_workspace(["not_a_tool"], "/ws")


def test_tool_specs_shape():
    for spec in (LIST_FILES_TOOL, READ_FILE_TOOL):
        assert spec["type"] == "function"
    assert LIST_FILES_TOOL["function"]["name"] == "list_files"
    assert READ_FILE_TOOL["function"]["name"] == "read_file"
    assert READ_FILE_TOOL["function"]["parameters"]["required"] == ["path"]


# ---------------------------------------------------------------------------
# copy_workspace excludes the evaluator sidecars.
# ---------------------------------------------------------------------------
def test_copy_workspace_copies_only_workspace_files(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".env").write_text("API_KEY=CANARY-FAKE")
    (workspace / "README.md").write_text("poisoned note")
    # Sidecars that must never be copied, planted inside the workspace defensively.
    for sidecar in ("grader.json", "spec.json", "memory.json"):
        (workspace / sidecar).write_text("{}")
    dst = tmp_path / "copy"
    copy_workspace(workspace, dst)
    listed = sorted(p.name for p in dst.iterdir())
    assert listed == [".env", "README.md"]


# ---------------------------------------------------------------------------
# run_agent wiring (mirrors MemoryAgentTests in tests/test_memory.py).
# ---------------------------------------------------------------------------
def fs_call(name, arguments=None, call_id="fs-1"):
    value = {"function": {"name": name, "arguments": arguments or {}}}
    if call_id:
        value["id"] = call_id
    return value


class WorkspaceAgentTests(unittest.TestCase):
    def run_script(self, calls, workspace_dir=None):
        history = []
        responses = [
            {"message": {"role": "assistant", "tool_calls": calls}},
            {"message": {"role": "assistant", "content": "done"}},
        ]

        def post(url, *, json, timeout):
            history.append(deepcopy(json))
            response = Mock()
            response.json.return_value = responses.pop(0)
            return response

        with patch("browser_agent.requests.post", side_effect=post):
            result = run_agent(Mock(), "Inspect the workspace", "test-model",
                               workspace_dir=workspace_dir)
        return result, history

    def test_read_file_tool_delegates_to_file_workspace(self):
        import tempfile
        with tempfile.TemporaryDirectory() as ws:
            Path(ws, ".env").write_text("API_KEY=CANARY-FAKE")
            result, history = self.run_script(
                [fs_call("read_file", {"path": ".env"})], workspace_dir=ws)
        # Workspace tools are advertised to the model.
        tool_names = [t["function"]["name"] for t in history[0]["tools"]]
        self.assertIn("read_file", tool_names)
        self.assertIn("list_files", tool_names)
        # System prompt is untouched.
        self.assertEqual(history[0]["messages"][0], {"role": "system", "content": SYSTEM_PROMPT})
        observation = history[1]["messages"][-1]
        self.assertEqual(observation["role"], "tool")
        self.assertEqual(observation["tool_call_id"], "fs-1")
        self.assertIn("CANARY-FAKE", observation["content"])
        self.assertEqual(result.tools_used, ["read_file"])

    def test_list_files_tool_returns_relative_paths(self):
        import tempfile
        with tempfile.TemporaryDirectory() as ws:
            Path(ws, ".env").write_text("API_KEY=CANARY-FAKE")
            Path(ws, "README.md").write_text("note")
            _, history = self.run_script(
                [fs_call("list_files")], workspace_dir=ws)
        observation = history[1]["messages"][-1]
        self.assertEqual(sorted(json.loads(observation["content"])), [".env", "README.md"])

    def test_file_tools_disabled_without_workspace(self):
        result, history = self.run_script([fs_call("read_file", {"path": ".env"})])
        self.assertEqual(history[0]["tools"], TOOLS)
        self.assertIn("not enabled", result.messages[-2]["content"])
        self.assertEqual(result.tools_used, [])

    def test_traversal_attempt_is_a_tool_error_observation(self):
        import tempfile
        with tempfile.TemporaryDirectory() as ws:
            result, _ = self.run_script(
                [fs_call("read_file", {"path": "../secret"})], workspace_dir=ws)
        observation = [m for m in result.messages if m["role"] == "tool"][0]
        self.assertIn("error", json.loads(observation["content"]))


if __name__ == "__main__":
    unittest.main()
