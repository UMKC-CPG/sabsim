"""Unit tests for the general slab / facing-pair builder (structure).

These exercise the real geometry the driver will depend on, driven from
a CIF the way any material will be: a slab cut from the Si diamond CIF,
the coincidence matcher returning its IDENTITY/null answer for Si/Si
(DESIGN.md §2.548), a facing pair separated by the requested gap and
tagged by provenance, an open-z periodic box, and a LAMMPS data file
that round-trips the atom count. Si/Si is the first input; the same code
serves any crystal, so nothing here is silicon-specific but the CIF.
"""

import os

from ase.io import read as ase_read

import sabsim.structure
from sabsim.structure.slab_builder import (
    WAFER_A_TAG,
    WAFER_B_TAG,
    assemble_facing_pair,
    build_facing_pair,
    build_slab,
    bulk_atoms,
    load_crystal,
    match_surfaces,
    write_bulk_data,
    write_lammps_data,
)

# The Si diamond CIF shipped as reference data — the authoritative
# structure a wafer names (DESIGN.md §1.2), located beside the package.
_SI_CIF = os.path.join(
    os.path.dirname(sabsim.structure.__file__), "data", "si_diamond.cif")

_SI_100 = (1, 0, 0)


def test_load_crystal_reads_the_cif():
    """The CIF loads to a silicon crystal (the authoritative structure)."""
    crystal = load_crystal(_SI_CIF)
    assert set(crystal.symbol_set) == {"Si"}


def test_build_slab_from_cif_is_silicon():
    """A (100) slab cut from the CIF is a non-empty silicon slab."""
    slab = build_slab(load_crystal(_SI_CIF), _SI_100)
    assert len(slab) > 0
    assert set(slab.get_chemical_symbols()) == {"Si"}


def test_sisi_match_is_the_identity_null_test():
    """Si/Si matches at zero strain — the coincidence matcher's null."""
    slab = build_slab(load_crystal(_SI_CIF), _SI_100)
    match = match_surfaces(slab, slab)
    assert match.is_identity
    assert match.residual_strain < 1.0e-6


def test_pair_stacks_both_wafers_with_a_gap():
    """The pair has both slabs, tagged, separated by the requested gap."""
    slab_a = build_slab(load_crystal(_SI_CIF), _SI_100)
    slab_b = build_slab(load_crystal(_SI_CIF), _SI_100)
    match = match_surfaces(slab_a, slab_b)
    gap = 3.0
    pair = assemble_facing_pair(slab_a, slab_b, match, gap=gap)

    # Every atom of both slabs is present and provenance-tagged.
    assert len(pair.atoms) == len(slab_a) + len(slab_b)
    tags = pair.atoms.get_tags()
    assert (tags == WAFER_A_TAG).sum() == len(slab_a)
    assert (tags == WAFER_B_TAG).sum() == len(slab_b)

    # The nearest approach between the two wafers is the requested gap.
    z = pair.atoms.get_positions()[:, 2]
    top_of_a = z[tags == WAFER_A_TAG].max()
    bottom_of_b = z[tags == WAFER_B_TAG].min()
    assert abs((bottom_of_b - top_of_a) - gap) < 1.0e-6


def test_pair_box_is_periodic_in_plane_open_in_z():
    """The facing pair is periodic in x,y and open along z (free ends)."""
    pair = build_facing_pair(_SI_CIF, _SI_100, _SI_CIF, _SI_100, gap=3.0)
    assert tuple(pair.atoms.get_pbc()) == (True, True, False)
    # The interface plane sits between the two wafers.
    _, high_a = pair.wafer_a_z_range
    low_b, _ = pair.wafer_b_z_range
    assert high_a <= pair.interface_z <= low_b


def test_type_map_is_silicon_only():
    """A Si/Si pair maps a single species to type id 1."""
    pair = build_facing_pair(_SI_CIF, _SI_100, _SI_CIF, _SI_100, gap=3.0)
    assert pair.type_map == {"Si": 1}


def test_lammps_data_round_trips_atom_count(tmp_path):
    """Writing then reading the data file preserves every atom."""
    pair = build_facing_pair(_SI_CIF, _SI_100, _SI_CIF, _SI_100, gap=3.0)
    data_path = os.path.join(tmp_path, "pair.data")
    write_lammps_data(pair, data_path)

    restored = ase_read(
        data_path, format="lammps-data", atom_style="atomic")
    assert len(restored) == len(pair.atoms)


def test_bulk_block_replicates_the_conventional_cell():
    """A bulk block is the 8-atom Si cell replicated to N per axis."""
    block = bulk_atoms(load_crystal(_SI_CIF), cells_per_axis=2)
    # 8 atoms in the conventional diamond cell, times 2x2x2.
    assert len(block) == 8 * 2 * 2 * 2
    assert set(block.get_chemical_symbols()) == {"Si"}


def test_write_bulk_data_round_trips_and_maps_species(tmp_path):
    """The bulk data file writes every atom and returns its type map."""
    data_path = os.path.join(tmp_path, "bulk.data")
    type_map = write_bulk_data(load_crystal(_SI_CIF), 1, data_path)
    assert type_map == {"Si": 1}

    restored = ase_read(
        data_path, format="lammps-data", atom_style="atomic")
    assert len(restored) == 8
