"""Unit tests for the wave-0 Si structure builder (sabsim.structure).

These check the real geometry the driver will depend on: a diamond-(100)
slab of the expected atom count, a facing pair with the two wafers
separated by the requested gap and tagged by provenance, an open-z
periodic box, and a LAMMPS data file that round-trips the atom count.
"""

import os

from ase.io import read as ase_read

from sabsim.structure.si_slabs import (
    WAFER_A_TAG,
    WAFER_B_TAG,
    build_diamond_slab,
    stack_facing_pair,
    write_lammps_data,
)

# A conventional cubic diamond cell holds 8 atoms, so a block is
# 8 * nx * ny * nz atoms.
_ATOMS_PER_CONVENTIONAL_CELL = 8


def test_slab_has_expected_atom_count():
    """A 2x2x4 diamond block is 8*2*2*4 = 128 atoms."""
    slab = build_diamond_slab(
        cells_in_plane=(2, 2), cells_through_thickness=4)
    assert len(slab) == _ATOMS_PER_CONVENTIONAL_CELL * 2 * 2 * 4


def test_pair_stacks_both_wafers_with_a_gap():
    """The pair has both slabs, tagged, separated by the requested gap."""
    wafer_a = build_diamond_slab(cells_through_thickness=4)
    wafer_b = build_diamond_slab(cells_through_thickness=4)
    gap = 3.0
    pair = stack_facing_pair(wafer_a, wafer_b, gap=gap)

    # Every atom of both slabs is present and provenance-tagged.
    assert len(pair.atoms) == len(wafer_a) + len(wafer_b)
    tags = pair.atoms.get_tags()
    assert (tags == WAFER_A_TAG).sum() == len(wafer_a)
    assert (tags == WAFER_B_TAG).sum() == len(wafer_b)

    # The nearest approach between the two wafers is the gap (within a
    # small tolerance for where the atomic planes actually sit).
    positions = pair.atoms.get_positions()[:, 2]
    top_of_a = positions[tags == WAFER_A_TAG].max()
    bottom_of_b = positions[tags == WAFER_B_TAG].min()
    assert abs((bottom_of_b - top_of_a) - gap) < 1e-6


def test_pair_box_is_periodic_in_plane_open_in_z():
    """The facing pair is periodic in x,y and open along z (free ends)."""
    wafer_a = build_diamond_slab()
    wafer_b = build_diamond_slab()
    pair = stack_facing_pair(wafer_a, wafer_b, gap=3.0)
    assert tuple(pair.atoms.get_pbc()) == (True, True, False)
    # The interface plane sits between the two wafers.
    low_a, high_a = pair.wafer_a_z_range
    low_b, high_b = pair.wafer_b_z_range
    assert high_a <= pair.interface_z <= low_b


def test_type_map_is_silicon_only():
    """A Si/Si pair maps a single species to type id 1."""
    pair = stack_facing_pair(
        build_diamond_slab(), build_diamond_slab(), gap=3.0)
    assert pair.type_map == {"Si": 1}


def test_lammps_data_round_trips_atom_count(tmp_path):
    """Writing then reading the data file preserves every atom."""
    pair = stack_facing_pair(
        build_diamond_slab(), build_diamond_slab(), gap=3.0)
    data_path = os.path.join(tmp_path, "pair.data")
    write_lammps_data(pair, data_path)

    restored = ase_read(
        data_path, format="lammps-data", atom_style="atomic")
    assert len(restored) == len(pair.atoms)
