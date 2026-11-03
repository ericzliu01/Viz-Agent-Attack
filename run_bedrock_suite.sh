#!/bin/bash
# The real-dataset suite of run_real_datasets.slurm (condition react_browser_repair,
# no critic) on AWS Bedrock instead of Ollama, all four libraries in one process.
# Load credentials first (never commit them):  . AWS-API/aws-api-test.env
# Usage: MODEL=us.openai.gpt-6-luna OUT=results/bedrock_luna ./run_bedrock_suite.sh
# Re-running with the same OUT skips trials that already have a non-error row.
set -euo pipefail
: "${MODEL:?Set MODEL to a Bedrock inference-profile id, e.g. us.anthropic.claude-sonnet-5-5}"
: "${OUT:?Set OUT to a results directory}"
: "${AWS_BEARER_TOKEN_BEDROCK:?Load Bedrock credentials first: . AWS-API/aws-api-test.env}"
cd "$(dirname "$0")"
export VIS_RESULTS_DIR="$PWD/$OUT"
COMMON=(--models "$MODEL" --backend bedrock --datasets climate,public_health,steam
        --timeout 180 --max-steps 15)

# 54 attacked tasks per library, each with its clean baseline.
python3 run_attack_suite.py "${COMMON[@]}"
# The 6 steam line tasks have no attack page: clean chart only.
STEAM_LINE=steam_line_retrieve_value,steam_line_find_extremum,steam_line_determine_range,steam_line_sort,steam_line_compute_derived_value,steam_line_correlate
python3 run_capability_suite.py "${COMMON[@]}" --datasets steam --task-ids "$STEAM_LINE"
