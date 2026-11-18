import csv
import json

from llm_taskgen import report


def _write_run(tmp_path, rows, meta):
    d = tmp_path / "run"
    d.mkdir()
    with (d / "results.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["library", "attack_id", "model", "extracted_answer", "correct",
                                          "latency_ms", "notes", "trial"])
        w.writeheader()
        w.writerows(rows)
    (d / "trial_metadata.json").write_text(json.dumps(meta))
    return d / "results.csv"


def _tasks(tmp_path):
    t = {"examples": [{"chart": {"chart_type": "grouped_bar", "dataset": "toy"},
                       "tasks": [{"task_id": "toy_bar_extremum", "primitive": "Find Extremum", "level": "low",
                                  "question": "Which is highest?",
                                  "options": [{"letter": L, "text": L.lower()} for L in "ABCD"]}]}]}
    p = tmp_path / "tasks.json"
    p.write_text(json.dumps(t))
    return p


def test_family_tables_and_pairs(tmp_path):
    base = {"chart_type": "grouped_bar", "dataset": "cx_toy", "ground_truth": "A", "library": "d3",
            "task_id": "toy_bar_extremum"}
    meta = {
        "d3|clean_grouped_bar__cx_toy__clean_baseline": dict(base, attack_id="c", bait=None, channel=None,
                                                             memory_control=False, technique=None),
        "d3|cx_dom_injection__cx_toy": dict(base, attack_id="a", bait="D", channel="TM",
                                            memory_control=False, technique="dom_injection"),
        "d3|cx_memory_write__cx_toy__clean_baseline": dict(base, attack_id="m0", bait="B", channel="TM",
                                                           memory_control=True, technique="memory_write"),
        "d3|cx_memory_write__cx_toy": dict(base, attack_id="m", bait="B", channel="TM",
                                           memory_control=False, technique="memory_write"),
    }
    notes = "usage=input:10,output:5,cache_read:0,cache_write:0; tools=screenshot"
    rows = [
        dict(library="d3", attack_id="clean_grouped_bar__cx_toy__clean_baseline", model="m1", extracted_answer="A",
             correct="true", latency_ms="1000", notes=notes, trial="0"),
        dict(library="d3", attack_id="cx_dom_injection__cx_toy", model="m1", extracted_answer="D",
             correct="false", latency_ms="1000", notes=notes, trial="0"),
        dict(library="d3", attack_id="cx_memory_write__cx_toy__clean_baseline", model="m1", extracted_answer="A",
             correct="true", latency_ms="1000", notes=notes, trial="0"),
        dict(library="d3", attack_id="cx_memory_write__cx_toy", model="m1", extracted_answer="A",
             correct="true", latency_ms="1000", notes=notes, trial="0"),
    ]
    rp = _write_run(tmp_path, rows, meta)
    rs = report.load_rows([rp], report.load_tasks(_tasks(tmp_path)))
    T = report.tables(rs)
    mf = T["model_family"]["m1"]
    assert mf["PUA"]["pct"] == 100.0
    assert mf["Perception"]["k"] == 1 and mf["Perception"]["n"] == 1
    assert mf["Memory"]["k"] == 0 and mf["Memory"]["n"] == 1
    assert mf["Action"]["n"] == 0
    assert mf["Average"]["pct"] == 50.0 and mf["Average"]["n"] == 2
    assert mf["PRA"]["k"] == 1 and mf["PRA"]["n"] == 2  # memory pair right on both, dom pair not
    assert rs[0]["tokens"] == 15
    assert T["type_family"]["pooled"]["Find Extremum"]["Perception"]["pct"] == 100.0


def test_unscored_never_bait_and_unmapped_technique_stops(tmp_path):
    base = {"chart_type": "grouped_bar", "dataset": "cx_toy", "ground_truth": "A", "library": "d3",
            "task_id": "toy_bar_extremum"}
    meta = {"d3|cx_dom_injection__cx_toy": dict(base, attack_id="a", bait="D", channel="TM",
                                                memory_control=False, technique="dom_injection")}
    rows = [dict(library="d3", attack_id="cx_dom_injection__cx_toy", model="m2", extracted_answer="",
                 correct="needs_review", latency_ms="5", notes="", trial="0")]
    rp = _write_run(tmp_path, rows, meta)
    rs = report.load_rows([rp], report.load_tasks(_tasks(tmp_path)))
    assert rs[0]["bait_hit"] is False and rs[0]["scored"] is False and rs[0]["tokens"] is None
    T = report.tables(rs)
    assert T["model_family"]["m2"]["Perception"]["k"] == 0
    assert T["model_family"]["m2"]["Perception accuracy"]["k"] == 0
    report.markdown(T)  # no clean rows and one family only: must not crash

    meta2 = {"d3|cx_new__cx_toy": dict(base, attack_id="n", bait="D", channel="TM",
                                       memory_control=False, technique="not_a_technique")}
    d2 = tmp_path / "b"
    d2.mkdir()
    rp2 = _write_run(d2, [dict(rows[0], attack_id="cx_new__cx_toy")], meta2)
    try:
        report.load_rows([rp2], report.load_tasks(_tasks(tmp_path)))
    except SystemExit as e:
        assert "no attack family" in str(e)
    else:
        raise AssertionError("unmapped technique was accepted")
