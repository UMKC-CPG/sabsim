"""Structure building — slabs and facing pairs (DESIGN.md §2).

The builder (:mod:`sabsim.structure.slab_builder`) is written ONCE for
any material: a wafer is a CIF (the authoritative structure, §1.2) plus
a Miller face, and the same code path builds silicon, silicon dioxide,
or anything else. ASE is the structure membrane (VISION principle 4), so
a slab is an ASE ``Atoms`` object and the only thing that crosses to
LAMMPS is a data file written from it, while pymatgen supplies the
adopted heavy geometry — the slab cut and the Zur-McGill coincidence
matcher (§2.3). Silicon-on-silicon is the first input and the matcher's
identity/null test; the strained-mismatch assembly and the §2.5
surface-energy termination arrive with the force engine (wave 3).
"""
