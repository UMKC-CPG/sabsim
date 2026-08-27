#!/bin/bash
# T-28: the bond stage (heal -> gate -> press -> settle -> pull) run
# IN-PROCESS under the universal DPA-3.1-3M model, in the sabsim-dp3
# environment (T-25), on the clean 50 eV demo activation — the same
# assembled pair the graph.pb bond (job 16825513) collapsed at the heal.
# Same code path as `sabsim run --bond`; only the environment and the
# study file's production_weights differ. Judged from the press dump.
#SBATCH --job-name=t28-bond-dpa3
#SBATCH --partition=gpu,requeue
#SBATCH --account=general
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:H100:1
#SBATCH --mem=32G
#SBATCH --time=12:00:00
#SBATCH --output=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim/jobs/demo_si_small_50ev_dpa3/t28-%j.out
#SBATCH --error=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim/jobs/demo_si_small_50ev_dpa3/t28-%j.err
set -uo pipefail
REPO=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim
SHARE=/cluster/VAST/rulisp-lab/cpg
export SABSIM_SCRATCH="$HOME/data/scratch/sabsim"
export SABSIM_SHARE="$SHARE"
# Module FIRST (bundle bin/lib + the plugin path), THEN the dp3 venv.
module use "$SHARE/modulefiles"
module load cpg_lammps_conda/deepmd-kit-3.2.0b0
source "$SHARE/virtual_envs/sabsim-dp3/bin/activate"
module list 2>&1 || true
echo "python=$(command -v python)"; nvidia-smi -L || true
cd "$REPO/jobs/demo_si_small_50ev_dpa3"
unset SLURM_MEM_PER_NODE SLURM_MEM_PER_CPU SLURM_MEM_PER_GPU
srun --mpi=pmix -n 1 python -m sabsim run sabsim.toml --bond --only si-si-reference --dump-visuals
echo "=== T-28 exit $? ==="
