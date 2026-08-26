#!/bin/bash
# TIER-1 ENERGY SCAN under DPA-3.1-3M (the model that PASSED Tier-0).
# One array task per energy, 1 impact, 1 seed -- many energies to find
# the bracket; seeds come later on the chosen point only.
#
# Runs on A100 via the PyTorch .pth model: .pth is NOT architecture-
# locked (unlike the AOT .pt2), so it takes ANY GPU rather than the
# three V100s the .pt2 needs. Heterogeneous GPUs across tasks are
# acceptable here: single-seed depth scatter is several angstrom
# (LEDGER T-21 / the 2026-07-21 sweep), far above any TF32-level
# numerical difference. Each task logs the GPU it landed on.
#SBATCH --job-name=tier1-escan
#SBATCH --partition=gpu,requeue
#SBATCH --account=general
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=8
#SBATCH --gres=gpu:1
#SBATCH --exclude=g003
#SBATCH --mem=48G
#SBATCH --time=04:00:00
# Twelve energies (tasks 0-11) plus the zero-impact NULL CONTROL
# (task 12), which measures the vacated-site floor the pre-relax
# alone produces so the bombarded points are read against it.
#SBATCH --array=0-12
# Log paths are relative to the SUBMISSION directory (the repo
# root); mkdir -p the directory before submitting.
#SBATCH --output=jobs/bulk_si/scan_logs/escan-%A_%a.out
#SBATCH --error=jobs/bulk_si/scan_logs/escan-%A_%a.err
set -uo pipefail

REPO=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim
SHARE=/cluster/VAST/rulisp-lab/cpg
FIX="$SHARE/share/models/dpa_gpu_bench/v320fix"

echo "=== task ${SLURM_ARRAY_TASK_ID} on $(hostname) ==="
nvidia-smi --query-gpu=name --format=csv,noheader || true

module use "$SHARE/modulefiles"
module load cpg_lammps_conda/2024.08.29-deepmd
source "$SHARE/virtual_envs/sabsim/bin/activate"
export PYTHONPATH="$REPO/src"

# Universal cascade, out-of-process in the deepmd bundle. The MODEL is
# named by the study file's [potential] block (dev/templates/study_spec
# .toml), not here. It is
# DPA-3.1-3M as a .pth: no AOT .pt2 exists for it (the network.py `u0`
# bug, diagnosed in dev/notes/mlip-cascade-integration.md) but lmp loads
# .pth directly with energy conserved.
export SABSIM_CASCADE_ENGINE_PREFIX="$SHARE/programs/deepmd-kit-3.2.0b0-cuda129"
unset SLURM_MEM_PER_NODE SLURM_MEM_PER_CPU SLURM_MEM_PER_GPU

cd "$REPO"
srun --mpi=pmix -n 1 \
     python install/tests/t22_energy_scan/run_energy_scan.py \
     "${SLURM_ARRAY_TASK_ID}"
echo "=== task ${SLURM_ARRAY_TASK_ID} exit $? ==="
