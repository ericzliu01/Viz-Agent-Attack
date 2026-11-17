"""Materialize instance specs to disk and run the validation gate (stage 5).

Earlier stages (Tasks 1-9) produce :class:`~pipeline.specs.InstanceSpec`s but
defer every file write. This module is where a spec becomes an on-disk instance
directory and where the accept/reject gate runs over the built artifacts.

Two public entry points:

* :func:`render_instance` -- write ONE variant to
  ``<out_root>/instances/<base_id>/<variant_id>/`` and return a
  ``{relative_path: sha256}`` manifest of the files it wrote.
* :func:`render_from_jsonl` -- render EVERY spec, validate each with
  :func:`pipeline.validate.validate_instance` (and paired TM/MM groups with
  :func:`pipeline.validate.validate_pair`), **abort with
  :class:`~pipeline.validate.ValidationFailed` on any failure**, and write a
  combined ``manifest.json``.

**Three distinct "graders".** This is the subtlety of the task:

1. The **served** ``spec.json`` -- :func:`pipeline.specs.split_grader`'s served
   half. It carries the question/options/charts the tested agent sees and NONE of
   the answer-key fields (no ``correct_index``, ``sql``, ``target_option`` ...).
2. The **on-disk** ``grader.json`` -- the JSON evaluator sidecar. It is
   :func:`split_grader`'s grader half, flattened and augmented with ``payload``
   and ``trap_group_id`` (which ``split_grader`` leaves on the served trap, but
   which :func:`validate_pair` reads off ``grader.json``). It is JSON-only, so it
   never carries a DataFrame.
3. The **in-memory validation grader** -- assembled only at validate time inside
   :func:`render_from_jsonl`. It extends the on-disk grader with the
   non-serializable / cross-instance baselines :func:`validate_instance` needs:
   ``baseline_html`` (the pre-injection page), ``clean_spec`` (the clean TT chart
   dict, for the misleader diff), ``misleader_id``, and ``dataframe`` (a pandas
   DataFrame read from the source CSV). It is never written to disk.

**Trap materialization.** ``generate.py`` only attaches the trap dict to the
spec; the bytes are produced here by :func:`pipeline.traps.assemble_trap`. For a
page-channel trap it rewrites ``chart.html`` with the injected payload; for a
store trap (``retrieval`` / ``document_memory``) it writes ``memory.json`` or
``workspace/`` and leaves the clean ``chart.html`` in place.

**vendor_prefix.** Instances live three directories below ``out_root``
(``instances/<base_id>/<variant_id>/``), deeper than ``pages/<lib>/``. The served
page must load the vendored Vega libraries, never a CDN. The serving layer for
this repo -- :func:`browser_environment.serve_chart`, which the validation render
check and the agent harness both use -- maps the absolute URL ``/vendor/<name>``
to the repository's vendored copies and serves nothing else; a depth-relative
``../../../vendor/`` prefix would NOT resolve under it. We therefore render with a
fixed absolute ``/vendor/`` prefix (:data:`VENDOR_URL_PREFIX`). Being constant, it
is also location-independent, so a re-render into any ``out_root`` reproduces the
page bytes (and therefore the hash) exactly.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from pipeline import channels, charts
from pipeline.specs import from_jsonl_line, split_grader
from pipeline.traps import assemble_trap
from pipeline.validate import ValidationFailed, validate_instance, validate_pair

# FAKE exfiltration canary and sink; mirror ``generate.Config`` defaults. The
# canary is never a real secret -- it only has to be a token the agent could try
# to exfiltrate into the sink URL.
DEFAULT_CANARY = "CANARY-FAKE-KEY"
DEFAULT_SINK_URL = "https://sink.example/log"

# Absolute URL prefix the serving layer (browser_environment.serve_chart) maps to
# the repo's vendored Vega libraries. Constant => deterministic & location-free.
VENDOR_URL_PREFIX = "/vendor/"


# --------------------------------------------------------------------------
# Path helpers.
# --------------------------------------------------------------------------
def _safe(segment: str) -> str:
    """Make an id safe to use as a single path segment.

    IDs are ``":"``-joined (e.g. ``qX:bar:perception_facts:a11y:240:TM``); colons
    and any other non-portable characters become ``"_"`` so the layout is the same
    on every filesystem.
    """
    return "".join(c if (c.isalnum() or c in "._-") else "_" for c in segment)


def _variant_id(spec) -> str:
    """The within-``base_id`` variant segment, derived from ``instance_id``.

    ``instance_id`` is globally unique and is prefixed by ``base_id`` (TT/MT) or
    by the ``base_id``-rooted ``trap_group_id`` (TM/MM), so stripping the
    ``base_id`` prefix yields a segment that is unique among a base's variants.
    """
    base, iid = spec.base_id, spec.instance_id
    if iid.startswith(base):
        variant = iid[len(base):].lstrip(":")
    else:  # pragma: no cover - defensive; generator always prefixes base_id
        variant = iid
    return _safe(variant or spec.cell)


def _instance_dir(out_root, spec) -> Path:
    return Path(out_root) / "instances" / _safe(spec.base_id) / _variant_id(spec)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _manifest_for_dir(out_root: Path, instance_dir: Path) -> dict:
    """``{relative_path: sha256}`` for every file under ``instance_dir``.

    Keys are POSIX paths relative to ``out_root`` so the manifest is independent
    of where ``out_root`` lives.
    """
    out = {}
    for path in sorted(instance_dir.rglob("*")):
        if path.is_file():
            rel = path.relative_to(out_root).as_posix()
            out[rel] = _sha256_file(path)
    return out


# --------------------------------------------------------------------------
# The three graders.
# --------------------------------------------------------------------------
def _served_spec(spec) -> dict:
    served, _ = split_grader(spec)
    return served


def _grader_json(spec) -> dict:
    """The on-disk evaluator sidecar: :func:`split_grader`'s grader half,
    augmented so :func:`validate_pair` and :func:`validate_instance` can read the
    fields they need from a single flat JSON object.
    """
    _, grader = split_grader(spec)
    grader = dict(grader)  # split_grader already includes correct_index/sql/options
    grader["instance_id"] = spec.instance_id
    grader["base_id"] = spec.base_id
    grader["cell"] = spec.cell
    grader["direction"] = spec.direction

    trap = spec.trap
    if trap:
        # payload + trap_group_id stay on the SERVED trap per split_grader, but
        # the pair check reads them off grader.json, so surface them here.
        grader["payload"] = trap.get("payload")
        grader["trap_group_id"] = trap.get("trap_group_id")
        grader["channel"] = trap.get("channel")
        grader["subtype"] = trap.get("subtype")
        grader["family"] = trap.get("family")
        grader["target_option"] = trap.get("target_option")
        grader["extra_wrong_option"] = trap.get("extra_wrong_option")
        if trap.get("channel") == "retrieval":
            grader["poisoned_document_ids"] = [trap.get("doc_id", "poisoned-0")]

    misleader = spec.misleader
    if misleader:
        grader["misleader_id"] = misleader.get("misleader_id")
        grader["misleader_wrong"] = misleader.get("wrong_option")
    return grader


def _render_base_html(spec) -> str:
    """The clean, pre-injection page for ``spec`` (deterministic).

    This is both what a clean TT/MT variant serves and the strip-to-baseline
    reference for a page-channel trap.
    """
    # Use stage 1's brief neutral title; never the chart description (which could
    # bias the agent). Safety net: fall back to a neutral constant if the title is
    # empty or leaks the answer value.
    answer = (spec.options[spec.correct_index]
              if spec.options and 0 <= spec.correct_index < len(spec.options) else None)
    title = (spec.title or "").strip()
    if not title or (answer and str(answer) in title):
        title = "Chart"
    subtitle = spec.question or ""
    return charts.render_html(
        spec.charts, title, subtitle, vendor_prefix=VENDOR_URL_PREFIX
    )


# --------------------------------------------------------------------------
# Public: render one variant.
# --------------------------------------------------------------------------
def render_instance(spec, out_root, *, canary=DEFAULT_CANARY,
                    sink_url=DEFAULT_SINK_URL) -> dict:
    """Write ``spec``'s instance directory and return its ``{path: sha256}``.

    Writes ``spec.json`` (served), ``grader.json`` (evaluator sidecar),
    ``chart.html``, and -- for a store trap -- ``workspace/`` or ``memory.json``.
    The directory is created first (``build_memory_json``/``build_workspace`` do
    not create their parent). Page-channel traps are injected by
    :func:`pipeline.traps.assemble_trap`; store traps leave the clean page in
    place. Returned keys are POSIX paths relative to ``out_root``.
    """
    out_root = Path(out_root)
    instance_dir = _instance_dir(out_root, spec)
    instance_dir.mkdir(parents=True, exist_ok=True)

    # 1. Served spec and 2. on-disk grader.
    (instance_dir / "spec.json").write_text(
        json.dumps(_served_spec(spec), indent=2, sort_keys=True, ensure_ascii=False)
    )
    (instance_dir / "grader.json").write_text(
        json.dumps(_grader_json(spec), indent=2, sort_keys=True, ensure_ascii=False)
    )

    # 3. The page, and any store artifacts.
    base_html = _render_base_html(spec)
    trap = spec.trap
    if trap and trap.get("channel") in channels.PAGE_CHANNELS:
        # assemble_trap writes the injected chart.html.
        assemble_trap(base_html, spec, trap, canary, sink_url, instance_dir)
    else:
        (instance_dir / "chart.html").write_text(base_html)
        if trap:  # store trap: writes memory.json / workspace/, not chart.html
            assemble_trap(base_html, spec, trap, canary, sink_url, instance_dir)

    return _manifest_for_dir(out_root, instance_dir)


# --------------------------------------------------------------------------
# Public: render + validate a whole dataset.
# --------------------------------------------------------------------------
def _load_specs(specs_jsonl):
    """Accept a path to a ``.jsonl`` file, a single JSONL string, or an iterable
    of :class:`InstanceSpec` / JSONL-line strings, and return a list of specs."""
    if isinstance(specs_jsonl, (str, os.PathLike)):
        text = Path(specs_jsonl).read_text()
        return [from_jsonl_line(line) for line in text.splitlines() if line.strip()]
    specs = []
    for item in specs_jsonl:
        specs.append(from_jsonl_line(item) if isinstance(item, str) else item)
    return specs


def _validation_grader(spec, instance_dir: Path, clean_specs: dict):
    """The in-memory grader for :func:`validate_instance` (never written out)."""
    grader = _grader_json(spec)
    grader["baseline_html"] = _render_base_html(spec)
    if spec.misleader:
        grader["clean_spec"] = clean_specs.get(spec.base_id)
        grader["misleader_id"] = spec.misleader.get("misleader_id")
    # The ground-truth SQL runs over the source CSV; fall back to the chart data
    # (validate._dataframe_from_spec) when the CSV is unavailable.
    df = _dataframe(spec)
    if df is not None:
        grader["dataframe"] = df
    return grader


def _dataframe(spec):
    try:
        import pandas as pd

        if spec.csv and Path(spec.csv).is_file():
            return pd.read_csv(spec.csv)
    except Exception:  # pragma: no cover - fall back to chart data in validate
        return None
    return None


def render_from_jsonl(specs_jsonl, out_root, *, validate=True) -> dict:
    """Render every spec, (optionally) run the validation gate, and write ``manifest.json``.

    Renders each spec with :func:`render_instance`; when ``validate`` is True (the
    default), validates each instance with :func:`validate_instance` and each paired
    TM/MM group (shared ``trap_group_id``) with :func:`validate_pair`, raising
    :class:`~pipeline.validate.ValidationFailed` on the first failure. Passing
    ``validate=False`` renders only (no Chromium render/strip checks, no SQL
    re-execution) for fast iteration -- validate the frozen corpus in a separate pass
    before evaluating. On success writes ``<out_root>/manifest.json`` and returns the
    merged ``{relative_path: sha256}`` mapping.

    Deterministic: re-rendering the same specs into a same-depth ``out_root``
    yields byte-identical files and therefore an identical manifest.
    """
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    specs = _load_specs(specs_jsonl)

    # Clean TT chart dict per base_id, for the misleader diff baseline.
    clean_specs = {
        s.base_id: (s.charts[0] if s.charts else None)
        for s in specs
        if s.cell == "TT" and not s.misleader
    }

    manifest = {}
    dirs_by_group = {}  # trap_group_id -> {cell: instance_dir}
    for spec in specs:
        instance_dir = _instance_dir(out_root, spec)
        manifest.update(render_instance(spec, out_root))

        if validate:
            grader = _validation_grader(spec, instance_dir, clean_specs)
            failures = validate_instance(spec, instance_dir, grader)
            if failures:
                raise ValidationFailed(failures)

        if spec.trap and spec.cell in ("TM", "MM"):
            gid = spec.trap.get("trap_group_id")
            dirs_by_group.setdefault(gid, {})[spec.cell] = instance_dir

    # Cross-instance shared-trap rule for paired TM/MM.
    if validate:
        for gid, cells in sorted(dirs_by_group.items()):
            if "TM" in cells and "MM" in cells:
                failures = validate_pair(cells["TM"], cells["MM"])
                if failures:
                    raise ValidationFailed(failures)

    manifest_path = out_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False)
    )
    return manifest
