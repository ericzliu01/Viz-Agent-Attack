#!/bin/bash
#SBATCH --job-name=vis_cognitive
#SBATCH --array=0-2
#SBATCH --partition=v100
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --gres=gpu:1
#SBATCH --time=14:00:00
#SBATCH --output=/users/5/liu02496/VisAgent/test/results/cognitive_%A_%a.log

set -euo pipefail

# Cognitive attacks (build_cognitive_pages.py): cog_rag_poisoning,
# cog_memory_write and cog_icl_trap on all 60 real-dataset tasks, each with
# its clean baseline and control memory. The pilot runs d3 only (set
# LIBRARIES for more) as a three-task array, one GPU node per attack:
# 60 attack trials + 60 baselines per model and node, about half of the 228
# per node that run_real_datasets.slurm fits in the same 14 h. Each task writes results/cognitive_<jobid>_<task>/
# results.csv; whichever finishes last merges all three into
# results/results.csv and writes results/cognitive_summary.md.
# Submit with: MODELS=qwen3-vl:8b sbatch run_cognitive_attacks.slurm
: "${MODELS:?Set MODELS to comma-separated Ollama vision+tool model tags}"
LIBRARIES=${LIBRARIES:-d3}
WORK_DIR=${WORK_DIR:-/users/5/liu02496/VisAgent/test}
export PATH="$HOME/.local/bin:$HOME/ollama/bin:$PATH"
export OLLAMA_MODELS=/scratch.global/$USER/ollama-models
export PLAYWRIGHT_BROWSERS_PATH=/scratch.global/$USER/pw-browsers

ATTACK_SPLIT=(cog_rag_poisoning cog_memory_write cog_icl_trap)
ATTACK=${ATTACK_SPLIT[$SLURM_ARRAY_TASK_ID]}
# A port of its own per array task (each has its own SLURM_JOB_ID), so tasks
# of this and the other jobs can share a multi-GPU node.
PORT=$((20000 + SLURM_JOB_ID % 40000))
export OLLAMA_HOST=127.0.0.1:$PORT
BASE_URL=http://127.0.0.1:$PORT

module load python/3.10.9_anaconda2023.03_libmamba
mkdir -p "$WORK_DIR/results"
cd "$WORK_DIR"
# Preinstall requirements.txt and Chromium on a network-connected login node.
ollama serve > "results/ollama_${SLURM_ARRAY_JOB_ID}_${SLURM_ARRAY_TASK_ID}.log" 2>&1 &
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
    # The tasks share OLLAMA_MODELS; only pull a model that isn't there yet.
    ollama show "$MODEL" >/dev/null 2>&1 || ollama pull "$MODEL"
done

export VIS_RESULTS_DIR="$WORK_DIR/results/cognitive_${SLURM_ARRAY_JOB_ID}_${SLURM_ARRAY_TASK_ID}"
# No critic pass (E, 2026-10-20): condition react_browser_repair, with a
# _memory_<hash> suffix on the cog_rag_poisoning pairs.
python3 run_attack_suite.py --models "$MODELS" --base-url "$BASE_URL" --libraries "$LIBRARIES" \
    --datasets climate,public_health,steam --attacks "$ATTACK" \
    --timeout 180 --max-steps 15
mkdir -p "$VIS_RESULTS_DIR" && touch "$VIS_RESULTS_DIR/done"
unset VIS_RESULTS_DIR
(
    flock 9
    PARTS=("$WORK_DIR"/results/cognitive_"${SLURM_ARRAY_JOB_ID}"_*/)
    if [ "$(ls "$WORK_DIR"/results/cognitive_"${SLURM_ARRAY_JOB_ID}"_*/done 2>/dev/null | wc -l)" -eq 3 ]; then
        python3 merge_results.py "${PARTS[@]}"
        python3 summarize_cognitive.py
    else
        echo "Other array tasks still running; the last one will merge and summarize."
    fi
# One lock for every job, since they all append to results/results.csv.
) 9>"$WORK_DIR/results/merge.lock"
