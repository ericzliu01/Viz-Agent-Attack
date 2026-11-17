#!/bin/bash -l
# ===========================================================================
# run_eval.slurm -- evaluate a Viz-Agent-Attack corpus against a LOCAL Ollama
# Qwen3-VL target on an MSI (UMN Agate) GPU node.
#
# Submit from the repo root:   sbatch deploy/msi/run_eval.slurm
# Resume after preemption/timeout: just `sbatch` it again -- the results dir is
# stable and run_eval skips trials already in trial_results.csv.
#
# BEFORE FIRST SUBMIT, edit the PLACEHOLDERS marked <<< below (at minimum the
# SLURM account). See deploy/msi/README.md "Assumptions to confirm".
# ===========================================================================
#
#SBATCH --job-name=viz-agent-eval
#SBATCH --account=PLACEHOLDER_ACCOUNT          # <<< REQUIRED: your MSI allocation/group (e.g. the PI's group). Find with `groups` or `sacctmgr show assoc user=$USER`.
#SBATCH --partition=a100-4                      # <<< default a100-4; alternatives: a100-8, v100, msigpu
#SBATCH --gres=gpu:1                            # one GPU is enough for an 8B VL model
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=08:00:00                         # <<< must stay under the 1-00:00:00 (24h) partition cap
#SBATCH --requeue                               # allow automatic requeue on preemption (resume-safe)
#SBATCH --output=deploy/msi/logs/slurm-%j.out
#SBATCH --open-mode=append                      # append on requeue instead of truncating
# (Optional) email: uncomment and set your address.
##SBATCH --mail-type=END,FAIL
##SBATCH --mail-user=pan00342@umn.edu

set -euo pipefail

# ----- Tunables (override at submit time: `sbatch --export=ALL,QWEN_MODEL=... run_eval.slurm`) -----
# PLACEHOLDER: confirm this exact Ollama tag EXISTS (`ollama pull <tag>`) and
# fits one GPU's memory. qwen3-vl:8b matches the repo's references; larger tags
# (e.g. qwen3-vl:32b) need an a100-8 or multi-GPU and more --mem.
QWEN_MODEL="${QWEN_MODEL:-qwen3-vl:8b}"

# Must match setup_env.sh. Override if you changed them there.
PYTHON_MODULE="${PYTHON_MODULE:-python3.10}"   # <<< confirm with `module avail python`
VENV_DIR="${VENV_DIR:-$HOME/viz-agent-venv}"
OLLAMA_DIR="${OLLAMA_DIR:-$HOME/ollama}"

# Corpus to evaluate (an instances tree copied onto MSI). See README step (a).
CORPUS_DIR="${CORPUS_DIR:-$SLURM_SUBMIT_DIR/runs/pilot10}"

# STABLE results dir -> resume-safe. Do NOT put $SLURM_JOB_ID in this path, or a
# requeued/new job would start a fresh (non-resuming) results dir.
OUT_DIR="${OUT_DIR:-$SLURM_SUBMIT_DIR/runs_msi/$(basename "$CORPUS_DIR")-ollama}"

SEED="${SEED:-0}"
REPETITIONS="${REPETITIONS:-1}"

# Ollama server binding + model store. Bind to loopback only (the agent connects
# to 127.0.0.1:11434). Put the (large, multi-GB) model blobs on scratch if your
# $HOME quota is tight -- OVERRIDE OLLAMA_MODELS to a scratch path.
export OLLAMA_HOST="127.0.0.1:11434"
export OLLAMA_MODELS="${OLLAMA_MODELS:-$HOME/ollama-models}"   # <<< consider /scratch.global/$USER/ollama-models
OLLAMA_URL="http://127.0.0.1:11434"
export OLLAMA_URL

# ---------------------------------------------------------------------------
REPO_ROOT="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
mkdir -p "$REPO_ROOT/deploy/msi/logs" "$OUT_DIR" "$OLLAMA_MODELS"
cd "$REPO_ROOT"

echo "=== Viz-Agent-Attack MSI eval job ==="
echo "job id     : ${SLURM_JOB_ID:-<none>}  node: ${SLURMD_NODENAME:-<none>}"
echo "repo root  : $REPO_ROOT"
echo "corpus     : $CORPUS_DIR"
echo "out dir    : $OUT_DIR   (stable -> resumable)"
echo "model      : $QWEN_MODEL"
echo "venv       : $VENV_DIR"
echo "ollama     : $OLLAMA_DIR  (models in $OLLAMA_MODELS)"
echo "gpu        : $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || echo 'nvidia-smi unavailable')"
echo

# ----- Environment: modules + venv -----------------------------------------
if ! command -v module >/dev/null 2>&1; then
  for init in /etc/profile.d/lmod.sh /etc/profile.d/z00_lmod.sh /etc/profile.d/modules.sh; do
    [ -f "$init" ] && source "$init" && break
  done
fi
command -v module >/dev/null 2>&1 && module load "$PYTHON_MODULE" || \
  echo "WARNING: could not 'module load $PYTHON_MODULE'; using PATH python." >&2

if [ ! -f "$VENV_DIR/bin/activate" ]; then
  echo "ERROR: venv not found at $VENV_DIR. Run deploy/msi/setup_env.sh first." >&2
  exit 1
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
export PATH="$OLLAMA_DIR/bin:$PATH"

# ----- Start ollama serve in the background --------------------------------
OLLAMA_LOG="$REPO_ROOT/deploy/msi/logs/ollama-${SLURM_JOB_ID:-local}.log"
echo "[ollama] starting server -> $OLLAMA_LOG"
ollama serve >"$OLLAMA_LOG" 2>&1 &
OLLAMA_PID=$!

# Always stop ollama when the job exits (normal, error, or SIGTERM on preempt).
cleanup() {
  echo "[cleanup] stopping ollama (pid $OLLAMA_PID)"
  kill "$OLLAMA_PID" 2>/dev/null || true
  wait "$OLLAMA_PID" 2>/dev/null || true
}
trap cleanup EXIT TERM INT

# ----- Wait for the server to be healthy -----------------------------------
echo "[ollama] waiting for server to become healthy..."
healthy=0
for i in $(seq 1 60); do
  if curl -fsS "$OLLAMA_URL/api/version" >/dev/null 2>&1; then
    healthy=1
    echo "[ollama] healthy after ${i}s: $(curl -fsS "$OLLAMA_URL/api/version")"
    break
  fi
  if ! kill -0 "$OLLAMA_PID" 2>/dev/null; then
    echo "ERROR: ollama serve died during startup. Last log lines:" >&2
    tail -n 30 "$OLLAMA_LOG" >&2 || true
    exit 1
  fi
  sleep 1
done
if [ "$healthy" != 1 ]; then
  echo "ERROR: ollama did not become healthy in 60s. Last log lines:" >&2
  tail -n 30 "$OLLAMA_LOG" >&2 || true
  exit 1
fi

# ----- Pull the model (idempotent; a no-op if already present) --------------
echo "[ollama] pull $QWEN_MODEL"
if ! ollama pull "$QWEN_MODEL"; then
  echo "ERROR: 'ollama pull $QWEN_MODEL' failed. Confirm the tag exists on the" >&2
  echo "       Ollama library and fits GPU memory (see README)." >&2
  exit 1
fi

# ----- Run the evaluation (resumable) --------------------------------------
echo "[eval] launching eval_entry.py"
set +e   # capture eval exit code so cleanup still runs and we report it
python deploy/msi/eval_entry.py \
  --corpus   "$CORPUS_DIR" \
  --out      "$OUT_DIR" \
  --model    "$QWEN_MODEL" \
  --ollama-url "$OLLAMA_URL" \
  --seed     "$SEED" \
  --repetitions "$REPETITIONS"
EVAL_RC=$?
set -e

echo "[eval] exit code: $EVAL_RC"
echo "[eval] results : $OUT_DIR/trial_results.csv"
echo "=== job done (rc=$EVAL_RC) ==="
exit "$EVAL_RC"
