#!/bin/bash
#SBATCH --job-name=vis_react
#SBATCH --partition=v100
#SBATCH --array=0-1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --gres=gpu:1
#SBATCH --time=10:00:00
#SBATCH --output=/users/5/liu02496/VisAgent/test/results/multimodal_%A_%a.log

set -euo pipefail

# Original attack corpus (build_dataset_pages.py) on the hand-written pages and
# the CSV-based datasets. Submit with: MODELS=qwen3-vl:8b,qwen3.5:9b sbatch run_multimodal_suite.slurm
# Two array tasks, each on its own GPU node, split by library:
#   task 0: d3, plotly    task 1: chartjs, vega-lite
# Each task writes results/multimodal_<jobid>_<task>/results.csv; whichever task
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

export VIS_RESULTS_DIR="$WORK_DIR/results/multimodal_${SLURM_ARRAY_JOB_ID}_${SLURM_ARRAY_TASK_ID}"
# The original attack corpus: the 14 bar, line, scatter and stacked bar
# attacks on the hand-written pages and on the CSV-based datasets
# (datasets/corpus_datasets.json), each with its own dataset's clean
# baseline. 43 attacked pages per library (14 original + 29 on the CSVs);
# the real-dataset tasks and the reasoning attacks have their own jobs.
ATTACKS=bar_aria_deception,bar_color_highlight_decoy,bar_dom_injection,bar_truncated_axis
ATTACKS+=,line_automation_cloak,line_close_colors,line_console_false_claim,line_dual_axis
ATTACKS+=,scatter_css_hidden_text,scatter_log_scale,scatter_wide_axis_range
ATTACKS+=,stacked_bar_alt_text_bias,stacked_bar_close_colors,stacked_bar_wide_axis_range
DATASETS=original,climate_core,public_health_core,steam_core
python3 run_attack_suite.py --models "$MODELS" --base-url "$BASE_URL" --libraries "$LIBRARIES" \
    --attacks "$ATTACKS" --datasets "$DATASETS" --timeout 180 --max-steps 15
# The same charts' capability questions on the clean pages (no attack), so each
# dataset has its own capability baseline: 212 trials per task here (the 9
# generic task ids also pick the revenue charts' retrieve_value question, which
# the reasoning job does not ask).
TASKS=retrieve_value,find_anomalies,find_extremum,filter,determine_range,sort
TASKS+=,compute_derived_value,characterize_distribution,correlate
python3 run_capability_suite.py --models "$MODELS" --base-url "$BASE_URL" --libraries "$LIBRARIES" \
    --task-ids "$TASKS" --datasets "$DATASETS" --timeout 180 --max-steps 15

mkdir -p "$VIS_RESULTS_DIR" && touch "$VIS_RESULTS_DIR/done"
unset VIS_RESULTS_DIR
(
    flock 9
    PARTS=("$WORK_DIR"/results/multimodal_"${SLURM_ARRAY_JOB_ID}"_*/)
    if [ "$(ls "$WORK_DIR"/results/multimodal_"${SLURM_ARRAY_JOB_ID}"_*/done 2>/dev/null | wc -l)" -eq 2 ]; then
        python3 merge_results.py "${PARTS[@]}"
        python3 summarize_results.py
        python3 summarize_capability.py
    else
        echo "Other array task still running; it will merge and summarize."
    fi
# One lock for every job, since they all append to results/results.csv.
) 9>"$WORK_DIR/results/merge.lock"
