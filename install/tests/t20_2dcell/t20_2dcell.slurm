#!/bin/bash
# T-20 — the CORRECTED oxide cell: DPA lattices + a worst-axis-ranked 2-D
# coincidence (not the exploding ribbon). Part 1 (sabsim env) builds the
# pristine pair; part 2 (deepmd bundle) measures frame-0 stress, applies
# the item-3 box-relax, and runs a short NVT -- reporting atom COUNT at
# every stage so a disintegration is caught, and dumping a movie for OVITO.
#SBATCH --job-name=t20-2dcell
#SBATCH --partition=gpu
#SBATCH --account=general
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:V100-PCIE-32GB:1
#SBATCH --mem=48G
#SBATCH --time=02:00:00
#SBATCH --chdir=/cluster/VAST/rulisp-lab/cpg/share/models/dpa_gpu_bench
#SBATCH --output=t20-2dcell-%j.out
#SBATCH --error=t20-2dcell-%j.err
set -uo pipefail

REPO=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim
SHARE=/cluster/VAST/rulisp-lab/cpg
BENCH="$SHARE/share/models/dpa_gpu_bench"
PREFIX="$SHARE/programs/deepmd-kit-3.2.0b0-cuda129"

export VALWORK="${VALWORK:-$BENCH/v_2dcell}"
export SABSIM_CASCADE_MLIP_MODEL="$BENCH/v320fix/dpa24.pt2"
mkdir -p "$VALWORK"

echo "=== node / gpu ==="; nvidia-smi -L || true

echo "=== Part 1: build the pristine 2-D pair (sabsim env) ==="
source "$SHARE/virtual_envs/sabsim/bin/activate" 2>/dev/null || true
python "$REPO/install/tests/t20_2dcell/prepare_pair.py" || exit 5

echo "=== Part 2: frame-0 stress + box-relax + NVT (bundle python) ==="
(
  unset PYTHONPATH LD_LIBRARY_PATH LAMMPS_PLUGIN_PATH DEEPMD_LMP_PLUGIN
  unset CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_PREFIX_1 CONDA_PREFIX_2
  unset CONDA_PROMPT_MODIFIER
  export CONDA_SHLVL=0
  export PATH=/usr/bin:/bin
  source "$PREFIX/etc/profile.d/conda.sh"
  conda activate "$PREFIX"
  export PYTHONPATH="$REPO/src"
  python "$REPO/install/tests/t20_2dcell/frame0_check.py"
)
rc=$?
echo "=== T-20 exit $rc ==="
echo "=== DONE ==="
exit $rc
