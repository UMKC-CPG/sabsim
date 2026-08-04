#!/bin/bash
# STACK C probe: our conda-built deepmd engine (OpenMPI 5.0.10) driven
# in-process under the sabsim_dev venv Python with the mpi4py
# comm-sharing model SABSIM's code uses.  Fills matrix cells E1+E2+E4.
# Symmetric counterpart to site_engine_probe.slurm (job 15580445).
#SBATCH --job-name=sabsim-conda-engine
#SBATCH --partition=general
#SBATCH --account=general
#SBATCH --nodes=2
#SBATCH --ntasks-per-node=1
#SBATCH --time=00:15:00
#SBATCH --output=/home/rulisp/data/ucx_fabric_test/conda_engine-%j.out
#SBATCH --error=/home/rulisp/data/ucx_fabric_test/conda_engine-%j.err

# No `set -e`: attempt both launchers so one bad path cannot mask the
# engine's real behaviour.

HERE=/mnt/pixstor/data/rulisp/ucx_fabric_test
DEV=/cluster/VAST/rulisp-lab/cpg/mamba/envs/sabsim_dev
ENGINE=/cluster/VAST/rulisp-lab/cpg/programs/lammps/2024.08.29-deepmd-conda-ompi5.0.10
VENV_PYTHON=/cluster/VAST/rulisp-lab/cpg/virtual_envs/sabsim_dev/bin/python

# Select the conda deepmd engine like a module, but via env vars (it is
# NOT a Lmod module): its ctypes wrapper on PYTHONPATH, its liblammps +
# the conda libs (libmpi 5.0.10) on LD_LIBRARY_PATH, its bundled
# potentials, and the conda deepmd plugin.  No LD_PRELOAD: the conda
# libstdc++ this env ships already provides the CXXABI the backend needs.
export PYTHONPATH="$ENGINE/lib64/python:${PYTHONPATH:-}"
export LD_LIBRARY_PATH="$ENGINE/lib64:$DEV/lib:${LD_LIBRARY_PATH:-}"
export LAMMPS_POTENTIALS="$ENGINE/share/lammps/potentials"
export DEEPMD_LMP_PLUGIN="$DEV/lib/libdeepmd_lmp.so"

# Same launcher fix proven for the conda run (job 15551533): clear the
# mutually-exclusive memory exports before any nested launch.
unset SLURM_MEM_PER_NODE SLURM_MEM_PER_CPU SLURM_MEM_PER_GPU

# Drop any inherited LAMMPS_PLUGIN_PATH.  The deepmd-kit conda hook
# (etc/conda/activate.d/deepmd-kit_activate.sh) exports it to
# $CONDA_PREFIX/lib/deepmd_lmp, so a submitting shell with ANY deepmd env
# active would make LAMMPS auto-load that plugin at startup.  SABSIM's
# design loads deepmd EXPLICITLY instead (prepare.py:122, ARCHITECTURE
# §4.4: the LAMMPS input issues `plugin load $DEEPMD_LMP_PLUGIN`), so the
# silent auto-load is unwanted and non-reproducible.  Clear it here.
unset LAMMPS_PLUGIN_PATH

# --- Self-logging (ledger rule #2): the log alone must reconstruct the
#     environment that ran. ---
echo "nodelist : $SLURM_JOB_NODELIST   ntasks: $SLURM_NTASKS"
echo "engine   : $ENGINE"
echo "python   : $VENV_PYTHON"
echo "mpirun   : $DEV/bin/mpirun"
echo "PYTHONPATH        : $PYTHONPATH"
echo "DEEPMD_LMP_PLUGIN : $DEEPMD_LMP_PLUGIN"
echo "--- libmpi that liblammps links ---"
ldd "$ENGINE/lib64/liblammps.so" | grep -iE "libmpi|open-pal"
echo

echo "########### C1: srun --mpi=pmix (comm-share, 2 nodes) ###########"
srun --mpi=pmix -n "$SLURM_NTASKS" -N 2 "$VENV_PYTHON" "$HERE/conda_engine_probe.py"
echo "=== C1 srun exit: $? ==="

echo
echo "########### C2: mpirun (comm-share, 2 nodes) ###########"
"$DEV/bin/mpirun" -np "$SLURM_NTASKS" "$VENV_PYTHON" "$HERE/conda_engine_probe.py"
echo "=== C2 mpirun exit: $? ==="
