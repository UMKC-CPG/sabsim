#!/bin/bash
# Decisive probe: does Imago's SITE-toolchain LAMMPS engine (OpenMPI
# 4.1.5) load and run multi-node IN-PROCESS under the sabsim venv
# Python -- deepmd included -- now that no competing conda liblammps
# exists?  A PASS means the conda-OpenMPI-5.0.10 rebuild was NOT required
# and SABSIM can adopt the proven site module (resolves ARCHITECTURE
# §4.1 vs §4.4).
#SBATCH --job-name=sabsim-site-engine
#SBATCH --partition=general
#SBATCH --account=general
#SBATCH --nodes=2
#SBATCH --ntasks-per-node=1
#SBATCH --time=00:15:00
#SBATCH --output=/home/rulisp/data/ucx_fabric_test/site_engine-%j.out
#SBATCH --error=/home/rulisp/data/ucx_fabric_test/site_engine-%j.err

# No `set -e`: attempt every launcher so one bad path cannot mask the
# engine's real behaviour.

HERE=/mnt/pixstor/data/rulisp/ucx_fabric_test
VENV_PYTHON=/cluster/VAST/rulisp-lab/cpg/virtual_envs/sabsim/bin/python

# Bring Lmod into this non-interactive shell, then load Imago's engine
# module.  cpg_lammps/2024.08.29-deepmd auto-loads openmpi/4.1.5, and
# sets PYTHONPATH (site wrapper), LD_LIBRARY_PATH (site liblammps),
# LAMMPS_POTENTIALS, LD_PRELOAD (deepmd's libstdc++), and
# DEEPMD_LMP_PLUGIN -- exactly the Imago-validated composition.
source /etc/profile.d/modules.sh
module use /cluster/VAST/rulisp-lab/cpg/modulefiles
module load cpg_lammps/2024.08.29-deepmd

# Same launcher fix proven for the conda run (job 15551533): the
# allocation exports these mutually-exclusive, which aborts the nested
# daemon/step launch.  Clear them before any mpirun/srun.
unset SLURM_MEM_PER_NODE SLURM_MEM_PER_CPU SLURM_MEM_PER_GPU

echo "nodelist : $SLURM_JOB_NODELIST   ntasks: $SLURM_NTASKS"
echo "python   : $VENV_PYTHON"
echo "which mpirun : $(command -v mpirun)"
echo "PYTHONPATH   : $PYTHONPATH"
echo "DEEPMD_LMP_PLUGIN : ${DEEPMD_LMP_PLUGIN:-unset}"
echo

echo "########### A1: site mpirun (modulefile's blessed launcher) ###########"
mpirun -np "$SLURM_NTASKS" "$VENV_PYTHON" "$HERE/site_engine_probe.py"
echo "=== A1 mpirun exit: $? ==="

echo
echo "########### A2: srun --mpi=pmix (matches the conda-run launcher) ###########"
srun --mpi=pmix -n "$SLURM_NTASKS" -N 2 "$VENV_PYTHON" "$HERE/site_engine_probe.py"
echo "=== A2 srun exit: $? ==="
