#!/bin/bash
# Drive the HPC test runs from your own machine over SSH.
#
#   hpc/remote.sh submit [submit.sh options] <suite>   build pages and sbatch on the cluster
#   hpc/remote.sh status [JOB]                          your queued/running jobs, or one job's history
#   hpc/remote.sh tail [latest|RUN_DIR [JOB]]           last lines of each Slurm log of a run
#   hpc/remote.sh fetch [latest|RUN_DIR [JOB]] [DEST]   copy a run's results here with rsync
#
# For real/cognitive/reasoning the run directory is the shared results/ folder, so
# tail and fetch keep to the files named by the job id (from LATEST, or JOB).
#
# Examples:
#   hpc/remote.sh submit llm_examples --models qwen3-vl:8b,qwen3.5:9b --trials 3
#   hpc/remote.sh submit cognitive --models qwen3-vl:8b --libraries d3
#   hpc/remote.sh status
#   hpc/remote.sh fetch latest          # -> ~/Downloads/vis-attack-results/hpc/<run>/
#
# submit sends this checkout's hpc/submit.sh to the cluster, so the script runs in
# the version you have here; the code it runs is origin/<branch> on GitHub, so push first.
#
# Settings (environment): HPC_HOST (ssh host or alias, default "agate"),
# HPC_RESULTS (local destination root, default ~/Downloads/vis-attack-results/hpc).
# MSI logins ask for Duo on every connection; to approve once per session, add to
# ~/.ssh/config:
#   Host agate
#     HostName agate.msi.umn.edu
#     User <your MSI username>
#     ControlMaster auto
#     ControlPath ~/.ssh/cm-%r@%h:%p
#     ControlPersist 8h
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
HOST=${HPC_HOST:-agate}
DEST_ROOT=${HPC_RESULTS:-$HOME/Downloads/vis-attack-results/hpc}
RUNS_ROOT_REMOTE='$HOME/VisAgent/runs'

die() { echo "remote.sh: $*" >&2; exit 1; }
remote() { ssh "$HOST" "bash -lc $(printf '%q' "$1")"; }

# Sets D (run directory) and JOB from "latest" (the last submit) or "RUN_DIR [JOB]".
# JOB is empty for an llm_examples run directory, which holds that one run only.
resolve() {
    local line
    if [ "${1:-latest}" = latest ]; then
        line=$(remote "cat $RUNS_ROOT_REMOTE/LATEST")
        D=$(sed -n 's/^RUN_DIR=\([^ ]*\) .*/\1/p' <<< "$line")
        JOB=$(sed -n 's/.* JOB=\([0-9]*\).*/\1/p' <<< "$line")
        [ "$(sed -n 's/.* SUITE=\([a-z_]*\).*/\1/p' <<< "$line")" = llm_examples ] && JOB=""
        NEXT=1
    else
        D=$1; JOB=""; NEXT=1
        if [[ "${2:-}" =~ ^[0-9]+$ ]]; then JOB=$2; NEXT=2; fi
    fi
    [ -n "$D" ] || die "no run found"
}

cmd=${1:-help}; shift || true
case "$cmd" in
    submit)
        [ $# -gt 0 ] || die "submit needs a suite and --models; see hpc/submit.sh --help"
        for a in "$@"; do case "$a" in -h|--help) exec bash "$HERE/submit.sh" --help ;; esac; done
        # The script goes as an argument (stdin stays free), through bash -l so the module
        # command is defined; everything is quoted for the remote shell.
        ssh "$HOST" "bash -l -c $(printf '%q' "$(cat "$HERE/submit.sh")") submit.sh $(printf '%q ' "$@")" </dev/null
        ;;
    status)
        if [ $# -gt 0 ]; then
            remote "sacct -j $(printf '%q' "$1") --format=JobID,JobName%20,State,Elapsed,ExitCode,NodeList"
        else
            remote 'squeue -u "$USER" -o "%.12i %.20j %.8T %.10M %.10l %R"'
        fi
        ;;
    tail)
        resolve "$@"
        if [ -n "$JOB" ]; then pat="*_${JOB}_*.log"; else pat="*.log"; fi
        remote "for f in $(printf '%q' "$D")/$pat; do [ -f \"\$f\" ] && { echo \"== \$f\"; tail -n 15 \"\$f\"; }; done; true"
        ;;
    fetch)
        resolve "$@"; shift "$NEXT" 2>/dev/null || shift $#
        if [ -n "$JOB" ]; then
            dest=${1:-$DEST_ROOT/$(basename "$(dirname "$D")")_$JOB}
            # Only this job's parts and logs (the job files name them <suite>_<job>_<task>).
            FILTER=(--include="*_${JOB}_*/***" --include="*_${JOB}_*" --exclude='*')
        else
            dest=${1:-$DEST_ROOT/$(basename "$D")}
            FILTER=()
        fi
        mkdir -p "$dest"
        rsync -az --exclude 'ollama*.log' --exclude '.lock' --exclude 'merge.lock' ${FILTER[@]+"${FILTER[@]}"} "$HOST:$D/" "$dest/"
        echo "copied $HOST:$D${JOB:+ (job $JOB)} to $dest"
        if [ -z "$JOB" ]; then
            [ -f "$dest/summary.md" ] && echo "summary: $dest/summary.md" || echo "no summary.md yet (run still going, or see slurm_*.log)"
        fi
        ;;
    help|-h|--help)
        sed -n '2,28p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
        ;;
    *) die "unknown command '$cmd'; try hpc/remote.sh help" ;;
esac
