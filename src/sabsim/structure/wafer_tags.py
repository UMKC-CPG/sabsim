"""The two wafer-tag constants, in a dependency-free module.

Wafer A is the BOTTOM slab of an assembled pair and wafer B the TOP — the
assembly invariant the press/pull driver relies on (`DESIGN.md` §2.6). The
constants live HERE, apart from :mod:`sabsim.structure.slab_builder`, so
that consumers who need only the tags — notably the press/pull DRIVER
(:mod:`sabsim.driver.press_pull`) — do not transitively import the heavy
structure-building stack (pymatgen's coincidence search, ASE). That
decoupling is what lets the driver run inside the deepmd bundle's Python
(which has neither pymatgen nor, by default, ASE) so the press/pull can be
driven by the out-of-process universal MLIP. ``slab_builder`` re-exports
these, so ``from ...slab_builder import WAFER_A_TAG`` keeps working.
"""

# LAMMPS atom-tag values that mark which wafer an atom belongs to. Small
# positive integers so they survive a LAMMPS data file's tag column.
WAFER_A_TAG = 1
WAFER_B_TAG = 2
