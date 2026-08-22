#!/usr/bin/env python
"""T-19 part 1 (sabsim env): assemble the oxide pair WITH per-wafer species.

Like the T-15 assembler, but records each wafer's DECLARED material species
on the pair so part 2 can run the REAL §3.5 gate per wafer (item 6): wafer
A is SiO2 -> {O, Si}, wafer B is LiNbO3 -> {Li, Nb, O}. The gate keys each
wafer's activation reference by ITS set (O_Si.toml / Li_Nb_O.toml), not the
pair's global type map. The light namespace handed to part 2 therefore
carries wafer_a_species / wafer_b_species (the two fields gate_healed_
surfaces reads).

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
# Each wafer's DECLARED material species -- what the §3.5 gate keys on.
SIO2_SPECIES = frozenset({"O", "Si"})
LINBO3_SPECIES = frozenset({"Li", "Nb", "O"})


def _widen_gap(built, target=8.0):
    """Slide wafer B up to a clean ``target`` closest-atom gap."""
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
    """Short press hold + one fast pull rung -- a first driver run."""
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
        clash_floor=1.8,
        wafer_a_species=SIO2_SPECIES, wafer_b_species=LINBO3_SPECIES)
    built = _widen_gap(built, target=8.0)
    built = dataclasses.replace(built, type_map=dict(PRAKASH_TYPE_MAP))
    gap = built.wafer_b_z_range[0] - built.wafer_a_z_range[1]
    print(f"assembled pair: {len(built.atoms)} atoms | gap {gap:.2f} A")
    print(f"wafer A species {sorted(built.wafer_a_species)} | "
          f"wafer B species {sorted(built.wafer_b_species)}")

    data_file = os.path.join(work_directory, "oxide_pair.data")
    write_lammps_data(built, data_file)

    member = _trim(load_and_validate_study(template).members[1])

    # The light namespace part 2 unpickles with ASE + stdlib only -- now
    # carrying the per-wafer species the real gate reads.
    light_built = SimpleNamespace(
        atoms=built.atoms, interface_z=built.interface_z,
        wafer_a_z_range=built.wafer_a_z_range,
        wafer_b_z_range=built.wafer_b_z_range, type_map=built.type_map,
        wafer_a_species=built.wafer_a_species,
        wafer_b_species=built.wafer_b_species,
        match=None, initial_gap_adjustment=0.0)
    with open(os.path.join(work_directory, "built.pkl"), "wb") as handle:
        pickle.dump(light_built, handle)
    with open(os.path.join(work_directory, "member.pkl"), "wb") as handle:
        pickle.dump(member, handle)
    print("T19 ASSEMBLE OK ->", data_file)


if __name__ == "__main__":
    main()
