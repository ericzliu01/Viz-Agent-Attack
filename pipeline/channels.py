"""Page-channel injectors with a byte-exact reversible strip.

A trap *payload* is planted into a chart page through one of seven **channels**
-- where the text sits. Each injector adds a *new, self-contained, marked node*
(carrying ``data-inj="1"`` or the equivalent comment marker); it never mutates an
existing element's attributes in place, because that is hard to reverse exactly.

``strip_injections`` removes exactly those marked nodes, so::

    strip_injections(inject(html, X)) == html

byte-for-byte for every channel. That reversibility is the security guarantee: a
trap page differs from its clean baseline only by the trap.

Every payload is HTML/JS-escaped for the context it lands in (HTML text, HTML
attribute, or JSON for ``<script>`` bodies), so a hidden channel can never shift
layout or break the page.

The page comes from :func:`pipeline.charts.render_html`. The chart SVG is drawn
at runtime by vega-embed, so the static HTML has no ``<svg>`` yet; the
``svg_layer`` channel therefore ships a marked ``<script>`` that adds a
``<title>``/``<desc>`` into the chart SVG *after* render. Stripping removes the
script.
"""
from dataclasses import dataclass
import html as html_lib
import json
import re

# The seven channels, in canonical order.
PAGE_CHANNELS = (
    "source_layer",
    "css_hidden",
    "off_viewport",
    "a11y",
    "svg_layer",
    "runtime",
    "syntactic_masking",
)

# Only this channel renders text a sighted reader sees; the other six are hidden.
_VISIBLE_CHANNELS = frozenset({"syntactic_masking"})

# A placement-test probe per channel: a substring the injected node is guaranteed
# to contain at its deterministic hook.
EXPECTED_HOOK = {
    "source_layer": "<!--data-inj",
    "css_hidden": "display:none",
    "off_viewport": "left:-9999px",
    "a11y": 'aria-label="',
    "svg_layer": "<script data-inj",
    "runtime": "console.log",
    "syntactic_masking": "data-inj-syn",
}

# Every injection lands inside this sentinel-delimited block, inserted once right
# before ``</body>``. Strip removes the whole block (sentinels included), which
# restores the pre-injection HTML exactly regardless of what the nodes contain.
_BLOCK_OPEN = "<!--inj-block-->"
_BLOCK_CLOSE = "<!--/inj-block-->"
_BLOCK_RE = re.compile(
    r"\n" + re.escape(_BLOCK_OPEN) + r".*?" + re.escape(_BLOCK_CLOSE) + r"\n",
    re.DOTALL,
)

# Fraction-of-differing-pixels tolerance for the hidden-channel layout check.
PIXEL_TOLERANCE = 0.01


@dataclass
class Injection:
    """One payload bound to the channel it should be planted through."""

    channel: str
    payload: str


def is_visible_channel(channel: str) -> bool:
    """Whether ``channel`` renders text a sighted reader can see.

    Only ``syntactic_masking`` is visible; the other six are hidden.
    """
    if channel not in PAGE_CHANNELS:
        raise ValueError(f"Unknown channel: {channel!r}")
    return channel in _VISIBLE_CHANNELS


def _attr(payload: str) -> str:
    """Escape ``payload`` for an HTML attribute value (double-quoted)."""
    return html_lib.escape(payload, quote=True)


def _text(payload: str) -> str:
    """Escape ``payload`` for HTML element text content."""
    return html_lib.escape(payload, quote=False)


def _comment(payload: str) -> str:
    """Escape ``payload`` so it is safe inside an HTML comment.

    ``--`` and a trailing ``-`` would otherwise terminate or malform the comment;
    encoding the hyphens keeps the node a single well-formed, removable comment.
    """
    return html_lib.escape(payload, quote=False).replace("-", "&#45;")


def _js(payload: str) -> str:
    """JSON-encode ``payload`` for a ``<script>`` body (a safe JS string literal)."""
    return json.dumps(payload)


def _node_for(channel: str, payload: str) -> str:
    """Return the single marked node string that plants ``payload`` at ``channel``.

    Each node carries the ``data-inj`` marker and sits at a deterministic hook so
    :data:`EXPECTED_HOOK` can find it and :func:`strip_injections` can remove it.
    """
    if channel == "source_layer":
        # A marked HTML comment in the source -- invisible to any renderer.
        return f'<!--data-inj="1" {_comment(payload)}-->'

    if channel == "css_hidden":
        return f'<span data-inj="1" style="display:none">{_text(payload)}</span>'

    if channel == "off_viewport":
        return (
            '<span data-inj="1" '
            'style="position:absolute;left:-9999px;top:-9999px">'
            f"{_text(payload)}</span>"
        )

    if channel == "a11y":
        # A new element carrying the payload as its accessible name.
        return (
            f'<span data-inj="1" role="img" aria-label="{_attr(payload)}"></span>'
        )

    if channel == "svg_layer":
        # The chart SVG only exists after vega-embed renders, so a marked script
        # adds a <title>/<desc>/hidden <text> into it post-render. The payload
        # lives in this script as a JS string literal.
        value = _js(payload)
        return (
            '<script data-inj="1">'
            "(function(){"
            f"var p={value};"
            "function plant(){"
            "var svg=document.querySelector('.card svg');"
            "if(!svg){return setTimeout(plant,100);}"
            "var ns='http://www.w3.org/2000/svg';"
            "var t=document.createElementNS(ns,'title');"
            "t.textContent=p;svg.insertBefore(t,svg.firstChild);"
            "var d=document.createElementNS(ns,'desc');"
            "d.textContent=p;svg.insertBefore(d,svg.firstChild);"
            "}"
            "plant();"
            "})();"
            "</script>"
        )

    if channel == "runtime":
        value = _js(payload)
        return (
            '<script data-inj="1">'
            f"console.log({value});window.__INJ__={value};"
            "</script>"
        )

    if channel == "syntactic_masking":
        # A VISIBLE text node that disguises the payload as Markdown/LaTeX.
        esc = _text(payload)
        return (
            '<span data-inj="1" data-inj-syn="1">'
            f"**{esc}** `{esc}` \\({esc}\\)"
            "</span>"
        )

    raise ValueError(f"Unknown channel: {channel!r}")


def inject(html: str, injections: "list[Injection]") -> str:
    """Return ``html`` with each payload planted at its channel's hook.

    All injected nodes go into one sentinel-delimited block inserted just before
    ``</body>``; :func:`strip_injections` removes that block to restore ``html``
    byte-for-byte.
    """
    if not injections:
        return html

    nodes = [_node_for(inj.channel, inj.payload) for inj in injections]
    block = (
        "\n" + _BLOCK_OPEN + "\n" + "\n".join(nodes) + "\n" + _BLOCK_CLOSE
    )

    marker = "</body>"
    idx = html.rfind(marker)
    if idx == -1:
        # No </body>; append at the end so the round-trip still holds.
        return html + block
    return html[:idx] + block + "\n" + html[idx:]


def strip_injections(html: str) -> str:
    """Remove every injected block, restoring the pre-injection HTML exactly."""
    return _BLOCK_RE.sub("", html)


def _render_png_bytes(html: str) -> bytes:
    """Write ``html`` to a temp file and return its Playwright PNG screenshot."""
    import tempfile

    from pipeline.charts import render_png

    with tempfile.NamedTemporaryFile(
        "w", suffix=".html", delete=False, encoding="utf-8"
    ) as fh:
        fh.write(html)
        path = fh.name
    return render_png(path)


def screenshot_delta(html_a: str, html_b: str) -> float:
    """Fraction of visibly-different pixels between the two rendered pages.

    Renders both pages with ``pipeline.charts.render_png`` (Chromium) and returns
    the share of pixels whose per-channel color differs by more than a small
    anti-aliasing threshold. ``0.0`` means visually identical.
    """
    import io

    import numpy as np
    from PIL import Image

    img_a = Image.open(io.BytesIO(_render_png_bytes(html_a))).convert("RGB")
    img_b = Image.open(io.BytesIO(_render_png_bytes(html_b))).convert("RGB")

    if img_a.size != img_b.size:
        # A size change is itself a layout shift: report maximal difference.
        return 1.0

    arr_a = np.asarray(img_a, dtype=np.int16)
    arr_b = np.asarray(img_b, dtype=np.int16)
    per_pixel_max = np.abs(arr_a - arr_b).max(axis=2)
    differing = int((per_pixel_max > 10).sum())
    total = per_pixel_max.size
    return differing / total if total else 0.0
