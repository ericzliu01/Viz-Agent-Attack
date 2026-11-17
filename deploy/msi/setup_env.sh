#!/bin/bash -l
# ---------------------------------------------------------------------------
# setup_env.sh -- idempotent environment bootstrap for running the
# Viz-Agent-Attack evaluation against a LOCAL Ollama Qwen3-VL target on MSI
# (UMN Agate HPC).
#
# Run this ONCE on a login node (ahl01) or an interactive node, from anywhere
# inside the repo checkout. It is safe to re-run: it reuses an existing venv and
# an already-downloaded Ollama, and only reinstalls what is missing.
#
# What it does:
#   1. `module load` a modern Python (3.10+)   [see PYTHON_MODULE below]
#   2. create/reuse a venv                      [see VENV_DIR below]
#   3. pip install -r requirements.txt + playwright
#   4. `playwright install chromium`            (no root; downloads to ~/.cache)
#   5. attempt `playwright install-deps`        (root-only; failure is tolerated)
#   6. verify headless Chromium actually launches
#   7. download the Ollama linux binary to a user-writable dir (no root)
#   8. print a success/verify summary
#
# NOTHING here needs sudo. The one root-only step (`playwright install-deps`) is
# attempted and its failure is reported, not fatal -- see the README
# "Chromium system-lib deps" troubleshooting section.
# ---------------------------------------------------------------------------
set -euo pipefail

# ----- Tunables (override by exporting before running) ----------------------
# PLACEHOLDER: confirm the exact module name with `module avail python` on MSI.
# As of writing MSI's system python3 is 3.6.8 (too old); you MUST load a 3.10+
# module. Common MSI names look like "python3.10", "python/3.10", or a conda
# module -- verify and set PYTHON_MODULE accordingly.
PYTHON_MODULE="${PYTHON_MODULE:-python3.10}"

# The venv lives under $HOME by default. $HOME has a modest quota on MSI; the
# venv itself is small (~1 GB with Playwright's Chromium cache), so $HOME is
# usually fine. Override to a scratch path if you prefer.
VENV_DIR="${VENV_DIR:-$HOME/viz-agent-venv}"

# Ollama install (no root): we download the official release tarball and extract
# it to a user-writable dir. The `curl | sh` installer writes to /usr/local and
# needs root, so we deliberately AVOID it.
OLLAMA_DIR="${OLLAMA_DIR:-$HOME/ollama}"
# PLACEHOLDER: bump to the latest Ollama release that ships qwen3-vl support.
OLLAMA_VERSION="${OLLAMA_VERSION:-v0.6.8}"
OLLAMA_PLATFORM="${OLLAMA_PLATFORM:-linux-amd64}"

# ---------------------------------------------------------------------------
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
echo "=== Viz-Agent-Attack MSI setup ==="
echo "Repo root     : $REPO_ROOT"
echo "Python module : $PYTHON_MODULE   (PLACEHOLDER -- confirm with 'module avail python')"
echo "Venv dir      : $VENV_DIR"
echo "Ollama dir    : $OLLAMA_DIR ($OLLAMA_VERSION, $OLLAMA_PLATFORM)"
echo

# ----- 1. Load a modern Python via Lmod ------------------------------------
# `#!/bin/bash -l` above gives us a login shell so `module` is defined. If it
# is somehow not, try sourcing the Lmod init explicitly.
if ! command -v module >/dev/null 2>&1; then
  for init in /etc/profile.d/lmod.sh /etc/profile.d/z00_lmod.sh /etc/profile.d/modules.sh; do
    [ -f "$init" ] && source "$init" && break
  done
fi
if command -v module >/dev/null 2>&1; then
  echo "[1/7] module load $PYTHON_MODULE"
  module load "$PYTHON_MODULE"
else
  echo "[1/7] WARNING: 'module' command not found; relying on PATH python3." >&2
fi

PYTHON_BIN="$(command -v python3 || true)"
if [ -z "$PYTHON_BIN" ]; then
  echo "ERROR: no python3 on PATH after module load. Fix PYTHON_MODULE." >&2
  exit 1
fi
PY_VER="$("$PYTHON_BIN" -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
echo "       python3 -> $PYTHON_BIN (version $PY_VER)"
"$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,10) else 1)' || {
  echo "ERROR: python $PY_VER is too old (need >=3.10). Fix PYTHON_MODULE." >&2
  exit 1
}

# ----- 2. Create / reuse the venv ------------------------------------------
if [ ! -f "$VENV_DIR/bin/activate" ]; then
  echo "[2/7] creating venv at $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
else
  echo "[2/7] reusing existing venv at $VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# ----- 3. Install python deps ----------------------------------------------
echo "[3/7] pip install -U pip + requirements.txt"
python -m pip install -U pip
python -m pip install -r "$REPO_ROOT/requirements.txt"
# requirements.txt already lists playwright, but pin it explicitly too in case
# that file changes; installing the full requirements is simplest and the only
# heavy transitive dep (anthropic) is lazy-imported at runtime for the Ollama
# path, so it is harmless if present.
python -m pip install "playwright>=1.49"

# ----- 4. Install Playwright's Chromium (no root) --------------------------
echo "[4/7] playwright install chromium (downloads browser to ~/.cache/ms-playwright)"
python -m playwright install chromium

# ----- 5. System library deps (root-only; tolerated failure) ---------------
# `playwright install-deps` apt-get installs Chromium's shared libs and REQUIRES
# ROOT -- it will fail on MSI compute/login nodes where you have no sudo. That is
# expected. If Chromium fails to launch in step 6, see the README troubleshooting
# ("Chromium system-lib deps on compute nodes"): the usual no-root fix is to
# `module load` a system libs / mesa / nss module, or run the compute job in a
# container (apptainer/singularity) that ships the libs.
echo "[5/7] attempting 'playwright install-deps' (root-only; failure is OK)"
if python -m playwright install-deps chromium 2>/tmp/pw-deps.$$; then
  echo "       install-deps succeeded (you have root, or deps already present)"
else
  echo "       install-deps could not run without root -- this is expected on MSI."
  echo "       If step 6 fails, resolve system libs the no-root way (see README)."
fi
rm -f "/tmp/pw-deps.$$" 2>/dev/null || true

# ----- 6. Verify headless Chromium actually launches -----------------------
echo "[6/7] verifying headless Chromium launch"
if python - <<'PYEOF'
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch()  # headless by default
    pg = b.new_page()
    pg.set_content("<h1 id=x>ok</h1>")
    assert pg.text_content("#x") == "ok"
    b.close()
print("       Chromium headless launch: OK")
PYEOF
then
  CHROMIUM_OK=1
else
  CHROMIUM_OK=0
  echo "       Chromium headless launch: FAILED (missing system libs -- see README)." >&2
fi

# ----- 7. Download Ollama (no root) ----------------------------------------
OLLAMA_BIN="$OLLAMA_DIR/bin/ollama"
if [ -x "$OLLAMA_BIN" ]; then
  echo "[7/7] reusing existing Ollama at $OLLAMA_BIN"
else
  echo "[7/7] downloading Ollama $OLLAMA_VERSION ($OLLAMA_PLATFORM) to $OLLAMA_DIR"
  mkdir -p "$OLLAMA_DIR"
  TGZ_URL="https://github.com/ollama/ollama/releases/download/${OLLAMA_VERSION}/ollama-${OLLAMA_PLATFORM}.tgz"
  TMP_TGZ="$(mktemp)"
  # The .tgz unpacks to bin/ollama (+ lib/ with bundled CUDA/ROCm runners); it
  # needs no root and no system-wide install.
  if curl -fL "$TGZ_URL" -o "$TMP_TGZ"; then
    tar -xzf "$TMP_TGZ" -C "$OLLAMA_DIR"
    rm -f "$TMP_TGZ"
  else
    rm -f "$TMP_TGZ"
    echo "ERROR: could not download $TGZ_URL" >&2
    echo "       Confirm OLLAMA_VERSION exists for '$OLLAMA_PLATFORM' at" >&2
    echo "       https://github.com/ollama/ollama/releases" >&2
    exit 1
  fi
fi
if [ ! -x "$OLLAMA_BIN" ]; then
  echo "ERROR: ollama binary not found at $OLLAMA_BIN after extraction." >&2
  exit 1
fi
export PATH="$OLLAMA_DIR/bin:$PATH"
echo -n "       ollama version: "; "$OLLAMA_BIN" --version || true

# ----- Summary --------------------------------------------------------------
echo
echo "=== SETUP SUMMARY ==="
echo "  venv            : $VENV_DIR   (activate with: source $VENV_DIR/bin/activate)"
echo "  python          : $("$VENV_DIR/bin/python" -V 2>&1)"
echo "  playwright      : $("$VENV_DIR/bin/python" -m playwright --version 2>&1 || echo '??')"
echo "  chromium launch : $([ "$CHROMIUM_OK" = 1 ] && echo OK || echo 'FAILED -- see README')"
echo "  ollama binary   : $OLLAMA_BIN"
echo
echo "Next: edit the PLACEHOLDERS in deploy/msi/run_eval.slurm (account, partition,"
echo "model tag, paths), then:  sbatch deploy/msi/run_eval.slurm"
if [ "$CHROMIUM_OK" != 1 ]; then
  echo
  echo "WARNING: Chromium did not launch headless. The GPU job WILL FAIL at the"
  echo "         browser step until this is fixed. See README troubleshooting." >&2
  exit 1
fi
