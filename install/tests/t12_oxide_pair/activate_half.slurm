#!/bin/bash
# Amorphize ONE pre-built matched oxide half (SiO2 or LiNbO3) with the
# universal DPA-2.4-7M cascade, out-of-process on the GPU, recording a
# movie. Which half is set by T12_HALF_NAME (passed via --export by
# submit.sh: sio2 | linbo3). Reads the pre-built {name}_half.{data,pkl}
# from VALWORK. NO gate (no oxide reference yet) — this CREATES the
# amorphous surface. ~4-5 h; 10 h walltime is generous and fits well
# before the Tuesday maintenance window.
#SBATCH --job-name=t12-oxide-activate
#SBATCH --partition=gpu
#SBATCH --account=general
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:V100-PCIE-32GB:1
#SBATCH --mem=48G
#SBATCH --time=10:00:00
#SBATCH --chdir=/cluster/VAST/rulisp-lab/cpg/share/models/dpa_gpu_bench
#SBATCH --output=t12-activate-%j.out
#SBATCH --error=t12-activate-%j.err
set -uo pipefail

: "${T12_HALF_NAME:?set T12_HALF_NAME=sio2|linbo3 (submit.sh does this)}"

# [ADAPT] every path below to your cluster.
REPO=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim
SHARE=/cluster/VAST/rulisp-lab/cpg
BENCH="$SHARE/share/models/dpa_gpu_bench"

# The out-of-process cascade engine + universal .pt2 (exploratory opt-in:
# DPA-2.4-7M is not yet gate-cleared — and there is no oxide gate yet).
export SABSIM_CASCADE_ENGINE_PREFIX="$SHARE/programs/deepmd-kit-3.2.0b0-cuda129"
export SABSIM_CASCADE_MLIP_MODEL="$BENCH/v320fix/dpa24.pt2"
export SABSIM_ALLOW_UNVALIDATED_POTENTIAL=1
export SABSIM_TEMPLATE="$REPO/share/templates/study_spec.toml"
# VALWORK (outputs) + T12_BUILD_DIR (the pre-built half) default to t12_val
# but honour an --export override, so an energy re-run writes to its OWN dir
# while reading the one matched build. T12_ENERGY_EV (if exported) sets the
# beam energy; unset keeps the study's 75 eV.
export T12_BUILD_DIR="${T12_BUILD_DIR:-$BENCH/t12_val}"
export VALWORK="${VALWORK:-$BENCH/t12_val}"
mkdir -p "$VALWORK"

echo "=== half: $T12_HALF_NAME ==="
echo "=== node / gpu ==="; nvidia-smi -L || true
module list 2>&1 || true
source "$SHARE/virtual_envs/sabsim/bin/activate" 2>/dev/null || true
echo "python=$(command -v python)"
python -c "import sabsim, ase; print('sabsim env OK')" || exit 2
ls "$SABSIM_CASCADE_MLIP_MODEL" || { echo "MODEL missing"; exit 3; }
ls "$T12_BUILD_DIR/${T12_HALF_NAME}_half.pkl" \
    || { echo "no pre-built half in $T12_BUILD_DIR"; exit 4; }

echo "=== running oxide cascade ($T12_HALF_NAME) ==="
python "$REPO/install/tests/t12_oxide_pair/activate_half.py"
rc=$?
echo "=== $T12_HALF_NAME exit $rc ==="
if [ $rc -ne 0 ]; then
    echo "--- cascade log tail ---"
    tail -50 "$VALWORK/log.activate_${T12_HALF_NAME}" 2>/dev/null || true
fi
echo "=== DONE ==="
exit $rc
