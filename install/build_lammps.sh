#!/bin/bash
#SBATCH --job-name=sabsim-lammps-conda5
#SBATCH --account=general
#SBATCH --partition=general
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=128G
#SBATCH --time=06:00:00
#SBATCH --output=/home/rulisp/programs/lammps/build-jobs/%x-%j.out
#SBATCH --error=/home/rulisp/programs/lammps/build-jobs/%x-%j.out
# ==========================================================================
# Build LAMMPS from source against THIS env's conda OpenMPI 5.0.10, for the
# TWO engines the pipeline needs:
#   * classical 22 Jul 2025 (activate/analyze: SW + ZBL)
#   * deepmd    29 Aug 2024 (bond: ABI-matched to the conda deepmd plugin)
#
# Adapted from the proven site recipe (build-jobs/build-lammps.sbatch) with
# ONE deliberate reversal: that recipe SCRUBBED conda and used the site
# toolchain because "conda's OpenMPI has no verbs/InfiniBand" — which the
# fabric test (job 15551674) DISPROVED (conda 5.0.10 + UCX = ~12 GB/s). So
# here we EMBRACE the conda toolchain: conda OpenMPI 5.0.10 (MPI-consistent
# with mpi4py and the forced in-process libmpi) and conda gcc / libstdc++
# 16 (matches the deepmd plugin's CXXABI — so NO LD_PRELOAD needed).
#
# Each engine installs to a versioned PREFIX with PKG_PYTHON=OFF and a pure
# ctypes wrapper — Python-agnostic, selected per job by PYTHONPATH +
# LD_LIBRARY_PATH (like the cpg_lammps modules), NOT put into the venv (one
# venv holds only one `lammps`). Run: `sbatch install/build_lammps.sh`.
# Requires the build toolchain from environment.yml (cxx-compiler, cmake,
# make, fftw) — `mamba env update -f environment.yml` first if needed.
# ==========================================================================
set -euo pipefail

# --- EDIT for your machine --------------------------------------------
CONDA_HOOK=/cluster/software/common/mamba/1.4.2/etc/profile.d/conda.sh
CONDA_ENV=sabsim_dev
LROOT=/cluster/pixstor/home/rulisp/programs/lammps        # sources + builds
PREFIX_ROOT=/cluster/VAST/rulisp-lab/cpg/programs/lammps   # install prefixes

# --- Activate the conda toolchain -------------------------------------
# Sourcing the hook FIRST defines the `conda` function a batch shell lacks;
# activating sabsim_dev then puts conda gcc/g++, mpicc/mpicxx, cmake and
# FFTW on PATH and sets the compiler sysroot/flags.
set +u
source "$CONDA_HOOK"
conda activate "$CONDA_ENV"
set -u

MPICC="$CONDA_PREFIX/bin/mpicc"
MPICXX="$CONDA_PREFIX/bin/mpicxx"
# RPATH baked into the binaries so they find conda libmpi / libstdc++ /
# fftw regardless of which env is active at run time. $ORIGIN is written
# literally so the loader expands it relative to the binary at run time.
INSTALL_RPATH="\$ORIGIN;\$ORIGIN/../lib64;$CONDA_PREFIX/lib"

# --- Build one engine -------------------------------------------------
build_engine () {   # $1 = source subdir  $2 = prefix name  $3 = label
    local src="$LROOT/$1"
    local build="$LROOT/build-$2"
    local prefix="$PREFIX_ROOT/$2"

    echo "======================================================="
    echo "ENGINE      : $3"
    echo "source      : $src"
    echo "version.h   : $(grep -m1 LAMMPS_VERSION "$src/src/version.h")"
    echo "cc / cxx    : $MPICC | $MPICXX"
    echo "mpi         : $("$MPICXX" -show 2>&1 | head -1)"
    echo "cmake       : $(cmake --version | head -1)"
    echo "prefix      : $prefix"
    echo "======================================================="

    rm -rf "$build"; mkdir -p "$build"; cd "$build"

    # NOTE — packages TRIMMED from the proven site set. They MAY be needed
    #   later; restore by adding the dep to environment.yml AND re-enabling
    #   the flag here:
    #     PKG_ML-HDNNP + DOWNLOAD_N2P2   (HDNNP potentials; self-download)
    #     PKG_VORONOI  + DOWNLOAD_VORO   (Voronoi compute;  self-download)
    #     WITH_PNG  (needs libpng)       image dumps
    #     WITH_CURL (needs libcurl)      remote potential fetch
    #   The v1 pipeline (SW/ZBL + deepmd) needs none of these; they were cut
    #   only to isolate the first conda-toolchain build.
    cmake "$src/cmake" \
        -D CMAKE_BUILD_TYPE=Release \
        -D CMAKE_INSTALL_PREFIX="$prefix" \
        -D CMAKE_C_COMPILER="$MPICC" \
        -D CMAKE_CXX_COMPILER="$MPICXX" \
        -D BUILD_MPI=ON \
        -D BUILD_OMP=ON \
        -D BUILD_SHARED_LIBS=ON \
        -D CMAKE_INSTALL_RPATH="$INSTALL_RPATH" \
        -D CMAKE_INSTALL_RPATH_USE_LINK_PATH=ON \
        -D PKG_EXTRA-COMMAND=ON \
        -D PKG_EXTRA-COMPUTE=ON \
        -D PKG_EXTRA-DUMP=ON \
        -D PKG_EXTRA-FIX=ON \
        -D PKG_EXTRA-MOLECULE=ON \
        -D PKG_EXTRA-PAIR=ON \
        -D PKG_KSPACE=ON \
        -D PKG_MANYBODY=ON \
        -D PKG_MEAM=ON \
        -D PKG_ML-IAP=ON \
        -D PKG_ML-SNAP=ON \
        -D PKG_MOLECULE=ON \
        -D PKG_PHONON=ON \
        -D PKG_PLUGIN=ON \
        -D PKG_REACTION=ON \
        -D PKG_REAXFF=ON \
        -D PKG_RIGID=ON \
        -D PKG_MC=ON \
        -D PKG_QEQ=ON \
        -D PKG_OPENMP=ON \
        -D PKG_OPT=ON \
        -D PKG_REPLICA=ON \
        -D PKG_MISC=ON \
        -D PKG_DIFFRACTION=ON \
        -D PKG_COMPRESS=ON \
        -D PKG_PYTHON=OFF \
        -D FFT=FFTW3 \
        -D FFT_SINGLE=OFF \
        -D FFT_FFTW_THREADS=ON \
        -D FFTW3_INCLUDE_DIR="$CONDA_PREFIX/include" \
        -D FFTW3_LIBRARY="$CONDA_PREFIX/lib/libfftw3.so" \
        -D FFTW3_OMP_LIBRARY="$CONDA_PREFIX/lib/libfftw3_omp.so" \
        -D WITH_PNG=OFF \
        -D WITH_JPEG=OFF \
        -D WITH_FFMPEG=OFF \
        -D WITH_CURL=OFF \
        -D DOWNLOAD_POTENTIALS=ON

    make -j "${SLURM_CPUS_PER_TASK:-16}"
    make install

    # Python-agnostic ctypes wrapper into the prefix (env-neutral).
    mkdir -p "$prefix/lib64/python"
    cp -r "$src/python/lammps" "$prefix/lib64/python/"

    # --- Verify the properties this build exists for ------------------
    local lib="$prefix/lib64/liblammps.so.0"
    [ -e "$lib" ] || lib="$prefix/lib/liblammps.so.0"
    echo "--- VERIFY $3 ($lib) ---"
    echo "glibc floor (want <= 2.28):"
    readelf -V "$lib" 2>/dev/null | grep -oE 'GLIBC_[0-9.]+' \
        | sort -V | uniq | tail -1
    echo "libmpi linked (want conda 5.0.10 / libopen-pal.so.80):"
    ldd "$lib" 2>/dev/null | grep -iE 'libmpi|libopen-pal' | head -3
    echo "libpython linkage (want none):"
    readelf -d "$lib" 2>/dev/null | grep -i 'NEEDED.*python' \
        || echo "   none: Python-agnostic"
    if [ "$1" = "lammps-29Aug2024" ]; then
        echo "deepmd ABI symbol (want the NO-trailing-int bounds<int>):"
        nm -D --defined-only "$lib" 2>/dev/null \
            | grep '5utils6boundsIiE' | c++filt | head -2
    fi
    echo "DONE: $prefix"
}

# --- Build both engines -----------------------------------------------
build_engine lammps-22Jul2025 \
    22Jul2025-conda-ompi5.0.10          "classical 22Jul2025"
build_engine lammps-29Aug2024 \
    2024.08.29-deepmd-conda-ompi5.0.10  "deepmd 29Aug2024"

echo "======================================================="
echo "ALL LAMMPS BUILDS COMPLETE."
