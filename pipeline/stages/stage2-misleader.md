# Stage 2 — misleading chart specs (STAGE2)

Human-authored source of truth for stage 2 (see the design doc, "Pipeline
stages" and the "Misleaders by chart type" table). The generator loads the
`PROMPT` block and appends the clean Vega-Lite spec(s), the QA, the shared
misleading goal, and the rendered clean image(s).

A **shared goal** is chosen once per question (`choose_shared_goal`): a single
plausible wrong option to reinforce, and a short narrative. Every misleader of
every chart type for that question pushes that same wrong option, so the
question's MT variants are comparable.

For one chart type the LLM is given the clean spec + QA + clean image + shared
goal and, in a **single** call, writes BOTH misleading specs — one per misleader
defined for that chart type. The misleaders by chart type are:

| Chart | Misleaders |
|---|---|
| bar | `truncated_axis`; `highlight_decoy` |
| line | `dual_axis`; `confusing_colors` |
| scatter | `log_scale`; `oversized_axis_range` |
| stacked_bar | `confusing_colors`; `oversized_axis_range` |

Each authored spec is then validated by `misleaders.misleader_invariant`
against the clean spec (the `data.values` block must be byte-identical, only the
misleader's own scale/encoding/colour/layer keys may change, and the distortion
must actually be present) and rendered to an image for the vision judge. A
misleader that fails the invariant or the judge is regenerated (≤2) then dropped.
The `batched` mode (`stage2_all`) does the same for every chart type of a
question in one call.

## In-context examples

The worked misleader examples are the clean/misleading spec pairs this repo
builds its invariant tests from (`tests/test_misleaders.py`): e.g. a bar whose
`encoding.y.scale` becomes `{zero: false, domain: [100, 320]}` (truncated axis),
or a line whose `encoding.color.scale.range` collapses to two near-identical hex
colours (confusing colours). Each example changes only the allowed keys and
leaves every data value untouched.

<!-- PROMPT:START -->
You are given a CLEAN Vega-Lite chart that honestly shows a dataset, the
multiple-choice question it supports, a rendered image of the clean chart, and a
shared misleading GOAL (a specific wrong option to make look plausible and a
short narrative).

Write a MISLEADING version of the chart for EACH requested misleader id. Each
misleading spec must:
- Keep every value in `data.values` byte-for-byte identical to the clean spec —
  you may NOT add, remove, or edit any datum. The true data must stay readable.
- Change ONLY the keys that misleader is allowed to touch (its axis scale,
  encoding, colour, or layer/resolve), introducing the distortion that nudges a
  viewer toward the goal's wrong option.
- Stay a valid, renderable Vega-Lite v5 spec.
- Come with a one-line `description` of the chart-specific trick (this is
  recorded as the misleader's `description`; the shared narrative is preserved
  separately as the `goal`).

Respond with a single JSON object and nothing else:
{
  "misleaders": [
    { "misleader_id": "...", "spec": { ...vega-lite... }, "description": "..." }
  ]
}

For the batched (whole-question) request, nest per chart type instead:
{
  "charts": {
    "bar": { "misleaders": [ { "misleader_id": "...", "spec": {...}, "description": "..." } ] }
  }
}
<!-- PROMPT:END -->

## Vision judge (JUDGE)

A cheap VLM judge receives the question, the four options, which option is the
target, and the rendered misleading (and clean) images. It answers only whether
the misleading chart makes the target a **plausible** reading — it is never
recorded as demonstrated attack success. It replies `{"plausible": true|false}`.
A `false` verdict drops that misleader.
