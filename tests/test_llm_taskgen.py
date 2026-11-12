"""Tests for llm_taskgen: the A-D answer schema, bait rules, gates and the few-shot examples.

Run from the repo root: python -m unittest tests.test_llm_taskgen -v
"""
import json
import unittest
from pathlib import Path

import pandas as pd

from llm_taskgen import core
from llm_taskgen.answer import grade_mcq, parse_letter
from llm_taskgen import examples
from llm_taskgen.examples import build

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "datasets"
COMMITTED = ROOT / "tasks/llm_examples/task-attack-examples.json"


class AnswerSchemaTests(unittest.TestCase):
    def test_tool_letter_wins(self):
        self.assertEqual(parse_letter("ANSWER: B", tool_letter="c"), ("C", "tool"))

    def test_last_answer_line(self):
        self.assertEqual(parse_letter("ANSWER: A\nOn reflection...\nANSWER: D"), ("D", "answer_line"))

    def test_markdown_bold_is_accepted(self):
        self.assertEqual(parse_letter("The tallest bar is 2020.\n**ANSWER: B**"), ("B", "answer_line"))

    def test_parenthesised_letter(self):
        self.assertEqual(parse_letter("ANSWER: (C)."), ("C", "answer_line"))

    def test_only_the_last_line_counts(self):
        self.assertEqual(parse_letter("ANSWER: B\nWait, on reflection it is C."), (None, "unscored"))
        self.assertEqual(parse_letter("ANSWER: B\nANSWER: E"), (None, "unscored"))

    def test_tolerated_formatting(self):
        for reply in ["Answer: b", "### ANSWER: B", "> ANSWER: B", "ANSWER : B", "_ANSWER: B_"]:
            self.assertEqual(parse_letter(reply), ("B", "answer_line"), reply)

    def test_rejected_formatting(self):
        for reply in ["ANSWER: (B", "ANSWER: B (2nd Class)", "ANSWER: B or C"]:
            self.assertEqual(parse_letter(reply), (None, "unscored"), reply)

    def test_unscored_without_schema(self):
        for reply in ["B", "The answer is B", "ANSWER: E", "answer: b is likely", "", None]:
            self.assertEqual(parse_letter(reply), (None, "unscored"), reply)
        self.assertEqual(parse_letter("", tool_letter=""), (None, "unscored"))

    def test_grade_mcq(self):
        self.assertEqual(grade_mcq("ANSWER: D", "D"), ("true", "D"))
        self.assertEqual(grade_mcq("ANSWER: A", "D"), ("false", "A"))
        self.assertEqual(grade_mcq("D", "D"), ("needs_review", ""))

    def test_runner_uses_mcq_grader(self):
        from run_attack_suite import grade
        self.assertEqual(grade("Looks like D.\nANSWER: D", "D", "mcq"), ("true", "D"))
        # the existing A-C 'choice' path is unchanged
        self.assertEqual(grade("B", "B", "choice"), ("true", "B"))


class BaitRuleTests(unittest.TestCase):
    def opts(self, values, tags):
        return [{"letter": l, "value": v, "text": str(v), "misreading": t}
                for l, v, t in zip("ABCD", values, tags)]

    def test_runner_up_first(self):
        task = {"options": self.opts([5, 9, 6, 1], ["runner_up", None, "x", "y"])}
        self.assertEqual(core.tm_bait(task)[0]["letter"], "A")

    def test_nearest_numeric(self):
        task = {"options": self.opts([10, 14, 7, 30], [None, "a", "b", "c"])}
        self.assertEqual(core.tm_bait(task)[0]["letter"], "C")

    def test_sign_flip_for_text(self):
        task = {"options": [{"letter": "A", "value": "down", "text": "down", "misreading": None},
                            {"letter": "B", "value": "up", "text": "up", "misreading": "sign_flip"},
                            {"letter": "C", "value": "flat", "text": "flat", "misreading": "flattened"},
                            {"letter": "D", "value": "peak", "text": "peak", "misreading": "shape"}]}
        self.assertEqual(core.tm_bait(task)[0]["letter"], "B")

    def test_numpy_numbers_use_nearest_rule(self):
        import numpy as np
        task = {"options": self.opts([np.int64(10), np.int64(14), np.int64(7), np.int64(30)], [None, "a", "b", "c"])}
        self.assertEqual(core.tm_bait(task), (task["options"][2], "nearest_numeric"))

    def test_no_rule_raises_gate_error(self):
        task = {"options": [{"letter": l, "value": l, "text": l, "misreading": t}
                            for l, t in zip("ABCD", [None, "a", "b", "c"])]}
        with self.assertRaises(core.GateError):
            core.tm_bait(task)

    def test_unknown_primitive_raises_gate_error(self):
        with self.assertRaises(core.GateError):
            core.item(task_id="x", primitive="Cluster")

    def test_lettering_balances_truth(self):
        L = core.Lettering(1)
        positions = []
        for _ in range(8):
            opts = L.assign([{"misreading": None}] + [{"misreading": t} for t in "xyz"])
            positions.append(next(o["letter"] for o in opts if o["misreading"] is None))
        self.assertEqual(sorted(positions), sorted("ABCD" * 2))


class ExampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = build(DATASETS)
        cls.tasks = {t["task_id"]: t for c in cls.doc["examples"] for t in c["tasks"]}
        cls.specs = {t["task_id"]: c["chart"] for c in cls.doc["examples"] for t in c["tasks"]}

    def truth(self, tid):
        t = self.tasks[tid]
        return next(o["text"] for o in t["options"] if o["letter"] == t["answer_letter"])

    def bait(self, tid, technique):
        t = self.tasks[tid]
        a = next(a for a in t["attacks"] if a["technique"] == technique)
        return next(o["text"] for o in t["options"] if o["letter"] == a["bait_letter"])

    def test_committed_file_matches_build(self):
        self.assertEqual(json.loads(json.dumps(self.doc, default=float)), json.loads(COMMITTED.read_text()))

    def test_shape(self):
        self.assertEqual(len(self.tasks), 10)
        self.assertEqual({c["chart"]["chart_type"] for c in self.doc["examples"]}, set(core.REQUIRED_CHANNELS))
        self.assertEqual(sum(len(t["attacks"]) for t in self.tasks.values()), 21)

    def test_answers_recomputed_independently(self):
        h = pd.read_csv(DATASETS / "heart_disease_uci.csv")
        cle = h[h.dataset == "Cleveland"]
        male_max = cle[cle.sex == "Male"].sort_values("oldpeak").iloc[-1]
        self.assertEqual(self.truth("ex_scatter_heart_extremum_size"), f"Age {male_max.age}")
        self.assertLess(cle.age.corr(cle.thalch), -0.3)
        t = pd.read_csv(DATASETS / "titanicmaster.tsv", sep="\t")
        f3 = t[(t.Class == "3rd Class Passenger") & (t.Gender == "Female")].Survived.mean() * 100
        self.assertEqual(self.truth("ex_bar_titanic_retrieve"), f"{round(f3)}%")
        n = pd.read_csv(DATASETS / "netflix_titles.csv")
        self.assertEqual(self.truth("ex_stacked_netflix_total"), str((n.release_year == 2019).sum()))
        tv = n[(n.type == "TV Show") & n.release_year.between(2015, 2021)].release_year.value_counts()
        self.assertEqual(self.truth("ex_stacked_netflix_tv_peak"), str(tv.idxmax()))
        c = pd.read_csv(DATASETS / "climate.csv")
        de = c[(c.country == "Germany") & c.year.between(2000, 2022)].consumption_co2_per_capita
        self.assertEqual(self.truth("ex_line_climate_range_style"), f"{round(de.max() - de.min(), 1)} t")

    def test_mt_close_colors_bait_is_what_the_misleader_produces(self):
        h = pd.read_csv(DATASETS / "heart_disease_uci.csv")
        cle = h[h.dataset == "Cleveland"]
        largest_overall = cle.sort_values("oldpeak").iloc[-1]
        self.assertNotEqual(largest_overall.sex, "Male")
        self.assertEqual(self.bait("ex_scatter_heart_extremum_size", "close_colors"), f"Age {largest_overall.age}")

    def test_every_attack_has_a_registered_technique_and_wrong_bait(self):
        for t in self.tasks.values():
            for a in t["attacks"]:
                self.assertIn(a["technique"], core.TECHNIQUES)
                self.assertNotEqual(a["bait_letter"], t["answer_letter"])


class GateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = build(DATASETS)

    def pick(self, tid):
        """A fresh, unvalidated copy of one example task (with its recompute function)."""
        L = core.Lettering(examples.SEED)
        for fn in (examples.scatter_heart, examples.bar_titanic, examples.line_climate,
                   examples.stacked_netflix, examples.heatmap_heart):
            spec, tasks = fn(DATASETS, L)
            for t in tasks:
                if t["task_id"] == tid:
                    core.fill_tm(t)
                    return spec, t
        raise KeyError(tid)

    def test_valid_task_passes(self):
        core.validate_task(*self.pick("ex_bar_titanic_retrieve"))

    def test_field_not_on_chart_is_rejected(self):
        spec, t = self.pick("ex_bar_titanic_retrieve")
        t["fields_referenced"].append("Age")
        with self.assertRaises(core.GateError):
            core.validate_task(spec, t)

    def test_answer_in_question_is_rejected(self):
        spec, t = self.pick("ex_bar_titanic_retrieve")
        t["question"] += " (hint: 49%)"
        with self.assertRaises(core.GateError):
            core.validate_task(spec, t)

    def test_unknown_technique_is_rejected(self):
        spec, t = self.pick("ex_bar_titanic_retrieve")
        t["attacks"][0]["technique"] = "invented_trick"
        with self.assertRaises(core.GateError):
            core.validate_task(spec, t)

    def test_bait_equal_to_truth_is_rejected(self):
        spec, t = self.pick("ex_bar_titanic_retrieve")
        t["attacks"][0]["bait_letter"] = t["answer_letter"]
        with self.assertRaises(core.GateError):
            core.validate_task(spec, t)

    def test_wrong_recompute_is_rejected(self):
        spec, t = self.pick("ex_bar_titanic_retrieve")
        t["recompute"] = lambda rows: "50%"
        with self.assertRaises(core.GateError):
            core.validate_task(spec, t)

    def test_missing_required_channel_is_rejected(self):
        spec, t = self.pick("ex_scatter_heart_correlate")
        del spec["encodings"]["size"]
        with self.assertRaises(core.GateError):
            core.check_channels_exercised(spec, [t])

    def test_unexercised_channel_is_rejected(self):
        spec, t = self.pick("ex_scatter_heart_correlate")  # uses x and y only
        with self.assertRaises(core.GateError):
            core.check_channels_exercised(spec, [t])

    def test_missing_recompute_is_rejected(self):
        spec, t = self.pick("ex_bar_titanic_retrieve")
        del t["recompute"]
        with self.assertRaises(core.GateError):
            core.validate_task(spec, t)

    def test_filter_not_in_title_is_rejected(self):
        spec, t = self.pick("ex_bar_titanic_retrieve")
        spec["filters"]["Joined"] = "Southampton"
        with self.assertRaises(core.GateError):
            core.validate_task(spec, t)

    def test_named_value_not_plotted_is_rejected(self):
        spec, t = self.pick("ex_bar_titanic_retrieve")
        spec["data"] = [r for r in spec["data"] if r["class"] != "3rd Class"]
        with self.assertRaises(core.GateError):
            core.validate_task(spec, t)

    def test_claim_with_truth_is_rejected(self):
        spec, t = self.pick("ex_bar_titanic_retrieve")
        tm = next(a for a in t["attacks"] if a["channel"] == "TM")
        tm["claim_text"] += " Earlier estimates said 49%."
        with self.assertRaises(core.GateError):
            core.validate_task(spec, t)

    def test_close_options_are_rejected(self):
        opts = [{"text": str(v), "value": v} for v in (10, 12, 30, 40)]
        with self.assertRaises(core.GateError):
            core.check_options(opts, min_gap=5)


if __name__ == "__main__":
    unittest.main()
