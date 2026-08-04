"""Runtime probe of the conda-5.0.10 LAMMPS classical engine.

Confirms the freshly built engine (a) imports from its prefix wrapper,
(b) loads its glibc-safe liblammps under the venv python, (c) runs a real
Si Stillinger-Weber MD step, and (d) does all of that across two nodes on
the InfiniBand fabric. This is the analog of the diagnostic probe that
first exposed the RPATH/glibc failure (job 15520412) — now against the
FIXED engine, so it should PASS.
"""
import socket

from mpi4py import MPI
from lammps import lammps
import lammps as lammps_module

comm = MPI.COMM_WORLD
rank = comm.Get_rank()
size = comm.Get_size()
this_host = socket.gethostname()
layout = comm.gather((rank, this_host), root=0)

# A small crystalline Si block run for a few NVE steps under the
# Stillinger-Weber potential — a genuine force evaluation plus MPI ghost
# exchange, so a 2-rank run actually crosses the network.
engine = lammps(comm=comm, cmdargs=["-log", "none", "-screen", "none"])
for command in [
    "units metal",
    "atom_style atomic",
    "boundary p p p",
    "lattice diamond 5.431",
    "region box block 0 6 0 6 0 6",
    "create_box 1 box",
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

version = engine.version()
num_atoms = engine.get_natoms()
potential_energy = engine.get_thermo("pe")
engine.close()

if rank == 0:
    print("lammps wrapper :", lammps_module.__file__)
    print("LAMMPS version :", version)
    print("COMM_WORLD     :", size, "ranks")
    for member_rank, member_host in sorted(layout):
        print(f"    rank {member_rank} -> {member_host}")
    print("atoms          :", num_atoms)
    print("PE (eV)        :", potential_energy)
    print("ENGINE RUN OK")
