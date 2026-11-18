# Running Qwen3-VL on the chart-spread selection (MSI / Agate)

This runs the **vision** Qwen3-VL target against the **exact same balanced
selection** the Bedrock Haiku/GPT runs used, so Qwen results are apples-to-apples.

## What to copy to Agate

From this repo, copy the whole repo (or at least):

- `runs/chartspread/instances/` — the rendered pages (required)
- `runs/chartspread/specs.jsonl`
- `runs/chartspread/eval_selection_matched.json` — the 1,430-instance balanced selection
- `pipeline/`, `deploy/msi/`, and the repo-root modules (`browser_agent.py`,
  `browser_environment.py`, `memory.py`, `run_attack_suite.py`)

```bash
# from your laptop, e.g.
rsync -av --exclude 'runs/chartspread/cache' \
  Viz-Agent-Attack/ <user>@agate.msi.umn.edu:~/Viz-Agent-Attack/
```

> The `cache/` dir is Bedrock generation cache — not needed for eval, skip it.

## Launch (one sbatch)

```bash
cd ~/Viz-Agent-Attack
sbatch --export=ALL,\
QWEN_MODEL=qwen3-vl:8b,\
CORPUS_DIR=$PWD/runs/chartspread,\
SELECT_FILE=$PWD/runs/chartspread/eval_selection_matched.json,\
OUT_DIR=$PWD/runs_msi/chartspread-qwen3vl8b,\
REPETITIONS=1 \
  deploy/msi/run_eval.slurm
```

- `SELECT_FILE` → scores only the 1,430 selected instances (not the full 72k corpus).
- `OUT_DIR` is stable → the job is **resumable**: if it times out, just `sbatch`
  the same line again and it continues (already-recorded trials are skipped).
- Qwen3-VL is a vision agent, so no Bedrock/AWS key is needed here — only a local
  Ollama server (the slurm script pulls the model) and working Playwright/Chromium.

## Expected cost

~1,430 trials on one GPU. At the 8b tag expect this to run for several hours; the
resumable design means a 4-8h wall limit with requeue is fine.

## Bring results back

```bash
rsync -av <user>@agate:~/Viz-Agent-Attack/runs_msi/chartspread-qwen3vl8b/trial_results.csv \
  runs/chartspread/eval/qwen3-vl-8b/trial_results.csv
```

Then the same report script scores Qwen alongside Haiku/GPT:

```bash
PYTHONPATH=. python3 report_chartspread.py runs/chartspread haiku-5-5 gpt-5-6-luna qwen3-vl-8b
```
