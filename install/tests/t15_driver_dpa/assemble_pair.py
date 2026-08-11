#!/usr/bin/env python
"""T-15 part 1 (sabsim env): assemble the SiO2/LiNbO3 pair for the driver.

Runs in the NORMAL sabsim env (has pymatgen/ASE). It assembles the two
matched amorphized oxide surfaces, remaps the type order to Prakash's
[Si,Li,Nb,O] (so `pair_coeff * * Si Li Nb O` is correct for the universal
DPA model too), forces a clean wide gap, and hands the result to part 2 —
which runs the REAL press/pull driver inside the deepmd BUNDLE's Python.

To keep part 2 pymatgen-free it does NOT pickle the pymatgen-defined
BuiltPair; it pickles a plain namespace with exactly the fields the driver
reads (atoms+tags, the per-wafer z-ranges, the interface plane, the type
map) plus the trimmed member. Part 2 unpickles those with only ASE +
stdlib.

Env: SIO2_SURFACE, LINBO3_SURFACE (activated .extxyz), MATCH_PKL, VALWORK,
SABSIM_TEMPLATE.
"""

import dataclasses
import os
import pickle
from types import SimpleNamespace

import numpy as np
from ase.io import read as ase_read

from sabsim.spec.loader import load_and_validate_study
from sabsim.spec.records import Quantity
from sabsim.structure.amorphized_assembly import assemble_amorphized_pair
from sabsim.structure.slab_builder import write_lammps_data
from sabsim.structure.wafer_tags import WAFER_A_TAG, WAFER_B_TAG

PRAKASH_TYPE_MAP = {"Si": 1, "Li": 2, "Nb": 3, "O": 4}


def _widen_gap(built, target=8.0):
    """Slide wafer B up to a clean ``target`` closest-atom gap (demo aid)."""
    atoms = built.atoms.copy()
    tags = np.asarray(atoms.get_tags())
    positions = atoms.get_positions()
    a_high = positions[tags == WAFER_A_TAG][:, 2].max()
    b_low = positions[tags == WAFER_B_TAG][:, 2].min()
    shift = target - (b_low - a_high)
    if shift > 0.0:
        positions[tags == WAFER_B_TAG, 2] += shift
        atoms.set_positions(positions)
        cell = np.asarray(atoms.get_cell())
        cell[2, 2] = positions[:, 2].max() + 15.0
        atoms.set_cell(cell)
    b_low = float(positions[tags == WAFER_B_TAG][:, 2].min())
    b_high = float(positions[tags == WAFER_B_TAG][:, 2].max())
    return dataclasses.replace(
        built, atoms=atoms, wafer_b_z_range=(b_low, b_high),
        interface_z=float(a_high + target / 2.0))


def _trim(member):
    """Short press hold + one fast pull rung — a first driver run."""
    ladder = member.numerical.pull_rate_ladder
    fastest = max(ladder, key=lambda rate: rate.value)
    numerical = dataclasses.replace(
        member.numerical, pull_rate_ladder=(fastest,))
    protocol = dataclasses.replace(
        member.protocol, press_duration=Quantity(10.0, "ps"))
    return dataclasses.replace(member, numerical=numerical, protocol=protocol)


def main() -> None:
    work_directory = os.environ["VALWORK"]
    os.makedirs(work_directory, exist_ok=True)
    template = os.environ["SABSIM_TEMPLATE"]

    half_a = ase_read(os.environ["SIO2_SURFACE"], format="extxyz")
    half_b = ase_read(os.environ["LINBO3_SURFACE"], format="extxyz")
    half_a.set_tags([WAFER_A_TAG] * len(half_a))
    half_b.set_tags([WAFER_B_TAG] * len(half_b))
    with open(os.environ["MATCH_PKL"], "rb") as handle:
        match = pickle.load(handle)["match"]

    built = assemble_amorphized_pair(
        half_a, half_b, match, bond_cutoff=2.8, initial_gap=10.0,
        clash_floor=1.8)
    built = _widen_gap(built, target=8.0)
    built = dataclasses.replace(built, type_map=dict(PRAKASH_TYPE_MAP))
    gap = built.wafer_b_z_range[0] - built.wafer_a_z_range[1]
    print(f"assembled pair: {len(built.atoms)} atoms | gap {gap:.2f} A")

    data_file = os.path.join(work_directory, "oxide_pair.data")
    write_lammps_data(built, data_file)

    member = _trim(load_and_validate_study(template).members[1])
    print("press_control:", member.protocol.press_control,
          "| pull ladder:", member.numerical.pull_rate_ladder)

    # A plain namespace with ONLY the fields the driver reads — so part 2
    # unpickles it with ASE + stdlib, no pymatgen BuiltPair class.
    light_built = SimpleNamespace(
        atoms=built.atoms, interface_z=built.interface_z,
        wafer_a_z_range=built.wafer_a_z_range,
        wafer_b_z_range=built.wafer_b_z_range, type_map=built.type_map,
        match=None, initial_gap_adjustment=0.0)
    with open(os.path.join(work_directory, "built.pkl"), "wb") as handle:
        pickle.dump(light_built, handle)
    with open(os.path.join(work_directory, "member.pkl"), "wb") as handle:
        pickle.dump(member, handle)
    print("wrote:", data_file, "+ built.pkl + member.pkl")
    print("T15 ASSEMBLE OK")


if __name__ == "__main__":
    main()
