#!/bin/bash
# T-14 — press-pull the SiO2/LiNbO3 pair under the UNIVERSAL DPA model,
# out-of-process in the deepmd bundle on the GPU. Same potential that made
# the surfaces => no potential-change collapse (T-13's failure was pressing
# DPA surfaces under Prakash's model). A self-contained press-pull script
# (heal -> press -> hold -> pull) recording a movie. A workflow visual.
#SBATCH --job-name=t14-dpa-press-pull
#SBATCH --partition=gpu
#SBATCH --account=general
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:V100-PCIE-32GB:1
#SBATCH --mem=48G
#SBATCH --time=04:00:00
#SBATCH --chdir=/cluster/VAST/rulisp-lab/cpg/share/models/dpa_gpu_bench
#SBATCH --output=t14-dpa-press-pull-%j.out
#SBATCH --error=t14-dpa-press-pull-%j.err
set -uo pipefail

REPO=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim
SHARE=/cluster/VAST/rulisp-lab/cpg
BENCH="$SHARE/share/models/dpa_gpu_bench"

export SABSIM_CASCADE_ENGINE_PREFIX="$SHARE/programs/deepmd-kit-3.2.0b0-cuda129"
export SABSIM_CASCADE_MLIP_MODEL="$BENCH/v320fix/dpa24.pt2"
export OXIDE_PAIR_DATA="$BENCH/t13_val/oxide_pair.data"
export VALWORK="$BENCH/t14_val"
mkdir -p "$VALWORK"

echo "=== node / gpu ==="; nvidia-smi -L || true
source "$SHARE/virtual_envs/sabsim/bin/activate" 2>/dev/null || true
python -c "import sabsim, ase; print('sabsim env OK')" || exit 2
ls "$SABSIM_CASCADE_MLIP_MODEL" || { echo "MODEL missing"; exit 3; }
ls "$OXIDE_PAIR_DATA" || { echo "assembled pair missing (run T-13 first)"; exit 4; }

echo "=== running T-14 (DPA press-pull) ==="
python "$REPO/install/tests/t14_dpa_press_pull/t14_dpa_press_pull.py"
rc=$?
echo "=== T-14 exit $rc ==="
if [ $rc -ne 0 ]; then
    echo "--- press-pull log tail ---"
    tail -50 "$VALWORK/log.press_pull" 2>/dev/null || true
fi
echo "=== DONE ==="
exit $rc
