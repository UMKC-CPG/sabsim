#!/usr/bin/env python
"""T-20 part 1 (sabsim env): build a PRISTINE 2-D SiO2/LiNbO3 pair.

The corrected build the T-18 ribbon skipped: rescale each crystal to its
DPA-preferred lattice (§2.2), match on a LOW-ASPECT 2-D coincidence cell
ranked by the item-4 WORST-AXIS strain (not the misleading scalar), and
assemble the pristine facing pair. Written to VALWORK/pristine_pair.data
for the part-2 GPU frame-0 stress check -- the archive's decision gate,
BEFORE any activation or press.

The target cell is the 636 A^2 / aspect-1.13 / worst-axis-1.77% / twist-5.4
cell chosen from the worst-axis search. Env: VALWORK, T17_LATTICE_JSON.
"""
import json
import math
import os

import numpy as np
import warnings

warnings.filterwarnings("ignore")

from pymatgen.analysis.interfaces.zsl import ZSLGenerator
from pymatgen.core import Lattice, Structure

from sabsim.structure.amorphized_assembly import assemble_amorphized_pair
from sabsim.structure.slab_builder import (
    WAFER_A_TAG, WAFER_B_TAG, SurfaceMatch, _polar_rotation,
    _surface_vectors, _worst_axis_strain, build_slab, build_standalone_half,
    even_split_shared_cell, load_crystal, write_lammps_data,
)

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
SIO2_CIF = os.path.join(_REPO, "src/sabsim/structure/data/"
                        "sio2_alpha_quartz.cif")
LINBO3_CIF = os.path.join(_REPO, "sunita/bond_debond/share/linbo3_bulk.cif")
LAT = json.load(open(os.environ.get(
    "T17_LATTICE_JSON",
    "/cluster/VAST/rulisp-lab/cpg/share/models/dpa_gpu_bench/"
    "t17_val/lattice_results.json")))
TARGET_AREA, TARGET_WORST = 636.0, 0.0177


def rescale(crystal, cp):
    """Scale a crystal to a=b=mean(a,b), c from the DPA cellpar (§2.2)."""
    am = 0.5 * (cp[0] + cp[1])
    tgt = np.array([am, am, cp[2]]); cur = np.array(crystal.lattice.abc)
    M = np.asarray(crystal.lattice.matrix) * (tgt / cur)[:, None]
    return Structure(Lattice(M), crystal.species, crystal.frac_coords)


def main():
    work = os.environ["VALWORK"]
    os.makedirs(work, exist_ok=True)
    sio2 = rescale(load_crystal(SIO2_CIF), LAT["sio2"]["dpa_per_cell_cellpar"])
    linbo3 = rescale(load_crystal(LINBO3_CIF),
                     LAT["linbo3"]["dpa_per_cell_cellpar"])
    # ZSLGenerator(film, substrate): wafer A = SiO2 (film), B = LiNbO3.
    vf = _surface_vectors(build_slab(sio2, (1, 0, 0)))
    vs = _surface_vectors(build_slab(linbo3, (0, 0, 1)))
    best, best_cost = None, 1e9
    for max_area in (500, 700):
        for tol in (0.03, 0.06):
            for m in ZSLGenerator(max_area=max_area, max_length_tol=tol,
                                  max_angle_tol=tol)(vf, vs):
                w = _worst_axis_strain(m.substrate_sl_vectors,
                                       m.film_sl_vectors)
                cost = (abs(m.match_area - TARGET_AREA)
                        + 1000 * abs(w - TARGET_WORST))
                if cost < best_cost:
                    best_cost, best = cost, m
    film_cell = np.asarray(best.film_sl_vectors, float)         # SiO2
    substrate_cell = np.asarray(best.substrate_sl_vectors, float)  # LiNbO3
    worst = _worst_axis_strain(substrate_cell, film_cell)
    shared = even_split_shared_cell(substrate_cell, film_cell)
    la, lb = np.linalg.norm(shared[0]), np.linalg.norm(shared[1])
    rot = _polar_rotation(substrate_cell[:, :2]
                          @ np.linalg.inv(film_cell[:, :2]))
    print(f"chosen cell: area {best.match_area:.1f} | worst-axis "
          f"{100*worst:.2f}% | aspect {max(la, lb)/min(la, lb):.2f} | "
          f"twist {abs(math.degrees(math.atan2(rot[1,0], rot[0,0]))):.1f}")

    half_a = build_standalone_half(
        sio2, (1, 0, 0), "SiO2", (), min_slab_thickness=25.0,
        min_vacuum=20.0, matched_cell=film_cell, shared_cell=shared)
    half_b = build_standalone_half(
        linbo3, (0, 0, 1), "LiNbO3", (), min_slab_thickness=25.0,
        min_vacuum=20.0, matched_cell=substrate_cell, shared_cell=shared)
    for tag, h in (("SiO2(A)", half_a), ("LiNbO3(B)", half_b)):
        cell = np.asarray(h.atoms.get_cell())
        print(f"  {tag}: {len(h.atoms)} atoms | a={np.linalg.norm(cell[0]):.2f}"
              f" b={np.linalg.norm(cell[1]):.2f} A")

    half_a.atoms.set_tags([WAFER_A_TAG] * len(half_a.atoms))
    half_b.atoms.set_tags([WAFER_B_TAG] * len(half_b.atoms))
    match = SurfaceMatch(residual_strain=worst, worst_axis_strain=worst,
                         match_area=float(best.match_area), is_identity=False)
    built = assemble_amorphized_pair(
        half_a.atoms, half_b.atoms, match, bond_cutoff=3.2,
        initial_gap=8.0, clash_floor=1.5,
        wafer_a_species=frozenset({"O", "Si"}),
        wafer_b_species=frozenset({"Li", "Nb", "O"}))
    data_file = os.path.join(work, "pristine_pair.data")
    write_lammps_data(built, data_file)
    gap = built.wafer_b_z_range[0] - built.wafer_a_z_range[1]
    print(f"PRISTINE pair: {len(built.atoms)} atoms | gap {gap:.2f} A | "
          f"type_map {built.type_map}")
    print("T20 PREPARE OK ->", data_file)


if __name__ == "__main__":
    main()
