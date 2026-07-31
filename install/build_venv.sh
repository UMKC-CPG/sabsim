#!/usr/bin/env bash
# build_venv.sh — SABSIM venv layer over the conda base (DRAFT, ARCH §4.1)
# ==========================================================================
# Builds the venv HALF of the deployment stack on top of the `sabsim_dev`
# conda env created from environment.yml. Run it AFTER:
#     mamba env create -f environment.yml     # creates conda `sabsim_dev`
#
# THE LOAD-BEARING STEP is (3): mpi4py is pip-COMPILED here against the
# SITE OpenMPI 4.1.5 (loaded as a module), NOT taken from conda, so the
# in-process `import lammps` (site) + `import mpi4py` share ONE MPI. This
# is the single most important thing this script does; everything else is
# ordinary pip.
#
# DEV naming: this builds `virtual_envs/sabsim_dev` alongside the
# production `virtual_envs/sabsim`. Nothing here touches the old env.
# ==========================================================================
set -euo pipefail

# --- 0. Layout — EDIT these for your machine --------------------------
CONDA_ENV="sabsim_dev"
VENV="/cluster/VAST/rulisp-lab/cpg/virtual_envs/sabsim_dev"
SABSIM_CLONE="$HOME/CPG/cpg-repo/sabsim"          # this repo (editable)
ALF_CLONE="$HOME/CPG/cpg-repo/ALF"                # the ALF clone (editable)
SITE_MODULEFILES="/cluster/VAST/rulisp-lab/cpg/modulefiles"

# Versions pinned from the working env's recipe seed (2026-07-31). Bump
#   deliberately; ase/pymatgen track the study inputs, parsl tracks ALF.
MPI4PY_VERSION="4.1.2"
ASE_VERSION="3.29.0"
PYMATGEN_VERSION="2026.5.4"
PARSL_VERSION="2026.6.29"

# --- 1. Site toolchain + MPI — the mpi4py build target ----------------
# Load the SITE gcc 12.3.0 and OpenMPI 4.1.5 (what the cpg_lammps modules
#   are built against). `mpicc` from THIS OpenMPI is what mpi4py compiles
#   against below — the whole point of the exercise.
module use "$SITE_MODULEFILES"
module load gcc/12.3.0
module load openmpi/4.1.5_gcc_12.3.0
echo "site mpicc: $(command -v mpicc)"        # sanity: must be site 4.1.5

# --- 2. Create the venv over the conda base ---------------------------
# --system-site-packages so the venv SEES the conda deepmd/torch/tf/numpy
#   stack, while its OWN bin/python wins for the editable sabsim + pins.
conda activate "$CONDA_ENV"
python -m venv --system-site-packages "$VENV"
source "$VENV/bin/activate"
python -m pip install --upgrade pip

# Guard principle 2: the conda base must NOT carry an mpi4py (it would
#   shadow ours from system-site-packages). If this prints a path, stop
#   and remove it from the conda env before continuing.
python - <<'PY'
import importlib.util as u, sys
spec = u.find_spec("mpi4py")
print("PRE-CHECK mpi4py already visible at:", spec.origin if spec else "none")
PY

# --- 3. mpi4py — COMPILED against the site OpenMPI 4.1.5 (THE crux) ----
# Site 4.1.5 is CONFIRMED sufficient for LAMMPS + mpi4py (both use it, and
#   it drives the interconnect); the only open MPI question is deepmd's
#   op_pt library, settled by a bond run (see environment.yml).
# --no-binary forces a source build so it links the site `mpicc` loaded
#   above, not a wheel carrying some other MPI. Then VERIFY the linked
#   library really is Open MPI 4.1.5.
MPICC="$(command -v mpicc)" \
    python -m pip install --no-binary=mpi4py "mpi4py==${MPI4PY_VERSION}"
python - <<'PY'
from mpi4py import MPI
print("mpi4py links:", MPI.Get_library_version().strip().splitlines()[0])
PY

# --- 4. Pinned scientific + orchestration deps ------------------------
python -m pip install \
    "ase==${ASE_VERSION}" \
    "pymatgen==${PYMATGEN_VERSION}" \
    "parsl==${PARSL_VERSION}"

# --- 5. Editable installs: ALF first, then SABSIM ---------------------
# ALF is the active-learning driver; SABSIM imports it. --no-deps on
#   sabsim so pip never re-resolves the hand-pinned stack (§4.1).
python -m pip install -e "$ALF_CLONE"
python -m pip install -e "$SABSIM_CLONE" --no-deps

# --- 6. NO lammps here --------------------------------------------------
# The site `cpg_lammps` module supplies LAMMPS + its python wrapper at run
#   time. Installing a conda/pip lammps here re-creates the RPATH-shadow
#   bug (environment.yml principle 1). Deliberately omitted.

echo
echo "venv layer built: $VENV"
echo "NEXT: validate — engine probe, then activate, then a bond smoke,"
echo "      using a sabsimrc.dev that activates ${CONDA_ENV} + this venv."
