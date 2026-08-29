#!/bin/bash
# T-37: library separation vs descriptor cutoff and warm temperature
# (see separation.py). Reuses T-36's Collection 1 frames.
#SBATCH --job-name=t37-lib-sep
#SBATCH --partition=gpu,requeue
#SBATCH --account=general
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:H100:1
#SBATCH --mem=24G
#SBATCH --time=02:00:00
#SBATCH --output=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim/jobs/bootstrap_si_lib/t37-%j.out
#SBATCH --error=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim/jobs/bootstrap_si_lib/t37-%j.err
set -uo pipefail
REPO=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim
SHARE=/cluster/VAST/rulisp-lab/cpg
export SABSIM_SCRATCH="$HOME/data/scratch/sabsim"
export SABSIM_SHARE="$SHARE"
export SABSIM_CASCADE_ENGINE_PREFIX="$SHARE/programs/deepmd-kit-3.2.0b0-cuda129"
source "$SHARE/virtual_envs/sabsim/bin/activate"
cd "$REPO/jobs/bootstrap_si_lib"
echo "=== $(date) node $(hostname) commit $(git -C $REPO rev-parse --short HEAD) ==="
unset SLURM_MEM_PER_NODE SLURM_MEM_PER_CPU SLURM_MEM_PER_GPU
C1="$SABSIM_SCRATCH/CPG/cpg-repo/sabsim/jobs/bootstrap_si_lib/bootstrap/si-lean-v0/collection1"
srun --mpi=pmix -n 1 python "$REPO/install/tests/t37_library_separation/separation.py" recipe.toml "$C1" "$C1/../t37_separation"
