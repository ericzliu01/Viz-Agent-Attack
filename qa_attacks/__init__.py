"""Adversarial attack injection for existing image-based chart QA benchmarks.

The HTML pipeline (:mod:`pipeline`) builds charts from scratch and plants traps
in page channels. Existing benchmarks (ChartGalaxy, Misviz, ...) ship raster
images plus QA, so here the attack is injected into the benchmark item itself:

* :mod:`qa_attacks.answers` -- parse a question's answer format and pick the
  wrong *target* answer the attack pushes.
* :mod:`qa_attacks.payloads` -- the injected text, per payload subtype (names
  shared with :data:`pipeline.traps.PAYLOAD_FAMILIES`), plus a neutral control.
* :mod:`qa_attacks.image_channels` -- where the text goes: rendered into the
  image (banner, footnote, overlay, low-contrast) or into the text context.
* :mod:`qa_attacks.inject` -- benchmark-agnostic cross of item x subtype x
  channel, writing attacked rows that keep the source benchmark's schema.
* :mod:`qa_attacks.chartgalaxy` -- ChartGalaxy adapter and CLI.
"""
