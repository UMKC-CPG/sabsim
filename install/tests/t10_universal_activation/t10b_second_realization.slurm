#!/bin/bash
# T-10b — a SECOND, independent Si activation (different cascade seed), so
# the Si bond-debond can use a genuine A != B pair (surface A from T-10,
# surface B from here) instead of one surface mirrored. Same 6x6x10 slab
# and full fluence as T-10, run on a REQUEUE V100 (the idle capacity there)
# in parallel with the three gpu-partition jobs. Preemptible: if bumped it
# requeues and restarts (the cascade is not checkpointed) — acceptable for
# a bonus realization. Writes to its OWN dir so it never touches T-10.
#SBATCH --job-name=t10b-si-realization
#SBATCH --partition=requeue
#SBATCH --account=general
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:V100-PCIE-32GB:1
#SBATCH --mem=48G
# ~11 h; 16 h wall gives margin and stays well before Tuesday 08:00.
#SBATCH --time=16:00:00
#SBATCH --chdir=/cluster/VAST/rulisp-lab/cpg/share/models/dpa_gpu_bench
#SBATCH --output=t10b-si-%j.out
#SBATCH --error=t10b-si-%j.err
set -uo pipefail

REPO=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim
SHARE=/cluster/VAST/rulisp-lab/cpg
BENCH="$SHARE/share/models/dpa_gpu_bench"

export SABSIM_CASCADE_ENGINE_PREFIX="$SHARE/programs/deepmd-kit-3.2.0b0-cuda129"
export SABSIM_CASCADE_MLIP_MODEL="$BENCH/v320fix/dpa24.pt2"
export SABSIM_ALLOW_UNVALIDATED_POTENTIAL=1
export SABSIM_TEMPLATE="$REPO/share/templates/study_spec.toml"
# Own scratch dir + a DISTINCT seed = an independent realization.
export VALWORK="$BENCH/t10b_val"
export T10_SEED=20260810
mkdir -p "$VALWORK"

echo "=== T-10b: second Si realization (seed $T10_SEED) ==="
echo "=== node / gpu ==="; nvidia-smi -L || true
module list 2>&1 || true
source "$SHARE/virtual_envs/sabsim/bin/activate" 2>/dev/null || true
echo "python=$(command -v python)"
python -c "import sabsim, ase; print('sabsim env OK')" || exit 2
ls "$SABSIM_CASCADE_MLIP_MODEL" || { echo "MODEL missing"; exit 3; }

echo "=== running T-10b (full-fluence universal activate + gate) ==="
python "$REPO/install/tests/t10_universal_activation/t10_activate_gate.py"
rc=$?
echo "=== T-10b exit $rc ==="
if [ $rc -ne 0 ]; then
    echo "--- cascade log tail ---"
    tail -50 "$VALWORK/log.activate" 2>/dev/null || true
fi
echo "=== DONE ==="
exit $rc
