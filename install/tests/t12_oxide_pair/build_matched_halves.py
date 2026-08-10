#!/usr/bin/env python
"""Build the two MATCHED SiO2 / LiNbO3 halves on ONE shared cell (§2.4).

Login-node geometry step for the SiO2/LiNbO3 bond-debond: the two wafers
must sit on ONE commensurate, low-strain cell BEFORE amorphization, because
an amorphous network has no lattice to strain cleanly afterward (§2.4). This
mirrors the live build convention (`live_stages.build_halves`) exactly:

  cut each wafer's PRIMITIVE surface slab (SiO2(100), LiNbO3(001))
    -> match the two surface lattices (Zur-McGill, `match_surfaces`)
    -> even-split the shared cell (`even_split_shared_cell`)
    -> tile each wafer by its whole-number matrix ONTO that cell (strain in)
    -> tile both by the SAME dose footprint (commensurate, strain-neutral)

Both halves DECLARE the GLOBAL type map — the beam plus EVERY element either
wafer contributes ({Ar, Li, Nb, O, Si}) — so the assembled pair maps onto
Prakash's [Si, Li, Nb, O] bond model unchanged (§4.3). It writes each half's
LAMMPS data file (the cascade reads it) and pickles the half (the cascade
needs its atoms + type map), plus the match, into VALWORK.

CIF lattices are used directly here; the model-derived-lattice rescale
(§2.2) is a deferred refinement. Env: VALWORK (output dir), and optional
overrides T12_TARGET_FOOTPRINT (A^2), T12_THICKNESS, T12_VACUUM.
"""

import os
import pickle
import warnings
from collections import Counter

import numpy as np

warnings.filterwarnings("ignore")   # pymatgen CIF rounding notices

from sabsim.structure.slab_builder import (
    build_standalone_half,
    even_split_shared_cell,
    load_crystal,
    match_surfaces,
    write_standalone_half,
)

# The two crystals and the faces that matched at ~2% strain (SiO2(100) /
# LiNbO3(001), the lowest-strain compact fit the matcher found).
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
SIO2_CIF = os.path.join(
    _REPO, "src/sabsim/structure/data/sio2_alpha_quartz.cif")
LINBO3_CIF = os.path.join(
    _REPO, "sunita/bond_debond/share/linbo3_bulk.cif")
SIO2_FACE = (1, 0, 0)
LINBO3_FACE = (0, 0, 1)
# The beam plus BOTH wafers' species — the one global type map (§4.3).
GLOBAL_SPECIES = frozenset({"Ar", "Si", "O", "Li", "Nb"})


def main() -> None:
    work_directory = os.environ["VALWORK"]
    os.makedirs(work_directory, exist_ok=True)
    target_footprint = float(os.environ.get("T12_TARGET_FOOTPRINT", "500"))
    thickness = float(os.environ.get("T12_THICKNESS", "45"))
    vacuum = float(os.environ.get("T12_VACUUM", "20"))

    sio2 = load_crystal(SIO2_CIF)
    linbo3 = load_crystal(LINBO3_CIF)

    # Match on the PRIMITIVE surface cells (lateral repeat 1), as the matcher
    # expects — its area budget is for the primitive cell.
    primitive_sio2 = build_standalone_half(
        sio2, SIO2_FACE, "SiO2", GLOBAL_SPECIES,
        min_slab_thickness=thickness, min_vacuum=vacuum, lateral_repeat=1)
    primitive_linbo3 = build_standalone_half(
        linbo3, LINBO3_FACE, "LiNbO3", GLOBAL_SPECIES,
        min_slab_thickness=thickness, min_vacuum=vacuum, lateral_repeat=1)

    # slab_a = film (SiO2), slab_b = substrate (LiNbO3) — the live convention.
    match = match_surfaces(
        primitive_sio2.atoms, primitive_linbo3.atoms,
        max_area=400.0, misfit_tolerance=0.08)
    shared_cell = even_split_shared_cell(
        match.substrate_cell, match.film_cell)
    tiling_sio2 = match.film_tiling            # SiO2 is the film
    tiling_linbo3 = match.substrate_tiling     # LiNbO3 is the substrate
    print("match: strain=%.2f%% area=%.0f A^2 | SiO2 tiling=%s "
          "LiNbO3 tiling=%s" % (match.residual_strain * 100,
          match.match_area, tiling_sio2, tiling_linbo3))

    # One dose tile IS the shared cell; size the footprint from its area.
    base_area = abs(float(np.linalg.det(np.asarray(shared_cell)[:, :2])))
    footprint_repeat = max(
        1, int(round((target_footprint / base_area) ** 0.5)))
    print("shared-cell base area=%.0f A^2 -> footprint_repeat=%d (~%.0f A^2)"
          % (base_area, footprint_repeat, base_area * footprint_repeat ** 2))

    # Build BOTH footprint halves on the shared cell (the same repeat keeps
    # them commensurate; tiling is strain-neutral so it never touches match).
    half_sio2 = build_standalone_half(
        sio2, SIO2_FACE, "SiO2", GLOBAL_SPECIES,
        min_slab_thickness=thickness, min_vacuum=vacuum,
        lateral_repeat=footprint_repeat,
        coincidence_tiling=tiling_sio2, shared_cell=shared_cell)
    half_linbo3 = build_standalone_half(
        linbo3, LINBO3_FACE, "LiNbO3", GLOBAL_SPECIES,
        min_slab_thickness=thickness, min_vacuum=vacuum,
        lateral_repeat=footprint_repeat,
        coincidence_tiling=tiling_linbo3, shared_cell=shared_cell)

    for name, half in (("sio2", half_sio2), ("linbo3", half_linbo3)):
        atoms = half.atoms
        z_extent = float(np.ptp(atoms.get_positions()[:, 2]))
        print("%-7s %5d atoms | %s | z-extent %.1f A | type_map %s"
              % (name, len(atoms),
                 dict(Counter(atoms.get_chemical_symbols())), z_extent,
                 half.type_map))
        write_standalone_half(
            half, os.path.join(work_directory, f"{name}_half.data"))
        with open(os.path.join(work_directory, f"{name}_half.pkl"),
                  "wb") as handle:
            pickle.dump(half, handle)

    # The decisive check: the two in-plane cells must be identical, which is
    # what the assembly's commensurability assert (§2.6) demands.
    cell_sio2 = np.asarray(half_sio2.atoms.get_cell())[:2, :2]
    cell_linbo3 = np.asarray(half_linbo3.atoms.get_cell())[:2, :2]
    commensurate = bool(np.allclose(cell_sio2, cell_linbo3, atol=1.0e-6))
    print("in-plane cells commensurate:", commensurate)
    assert commensurate, "halves are NOT commensurate — will not assemble"

    with open(os.path.join(work_directory, "match.pkl"), "wb") as handle:
        pickle.dump({"match": match, "shared_cell": shared_cell,
                     "footprint_repeat": footprint_repeat}, handle)
    print("MATCHED BUILD OK ->", work_directory)


if __name__ == "__main__":
    main()
