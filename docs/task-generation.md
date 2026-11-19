# Task generation pilot

This pipeline generates tasks only. It does not generate attacks, pages, or evaluation results.
Netflix is the initial dataset. Four task primitives are supported: Retrieve Value,
Find Extremum, Filter, and Compute Derived Value. Views count titles by release year
or rating within explicit inclusive release-year ranges and optional content-type filters.
Missing categories and misplaced duration strings in rating are excluded.

```bash
python task_generation.py --count 100 --seed 42
python task_generation.py --mode bedrock --model MODEL_ID --count 100 --output tasks/generated/netflix-bedrock.json
```

Bedrock mode reads literal credentials from `.env` (never sources it as shell code).
Existing environment values take precedence. Model ID may alternatively be supplied
as BEDROCK_MODEL_ID. It uses the existing `bedrock_backend` Converse client.

Code constructs a validated menu of task designs and computes every answer. The LLM
selects designs from that menu in batches of ten; it cannot invent calculations or
change task meaning. This deliberately constrained pilot does not support unrestricted
LLM-authored question wording. Invalid responses are retried at most three times;
API errors stop the run. There is no silent offline fallback. Bedrock backend may also
retry transient service errors. Budget is ten successful calls for 100 cases, at most
30 calls for invalid selection responses (excluding transport retries).

Each case includes the exact view data, filters, operation, answer, shuffled options,
named misreadings, and a computed solution with source hash and selected-row digest.
Option letters are seeded; task identity is independent of option order. Wrong options
must be distinct from truth and each other. Extremum ties are rejected. Template
selection balances primitives. Bedrock is requested to balance its selections but
its final distribution can vary. Neither mode produces duplicate task IDs.

The sibling `.trace.jsonl` stores prompts, raw replies, model, seed and token usage.
Seeds control local sampling only; Bedrock output is not guaranteed reproducible.
Keep the trace to reproduce the chosen task list. Failed runs preserve their trace
but do not write a partial dataset. Output is replaced only after all tasks succeed.
Solutions are evaluator material and must not later be served to the tested agent.

The data is a catalog snapshot, not a history of Netflix availability. Release year
means release year, not year added to Netflix. Counts describe this CSV only.

## Verified pilot

`tasks/generated/netflix-bedrock.json` contains 100 unique cases selected with
`us.anthropic.claude-sonnet-5-5`, seed 42: 26 Retrieve Value, 25 Find Extremum,
25 Filter, and 24 Compute Derived Value. Ten Converse requests used 33,174 input
and 5,342 output tokens. The sibling trace preserves each prompt and response.
All 100 solutions and distractors were independently recomputed from the CSV;
the seven pipeline tests passed. Run them with:

```bash
python -m unittest discover -s tests -p test_task_generation.py -v
```

These files are evaluator artifacts: answer fields, option IDs, misreading tags,
and solutions must be removed from any future agent-facing projection. No bait
is selected until an attack is matched in a later stage. This pilot favors high-count
categories and overlapping time windows; 100 unique tasks are not 100 independent
datasets. It provides task generation only, not a validated rendered benchmark.
