"""Tests for llm_taskgen.highlevel: compound and high-level (statement) MCQ tasks.

Run from the repo root: python -m unittest tests.test_highlevel -v
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from llm_taskgen import csvgen, highlevel as hl, pages, profile
from llm_taskgen.core import LETTERS, TIER, GateError, Lettering
from tests.test_csvgen import synthetic_csv

ROOT = Path(__file__).resolve().parents[1]


def _tasks(doc):
    return {t["task_id"]: (c["chart"], t) for c in doc["examples"] for t in c["tasks"]}


class LevelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.csv = cls.tmp / "shop.csv"
        cls.raw = synthetic_csv(cls.csv)
        cls.doc = csvgen.build([cls.csv])
        cls.tasks = _tasks(cls.doc)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_all_three_levels_are_generated(self):
        counts = self.doc["level_counts"]
        self.assertTrue(all(counts[x] > 0 for x in hl.LEVELS), counts)

    def test_low_level_tasks_unchanged(self):
        """Adding compound/high tasks must not change the charts or any low-level task."""
        low = csvgen.build([self.csv], levels=("low",))
        lt = _tasks(low)
        for tid, (chart, t) in lt.items():
            self.assertEqual(json.dumps(t, sort_keys=True), json.dumps(self.tasks[tid][1], sort_keys=True))
        self.assertEqual([c["chart"] for c in low["examples"]], [c["chart"] for c in self.doc["examples"]])

    def test_levels_filter(self):
        for want in (("high",), ("low",), ("low", "high"), ("compound",)):
            only = csvgen.build([self.csv], levels=want)
            self.assertTrue(only["examples"])
            self.assertEqual({t["level"] for c in only["examples"] for t in c["tasks"]}, set(want), want)

    def test_chains_are_literature_primitives(self):
        for chart, t in self.tasks.values():
            if t["level"] == "low":
                continue
            self.assertGreaterEqual(len(t["primitive_chain"]), 2, t["task_id"])
            for p in t["primitive_chain"]:
                self.assertIn(p, TIER)
            self.assertEqual(t["tier"], max(TIER[p] for p in t["primitive_chain"]))
            if t["level"] == "high":
                self.assertIn(t["pattern"], hl.BM)

    def test_statement_options_exactly_one_true(self):
        n = 0
        for chart, t in self.tasks.values():
            if t["level"] != "high":
                continue
            n += 1
            self.assertEqual(len(t["options"]), 4)
            res = {o["letter"]: hl.option_holds(o, chart) for o in t["options"]}
            self.assertEqual([k for k, (h, _) in res.items() if h], [t["answer_letter"]], t["task_id"])
            self.assertTrue(all(c for _, c in res.values()), t["task_id"])
            tags = {o["misreading"] for o in t["options"]} - {None}
            self.assertLessEqual(tags, {"flipped_direction", "wrong_ranking", "overgeneralization", "false_exception"})
        self.assertGreater(n, 0)

    def test_high_attacks_target_a_bait_insight(self):
        for chart, t in self.tasks.values():
            if t["level"] != "high":
                continue
            for a in t["attacks"]:
                bait = next(o for o in t["options"] if o["letter"] == a["bait_letter"])
                self.assertEqual(bait["misreading"], "flipped_direction")
                if a["channel"] == "MT":
                    self.assertEqual(a["params"]["title"], bait["text"])
                    self.assertEqual(a["params"]["subtitle"], chart["subtitle"])
                else:
                    self.assertIn(bait["text"], a["claim_text"])

    def test_bar_compare_matches_raw_csv(self):
        chart, t = self.tasks["shop_bar_compare"]
        enc = chart["encodings"]
        xc, gc, yf = enc["x"], enc["group"], enc["y"]
        g1, g2 = chart["category_order"][gc]
        raw = self.raw
        col = yf.split("_", 1)[1]

        def stat(f):
            if yf.startswith("mean_"):
                return f[col].mean()
            if yf.startswith("pct_"):
                pos = profile.profile(self.csv)[0]["columns"][col]["positive"]
                return (f[col].astype(str) == pos).mean() * 100
            return len(f)
        diffs = [stat(raw[(raw[xc].astype(str) == str(x)) & (raw[gc].astype(str) == g1)])
                 - stat(raw[(raw[xc].astype(str) == str(x)) & (raw[gc].astype(str) == g2)])
                 for x in chart["category_order"][xc]]
        k = sum(d > 0 for d in diffs)
        hi, lo = (g1, g2) if 2 * k > len(diffs) else (g2, g1)
        truth = next(o for o in t["options"] if o["misreading"] is None)["text"]
        self.assertIn(f"higher for {csvgen.lab(profile.profile(self.csv)[0], gc)} {hi} than", truth)
        self.assertEqual("every" in truth, k in (0, len(diffs)))

    def test_filter_average_matches_raw_csv(self):
        chart, t = self.tasks["shop_bar_filter_average"]
        enc = chart["encodings"]
        xc, gc, yf = enc["x"], enc["group"], enc["y"]
        (b,) = t["named_values"][gc]
        thr = t["solution"]["threshold"]
        col = yf.split("_", 1)[1]
        vals = []
        for x in chart["category_order"][xc]:
            f = self.raw[(self.raw[xc].astype(str) == str(x)) & (self.raw[gc].astype(str) == b)]
            if yf.startswith("mean_"):
                v = f[col].mean()
            elif yf.startswith("pct_"):
                v = (f[col].astype(str) == profile.profile(self.csv)[0]["columns"][col]["positive"]).mean() * 100
            else:
                v = len(f)
            if csvgen.round_sig(v) > thr:
                vals.append(csvgen.round_sig(v))
        truth = next(o for o in t["options"] if o["misreading"] is None)
        self.assertAlmostEqual(truth["value"], np.mean(vals), delta=abs(np.mean(vals)) * 1e-3)

    def test_pages_carry_level(self):
        out = self.tmp / "pages"
        pages.build(self._write(), out, ["vega-lite"], "cx_")
        meta = json.loads((out / "vega-lite" / "clean_grouped_bar__cx_shop_bar_compare.meta.json").read_text())
        self.assertEqual(meta["level"], "high")
        self.assertEqual(meta["pattern"], "compare populations")
        self.assertIn("Characterize Distribution", meta["primitive_chain"])

    def _write(self):
        p = self.tmp / "tasks.json"
        p.write_text(json.dumps(self.doc, default=profile.to_py))
        return p


def _spec(rows, enc, order, span=100):
    return {"data": rows, "encodings": enc, "category_order": order}


class ClaimTests(unittest.TestCase):
    """evaluate() on hand-made rows."""

    def bar(self, a_vals, b_vals):
        rows = [{"x": f"x{i}", "g": g, "y": v} for i, (va, vb) in enumerate(zip(a_vals, b_vals))
                for g, v in (("A", va), ("B", vb))]
        return _spec(rows, {"x": "x", "group": "g", "y": "y"}, {"x": [f"x{i}" for i in range(len(a_vals))], "g": ["A", "B"]})

    def order(self, q):
        return {"type": "order", "a": {"g": "A"}, "b": {"g": "B"}, "along": "x", "value": "y", "span": 100, "quant": q}

    def test_order_quantifiers(self):
        s = self.bar([50, 60, 70, 80], [10, 20, 30, 40])
        self.assertEqual(hl.evaluate(self.order("every"), s), (True, True))
        self.assertEqual(hl.evaluate(self.order("most_not_all"), s), (False, True))
        s = self.bar([50, 60, 70, 10], [10, 20, 30, 40])
        self.assertEqual(hl.evaluate(self.order("every"), s), (False, True))
        self.assertEqual(hl.evaluate(self.order("most_not_all"), s), (True, True))
        s = self.bar([50, 60, 70, 41], [10, 20, 30, 40])  # one near tie
        self.assertEqual(hl.evaluate(self.order("most_not_all"), s)[1], False)

    def test_gap_max(self):
        s = self.bar([50, 90, 70, 80], [10, 20, 30, 40])
        atom = {"type": "gap_max", "a": {"g": "A"}, "b": {"g": "B"}, "along": "x", "value": "y", "span": 100}
        self.assertEqual(hl.evaluate({**atom, "at": "x1"}, s), (True, True))
        self.assertEqual(hl.evaluate({**atom, "at": "x0"}, s), (False, True))

    def test_trend_and_end(self):
        rows = [{"yr": y, "c": c, "v": v} for y, a, b in zip(range(2000, 2006), [10, 20, 30, 40, 50, 60], [30, 30, 30, 30, 30, 30])
                for c, v in (("P", a), ("Q", b))]
        s = _spec(rows, {"x": "yr", "color": "c", "y": "v"}, {"c": ["P", "Q"]})
        base = {"along": "yr", "value": "v", "span": 60}
        self.assertEqual(hl.evaluate({**base, "type": "trend", "a": {"c": "P"}, "dir": "rose"}, s), (True, True))
        self.assertEqual(hl.evaluate({**base, "type": "trend", "a": {"c": "P"}, "dir": "fell"}, s), (False, True))
        self.assertEqual(hl.evaluate({**base, "type": "at_end", "a": {"c": "P"}, "b": {"c": "Q"}}, s), (True, True))
        self.assertEqual(hl.evaluate({**base, "type": "every_step", "a": {"c": "P"}, "dir": "rose"}, s), (True, True))
        self.assertFalse(hl.evaluate({**base, "type": "trend", "a": {"c": "Q"}, "dir": "rose"}, s)[1])  # flat: not clear

    def heat(self, cells):
        rows = [{"r": r, "c": c, "v": v} for (r, c), v in cells.items()]
        rs = sorted({r for r, _ in cells})
        cs = sorted({c for _, c in cells})
        return _spec(rows, {"x": "c", "y": "r", "color": "v"}, {"c": cs, "r": rs})

    def test_spread_and_best_in_row(self):
        # columns differ a lot, rows barely
        s = self.heat({(r, c): 10 * ci + ri for ri, r in enumerate("PQR") for ci, c in enumerate("abcd")})
        self.assertEqual(hl.evaluate({"type": "spread", "more": "x", "span": 40}, s), (True, True))
        self.assertEqual(hl.evaluate({"type": "spread", "more": "y", "span": 40}, s), (False, True))
        self.assertEqual(hl.evaluate({"type": "best_in_every_row", "x": "d", "span": 40}, s), (True, True))
        self.assertEqual(hl.evaluate({"type": "best_in_every_row", "x": "c", "span": 40}, s), (False, True))
        self.assertEqual(hl.evaluate({"type": "cell_max", "at": ["R", "d"], "span": 40}, s)[0], True)

    def test_blank_cell_is_not_evidence(self):
        cells = {(r, c): 10 * ci + ri for ri, r in enumerate("PQR") for ci, c in enumerate("abcd")}
        cells[("P", "d")] = None
        s = self.heat(cells)
        holds, clear = hl.evaluate({"type": "best_in_every_row", "x": "d", "span": 40}, s)
        self.assertFalse(holds)
        self.assertFalse(clear)  # d is best wherever it is drawn; the blank row proves nothing

    def test_gate_rejects_wrong_key(self):
        s = self.bar([50, 60, 70, 80], [10, 20, 30, 40])
        opts = [{"text": "t", "misreading": None, "claim": [self.order("most_not_all")]},
                {"text": "u", "misreading": "flipped_direction", "claim": [self.order("every")]}]
        with self.assertRaises(GateError):
            hl.check_statements(s, {"task_id": "x", "options": opts})


class AggregationTests(unittest.TestCase):
    """Plan 3.2: a within-strata direction that the pooled data reverse is not used as a key point."""

    def test_simpson_reversal_drops_compare_task(self):
        rng = np.random.default_rng(1)
        rows = []
        # within each dept women are admitted more, but women mostly apply to hard depts
        for dept, rate_f, rate_m, n_f, n_m in (("D1", .90, .80, 40, 400), ("D2", .75, .65, 40, 300),
                                              ("D3", .30, .20, 400, 40), ("D4", .20, .10, 400, 40)):
            for g, rate, n in (("F", rate_f, n_f), ("M", rate_m, n_m)):
                k = int(round(rate * n))
                rows += [{"dept": dept, "gender": g, "admitted": i < k, "score": rng.normal()} for i in range(n)]
        tmp = Path(tempfile.mkdtemp())
        try:
            path = tmp / "admit.csv"
            pd.DataFrame(rows).to_csv(path, index=False)
            prof, df = profile.profile(path)
            prof["_used"] = set()
            M = csvgen.Measure("rate", "admitted", prof)
            spec, _ = csvgen._grouped_bar(prof, df, Lettering("a"), csvgen.TMPlan("rotate"), "dept", "gender", M)
            ctx = {**spec.pop("_ctx"), "_dropped": []}
            pooled = hl._pooled(prof, df, spec, ctx, "gender", "F", "M")
            self.assertLess(pooled, 0)
            hl.cg = csvgen
            out = hl.grouped_bar(prof, df, spec, ctx, Lettering("b"), csvgen.TMPlan("rotate"))
            self.assertNotIn("admit_bar_compare", [t["task_id"] for t in out])
            self.assertTrue(any("pooled data reverse" in d for d in ctx["_dropped"]), ctx["_dropped"])
        finally:
            shutil.rmtree(tmp)


class RepoDatasetTests(unittest.TestCase):
    """The committed tasks file: keys and statements re-checked from the plotted rows."""

    def test_committed_tasks(self):
        doc = json.loads((ROOT / "tasks/csv_tasks/tasks.json").read_text())
        for chart, t in _tasks(doc).values():
            if t["level"] == "high":
                truth = [o["letter"] for o in t["options"] if hl.option_holds(o, chart)[0]]
                self.assertEqual(truth, [t["answer_letter"]], t["task_id"])
        self.assertGreater(doc["level_counts"]["high"], 0)
        self.assertGreater(doc["level_counts"]["compound"], 0)

    def test_titanic_compare_matches_plan_reference(self):
        """Plan 3.2: women survived at a higher rate than men in every class (female 72.8%, male 20.7% overall)."""
        doc = json.loads((ROOT / "tasks/csv_tasks/tasks.json").read_text())
        chart, t = _tasks(doc)["titanicmaster_bar_compare"]
        truth = next(o for o in t["options"] if o["misreading"] is None)["text"]
        self.assertIn("higher for Gender Female than for Gender Male in every Class", truth)
        raw = pd.read_csv(ROOT / "datasets/titanicmaster.tsv", sep="\t")
        surv = raw["Survived"].astype(str).str.lower().isin(["true", "yes", "1"])
        for cls in chart["category_order"]["class"]:
            m = raw["Class"] == cls
            f = surv[m & (raw["Gender"] == "Female")].mean()
            ml = surv[m & (raw["Gender"] == "Male")].mean()
            self.assertGreater(f, ml, cls)
        self.assertGreater(t["solution"]["pooled_difference"], 0)


if __name__ == "__main__":
    unittest.main()
