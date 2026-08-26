#!/bin/bash
# T-25: the deepmd-kit 3.2 bundle as an IN-PROCESS SABSIM engine (option
# (a), 2026-08-26). Two srun launches: 1 rank, then 2 ranks, so the
# bundle's OpenMPI is exercised under pmix as the real bond job would use
# it. Judged from the physics printed by probe_inprocess_dp3.py.
#SBATCH --job-name=t25-inproc-dp3
#SBATCH --partition=gpu,requeue
#SBATCH --account=general
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=2
#SBATCH --gres=gpu:1
#SBATCH --mem=32G
#SBATCH --time=00:30:00
#SBATCH --output=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim/jobs/t25_inprocess_dp3/t25-%j.out
#SBATCH --error=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim/jobs/t25_inprocess_dp3/t25-%j.err
set -uo pipefail
export SABSIM_REPO=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim
SHARE=/cluster/VAST/rulisp-lab/cpg
export T25_WORK="$SABSIM_REPO/jobs/t25_inprocess_dp3/work"
export T25_MODEL="$SHARE/share/models/dpa_gpu_bench/v320fix/dpa3.pth"
mkdir -p "$T25_WORK"
echo "=== node / gpu ==="; nvidia-smi -L || true
# The in-process engine module FIRST (it prepends the bundle's bin for
# mpirun/lmp), THEN the dp3 venv, whose activate prepends its own bin so
# `python` is the venv interpreter that carries sabsim + pymatgen.
module use "$SHARE/modulefiles"
module load cpg_lammps_conda/deepmd-kit-3.2.0b0
source "$SHARE/virtual_envs/sabsim-dp3/bin/activate"
module list 2>&1 || true
echo "python=$(command -v python)"
unset SLURM_MEM_PER_NODE SLURM_MEM_PER_CPU SLURM_MEM_PER_GPU
python -c "import sabsim, lammps, torch; print('imports OK; torch cuda:', torch.cuda.is_available())" || exit 2
echo "=== 1 rank ==="
srun --mpi=pmix -n 1 python "$SABSIM_REPO/install/tests/t25_inprocess_dp3/probe_inprocess_dp3.py"
rc1=$?
echo "=== 2 ranks ==="
srun --mpi=pmix -n 2 python "$SABSIM_REPO/install/tests/t25_inprocess_dp3/probe_inprocess_dp3.py"
rc2=$?
echo "=== T-25 exit 1rank=$rc1 2ranks=$rc2 ==="
tail -20 "$T25_WORK/log.t25" 2>/dev/null || true
exit $(( rc1 + rc2 ))
