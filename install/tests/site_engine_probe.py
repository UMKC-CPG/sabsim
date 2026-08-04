"""Decisive probe: can SABSIM adopt Imago's SITE-toolchain LAMMPS engine?

This is the experiment that settles the ARCHITECTURE §4.1-vs-§4.4
contradiction.  §4.4 says the engine is a site-toolchain module
(gcc 12.3.0, OpenMPI 4.1.5) loaded with `module load`; §4.1 claims those
site modules "do NOT fit" because the conda Python's DT_RPATH forces a
conda libmpi.  Only one can be right, so we test it directly.

What this driver deliberately does and does NOT do:

  * It runs under the real SABSIM interpreter -- the `sabsim_dev` venv
    Python, which is a symlink to the conda mamba Python.  That is the
    exact interpreter whose DT_RPATH (=$ORIGIN/../lib -> conda lib) is
    the whole basis of the §4.1 "forced conda MPI" claim.  If the site
    engine loads and runs here, the claim is refuted.

  * It uses the LAMMPS-owns-MPI model: `lammps()` is created with NO
    `comm=` argument, so LAMMPS calls MPI_Init itself against its own
    RPATH-baked site OpenMPI 4.1.5.  We import NO mpi4py, precisely so
    that no conda libmpi is ever pre-loaded into the process -- the
    site liblammps must resolve its own libmpi cleanly.  (Whether the
    fuller SABSIM design later shares a communicator via a site-built
    mpi4py is a separate, smaller question; this probe answers the
    load-and-run-on-the-fabric question first.)

  * After the plain MD run it loads the conda deepmd-kit plugin exactly
    as the site modulefile prescribes and checks that `pair_style
    deepmd` registers -- confirming the deepmd path (Q1/Q2 from the
    linkage analysis: no rebuild, no OpenMPI-5 lock) works on the site
    engine too.

A PASS means: site engine imports under the venv Python, MPI_Init spans
the two allocated nodes, a genuine Stillinger-Weber force step runs, and
the deepmd plugin registers -- i.e. the proven Imago engine is directly
adoptable and the conda-5.0.10 rebuild was not required.
"""
import os
import socket

# The LAMMPS Python wrapper on PYTHONPATH is the SITE build's (the
# modulefile prepends its prefix/lib64/python).  Import it and record
# WHICH wrapper answered, so the log proves no stray copy sneaked in.
from lammps import lammps
import lammps as lammps_module

this_host = socket.gethostname()

# Build the engine WITHOUT handing it a communicator.  LAMMPS then owns
# MPI: it runs MPI_Init and adopts the launcher's MPI_COMM_WORLD, which
# under `srun --mpi=pmix` (or site `mpirun`) spans every allocated node.
# Keep the per-run log off; let the startup banner reach the shared
# stdout only from the primary rank so the "on N procs" summary -- the
# direct proof of the MPI world size -- shows up exactly once.
startup_arguments = ["-log", "none"]

# Peek at the launcher-provided rank so only rank 0 keeps screen output.
# These environment variables are set by srun/mpirun, not by mpi4py, so
# reading them keeps this driver mpi4py-free.
launcher_rank = int(
    os.environ.get("PMIX_RANK", os.environ.get("OMPI_COMM_WORLD_RANK", "0"))
)
if launcher_rank != 0:
    startup_arguments += ["-screen", "none"]

engine = lammps(cmdargs=startup_arguments)

# A small crystalline-silicon block under the Stillinger-Weber potential,
# run for a few NVE steps.  This is a genuine force evaluation with MPI
# ghost-atom exchange, so a 2-rank run actually crosses the network.
for command in [
    "units metal",
    "atom_style atomic",
    "boundary p p p",
    "lattice diamond 5.431",
    "region simulation_box block 0 6 0 6 0 6",
    "create_box 1 simulation_box",
    "create_atoms 1 box",
    "mass 1 28.0855",
    "pair_style sw",
    "pair_coeff * * Si.sw Si",
    "velocity all create 300.0 12345 mom yes rot yes",
    "fix integrate all nve",
    "thermo 25",
    "run 50",
]:
    engine.command(command)

# Ask LAMMPS itself how large its MPI world is and which rank we are --
# this is the engine's own view of MPI, the strongest possible evidence
# that the site OpenMPI actually initialised across the allocation.
try:
    world_size = engine.extract_setting("world_size")
    world_rank = engine.extract_setting("world_rank")
except Exception as extract_error:  # very old wrappers may lack these
    world_size = "?"
    world_rank = "?"
    print("NOTE extract_setting unavailable:", extract_error)

potential_energy = engine.get_thermo("pe")
num_atoms = engine.get_natoms()

# Every rank prints one self-describing line.  Two lines from two
# distinct hosts, each reporting world_size == 2, proves the engine ran
# as one 2-node MPI job (not two accidental serial engines).
print(
    f"RANKINFO world_rank={world_rank}/{world_size} "
    f"host={this_host} natoms={num_atoms} pe_eV={potential_energy}"
)

# --- DeePMD plugin registration (collective: run on ALL ranks) --------
# The site modulefile exposes the conda deepmd-kit 3.1.3 plugin through
# DEEPMD_LMP_PLUGIN and pre-loads the matching libstdc++.  Loading it
# here registers pair_style deepmd; we do NOT run a deepmd MD step (that
# needs a trained model), only confirm the style becomes available --
# the payoff being that this validates the deepmd path on the SITE
# engine (no rebuild, no OpenMPI-5 lock) at the same time.
deepmd_plugin_path = os.environ.get("DEEPMD_LMP_PLUGIN", "")
deepmd_registered = None
if deepmd_plugin_path:
    engine.command(f"plugin load {deepmd_plugin_path}")
    deepmd_registered = engine.has_style("pair", "deepmd")

# Rank 0 prints the human-facing verdict lines.
if launcher_rank == 0:
    print("wrapper file   :", lammps_module.__file__)
    print("LAMMPS version :", engine.version())
    print("deepmd plugin  :", deepmd_plugin_path or "(DEEPMD_LMP_PLUGIN unset)")
    print("pair_style deepmd registered:", deepmd_registered)
    if world_size == 2 and deepmd_registered:
        print("SITE ENGINE OK")

engine.close()
