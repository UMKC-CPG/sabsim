-- ---------------------------------------------------------------------
-- LAMMPS 29 Aug 2024, the conda-derived DeePMD-capable engine (ARCH
--   §4.4).  Identical recipe to cpg_lammps_conda/22Jul2025 -- source-built,
--   conda OpenMPI 5.0.10, PKG_PYTHON=OFF, glibc-safe -- EXCEPT the LAMMPS
--   version, which is the whole reason it exists: the prebuilt deepmd-kit
--   plugin (libdeepmd_lmp.so) is ABI-locked to LAMMPS 2024.08.29 (a
--   utils::bounds<int> signature changed after it), so it loads here and
--   refuses the 22Jul2025 engine.  DeePMD is therefore reachable with NO
--   deepmd rebuild.
--
-- Cheaper than the site deepmd module in two ways, both because the conda
--   env supplies newer libraries: NO libstdc++ LD_PRELOAD is needed (the
--   env's libstdc++ already has the CXXABI the backend wants), and the
--   deepmd-kit here is 3.1.3 (dual TF + PyTorch backend), which loads a
--   model frozen by the group's deepmd 2.2.10 / TensorFlow training stack
--   DIRECTLY -- a real 2.2.10 graph.pb ran a force step through it with no
--   conversion (job 15686597).
--
-- Assumes sabsim is ACTIVE (inherited from ssabsim): the plugin's
--   TF/PyTorch/CUDA backend libraries resolve from that env.  The plugin is
--   loaded EXPLICITLY by a LAMMPS input line (variable dp getenv
--   DEEPMD_LMP_PLUGIN; plugin load ${dp}) -- never auto-loaded via
--   LAMMPS_PLUGIN_PATH, which the job scripts unset (§4.4).
--
-- family("lammps") makes this and cpg_lammps_conda/22Jul2025 mutually
--   exclusive -- load exactly one.
-- ---------------------------------------------------------------------

help([[
LAMMPS 29 Aug 2024 (conda-derived), the DeePMD-capable build: source-
built, conda OpenMPI 5.0.10, deepmd-kit 3.1.3 plugin.  The bond-job engine.
Load it from a job that has already activated sabsim; then, from a
LAMMPS input:
   variable dp getenv DEEPMD_LMP_PLUGIN
   plugin load ${dp}
after which pair_style deepmd (and deepspin, dplr, ...) are available.
No libstdc++ preload is required (the conda env supplies the CXXABI).
]])

whatis("Name        : cpg_lammps_conda")
whatis("Version     : 2024.08.29-deepmd (conda OpenMPI 5.0.10)")
whatis("Category    : molecular dynamics")
whatis("Description : LAMMPS DeePMD engine, source-built + conda-linked")

-- The versioned install directory.  Point this at a new prefix to
--   publish a rebuild; nothing else in this file needs to change.
local prefix = "/cluster/VAST/rulisp-lab/cpg/programs/lammps/"
               .. "2024.08.29-deepmd-conda-ompi5.0.10"

-- The conda env that provides the DeePMD inference libraries (the plugin,
--   libdeepmd_cc, the TF/PyTorch backends and CUDA) AND the newer
--   libstdc++.  The plugin is exposed as an env var a LAMMPS input loads
--   explicitly; loading it from its REAL directory lets its own
--   $ORIGIN-relative dependencies resolve.
local deepmd_env = "/cluster/VAST/rulisp-lab/cpg/mamba/envs/sabsim"

prepend_path("PATH", pathJoin(prefix, "bin"))
prepend_path("LD_LIBRARY_PATH", pathJoin(prefix, "lib64"))
prepend_path("PYTHONPATH", pathJoin(prefix, "lib64/python"))
setenv("LAMMPS_POTENTIALS", pathJoin(prefix, "share/lammps/potentials"))
prepend_path("CPATH", pathJoin(prefix, "include"))
prepend_path("PKG_CONFIG_PATH", pathJoin(prefix, "lib64/pkgconfig"))

-- Backend libraries for the deepmd plugin (belt-and-suspenders over the
--   active env): libdeepmd_cc and the PyTorch runtime the plugin dlopens.
prepend_path("LD_LIBRARY_PATH", pathJoin(deepmd_env, "lib"))
prepend_path("LD_LIBRARY_PATH",
    pathJoin(deepmd_env, "lib/python3.11/site-packages/torch/lib"))

-- The plugin path a LAMMPS input loads with `plugin load ${dp}`.
setenv("DEEPMD_LMP_PLUGIN", pathJoin(deepmd_env, "lib/libdeepmd_lmp.so"))

family("lammps")
