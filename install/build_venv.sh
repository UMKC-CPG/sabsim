#!/usr/bin/env bash
# build_venv.sh — SABSIM venv layer over the conda base (DRAFT, ARCH §4.1)
# ==========================================================================
# Builds the venv HALF of the deployment stack on top of the `sabsim`
# conda env created from environment.yml. Run it AFTER:
#     CONDA_OVERRIDE_CUDA=12.9 mamba env create -f environment.yml
#
# The venv adds only what conda should NOT own: the version-pinned pure
# pip deps and the EDITABLE ALF + sabsim installs. MPI is NOT here — mpi4py
# comes from the conda base (it matches the conda OpenMPI 5.0.10 the whole
# stack runs on), so this script needs no site MPI module and no mpi4py
# source build. LAMMPS is also NOT here — it is a separate source build
# against conda OpenMPI 5.0.10 (dev/TODO.md).
#
# Builds `virtual_envs/sabsim`, the production venv, over the `sabsim`
# conda env. (This stack was first built under the transitional name
# `sabsim_dev`, then renamed to `sabsim` once validated, 2026-08-05.)
# ==========================================================================
set -euo pipefail

# --- 0. Layout — EDIT these for your machine --------------------------
CONDA_ENV="sabsim"
VENV="/cluster/VAST/rulisp-lab/cpg/virtual_envs/sabsim"
# The conda env's interpreter, BY FULL PATH — used to create the venv.
# Using the path (not `conda activate`) avoids needing the conda shell
# function, which a non-interactive `bash build_venv.sh` does not have.
CONDA_PY="/cluster/VAST/rulisp-lab/cpg/mamba/envs/${CONDA_ENV}/bin/python"
SABSIM_CLONE="$HOME/CPG/cpg-repo/sabsim"          # this repo (editable)
ALF_CLONE="/cluster/VAST/rulisp-lab/cpg/clones/ALF"   # ALF clone (editable)

# Versions pinned from the working env's recipe seed (2026-07-31).
ASE_VERSION="3.29.0"
PYMATGEN_VERSION="2026.5.4"
PARSL_VERSION="2026.6.29"
PYTEST_VERSION="9.1.1"          # the test suite's own runner (dev dep)

# Versions pinned to match Imago's own venv (2026-09-29), so an Imago
#   script behaves the same whether it runs from there or from here.
OPENPYXL_VERSION="3.1.5"        # spreadsheet reader for plotgraph.py
MPLCURSORS_VERSION="0.7.1"      # hover labels on plotgraph.py's plots
VEDO_VERSION="2026.6.1"         # the 3-D scene library of viewCell.py
VTK_VERSION="9.6.1"             # the rendering engine beneath vedo
PYPDF_VERSION="6.14.2"          # PDF reading, kept for Imago parity

# --- 1. Create the venv over the conda base ---------------------------
# --system-site-packages so the venv SEES the conda deepmd/torch/tf/numpy
#   AND mpi4py stack, while its OWN bin/python wins for editable sabsim.
"$CONDA_PY" -m venv --system-site-packages "$VENV"
source "$VENV/bin/activate"
python -m pip install --upgrade pip

# Sanity: the conda base must already provide mpi4py (linked to conda
#   OpenMPI 5.0.10). If this is missing, environment.yml was not applied.
python -c "import mpi4py; print('mpi4py from conda:', mpi4py.__file__)"

# --- 2. Pinned scientific + orchestration deps ------------------------
# pytest is included so a fresh checkout can run the test suite (the
#   project's definition-of-done leans on it, ARCHITECTURE §5.1) without a
#   second manual install.
python -m pip install \
    "ase==${ASE_VERSION}" \
    "pymatgen==${PYMATGEN_VERSION}" \
    "parsl==${PARSL_VERSION}" \
    "pytest==${PYTEST_VERSION}"

# --- 2b. Packages that let Imago's scripts run in this venv -----------
# Imago's Python scripts start with `#!/usr/bin/env python3`, so once
#   Imago's rc file is sourced on top of this environment they run on
#   THIS interpreter. Nearly everything they import is already here;
#   the packages below are the ones that were missing. They are what
#   lets a student work on both codes from one shell without sourcing
#   Imago's own venv, which would take `python` away from sabsim.
# PySide6 is deliberately NOT in this list: the conda base already
#   provides it (with its matching Qt), and a pip copy in the venv
#   would shadow that one with a different Qt version.
python -m pip install \
    "openpyxl==${OPENPYXL_VERSION}" \
    "mplcursors==${MPLCURSORS_VERSION}" \
    "vedo==${VEDO_VERSION}" \
    "vtk==${VTK_VERSION}" \
    "pypdf==${PYPDF_VERSION}"

# --- 3. Editable installs: ALF first, then SABSIM ---------------------
# ALF is the active-learning driver; SABSIM imports it. --no-deps on
#   sabsim so pip never re-resolves the hand-pinned stack (§4.1).
python -m pip install -e "$ALF_CLONE"
python -m pip install -e "$SABSIM_CLONE" --no-deps

# --- 4. NO lammps here --------------------------------------------------
# LAMMPS is a source build against conda OpenMPI 5.0.10 (el8-native),
#   done separately (dev/TODO.md). A conda/pip lammps re-creates the
#   RPATH-shadow bug (environment.yml principle 1). Deliberately omitted.

echo
echo "venv layer built: $VENV"
echo "NEXT: build LAMMPS against conda OpenMPI 5.0.10, then validate with"
echo "      the .sabsim/sabsimrc (activate sabsim + this venv) and a run"
echo "      launched via 'srun --mpi=pmix' after 'unset SLURM_MEM_PER_*'."
