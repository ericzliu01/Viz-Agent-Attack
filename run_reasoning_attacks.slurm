#!/bin/bash
#SBATCH --job-name=vis_reasoning
#SBATCH --partition=v100
#SBATCH --array=0-1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --gres=gpu:1
#SBATCH --time=12:00:00
#SBATCH --output=/users/5/liu02496/VisAgent/test/results/reasoning_%A_%a.log

set -euo pipefail

# Reasoning attacks (build_reasoning_pages.py) on the hand-written revenue chart
# and on steam_core. Submit with: MODELS=qwen3-vl:8b,qwen3.5:9b sbatch run_reasoning_attacks.slurm
# Two array tasks, each on its own GPU node, split by library:
#   task 0: d3, plotly    task 1: chartjs, vega-lite
# Each task writes results/reasoning_<jobid>_<task>/results.csv; whichever task
# finishes last merges both into results/results.csv and writes the summaries.
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

export VIS_RESULTS_DIR="$WORK_DIR/results/reasoning_${SLURM_ARRAY_JOB_ID}_${SLURM_ARRAY_TASK_ID}"
# Reasoning attacks (biased framing, critic evasion, persona hyperstition) on
# the hand-written revenue chart and on steam_core (Steam releases by genre,
# datasets/corpus_datasets.json): 3 attacks x 10 tasks x 2 datasets, each with
# its clean baseline (240 trials per task here).
ATTACKS=revenue_biased_framing,revenue_critic_evasion,revenue_persona_hyperstition
DATASETS=original,steam_core
COMMON=(--models "$MODELS" --base-url "$BASE_URL" --libraries "$LIBRARIES" --datasets "$DATASETS"
        --timeout 180 --max-steps 15)
python3 run_attack_suite.py "${COMMON[@]}" --attacks "$ATTACKS"
# Same trials with the critic pass (condition react_browser_critic).
python3 run_attack_suite.py "${COMMON[@]}" --attacks "$ATTACKS" --critic
# The 10 tasks as capability questions on each clean chart (no attack, no
# memory). Three task ids name the dip quarters/years, so they differ per dataset.
TASKS=revenue_vs_quarter,lowest_quarter,top_region,any_decline,quarters_up,sort_quarters,trend_break
TASKS+=,q2_q3_change,growth_q1_q4,largest_q3_drop
TASKS+=,2016_2017_change,growth_2015_2018,largest_2017_drop
python3 run_capability_suite.py "${COMMON[@]}" --task-ids "$TASKS"

mkdir -p "$VIS_RESULTS_DIR" && touch "$VIS_RESULTS_DIR/done"
unset VIS_RESULTS_DIR
(
    flock 9
    PARTS=("$WORK_DIR"/results/reasoning_"${SLURM_ARRAY_JOB_ID}"_*/)
    if [ "$(ls "$WORK_DIR"/results/reasoning_"${SLURM_ARRAY_JOB_ID}"_*/done 2>/dev/null | wc -l)" -eq 2 ]; then
        python3 merge_results.py "${PARTS[@]}"
        python3 summarize_reasoning.py
        python3 summarize_results.py
    else
        echo "Other array task still running; it will merge and summarize."
    fi
# One lock for every job, since they all append to results/results.csv.
) 9>"$WORK_DIR/results/merge.lock"
