"""Tests for the page-channel injectors and their reversible strip.

The core guarantee is round-trip identity: for every channel,
``strip_injections(inject(html, X)) == html`` byte-for-byte, so a trap page
differs from its clean baseline only by the trap.
"""
import pytest

from pipeline.channels import (
    EXPECTED_HOOK,
    PAGE_CHANNELS,
    PIXEL_TOLERANCE,
    Injection,
    inject,
    is_visible_channel,
    screenshot_delta,
    strip_injections,
)
from pipeline.charts import render_html

# The screenshot-delta check needs Playwright + a Chromium build. Skip only that
# test when either is missing; the pure string round-trips always run.
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

PAYLOAD = "PLACED_PAYLOAD_MARKER"


def _values():
    return [
        {"region": "North", "signups": 180},
        {"region": "South", "signups": 240},
        {"region": "East", "signups": 155},
        {"region": "West", "signups": 310},
        {"region": "Central", "signups": 205},
    ]


bar_spec = {
    "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
    "width": 480,
    "height": 260,
    "background": "#fcfcfb",
    "data": {"values": _values()},
    "mark": {"type": "bar", "color": "#2a78d6"},
    "encoding": {
        "x": {"field": "region", "type": "nominal"},
        "y": {"field": "signups", "type": "quantitative"},
    },
}


def test_page_channels_is_the_exact_tuple():
    assert PAGE_CHANNELS == (
        "source_layer",
        "css_hidden",
        "off_viewport",
        "a11y",
        "svg_layer",
        "runtime",
        "syntactic_masking",
        "visible_paragraph",
    )


@pytest.mark.parametrize("channel", PAGE_CHANNELS)  # all 7 channels
def test_inject_then_strip_is_identity_per_channel(channel):
    base = render_html([bar_spec], "T", "s")
    out = inject(base, [Injection(channel, PAYLOAD)])
    assert PAYLOAD in out                    # payload is actually placed
    assert out != base                       # it changed the page
    assert strip_injections(out) == base     # removing it restores the baseline


@pytest.mark.parametrize("channel", PAGE_CHANNELS)
def test_each_channel_places_payload_at_its_hook(channel):
    out = inject(render_html([bar_spec], "T", "s"), [Injection(channel, PAYLOAD)])
    assert EXPECTED_HOOK[channel] in out


def test_a11y_uses_aria_label_with_the_payload():
    out = inject(render_html([bar_spec], "T", "s"), [Injection("a11y", "ARIA")])
    assert 'aria-label="ARIA"' in out


def test_same_payload_across_channels_reassembles_to_one_baseline():
    base = render_html([bar_spec], "T", "s")
    pages = {c: inject(base, [Injection(c, PAYLOAD)]) for c in PAGE_CHANNELS}
    # each channel's page is distinct, but all strip back to the identical baseline
    assert len({v for v in pages.values()}) == len(PAGE_CHANNELS)
    assert all(strip_injections(v) == base for v in pages.values())


def test_multiple_injections_in_one_call_round_trip():
    base = render_html([bar_spec], "T", "s")
    out = inject(base, [Injection(c, PAYLOAD) for c in PAGE_CHANNELS])
    for channel in PAGE_CHANNELS:
        assert EXPECTED_HOOK[channel] in out
    assert strip_injections(out) == base


def test_strip_is_noop_on_clean_page():
    base = render_html([bar_spec], "T", "s")
    assert strip_injections(base) == base


def test_visible_vs_hidden_classification():
    visible = {"syntactic_masking", "visible_paragraph"}
    assert is_visible_channel("css_hidden") is False
    assert is_visible_channel("off_viewport") is False
    assert is_visible_channel("syntactic_masking") is True
    assert is_visible_channel("visible_paragraph") is True
    for channel in PAGE_CHANNELS:
        assert is_visible_channel(channel) is (channel in visible)


def test_unknown_channel_rejected():
    with pytest.raises(ValueError):
        inject(render_html([bar_spec], "T", "s"), [Injection("bogus", PAYLOAD)])


@pytest.mark.parametrize("channel", ["runtime", "svg_layer"])
def test_script_channel_payload_cannot_break_out_of_script(channel):
    # An adversarial payload containing </script> must not close the tag early
    # and leak as visible page text; it stays inside the JS string literal.
    evil = "foo</script><b>pwned"
    base = render_html([bar_spec], "T", "s")
    out = inject(base, [Injection(channel, evil)])
    # The literal closing tag only appears for the injected <script> itself,
    # never from the payload. Count against the baseline to be exact.
    assert out.count("</script>") == base.count("</script>") + 1
    assert "<b>pwned" not in out                 # not leaked as raw HTML
    assert "\\u003c/script\\u003e" in out        # present only in escaped form
    assert strip_injections(out) == base         # still reverses exactly


@needs_chromium
@pytest.mark.parametrize("channel", ["runtime", "svg_layer"])
def test_script_channel_breakout_payload_does_not_shift_layout(channel):
    base = render_html([bar_spec], "T", "s")
    out = inject(base, [Injection(channel, "foo</script><b>pwned")])
    assert screenshot_delta(base, out) <= PIXEL_TOLERANCE


def test_round_trip_when_no_body_tag():
    base = "<html><head></head>no body close</html>"
    out = inject(base, [Injection("runtime", PAYLOAD)])
    assert PAYLOAD in out
    assert out != base
    assert strip_injections(out) == base


@needs_chromium
def test_hidden_channel_does_not_shift_layout():
    # a hidden-channel injection must not move visible pixels (delta <= tolerance)
    base = render_html([bar_spec], "T", "s")
    out = inject(base, [Injection("css_hidden", PAYLOAD)])
    assert screenshot_delta(base, out) <= PIXEL_TOLERANCE
