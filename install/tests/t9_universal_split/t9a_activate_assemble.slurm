#!/bin/bash
# T-9a — universal cascade-only activate (GPU) + wide-gap assemble.
#
# sabsim (this env) builds a small Si slab and emits the cascade-ONLY
# script, spawns the deepmd bundle's lmp as an ISOLATED subprocess to run
# the universal DPA-2.4-7M + ZBL cascade on the GPU, reads each amorphized
# half back, and assembles the pair at the WIDE gap — writing it for Job B.
# Cascade-only: NO re-anneal, NO gate here, so NO LAMMPS_POTENTIALS (the
# heal + §3.5 gate moved to the bond job, T-9b). Submit from a shell with
# the sabsim env active (--export=ALL carries it in); or use submit.sh.
#SBATCH --job-name=t9a-activate
#SBATCH --partition=gpu,requeue
#SBATCH --account=general
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:V100-PCIE-32GB:1
#SBATCH --mem=48G
#SBATCH --time=00:40:00
# --chdir so the log paths below fit in 80 cols; the script itself uses
# absolute paths throughout, so the working directory does not matter.
#SBATCH --chdir=/cluster/VAST/rulisp-lab/cpg/share/models/dpa_gpu_bench
#SBATCH --output=t9-activate-%j.out
#SBATCH --error=t9-activate-%j.err
set -uo pipefail

# [ADAPT] every path below to your cluster.
REPO=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim
SHARE=/cluster/VAST/rulisp-lab/cpg
BENCH="$SHARE/share/models/dpa_gpu_bench"

# The out-of-process cascade engine (the deepmd bundle, its OWN torch/MPI)
# and the GPU-arch-specific universal .pt2 it loads. The exploratory opt-in
# is set because DPA-2.4-7M has not yet cleared the §3.5 gate.
export SABSIM_CASCADE_ENGINE_PREFIX="$SHARE/programs/deepmd-kit-3.2.0b0-cuda129"
export SABSIM_CASCADE_MLIP_MODEL="$BENCH/v320fix/dpa24.pt2"
export SABSIM_ALLOW_UNVALIDATED_POTENTIAL=1
export SABSIM_TEMPLATE="$REPO/share/templates/study_spec.toml"
# The shared scratch the A->B handoff lives in (assembled_pair.data + the
# BuiltPair pickle). Same dir Job B reads.
export VALWORK="$BENCH/t9_val"
mkdir -p "$VALWORK"

echo "=== node / gpu ==="; nvidia-smi -L || true
echo "=== modules (expect none: universal path uses the bundle) ==="
module list 2>&1 || true
echo "=== sabsim env ==="
source "$SHARE/virtual_envs/sabsim/bin/activate" 2>/dev/null || true
echo "python=$(command -v python)"
python -c "import sabsim, ase; print('sabsim env OK')" || exit 2
ls "$SABSIM_CASCADE_MLIP_MODEL" || { echo "MODEL missing"; exit 3; }

echo "=== running T-9a (activate + wide assemble) ==="
python "$REPO/install/tests/t9_universal_split/t9a_activate_assemble.py"
rc=$?
echo "=== T-9a exit $rc ==="
if [ $rc -ne 0 ]; then
    echo "--- last activate subprocess log tail ---"
    tail -40 "$VALWORK"/log.activate_* 2>/dev/null || true
fi
echo "=== DONE ==="
exit $rc
