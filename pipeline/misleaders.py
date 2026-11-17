"""Misleader catalog and the authored-spec validation invariant.

Stage 2 (Task 10) has the LLM write the misleading Vega-Lite spec **directly**,
rather than patching the clean one. This module does not construct specs; it

  1. catalogs the six misleaders (``MISLEADERS``), and
  2. validates an authored MT spec against its clean TT counterpart
     (``misleader_invariant``),

so the MT page stays a *checkable diff* of the TT page even though it was
authored. The invariant enforces three things, in order:

  (1) the data block is byte-for-byte equivalent (``data_block_hash``);
  (2) every JSON path that differs between clean and MT falls under that
      misleader's ``allowed_changed_keys``; and
  (3) the misleader's ``effect(mt_spec)`` predicate holds.

Specs are plain dicts (``data.values`` / ``mark`` / ``encoding`` / optional
``layer``) -- the dicts that live in ``InstanceSpec.charts[i]``.
"""
from dataclasses import dataclass
from typing import Callable

from memory import fingerprint


class InvariantError(Exception):
    """Raised when an authored MT spec is not a valid diff of its clean spec."""


@dataclass(frozen=True)
class Misleader:
    """One catalog entry.

    - ``chart_types``: the chart types this misleader is defined for.
    - ``applies(spec, df)``: whether it can be drawn from this spec + data.
    - ``allowed_changed_keys``: concrete normalized path prefixes it may touch.
      A changed path is permitted iff it equals one of these prefixes or is a
      descendant of one. List indices normalize to ``[]`` (see ``_norm_path``),
      so ``layer.[].encoding.y.scale`` matches any layer entry.
    - ``effect(mt_spec)``: the misleader-specific check that the distortion is
      actually present.
    """

    id: str
    chart_types: tuple
    allowed_changed_keys: frozenset
    applies: Callable
    effect: Callable


# ---------------------------------------------------------------------------
# Data-block hashing.
# ---------------------------------------------------------------------------
def data_block_hash(spec) -> str:
    """Key-order-independent sha256 over ``spec["data"]["values"]`` only.

    Reuses ``memory.fingerprint`` so an edit to any datum anywhere in the
    values list changes the hash, while cosmetic key reordering does not.
    """
    return fingerprint(spec["data"]["values"])


# ---------------------------------------------------------------------------
# Recursive path diff.
# ---------------------------------------------------------------------------
def _norm_path(path) -> str:
    """Normalize a tuple path to a dotted string; list indices become ``[]``."""
    return ".".join("[]" if isinstance(seg, int) else seg for seg in path)


def _diff_paths(clean, mt, prefix=()):
    """Set of normalized JSON paths where ``clean`` and ``mt`` differ.

    An added or removed key is reported as that key's path (its subtree is not
    expanded). A list whose length changed is reported at the list's own path.
    """
    paths = set()
    if type(clean) is not type(mt):
        paths.add(_norm_path(prefix))
        return paths
    if isinstance(clean, dict):
        for key in set(clean) | set(mt):
            if key not in clean or key not in mt:
                paths.add(_norm_path(prefix + (key,)))
            else:
                paths |= _diff_paths(clean[key], mt[key], prefix + (key,))
    elif isinstance(clean, list):
        if len(clean) != len(mt):
            paths.add(_norm_path(prefix))
        else:
            for index, (a, b) in enumerate(zip(clean, mt)):
                paths |= _diff_paths(a, b, prefix + (index,))
    else:
        if clean != mt:
            paths.add(_norm_path(prefix))
    return paths


def _is_allowed(path: str, allowed) -> bool:
    """True if ``path`` equals or is a descendant of an allowed prefix."""
    for prefix in allowed:
        if path == prefix or path.startswith(prefix + "."):
            return True
    return False


def _normalize_mark(spec):
    """Return ``spec`` with a string ``mark`` rewritten to ``{"type": mark}``.

    Vega-Lite treats ``"mark": "bar"`` and ``"mark": {"type": "bar"}`` as identical,
    but a raw path diff sees a str-vs-dict type change and flags the whole ``mark``
    path. Normalizing both sides before the diff removes that false positive (an
    authored misleader that re-emits the mark in object form is not a real change).
    """
    if isinstance(spec, dict) and isinstance(spec.get("mark"), str):
        return {**spec, "mark": {"type": spec["mark"]}}
    return spec


def _nested_data_paths(spec) -> list:
    """Normalized paths of every ``data`` key that appears BELOW the spec root.

    ``data_block_hash`` only verifies the single top-level ``data.values`` block, so
    any ``data`` introduced deeper in the tree (``layer[].data``, ``concat[].data``,
    a nested ``spec.data`` ...) would carry chart data that escapes the hash. A
    misleader that allows structural keys (e.g. ``dual_axis`` allows ``layer``) could
    otherwise replace what is plotted with layer-local data and still pass the
    invariant. This collects those below-root ``data`` keys so the invariant can
    reject them; the root ``data`` key (path ``"data"``) is excluded.
    """
    found = []

    def walk(node, prefix):
        if isinstance(node, dict):
            for key, value in node.items():
                path = prefix + (key,)
                if key == "data" and prefix != ():
                    found.append(_norm_path(path))
                walk(value, path)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, prefix + (index,))

    walk(spec, ())
    return found


# ---------------------------------------------------------------------------
# Small spec helpers shared by applies/effect predicates.
# ---------------------------------------------------------------------------
def _y_encoding(spec):
    return spec.get("encoding", {}).get("y", {})


def _field_values(spec, field):
    out = []
    for row in spec.get("data", {}).get("values", []):
        value = row.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out.append(value)
    return out


def _hex_to_rgb(color):
    color = color.lstrip("#")
    if len(color) != 6:
        return None
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def _min_color_distance(colors):
    """Minimum pairwise Euclidean RGB distance among hex colors (or ``inf``)."""
    rgbs = [rgb for rgb in (_hex_to_rgb(c) for c in colors) if rgb is not None]
    best = float("inf")
    for i in range(len(rgbs)):
        for j in range(i + 1, len(rgbs)):
            dist = sum((a - b) ** 2 for a, b in zip(rgbs[i], rgbs[j])) ** 0.5
            best = min(best, dist)
    return best


_CONFUSING_COLOR_THRESHOLD = 60.0  # RGB-space distance below which two series read as "same"
_OVERSIZED_FACTOR = 3  # domain span must be >= N * data span


# ---------------------------------------------------------------------------
# applies(spec, df) predicates.
# ---------------------------------------------------------------------------
def _applies_quant_y(spec, df):
    return _y_encoding(spec).get("type") == "quantitative"


def _applies_highlight(spec, df):
    x = spec.get("encoding", {}).get("x", {})
    return x.get("type") == "nominal" and _y_encoding(spec).get("type") == "quantitative"


def _applies_color_series(spec, df):
    color = spec.get("encoding", {}).get("color", {})
    return bool(color.get("field")) and "scale" in color


def _applies_log(spec, df):
    y = _y_encoding(spec)
    if y.get("type") != "quantitative":
        return False
    values = _field_values(spec, y.get("field"))
    return bool(values) and all(v > 0 for v in values)


# ---------------------------------------------------------------------------
# effect(mt_spec) predicates.
# ---------------------------------------------------------------------------
def _effect_truncated_axis(mt):
    scale = _y_encoding(mt).get("scale", {})
    if scale.get("zero") is not False:
        return False
    domain = scale.get("domain")
    return isinstance(domain, list) and len(domain) == 2 and domain[0] > 0


def _effect_highlight_decoy(mt):
    color = mt.get("encoding", {}).get("color", {})
    return isinstance(color.get("condition"), (dict, list))


def _effect_dual_axis(mt):
    layers = mt.get("layer")
    if not isinstance(layers, list) or len(layers) < 2:
        return False
    y_scaled = [
        layer for layer in layers
        if "scale" in layer.get("encoding", {}).get("y", {})
    ]
    if len(y_scaled) < 2:
        return False
    return mt.get("resolve", {}).get("scale", {}).get("y") == "independent"


def _effect_confusing_colors(mt):
    scale = mt.get("encoding", {}).get("color", {}).get("scale", {})
    colors = scale.get("range")
    if not isinstance(colors, list) or len(colors) < 2:
        return False
    return _min_color_distance(colors) < _CONFUSING_COLOR_THRESHOLD


def _effect_log_scale(mt):
    return _y_encoding(mt).get("scale", {}).get("type") == "log"


def _effect_oversized_range(mt):
    y = _y_encoding(mt)
    domain = y.get("scale", {}).get("domain")
    if not (isinstance(domain, list) and len(domain) == 2):
        return False
    domain_span = domain[1] - domain[0]
    values = _field_values(mt, y.get("field"))
    if not values:
        return False
    data_span = max(values) - min(values)
    if data_span <= 0:
        return False
    return domain_span >= _OVERSIZED_FACTOR * data_span


# ---------------------------------------------------------------------------
# The catalog.
# ---------------------------------------------------------------------------
MISLEADERS: dict = {
    "truncated_axis": Misleader(
        id="truncated_axis",
        chart_types=("bar",),
        allowed_changed_keys=frozenset({"encoding.y.scale"}),
        applies=_applies_quant_y,
        effect=_effect_truncated_axis,
    ),
    "highlight_decoy": Misleader(
        id="highlight_decoy",
        chart_types=("bar",),
        allowed_changed_keys=frozenset({"encoding.color", "mark.color"}),
        applies=_applies_highlight,
        effect=_effect_highlight_decoy,
    ),
    "dual_axis": Misleader(
        id="dual_axis",
        chart_types=("line",),
        allowed_changed_keys=frozenset({"mark", "encoding", "layer", "resolve"}),
        applies=_applies_quant_y,
        effect=_effect_dual_axis,
    ),
    "confusing_colors": Misleader(
        id="confusing_colors",
        chart_types=("line", "stacked_bar"),
        allowed_changed_keys=frozenset({"encoding.color.scale"}),
        applies=_applies_color_series,
        effect=_effect_confusing_colors,
    ),
    "log_scale": Misleader(
        id="log_scale",
        chart_types=("scatter",),
        allowed_changed_keys=frozenset({"encoding.y.scale"}),
        applies=_applies_log,
        effect=_effect_log_scale,
    ),
    "oversized_axis_range": Misleader(
        id="oversized_axis_range",
        chart_types=("scatter", "stacked_bar"),
        allowed_changed_keys=frozenset({"encoding.y.scale"}),
        applies=_applies_quant_y,
        effect=_effect_oversized_range,
    ),
}


# Chart-type -> the two misleader ids defined for it (Global Constraints table).
_CHART_TYPES = ("bar", "line", "scatter", "stacked_bar")


def misleaders_for(chart_type: str) -> list:
    """The ids of the misleaders defined for ``chart_type`` (2 per type)."""
    if chart_type not in _CHART_TYPES:
        raise ValueError(f"Unknown chart_type: {chart_type!r}")
    return [mid for mid, m in MISLEADERS.items() if chart_type in m.chart_types]


# ---------------------------------------------------------------------------
# The invariant.
# ---------------------------------------------------------------------------
def misleader_invariant(clean_spec, mt_spec, misleader_id) -> None:
    """Validate an authored MT spec against its clean TT spec.

    Raises :class:`InvariantError` unless all three checks hold, in order:
    (1) data-block hash equality, (2) only ``allowed_changed_keys`` differ, and
    (3) the misleader's ``effect`` is present. Raises ``KeyError`` if
    ``misleader_id`` is not in the catalog.
    """
    misleader = MISLEADERS[misleader_id]

    # Normalize mark representation on both sides so "bar" == {"type": "bar"}.
    clean_spec = _normalize_mark(clean_spec)
    mt_spec = _normalize_mark(mt_spec)

    # (1) Data block unchanged.
    if data_block_hash(clean_spec) != data_block_hash(mt_spec):
        raise InvariantError(
            f"{misleader_id}: data-block hash changed (data.values was edited)"
        )

    # (1b) No chart data may hide below the root. The hash above only covers the
    # top-level data.values; a layer-local / nested ``data`` block would plot data
    # that escapes it (the dual-axis layer-replacement loophole). All plotted data
    # must come from the single verified top-level block.
    nested = _nested_data_paths(mt_spec)
    if nested:
        raise InvariantError(
            f"{misleader_id}: data defined below the root (escapes the data hash): {nested}"
        )

    # (2) Only allowed paths differ.
    changed = _diff_paths(clean_spec, mt_spec)
    # The data block is validated by the hash above; its paths are not part of
    # the scale/encoding/color/layer surface and must not count as violations.
    changed = {p for p in changed if p != "data" and not p.startswith("data.")}
    disallowed = sorted(p for p in changed if not _is_allowed(p, misleader.allowed_changed_keys))
    if disallowed:
        raise InvariantError(
            f"{misleader_id}: changed paths outside allowed_changed_keys: "
            f"{disallowed} (allowed: {sorted(misleader.allowed_changed_keys)})"
        )

    # (3) The misleader's distortion is actually present.
    if not misleader.effect(mt_spec):
        raise InvariantError(
            f"{misleader_id}: effect predicate not satisfied (distortion absent)"
        )
