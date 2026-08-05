"""Validate a conda-derived LAMMPS engine after the sabsim_dev -> sabsim
rename (T-RENAME).

The rename cloned the conda env, rebuilt the venv, and `patchelf`-ed the
engine binaries' RPATH from `.../envs/sabsim_dev/lib` to
`.../envs/sabsim/lib`.  This probe is the runtime proof that the patched
engine still loads its conda libmpi and runs a real MD step under the NEW
env, and (for deepmd) that the module's rewritten plugin path resolves.

Run it once per engine via the slurm sibling, which selects the engine
with a Lmod `module load` and passes the mode as argv[1]:

    python rename_validate.py {classical|deepmd}

It builds a tiny crystalline-silicon box from a lattice (no data file
needed), loads the engine's force model, and runs a few steps.  It
self-logs the loaded `liblammps` and its `libmpi` so the log alone proves
the binary now resolves the conda MPI from `envs/sabsim`, not `sabsim_dev`.
"""

from __future__ import annotations

import os
import subprocess
import sys


def _log_environment(engine_mode: str) -> None:
    """Print the few facts that let the log reconstruct what ran."""
    print(f"=== RENAME VALIDATE: engine={engine_mode} ===", flush=True)
    print("CONDA_DEFAULT_ENV :", os.environ.get("CONDA_DEFAULT_ENV"),
          flush=True)
    print("python            :", sys.executable, flush=True)
    import lammps
    print("lammps wrapper    :", lammps.__file__, flush=True)


def _log_liblammps_libmpi() -> None:
    """ldd the loaded liblammps and show which libmpi it binds.

    The whole point of the rename validation: this line must resolve to
    `.../envs/sabsim/lib/libmpi...`, never `sabsim_dev`.
    """
    import lammps
    wrapper_directory = os.path.dirname(lammps.__file__)
    # The shared library sits one level up from the ctypes wrapper, in
    # the engine prefix's lib64; ldd it to see the resolved libmpi.
    candidate = os.path.join(
        os.path.dirname(wrapper_directory), "liblammps.so")
    if os.path.isfile(candidate):
        ldd = subprocess.run(
            ["ldd", candidate], capture_output=True, text=True)
        for line in ldd.stdout.splitlines():
            if "libmpi" in line or "libdeepmd" in line:
                print("   ldd:", line.strip(), flush=True)


# The tiny crystalline-silicon box every mode runs on — a lattice build,
# so the probe needs no external data file.  One atom type (Si), which
# matches both the classical SW potential and the Si-only deepmd model.
_SILICON_BOX_COMMANDS = """
units metal
atom_style atomic
boundary p p p
lattice diamond 5.43
region box block 0 3 0 3 0 3
create_box 1 box
create_atoms 1 box
mass 1 28.0855
"""


def run_classical(engine) -> None:
    """Load the Stillinger-Weber potential and run ten steps."""
    engine.commands_string(_SILICON_BOX_COMMANDS)
    # Si.sw is found through LAMMPS_POTENTIALS, which the module sets.
    engine.commands_string(
        "pair_style sw\n"
        "pair_coeff * * Si.sw Si\n"
        "velocity all create 300.0 12345\n"
        "fix integrate all nve\n"
        "thermo 5\n"
        "run 10\n")


def run_deepmd(engine) -> None:
    """Load the deepmd plugin, then the Si model, and run one step.

    The model path comes from SABSIM_DEEPMD_MODEL (the slurm sets it to
    the group's trained Si graph.pb); the plugin path from the engine
    module's DEEPMD_LMP_PLUGIN, which the rename repointed to envs/sabsim.
    """
    model_path = os.environ["SABSIM_DEEPMD_MODEL"]
    engine.commands_string(_SILICON_BOX_COMMANDS)
    engine.commands_string(
        "variable dp getenv DEEPMD_LMP_PLUGIN\n"
        "plugin load ${dp}\n"
        f"pair_style deepmd {model_path}\n"
        "pair_coeff * *\n"
        "velocity all create 300.0 12345\n"
        "fix integrate all nve\n"
        "thermo 1\n"
        "run 2\n")


def main() -> int:
    """Load the selected engine, run its force model, report the energy."""
    engine_mode = sys.argv[1] if len(sys.argv) > 1 else "classical"
    _log_environment(engine_mode)

    from lammps import lammps
    engine = lammps(cmdargs=["-screen", "none", "-log", "none"])
    _log_liblammps_libmpi()

    if engine_mode == "deepmd":
        run_deepmd(engine)
    else:
        run_classical(engine)

    potential_energy = engine.get_thermo("pe")
    print(f"potential_energy (eV): {potential_energy}", flush=True)
    if potential_energy == 0.0:
        raise SystemExit("PE is exactly zero — the force model did not "
                         "engage; treat as FAIL.")
    print(f"RENAME VALIDATE {engine_mode}: OK", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
