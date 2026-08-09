#!/bin/bash
# T-9b — bond-flow heal + per-wafer gate + press (committee of one).
#
# Reads Job A's WIDE-gap assembled pair and runs the re-architected bond
# flow IN-PROCESS on the GPU under a single frozen bespoke DeePMD model
# (the SABSIM_DEEPMD_MODEL override = "committee of one"): press_and_bond
# HEALS the combined cell, GATES each healed surface per wafer tag, halts
# on a failed gate, else scissors + presses. Depends on T-9a (afterok) via
# submit.sh so the assembled pair is on disk. The in-process deepmd engine
# comes from the conda-derived module (needs NO libstdc++ LD_PRELOAD — the
# env already carries the CXXABI; the plugin is loaded by a LAMMPS input).
#SBATCH --job-name=t9b-bond
#SBATCH --partition=gpu,requeue
#SBATCH --account=general
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:V100-PCIE-32GB:1
#SBATCH --mem=32G
#SBATCH --time=00:40:00
# --chdir so the log paths below fit in 80 cols; the script itself uses
# absolute paths throughout, so the working directory does not matter.
#SBATCH --chdir=/cluster/VAST/rulisp-lab/cpg/share/models/dpa_gpu_bench
#SBATCH --output=t9-bond-%j.out
#SBATCH --error=t9-bond-%j.err
set -uo pipefail

# [ADAPT] every path below to your cluster.
REPO=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim
SHARE=/cluster/VAST/rulisp-lab/cpg
BENCH="$SHARE/share/models/dpa_gpu_bench"

# The committee of one: the group's trained Si graph.pb (type_map [Si],
# rcut 6). The bond flow presses under THIS model, in-process.
export SABSIM_DEEPMD_MODEL="$SHARE/share/train_deepmd_si/graph.pb"
export SABSIM_TEMPLATE="$REPO/dev/templates/study_spec.toml"
export VALWORK="$BENCH/t9_val"

# LAMMPS needs the SLURM per-* memory exports cleared or the launch aborts
# (ARCHITECTURE §4.1); LAMMPS_PLUGIN_PATH unset so no stray plugin auto-
# loads before our explicit `plugin load` (LEDGER T-CONDA-ENGINE note).
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
ls "$VALWORK/built_pair.pkl" || { echo "no assembled pair from T-9a"; exit 4; }

echo "=== running T-9b (bond heal + gate + press) ==="
srun --mpi=pmix -n 1 \
    python "$REPO/install/tests/t9_universal_split/t9b_bond_press.py"
rc=$?
echo "=== T-9b exit $rc ==="
if [ $rc -ne 0 ]; then
    echo "--- bond press log tail ---"
    tail -40 "$VALWORK/log.bond_press" 2>/dev/null || true
fi
echo "=== DONE ==="
exit $rc
