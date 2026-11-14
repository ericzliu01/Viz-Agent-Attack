# Running the tests on the HPC cluster

Terms: **suite** = one family of tests (`llm_examples`, `real`, `cognitive`, `reasoning`);
**run directory** = the folder a submitted run writes to; **worktree** = a separate
checkout of one branch on the cluster, so jobs never run in the main checkout.

## From your own machine

```bash
hpc/remote.sh submit llm_examples --models qwen3-vl:8b,qwen3.5:9b --trials 3
hpc/remote.sh status             # your jobs in the queue
hpc/remote.sh tail               # last lines of the latest run's logs
hpc/remote.sh fetch latest       # copy results to ~/Downloads/vis-attack-results/hpc/<run>/
```

`remote.sh` runs over SSH (`HPC_HOST`, default `agate`); see its header for an
`~/.ssh/config` entry that keeps one Duo-approved connection open. The cluster runs
`origin/<branch>`, so push before you submit.

## On a login node

```bash
hpc/submit.sh --models qwen3-vl:8b llm_examples      # or real, cognitive, reasoning
hpc/submit.sh --models qwen3-vl:8b --dry-run llm_examples   # build + check, print sbatch only
```

`submit.sh --help` lists every option. For `llm_examples` it:
1. checks out `origin/<branch>` in `~/VisAgent/runs/<branch>`;
2. builds the pages (`python -m llm_taskgen.pages`);
3. runs the browser check if Node Playwright is installed, and stops on failure;
4. submits `hpc/llm_examples.slurm` as an array, one GPU node per library group
   (default `d3,plotly;chartjs,vega-lite`);
5. the last array task writes `summary.md` (bait/ASR, exposure) in the run directory.

The other suites submit their existing job files (`run_*.slurm`) unchanged.

## One-time setup on the cluster

The job files assume what the existing ones do: a checkout at `~/VisAgent/test`,
`pip install --user -r requirements.txt`, Ollama in `~/ollama/bin`, models in
`/scratch.global/$USER/ollama-models` and Playwright Chromium in
`/scratch.global/$USER/pw-browsers`.
