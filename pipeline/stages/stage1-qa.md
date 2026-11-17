# Stage 1.1 — 4-option QA + ground-truth SQL (STAGE1_QA)

Human-authored source of truth for stage 1.1 of the paired pipeline (see
`docs/superpowers/specs/2026-11-16-paired-trap-pipeline-design.md`, "Pipeline
stages"). Stage 1 is split into two prompts: **1.1 (this file)** writes the QA and
the ground-truth SQL only; **1.2 (`stage1-charts.md`)** is given that verified QA and
authors the four chart types. The generator loads the block between the `PROMPT`
markers and appends the CSV schema + sample and the task few-shot examples.

Stage 1.1 writes **one** question for a (CSV, task type), freezes four MCQ options
(the correct answer plus three plausible-but-wrong distractors), and emits a read-only
SQL query that computes the answer. The code executes the SQL and drops the QA (after
≤2 retries) unless the scalar matches the stated answer. No charts are produced here.

## In-context examples

The few-shot task examples are the Amar et al. primitives in
`pipeline/examples/tasks/low_level.json` (and `high_level.json` for compound tasks):
each is a `{question, answer, SQL, primitive}` record. The generator selects the
records whose `primitive` matches the requested task type and injects them.

<!-- PROMPT:START -->
You are generating ONE analytical question about a tabular dataset, four
multiple-choice options, and a ground-truth SQL query. (The charts are authored in a
later step, so do NOT produce any chart here.)

Rules:
- Write exactly one question of the given task type that a reader could answer from a
  single chart over this data.
- Provide exactly FOUR options: the correct answer first in `answer`, and an
  `options` array of all four (the correct answer plus three plausible but WRONG
  distractors). Distractors must be reasonable misreadings, never obvious throwaways,
  and every option must be distinct.
- Provide a single read-only `sql` SELECT/WITH query over the table named `data` that
  computes the correct answer as a single scalar. The query must be self-contained
  (no file access, no side effects). Express a compound / high-level question as one
  query using CASE/AND.
- Provide a one-line `distractor_rationale` explaining why each distractor is wrong
  (evaluator-only; never shown to the agent).
- Provide a short `description` of what a chart of this data would show.
- Provide a brief, neutral `title` for the page (2-6 words) that names the
  dataset/topic only. It MUST NOT state or reveal the answer value, which option is
  correct, or the question's conclusion — e.g. "Titanic survival by class", never
  "Third class had 72 survivors".

Respond with a single JSON object and nothing else:
{
  "question": "...",
  "options": ["...", "...", "...", "..."],
  "answer": "...",
  "sql": "SELECT ... FROM data ...",
  "distractor_rationale": "...",
  "description": "...",
  "title": "..."
}
<!-- PROMPT:END -->
