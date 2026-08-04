#!/bin/bash
# Launcher FIX test: the nested srun that OpenMPI 5 / PRRTE uses to launch
# its per-node daemon died on "SLURM_MEM_PER_CPU/GPU/NODE are mutually
# exclusive" (job 15551533). Clear those vars, then retry the srun-based
# launches. A 2-host COMM_WORLD + ping-pong here settles BOTH the launcher
# and the fabric-bandwidth questions.
#SBATCH --job-name=sabsim-launch-fix
#SBATCH --partition=general
#SBATCH --account=general
#SBATCH --nodes=2
#SBATCH --ntasks-per-node=1
#SBATCH --time=00:10:00
#SBATCH --output=/mnt/pixstor/data/rulisp/ucx_fabric_test/launch_fix-%j.out
#SBATCH --error=/mnt/pixstor/data/rulisp/ucx_fabric_test/launch_fix-%j.err

# No `set -e`: run both methods regardless.

DEV=/cluster/VAST/rulisp-lab/cpg/mamba/envs/sabsim_dev
VENV=/cluster/VAST/rulisp-lab/cpg/virtual_envs/sabsim_dev
MPIRUN="$DEV/bin/mpirun"
PY="$VENV/bin/python"
HERE=/mnt/pixstor/data/rulisp/ucx_fabric_test
export LD_LIBRARY_PATH="$DEV/lib:${LD_LIBRARY_PATH:-}"

echo "nodelist: $SLURM_JOB_NODELIST   ntasks: $SLURM_NTASKS"
echo "SLURM_MEM_PER_NODE=${SLURM_MEM_PER_NODE:-unset}  "\
     "SLURM_MEM_PER_CPU=${SLURM_MEM_PER_CPU:-unset}  "\
     "SLURM_MEM_PER_GPU=${SLURM_MEM_PER_GPU:-unset}"

# THE FIX: drop the mutually-exclusive mem vars so the nested srun the
# launcher uses does not abort. (Harmless if some are already unset.)
unset SLURM_MEM_PER_NODE SLURM_MEM_PER_CPU SLURM_MEM_PER_GPU
echo "-> cleared SLURM_MEM_PER_* ; retrying launches"

echo
echo "########### M1b: srun --mpi=pmix (fabric via UCX) ###########"
UCX_LOG_LEVEL=info srun --mpi=pmix -n "$SLURM_NTASKS" \
    "$PY" "$HERE/fabric_test.py"
echo "=== M1b exit: $? ==="

echo
echo "########### M2b: mpirun (srun plm), force UCX ###########"
UCX_LOG_LEVEL=info "$MPIRUN" -np "$SLURM_NTASKS" --map-by ppr:1:node \
    --mca pml ucx "$PY" "$HERE/fabric_test.py"
echo "=== M2b exit: $? ==="
