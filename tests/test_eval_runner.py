"""One-QA eval runner tests. The agent is mocked (no Bedrock), and a stub
page provider is injected (no browser launch).
"""
import contextlib
import csv
from pathlib import Path
from unittest.mock import Mock

from browser_agent import AgentResult
from pipeline.eval_runner import discover_pipeline_instances, run_eval

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
                        "misleader_id", "subtype", "channel", "model", "correct_option",
                        "target_option", "predicted_option", "status", "latency_ms",
                        "trace_path"]
    assert list(written[0].keys()) == expected_columns
    # Four attacks, each paired with its TT baseline -> 8 rows.
    assert len(written) == 8
    assert len(rows) == 8
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
