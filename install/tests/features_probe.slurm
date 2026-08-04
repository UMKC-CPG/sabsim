#!/bin/bash
# Feature-coverage probe for the two Stack-C engines: ask each installed
# binary what packages it actually contains, and check that every package
# SABSIM's emitted styles depend on is present.  Fills the open question
# "do all desired features survive the conda build?" with a runtime fact,
# not a reading of the CMake flags.  One serial rank per engine is enough
# (package registration is identical on every rank).
#SBATCH --job-name=sabsim-features
#SBATCH --partition=general
#SBATCH --account=general
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --time=00:10:00
#SBATCH --output=/home/rulisp/data/ucx_fabric_test/features-%j.out
#SBATCH --error=/home/rulisp/data/ucx_fabric_test/features-%j.err

# No `set -e`: probe BOTH engines so a fault in one cannot mask the other.

HERE=/mnt/pixstor/data/rulisp/ucx_fabric_test
DEV=/cluster/VAST/rulisp-lab/cpg/mamba/envs/sabsim_dev
VENV_PYTHON=/cluster/VAST/rulisp-lab/cpg/virtual_envs/sabsim_dev/bin/python
PROGRAMS=/cluster/VAST/rulisp-lab/cpg/programs/lammps
ENGINE_DEEPMD="$PROGRAMS/2024.08.29-deepmd-conda-ompi5.0.10"
ENGINE_CLASSICAL="$PROGRAMS/22Jul2025-conda-ompi5.0.10"

# Clear the mutually-exclusive memory exports before any nested launch
# (same launcher fix proven in jobs 15551533 / 15582291).
unset SLURM_MEM_PER_NODE SLURM_MEM_PER_CPU SLURM_MEM_PER_GPU

# Drop any inherited LAMMPS_PLUGIN_PATH so no deepmd plugin auto-loads
# from a stale env; SABSIM loads deepmd explicitly (ARCHITECTURE §4.4).
unset LAMMPS_PLUGIN_PATH

# Run one engine: select it like a module via env vars (it is NOT a Lmod
# module), then dump its installed-package set through the shared probe.
probe_engine () {   # $1 = engine prefix   $2 = human label
    local engine="$1"
    local label="$2"
    echo "########### $label ###########"
    echo "engine   : $engine"
    echo "python   : $VENV_PYTHON"
    echo "--- packages that liblammps links (mpi sanity) ---"
    ldd "$engine/lib64/liblammps.so" | grep -iE "libmpi|open-pal" | head -2
    PYTHONPATH="$engine/lib64/python:${PYTHONPATH:-}" \
    LD_LIBRARY_PATH="$engine/lib64:$DEV/lib:${LD_LIBRARY_PATH:-}" \
    LAMMPS_POTENTIALS="$engine/share/lammps/potentials" \
        srun --mpi=pmix -n 1 "$VENV_PYTHON" "$HERE/features_probe.py"
    echo "=== $label exit: $? ==="
    echo
}

probe_engine "$ENGINE_DEEPMD"    "DEEPMD ENGINE 2024.08.29"
probe_engine "$ENGINE_CLASSICAL" "CLASSICAL ENGINE 22Jul2025"
