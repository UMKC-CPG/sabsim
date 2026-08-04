-- ---------------------------------------------------------------------
-- LAMMPS 22 Jul 2025 (classical), the conda-derived engine (ARCH §4.4).
--
-- The sibling of the site cpg_lammps/22Jul2025 module, but built by
--   install/build_lammps.sh from source and linked against this project's
--   CONDA OpenMPI 5.0.10 (env sabsim_dev), NOT the site toolchain.  It
--   exists because sabsim drives LAMMPS IN-PROCESS and shares one
--   MPI_COMM_WORLD between mpi4py and liblammps (§4.1), so the engine's
--   libmpi MUST be the same conda 5.0.10 the Python already forces.  The
--   site engine (OpenMPI 4.1.5) links the wrong libmpi and cannot share
--   that communicator; it stays a documented fallback (§4.4).
--
-- Assumes the sabsim_dev conda+venv environment is ACTIVE (a job inherits
--   it from `ssabsim_dev` / .sabsim/sabsimrc_dev, SLURM --export=ALL): the
--   binary's RPATH resolves the conda libmpi/libstdc++ from that env, and
--   the launcher (srun --mpi=pmix, or mpirun) comes from it too.  So this
--   module does NOT load any site openmpi -- it only puts the engine's
--   ctypes wrapper and potentials on the path.  Built PKG_PYTHON=OFF, so
--   the one pure-ctypes wrapper serves any Python (LammpsEngine imports it
--   unchanged); glibc-safe (no symbol above GLIBC_2.14), so it starts on
--   the 2.28 compute nodes.  Feature-verified: 25 packages, only ML-HDNNP
--   and VORONOI dropped vs the site build, neither used by the pipeline
--   (job 15683172).
-- ---------------------------------------------------------------------

help([[
LAMMPS 22 Jul 2025 (classical), conda-derived: source-built, conda
OpenMPI 5.0.10 (env sabsim_dev).  The SW/ZBL cascade engine for the
`activate` job.  Load it from a job that has already activated sabsim_dev.

Driving LAMMPS from Python (the sabsim path):
   from lammps import lammps
   sim = lammps(comm=MPI.COMM_WORLD)     # shared-communicator, in-process

Bundled potentials are pointed to by $LAMMPS_POTENTIALS.
Enabled packages: COMPRESS DIFFRACTION EXTRA-COMMAND EXTRA-COMPUTE
EXTRA-DUMP EXTRA-FIX EXTRA-MOLECULE EXTRA-PAIR KSPACE MANYBODY MC MEAM
MISC ML-IAP ML-SNAP MOLECULE OPENMP OPT PHONON PLUGIN QEQ REACTION
REAXFF REPLICA RIGID
]])

whatis("Name        : cpg_lammps_conda")
whatis("Version     : 22Jul2025 (conda OpenMPI 5.0.10)")
whatis("Category    : molecular dynamics")
whatis("Description : LAMMPS classical engine, source-built + conda-linked")

-- The versioned install directory.  Point this at a new prefix to
--   publish a rebuild; nothing else in this file needs to change.
local prefix = "/cluster/VAST/rulisp-lab/cpg/programs/lammps/"
               .. "22Jul2025-conda-ompi5.0.10"

-- No site openmpi load: conda 5.0.10 comes from the active sabsim_dev env
--   (libmpi via the binary's RPATH; mpirun/srun from the env / SLURM).

prepend_path("PATH", pathJoin(prefix, "bin"))

-- The Python wrapper reaches the library through a plain
--   dlopen("liblammps.so"), which searches LD_LIBRARY_PATH (the RPATH
--   compiled into the executable does not help a dlopen from python).
prepend_path("LD_LIBRARY_PATH", pathJoin(prefix, "lib64"))

-- One copy of the pure-ctypes wrapper, beside the library.
prepend_path("PYTHONPATH", pathJoin(prefix, "lib64/python"))

-- Where LAMMPS looks for the bundled potential files.
setenv("LAMMPS_POTENTIALS", pathJoin(prefix, "share/lammps/potentials"))

prepend_path("CPATH", pathJoin(prefix, "include"))
prepend_path("PKG_CONFIG_PATH", pathJoin(prefix, "lib64/pkgconfig"))

family("lammps")
