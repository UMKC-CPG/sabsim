"""Structure building — slabs and facing pairs (DESIGN.md §2).

Wave 0 provides a minimal Si/Si builder (:mod:`sabsim.structure.si_slabs`)
behind the same idea the full §2 builder will fill in: ASE is the
structure membrane (VISION principle 4), so a slab is an ASE ``Atoms``
object and the only thing that crosses to LAMMPS is a data file written
from it. The coincidence matcher and the §2.5 thickness convergence
arrive with the Si/SiO2 milestone (ARCHITECTURE.md §5, wave 3).
"""
