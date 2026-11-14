#!/bin/bash
#SBATCH --job-name=vis_lx
#SBATCH --partition=v100
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --gres=gpu:1
#SBATCH --time=14:00:00

set -euo pipefail

# llm_taskgen example pages (lx_*) on Ollama models. Submitted by hpc/submit.sh,
# which builds the pages, sets --array (one task per library group) and --output,
# and exports the variables below. Each array task writes
# $RUN_DIR/part_<task>/results.csv (+ trial_metadata.json, traces/); whichever task
# finishes last writes $RUN_DIR/summary.md with llm_taskgen.summarize.
: "${MODELS:?}" "${LIBRARY_GROUPS:?}" "${RUN_DIR:?}"
TRIALS=${TRIALS:-3}
TIMEOUT=${TIMEOUT:-180}
MAX_STEPS=${MAX_STEPS:-15}
EXTRA_ARGS=${EXTRA_ARGS:-}
WORK_DIR=${SLURM_SUBMIT_DIR:-$PWD}
export PATH="$HOME/.local/bin:$HOME/ollama/bin:$PATH"
export OLLAMA_MODELS=${OLLAMA_MODELS:-/scratch.global/${USER:-$(id -un)}/ollama-models}
export PLAYWRIGHT_BROWSERS_PATH=${PLAYWRIGHT_BROWSERS_PATH:-/scratch.global/${USER:-$(id -un)}/pw-browsers}

IFS=';' read -r -a GROUPS_ARR <<< "$LIBRARY_GROUPS"
TASK=${SLURM_ARRAY_TASK_ID:-0}
LIBRARIES=${GROUPS_ARR[$TASK]}
# A port of its own per array task, so tasks of this and other jobs can share a node.
PORT=$((20000 + SLURM_JOB_ID % 40000))
export OLLAMA_HOST=127.0.0.1:$PORT
BASE_URL=http://127.0.0.1:$PORT

# On any exit: stop Ollama, mark this part done or failed, and if every part has
# finished, summarize the parts that have results (failed parts are listed).
finish() {
    local status=$?
    kill "$OLLAMA_PID" 2>/dev/null || true
    if [ "$status" -eq 0 ]; then touch "$PART/done"; else echo "exit $status" > "$PART/failed"; fi
    (
        flock 9
        local finished failed
        finished=$(find "$RUN_DIR" -maxdepth 2 -path '*/part_*' \( -name done -o -name failed \) | wc -l)
        failed=$(find "$RUN_DIR" -maxdepth 2 -path '*/part_*' -name failed | sed 's|/failed$||; s|.*/||' | tr '\n' ' ')
        if [ "$finished" -lt "${#GROUPS_ARR[@]}" ] || [ -e "$RUN_DIR/summary.md" ]; then
            echo "$finished of ${#GROUPS_ARR[@]} parts finished; the last one writes the summary."
            exit 0
        fi
        csvs=("$RUN_DIR"/part_*/results.csv)
        {
            [ -n "$failed" ] && printf 'Failed parts (see slurm_*.log): %s\n\n' "$failed"
            if [ -e "${csvs[0]}" ]; then python3 -m llm_taskgen.summarize "${csvs[@]}"; else echo "No results.csv in any part."; fi
        } > "$RUN_DIR/summary.md.tmp" && mv "$RUN_DIR/summary.md.tmp" "$RUN_DIR/summary.md"
        echo "summary written to $RUN_DIR/summary.md"
    ) 9>"$RUN_DIR/.lock" || true
    exit "$status"
}

module load python/3.10.9_anaconda2023.03_libmamba
cd "$WORK_DIR"
PART="$RUN_DIR/part_$TASK"
mkdir -p "$PART"
echo "job $SLURM_JOB_ID task $TASK: libraries=$LIBRARIES models=$MODELS trials=$TRIALS commit=$(git rev-parse --short HEAD 2>/dev/null || echo ?)"
ollama --version || true
ollama serve > "$PART/ollama.log" 2>&1 &
OLLAMA_PID=$!
trap finish EXIT
for _ in $(seq 1 60); do
    curl -fsS "$BASE_URL/api/tags" >/dev/null 2>&1 && break
    sleep 1
done
curl -fsS "$BASE_URL/api/tags" >/dev/null

IFS=',' read -r -a MODEL_TAGS <<< "$MODELS"
for MODEL in "${MODEL_TAGS[@]}"; do
    # Tasks share OLLAMA_MODELS; only pull a model that isn't there yet.
    ollama show "$MODEL" >/dev/null 2>&1 || ollama pull "$MODEL"
done

# shellcheck disable=SC2086  # EXTRA_ARGS is a list of extra flags
VIS_RESULTS_DIR="$PART" python3 -m llm_taskgen.run --models "$MODELS" --base-url "$BASE_URL" \
    --libraries "$LIBRARIES" --trials "$TRIALS" --timeout "$TIMEOUT" --max-steps "$MAX_STEPS" \
    --trace-dir "$PART/traces" $EXTRA_ARGS
