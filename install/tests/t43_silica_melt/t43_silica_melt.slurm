#!/bin/bash
# T-43: does alpha quartz MELT under the recipe, and at what settings?
# One melt-quench variant per array task (see VARIANTS in the probe),
# each run through the real `melt_quench_script` with the new
# melt-check dump, then judged three ways: the diffusion ratio
# `verify_melt` uses, the final frame's shift from its lattice sites,
# and the §3.5 separation of the quenched glass from the warm
# catalogue job 16873844 described. Answers LEDGER T-42's open
# question with numbers instead of a guessed temperature.
#SBATCH --job-name=t43-melt
#SBATCH --partition=gpu,requeue
#SBATCH --account=general
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:H100:1
#SBATCH --mem=48G
#SBATCH --time=03:00:00
#SBATCH --array=0-5
#SBATCH --output=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim/install/tests/t43_silica_melt/t43-%A_%a.out
#SBATCH --error=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim/install/tests/t43_silica_melt/t43-%A_%a.err
set -uo pipefail
REPO=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim
SHARE=/cluster/VAST/rulisp-lab/cpg
export SABSIM_SCRATCH="$HOME/data/scratch/sabsim"
export SABSIM_SHARE="$SHARE"
export SABSIM_CASCADE_ENGINE_PREFIX="$SHARE/programs/deepmd-kit-3.2.0b0-cuda129"
export SABSIM_T43_REPO="$REPO"
export SABSIM_T43_WORK="$SABSIM_SCRATCH/tests/t43_silica_melt/${SLURM_ARRAY_JOB_ID}"
source "$SHARE/virtual_envs/sabsim/bin/activate"
cd "$REPO"
echo "=== $(date) node $(hostname) commit $(git rev-parse --short HEAD) task $SLURM_ARRAY_TASK_ID ==="
nvidia-smi -L || true
unset SLURM_MEM_PER_NODE SLURM_MEM_PER_CPU SLURM_MEM_PER_GPU
srun --mpi=pmix -n 1 python install/tests/t43_silica_melt/t43_melt_probe.py "$SLURM_ARRAY_TASK_ID"
rc=$?
echo "=== probe exit $rc ==="
exit $rc
