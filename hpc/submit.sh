#!/bin/bash
# Submit a test suite to Slurm on the HPC cluster (agate). Run it on a login node,
# or from your own machine with hpc/remote.sh, which streams this script over SSH.
#
#   hpc/submit.sh [options] <suite>
#
# Suites:
#   llm_examples  llm_taskgen example pages (hpc/llm_examples.slurm); default branch
#                 claude/project-thread-c0vsra
#   real          run_real_datasets.slurm       (default branch testing)
#   cognitive     run_cognitive_attacks.slurm   (default branch testing)
#   reasoning     run_reasoning_attacks.slurm   (default branch testing)
#
# Options:
#   --models M1,M2      Ollama model tags (required), e.g. qwen3-vl:8b,qwen3.5:9b
#   --branch B          git branch to run (default: per suite, above)
#   --groups "a,b;c,d"  llm_examples: library groups, one GPU node each
#                       (default "d3,plotly;chartjs,vega-lite")
#   --libraries a,b     cognitive/reasoning: LIBRARIES for the job; llm_examples: one group
#   --trials N          llm_examples: trials per cell (default 3)
#   --time HH:MM:SS     Slurm time limit (default: the job file's)
#   --partition P       Slurm partition (default: the job file's, v100)
#   --extra "ARGS"      llm_examples: extra flags for python -m llm_taskgen.run
#   --repo PATH         main checkout on the cluster (default $HOME/VisAgent/test)
#   --dry-run           update the checkout and build pages, print the sbatch command, submit nothing
#
# The branch is checked out (detached at origin/<branch>) in its own git worktree,
# $HOME/VisAgent/runs/<branch>, so the main checkout and running jobs are untouched.
# Results: <worktree>/results/<suite>_<timestamp>/ for llm_examples; the other suites
# write where their job files always have (<worktree>/results/). The last line printed
# is "RUN_DIR=<dir> JOB=<id>", and $HOME/VisAgent/runs/LATEST holds the same line.
set -euo pipefail

usage() { sed -n '2,32p' "${BASH_SOURCE[0]:-/dev/null}" 2>/dev/null | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }
die() { echo "submit.sh: $*" >&2; exit 1; }

MODELS="" BRANCH="" GROUPS_ARG="" LIBRARIES="" TRIALS=3 TIME="" PARTITION="" EXTRA="" DRY=0
REPO=${REPO:-$HOME/VisAgent/test}
RUNS_ROOT=${RUNS_ROOT:-$HOME/VisAgent/runs}
SUITE=""
while [ $# -gt 0 ]; do
    case "$1" in
        --models) MODELS=$2; shift 2 ;;
        --branch) BRANCH=$2; shift 2 ;;
        --groups) GROUPS_ARG=$2; shift 2 ;;
        --libraries) LIBRARIES=$2; shift 2 ;;
        --trials) TRIALS=$2; shift 2 ;;
        --time) TIME=$2; shift 2 ;;
        --partition) PARTITION=$2; shift 2 ;;
        --extra) EXTRA=$2; shift 2 ;;
        --repo) REPO=$2; shift 2 ;;
        --dry-run) DRY=1; shift ;;
        -h|--help) usage 0 ;;
        -*) die "unknown option $1" ;;
        *) [ -z "$SUITE" ] || die "more than one suite given"; SUITE=$1; shift ;;
    esac
done
[ -n "$SUITE" ] || die "no suite given (llm_examples, real, cognitive, reasoning); --help for usage"
[ -n "$MODELS" ] || die "--models is required"
case "$SUITE" in
    llm_examples) JOB_FILE=hpc/llm_examples.slurm; BRANCH=${BRANCH:-claude/project-thread-c0vsra} ;;
    real) JOB_FILE=run_real_datasets.slurm; BRANCH=${BRANCH:-testing} ;;
    cognitive) JOB_FILE=run_cognitive_attacks.slurm; BRANCH=${BRANCH:-testing} ;;
    reasoning) JOB_FILE=run_reasoning_attacks.slurm; BRANCH=${BRANCH:-testing} ;;
    *) die "unknown suite '$SUITE'" ;;
esac
[[ "$TRIALS" =~ ^[1-9][0-9]*$ ]] || die "--trials must be a positive integer"

# 1. Check out origin/<branch> in its own worktree.
[ -d "$REPO/.git" ] || die "no git checkout at $REPO (set --repo)"
git -C "$REPO" fetch -q origin "$BRANCH" || die "git fetch of $BRANCH failed"
WT="$RUNS_ROOT/${BRANCH//\//-}"
if [ -d "$WT" ]; then
    git -C "$WT" diff --quiet HEAD -- || die "$WT has uncommitted changes to tracked files; commit or discard them first"
    git -C "$WT" checkout -q --detach "origin/$BRANCH"
else
    mkdir -p "$RUNS_ROOT"
    git -C "$REPO" worktree add -q --detach "$WT" "origin/$BRANCH"
fi
cd "$WT"
COMMIT=$(git rev-parse --short HEAD)
echo "checkout: $WT at $COMMIT ($BRANCH)"
[ -f "$JOB_FILE" ] || die "$JOB_FILE is not on $BRANCH"

# The module command exists in login shells on MSI; skip it elsewhere.
if type module >/dev/null 2>&1; then module load python/3.10.9_anaconda2023.03_libmamba >/dev/null 2>&1 || true; fi

SB=(sbatch --parsable --chdir="$WT")
[ -n "$TIME" ] && SB+=(--time="$TIME")
[ -n "$PARTITION" ] && SB+=(--partition="$PARTITION")
STAMP=$(date +%Y%m%d_%H%M%S)

if [ "$SUITE" = llm_examples ]; then
    GROUPS_STR=${GROUPS_ARG:-${LIBRARIES:-d3,plotly;chartjs,vega-lite}}
    IFS=';' read -r -a GROUPS_ARR <<< "$GROUPS_STR"
    ALL_LIBS=$(IFS=,; echo "${GROUPS_ARR[*]}")
    # 2. Build the pages on the login node (pure Python, no GPU or network).
    python3 -m llm_taskgen.pages --libraries "$ALL_LIBS"
    # 3. Browser smoke check, if Node Playwright is installed here; it fails fast on broken pages.
    if command -v node >/dev/null 2>&1 && NODE_PATH=$(npm root -g 2>/dev/null) node -e "require('playwright')" >/dev/null 2>&1; then
        NODE_PATH=$(npm root -g) node llm_taskgen/browser_check.js pages tasks/llm_examples/task-attack-examples.json \
            || die "browser check failed; nothing submitted"
    else
        echo "note: Node Playwright not found, skipping the browser check"
    fi
    RUN_DIR="$WT/results/${SUITE}_$STAMP"
    mkdir -p "$RUN_DIR"
    # Values with commas (models, groups) can't go in --export=NAME=value, so they are
    # exported here and passed with --export=ALL.
    export MODELS LIBRARY_GROUPS="$GROUPS_STR" RUN_DIR TRIALS EXTRA_ARGS="$EXTRA"
    ENV_SHOWN="MODELS LIBRARY_GROUPS RUN_DIR TRIALS EXTRA_ARGS"
    SB+=(--array="0-$((${#GROUPS_ARR[@]} - 1))" --output="$RUN_DIR/slurm_%A_%a.log" --export=ALL)
    printf '{"suite": "%s", "branch": "%s", "commit": "%s", "models": "%s", "groups": "%s", "trials": %s, "extra": "%s", "submitted": "%s"}\n' \
        "$SUITE" "$BRANCH" "$COMMIT" "$MODELS" "$GROUPS_STR" "$TRIALS" "$EXTRA" "$STAMP" > "$RUN_DIR/run.json"
else
    RUN_DIR="$WT/results"
    mkdir -p "$RUN_DIR"
    export MODELS WORK_DIR="$WT"
    ENV_SHOWN="MODELS WORK_DIR"
    if [ -n "$LIBRARIES" ]; then export LIBRARIES; ENV_SHOWN+=" LIBRARIES"; fi
    SB+=(--output="$RUN_DIR/${SUITE}_%A_%a.log" --export=ALL)
fi
SB+=("$JOB_FILE")

if [ "$DRY" = 1 ]; then
    printf 'dry run, would submit with'; for v in $ENV_SHOWN; do printf ' %s=%q' "$v" "${!v}"; done
    printf ':'; printf ' %q' "${SB[@]}"; echo
    [ "$SUITE" = llm_examples ] && rm -rf "$RUN_DIR"
    exit 0
fi
command -v sbatch >/dev/null 2>&1 || die "sbatch not found; run this on a cluster login node"
JOB=$("${SB[@]}")
JOB=${JOB%%;*}
[ "$SUITE" = llm_examples ] && echo "$JOB" > "$RUN_DIR/job_id"
echo "submitted $SUITE as job $JOB (watch: squeue -j $JOB)"
echo "RUN_DIR=$RUN_DIR JOB=$JOB" | tee "$RUNS_ROOT/LATEST"
