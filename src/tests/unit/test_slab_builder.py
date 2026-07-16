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

import pytest
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
    """Writing then reading the data file preserves every atom.

    The species check is not decoration: a data file identifies its
    species ONLY through the ``Masses`` section, so a count-only
    assertion passes on a file whose atoms all read back as hydrogen
    (see :func:`_masses_in_data_file`).
    """
    pair = build_facing_pair(_SI_CIF, _SI_100, _SI_CIF, _SI_100, gap=3.0)
    data_path = os.path.join(tmp_path, "pair.data")
    write_lammps_data(pair, data_path)

    restored = ase_read(
        data_path, format="lammps-data", atom_style="atomic")
    assert len(restored) == len(pair.atoms)
    assert set(restored.get_chemical_symbols()) == {"Si"}


def test_bulk_block_replicates_the_conventional_cell():
    """A bulk block is the 8-atom Si cell replicated to N per axis."""
    block = bulk_atoms(load_crystal(_SI_CIF), cells_per_axis=2)
    # 8 atoms in the conventional diamond cell, times 2x2x2.
    assert len(block) == 8 * 2 * 2 * 2
    assert set(block.get_chemical_symbols()) == {"Si"}


def test_write_bulk_data_round_trips_and_maps_species(tmp_path):
    """The bulk data file writes every atom and returns its type map.

    Named "maps species", so it asserts the species actually survive the
    round trip rather than the atom count alone (see
    :func:`_masses_in_data_file` for why those differ).
    """
    data_path = os.path.join(tmp_path, "bulk.data")
    type_map = write_bulk_data(load_crystal(_SI_CIF), 1, data_path)
    assert type_map == {"Si": 1}

    restored = ase_read(
        data_path, format="lammps-data", atom_style="atomic")
    assert len(restored) == 8
    assert set(restored.get_chemical_symbols()) == {"Si"}


# The mass LAMMPS must find for silicon, in metal units (amu). Compared
# loosely: the writer's value carries the isotope-averaged tail
# (28.0849999...), and the point here is that a RIGHT mass is present,
# not that a particular number of digits round-trips.
_SILICON_MASS_AMU = 28.085


def _masses_in_data_file(data_path: str) -> dict:
    """Parse a LAMMPS data file's ``Masses`` section: type id -> mass.

    Parsed by hand rather than through ASE's reader on purpose. A LAMMPS
    data file carries no element symbols — ``Masses`` is what identifies
    each type's species, and the ``Atoms`` section names only bare type
    ids. So a file written without it does not fail loudly on read-back:
    ASE returns the right NUMBER of atoms with every species silently
    mislabelled (silicon comes back as hydrogen, type id read as an
    atomic number). A round-trip asserting only the atom count therefore
    passes over a file LAMMPS itself refuses to load. This reads the
    bytes as LAMMPS reads them.
    """
    with open(data_path) as data_file:
        lines = [line.strip() for line in data_file]
    if "Masses" not in lines:
        return {}
    masses = {}
    for line in lines[lines.index("Masses") + 1:]:
        if not line:
            continue
        if not line[0].isdigit():
            break              # the next section header ends the block
        fields = line.split()
        masses[int(fields[0])] = float(fields[1])
    return masses


def test_pair_data_file_carries_per_type_masses(tmp_path):
    """The pair data file sets every type's mass, or LAMMPS won't run.

    A regression guard for a real failure: ASE omits the ``Masses``
    section unless explicitly asked, and LAMMPS then rejects the file
    with "Not all per-type masses are set" before reaching any run.
    ``MockEngine`` never parses a data file, so the whole mock-side
    suite passed over a file the real engine would not load. This is
    where that gap closes — on the login node, with no LAMMPS present.
    """
    pair = build_facing_pair(_SI_CIF, _SI_100, _SI_CIF, _SI_100, gap=3.0)
    data_path = os.path.join(tmp_path, "pair.data")
    write_lammps_data(pair, data_path)

    masses = _masses_in_data_file(data_path)
    assert set(masses) == set(pair.type_map.values())
    assert masses[pair.type_map["Si"]] == pytest.approx(
        _SILICON_MASS_AMU, abs=1.0e-2)


def test_bulk_data_file_carries_per_type_masses(tmp_path):
    """The bulk data file sets its type's mass (same §2.2 requirement).

    The bulk block is the FIRST thing the force engine ever loads (the
    §2.2 lattice derivation), so a massless data file breaks the
    pipeline at its earliest engine contact.
    """
    data_path = os.path.join(tmp_path, "bulk.data")
    type_map = write_bulk_data(load_crystal(_SI_CIF), 1, data_path)

    masses = _masses_in_data_file(data_path)
    assert set(masses) == set(type_map.values())
    assert masses[type_map["Si"]] == pytest.approx(
        _SILICON_MASS_AMU, abs=1.0e-2)
