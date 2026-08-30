#!/bin/bash
# T-42: the first SILICA environment library, built INSIDE the prep
# folder of a project under the 2026-08-30 folder convention:
# `sabsim bootstrap generate recipe.toml --skip-collection2` run with
# CWD = jobs/si_sio2/prep_surf2_sio2/, so the library lands there as
# environment_library.{toml,npz} (no shared repository). Same settings
# as T-38 (cutoff 4.2 A, 300 K warm runs) on alpha quartz. Judged from
# the library sidecar: self-check fractions and thermal scatter.
#SBATCH --job-name=t42-sio2-lib
#SBATCH --partition=gpu,requeue
#SBATCH --account=general
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:H100:1
#SBATCH --mem=48G
#SBATCH --time=03:00:00
#SBATCH --output=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim/jobs/si_sio2/prep_surf2_sio2/t42-%j.out
#SBATCH --error=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim/jobs/si_sio2/prep_surf2_sio2/t42-%j.err
set -uo pipefail
REPO=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim
SHARE=/cluster/VAST/rulisp-lab/cpg
export SABSIM_SCRATCH="$HOME/data/scratch/sabsim"
export SABSIM_SHARE="$SHARE"
export SABSIM_CASCADE_ENGINE_PREFIX="$SHARE/programs/deepmd-kit-3.2.0b0-cuda129"
source "$SHARE/virtual_envs/sabsim/bin/activate"
cd "$REPO/jobs/si_sio2/prep_surf2_sio2"
echo "=== $(date) node $(hostname) commit $(git -C $REPO rev-parse --short HEAD) ==="
nvidia-smi -L || true
unset SLURM_MEM_PER_NODE SLURM_MEM_PER_CPU SLURM_MEM_PER_GPU
srun --mpi=pmix -n 1 sabsim bootstrap generate recipe.toml --skip-collection2
rc=$?
echo "=== generate exit $rc ==="
echo "=== prep folder ==="
ls -l
echo "=== library sidecar ==="
grep -v "^#" environment_library.toml 2>/dev/null | head -60
[ $rc -eq 0 ] && [ -f environment_library.toml ] && echo "T42RESULT library written in prep_surf2_sio2"
exit $rc
