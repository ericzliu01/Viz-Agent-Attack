#!/bin/bash
# Drive the HPC test runs from your own machine over SSH.
#
#   hpc/remote.sh submit [submit.sh options] <suite>   build pages and sbatch on the cluster
#   hpc/remote.sh status [JOB]                          your queued/running jobs, or one job's history
#   hpc/remote.sh tail [RUN_DIR|latest]                 last lines of each Slurm log of a run
#   hpc/remote.sh fetch [RUN_DIR|latest] [DEST]         copy a run's results here with rsync
#
# Examples:
#   hpc/remote.sh submit llm_examples --models qwen3-vl:8b,qwen3.5:9b --trials 3
#   hpc/remote.sh submit cognitive --models qwen3-vl:8b --libraries d3
#   hpc/remote.sh status
#   hpc/remote.sh fetch latest          # -> ~/Downloads/vis-attack-results/hpc/<run>/
#
# submit streams this checkout's hpc/submit.sh to the cluster, so the script runs in
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

# Resolve "latest" (or nothing) to the RUN_DIR of the last submit.
run_dir() {
    local arg=${1:-latest}
    if [ "$arg" = latest ]; then
        remote "cat $RUNS_ROOT_REMOTE/LATEST" | sed -n 's/^RUN_DIR=\([^ ]*\) .*/\1/p' | tail -1
    else
        echo "$arg"
    fi
}

cmd=${1:-help}; shift || true
case "$cmd" in
    submit)
        [ $# -gt 0 ] || die "submit needs a suite and --models; see hpc/submit.sh --help"
        # bash -l so the module command is defined; arguments are quoted for the remote shell.
        ssh "$HOST" "bash -l -s -- $(printf '%q ' "$@")" < "$HERE/submit.sh"
        ;;
    status)
        if [ $# -gt 0 ]; then
            remote "sacct -j $(printf '%q' "$1") --format=JobID,JobName%20,State,Elapsed,ExitCode,NodeList"
        else
            remote 'squeue -u "$USER" -o "%.12i %.20j %.8T %.10M %.10l %R"'
        fi
        ;;
    tail)
        d=$(run_dir "${1:-latest}"); [ -n "$d" ] || die "no run found"
        remote "for f in $(printf '%q' "$d")/*.log; do [ -f \"\$f\" ] && { echo \"== \$f\"; tail -n 15 \"\$f\"; }; done; true"
        ;;
    fetch)
        d=$(run_dir "${1:-latest}"); [ -n "$d" ] || die "no run found"
        dest=${2:-$DEST_ROOT/$(basename "$d")}
        mkdir -p "$dest"
        rsync -az --exclude 'ollama.log' --exclude '.lock' "$HOST:$d/" "$dest/"
        echo "copied $HOST:$d to $dest"
        [ -f "$dest/summary.md" ] && echo "summary: $dest/summary.md" || echo "no summary.md yet (run still going?)"
        ;;
    help|-h|--help)
        sed -n '2,28p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
        ;;
    *) die "unknown command '$cmd'; try hpc/remote.sh help" ;;
esac
