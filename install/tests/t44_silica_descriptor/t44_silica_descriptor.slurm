#!/bin/bash
# T-44: which descriptor settings separate silica glass from warm quartz
# (see the probe's docstring). CPU only: sna/atom needs no GPU.
#SBATCH --job-name=t44-descr
#SBATCH --partition=general
#SBATCH --account=general
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=02:00:00
#SBATCH --output=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim/install/tests/t44_silica_descriptor/t44-%j.out
#SBATCH --error=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim/install/tests/t44_silica_descriptor/t44-%j.err
set -uo pipefail
REPO=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim
SHARE=/cluster/VAST/rulisp-lab/cpg
export SABSIM_SCRATCH="$HOME/data/scratch/sabsim"
export SABSIM_SHARE="$SHARE"
export SABSIM_CASCADE_ENGINE_PREFIX="$SHARE/programs/deepmd-kit-3.2.0b0-cuda129"
export SABSIM_T44_WORK="$SABSIM_SCRATCH/tests/t44_silica_descriptor/${SLURM_JOB_ID}"
source "$SHARE/virtual_envs/sabsim/bin/activate"
cd "$REPO"
echo "=== $(date) node $(hostname) commit $(git rev-parse --short HEAD) ==="
unset SLURM_MEM_PER_NODE SLURM_MEM_PER_CPU SLURM_MEM_PER_GPU
srun --mpi=pmix -n 1 python install/tests/t44_silica_descriptor/t44_descriptor_sweep.py
rc=$?
echo "=== probe exit $rc ==="
exit $rc
