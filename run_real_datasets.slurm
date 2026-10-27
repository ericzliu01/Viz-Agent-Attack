#!/bin/bash
#SBATCH --job-name=vis_real
#SBATCH --partition=v100
#SBATCH --array=0-1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --gres=gpu:1
#SBATCH --time=14:00:00
#SBATCH --output=/users/5/liu02496/VisAgent/test/results/real_%A_%a.log

set -euo pipefail

# Real datasets (climate, public_health, steam; build_real_dataset_pages.py).
# Two array tasks, each on its own GPU node, split by library:
#   task 0: d3, plotly    task 1: chartjs, vega-lite
# Each task writes results/real_<jobid>_<task>/results.csv; whichever task
# finishes last merges both into results/results.csv and writes the summaries.
# Submit with: MODELS=qwen3-vl:8b sbatch run_real_datasets.slurm
: "${MODELS:?Set MODELS to comma-separated Ollama vision+tool model tags}"
WORK_DIR=${WORK_DIR:-/users/5/liu02496/VisAgent/test}
export PATH="$HOME/.local/bin:$HOME/ollama/bin:$PATH"
export OLLAMA_MODELS=/scratch.global/$USER/ollama-models
export PLAYWRIGHT_BROWSERS_PATH=/scratch.global/$USER/pw-browsers

LIBRARY_SPLIT=("d3,plotly" "chartjs,vega-lite")
LIBRARIES=${LIBRARY_SPLIT[$SLURM_ARRAY_TASK_ID]}
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
    # Both tasks share OLLAMA_MODELS; only pull a model that isn't there yet.
    ollama show "$MODEL" >/dev/null 2>&1 || ollama pull "$MODEL"
done

export VIS_RESULTS_DIR="$WORK_DIR/results/real_${SLURM_ARRAY_JOB_ID}_${SLURM_ARRAY_TASK_ID}"
DATASETS=climate,public_health,steam
COMMON=(--models "$MODELS" --base-url "$BASE_URL" --libraries "$LIBRARIES" --datasets "$DATASETS"
        --timeout 180 --max-steps 15)

# 54 attacked tasks per library, each with its clean baseline (216 trials per task here).
python3 run_attack_suite.py "${COMMON[@]}"
# No critic pass for now (E, 2026-10-20): run_attack_suite.py --critic still
# works, but this job runs condition react_browser_repair only.
# The 6 steam line tasks have no attack page (one-series chart): ask them on
# the clean chart only (12 trials per task here).
STEAM_LINE=steam_line_retrieve_value,steam_line_find_extremum,steam_line_determine_range,steam_line_sort,steam_line_compute_derived_value,steam_line_correlate
python3 run_capability_suite.py "${COMMON[@]}" --datasets steam --task-ids "$STEAM_LINE"

mkdir -p "$VIS_RESULTS_DIR" && touch "$VIS_RESULTS_DIR/done"
unset VIS_RESULTS_DIR
(
    flock 9
    PARTS=("$WORK_DIR"/results/real_"${SLURM_ARRAY_JOB_ID}"_*/)
    if [ "$(ls "$WORK_DIR"/results/real_"${SLURM_ARRAY_JOB_ID}"_*/done 2>/dev/null | wc -l)" -eq 2 ]; then
        python3 merge_results.py "${PARTS[@]}"
        python3 summarize_results.py
        python3 summarize_capability.py
    else
        echo "Other array task still running; it will merge and summarize."
    fi
# One lock for every job, since they all append to results/results.csv.
) 9>"$WORK_DIR/results/merge.lock"
