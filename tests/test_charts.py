"""Tests for the Vega-Lite chart page builder, applicability, and render checks."""
import pandas as pd
import pytest

from pipeline.charts import applies, render_html

# The render / screenshot checks need Playwright + a Chromium build. Skip the
# whole group when either is missing, so a plain unit run stays green on a
# machine without a browser; they RUN wherever Chromium is installed.
try:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as _pw:
        _pw.chromium.launch(headless=True).close()
    _CHROMIUM_OK = True
    _CHROMIUM_WHY = ""
except Exception as exc:  # pragma: no cover - environment dependent
    _CHROMIUM_OK = False
    _CHROMIUM_WHY = f"Playwright/Chromium unavailable: {exc}"

needs_chromium = pytest.mark.skipif(not _CHROMIUM_OK, reason=_CHROMIUM_WHY)


def _values():
    return [
        {"region": "North", "signups": 180},
        {"region": "South", "signups": 240},
        {"region": "East", "signups": 155},
        {"region": "West", "signups": 310},
        {"region": "Central", "signups": 205},
    ]


def _bar_spec(values=None):
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "width": 480,
        "height": 260,
        "background": "#fcfcfb",
        "data": {"values": _values() if values is None else values},
        "mark": {"type": "bar", "color": "#2a78d6"},
        "encoding": {
            "x": {"field": "region", "type": "nominal"},
            "y": {"field": "signups", "type": "quantitative"},
        },
    }


bar_spec = _bar_spec()

# A chart that draws nothing: empty data and no drawable mark, so vegaEmbed
# produces no view. The repo's `chart_rendered` sanity check exists to flag a
# page that "failed to draw anything" -- any spec that DOES compile paints the
# view frame onto the canvas and counts as rendered, so a blank result requires
# a spec that yields no view at all.
empty_data_spec = {
    "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
    "width": 480,
    "height": 260,
    "data": {"values": []},
    "encoding": {
        "x": {"field": "region", "type": "nominal"},
        "y": {"field": "signups", "type": "quantitative"},
    },
}

two_numeric_df = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [4, 5, 6]})
one_numeric_df = pd.DataFrame({"a": [1, 2, 3], "label": ["x", "y", "z"]})
categorical_only_df = pd.DataFrame({"g": ["a", "b"], "h": ["c", "d"]})
temporal_df = pd.DataFrame({"when": pd.to_datetime(["2020-01-01", "2020-01-02"]),
                            "label": ["x", "y"]})
stacked_df = pd.DataFrame({"x": ["a", "b"], "series": ["p", "q"], "value": [1, 2]})


def test_render_html_embeds_vendor_relative_not_cdn():
    html = render_html([bar_spec], "T", "s", vendor_prefix="../../vendor/")
    assert "vendor/vega-lite-5.23.0.min.js" in html and "cdn" not in html.lower()


def test_render_html_includes_all_three_libs_and_titles():
    html = render_html([bar_spec], "My Title", "my subtitle")
    assert "../../vendor/vega-5.33.1.min.js" in html
    assert "../../vendor/vega-embed-6.29.0.min.js" in html
    assert "My Title" in html and "my subtitle" in html
    assert "actions: false" in html.replace(" ", " ")


def test_render_html_one_embed_per_chart():
    html = render_html([bar_spec, _bar_spec()], "T", "s")
    assert html.count("vegaEmbed(") == 2


def test_applies_bar_requires_one_numeric():
    assert applies("bar", one_numeric_df) is True
    assert applies("bar", categorical_only_df) is False


def test_applies_scatter_requires_two_numeric():
    assert applies("scatter", two_numeric_df) is True
    assert applies("scatter", one_numeric_df) is False


def test_applies_line_needs_temporal_or_ordered_axis():
    assert applies("line", temporal_df) is True          # temporal axis
    assert applies("line", one_numeric_df) is True        # numeric ordered axis
    assert applies("line", categorical_only_df) is False  # purely categorical


def test_applies_stacked_bar_needs_three_way_split():
    assert applies("stacked_bar", stacked_df) is True
    assert applies("stacked_bar", two_numeric_df) is False  # no 2nd categorical


def test_spec_embedded_readable_not_minified():
    html = render_html([bar_spec], "T", "s")
    assert '\n    "mark"' in html or '\n  "mark"' in html   # indented, not one line


@needs_chromium
def test_chart_renders_true_for_clean_bar(tmp_path):
    from pipeline.charts import chart_renders

    p = tmp_path / "chart.html"
    p.write_text(render_html([bar_spec], "T", "s"))
    assert chart_renders(str(p)) is True


@needs_chromium
def test_chart_renders_false_for_empty_data(tmp_path):
    from pipeline.charts import chart_renders

    p = tmp_path / "chart.html"
    p.write_text(render_html([empty_data_spec], "T", "s"))
    assert chart_renders(str(p)) is False


@needs_chromium
def test_render_png_returns_image_bytes(tmp_path):
    from pipeline.charts import render_png

    p = tmp_path / "chart.html"
    p.write_text(render_html([bar_spec], "T", "s"))
    assert render_png(str(p)).startswith(b"\x89PNG")


# --- $schema normalization (a model's wrong host must not break rendering) ---
WRONG_SCHEMA = "https://vega-lite.github.io/schema/v5.json"


def _wrong_schema_spec():
    spec = dict(bar_spec)
    spec["$schema"] = WRONG_SCHEMA
    return spec


def test_canonical_schema_returns_copy_with_canonical_url():
    from pipeline.charts import VEGA_LITE_SCHEMA, canonical_schema

    spec = _wrong_schema_spec()
    out = canonical_schema(spec)
    assert out["$schema"] == VEGA_LITE_SCHEMA
    assert spec["$schema"] == WRONG_SCHEMA          # input not mutated
    assert {k: v for k, v in out.items() if k != "$schema"} == \
        {k: v for k, v in spec.items() if k != "$schema"}


def test_render_html_uses_canonical_schema_without_mutating_input():
    from pipeline.charts import VEGA_LITE_SCHEMA

    spec = _wrong_schema_spec()
    html = render_html([spec], "T", "s")
    assert VEGA_LITE_SCHEMA in html
    assert WRONG_SCHEMA not in html
    assert spec["$schema"] == WRONG_SCHEMA


@needs_chromium
def test_chart_renders_true_despite_wrong_schema_host(tmp_path):
    from pipeline.charts import chart_renders

    p = tmp_path / "chart.html"
    p.write_text(render_html([_wrong_schema_spec()], "T", "s"))
    assert chart_renders(str(p)) is True
