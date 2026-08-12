#!/usr/bin/env python
"""T-17 part 1 (sabsim env): build bulk crystals for the DPA box-relax.

The T-16 press-pull explosion traced back to ONE number: the matched
SiO2/LiNbO3 cell starts at ~24 GPa of internal stress because the
geometrically-commensurate lattice is far from the universal DPA model's
OWN preferred lattice. This diagnostic measures that preferred lattice
for each material independently, so we can quantify how far off the
built cell is and decide whether a re-matched (DPA-relaxed) cell can sit
near zero pressure without breaking commensurability.

Here we only PREPARE the inputs: read each CIF, tile it into a modest
3D-periodic bulk supercell (no vacuum — this is bulk, not a slab), and
write a LAMMPS data file the bundle's in-process LAMMPS can read. We also
record each crystal's per-unit-cell lattice parameters as the BASELINE
the relaxed lattice is compared against in part 2.

Env: T17_BUILD_DIR (output data files + baseline.json), and the two CIF
paths SIO2_CIF / LINBO3_CIF.
"""

import json
import os

from ase.io import read as ase_read
from ase.io import write as ase_write

# Each material: (CIF env var, LAMMPS species order, supercell repeats).
# The species order fixes the type<->element map the pair_coeff must
# echo; the repeats give ~540-580 atoms, a healthy bulk neighbor
# environment while staying fast on one GPU.
_MATERIALS = {
    "sio2": {"cif_env": "SIO2_CIF", "specorder": ["Si", "O"],
             "repeats": (4, 4, 4)},
    "linbo3": {"cif_env": "LINBO3_CIF", "specorder": ["Li", "Nb", "O"],
               "repeats": (3, 3, 2)},
}


def main() -> None:
    build_directory = os.environ["T17_BUILD_DIR"]
    os.makedirs(build_directory, exist_ok=True)

    baseline = {}
    for name, spec in _MATERIALS.items():
        cif_path = os.environ[spec["cif_env"]]
        unit_cell = ase_read(cif_path)
        # The per-unit-cell lattice parameters are the reference the DPA
        # relaxation is measured against (a,b,c in Angstrom; angles in
        # degrees). Record them BEFORE tiling, so they stay per-cell.
        cell_parameters = [float(value) for value in
                           unit_cell.cell.cellpar()]

        supercell = unit_cell.repeat(spec["repeats"])
        data_file = os.path.join(build_directory, f"{name}_bulk.data")
        ase_write(data_file, supercell, format="lammps-data",
                  specorder=spec["specorder"], atom_style="atomic")

        baseline[name] = {
            "repeats": list(spec["repeats"]),
            "specorder": spec["specorder"],
            "unit_cell_cellpar": cell_parameters,
            "supercell_atoms": len(supercell),
        }
        print(f"{name}: {len(supercell)} atoms "
              f"({spec['repeats']} x {len(unit_cell)}/cell) -> {data_file}")
        print(f"   CIF per-cell a,b,c = {cell_parameters[0]:.4f} "
              f"{cell_parameters[1]:.4f} {cell_parameters[2]:.4f} | "
              f"angles {cell_parameters[3]:.2f} {cell_parameters[4]:.2f} "
              f"{cell_parameters[5]:.2f}")

    baseline_path = os.path.join(build_directory, "baseline.json")
    with open(baseline_path, "w") as handle:
        json.dump(baseline, handle, indent=2)
    print("wrote baseline:", baseline_path)


if __name__ == "__main__":
    main()
