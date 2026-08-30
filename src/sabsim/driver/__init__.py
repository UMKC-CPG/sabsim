"""The persistent LAMMPS driver for the press/pull MD (DESIGN.md §5, §9).

The bond/debond stage runs on ONE persistent, in-process LAMMPS driver
rather than a fresh process per phase with a disk round-trip
(ARCHITECTURE.md §4.1). This package is built in slices:

* :mod:`sabsim.driver.commands` — slice 2. The PURE, deterministic
  mapping from the project's ``{value, unit}`` knobs to the LAMMPS command
  strings that set up and drive the press and pull. It touches no
  simulator, so it is unit-testable on a login node with no LAMMPS
  present (PSEUDOCODE.md §9.8, "the exact LAMMPS fix syntax" — the code
  level below the pseudocode).

Later slices add the control logic that decides mid-run when to stop
(slice 3) and the in-process engine that actually issues these commands
to LAMMPS and reads forces and stresses back (slices 4-5, compute node).
"""
