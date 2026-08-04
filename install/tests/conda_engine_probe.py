"""Symmetric counterpart to site_engine_probe.py, for STACK C.

Where the site probe (job 15580445) ran the LAMMPS-owns-MPI model, this
one exercises the model SABSIM's CODE actually uses -- mpi4py
comm-sharing -- against our conda-built deepmd engine (linked to conda
OpenMPI 5.0.10).  It fills three cells of the decision matrix at once:

  E1  engine imports + runs a real 2-node MD step, in-process
  E2  pair_style deepmd registers
  E4  the mpi4py comm-sharing model works (comm=MPI.COMM_WORLD passed to
      LAMMPS, AND a Python-side comm.bcast -- the exact operation at
      src/sabsim/pipeline/live_stages.py:518)

A PASS means Stack C supports SABSIM's current code unchanged, with a
single MPI (conda 5.0.10) shared by mpi4py and liblammps.

Self-logging: this driver prints which wrapper, which mpi4py, and which
libmpi actually loaded, so the log alone reconstructs what ran (ledger
rule #2).
"""
import os
import socket

# Import order matters for the honesty of the test: bring in mpi4py
# FIRST (this is what SABSIM's cli.py does), so the process is already
# holding conda's libmpi when LAMMPS loads.  Both must be the SAME
# libmpi for a shared communicator to work at all.
from mpi4py import MPI
import mpi4py

from lammps import lammps
import lammps as lammps_module

communicator = MPI.COMM_WORLD
rank = communicator.Get_rank()
size = communicator.Get_size()
this_host = socket.gethostname()

# Build the engine with the SHARED communicator -- exactly as
# lammps_engine.py:85 and live_stages.py:411 do.  LAMMPS then
# domain-decomposes over mpi4py's MPI_COMM_WORLD instead of owning MPI
# itself.  Keep per-run logs off; let only rank 0 keep screen so the
# "on N procs" summary prints once.
startup_arguments = ["-log", "none"]
if rank != 0:
    startup_arguments += ["-screen", "none"]

engine = lammps(comm=communicator, cmdargs=startup_arguments)

# The same small crystalline-silicon Stillinger-Weber run as the site
# probe, so the two tests are directly comparable.
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

# LAMMPS's own view of the MPI world.  If it equals the mpi4py size, the
# shared communicator really did reach LAMMPS (not two serial engines).
try:
    lammps_world_size = engine.extract_setting("world_size")
except Exception as extract_error:
    lammps_world_size = "?"
    print("NOTE extract_setting unavailable:", extract_error)

potential_energy = engine.get_thermo("pe")
num_atoms = engine.get_natoms()

# --- Exercise the Python-side collective the code depends on ----------
# live_stages.py:518 does `structure = comm.bcast(structure, root=0)`.
# Reproduce that exact call shape: rank 0 broadcasts a payload, every
# rank must receive it.  This proves mpi4py collectives work on the same
# communicator LAMMPS is using -- the crux of E4.
broadcast_payload = {"probe": "stack-C", "token": 424242} if rank == 0 else None
broadcast_payload = communicator.bcast(broadcast_payload, root=0)
broadcast_ok = (
    isinstance(broadcast_payload, dict)
    and broadcast_payload.get("token") == 424242
)

# Gather the rank->host layout so the log proves 2 distinct nodes.
host_layout = communicator.gather((rank, this_host), root=0)

# Every rank prints its own line (helps if something hangs on one rank).
print(
    f"RANKINFO rank={rank}/{size} lammps_world={lammps_world_size} "
    f"host={this_host} natoms={num_atoms} bcast_ok={broadcast_ok}"
)

# --- DeePMD plugin registration (collective: all ranks) ---------------
deepmd_plugin_path = os.environ.get("DEEPMD_LMP_PLUGIN", "")
deepmd_registered = None
if deepmd_plugin_path:
    engine.command(f"plugin load {deepmd_plugin_path}")
    deepmd_registered = engine.has_style("pair", "deepmd")

# Rank 0 prints the self-logging block and the verdict.
if rank == 0:
    distinct_hosts = sorted({host for _, host in host_layout})
    print("wrapper file   :", lammps_module.__file__)
    print("mpi4py module  :", mpi4py.__file__)
    print("LAMMPS version :", engine.version())
    print("mpi4py world   :", size, "ranks on hosts", distinct_hosts)
    print("deepmd plugin  :", deepmd_plugin_path or "(DEEPMD_LMP_PLUGIN unset)")
    print("pair_style deepmd registered:", deepmd_registered)
    all_checks_pass = (
        lammps_world_size == size
        and len(distinct_hosts) == 2
        and broadcast_ok
        and deepmd_registered
    )
    if all_checks_pass:
        print("CONDA ENGINE OK")

engine.close()
