#!/bin/bash
# T-15 — the REAL press/pull driver under the universal DPA model.
# Part 1 (sabsim env): assemble the matched SiO2/LiNbO3 pair + pickle a
# light built/member for part 2. Part 2 (deepmd BUNDLE python, ISOLATED):
# run sabsim's actual driver (press_and_bond -> settle -> pull) with the
# force model = DPA-2.4-7M .pt2, using the bundle's in-process lammps. The
# driver's import chain is pymatgen-free (wafer_tags decoupling) and ASE is
# installed in the bundle, so it just imports. DEMO (gate bypassed).
#SBATCH --job-name=t15-driver-dpa
#SBATCH --partition=gpu
#SBATCH --account=general
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:V100-PCIE-32GB:1
#SBATCH --mem=48G
#SBATCH --time=06:00:00
#SBATCH --chdir=/cluster/VAST/rulisp-lab/cpg/share/models/dpa_gpu_bench
#SBATCH --output=t15-driver-dpa-%j.out
#SBATCH --error=t15-driver-dpa-%j.err
set -uo pipefail

REPO=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim
SHARE=/cluster/VAST/rulisp-lab/cpg
BENCH="$SHARE/share/models/dpa_gpu_bench"
PREFIX="$SHARE/programs/deepmd-kit-3.2.0b0-cuda129"

export SABSIM_TEMPLATE="$REPO/dev/templates/study_spec.toml"
# Default to the NO-PRERELAX surfaces (override via --export to compare).
_sio2="$BENCH/t12_val_sio2_noprerelax/sio2_activated.extxyz"
_linbo3="$BENCH/t12_val_linbo3_25ev_noprerelax/linbo3_activated.extxyz"
export SIO2_SURFACE="${SIO2_SURFACE:-$_sio2}"
export LINBO3_SURFACE="${LINBO3_SURFACE:-$_linbo3}"
export MATCH_PKL="$BENCH/t12_val/match.pkl"
export SABSIM_CASCADE_MLIP_MODEL="$BENCH/v320fix/dpa24.pt2"
# Honor a per-run VALWORK passed via --export (e.g. one dir per limiting
# pair) so concurrent jobs never share an output directory. Bare `sbatch`
# with no override falls back to the single-run default. The earlier T-16
# batch hardcoded this and both pairs raced in one dir; the fallback form
# fixes that while keeping the no-arg path working.
export VALWORK="${VALWORK:-$BENCH/t15_val}"
mkdir -p "$VALWORK"

echo "=== node / gpu ==="; nvidia-smi -L || true

echo "=== Part 1: assemble the pair (sabsim env) ==="
source "$SHARE/virtual_envs/sabsim/bin/activate" 2>/dev/null || true
ls "$SIO2_SURFACE" "$LINBO3_SURFACE" || { echo "surfaces missing"; exit 4; }
python "$REPO/install/tests/t15_driver_dpa/assemble_pair.py" || exit 5

echo "=== Part 2: real driver under DPA (bundle python, ISOLATED) ==="
(
  unset PYTHONPATH LD_LIBRARY_PATH LAMMPS_PLUGIN_PATH DEEPMD_LMP_PLUGIN
  unset CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_PREFIX_1 CONDA_PREFIX_2
  unset CONDA_PROMPT_MODIFIER
  export CONDA_SHLVL=0
  export PATH=/usr/bin:/bin
  source "$PREFIX/etc/profile.d/conda.sh"
  conda activate "$PREFIX"
  export PYTHONPATH="$REPO/src"
  case "$(command -v python)" in
    "$PREFIX"/*) : ;;
    *) echo "WRONG bundle python"; exit 2 ;;
  esac
  python "$REPO/install/tests/t15_driver_dpa/driver_press_pull.py"
)
rc=$?
echo "=== T-15 exit $rc ==="
if [ $rc -ne 0 ]; then
    echo "--- press log tail ---"
    tail -30 "$VALWORK/log.press" 2>/dev/null || true
fi
echo "=== DONE ==="
exit $rc
