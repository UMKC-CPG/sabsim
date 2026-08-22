#!/usr/bin/env python
"""T-20 part 2 (deepmd bundle python): frame-0 stress + box-relax + NVT.

The archive's DECISION GATE for the 2-D DPA-lattice pair: does it start
near zero stress under DPA (proceed) or is the commensurability-vs-
equilibrium tension fundamental (redesign)? Reports the atom COUNT at
every stage so a disintegration is caught from the count, not the exit
code, and dumps a trajectory for OVITO.

Env: SABSIM_CASCADE_MLIP_MODEL (.pt2), VALWORK (holds pristine_pair.data).
"""
import os

from sabsim.driver.commands import (
    ForceModel, combined_cell_relax_commands, force_model_commands,
    preamble_commands,
)
from sabsim.driver.lammps_engine import LammpsEngine
from sabsim.spec.records import Quantity

work = os.environ["VALWORK"]
model = os.environ["SABSIM_CASCADE_MLIP_MODEL"]
data = os.path.join(work, "pristine_pair.data")

# type_map {Li:1, Nb:2, O:3, Si:4} -> pair_coeff element order.
fm = ForceModel(pair_style=f"deepmd {model}",
                pair_coeff=("* * Li Nb O Si",), preload=(),
                needs_atom_map=True)
eng = LammpsEngine(
    command_line_args=["-screen", "none",
                       "-log", os.path.join(work, "log.frame0")], comm=None)

eng.commands(preamble_commands(data, Quantity(1.0, "fs"), fm))
eng.commands(force_model_commands(fm))
eng.commands(["dump traj all custom 200 "
              + os.path.join(work, "frame0_relax.dump") + " id type x y z"])
GPA = 10000.0


def report(tag):
    print(f"[{tag}] atoms={eng.atom_count()} "
          f"pxx+pyy(mean)={eng.in_plane_stress()/GPA:.2f} GPa "
          f"pzz={eng.normal_stress()/GPA:.2f} GPa")


eng.commands(["run 0"])
report("frame-0 (as built)")

# Item 3: the one-time combined-cell box-relax.
eng.commands(combined_cell_relax_commands())
eng.commands(["run 0"])
report("after box-relax")

# Short 300 K NVT on the relaxed cell -- does it STAY ordered / conserved?
# (No reset_timestep: the dump is open, and LAMMPS forbids resetting the
# step under an active dump; the absolute step just continues.)
eng.commands([
    "velocity all create 300.0 4928459 dist gaussian",
    "fix nvt all nvt temp 300.0 300.0 0.1",
    "run 4000",
    "unfix nvt",
])
report("after 2 ps NVT 300 K")
eng.close()
print("T20 FRAME0 CHECK COMPLETE")
