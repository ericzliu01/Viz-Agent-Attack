"""Tests for the task instance spec schema and served/grader split."""
import json

from pipeline.specs import (
    CELLS,
    DIRECTIONS,
    InstanceSpec,
    from_jsonl_line,
    spec_hash,
    split_grader,
    to_jsonl_line,
)


def make_spec(**overrides):
    """Build a fully-populated InstanceSpec, overriding any field by name."""
    fields = dict(
        instance_id="q1__ct_bar__TT",
        base_id="q1__ct_bar",
        question_id="q1",
        cell="TT",
        direction="same",
        csv="cars.csv",
        library="vega-lite",
        chart_type="bar",
        task_type="retrieve_value",
        question="What is the value?",
        options=["a", "b", "c", "d"],
        correct_index=0,
        sql="SELECT 1;",
        description="a bar chart",
        charts=[{"id": "chart_0", "spec": {"mark": "bar"}}],
        misleader=None,
        trap=None,
    )
    fields.update(overrides)
    return InstanceSpec(**fields)


def test_split_grader_removes_answer_fields():
    spec = make_spec(correct_index=2, options=["a", "b", "c", "d"])
    served, grader = split_grader(spec)
    assert "correct_index" not in json.dumps(served)
    assert grader["correct_index"] == 2 and grader["options"] == ["a", "b", "c", "d"]


def test_trap_target_only_in_grader():
    spec = make_spec(trap={"family": "perception", "channel": "css_hidden",
                           "payload": "x", "target_option": "b",
                           "extra_wrong_option": "d"})
    served, grader = split_grader(spec)
    assert "target_option" not in json.dumps(served)
    assert grader["trap"]["target_option"] == "b"


def test_roundtrip_jsonl():
    spec = make_spec()
    assert from_jsonl_line(to_jsonl_line(spec)) == spec


def test_spec_hash_stable_across_key_order():
    assert spec_hash(make_spec()) == spec_hash(make_spec())


def test_served_keeps_options_but_drops_sql():
    spec = make_spec(sql="SELECT secret FROM t;")
    served, grader = split_grader(spec)
    assert served["options"] == ["a", "b", "c", "d"]
    assert "sql" not in served
    assert grader["sql"] == "SELECT secret FROM t;"


def test_misleader_wrong_option_only_in_grader():
    spec = make_spec(misleader={"family": "axis", "wrong_option": "c",
                                "note": "truncated y-axis"})
    served, grader = split_grader(spec)
    assert "wrong_option" not in json.dumps(served)
    assert served["misleader"]["family"] == "axis"
    assert grader["misleader"]["wrong_option"] == "c"


def test_document_ids_and_attack_target_stripped_from_served():
    spec = make_spec(trap={"family": "memory", "poisoned_document_ids": ["d1"],
                           "attack_target": "b", "target_option": "b"})
    served, grader = split_grader(spec)
    dumped = json.dumps(served)
    assert "poisoned_document_ids" not in dumped
    assert "attack_target" not in dumped
    assert grader["trap"]["poisoned_document_ids"] == ["d1"]
    assert grader["trap"]["attack_target"] == "b"


def test_cells_and_directions_constants():
    assert CELLS == ("TT", "MT", "TM", "MM")
    assert DIRECTIONS == ("same", "different", "none")
