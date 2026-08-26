-- ---------------------------------------------------------------------
-- The deepmd-kit 3.2.0b0 bundle as an IN-PROCESS engine (ARCH §4.4,
--   decision 2026-08-26 "option (a)").  The bundle is a complete conda
--   environment: Python 3.12, OpenMPI 5.0.10 + mpi4py, a LAMMPS
--   2024.08.29 Python binding (liblammps.so), and the deepmd pair style
--   as a LAMMPS plugin (lib/deepmd_lmp/dpplugin.so) whose PyTorch backend
--   loads a DPA `.pth` -- the universal model, and later the ALF-trained
--   committee -- directly.  So `pair_style deepmd` can run inside
--   SABSIM's own process, which is what the interactive press/pull loops
--   need; no LAMMPS is compiled.
--
-- Pairs with the venv virtual_envs/sabsim-dp3, built on the bundle's
--   python (--system-site-packages) so numpy/ase/mpi4py/torch come from
--   the bundle and only pymatgen + sabsim are layered on top.  Load this
--   module FIRST, then activate that venv (so its python wins on PATH).
--
-- The plugin is loaded EXPLICITLY by a LAMMPS input line (variable dp
--   getenv DEEPMD_LMP_PLUGIN; plugin load ${dp}), never auto-loaded via
--   LAMMPS_PLUGIN_PATH, which is unset here -- the same discipline as the
--   2024.08.29-deepmd engine.  family("lammps") makes the engines
--   mutually exclusive.
-- ---------------------------------------------------------------------

help([[
deepmd-kit 3.2.0b0 bundle as the in-process SABSIM engine: LAMMPS
2024.08.29 Python binding + deepmd plugin (PyTorch backend, CUDA 12.9).
Load this module, THEN activate virtual_envs/sabsim-dp3; a LAMMPS
input then does
   variable dp getenv DEEPMD_LMP_PLUGIN
   plugin load ${dp}
after which pair_style deepmd loads a DPA/DeePMD .pth in-process.
]])

whatis("Name        : cpg_lammps_conda")
whatis("Version     : deepmd-kit-3.2.0b0 (bundle OpenMPI 5.0.10, CUDA 12.9)")
whatis("Category    : molecular dynamics")
whatis("Description : in-process LAMMPS + deepmd 3.2 plugin engine")

local prefix = "/cluster/VAST/rulisp-lab/cpg/programs/deepmd-kit-3.2.0b0-cuda129"

prepend_path("PATH", pathJoin(prefix, "bin"))
-- liblammps.so is found by ctypes by NAME (the python package carries no
--   copy), so the bundle's lib must be on the loader path.
prepend_path("LD_LIBRARY_PATH", pathJoin(prefix, "lib"))
prepend_path("LD_LIBRARY_PATH",
    pathJoin(prefix, "lib/python3.12/site-packages/torch/lib"))

setenv("DEEPMD_LMP_PLUGIN", pathJoin(prefix, "lib/deepmd_lmp/dpplugin.so"))
unsetenv("LAMMPS_PLUGIN_PATH")

family("lammps")
