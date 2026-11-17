# Stage 1 — clean chart + 4-option QA (STAGE1)

Human-authored source of truth for stage 1 of the paired pipeline (see
`docs/superpowers/specs/2026-11-16-paired-trap-pipeline-design.md`, section
"Pipeline stages"). The generator (`pipeline/generate.py`) loads the block
between the `PROMPT` markers as the instruction text and appends the dynamic
context (the CSV schema + sample, the task type, and the few-shot examples drawn
from `pipeline/examples/tasks/` and `pipeline/examples/charts/`).

Stage 1 writes **one** question for a (CSV, task type), freezes four MCQ options
(the correct answer plus three plausible-but-wrong distractors), emits a
ground-truth SQL query over the table named `data`, and authors one Vega-Lite
chart spec per applicable chart type. The code then (a) executes the SQL
read-only and drops the instance unless the result matches the stated answer,
and (b) keeps only the chart types that both pass the data-shape applicability
rule and render non-blank. The surviving chart types fan out into one TT
instance each, all sharing the question, options, correct answer and SQL.

## In-context examples

The few-shot task examples are the Amar et al. primitives in
`pipeline/examples/tasks/low_level.json` (and `high_level.json` for compound
tasks); the chart examples are the Flint-gallery specs catalogued in
`pipeline/examples/charts/manifest.json`. Each is a `{question, answer, SQL,
primitive}` record over one table (`titanic`, `cars`, `penguins`, `wines`,
`gapminder`). The generator selects the records whose `primitive` matches the
requested task type and injects them ahead of the prompt.

<!-- PROMPT:START -->
You are generating ONE analytical question about a tabular dataset, four
multiple-choice options, a ground-truth SQL query, and a Vega-Lite chart for
each chart type that fits the data.

Rules:
- Write exactly one question of the given task type that a reader could answer
  from a single chart over this data.
- Provide exactly FOUR options: the correct answer first in `answer`, and an
  `options` array of all four (the correct answer plus three plausible but
  WRONG distractors). Distractors must be reasonable misreadings, never obvious
  throwaways, and every option must be distinct.
- Provide a single read-only `sql` SELECT/WITH query over the table named
  `data` that computes the correct answer as a single scalar. The query must be
  self-contained (no file access, no side effects). Express a compound /
  high-level question as one query using CASE/AND.
- Provide a one-line `distractor_rationale` explaining why each distractor is
  wrong (evaluator-only; never shown to the agent).
- Provide a short `description` of what the chart shows.
- Provide a `charts` object mapping each applicable chart type (any of "bar",
  "line", "scatter", "stacked_bar") to a complete, valid Vega-Lite v5 spec that
  visualises the data this question is about. Each spec MUST embed the data
  inline under `data.values`. Only include chart types that genuinely suit the
  data shape; omit the rest.
- Chart titles, subtitles, axis labels, and annotations MUST NOT state or reveal
  the answer value or which option is correct. The title must describe the chart
  neutrally (what it shows, not the conclusion). For example, never title a chart
  "91 first-class female passengers survived" or otherwise embed the answer — a
  reader must have to read the chart to answer the question, not read it off the
  title.

Respond with a single JSON object and nothing else:
{
  "question": "...",
  "options": ["...", "...", "...", "..."],
  "answer": "...",
  "sql": "SELECT ... FROM data ...",
  "distractor_rationale": "...",
  "description": "...",
  "charts": { "bar": { ...vega-lite... }, "line": { ... } }
}
<!-- PROMPT:END -->

## Output section by library

The output contract above targets `vega-lite` (the only v1 library). The
`library` argument selects this section; another library would swap in its own
spec dialect under `charts` while the QA/SQL contract is unchanged.
