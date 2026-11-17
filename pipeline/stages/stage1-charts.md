# Stage 1.2 — four clean charts for a verified QA (STAGE1_CHARTS)

Human-authored source of truth for stage 1.2 of the paired pipeline (see
`docs/superpowers/specs/2026-11-16-paired-trap-pipeline-design.md`, "Pipeline
stages"). Stage 1.1 (`stage1-qa.md`) already produced and SQL-verified the question,
options and correct answer; this prompt is given that fixed QA and authors the four
chart types. The generator appends the verified QA, the CSV schema + sample, and the
chart few-shots (`pipeline/examples/charts/manifest.json` + one PNG per type).

The code keeps each chart type that renders non-blank; each becomes one TT instance
sharing the QA. No QA, options, answer or SQL are produced here — only `charts`.

<!-- PROMPT:START -->
You are given a VERIFIED multiple-choice question about a tabular dataset, its four
options, and the correct answer. Author a Vega-Lite v5 chart for EACH of the four
chart types so a reader could answer THIS question from each chart.

Rules:
- Produce ALL FOUR chart types: "bar", "line", "scatter", "stacked_bar". Do not omit
  any. Each MUST be a complete, valid Vega-Lite v5 spec with its data embedded inline
  under `data.values`.
- Every chart MUST let a reader answer the given question by reading the chart (the
  correct answer must be visible/derivable from what is plotted).
- The four charts need NOT share the same fields or encodings. When a raw single
  attribute does not suit a chart type, DERIVE or aggregate appropriate quantities so
  that type still works and still shows the answer — counts/percentages per category,
  group means or rates, binned distributions, or an ordered index on the x-axis for a
  line. Derived numeric fields are encouraged where they make a chart type genuinely
  answerable. Construct answerable data for a type rather than omitting it.
- Chart titles, subtitles, axis labels and annotations MUST NOT state or reveal the
  answer value or which option is correct — a reader must read the chart to answer,
  not read the answer off a label.
- Match the structure and field typing of the chart examples provided; write your own
  data values.

Respond with a single JSON object and nothing else:
{
  "charts": { "bar": {...}, "line": {...}, "scatter": {...}, "stacked_bar": {...} }
}
<!-- PROMPT:END -->
