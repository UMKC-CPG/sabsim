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

import numpy as np
import pytest
from ase.io import read as ase_read

from sabsim.structure.slab_builder import (
    WAFER_A_TAG,
    WAFER_B_TAG,
    _residual_strain,
    _worst_axis_strain,
    assemble_facing_pair,
    build_facing_pair,
    build_slab,
    bulk_atoms,
    bulk_type_map,
    even_split_shared_cell,
    load_crystal,
    match_surfaces,
    rescale_crystal_to_cell,
    tile_slab_to_shared_cell,
    write_bulk_data,
    write_lammps_data,
)

# The Si diamond CIF shipped as reference data — the authoritative
# structure a wafer names (DESIGN.md §1.2), located beside the package.
# The shipped crystals live in the materials catalog (DESIGN §10.11),
# one folder per entry beside the recipe that describes them.
from sabsim.catalog import lookup_entry

_SI_CIF = str(lookup_entry("si_diamond_100").cif)

_SI_100 = (1, 0, 0)


def test_rescale_crystal_to_cell_applies_the_model_cell():
    """The crystal takes the derived cell; fractional coords ride along."""
    crystal = load_crystal(_SI_CIF)
    # A 1% isotropic expansion plus a small xy tilt — a non-cubic target,
    # to prove the full 3x3 is applied, not a cubic scalar.
    target = np.array(crystal.lattice.matrix) * 1.01
    target[1][0] += 0.05
    rescaled = rescale_crystal_to_cell(crystal, target)

    assert np.allclose(rescaled.lattice.matrix, target)
    # The basis rides along untouched (fractional coords, species, count).
    assert np.allclose(rescaled.frac_coords, crystal.frac_coords)
    assert rescaled.species == crystal.species


def test_bulk_type_map_matches_the_written_block(tmp_path):
    """bulk_type_map (all ranks) equals write_bulk_data's map (rank 0)."""
    crystal = load_crystal(_SI_CIF)
    path = str(tmp_path / "bulk.data")
    assert bulk_type_map(crystal, 2) == write_bulk_data(crystal, 2, path)


def _data_file(name: str) -> str:
    """A shipped crystal file, found through the materials catalog."""
    for entry in (lookup_entry("si_diamond_100"),
                  lookup_entry("sio2_quartz_001")):
        if entry.cif.name == name:
            return str(entry.cif)
    raise AssertionError(f"no catalog entry ships {name}")


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


def test_worst_axis_strain_is_the_honest_metric_the_scalar_hides():
    """A short-axis strain the aggregate scalar buries shows up per-axis.

    The rotation-invariant `residual_strain` divides by the longest edge
    squared, so a big strain on a SHORT ribbon axis reads tiny; the
    per-axis `_worst_axis_strain` reports the true stretch each slab feels
    on the even-split cell. A ~5x50 ribbon whose short axis is stretched
    2.5% reads ~0.05% by the scalar but ~1.25% per-axis (half the misfit,
    the even split) -- an order of magnitude larger.
    """
    substrate = np.array([[5.0, 0.0], [0.0, 50.0]])
    film = np.array([[5.125, 0.0], [0.0, 50.0]])
    scalar = _residual_strain(substrate, film)
    worst = _worst_axis_strain(substrate, film)
    assert scalar < 0.001                    # the short axis is buried
    assert abs(worst - 0.0125) < 1.0e-3      # the honest per-axis stretch
    assert worst > 10.0 * scalar             # far larger than the scalar
    # An identity match feels nothing on either axis.
    assert _worst_axis_strain(substrate, substrate) < 1.0e-9


def test_match_surfaces_records_the_worst_axis_strain():
    """match_surfaces populates the honest per-axis strain (§2.4).

    For the Si/Si identity the honest metric is ~0 like the scalar; the
    field exists so a real mismatch carries the true per-direction ceiling
    the scalar would otherwise hide.
    """
    slab = build_slab(load_crystal(_SI_CIF), _SI_100)
    match = match_surfaces(slab, slab)
    assert match.worst_axis_strain is not None
    assert match.worst_axis_strain < 1.0e-6


def test_match_carries_the_tiling_geometry_for_a_mismatch():
    """A real mismatch keeps each slab's tiling matrix + supercell (§2.3).

    The strained tiling (§2.4) needs the whole-number tilings and both
    supercells the Zur-McGill search produces; the match must carry them,
    not just the scalar strain. Built from Si against a stretched Si so the
    surfaces genuinely differ, without needing a second material's CIF.
    """
    si = load_crystal(_SI_CIF)
    stretched = rescale_crystal_to_cell(
        si, np.array(si.lattice.matrix) * 1.1)
    slab_a = build_slab(si, _SI_100)
    slab_b = build_slab(stretched, _SI_100)

    match = match_surfaces(
        slab_a, slab_b, max_area=400.0, misfit_tolerance=0.15)

    assert not match.is_identity
    for tiling in (match.substrate_tiling, match.film_tiling):
        assert tiling is not None
        assert all(isinstance(n, int) for row in tiling for n in row)
    assert match.substrate_cell is not None
    assert match.film_cell is not None


def test_even_split_is_the_plain_midpoint_without_a_twist():
    """With no twist the shared cell is just the two cells' midpoint (§2.4)."""
    substrate = np.array([[5.5, 0.0], [0.0, 5.5]])
    film = np.array([[5.0, 0.0], [0.0, 5.0]])       # aligned, only stretched
    shared = even_split_shared_cell(substrate, film)
    assert np.allclose(shared, np.array([[5.25, 0.0], [0.0, 5.25]]))


def test_even_split_undoes_the_twist_before_averaging():
    """A rotated film is de-rotated first, so the split stays EVEN (§2.4).

    If the twist were not removed, averaging a rotated cell with an
    unrotated one would leak orientation into the size. The check: the
    point reflected across the shared cell from the substrate must be a
    RIGID rotation of the film cell — same metric tensor (dot products),
    which a pure rotation leaves unchanged. That is exactly "each slab is
    the same distance from the shared cell", i.e. the split is even.
    """
    substrate = np.array([[5.5, 0.0], [0.0, 5.5]])
    angle = np.deg2rad(9.0)
    rotation = np.array([[np.cos(angle), -np.sin(angle)],
                         [np.sin(angle), np.cos(angle)]])
    film = (rotation @ (np.array([[5.0, 0.0], [0.0, 5.0]]).T)).T

    shared = even_split_shared_cell(substrate, film)

    # Reflect the substrate across the shared cell to recover the film's
    # aligned image, and compare metric tensors (rotation-invariant).
    film_aligned = 2.0 * shared - substrate
    assert np.allclose(
        film_aligned @ film_aligned.T, film @ film.T, atol=1.0e-9)


def _rotated(cell, degrees):
    """Each ROW of ``cell`` rotated counterclockwise by ``degrees``."""
    angle = np.deg2rad(degrees)
    rotation = np.array([[np.cos(angle), -np.sin(angle)],
                         [np.sin(angle), np.cos(angle)]])
    return np.asarray(cell) @ rotation.T


def _edge_lengths(cell):
    return np.linalg.norm(np.asarray(cell)[:, :2], axis=1)


def test_even_split_of_a_twisted_cell_is_the_midpoint_of_the_lengths():
    """The shared cell itself, not only rotation-blind quantities.

    DESIGN §2.4, corrected 2026-09-28 (LEDGER T-45). The rotation used
    to be taken from the wrong matrix product, so the film was turned
    AWAY from the substrate and the shared cell came out short. The
    older test compared metric tensors, which a rotation in either
    direction leaves unchanged, and so could not see it. Here the
    edges are checked: a square film twisted 9 degrees, and the long
    thin cell of silicon (100) on quartz (001) twisted 26.57 degrees.
    """
    substrate = np.array([[5.5, 0.0], [0.0, 5.5]])
    film = _rotated([[5.0, 0.0], [0.0, 5.0]], 9.0)
    shared = even_split_shared_cell(substrate, film)
    assert np.allclose(shared, [[5.25, 0.0], [0.0, 5.25]], atol=1.0e-9)

    quartz = np.array([[8.510, 0.0], [0.0, 34.391]])
    silicon = _rotated([[8.586, 0.0], [0.0, 34.342]], 26.57)
    shared = even_split_shared_cell(quartz, silicon)
    assert np.allclose(_edge_lengths(shared), [8.548, 34.3665], atol=1e-3)
    # Each crystal is strained by half the misfit on each axis, under
    # half a percent — not the 20 percent the wrong product gave.
    assert _worst_axis_strain(quartz, silicon) < 0.005


def test_a_mirror_image_pair_is_refused_not_forced():
    """A clockwise film against a counterclockwise substrate (§2.3)."""
    substrate = np.array([[8.510, 0.0], [0.0, 34.391]])
    mirrored = np.array([[8.586, 0.0], [0.0, -34.342]])
    with pytest.raises(ValueError, match="opposite rotational order"):
        even_split_shared_cell(substrate, mirrored)


def test_the_film_is_described_so_it_fits_the_substrate():
    """Reversed, exchanged or mirrored edges are put right (§2.3)."""
    from sabsim.structure.slab_builder import _best_film_description
    substrate = np.array([[8.510, 0.0], [0.0, 34.391]])
    tiling = np.array([[1.0, 2.0], [0.0, 10.0]])
    for film in ([[8.586, 0.0], [0.0, -34.342]],       # mirrored
                 [[0.0, 34.342], [-8.586, 0.0]],       # edges exchanged
                 [[-8.586, 0.0], [0.0, -34.342]]):     # both reversed
        described, new_tiling, strain = _best_film_description(
            substrate, _rotated(film, 26.57), tiling)
        assert strain < 0.005
        assert np.linalg.det(described[:, :2]) > 0.0
        assert abs(abs(np.linalg.det(new_tiling)) - 10.0) < 1.0e-9


def test_silicon_on_quartz_builds_a_sound_cell():
    """The pair of LEDGER T-45, end to end through the geometry.

    Twenty silicon surface cells on fourteen quartz ones: a shared cell
    of about 8.55 by 34.37 A, each crystal strained under half a
    percent, and no two atoms closer than a bond length after tiling —
    where the defective build put 466,578 atoms in a sliver.
    """
    from scipy.spatial import cKDTree
    silicon = build_slab(load_crystal(_SI_CIF), _SI_100)
    quartz = build_slab(
        load_crystal(_data_file("sio2_alpha_quartz.cif")), (0, 0, 1))
    match = match_surfaces(
        silicon, quartz, max_area=400.0, misfit_tolerance=0.02)
    assert match.worst_axis_strain < 0.005
    assert abs(match.match_area - 294.8) < 1.0
    shared = even_split_shared_cell(match.substrate_cell, match.film_cell)
    assert np.allclose(_edge_lengths(shared), [8.548, 34.367], atol=0.01)
    for slab, cell, copies, bond in ((silicon, match.film_cell, 20, 2.2),
                                     (quartz, match.substrate_cell, 14,
                                      1.5)):
        tiled = tile_slab_to_shared_cell(slab, cell, shared)
        assert len(tiled) == copies * len(slab)
        positions = tiled.get_positions()
        nearest = cKDTree(positions).query(positions, k=2)[0][:, 1]
        assert nearest.min() > bond


def test_the_misfit_tolerance_is_held_on_the_built_cell(monkeypatch):
    """A candidate whose BUILT strain is over the tolerance is rejected.

    pymatgen's own filter compares the two cells' edge lengths, so a
    candidate it passes strains each crystal by about half the
    tolerance when soundly built. The check on the built cell exists
    for the candidates that cannot be built soundly; here every
    candidate is made to report 3 percent, and the refusal names it.
    """
    import sabsim.structure.slab_builder as builder
    original = builder._best_film_description

    def three_percent(substrate_cell, film_cell, film_tiling):
        described, tiling, _ = original(
            substrate_cell, film_cell, film_tiling)
        return described, tiling, 0.03

    monkeypatch.setattr(builder, "_best_film_description", three_percent)
    silicon = build_slab(load_crystal(_SI_CIF), _SI_100)
    with pytest.raises(ValueError, match=r"needs 3\.00 %"):
        match_surfaces(
            silicon, silicon, max_area=400.0, misfit_tolerance=0.02)


def test_even_split_uses_true_lengths_of_out_of_plane_vectors():
    """A film cell tilted out of xy must not be shortened by projection.

    Regression for the SiO2(100)/LiNbO3(001) build (T-17): SiO2's short
    supercell vector points ~30 deg out of the surface plane, so its TRUE
    length (4.869) differs from its bare xy-projection (4.217). The earlier
    even split dropped z and averaged the PROJECTION against LiNbO3's
    in-plane 5.119, landing the shared short edge at 4.668 -- below BOTH
    materials -- which over-compressed the build to ~24 GPa and amorphized
    the crystal before any impact. The shared short edge must instead be the
    midpoint of the true lengths, ~4.994.
    """
    substrate = np.array([[5.119, 0.0, 0.0], [0.0, 44.335, 0.0]])
    # SiO2 short vector: xy-length 4.217, z = -2.435 -> true length 4.869.
    film = np.array([[4.217, 0.0, -2.435], [0.0, 44.129, 0.0]])

    shared = even_split_shared_cell(substrate, film)

    short_edge = float(np.linalg.norm(shared[0]))
    # The midpoint of the TRUE lengths (4.869, 5.119), not the projected
    # average (4.217, 5.119) = 4.668 that caused the bug.
    assert abs(short_edge - 4.994) < 0.02, short_edge


def test_tile_slab_builds_supercell_matching_matched_cell():
    """The tiler builds the supercell that REPRODUCES the matched vectors.

    Regression for the T-17 oxide build: feeding the raw Zur-McGill tiling to
    ASE's ``make_supercell`` built a long 1xN strip (e.g. 189 Å) that, forced
    onto the compact shared cell, sheared atoms into ~0.8 Å overlaps. The
    tiler now derives the supercell transform from the matched CELL VECTORS
    (pymatgen's ``get_2d_transform``) and must reproduce them exactly — an
    oblique 2-D supercell stays that cell, never a strip.
    """
    from ase import Atoms
    hexagonal = [[5.119, 0.0, 0.0], [-2.56, 4.434, 0.0], [0.0, 0.0, 30.0]]
    slab = Atoms("Li", positions=[[0.0, 0.0, 15.0]], cell=hexagonal,
                 pbc=[True, True, False])
    # A genuine 2-D (off-diagonal) supercell of the hexagonal surface cell —
    # the shape the old make_supercell(tiling) path failed to reproduce.
    transform = np.array([[2, 1], [1, 3]])          # det 5, oblique
    primitive = np.asarray(slab.get_cell())[:2, :2]
    matched = transform @ primitive                 # the matched vectors
    # Strain-free (shared == matched) isolates the supercell build: the
    # transform must reproduce the matched cell, not a strip.
    tiled = tile_slab_to_shared_cell(slab, matched, matched)

    assert len(tiled) == 5                           # det(transform) atoms
    assert np.allclose(np.asarray(tiled.get_cell())[:2, :2], matched)


def test_tile_slab_to_shared_cell_tiles_and_strains():
    """The slab is built as the supercell matching the shared cell, on it."""
    slab = build_slab(load_crystal(_SI_CIF), _SI_100)
    # The slab's own 2x2 matched supercell vectors (det-4 atom count).
    matched = 2.0 * np.asarray(slab.get_cell())[:2, :2]
    shared = np.array([[7.9, 0.1], [-0.1, 7.9]])
    z_before = slab.get_positions()[:, 2]

    tiled = tile_slab_to_shared_cell(slab, matched, shared)

    # The whole-number matrix sets the atom count by its determinant.
    assert len(tiled) == len(slab) * 4
    # The in-plane cell is exactly the shared one; the slab is commensurate.
    assert np.allclose(np.asarray(tiled.get_cell())[:2, :2], shared)
    # Straining is purely in-plane: the z (vacuum) vector is untouched, and
    # so is the span of atom z-heights (scale_atoms holds fractional coords).
    assert np.allclose(
        np.asarray(tiled.get_cell())[2], np.asarray(slab.get_cell())[2])
    span_before = z_before.max() - z_before.min()
    z_after = tiled.get_positions()[:, 2]
    assert abs((z_after.max() - z_after.min()) - span_before) < 1.0e-9


def test_mismatched_halves_emerge_commensurate():
    """Matched, tiled, and strained, two mismatched slabs share one cell.

    The whole point of the strained tiling (§2.4): a genuine lattice
    mismatch is carried into ONE shared cell, so the assembly's
    commensurability assertion (§2.6) accepts the pair. Slab A is the
    matcher's 'film', slab B its 'substrate', so each takes its own matched
    supercell vectors.
    """
    si = load_crystal(_SI_CIF)
    stretched = rescale_crystal_to_cell(
        si, np.array(si.lattice.matrix) * 1.1)
    slab_a = build_slab(si, _SI_100)
    slab_b = build_slab(stretched, _SI_100)
    match = match_surfaces(
        slab_a, slab_b, max_area=400.0, misfit_tolerance=0.15)

    shared = even_split_shared_cell(match.substrate_cell, match.film_cell)
    tiled_a = tile_slab_to_shared_cell(slab_a, match.film_cell, shared)
    tiled_b = tile_slab_to_shared_cell(slab_b, match.substrate_cell, shared)

    cell_a = np.asarray(tiled_a.get_cell())[:2, :2]
    cell_b = np.asarray(tiled_b.get_cell())[:2, :2]
    assert np.allclose(cell_a, cell_b, atol=1.0e-6)


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


# ---------------------------------------------------------------------
# Oxidation states are stripped at LOAD, so nothing downstream can see a
# charge label where it expects a chemical symbol.
# ---------------------------------------------------------------------

def test_load_crystal_strips_oxidation_states():
    """A CIF labelling sites by ion still yields bare element symbols.

    The shipped alpha-quartz file writes ``Si4+`` and ``O2-`` in its
    ``_atom_site_type_symbol`` column. Read literally, a site's species
    stringifies to "O2-", which matches no potential-registry entry, no
    LAMMPS type-map key, and no reference-data filename — all of which
    are keyed on the element. Stripping at load is what makes every
    consumer downstream immune, rather than each having to remember.
    """
    quartz = load_crystal(_data_file("sio2_alpha_quartz.cif"))

    # Straight from the composition, and per-site: both bare.
    assert {element.symbol
            for element in quartz.composition.elements} == {"O", "Si"}
    assert {str(element)
            for element in quartz.composition.elements} == {"O", "Si"}
    assert {str(site.specie) for site in quartz} == {"O", "Si"}


def test_charge_labels_do_not_reach_the_type_map():
    """A slab cut from an ion-labelled CIF maps bare elements to types.

    The end-to-end consequence of the strip above: a type map carrying
    "O2-" would be written into a LAMMPS data file as an element name
    ASE cannot resolve, which is exactly how this surfaced.
    """
    quartz = load_crystal(_data_file("sio2_alpha_quartz.cif"))
    slab = build_slab(quartz, (0, 0, 1),
                      min_slab_thickness=6.0, min_vacuum=8.0)
    assert set(slab.get_chemical_symbols()) == {"O", "Si"}


def test_data_writer_ignores_a_stale_lammps_type_array(tmp_path):
    """The chemical symbols, never a leftover dump ``type`` array, decide
    an atom's LAMMPS type (LEDGER T-42: ASE 3.29 prefers the stale
    array to ``specorder``, so a melt-quench frame numbered {O: 1,
    Si: 2} by its MD stage was re-written under {Si: 1, O: 2} with
    every atom's species swapped on disk)."""
    from ase import Atoms
    from sabsim.structure.slab_builder import _write_atoms_as_lammps_data
    frame = Atoms("OOSi", positions=[[0, 0, 0], [1.6, 0, 0], [3, 0, 0]],
                  cell=[6.0, 6.0, 6.0], pbc=True)
    # What a dump readback leaves behind: the MD stage's own numbering.
    frame.arrays["type"] = np.array([1, 1, 2])
    path = tmp_path / "frame.data"
    _write_atoms_as_lammps_data(frame, {"Si": 1, "O": 2}, str(path))
    lines = path.read_text().splitlines()
    atom_lines = [line.split() for line in lines[-3:]]
    written_types = [int(fields[1]) for fields in atom_lines]
    # O, O, Si under {Si: 1, O: 2} must read 2, 2, 1 — the map's order.
    assert written_types == [2, 2, 1]
    masses = [line for line in lines if line.strip().endswith("# Si")]
    assert masses and masses[0].split()[0] == "1"
    # The caller's structure is untouched (a copy was written).
    assert "type" in frame.arrays


# ---------------------------------------------------------------------
# The sign of the face is honoured (DESIGN.md §2.5, 2026-09-28): the
# face names the slab's TOP, so (001) and (00-1) are the two sides of
# the same cuts. Wurtzite GaN is the test crystal because its two
# sides differ: every bilayer points the same way along c.
# ---------------------------------------------------------------------

def _wurtzite_gallium_nitride():
    """Wurtzite GaN, written out so the test needs no catalog entry.

    Each gallium has one nitrogen straight above it along +c, 0.378 of
    the cell height away: the VERTICAL bond, which points from gallium
    to nitrogen along +c throughout the crystal.
    """
    from pymatgen.core import Lattice, Structure
    return Structure(
        Lattice.hexagonal(3.1972, 5.207),
        ["Ga", "Ga", "N", "N"],
        [[1 / 3, 2 / 3, 0.091], [2 / 3, 1 / 3, 0.591],
         [1 / 3, 2 / 3, 0.469], [2 / 3, 1 / 3, 0.969]])


def _top_and_bottom_species(slab):
    """The species of a slab's highest and lowest atoms along its normal."""
    from sabsim.structure.slab_builder import slab_top_normal
    heights = slab.get_positions() @ slab_top_normal(slab.get_cell())
    symbols = slab.get_chemical_symbols()
    return symbols[int(np.argmax(heights))], symbols[int(np.argmin(heights))]


def _vertical_bond_direction(slab):
    """+1 if nitrogen sits straight ABOVE its gallium, -1 if below.

    Looks at one gallium deep inside the slab and finds the nitrogen
    that shares its in-plane position at one bond length (1.97 A).
    """
    positions = slab.get_positions()
    symbols = np.array(slab.get_chemical_symbols())
    heights = positions[:, 2]
    middle = 0.5 * (heights.max() + heights.min())
    galliums = np.where(symbols == "Ga")[0]
    gallium = galliums[np.argmin(np.abs(heights[galliums] - middle))]
    for nitrogen in np.where(symbols == "N")[0]:
        offset = slab.get_distance(gallium, nitrogen, mic=True,
                                   vector=True)
        if np.hypot(offset[0], offset[1]) < 0.05 and (
                abs(abs(offset[2]) - 1.97) < 0.05):
            return 1 if offset[2] > 0.0 else -1
    raise AssertionError("no vertical Ga-N bond found")


def test_opposite_faces_are_the_two_sides_of_the_same_cut():
    from sabsim.structure.slab_builder import slab_terminations
    crystal = _wurtzite_gallium_nitride()
    up = slab_terminations(crystal, (0, 0, 1), 10.0, 12.0)
    down = slab_terminations(crystal, (0, 0, -1), 10.0, 12.0)
    assert len(up) == len(down) == 2
    for slab_up, slab_down in zip(up, down):
        top, bottom = _top_and_bottom_species(slab_up)
        assert top != bottom                      # the two sides differ
        # The (00-1) slab's top is the (001) slab's bottom, and back.
        assert _top_and_bottom_species(slab_down) == (bottom, top)
        # In the crystal the vertical bond runs Ga -> N along +c: up
        # out of the (001) top, down into the (00-1) one.
        assert _vertical_bond_direction(slab_up) == 1
        assert _vertical_bond_direction(slab_down) == -1
        # Same cut, same cell: only turned over.
        assert len(slab_down) == len(slab_up)
        assert slab_down.get_volume() == pytest.approx(
            slab_up.get_volume())
        assert np.linalg.det(np.array(slab_down.get_cell())) > 0.0
        assert np.allclose(np.array(slab_down.get_cell())[2],
                           np.array(slab_up.get_cell())[2])


def test_the_sense_of_a_cut_is_read_from_the_tools_own_record():
    """The cleaving tool hands back the SAME slab for (001) and
    (00-1); its record of the slab cell says which side is up, and
    the two faces read opposite senses from it."""
    from pymatgen.core.surface import SlabGenerator
    from sabsim.structure.slab_builder import face_sense
    crystal = _wurtzite_gallium_nitride()
    cuts = {
        face: SlabGenerator(crystal, face, 10.0, 12.0,
                            center_slab=True).get_slabs()[0]
        for face in ((0, 0, 1), (0, 0, -1))}
    assert np.allclose(cuts[(0, 0, 1)].cart_coords,
                       cuts[(0, 0, -1)].cart_coords)
    assert face_sense(crystal, cuts[(0, 0, 1)], (0, 0, 1)) == 1
    assert face_sense(crystal, cuts[(0, 0, -1)], (0, 0, -1)) == -1


def test_the_shipped_faces_are_built_exactly_as_before():
    """Si (100) and quartz (001) come out of the cleaving tool the
    right way up, so honouring the sign moves no atom of theirs."""
    from pymatgen.core.surface import SlabGenerator
    from pymatgen.io.ase import AseAtomsAdaptor
    for label, face in (("si_diamond_100", (1, 0, 0)),
                        ("sio2_quartz_001", (0, 0, 1))):
        crystal = load_crystal(lookup_entry(label).cif)
        as_cut = AseAtomsAdaptor.get_atoms(SlabGenerator(
            crystal, face, 10.0, 12.0, center_slab=True).get_slabs()[0])
        built = build_slab(crystal, face, 10.0, 12.0)
        assert np.array_equal(built.get_positions(),
                              as_cut.get_positions())
        assert np.array_equal(np.array(built.get_cell()),
                              np.array(as_cut.get_cell()))


def test_turning_a_slab_over_is_a_rotation_not_a_mirror():
    """A handed cluster keeps its hand; turning twice restores it."""
    from ase import Atoms
    from sabsim.structure.slab_builder import turn_slab_over
    # Four atoms near the middle of a skewed cell, none in a plane with
    # the others: the signed volume they span tells left from right.
    slab = Atoms(
        "SiOOO",
        positions=[[2.0, 2.0, 15.0], [3.0, 2.2, 15.3],
                   [2.1, 3.1, 15.6], [2.4, 2.3, 16.4]],
        cell=[[6.0, 0.0, 0.0], [-3.0, 5.2, 0.0], [0.0, 0.0, 30.0]],
        pbc=True)

    def signed_volume(atoms):
        first = atoms.get_distance(0, 1, mic=True, vector=True)
        second = atoms.get_distance(0, 2, mic=True, vector=True)
        third = atoms.get_distance(0, 3, mic=True, vector=True)
        return float(np.dot(np.cross(first, second), third))

    turned = turn_slab_over(slab)
    assert signed_volume(turned) == pytest.approx(signed_volume(slab))
    assert np.linalg.det(np.array(turned.get_cell())) > 0.0
    assert np.allclose(np.array(turned.get_cell())[2], [0.0, 0.0, 30.0])
    # What was highest is now lowest.
    assert np.argmax(turned.get_positions()[:, 2]) == 0
    assert np.argmin(slab.get_positions()[:, 2]) == 0
    twice = turn_slab_over(turned)
    assert np.allclose(twice.get_positions(), slab.get_positions())


def test_a_slab_that_does_not_match_its_record_is_refused():
    from pymatgen.core.surface import SlabGenerator
    from sabsim.structure.slab_builder import face_sense
    crystal = _wurtzite_gallium_nitride()
    cut = SlabGenerator(crystal, (0, 0, 1), 10.0, 12.0,
                        center_slab=True).get_slabs()[0]
    # Asked about a face the slab was not cut for.
    with pytest.raises(ValueError, match="refused rather than oriented"):
        face_sense(crystal, cut, (1, 0, 0))
