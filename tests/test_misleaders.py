"""Tests for the misleader catalog and the authored-spec validation invariant.

Each MT spec below is a hand-built stand-in for stage-2 LLM output: the data
block is unchanged versus the clean spec, and only the misleader's own
scale/encoding/color/layer keys are edited.
"""
from copy import deepcopy

import pandas as pd
import pytest

from pipeline.misleaders import (
    InvariantError,
    MISLEADERS,
    data_block_hash,
    misleader_invariant,
    misleaders_for,
)


# --------------------------------------------------------------------------
# Clean spec fixtures (plain dicts, as live in InstanceSpec.charts[i]).
# --------------------------------------------------------------------------
def _clean_bar_spec():
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "width": 480,
        "height": 260,
        "data": {"values": [
            {"region": "North", "signups": 180},
            {"region": "South", "signups": 240},
            {"region": "East", "signups": 155},
            {"region": "West", "signups": 310},
            {"region": "Central", "signups": 205},
        ]},
        "mark": {"type": "bar", "color": "#2a78d6"},
        "encoding": {
            "x": {"field": "region", "type": "nominal"},
            "y": {"field": "signups", "type": "quantitative", "title": "Signups"},
            "tooltip": [{"field": "signups", "type": "quantitative"}],
        },
    }


def _clean_line_spec():
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "width": 480,
        "height": 260,
        "data": {"values": [
            {"day": "Mon", "platform": "Mobile", "users": 1200},
            {"day": "Mon", "platform": "Desktop", "users": 3400},
            {"day": "Tue", "platform": "Mobile", "users": 1300},
            {"day": "Tue", "platform": "Desktop", "users": 3600},
        ]},
        "mark": {"type": "line"},
        "encoding": {
            "x": {"field": "day", "type": "nominal"},
            "y": {"field": "users", "type": "quantitative", "title": "Active Users"},
            "color": {
                "field": "platform", "type": "nominal",
                "scale": {"domain": ["Mobile", "Desktop"],
                          "range": ["#2a78d6", "#d97a3c"]},
            },
        },
    }


def _clean_scatter_spec():
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "width": 480,
        "height": 260,
        "data": {"values": [
            {"spend": 1, "signups": 155, "campaign": "Campaign A"},
            {"spend": 3, "signups": 205, "campaign": "Campaign A"},
            {"spend": 5, "signups": 240, "campaign": "Campaign B"},
            {"spend": 8, "signups": 310, "campaign": "Campaign B"},
        ]},
        "mark": {"type": "point", "filled": True},
        "encoding": {
            "x": {"field": "spend", "type": "quantitative", "title": "Ad Spend"},
            "y": {"field": "signups", "type": "quantitative", "title": "Signups"},
            "color": {
                "field": "campaign", "type": "nominal",
                "scale": {"domain": ["Campaign A", "Campaign B"],
                          "range": ["#2a78d6", "#d97a3c"]},
            },
        },
    }


def _clean_stacked_bar_spec():
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "width": 480,
        "height": 260,
        "data": {"values": [
            {"quarter": "Q1", "product": "A", "revenue": 40},
            {"quarter": "Q1", "product": "B", "revenue": 120},
            {"quarter": "Q2", "product": "A", "revenue": 240},
            {"quarter": "Q2", "product": "B", "revenue": 90},
        ]},
        "mark": {"type": "bar"},
        "encoding": {
            "x": {"field": "quarter", "type": "nominal"},
            "y": {"field": "revenue", "type": "quantitative",
                  "aggregate": "sum", "title": "Revenue"},
            "color": {
                "field": "product", "type": "nominal",
                "scale": {"domain": ["A", "B"],
                          "range": ["#2a78d6", "#d97a3c"]},
            },
        },
    }


@pytest.fixture
def clean_bar_spec():
    return _clean_bar_spec()


# --------------------------------------------------------------------------
# LLM-like MT spec builders (data untouched; only the misleader keys edited).
# --------------------------------------------------------------------------
def llm_like_truncated_axis_spec(clean, floor=100):
    mt = deepcopy(clean)
    mt["encoding"]["y"]["scale"] = {"domain": [floor, 320], "zero": False}
    return mt


def llm_like_highlight_decoy_spec(clean):
    mt = deepcopy(clean)
    mt["mark"].pop("color", None)
    mt["encoding"]["color"] = {
        "condition": {"test": "datum.region === 'South'", "value": "#c94a3c"},
        "value": "#2a78d6",
    }
    return mt


def llm_like_dual_axis_spec(clean):
    mt = deepcopy(clean)
    mt.pop("mark")
    mt.pop("encoding")
    mt["layer"] = [
        {"mark": {"type": "line"},
         "encoding": {"x": {"field": "day", "type": "nominal"},
                      "y": {"field": "users", "type": "quantitative",
                            "scale": {"domain": [0, 2000]}}}},
        {"mark": {"type": "line"},
         "encoding": {"x": {"field": "day", "type": "nominal"},
                      "y": {"field": "users", "type": "quantitative",
                            "scale": {"domain": [0, 5000]},
                            "axis": {"orient": "right"}}}},
    ]
    mt["resolve"] = {"scale": {"y": "independent"}}
    return mt


def llm_like_confusing_colors_spec(clean):
    mt = deepcopy(clean)
    mt["encoding"]["color"]["scale"]["range"] = ["#2a78d6", "#4f8fe0"]
    return mt


def llm_like_log_scale_spec(clean):
    mt = deepcopy(clean)
    mt["encoding"]["y"]["scale"] = {"type": "log", "domain": [100, 320]}
    return mt


def llm_like_oversized_range_spec(clean, domain):
    mt = deepcopy(clean)
    mt["encoding"]["y"]["scale"] = {"domain": domain}
    return mt


# --------------------------------------------------------------------------
# Brief Step-1 tests.
# --------------------------------------------------------------------------
def test_valid_llm_misleading_spec_passes_invariant(clean_bar_spec):
    mt = llm_like_truncated_axis_spec(clean_bar_spec, floor=100)
    assert data_block_hash(mt) == data_block_hash(clean_bar_spec)
    misleader_invariant(clean_bar_spec, mt, "truncated_axis")  # no raise


def test_invariant_rejects_data_edit(clean_bar_spec):
    bad = deepcopy(clean_bar_spec)
    bad["data"]["values"][0]["signups"] = 999
    with pytest.raises(InvariantError):
        misleader_invariant(clean_bar_spec, bad, "truncated_axis")


def test_invariant_rejects_disallowed_key_change(clean_bar_spec):
    bad = deepcopy(clean_bar_spec)
    bad["mark"]["type"] = "line"  # outside allowed_changed_keys
    with pytest.raises(InvariantError):
        misleader_invariant(clean_bar_spec, bad, "truncated_axis")


def test_invariant_rejects_missing_effect(clean_bar_spec):
    noop = deepcopy(clean_bar_spec)  # no truncation applied
    with pytest.raises(InvariantError):
        misleader_invariant(clean_bar_spec, noop, "truncated_axis")


def test_misleaders_for_line():
    assert set(misleaders_for("line")) == {"dual_axis", "confusing_colors"}


# --------------------------------------------------------------------------
# Catalog structure.
# --------------------------------------------------------------------------
def test_catalog_has_six_ids():
    assert set(MISLEADERS) == {
        "truncated_axis", "highlight_decoy", "dual_axis",
        "confusing_colors", "log_scale", "oversized_axis_range",
    }


def test_misleaders_for_each_chart_type():
    assert set(misleaders_for("bar")) == {"truncated_axis", "highlight_decoy"}
    assert set(misleaders_for("line")) == {"dual_axis", "confusing_colors"}
    assert set(misleaders_for("scatter")) == {"log_scale", "oversized_axis_range"}
    assert set(misleaders_for("stacked_bar")) == {"confusing_colors",
                                                  "oversized_axis_range"}


def test_misleaders_for_unknown_raises():
    with pytest.raises(ValueError):
        misleaders_for("pie")


# --------------------------------------------------------------------------
# data_block_hash.
# --------------------------------------------------------------------------
def test_data_block_hash_ignores_key_order(clean_bar_spec):
    reordered = deepcopy(clean_bar_spec)
    reordered["data"]["values"][0] = {"signups": 180, "region": "North"}
    assert data_block_hash(reordered) == data_block_hash(clean_bar_spec)


def test_data_block_hash_changes_on_value_edit(clean_bar_spec):
    edited = deepcopy(clean_bar_spec)
    edited["data"]["values"][2]["signups"] = 1
    assert data_block_hash(edited) != data_block_hash(clean_bar_spec)


# --------------------------------------------------------------------------
# Per-misleader effect predicates via the full invariant.
# --------------------------------------------------------------------------
def test_highlight_decoy_invariant():
    clean = _clean_bar_spec()
    mt = llm_like_highlight_decoy_spec(clean)
    misleader_invariant(clean, mt, "highlight_decoy")


def test_dual_axis_invariant():
    clean = _clean_line_spec()
    mt = llm_like_dual_axis_spec(clean)
    assert data_block_hash(mt) == data_block_hash(clean)
    misleader_invariant(clean, mt, "dual_axis")


def test_confusing_colors_invariant_line():
    clean = _clean_line_spec()
    mt = llm_like_confusing_colors_spec(clean)
    misleader_invariant(clean, mt, "confusing_colors")


def test_confusing_colors_rejects_distinct_colors():
    clean = _clean_line_spec()
    mt = deepcopy(clean)
    mt["encoding"]["color"]["scale"]["range"] = ["#2a78d6", "#111111"]
    with pytest.raises(InvariantError):
        misleader_invariant(clean, mt, "confusing_colors")


def test_log_scale_invariant():
    clean = _clean_scatter_spec()
    mt = llm_like_log_scale_spec(clean)
    misleader_invariant(clean, mt, "log_scale")


def test_oversized_range_invariant_scatter():
    clean = _clean_scatter_spec()
    mt = llm_like_oversized_range_spec(clean, [0, 900])
    misleader_invariant(clean, mt, "oversized_axis_range")


def test_oversized_range_rejects_tight_domain():
    clean = _clean_scatter_spec()
    mt = llm_like_oversized_range_spec(clean, [150, 320])  # span ~ data span
    with pytest.raises(InvariantError):
        misleader_invariant(clean, mt, "oversized_axis_range")


def test_oversized_range_invariant_stacked_bar():
    clean = _clean_stacked_bar_spec()
    mt = llm_like_oversized_range_spec(clean, [0, 600])
    misleader_invariant(clean, mt, "oversized_axis_range")


def test_confusing_colors_invariant_stacked_bar():
    clean = _clean_stacked_bar_spec()
    mt = deepcopy(clean)
    mt["encoding"]["color"]["scale"]["range"] = ["#2a78d6", "#4f8fe0"]
    misleader_invariant(clean, mt, "confusing_colors")


# --------------------------------------------------------------------------
# applies(spec, df).
# --------------------------------------------------------------------------
def test_applies_truncated_axis_true():
    clean = _clean_bar_spec()
    df = pd.DataFrame(clean["data"]["values"])
    assert MISLEADERS["truncated_axis"].applies(clean, df) is True


def test_applies_log_scale_requires_positive():
    clean = _clean_scatter_spec()
    df = pd.DataFrame(clean["data"]["values"])
    assert MISLEADERS["log_scale"].applies(clean, df) is True
    neg = deepcopy(clean)
    neg["data"]["values"][0]["signups"] = -5
    df_neg = pd.DataFrame(neg["data"]["values"])
    assert MISLEADERS["log_scale"].applies(neg, df_neg) is False


def test_unknown_misleader_id_raises(clean_bar_spec):
    with pytest.raises(KeyError):
        misleader_invariant(clean_bar_spec, clean_bar_spec, "no_such_misleader")
