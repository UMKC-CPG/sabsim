#!/bin/bash
# T-10 — first gate-passing universal activation (§3.5, §4.7).
#
# Runs a FULL-fluence universal DPA-2.4-7M cascade on a ~2880-atom Si slab
# out-of-process on the GPU (recording a trajectory MOVIE of the whole
# bombardment), reads the amorphized surface back, and gates it DIRECTLY. A
# gate PASS is the evidence to flip the model's `validated` flag (DESIGN
# §4.7). This is a LONG run (~12 h): the cascade is 27 impacts x ~6.5k steps
# at DPA-2.4-7M speed. NO requeue — the cascade subprocess is not
# checkpointed, so a preemption would restart it from zero.
#SBATCH --job-name=t10-activate-gate
#SBATCH --partition=gpu
#SBATCH --account=general
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:V100-PCIE-32GB:1
#SBATCH --mem=48G
# ~12-15 h estimated. Kept at 20 h so the job SCHEDULES before the cluster
# maintenance window (a longer wall would run into it and never start);
# 20 h still covers the run with margin. [ADAPT: raise toward the 2-day
# ceiling when no maintenance reservation is pending.]
#SBATCH --time=20:00:00
#SBATCH --chdir=/cluster/VAST/rulisp-lab/cpg/share/models/dpa_gpu_bench
#SBATCH --output=t10-activate-gate-%j.out
#SBATCH --error=t10-activate-gate-%j.err
set -uo pipefail

# [ADAPT] every path below to your cluster.
REPO=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim
SHARE=/cluster/VAST/rulisp-lab/cpg
BENCH="$SHARE/share/models/dpa_gpu_bench"

# The out-of-process cascade engine + the universal .pt2, plus the
# exploratory opt-in (DPA-2.4-7M has not cleared the gate yet — this run is
# what tries to).
export SABSIM_CASCADE_ENGINE_PREFIX="$SHARE/programs/deepmd-kit-3.2.0b0-cuda129"
export SABSIM_CASCADE_MLIP_MODEL="$BENCH/v320fix/dpa24.pt2"
export SABSIM_ALLOW_UNVALIDATED_POTENTIAL=1
export SABSIM_TEMPLATE="$REPO/share/templates/study_spec.toml"
export VALWORK="$BENCH/t10_val"
mkdir -p "$VALWORK"
# Slab size + movie density (defaults reproduce the reference geometry).
export T10_N_LATERAL=6
export T10_N_DEPTH=10
export T10_TRAJ_STRIDE=500

echo "=== node / gpu ==="; nvidia-smi -L || true
echo "=== modules (expect none: universal path uses the bundle) ==="
module list 2>&1 || true
echo "=== sabsim env ==="
source "$SHARE/virtual_envs/sabsim/bin/activate" 2>/dev/null || true
echo "python=$(command -v python)"
python -c "import sabsim, ase; print('sabsim env OK')" || exit 2
ls "$SABSIM_CASCADE_MLIP_MODEL" || { echo "MODEL missing"; exit 3; }

echo "=== running T-10 (full-fluence universal activate + gate) ==="
python "$REPO/install/tests/t10_universal_activation/t10_activate_gate.py"
rc=$?
echo "=== T-10 exit $rc ==="
if [ $rc -ne 0 ]; then
    echo "--- cascade subprocess log tail ---"
    tail -50 "$VALWORK/log.activate" 2>/dev/null || true
fi
echo "=== DONE ==="
exit $rc
