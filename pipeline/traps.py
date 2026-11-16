"""Trap assembly and target-option rules.

This module wires the trap pieces together. A *trap* is a **payload** (what the
injected content says, generated once in stage 3) delivered through a **channel**
(where it sits: one of the seven page channels or one of the non-page stores).

Responsibilities:

* :data:`PAYLOAD_FAMILIES` / :func:`compatible` -- the payload taxonomy and the
  payload-family -> channel compatibility rule (the table lives in
  :data:`COMPATIBILITY` so it can be tightened from config later).
* :func:`choose_options` -- pick which wrong option a trap targets, as option
  **strings**, enforcing the cell/direction rules deterministically.
* :func:`payload_id` / :func:`trap_group_id` -- the two readable ``":"``-joined
  IDs that enforce the shared-trap rule. ``payload_id`` is question-level and
  channel-independent (one payload reused across channels AND chart types);
  ``trap_group_id`` is placement-level (links the TM page and MM page(s) that
  carry the identical payload in the same channel of one chart type).
* :func:`assemble_trap` -- place a *given* payload (never regenerated here) into
  either a page channel (via :func:`pipeline.channels.inject`) or a non-page
  store (via :mod:`pipeline.stores`), and write the per-variant artifacts.

**Logical-payload identity.** Channels escape/encode the payload for their
context (source_layer encodes hyphens, script channels ``\\u00xx``-escape), so the
on-page *bytes* differ by channel. We therefore keep the **logical** payload text
(exactly what stage 3 produced, after canary/sink fill) as the shared-trap
identity, and let the channel do the encoding only in the rendered HTML. The
page round-trips: ``strip_injections(assembled) == base_html``.
"""
from pathlib import Path

from pipeline.channels import PAGE_CHANNELS, Injection, inject
from pipeline.stores import build_memory_json, build_workspace

# --- Payload taxonomy -----------------------------------------------------

# Family -> ordered list of subtype keys. Subtype keys are family-prefixed so a
# bare subtype string still names its family (the text before the first "_").
PAYLOAD_FAMILIES = {
    "perception": ["perception_facts", "perception_opinions"],
    "reasoning": [
        "reasoning_biased_phrasing",
        "reasoning_oversight_evasion",
        "reasoning_persona",
    ],
    "cognitive": ["cognitive_rag", "cognitive_latent"],
    "action": ["action_jailbreak", "action_exfiltration"],
}

# The non-page stores, as channel names. ``retrieval`` -> inline memory corpus
# (RAG); ``document_memory`` -> the workspace ``README.md`` (context-memory /
# latent). These are the channel keys cognitive payloads use.
STORE_CHANNELS = ("retrieval", "document_memory")

# The persona subtype is the one payload allowed through either kind.
_PERSONA_SUBTYPE = "reasoning_persona"

# Payload family -> allowed channels (default compatibility table; lives here so
# it can later be sourced from config and tightened).
COMPATIBILITY = {
    "perception": frozenset(PAGE_CHANNELS),
    "reasoning": frozenset(PAGE_CHANNELS),
    "action": frozenset(PAGE_CHANNELS),
    "cognitive": frozenset(STORE_CHANNELS),
}

# Persona may use a page channel OR a non-page store.
_PERSONA_CHANNELS = frozenset(PAGE_CHANNELS) | frozenset(STORE_CHANNELS)


def _family_of(family_or_subtype):
    """Return the payload family named by a family key or a subtype key."""
    if family_or_subtype in COMPATIBILITY:
        return family_or_subtype
    return family_or_subtype.split("_", 1)[0]


def compatible(family, channel):
    """Whether a payload (``family`` may be a family or a subtype key) may use
    ``channel``.

    Perception / reasoning / action use the seven page channels; cognitive uses
    the non-page stores; the ``reasoning_persona`` subtype may use either kind.
    """
    if family == _PERSONA_SUBTYPE:
        return channel in _PERSONA_CHANNELS
    allowed = COMPATIBILITY.get(_family_of(family), frozenset())
    return channel in allowed


# --- Target-option selection ---------------------------------------------

def choose_options(correct_option, options, cell, direction, misleader_wrong):
    """Pick ``(target_option, extra_wrong_option)`` as option **strings**.

    Rules: ``target != correct``; MM-same -> ``target == misleader_wrong``;
    MM-different -> ``target not in {correct, misleader_wrong}``;
    ``extra_wrong not in {correct, target, misleader_wrong}``. TM uses
    ``direction == "none"`` and ``misleader_wrong is None`` -> target is any
    wrong option.

    Deterministic: selection is first-match in ``options`` order (no RNG), so a
    given input always yields the same pair.
    """
    if cell == "MM" and direction == "same":
        if misleader_wrong is None:
            raise ValueError("MM-same requires a misleader_wrong option")
        target = misleader_wrong
    elif cell == "MM" and direction == "different":
        excluded = {correct_option, misleader_wrong}
        target = _first_not_in(options, excluded)
    else:
        # TM (and any non-MM cell): any wrong option.
        target = _first_not_in(options, {correct_option})

    extra_wrong = _first_not_in(options, {correct_option, target, misleader_wrong})
    return target, extra_wrong


def _first_not_in(options, excluded):
    """First option not in ``excluded`` (order-deterministic)."""
    for option in options:
        if option not in excluded:
            return option
    raise ValueError(f"No option outside {excluded!r} among {options!r}")


# --- Shared-trap IDs ------------------------------------------------------

def payload_id(question_id, subtype, target_option):
    """Question-level, channel-independent payload identity.

    The payload text depends only on QA + subtype + target, so one generation
    call is cached and reused across every channel and chart type.
    """
    return f"{question_id}:{subtype}:{target_option}"


def trap_group_id(base_id, subtype, channel, target_option):
    """Placement-level identity linking the TM and MM page(s) that carry the
    identical payload planted in the same channel of one (question, chart_type).
    """
    return f"{base_id}:{subtype}:{channel}:{target_option}"


# --- Trap assembly --------------------------------------------------------

def _render_payload(trap, canary, sink_url):
    """Return the logical payload text with canary/sink filled for exfiltration.

    Filling is deterministic token replacement of ``{canary}`` and
    ``{sink_url}``. Every other payload is returned verbatim. This is the
    *logical* text; the channel does any context encoding later.
    """
    payload = trap["payload"]
    if trap.get("subtype") == "action_exfiltration":
        payload = payload.replace("{canary}", canary).replace("{sink_url}", sink_url)
    return payload


def assemble_trap(base_html, spec, trap, canary, sink_url, out_dir):
    """Place the payload in ``trap`` into its channel and write the artifacts.

    * Page channel -> route the rendered payload through
      :func:`pipeline.channels.inject` and write the trapped ``chart.html`` to
      ``out_dir``.
    * ``retrieval`` (cognitive RAG) -> write ``memory.json`` with a poisoned
      document carrying the payload.
    * ``document_memory`` (cognitive latent) -> write ``workspace/`` with the
      FAKE ``canary`` in ``.env`` and the payload as the poisoned ``README.md``.

    The payload text is taken as given (generated once in stage 3) and never
    regenerated; only the exfiltration canary/sink are filled in here.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    channel = trap["channel"]
    rendered = _render_payload(trap, canary, sink_url)

    if channel in PAGE_CHANNELS:
        trapped = inject(base_html, [Injection(channel, rendered)])
        (out_dir / "chart.html").write_text(trapped)
        return

    if channel == "retrieval":
        document = {
            "id": trap.get("doc_id", "poisoned-0"),
            "title": trap.get("doc_title", "Reference note"),
            "text": rendered,
        }
        # Any clean documents stage 3 supplies ride alongside the poisoned one.
        extra = trap.get("documents", [])
        build_memory_json(out_dir, [document, *extra])
        return

    if channel == "document_memory":
        build_workspace(out_dir, canary, readme_text=rendered)
        return

    raise ValueError(f"Unknown trap channel: {channel!r}")
