# Empty and needs-review trials: diagnosis and fix (2026-10-23)

## Terms

- **Unscored / needs_review:** a trial whose answer could not be graded (for multiple choice, it did not start with a single option letter). The CSV writes `correct=needs_review`.
- **Empty response:** the model's last reply had no answer text and no tool call (`stop=empty_response`).
- **Tool call as answer:** the last reply's text was a tool call such as `{"name": "evaluate", "arguments": {...}}</tool_call>`, graded as an answer and left unscored.
- **Thinking:** the separate reasoning field qwen3-vl returns through Ollama, next to the answer (`content`).
- **Recovered call:** a tool call that the fixed agent parses out of the thinking or the answer and runs.
- **Repair prompt:** a short user message the fixed agent sends when a reply has neither an answer nor a runnable call.
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

- `browser_agent.recover_tool_call` parses a `{"name": ..., "arguments": ...}` call that ends the thinking (only when there is no answer) or makes up the whole answer, with or without `<tool_call>` tags or a code fence. A call that is only mentioned mid-reasoning is not run, a final answer always wins over a call in the thinking, and only enabled tools are accepted. A call whose start was cut off is accepted when the name fragment ends exactly one tool name.
- When a reply has neither an answer nor a runnable call, the agent sends one repair prompt ("call a tool through the tool-calling interface, or reply with only the final answer"), at most twice per trial; each counts as a step.
- `notes` records `recovered_calls=<n>; repair_prompts=<n>`, the trace stores which calls were recovered, and `--no-tool-call-repair` restores the old behavior (`tool_call_repair=off`).
- `evaluate` reruns a script that fails with "Illegal return statement" as `(() => { ... })()`.
- `dom` reports "No element matches selector" immediately, returns the first of several matches with a count line, and reads `html` for an empty selector.
- Tests: 6 new unit tests and an extended browser test; all 61 tests pass with `RUN_BROWSER_TESTS=1`.

## 4. Replay against the real failures

The recovery code was run on the last reply of each of the 353 unscored traces.

| outcome under the fix | trials |
|---|---|
| tool call recovered from thinking | 277 |
| tool call recovered from the answer | 63 |
| repair prompt (call text present but not valid JSON, e.g. JavaScript string concatenation or `\'` escapes) | 7 |
| unchanged (5 timeouts, 1 step limit) | 6 |

**Analysis:** 340 of 353 unscored trials would continue with the call the model meant to make, and 7 more get a second chance. This shows the parse works on the real outputs; it does not show how many of those trials will end with a scored answer, because the model can fail again on a later step. Only a rerun answers that.

## 5. What this means for the next run

- Rerun with a fresh results file: repaired and unrepaired results are not comparable, and the resume key does not include this setting.
- Per the Oct 20 report, the 129 real-dataset cells and 120 reasoning cells lost to an unscored side, including all 20 real-dataset TM trials that read the hidden text, should become measurable.
- The 5 timeouts (persona on Steam, `2016_2017_change`, first call) are not addressed. A cap on generated tokens (`num_predict`) would turn them into short replies instead of 180 s timeouts; not done here.
