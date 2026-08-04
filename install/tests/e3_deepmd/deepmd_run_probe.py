"""E3 step 2 of 2 — a REAL pair_style deepmd force step on Stack C.

E2 already proved the deepmd style REGISTERS; this proves a trained model
actually COMPUTES forces through the Stack C engine.  It stays faithful
to SABSIM's code path: mpi4py is imported first, the engine is built with
the shared communicator (lammps_engine.py:85), and the deepmd plugin is
loaded EXPLICITLY from the LAMMPS side (prepare.py:122, ARCHITECTURE
§4.4) rather than auto-loaded via LAMMPS_PLUGIN_PATH.

The model is Prakash's PRODUCTION Si potential — a fully-trained (400k
step) deepmd-kit 2.2.10 / TensorFlow graph frozen as `graph.pb`, in
cpg/share/train_deepmd_si.  So this simultaneously tests the real
TRAINING->INFERENCE seam: a deepmd 2.2.10 / TF `.pb` loaded by our Stack
C deepmd 3.1.3 plugin (which ships both the TF and PyTorch backends).
Its type_map is ["Si"], so LAMMPS atom type 1 maps to Si and
`pair_coeff * *` needs no extra arguments.

PASS criteria (all must hold): the deepmd style is registered, a real MD
step completes, the potential energy is finite and non-zero, and the
maximum per-atom force magnitude is finite and non-zero — i.e. the neural
network truly evaluated forces, not a silent no-op.
"""
import os
import math
import socket

import numpy as np

# mpi4py FIRST, exactly as SABSIM's cli.py does, so the process holds the
# conda libmpi before LAMMPS loads and both share one MPI_COMM_WORLD.
from mpi4py import MPI

from lammps import lammps
import lammps as lammps_module

communicator = MPI.COMM_WORLD
rank = communicator.Get_rank()
size = communicator.Get_size()
this_host = socket.gethostname()

model_path = os.environ["E3_MODEL"]
plugin_path = os.environ.get("DEEPMD_LMP_PLUGIN", "")

# Keep per-run logs off; let only rank 0 keep the screen.
startup_arguments = ["-log", "none"]
if rank != 0:
    startup_arguments += ["-screen", "none"]

engine = lammps(comm=communicator, cmdargs=startup_arguments)

# Load the deepmd plugin EXPLICITLY (the design's mechanism), then build a
# small crystalline-silicon cell and drive it with the trained model.
engine.command(f"plugin load {plugin_path}")
deepmd_registered = engine.has_style("pair", "deepmd")

for command in [
    "units metal",
    "atom_style atomic",
    "boundary p p p",
    "lattice diamond 5.431",
    "region simulation_box block 0 3 0 3 0 3",
    "create_box 1 simulation_box",
    "create_atoms 1 box",
    "mass 1 28.0855",
    f"pair_style deepmd {model_path}",
    "pair_coeff * *",
    "velocity all create 300.0 12345 mom yes rot yes",
    "fix integrate all nve",
    "thermo 5",
    "run 10",
]:
    engine.command(command)

# LAMMPS's own MPI world size — equals mpi4py size only if the shared
# communicator really reached LAMMPS.
try:
    lammps_world_size = engine.extract_setting("world_size")
except Exception:
    lammps_world_size = "?"

num_atoms = engine.get_natoms()
potential_energy = engine.get_thermo("pe")

# Per-atom forces on THIS rank; reduce the local max magnitude across all
# ranks so rank 0 can report the global maximum.  A finite, non-zero max
# force is the real evidence the deepmd network evaluated forces.
local_forces = engine.numpy.extract_atom("f")
if local_forces is not None and len(local_forces):
    local_max_force = float(np.max(np.abs(local_forces)))
else:
    local_max_force = 0.0
global_max_force = communicator.allreduce(local_max_force, op=MPI.MAX)

energy_is_finite = isinstance(potential_energy, float) and math.isfinite(
    potential_energy) and abs(potential_energy) > 0.0
force_is_finite = math.isfinite(global_max_force) and global_max_force > 0.0

print(
    f"RANKINFO rank={rank}/{size} lammps_world={lammps_world_size} "
    f"host={this_host} natoms={num_atoms} "
    f"local_max_f={local_max_force:.6g}"
)

if rank == 0:
    print("wrapper file   :", lammps_module.__file__)
    print("model          :", model_path)
    print("deepmd plugin  :", plugin_path or "(DEEPMD_LMP_PLUGIN unset)")
    print("pair_style deepmd registered:", deepmd_registered)
    print(f"potential_energy (eV)       : {potential_energy:.6f}")
    print(f"global_max_force (eV/Angstrom): {global_max_force:.6f}")
    all_checks_pass = (
        deepmd_registered
        and lammps_world_size == size
        and energy_is_finite
        and force_is_finite
    )
    if all_checks_pass:
        print("DEEPMD RUN OK")
    else:
        print("DEEPMD RUN FAILED checks")

engine.close()
