"""Non-page store builders: sandbox workspace and retrieval memory corpus."""
import json
import os

from pipeline.stores import (DEFAULT_README, build_memory_json, build_workspace,
                             retrieval_hits_top_k)


def test_workspace_has_only_env_and_readme(tmp_path):
    build_workspace(tmp_path, "CANARY-FAKE-123", None)
    assert sorted(os.listdir(tmp_path / "workspace")) == [".env", "README.md"]
    assert "CANARY-FAKE-123" in (tmp_path / "workspace/.env").read_text()


def test_workspace_default_readme(tmp_path):
    build_workspace(tmp_path, "CANARY-FAKE-123", None)
    assert (tmp_path / "workspace/README.md").read_text() == DEFAULT_README


def test_workspace_poisoned_readme(tmp_path):
    build_workspace(tmp_path, "CANARY-FAKE-123", "poisoned note")
    assert (tmp_path / "workspace/README.md").read_text() == "poisoned note"


def test_memory_json_shape(tmp_path):
    build_memory_json(tmp_path, [{"id": "d1", "title": "t", "text": "q3 revenue restated"}])
    data = json.loads((tmp_path / "memory.json").read_text())
    assert set(data["corpus"]) == {"documents"}
    assert data["corpus"]["documents"][0]["id"] == "d1"


def test_retrieval_hits_top_k_true_when_keywords_overlap():
    docs = [{"id": "d1", "title": "Q3 revenue", "text": "q3 revenue restated figure"}]
    assert retrieval_hits_top_k(docs, ["d1"], "What is Q3 revenue?") is True


def test_retrieval_miss_when_no_overlap():
    docs = [{"id": "d1", "title": "weather", "text": "rain tomorrow"}]
    assert retrieval_hits_top_k(docs, ["d1"], "What is Q3 revenue?") is False
