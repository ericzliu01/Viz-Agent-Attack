"""Tests for llm_taskgen.csvgen / llm_taskgen.profile: task generation from arbitrary CSVs.

Run from the repo root: python -m unittest tests.test_csvgen -v
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from llm_taskgen import csvgen, pages, profile
from llm_taskgen.core import LETTERS, TECHNIQUES, TIER

ROOT = Path(__file__).resolve().parents[1]


def synthetic_csv(path, seed=0):
    """A shop-like table with strong, known effects so every chart type can be built."""
    rng = np.random.default_rng(seed)
    n = 3000
    region = rng.choice(["North", "South", "East", "West", "Central"], n, p=[.3, .25, .2, .15, .1])
    plan = rng.choice(["Basic", "Pro"], n, p=[.6, .4])
    w = np.linspace(2, 1, 16)
    year = rng.choice(np.arange(2005, 2021), n, p=w / w.sum())       # totals fall over time
    online = 0.05 + 0.5 * (year - 2005) / 15                           # while Online rises
    u = rng.random(n)
    segment = np.where(u < online, "Online", np.where(u < online + (1 - online) * 0.6, "Retail", "Wholesale"))
    base = {"North": 100, "South": 160, "East": 220, "West": 300, "Central": 420}
    revenue = np.array([base[r] for r in region]) * np.where(plan == "Pro", 1.8, 1.0) + rng.normal(0, 15, n)
    revenue += (year - 2005) * np.where(segment == "Online", 12, -4)
    cost = 0.6 * revenue + rng.normal(0, 20, n)
    visits = np.abs(rng.gamma(2, 5, n)) + np.where(plan == "Pro", 10, 0)
    spend_online = 50 + (year - 2005) * 6 + rng.normal(0, 3, n)
    spend_store = 120 - (year - 2005) * 5 + rng.normal(0, 3, n)
    churned = rng.random(n) < np.where(plan == "Pro", 0.1, 0.35) + np.array([0.0, .05, .1, .2, .3])[
        pd.Series(region).map({"North": 0, "South": 1, "East": 2, "West": 3, "Central": 4}).values]
    df = pd.DataFrame({
        "customer_id": np.arange(1, n + 1), "signup_date": [f"{y}-0{rng.integers(1, 10)}-1{rng.integers(0, 9)}" for y in year],
        "region": region, "plan": plan, "segment": segment, "year": year,
        "revenue": revenue.round(2), "cost": cost.round(2), "visits": visits.round(1),
        "spend_online": spend_online.round(2), "spend_store": spend_store.round(2), "churned": churned,
        "notes": [f"free text {i}" for i in range(n)], "tags": ["a;b"] * n,
    })
    df.to_csv(path, index=False)
    return df


class ProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.csv = cls.tmp / "shop.csv"
        synthetic_csv(cls.csv)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_roles(self):
        prof, df = profile.profile(self.csv)
        role = {k: c["role"] for k, c in prof["columns"].items()}
        self.assertEqual(role["customer_id"], "skip")
        self.assertEqual(role["signup_date"], "skip")       # a date: its year is derived
        self.assertEqual(role["signup_date_year"], "year")
        self.assertEqual(role["year"], "year")
        self.assertEqual(role["region"], "category")
        self.assertEqual(role["plan"], "binary")
        self.assertEqual(role["churned"], "binary")
        self.assertEqual(prof["columns"]["churned"]["positive"], "True")
        self.assertEqual(role["revenue"], "measure")
        self.assertEqual(role["notes"], "skip")
        self.assertEqual(role["tags"], "skip")              # multi-valued list

    def test_sidecar_overrides(self):
        side = {"name": "Shop", "noun": "customers", "labels": {"revenue": "Revenue ($)"},
                "roles": {"visits": "skip"}, "levels": {"region": ["North", "South", "East", "West"]},
                "where": {"segment": ["Retail", "Online"]}}
        prof, df = profile.profile(self.csv, sidecar=side)
        self.assertEqual(prof["noun"], "customers")
        self.assertEqual(prof["columns"]["revenue"]["label"], "Revenue ($)")
        self.assertEqual(prof["columns"]["visits"]["role"], "skip")
        self.assertEqual(set(df["segment"].unique()), {"Retail", "Online"})
        self.assertEqual(csvgen.top_levels(prof, df, "region", 6), ["North", "South", "East", "West"])

    def test_same_quantity(self):
        self.assertTrue(csvgen.same_quantity("co2_per_capita", "consumption_co2_per_capita"))
        self.assertTrue(csvgen.same_quantity("average_playtime", "median_playtime"))
        self.assertFalse(csvgen.same_quantity("co2_including_luc", "cumulative_oil_co2"))
        self.assertFalse(csvgen.same_quantity("firstpage", "downloads_xplore"))


class GenerateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.csv = cls.tmp / "shop.csv"
        cls.raw = synthetic_csv(cls.csv)
        cls.doc = csvgen.build([cls.csv])
        cls.tasks = {t["task_id"]: (c["chart"], t) for c in cls.doc["examples"] for t in c["tasks"]}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_every_chart_type_is_built(self):
        built = {c["chart"]["chart_type"] for c in self.doc["examples"]}
        self.assertEqual(built, set(csvgen.BUILDERS), self.doc["datasets"][0]["charts"])

    def test_deterministic(self):
        again = csvgen.build([self.csv])
        self.assertEqual(json.dumps(self.doc, default=profile.to_py), json.dumps(again, default=profile.to_py))

    def test_letters_balanced(self):
        counts = self.doc["truth_letter_counts"]
        self.assertLessEqual(max(counts.values()) - min(counts.values()), 1, counts)

    def test_tasks_use_literature_primitives(self):
        for chart, t in self.tasks.values():
            self.assertIn(t["primitive"], TIER)
            for p in t.get("primitive_chain", []):
                self.assertIn(p, TIER)

    def test_bar_retrieve_matches_raw_csv(self):
        chart, t = self.tasks["shop_bar_retrieve"]
        enc = chart["encodings"]
        (xc, (a,)), (gc, (b,)) = sorted(t["named_values"].items(), key=lambda kv: kv[0] != enc["x"])
        sub = self.raw[(self.raw[xc].astype(str) == a) & (self.raw[gc].astype(str) == b)]
        field = enc["y"]
        if field.startswith("mean_"):
            want = sub[field[5:]].mean()
        elif field.startswith("pct_"):
            col = field[4:]
            pos = profile.profile(self.csv)[0]["columns"][col]["positive"]
            want = (sub[col].astype(str) == pos).mean() * 100
        else:
            want = len(sub)
        truth = next(o for o in t["options"] if o["misreading"] is None)
        self.assertAlmostEqual(truth["value"], want, delta=abs(want) * 1e-3 + 1e-9)

    def test_stacked_total_matches_raw_csv(self):
        chart, t = self.tasks["shop_stacked_total"]
        xc, sc = chart["encodings"]["x"], chart["encodings"]["stack"]
        (x0,) = t["named_values"][xc]
        raw = self.raw
        if xc not in raw:  # a year derived from a date column
            raw = raw.assign(**{xc: pd.to_datetime(raw[xc.removesuffix("_year")]).dt.year})
        sub = raw[(raw[xc].astype(str) == str(x0)) & raw[sc].astype(str).isin(chart["stack_order"])]
        truth = next(o for o in t["options"] if o["misreading"] is None)
        self.assertEqual(truth["value"], len(sub))

    def test_scatter_correlation_sign_matches_raw(self):
        chart, t = self.tasks["shop_scatter_correlate"]
        x, y = chart["encodings"]["x"], chart["encodings"]["y"]
        r = self.raw[x].corr(self.raw[y])
        truth = next(o for o in t["options"] if o["misreading"] is None)
        self.assertEqual(truth["value"], "up" if r > 0 else "down")

    def test_attacks(self):
        for chart, t in self.tasks.values():
            self.assertTrue(t["attacks"])
            for a in t["attacks"]:
                self.assertIn(a["technique"], TECHNIQUES)
                self.assertNotEqual(a["bait_letter"], t["answer_letter"])
                bait = next(o for o in t["options"] if o["letter"] == a["bait_letter"])
                if a["channel"] == "MT":
                    self.assertIn(bait["misreading"], a["bait_rule"])
                else:
                    self.assertIn(bait.get("claim_phrase", bait["text"]), a["claim_text"])

    def test_tm_modes(self):
        doc = csvgen.build([self.csv], tm_mode="all", chart_types=["grouped_bar"])
        tms = {a["technique"] for c in doc["examples"] for t in c["tasks"] for a in t["attacks"] if a["channel"] == "TM"}
        self.assertEqual(tms, set(csvgen.CONTENT + csvgen.COGNITIVE))
        doc = csvgen.build([self.csv], tm_mode="none", chart_types=["grouped_bar"])
        self.assertFalse([a for c in doc["examples"] for t in c["tasks"] for a in t["attacks"] if a["channel"] == "TM"])

    def test_skips_are_reported(self):
        tmp = self.tmp / "tiny.csv"
        pd.DataFrame({"a": ["x", "y"] * 5, "b": range(10)}).to_csv(tmp, index=False)
        doc = csvgen.build([tmp])
        self.assertFalse(doc["examples"])
        self.assertTrue(all(v.startswith("skipped") for v in doc["datasets"][0]["charts"].values()))


class PageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        csv = cls.tmp / "shop.csv"
        synthetic_csv(csv)
        cls.doc = csvgen.build([csv])
        cls.ex = cls.tmp / "tasks.json"
        cls.ex.write_text(json.dumps(cls.doc, default=profile.to_py))
        cls.pages = cls.tmp / "pages"
        cls.written = pages.build(cls.ex, cls.pages, prefix="cx_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_counts_and_prefix(self):
        n = sum(1 + len(t["attacks"]) for c in self.doc["examples"] for t in c["tasks"])
        self.assertEqual(len(self.written), 4 * n)
        self.assertTrue(all("__cx_" in pid for _, pid in self.written))

    def test_mt_pages_differ_and_tm_pages_carry_the_claim(self):
        for lib in pages.LIBRARIES:
            for c in self.doc["examples"]:
                ct = c["chart"]["chart_type"]
                for t in c["tasks"]:
                    clean = (self.pages / lib / f"clean_{ct}__cx_{t['task_id']}.html").read_text()
                    for a in t["attacks"]:
                        page = (self.pages / lib / f"attack_cx_{a['technique']}__cx_{t['task_id']}.html").read_text()
                        meta = json.loads((self.pages / lib / f"attack_cx_{a['technique']}__cx_{t['task_id']}.meta.json").read_text())
                        self.assertEqual(meta["answer_type"], "mcq")
                        self.assertEqual(meta["ground_truth"], t["answer_letter"])
                        if a["channel"] == "MT":
                            self.assertNotEqual(page, clean, (lib, a["technique"], t["task_id"]))
                        elif a["technique"] in ("memory_write", "rag_poisoning"):
                            self.assertEqual(page, clean)
                            self.assertIn(a["claim_text"], json.dumps(meta["memory"]))
                        else:
                            import html as h
                            self.assertTrue(json.dumps(a["claim_text"])[1:-1] in page or h.escape(a["claim_text"]) in page,
                                            (lib, a["technique"]))


if __name__ == "__main__":
    unittest.main()
