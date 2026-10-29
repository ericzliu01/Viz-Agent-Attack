#!/bin/bash
#SBATCH --job-name=vis_cognitive
#SBATCH --partition=v100
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --gres=gpu:1
#SBATCH --time=14:00:00
#SBATCH --output=/users/5/liu02496/VisAgent/test/results/cognitive_%j.log

set -euo pipefail

# Cognitive attacks (build_cognitive_pages.py): cog_rag_poisoning,
# cog_memory_write and cog_icl_trap on all 60 real-dataset tasks, each with
# its clean baseline and control memory. The pilot runs d3 only on one node
# (3 x 60 attack trials + 180 baselines per model); set LIBRARIES for more.
# Writes results/cognitive_<jobid>/results.csv, merges it into
# results/results.csv and writes results/cognitive_summary.md.
# Submit with: MODELS=qwen3-vl:8b sbatch run_cognitive_attacks.slurm
: "${MODELS:?Set MODELS to comma-separated Ollama vision+tool model tags}"
LIBRARIES=${LIBRARIES:-d3}
WORK_DIR=${WORK_DIR:-/users/5/liu02496/VisAgent/test}
export PATH="$HOME/.local/bin:$HOME/ollama/bin:$PATH"
export OLLAMA_MODELS=/scratch.global/$USER/ollama-models
export PLAYWRIGHT_BROWSERS_PATH=/scratch.global/$USER/pw-browsers

# A port of its own, so this job can share a multi-GPU node with others.
PORT=$((20000 + SLURM_JOB_ID % 40000))
export OLLAMA_HOST=127.0.0.1:$PORT
BASE_URL=http://127.0.0.1:$PORT

module load python/3.10.9_anaconda2023.03_libmamba
mkdir -p "$WORK_DIR/results"
cd "$WORK_DIR"
# Preinstall requirements.txt and Chromium on a network-connected login node.
ollama serve > "results/ollama_${SLURM_JOB_ID}.log" 2>&1 &
OLLAMA_PID=$!
trap 'kill "$OLLAMA_PID" 2>/dev/null || true' EXIT
for i in $(seq 1 60); do
    if curl -fsS "$BASE_URL/api/tags" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done
curl -fsS "$BASE_URL/api/tags" >/dev/null

IFS=',' read -r -a MODEL_TAGS <<< "$MODELS"
for MODEL in "${MODEL_TAGS[@]}"; do
    ollama show "$MODEL" >/dev/null 2>&1 || ollama pull "$MODEL"
done

PART="$WORK_DIR/results/cognitive_${SLURM_JOB_ID}"
export VIS_RESULTS_DIR="$PART"
# No critic pass (E, 2026-10-20): condition react_browser_repair, with a
# _memory_<hash> suffix on the cog_rag_poisoning pairs.
python3 run_attack_suite.py --models "$MODELS" --base-url "$BASE_URL" --libraries "$LIBRARIES" \
    --datasets climate,public_health,steam --attacks cog_rag_poisoning,cog_memory_write,cog_icl_trap \
    --timeout 180 --max-steps 15
unset VIS_RESULTS_DIR
(
    flock 9
    python3 merge_results.py "$PART/"
    python3 summarize_cognitive.py
# One lock for every job, since they all append to results/results.csv.
) 9>"$WORK_DIR/results/merge.lock"
