#!/bin/bash
# Runtime probe of the newly built conda-5.0.10 classical LAMMPS engine:
# import from its prefix, load its liblammps under the venv python, run a
# real Si SW MD step, single-rank and then across 2 nodes on the fabric.
#SBATCH --job-name=sabsim-engine-run
#SBATCH --partition=general
#SBATCH --account=general
#SBATCH --nodes=2
#SBATCH --ntasks-per-node=1
#SBATCH --time=00:15:00
#SBATCH --output=/mnt/pixstor/data/rulisp/ucx_fabric_test/engine_run-%j.out
#SBATCH --error=/mnt/pixstor/data/rulisp/ucx_fabric_test/engine_run-%j.err

# No `set -e`: run both stages regardless.

DEV=/cluster/VAST/rulisp-lab/cpg/mamba/envs/sabsim_dev
VENV=/cluster/VAST/rulisp-lab/cpg/virtual_envs/sabsim_dev
ENGINE=/cluster/VAST/rulisp-lab/cpg/programs/lammps/22Jul2025-conda-ompi5.0.10
PY="$VENV/bin/python"
HERE=/mnt/pixstor/data/rulisp/ucx_fabric_test

# Select the classical engine like a module: its ctypes wrapper on
# PYTHONPATH, its liblammps + the conda libs on LD_LIBRARY_PATH, and its
# bundled potentials (so `pair_coeff * * Si.sw Si` resolves).
export PYTHONPATH="$ENGINE/lib64/python:${PYTHONPATH:-}"
export LD_LIBRARY_PATH="$ENGINE/lib64:$DEV/lib:${LD_LIBRARY_PATH:-}"
export LAMMPS_POTENTIALS="$ENGINE/share/lammps/potentials"

# Launcher fix (job 15551533): the allocation exports these mutually-
# exclusive, which aborts the nested launch.
unset SLURM_MEM_PER_NODE SLURM_MEM_PER_CPU SLURM_MEM_PER_GPU

echo "nodelist: $SLURM_JOB_NODELIST   ntasks: $SLURM_NTASKS"
echo "engine  : $ENGINE"
echo "python  : $PY"

echo
echo "########### single rank — import + run ###########"
srun --mpi=pmix -n 1 -N 1 "$PY" "$HERE/engine_run.py"
echo "=== single-rank exit: $? ==="

echo
echo "########### 2 ranks across 2 nodes — fabric ###########"
UCX_LOG_LEVEL=info srun --mpi=pmix -n "$SLURM_NTASKS" \
    "$PY" "$HERE/engine_run.py"
echo "=== 2-node exit: $? ==="
