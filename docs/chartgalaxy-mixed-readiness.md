# Mixed-input pilot readiness — 2026-11-24

The five image channels (`banner`, `footnote`, `overlay`, `low_contrast`,
`cotta`) use direct vision input. The two HTML channels (`visible_paragraph`,
`source_layer`) use browser pages. Auxiliary `cotta_trigger_only` uses direct
images. Each model/question has separate clean baselines for the two modes.
Reporting keeps their rates separate.

**Code and corpus are ready. Haiku and Luna passed preflight. Qwen's webpage
lane remains blocked by the strict JSON gate. The full evaluation has not run.**

## Frozen artifacts

- Evaluation code: `42904742ae740e25192558b51dc5b38a01770596`.
- Study: `chartgalaxy-mixed-pilot-v2`.
- Corpus digest: `88e579f21adaf60351c461a535c050b14e36821f260bf1e869006efc68a99911`.
- Corpus: `runs/qa_attacks/chartgalaxy/mixed-pilot-v2/corpus` (local, ignored).
- 1,776 rows: 48 clean, 192 neutral controls, 1,536 attacks including auxiliary.
- 1,320 direct-image trials and 456 webpage trials per model; 5,328 total
  across the three configured models.
- All image rows decoded and all 456 webpages passed Chromium validation.
- All 1,728 attack/control image sequences are byte-identical to the frozen v1
  sequences. The input-mode revision did not retune payloads or CoTTA pixels.
  `audits/cache-import.json` records source hashes, configuration, and provenance.
- Chromium `159.0.8154.6`, Playwright `1.65.2`;
  paragraph font is bundled and hashed.

## Verification

55 component tests passed. The final 19 integration tests passed using real
Chromium and offline model doubles. They cover direct-image byte order and no
browser creation, screenshot delivery, correct baseline pairing, split report
rates, six-case preflight selection, isolation, bounded JavaScript, retry/resume,
merge validation, and strict grading.

The live preflight contains one preselected choice, numeric, and yes/no question
in each mode per model. These 18 clean trials are separate from study results.
Correct chart answers are not the readiness criterion.

| Model | Direct image | Webpage | Infrastructure errors |
|---|---|---|---:|
| haiku | Pass (3/3) | Pass (3/3) | 0 |
| luna | Pass (3/3) | Pass (3/3) | 0 |
| qwen | Pass (3/3) | Blocked: 2/3 malformed JSON | 0 |

All browser preflight trials received screenshots. Qwen returned bare `B` and
`Yes` for two webpage cases; its third webpage response and all three direct
responses were valid JSON. These are completed behavioral outcomes, not API
errors. They were not retried, repaired, or stripped into JSON. The current
runner blocks the full Qwen job until the strict gate is resolved explicitly.

The earlier Luna/Qwen API failures were caused by placing images inside
`toolResult`, a field with [restricted model support](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ToolResultContentBlock.html).
The revised runner returns the text tool result, then a user image message
linked to the tool call. It uses this same transport for all models. All three
models accepted the revised transport; no model replacement is needed.

Local evidence is in `preflight/summary.json`, each model's `records/` and
`traces/`, and `corpus/validation.json` under the study directory. The local
`corpus/review.html` gallery shows direct inputs and webpage screenshots.
The superseded v1 corpus/preflight and transport diagnostics remain separate.

The [run plan](chartgalaxy-webpage-run-plan.md) contains launch and report commands.
No full-grid attack responses or ASR estimates have been produced for v2.
