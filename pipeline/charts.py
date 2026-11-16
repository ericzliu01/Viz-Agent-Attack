"""Vega-Lite page builder, chart-type applicability, and render/screenshot checks.

`render_html` turns a list of Vega-Lite spec dicts into one self-contained HTML
page modelled on ``pages/vega-lite/clean_bar.html``: a card wrapper, one inline
pretty-printed ``const spec = {...}`` per chart, and a ``vegaEmbed(..., {actions:
false})`` call each. The Vega/Vega-Lite/Vega-Embed libraries load from the
vendored copies via a relative ``vendor_prefix`` (never a CDN).

``applies`` inspects a DataFrame's dtypes to decide whether a chart type can be
drawn from it. ``chart_renders`` and ``render_png`` serve the page through
``browser_environment.serve_chart`` and drive Playwright/Chromium, reusing the
repo's existing ``browser_agent.chart_rendered`` sanity check.
"""
import html as html_lib
import json

# Vendored library filenames (relative to vendor_prefix). Never a CDN URL.
VEGA_JS = "vega-5.33.1.min.js"
VEGA_LITE_JS = "vega-lite-5.23.0.min.js"
VEGA_EMBED_JS = "vega-embed-6.29.0.min.js"

_PAGE_STYLE = """\
  :root {
    --surface: #fcfcfb;
    --page: #f9f9f7;
    --ink: #0b0b0b;
    --ink-secondary: #52514e;
    --grid: #e1e0d9;
  }
  body {
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    background: var(--page);
    color: var(--ink);
    margin: 0;
    padding: 32px;
  }
  .card {
    max-width: 560px;
    background: var(--surface);
    border: 1px solid var(--grid);
    border-radius: 12px;
    padding: 24px 28px 20px;
    margin-bottom: 24px;
  }
  h2 { font-size: 17px; font-weight: 600; margin: 0 0 2px; }
  .subtitle { font-size: 13px; color: var(--ink-secondary); margin: 0 0 16px; }"""


def render_html(charts: list[dict], title: str, subtitle: str,
                vendor_prefix: str = "../../vendor/") -> str:
    """Return a full HTML page embedding each Vega-Lite spec with ``vegaEmbed``.

    One ``.card`` with its own ``#chart-N`` div and inline, indented
    ``const spec = {...}`` is emitted per chart; the vendored libs load once
    from ``vendor_prefix``. Specs are pretty-printed JSON (``indent=2``), never
    minified.
    """
    cards = []
    scripts = []
    for index, spec in enumerate(charts):
        chart_id = f"chart-{index}"
        cards.append(f'  <div id="{chart_id}"></div>')
        pretty = json.dumps(spec, indent=2)
        scripts.append(
            f'const spec{index} = {pretty};\n'
            f'vegaEmbed("#{chart_id}", spec{index}, {{ actions: false }});'
        )

    cards_html = "\n".join(cards)
    scripts_html = "\n\n".join(scripts)
    safe_title = html_lib.escape(title)
    safe_subtitle = html_lib.escape(subtitle)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{safe_title}</title>
<script src="{vendor_prefix}{VEGA_JS}"></script>
<script src="{vendor_prefix}{VEGA_LITE_JS}"></script>
<script src="{vendor_prefix}{VEGA_EMBED_JS}"></script>
<style>
{_PAGE_STYLE}
</style>
</head>
<body>
<div class="card">
  <h2>{safe_title}</h2>
  <p class="subtitle">{safe_subtitle}</p>
{cards_html}
</div>
<script>
{scripts_html}
</script>
</body>
</html>
"""


def _column_kinds(df):
    """Split a DataFrame's columns into (numeric, temporal, categorical) counts."""
    from pandas.api import types as pdt

    numeric = temporal = categorical = 0
    for column in df.columns:
        series = df[column]
        if pdt.is_numeric_dtype(series) and not pdt.is_bool_dtype(series):
            numeric += 1
        elif pdt.is_datetime64_any_dtype(series):
            temporal += 1
        else:
            categorical += 1
    return numeric, temporal, categorical


def applies(chart_type: str, df) -> bool:
    """Whether ``chart_type`` can be drawn from ``df``, judged by dtypes.

    - ``bar``: at least one numeric column.
    - ``scatter``: at least two numeric columns.
    - ``line``: a temporal column or an ordered (numeric) axis — a
      purely-categorical frame does not qualify.
    - ``stacked_bar``: a 3-way split — a categorical x, a categorical
      series/group, and a numeric value (>= 2 categorical and >= 1 numeric).
    """
    numeric, temporal, categorical = _column_kinds(df)
    if chart_type == "bar":
        return numeric >= 1
    if chart_type == "scatter":
        return numeric >= 2
    if chart_type == "line":
        return temporal >= 1 or numeric >= 1
    if chart_type == "stacked_bar":
        return categorical >= 2 and numeric >= 1
    raise ValueError(f"Unknown chart_type: {chart_type!r}")


def _with_rendered_page(html_path, fn):
    """Serve ``html_path`` and run ``fn(page)`` on a loaded Chromium page.

    Mirrors how ``run_attack_suite.py`` drives ``serve_chart`` + Playwright:
    navigate until network idle, settle briefly, then act on the page.
    """
    from playwright.sync_api import sync_playwright

    from browser_agent import VIEWPORT
    from browser_environment import serve_chart

    with serve_chart(html_path) as url, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport=VIEWPORT)
            try:
                page = context.new_page()
                page.set_default_timeout(10_000)
                page.goto(url, wait_until="networkidle")
                page.wait_for_timeout(700)
                return fn(page)
            finally:
                context.close()
        finally:
            browser.close()


def chart_renders(html_path: str) -> bool:
    """True if the served page draws real marks (not a blank/failed chart).

    Wraps the repo's ``browser_agent.chart_rendered`` sanity check through
    ``serve_chart`` + Playwright.
    """
    from browser_agent import chart_rendered

    return bool(_with_rendered_page(html_path, chart_rendered))


def render_png(html_path: str) -> bytes:
    """Serve the page and return a full-page Playwright PNG screenshot (bytes)."""
    return _with_rendered_page(html_path, lambda page: page.screenshot(full_page=True))
