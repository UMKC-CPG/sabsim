#!/bin/bash
#SBATCH --job-name=sabsim-rename-validate
#SBATCH --account=general
#SBATCH --partition=gpu
#SBATCH --gres=gpu:L40S:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --mem=32G
#SBATCH --time=00:30:00
#SBATCH --output=%x-%j.out
#SBATCH --error=%x-%j.out
# =====================================================================
# T-RENAME validation: prove BOTH conda-derived engines load and run a
# real MD step under the RENAMED `sabsim` env (formerly sabsim_dev), so
# the old env can be removed safely.  Self-contained: it activates the
# sabsim env itself (the two-step conda+venv activation `ssabsim` does),
# rather than trusting an inherited environment.
# =====================================================================
set -uo pipefail

REPO=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim
MODEL=/cluster/VAST/rulisp-lab/cpg/share/train_deepmd_si/graph.pb

# The two-step activation (conda base, then the venv ON TOP) — the same
# layering `.sabsim/sabsimrc` performs, but named explicitly here.
source /cluster/software/common/mamba/1.4.2/etc/profile.d/conda.sh
conda activate sabsim
source /cluster/VAST/rulisp-lab/cpg/virtual_envs/sabsim/bin/activate

# The nested launcher aborts if these mutually-exclusive exports survive;
# LAMMPS_PLUGIN_PATH is cleared so deepmd is loaded only by the explicit
# `plugin load` in the probe, never auto-loaded at startup.
unset SLURM_MEM_PER_NODE SLURM_MEM_PER_CPU SLURM_MEM_PER_GPU
unset LAMMPS_PLUGIN_PATH

module use /cluster/VAST/rulisp-lab/cpg/modulefiles

echo "########## CLASSICAL engine (cpg_lammps_conda/22Jul2025) ##########"
module load cpg_lammps_conda/22Jul2025
srun --mpi=pmix -n 1 python "$REPO/install/tests/rename_validate.py" \
    classical
classical_status=$?
module unload cpg_lammps_conda/22Jul2025

echo "########## DEEPMD engine (cpg_lammps_conda/2024.08.29-deepmd) #####"
module load cpg_lammps_conda/2024.08.29-deepmd
export SABSIM_DEEPMD_MODEL="$MODEL"
srun --mpi=pmix -n 1 python "$REPO/install/tests/rename_validate.py" \
    deepmd
deepmd_status=$?

echo "=== classical exit: $classical_status ; deepmd exit: $deepmd_status ==="
if [ "$classical_status" -eq 0 ] && [ "$deepmd_status" -eq 0 ]; then
    echo "RENAME VALIDATE: PASS (both engines run under env sabsim)"
else
    echo "RENAME VALIDATE: FAIL"
fi
