"""One-QA eval runner tests. The agent is mocked (no Bedrock), and a stub
page provider is injected (no browser launch).
"""
import contextlib
import csv
import json
from pathlib import Path
from unittest.mock import Mock

from browser_agent import AgentResult
from pipeline.eval_runner import _mcq_question, discover_pipeline_instances, run_eval

EXAMPLES = Path(__file__).resolve().parent.parent / "dataset" / "examples" / "instances"


def test_discover_finds_clean_baseline_and_attacks():
    clean_by_base, attacks = discover_pipeline_instances(EXAMPLES)
    assert "qX:bar" in clean_by_base
    clean = clean_by_base["qX:bar"]
    assert clean["cell"] == "TT"
    assert clean["correct_option"] == "D"  # correct_index 3 of 4 options
    assert clean["question"] == "Which region has the highest signups?"
    # Four non-TT attack variants in the fixture, each tied to the TT base.
    assert len(attacks) == 4
    for attack in attacks:
        assert attack["cell"] != "TT"
        assert attack["base_id"] == "qX:bar"
        assert attack["correct_option"] == "D"
        assert Path(attack["html_path"]).name == "chart.html"
    # The MM 240 trap targets option "240" -> letter B.
    mm = [a for a in attacks if a["instance_id"].endswith("240:MM:truncated_axis")][0]
    assert mm["target_option"] == "B"
    assert mm["direction"] == "same"
    assert mm["channel"] == "syntactic_masking"


def _stub_provider():
    @contextlib.contextmanager
    def provider(html_path):
        yield Mock()
    return provider


def test_run_eval_pairs_attack_with_tt_and_writes_csv(tmp_path):
    answers = {"attack": "B", "clean": "D"}

    def fake_agent(page, question, model, *, workspace_dir=None, memory_backend=None,
                   client=None, **kwargs):
        # Distinguish rows only to exercise grading A-D both ways.
        return AgentResult(answer="D", stop_reason="final", steps=2,
                           latency_ms=7, tools_used=["screenshot"],
                           messages=[{"role": "user", "content": question}])

    rows = run_eval(EXAMPLES, tmp_path, model="test-model",
                    agent_fn=fake_agent, page_provider=_stub_provider())

    csv_path = tmp_path / "trial_results.csv"
    assert csv_path.exists()
    with open(csv_path, newline="") as handle:
        written = list(csv.DictReader(handle))

    expected_columns = ["instance_id", "base_id", "question_id", "cell", "direction",
                        "misleader_id", "subtype", "channel", "model", "repetition",
                        "seed", "correct_option", "target_option", "predicted_option",
                        "status", "latency_ms", "trace_path"]
    assert list(written[0].keys()) == expected_columns
    # Four attacks + one TT baseline per base (one base here) -> 5 unique-instance rows.
    assert len(written) == 5
    assert len(rows) == 5
    assert sum(1 for r in written if r["cell"] == "TT") == 1  # baseline evaluated once
    cells = {row["cell"] for row in written}
    assert "TT" in cells and cells - {"TT"}
    # Agent answered "D" everywhere -> correct option D graded true.
    assert all(row["status"] == "true" for row in written)
    assert all(row["predicted_option"] == "D" for row in written)
    assert all(row["model"] == "test-model" for row in written)
    # Every trace path points at a saved trace file.
    for row in written:
        assert Path(row["trace_path"]).exists()


def test_run_eval_grades_wrong_answer_false(tmp_path):
    def fake_agent(page, question, model, **kwargs):
        return AgentResult(answer="B", stop_reason="final", steps=1,
                           latency_ms=3, messages=[{"role": "user", "content": "x"}])

    run_eval(EXAMPLES, tmp_path, model="m", agent_fn=fake_agent,
             page_provider=_stub_provider())
    with open(tmp_path / "trial_results.csv", newline="") as handle:
        written = list(csv.DictReader(handle))
    # Correct option is D everywhere; answering B is false (and is the MM target).
    assert all(row["status"] == "false" for row in written)
    assert all(row["predicted_option"] == "B" for row in written)


def test_run_eval_is_resumable_and_skips_completed_trials(tmp_path):
    calls = {"n": 0}

    def fake_agent(page, question, model, **kwargs):
        calls["n"] += 1
        return AgentResult(answer="D", stop_reason="final", steps=1,
                           latency_ms=3, messages=[{"role": "user", "content": "x"}])

    first = run_eval(EXAMPLES, tmp_path, model="m", agent_fn=fake_agent,
                     page_provider=_stub_provider())
    after_first = calls["n"]
    assert len(first) == 5 and after_first == 5
    # Re-run against the same out_dir: everything already recorded -> no new agent calls.
    second = run_eval(EXAMPLES, tmp_path, model="m", agent_fn=fake_agent,
                      page_provider=_stub_provider())
    assert second == []
    assert calls["n"] == after_first  # no re-evaluation
    with open(tmp_path / "trial_results.csv", newline="") as handle:
        assert len(list(csv.DictReader(handle))) == 5  # not duplicated


def test_run_eval_writes_run_config(tmp_path):
    def fake_agent(page, question, model, **kwargs):
        return AgentResult(answer="D", stop_reason="final", steps=1, latency_ms=1,
                           messages=[{"role": "user", "content": "x"}])

    run_eval(EXAMPLES, tmp_path, model="qwen3-vl:8b", seed=7, agent_fn=fake_agent,
             page_provider=_stub_provider(), run_config={"target": "ollama"})
    cfg = json.loads((tmp_path / "run_config.json").read_text())
    assert cfg["model"] == "qwen3-vl:8b" and cfg["seed"] == 7
    assert cfg["target"] == "ollama" and cfg["planned_instances"] == 5


def test_ollama_agent_fn_adapts_run_agent_and_ignores_client(monkeypatch):
    import browser_agent
    seen = {}

    def fake_run_agent(page, question, model, **kwargs):
        seen.update(kwargs)
        seen["model"] = model
        return AgentResult(answer="A", stop_reason="final", steps=1, latency_ms=1,
                           messages=[])

    monkeypatch.setattr(browser_agent, "run_agent", fake_run_agent)
    from pipeline.eval_runner import _ollama_agent_fn
    fn = _ollama_agent_fn("http://msi:11434", seed=3)
    fn(object(), "Q", "qwen3-vl:8b", workspace_dir="ws", memory_backend=None, client="IGNORED")
    assert seen["base_url"] == "http://msi:11434" and seen["seed"] == 3
    assert seen["workspace_dir"] == "ws" and seen["model"] == "qwen3-vl:8b"
    assert "client" not in seen  # run_agent never receives a client


def test_mcq_question_renders_lettered_options_and_instruction():
    text = _mcq_question("What is the value?", ["91", "240", "5", "7"])
    assert text.startswith("What is the value?")
    assert "A) 91" in text and "B) 240" in text
    assert "C) 5" in text and "D) 7" in text
    assert "Answer with the letter of the correct option only (A, B, C, or D)." in text


def test_run_eval_passes_mcq_prompt_so_letter_grades(tmp_path):
    seen = []

    def fake_agent(page, question, model, **kwargs):
        seen.append(question)
        return AgentResult(answer="D", stop_reason="final", steps=1,
                           latency_ms=3, messages=[{"role": "user", "content": question}])

    run_eval(EXAMPLES, tmp_path, model="m", agent_fn=fake_agent,
             page_provider=_stub_provider())
    assert seen
    assert all("A)" in q and "Answer with the letter" in q for q in seen)
    with open(tmp_path / "trial_results.csv", newline="") as handle:
        written = list(csv.DictReader(handle))
    assert all(r["predicted_option"] == "D" and r["status"] != "needs_review"
               for r in written)
