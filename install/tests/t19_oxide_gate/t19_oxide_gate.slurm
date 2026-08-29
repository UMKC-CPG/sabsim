#!/bin/bash
# T-19 — the REAL per-wafer §3.5 gate + press under the universal DPA model.
# Part 1 (sabsim env): assemble the matched SiO2/LiNbO3 pair, recording each
# wafer's declared species so the gate keys per wafer. Part 2 (deepmd BUNDLE
# python, ISOLATED): run sabsim's driver with NO demo gate-bypass, so the
# real gate loads O_Si.toml for wafer A and Li_Nb_O.toml for wafer B and
# judges each. A FAILED gate halts before the press (correct); a PASS runs
# the combined-cell relax + press. Item 6 validation.
#SBATCH --job-name=t19-oxide-gate
#SBATCH --partition=gpu
#SBATCH --account=general
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:V100-PCIE-32GB:1
#SBATCH --mem=48G
#SBATCH --time=06:00:00
#SBATCH --chdir=/cluster/VAST/rulisp-lab/cpg/share/models/dpa_gpu_bench
#SBATCH --output=t19-oxide-gate-%j.out
#SBATCH --error=t19-oxide-gate-%j.err
set -uo pipefail

REPO=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim
SHARE=/cluster/VAST/rulisp-lab/cpg
BENCH="$SHARE/share/models/dpa_gpu_bench"
PREFIX="$SHARE/programs/deepmd-kit-3.2.0b0-cuda129"

export SABSIM_TEMPLATE="$REPO/share/templates/study_spec.toml"
_sio2="$BENCH/t12_val_sio2_noprerelax/sio2_activated.extxyz"
_linbo3="$BENCH/t12_val_linbo3_25ev_noprerelax/linbo3_activated.extxyz"
export SIO2_SURFACE="${SIO2_SURFACE:-$_sio2}"
export LINBO3_SURFACE="${LINBO3_SURFACE:-$_linbo3}"
export MATCH_PKL="$BENCH/t12_val/match.pkl"
export SABSIM_CASCADE_MLIP_MODEL="$BENCH/v320fix/dpa24.pt2"
export VALWORK="${VALWORK:-$BENCH/t19_val}"
mkdir -p "$VALWORK"

echo "=== node / gpu ==="; nvidia-smi -L || true

echo "=== Part 1: assemble the pair with per-wafer species (sabsim env) ==="
source "$SHARE/virtual_envs/sabsim/bin/activate" 2>/dev/null || true
ls "$SIO2_SURFACE" "$LINBO3_SURFACE" || { echo "surfaces missing"; exit 4; }
python "$REPO/install/tests/t19_oxide_gate/assemble_pair.py" || exit 5

echo "=== Part 2: real per-wafer gate + press (bundle python, ISOLATED) ==="
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
  python "$REPO/install/tests/t19_oxide_gate/driver_press_pull.py"
)
rc=$?
echo "=== T-19 exit $rc ==="
if [ $rc -ne 0 ]; then
    echo "--- press log tail ---"
    tail -30 "$VALWORK/log.press" 2>/dev/null
fi
echo "=== DONE ==="
exit $rc
