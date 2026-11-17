# Running the Viz-Agent-Attack eval on MSI (Agate) against local Ollama Qwen3-VL

This directory deploys the **evaluation** half of the pipeline to UMN MSI's Agate
HPC and runs it against a **local Ollama Qwen3-VL** target on a GPU node.

- It only **evaluates** a pre-generated corpus (an instances tree like
  `runs/pilot10`, produced locally with Bedrock). It does **not** generate.
- Because it does not generate, **no AWS/Bedrock key is needed on MSI** — only
  Playwright + Chromium, the repo's Python deps, and Ollama.
- The agent renders each served `chart.html` with **headless Playwright
  Chromium**, so the GPU/compute node must have Chromium working headless. This
  is the single biggest HPC risk — see Troubleshooting.

Files here:

| File | Purpose |
|------|---------|
| `setup_env.sh`  | One-time, idempotent env bootstrap (python module, venv, deps, Playwright+Chromium, Ollama download). |
| `eval_entry.py` | Thin entrypoint that calls `pipeline.eval_runner.run_eval` with the Ollama agent. |
| `run_eval.slurm`| The sbatch job: start `ollama serve`, pull the model, run the eval, stop the server. |
| `README.md`     | This runbook. |

---

## (a) Get the repo + a corpus onto MSI

From your laptop (or wherever the repo + a generated corpus live):

```bash
# 1. Repo onto MSI (clone once, then `git pull` to update).
ssh <user>@agate.msi.umn.edu            # or the ahl01 login node
cd ~/   # or a project dir
git clone <REPO_URL> Viz-Agent-Attack
cd Viz-Agent-Attack
# (on later runs just: git pull)

# 2. Copy a generated corpus (instances tree) onto MSI, from your laptop:
#    an instances tree is a dir containing grader.json files nested under it
#    (run_eval discovers them recursively). e.g. runs/pilot10.
rsync -avz --progress runs/pilot10/ <user>@agate.msi.umn.edu:~/Viz-Agent-Attack/runs/pilot10/
#    (scp -r works too). The `vendor/` dir is tracked in git, so a clone/pull
#    already has the Vega libs the charts need — you do NOT copy vendor separately.
```

Confirm `vendor/` is present after clone (the served charts load `/vendor/*`):

```bash
ls vendor/   # should list vega-*.min.js, vega-lite-*, d3*, plotly*, chart*
```

## (b) Build the environment (login or interactive node)

Run on the **login node** `ahl01` (downloads only; light) or an interactive node:

```bash
cd ~/Viz-Agent-Attack
# Edit the PLACEHOLDERS at the top of the script first if needed (PYTHON_MODULE!).
bash deploy/msi/setup_env.sh
```

It will `module load` a modern Python, create `~/viz-agent-venv`, install the
deps + Playwright Chromium, download Ollama to `~/ollama`, and **verify headless
Chromium actually launches**. Read its final SUMMARY. If `chromium launch` is not
`OK`, fix it (Troubleshooting) before submitting the job — it will otherwise fail
on the GPU node.

To override defaults (e.g. the python module name):

```bash
PYTHON_MODULE=python/3.10 VENV_DIR=$HOME/viz-agent-venv bash deploy/msi/setup_env.sh
```

## (c) Submit the job

Edit `deploy/msi/run_eval.slurm` and set at minimum `--account=` (your MSI
allocation). Then:

```bash
cd ~/Viz-Agent-Attack          # submit from the repo root
sbatch deploy/msi/run_eval.slurm
```

Override settings at submit time without editing the file:

```bash
sbatch --export=ALL,QWEN_MODEL=qwen3-vl:8b,CORPUS_DIR=$PWD/runs/pilot10,REPETITIONS=3 \
       deploy/msi/run_eval.slurm
```

## (d) Monitor

```bash
squeue --me                                   # or: squeue -u $USER
tail -f deploy/msi/logs/slurm-<jobid>.out     # job log (append-mode on requeue)
tail -f deploy/msi/logs/ollama-<jobid>.log    # ollama server log
# progress = number of recorded trials:
wc -l runs_msi/pilot10-ollama/trial_results.csv   # (minus 1 header row)
```

## (e) Resume

The job is resume-safe: the results dir (`OUT_DIR`) is **stable** (no job-id in
the path) and `run_eval` appends+flushes each trial to `trial_results.csv`,
skipping any `(instance_id, repetition)` already recorded. So after a timeout,
preemption, or crash, **just resubmit the same command**:

```bash
sbatch deploy/msi/run_eval.slurm
```

It continues where it left off. The only lost work is the single trial that was
in flight when the job was killed; it is re-run on resume. `--requeue` is set, so
SLURM may also auto-requeue on preemption.

## (f) Where results land

Under `OUT_DIR` (default `runs_msi/<corpus>-ollama/`, relative to the repo root):

- `trial_results.csv` — one row per (instance, repetition) trial. Columns:
  `instance_id, base_id, question_id, cell, direction, misleader_id, subtype,
  channel, model, repetition, seed, correct_option, target_option,
  predicted_option, status, latency_ms, trace_path`.
- `run_config.json` — frozen run config (model, seed, repetitions, planned
  instance count, plus host/job-id/target metadata from `eval_entry.py`).
- `traces/<hex>/trace.json` (+ screenshot PNGs) — a saved trace per trial.

Analyze/summarize these with the repo's existing tooling (e.g.
`summarize_results.py`) the same way as a local run.

---

## (g) Troubleshooting / Assumptions to confirm

Everything below is a **placeholder or risk you must verify on MSI** — the author
could not log in (interactive Duo auth required), so these are documented, not
tested there.

### Placeholders to fill in

| What | Where | How to resolve |
|------|-------|----------------|
| **Python module name** | `PYTHON_MODULE` in `setup_env.sh` **and** `run_eval.slurm` (default `python3.10`) | System `python3` is **3.6.8 — too old**. Run `module avail python` on MSI and set the exact 3.10+ module string (could be `python3.10`, `python/3.10`, a conda module, etc.). |
| **SLURM account** | `#SBATCH --account=PLACEHOLDER_ACCOUNT` in `run_eval.slurm` | Your allocation/group. Find with `groups`, `sacctmgr show assoc user=$USER format=account`, or ask your PI. The job will be rejected without a valid account. |
| **Partition / GPU** | `#SBATCH --partition=a100-4`, `--gres=gpu:1` | Default `a100-4` + 1 GPU suits an 8B VL model. Alternatives (all cap 24h): `a100-8`, `v100` (`--gres=gpu:v100:1`), `msigpu` (a100/v100/h100). Check with `sinfo` / MSI docs. |
| **Ollama model tag** | `QWEN_MODEL` (default `qwen3-vl:8b`) | Confirm the exact tag exists on the Ollama library and that `ollama pull <tag>` works. It must support **vision + tools** (the agent's `check_model_capabilities` enforces this) and fit GPU memory. |
| **Ollama version** | `OLLAMA_VERSION` in `setup_env.sh` (default `v0.6.8`) | Pick a release that ships `qwen3-vl` support from <https://github.com/ollama/ollama/releases>. The `linux-amd64.tgz` asset must exist for that tag. |
| **Model store location** | `OLLAMA_MODELS` in `run_eval.slurm` (default `$HOME/ollama-models`) | Model blobs are multi-GB. If `$HOME` quota is tight, override to scratch, e.g. `/scratch.global/$USER/ollama-models`. Confirm your scratch path. |
| **Corpus path** | `CORPUS_DIR` (default `runs/pilot10`) | Must point at the instances tree you copied in step (a). |
| **Walltime** | `#SBATCH --time=08:00:00` | Must stay **under the 24h partition cap**. Size it to your corpus; the job resumes on requeue, so a shorter wall time is safe. |

### Risks / things that may bite

- **Chromium system libs on compute nodes (biggest risk).** Playwright's
  Chromium needs shared libraries (nss, nspr, atk, cups, libdrm, mesa/GBM, X
  libs, etc.). `playwright install-deps` apt-installs them **but requires root**,
  which you do not have on MSI — `setup_env.sh` attempts it and tolerates the
  failure. No-root fixes, in order of preference:
  1. `module avail` for a mesa / nss / libs module and `module load` it in both
     scripts before launching (prepend to the Python env).
  2. Run the GPU job inside an **Apptainer/Singularity container** that ships the
     libs (and optionally Ollama + the venv). This is the most robust HPC path;
     if the raw-venv approach fails at the browser step, containerize.
  3. Install missing libs into a user prefix (e.g. via conda-forge: `nss`,
     `nspr`, `mesa-libgbm`) and set `LD_LIBRARY_PATH`.
  Verify early: `setup_env.sh` step 6 launches headless Chromium and reports OK /
  FAILED. If it fails on the login node, it will fail on the GPU node too.
  Diagnose the exact missing lib with:
  `ldd ~/.cache/ms-playwright/chromium-*/chrome-linux/chrome | grep 'not found'`.
- **No conda / ollama / playwright preinstalled** on MSI — all handled by
  `setup_env.sh` without root (Ollama via release tarball to `$HOME`, not the
  root-requiring `curl | sh` installer).
- **GPU memory vs. model size.** `qwen3-vl:8b` fits a single A100/V100
  comfortably; larger tags need `a100-8` and more `--mem`. If `ollama pull` or
  inference OOMs, pick a smaller tag or a bigger partition.
- **`module` in batch scripts.** Both scripts use `#!/bin/bash -l` (login shell)
  so Lmod's `module` is defined; they also fall back to sourcing
  `/etc/profile.d/lmod.sh`. If your site uses a different init path, add it.
- **Lazy `anthropic` import.** Importing `pipeline.eval_runner` imports
  `pipeline.bedrock_agent`, but its `anthropic` import is lazy, so the Ollama
  path needs no AWS creds. Installing the full `requirements.txt` is still
  simplest and harmless.
- **`srun` / interactive testing.** To debug on a GPU node interactively first:
  `srun --account=<acct> --partition=a100-4 --gres=gpu:1 --cpus-per-task=8 --mem=48G --time=1:00:00 --pty bash -l`
  then run the body of `run_eval.slurm` by hand.
