#!/bin/bash
# T-17 — DPA equilibrium-lattice diagnostic for SiO2 and LiNbO3.
# Part 1 (sabsim env): tile each CIF into a bulk supercell + write LAMMPS
# data + baseline.json. Part 2 (deepmd BUNDLE python, ISOLATED): box-relax
# each crystal under the universal DPA .pt2 at zero pressure and report the
# model's preferred lattice vs the CIF baseline. Answers whether the T-16
# 24 GPa built-in stress is fixable by re-matching at the DPA lattices.
#SBATCH --job-name=t17-dpa-lattice
#SBATCH --partition=requeue
#SBATCH --account=general
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:V100-PCIE-32GB:1
#SBATCH --mem=32G
#SBATCH --time=03:00:00
#SBATCH --chdir=/cluster/VAST/rulisp-lab/cpg/share/models/dpa_gpu_bench
#SBATCH --output=t17-dpa-lattice-%j.out
#SBATCH --error=t17-dpa-lattice-%j.err
set -uo pipefail

REPO=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim
SHARE=/cluster/VAST/rulisp-lab/cpg
BENCH="$SHARE/share/models/dpa_gpu_bench"
PREFIX="$SHARE/programs/deepmd-kit-3.2.0b0-cuda129"

# Honor a per-run VALWORK via --export; fall back to a single default.
export VALWORK="${VALWORK:-$BENCH/t17_val}"
export T17_BUILD_DIR="$VALWORK"
export SIO2_CIF="$REPO/src/sabsim/structure/data/sio2_alpha_quartz.cif"
export LINBO3_CIF="$REPO/sunita/bond_debond/share/linbo3_bulk.cif"
export SABSIM_CASCADE_MLIP_MODEL="$BENCH/v320fix/dpa24.pt2"
mkdir -p "$VALWORK"

echo "=== node / gpu ==="; nvidia-smi -L || true

echo "=== Part 1: build bulk crystals (sabsim env) ==="
source "$SHARE/virtual_envs/sabsim/bin/activate" 2>/dev/null || true
ls "$SIO2_CIF" "$LINBO3_CIF" || { echo "CIF missing"; exit 4; }
python "$REPO/install/tests/t17_dpa_lattice/build_bulk_crystals.py" || exit 5

echo "=== Part 2: DPA box-relax (bundle python, ISOLATED) ==="
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
  python "$REPO/install/tests/t17_dpa_lattice/relax_lattice.py"
)
rc=$?
echo "=== T-17 exit $rc ==="
echo "=== DONE ==="
exit $rc
