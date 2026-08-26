#!/bin/bash
# TIER-1 ENERGY SCAN, MOVIE MODE: three of the scanned points re-run
# with the cascade recording frames, so the bombardment can be WATCHED.
# This produces no new measurement -- job 16795220 already measured
# these points (LEDGER T-22) and its evidence is left untouched.
#
# The three points are chosen to show the bracket rather than to sample
# it evenly:
#   task 2  ->  40 eV  damage barely above the relaxation floor
#   task 7  -> 100 eV  the operating point: reach 6.89 A, the plateau
#   task 11 -> 200 eV  the deep outlier, where one ion found a channel
# The indices are positions in SCAN_ENERGIES_EV, so they stay correct
# only as long as that list does; run_energy_scan.py owns the list.
#
# Everything else -- model, cell, seed, durations -- is IDENTICAL to
# energy_scan.slurm, so a frame from this run and the measured number
# from that one describe the same physics. Only the recording differs.
#SBATCH --job-name=tier1-escan-movie
#SBATCH --partition=gpu,requeue
#SBATCH --account=general
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=8
#SBATCH --gres=gpu:1
#SBATCH --exclude=g003
#SBATCH --mem=48G
#SBATCH --time=04:00:00
#SBATCH --array=2,7,11
# Logs go to movie_logs/, NOT scan_logs/. The analyser globs
# `escan-*.out` under scan_logs/ and keeps only the newest job's
# SCANRESULT lines, so letting a three-point movie run land there would
# silently replace the thirteen-point measured table with three rows.
#SBATCH --output=jobs/bulk_si/movie_logs/escan-%A_%a.out
#SBATCH --error=jobs/bulk_si/movie_logs/escan-%A_%a.err
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

# Universal cascade, out-of-process in the deepmd bundle, DPA-3.1-3M as
# a .pth (no AOT .pt2 exists for it -- the network.py `u0` bug).
export SABSIM_CASCADE_ENGINE_PREFIX="$SHARE/programs/deepmd-kit-3.2.0b0-cuda129"
export SABSIM_CASCADE_MLIP_MODEL="$FIX/dpa3.pth"
export SABSIM_ALLOW_UNVALIDATED_POTENTIAL=1
unset SLURM_MEM_PER_NODE SLURM_MEM_PER_CPU SLURM_MEM_PER_GPU

cd "$REPO"
srun --mpi=pmix -n 1 \
     python install/tests/t22_energy_scan/run_energy_scan.py \
     "${SLURM_ARRAY_TASK_ID}" --movie
echo "=== task ${SLURM_ARRAY_TASK_ID} exit $? ==="
