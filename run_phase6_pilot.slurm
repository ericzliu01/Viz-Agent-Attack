#!/bin/bash
#SBATCH --job-name=vis_react_pilot
#SBATCH --partition=v100
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --gres=gpu:1
#SBATCH --time=6:00:00
#SBATCH --output=/users/5/liu02496/VisAgent/test/results/phase6_pilot_%j.log

set -euo pipefail

# Submit with MODELS set to installed/pullable tags supporting vision and tools.
# Example: MODELS=your-model sbatch run_phase6_pilot.slurm
: "${MODELS:?Set MODELS to comma-separated Ollama vision+tool model tags}"
WORK_DIR=${WORK_DIR:-/users/5/liu02496/VisAgent/test}
export PATH="$HOME/.local/bin:$HOME/ollama/bin:$PATH"
export OLLAMA_MODELS=/scratch.global/$USER/ollama-models
export PLAYWRIGHT_BROWSERS_PATH=/scratch.global/$USER/pw-browsers

module load python/3.10.9_anaconda2023.03_libmamba
mkdir -p "$WORK_DIR/results"
cd "$WORK_DIR"
# Preinstall requirements.txt and Chromium on a network-connected login node.
ollama serve > "results/ollama_${SLURM_JOB_ID}.log" 2>&1 &
OLLAMA_PID=$!
trap 'kill "$OLLAMA_PID" 2>/dev/null || true' EXIT
for i in $(seq 1 60); do
    if curl -fsS http://localhost:11434/api/tags >/dev/null 2>&1; then
        break
    fi
    sleep 1
done
curl -fsS http://localhost:11434/api/tags >/dev/null

IFS=',' read -r -a MODEL_TAGS <<< "$MODELS"
for MODEL in "${MODEL_TAGS[@]}"; do
    ollama pull "$MODEL"
done

python3 run_attack_suite.py --models "$MODELS" --timeout 180 --max-steps 15
# Verify completed trials are skipped.
python3 run_attack_suite.py --models "$MODELS" --timeout 180 --max-steps 15
python3 summarize_results.py
