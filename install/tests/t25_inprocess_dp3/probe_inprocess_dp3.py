"""T-25: can SABSIM's in-process engine run a DPA `.pth`? (option (a)).

Runs INSIDE the sabsim-dp3 venv on a GPU node. It uses the real pieces
the bond stage uses — :class:`LammpsEngine`, :func:`deepmd_model`, the
preamble that sets ``atom_modify map yes`` — on a periodic silicon block
built by the real bulk builder, and judges the result from the physics:
the plugin must register ``pair_style deepmd``, the model must evaluate
on the GPU, and 200 steps of NVE at 300 K must conserve total energy.
Every rank prints its verdict; under ``srun -n 2`` the two ranks must
agree on the energy, which proves the domain decomposition works with
the bundle's MPI.
"""

import os
import sys

import numpy as np

from mpi4py import MPI

from sabsim.driver.bulk_relax import bulk_relax_commands
from sabsim.driver.commands import deepmd_model
from sabsim.driver.lammps_engine import LammpsEngine
from sabsim.structure.slab_builder import (
    bulk_type_map,
    load_crystal,
    write_bulk_data,
)

REPO = os.environ["SABSIM_REPO"]
WORK = os.environ["T25_WORK"]
MODEL = os.environ["T25_MODEL"]
CELLS_PER_AXIS = 3            # 216-atom Si block, small and fast


def main() -> int:
    comm = MPI.COMM_WORLD
    rank = comm.Get_rank()
    crystal = load_crystal(
        os.path.join(REPO, "src/sabsim/structure/data/si_diamond.cif"))
    data_file = os.path.join(WORK, "bulk_si.data")
    if rank == 0:
        write_bulk_data(crystal, CELLS_PER_AXIS, data_file)
    comm.Barrier()
    model = deepmd_model(MODEL)
    engine = LammpsEngine(
        command_line_args=["-screen", "none", "-log",
                           os.path.join(WORK, f"log.t25")],
        comm=comm)
    # Relax the box under the model (the real §2.2 command block), then
    # a short NVE run to test energy conservation.
    engine.commands(bulk_relax_commands(data_file, model))
    relaxed_edge = float(engine.box()[0, 0]) / CELLS_PER_AXIS
    engine.commands([
        "unfix relax_box",
        "velocity all create 300.0 4928459 dist gaussian",
        "fix nve all nve",
        "timestep 0.001",
        "thermo 50",
        "compute ke_all all ke",
        "variable etotal equal pe+c_ke_all",
        "run 0",
    ])
    energy_start = float(engine._lmp.extract_variable("etotal"))
    engine.commands(["run 200"])
    energy_end = float(engine._lmp.extract_variable("etotal"))
    atoms = engine.atom_count()
    drift = abs(energy_end - energy_start) / atoms
    engine.close()
    print(f"T25RESULT rank={rank} ranks={comm.Get_size()} atoms={atoms} "
          f"a={relaxed_edge:.4f} etot0={energy_start:.4f} "
          f"etot1={energy_end:.4f} drift_eV_per_atom={drift:.2e}",
          flush=True)
    return 0 if drift < 1.0e-3 else 1


if __name__ == "__main__":
    sys.exit(main())
