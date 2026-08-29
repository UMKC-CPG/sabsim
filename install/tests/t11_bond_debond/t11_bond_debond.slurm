#!/bin/bash
# T-11 — bond-debond on the T-10 universal-activated surface (committee of
# one). Assembles a facing pair from T-10's gate-passing DPA-2.4-7M-
# activated Si surface and runs the FULL bond flow IN-PROCESS on the GPU
# under a single frozen bespoke DeePMD model: heal -> per-wafer gate ->
# press -> settle -> pull -> work of separation. Records a press/pull
# movie. Depends on a COMPLETED, gate-PASSING T-10 (its activated.extxyz);
# submit only after confirming T-10 passed. The in-process deepmd engine
# comes from the conda module (no libstdc++ LD_PRELOAD needed).
#SBATCH --job-name=t11-bond-debond
#SBATCH --partition=gpu
#SBATCH --account=general
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:V100-PCIE-32GB:1
#SBATCH --mem=32G
# ~2-4 h under the fast graph.pb; 8 h gives margin and fits before the
# Tuesday maintenance window when fired Monday morning.
#SBATCH --time=08:00:00
#SBATCH --chdir=/cluster/VAST/rulisp-lab/cpg/share/models/dpa_gpu_bench
#SBATCH --output=t11-bond-debond-%j.out
#SBATCH --error=t11-bond-debond-%j.err
set -uo pipefail

# [ADAPT] every path below to your cluster.
REPO=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim
SHARE=/cluster/VAST/rulisp-lab/cpg
BENCH="$SHARE/share/models/dpa_gpu_bench"

# The committee of one (the group's trained Si graph.pb), T-10's output
# dir (holds activated.extxyz), and this run's scratch.
export SABSIM_DEEPMD_MODEL="$SHARE/share/train_deepmd_si/graph.pb"
export SABSIM_TEMPLATE="$REPO/share/templates/study_spec.toml"
export T10_VALWORK="$BENCH/t10_val"
export VALWORK="$BENCH/t11_val"
mkdir -p "$VALWORK"

# LAMMPS: clear the SLURM per-* memory exports (§4.1) and any stray plugin
# path so only our explicit `plugin load` runs (LEDGER T-CONDA-ENGINE note).
unset SLURM_MEM_PER_NODE SLURM_MEM_PER_CPU SLURM_MEM_PER_GPU
unset LAMMPS_PLUGIN_PATH

echo "=== node / gpu ==="; nvidia-smi -L || true
echo "=== sabsim env + in-process deepmd engine module ==="
source "$SHARE/virtual_envs/sabsim/bin/activate" 2>/dev/null || true
module use "$SHARE/modulefiles"
module load cpg_lammps_conda/2024.08.29-deepmd
module list 2>&1 || true
echo "python=$(command -v python)"
python -c "import sabsim, lammps; print('sabsim + lammps import OK')" || exit 2
ls "$SABSIM_DEEPMD_MODEL" || { echo "MODEL missing"; exit 3; }
ls "$T10_VALWORK/activated.extxyz" || { echo "no T-10 surface"; exit 4; }

echo "=== running T-11 (bond-debond on the T-10 surface) ==="
srun --mpi=pmix -n 1 \
    python "$REPO/install/tests/t11_bond_debond/t11_bond_debond.py"
rc=$?
echo "=== T-11 exit $rc ==="
if [ $rc -ne 0 ]; then
    echo "--- press/pull log tails ---"
    tail -40 "$VALWORK/log.press" 2>/dev/null || true
fi
echo "=== DONE ==="
exit $rc
