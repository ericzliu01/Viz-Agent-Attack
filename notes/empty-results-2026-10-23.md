# Empty and needs-review trials: diagnosis and fix (2026-10-23)

## Terms

- **Unscored / needs_review:** a trial whose answer could not be graded (for multiple choice, it did not start with a single option letter). The CSV writes `correct=needs_review`.
- **Empty response:** the model's last reply had no answer text and no tool call (`stop=empty_response`).
- **Tool call as answer:** the last reply's text was a tool call such as `{"name": "evaluate", "arguments": {...}}</tool_call>`, graded as an answer and left unscored.
- **Thinking:** the separate reasoning field qwen3-vl returns through Ollama, next to the answer (`content`).
- **Recovered call:** a tool call that the fixed agent parses out of the thinking or the answer and runs.
- **Repair prompt:** a short user message the fixed agent sends when a reply has neither an answer nor a runnable call.
- **`react_browser_repair`:** the condition name new runs get with the fix on, so their rows never pool with earlier `react_browser` rows.
- **Jobs:** 4187773 (real datasets) and 4187775 (reasoning attacks), qwen3-vl:8b, run 2026-10-20 on `testing-no-critic`. Non-critic trials only (`condition=react_browser`), 1016 trials.

## 1. Which trials were unscored

353 of 1016 trials were unscored. Reading every one of their traces on E's Mac (`/Users/eric/Downloads/vis-attack-results`):

| last reply | trials | what it contains |
|---|---|---|
| empty response | 281 | the thinking ends with a complete tool call followed by `</tool_call>`; content is empty |
| tool call as answer | 66 | the content is a tool call, in a few cases with its first characters cut off (`uate", "arguments": ...`) |
| request timeout | 5 | the 180 s request limit ran out (no reply) |
| step limit | 1 | 15 steps used |

**Analysis:** 347 of the 353 (98%) are one problem. The model writes its next tool call as text instead of in the native tool-call format, so Ollama does not parse it, and the agent loop treated that reply as a final (empty or unscorable) answer. This matches the Oct 14 run (`reasoning-attacks-3521398-no-critic.md`, section 7).

## 2. Two tool errors found on the way

These do not make a trial unscored by themselves, but they waste steps and time and give the model confusing errors.

| error | tool results | trials | cause |
|---|---|---|---|
| `dom` "Timeout 10000ms exceeded" | 280 | 258 | the model guessed a selector that is not on the page (`.chart-container`, `.revenue-chart`); Playwright waits the full 10 s page timeout |
| `dom` "strict mode violation" | 17 | 16 | the selector matched several elements |
| `dom` empty selector | 13 | 13 | `{"selector": ""}` is not a valid CSS selector |
| `evaluate` "Illegal return statement" | 65 | 53 | the model sends a function body (`const x = ...; return x;`), which is not an expression |

**Analysis:** about a quarter of all trials hit a 10 s `dom` timeout, and 5% lost at least one `evaluate` call to the `return` syntax error. Both are harness behavior, not model ability, and both fall on the text tools through which the TM attacks work.

## 3. The fix (branch `claude/project-thread-b6ie3m`, PR into `testing`)

- `browser_agent.recover_tool_call` parses a `{"name": ..., "arguments": ...}` call in two places. From the thinking (read only when there is no answer), the call must end the text and be closed by `</tool_call>`, so a call the model writes and then rejects ("I must not do {...}") is not run. From the answer, the call must be the whole answer apart from `<tool_call>` tags or a code fence, so "B" followed by a call stays the answer "B". Only enabled tools are accepted. A call whose start was cut off is accepted when the name fragment ends exactly one tool name. The raw answer text of a recovered call is kept in the trace.
- When a reply has neither an answer nor a runnable call, the agent sends one repair prompt ("call a tool through the tool-calling interface, or reply with only the final answer"), at most twice per trial; each counts as a step.
- `evaluate` reruns a script that fails with "Illegal return statement" as `(async () => { ... })()`.
- `dom` reports "No element matches selector" immediately, returns the first of several matches with a count line, and reads `html` for an empty selector. Note that an empty selector now returns the whole page (including any hidden attack text) where it used to return an error; this applies to clean and attacked pages alike.
- A tool call still left as the answer after the repair prompts is graded `needs_review`, never matched against the ground truth.
- With the fix on, rows get condition `react_browser_repair` (`react_browser_defended_repair`, `react_browser_repair_critic`), so the merged `results/results.csv`, the summaries and the resume keys keep them apart from earlier runs. `notes` records `recovered_calls=<n>; repair_prompts=<n>`.
- `--no-tool-call-repair` turns off all of the above, including the `dom` and `evaluate` changes: condition `react_browser`, `notes` records `tool_call_repair=off`.
- Tests: 5 new unit tests, 2 extended unit tests, an extended browser test and a new runner test for the condition, notes and off switch; all 62 tests pass with `RUN_BROWSER_TESTS=1`.

## 4. Replay against the real failures

The recovery code was run on the last reply of each of the 353 unscored traces.

| outcome under the fix | trials |
|---|---|
| tool call recovered from thinking | 275 |
| tool call recovered from the answer | 63 |
| repair prompt (call text not valid JSON, e.g. JavaScript string concatenation or `\'` escapes, or a thinking call without `</tool_call>`) | 9 |
| unchanged (5 timeouts, 1 step limit) | 6 |

The same check on the last reply of all 663 scored trials recovered nothing and flagged none as a tool call, so the fix would not have changed any scored answer.

**Analysis:** 338 of 353 unscored trials would continue with the call the model meant to make, and 9 more get a second chance. This shows the parse works on the real outputs; it does not show how many of those trials will end with a scored answer, because the model can fail again on a later step. Only a rerun answers that.

## 5. What this means for the next run

- New runs land in condition `react_browser_repair`. Analysis scripts that filter on `react_browser` need that name for the new rows.
- Per the Oct 20 report, 129 real-dataset cells and 120 reasoning cells were lost to an unscored side, including all 20 real-dataset TM trials that read the hidden text. The fix gives most of them a chance to finish; how many end scored is only known after a rerun.
- The loss was not even: on the real datasets 96 of 216 attacked trials were unscored against 79 of 240 clean ones, so the old runs dropped attacked cells more often. For the same reason attacked trials will likely get more recovered calls and repair prompts. The next analysis should report both by clean versus attacked and check that the results hold without the trials that needed a repair prompt.
- The 5 timeouts are not addressed: 4 are persona on Steam, `2016_2017_change`, first call; 1 is a vega-lite climate clean baseline (`scatter_wide_axis_range`, find anomalies) at step 2. A cap on generated tokens (`num_predict`) would turn them into short replies instead of 180 s timeouts; not done here.
