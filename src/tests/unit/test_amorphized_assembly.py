"""Tests for the amorphized-half read-back and facing-pair assembly.

Every test here runs on a login node with no LAMMPS: the one
engine-facing routine (:func:`snapshot_amorphized_half`) is exercised
through ``MockEngine``'s scripted read-backs, and the geometry routines
(flip, ejecta removal, placement, clash relief) are pure ASE. Together
they cover the §2.6 assembly the sequencer will call between the two
activation stages and the press.
"""

from __future__ import annotations

import numpy as np
import pytest
from ase import Atoms

from sabsim.driver.engine import MockEngine
from sabsim.structure.amorphized_assembly import (
    _min_cross_distance,
    assemble_amorphized_pair,
    drop_disconnected,
    flip_in_z,
    snapshot_amorphized_half,
)
from sabsim.structure.slab_builder import (
    WAFER_A_TAG,
    WAFER_B_TAG,
    SurfaceMatch,
)

# An identity coincidence match — the Si/Si null case the assembly tests
# stack; the real matcher lands at wave 3 (§2.4), irrelevant here.
_IDENTITY_MATCH = SurfaceMatch(
    residual_strain=0.0, match_area=36.0, is_identity=True)


def _grid_slab(cell_side: float, tag: int | None = None) -> Atoms:
    """A small Si slab on a regular grid, periodic in the plane.

    Atoms sit on a 3x3 lateral grid (spacing 2 Å) across nine z-layers
    (spacing 1 Å), so nearest neighbours are 1-2 Å apart — a single
    connected cluster under a 2.5 Å bond cutoff, with a clean density
    profile along z for the dividing-surface search.
    """
    positions = [
        (x, y, z)
        for x in (0.0, 2.0, 4.0)
        for y in (0.0, 2.0, 4.0)
        for z in (0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0)]
    slab = Atoms(
        "Si" * len(positions), positions=positions,
        cell=[[cell_side, 0.0, 0.0], [0.0, cell_side, 0.0],
              [0.0, 0.0, 40.0]],
        pbc=(True, True, False))
    if tag is not None:
        slab.set_tags([tag] * len(slab))
    return slab


# ---------------------------------------------------------------------
# snapshot_amorphized_half — the engine -> ASE read-back.
# ---------------------------------------------------------------------

def test_snapshot_maps_types_to_species_and_tags():
    """The read-back rebuilds species from type ids and tags the wafer."""
    positions = np.array([
        [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    # Type ids 1->Si, 2->O; the frame is Si, O, Si.
    type_ids = np.array([1, 2, 1])
    box = np.diag([5.0, 5.0, 20.0])
    engine = MockEngine(
        box=box, positions=[positions], types=[type_ids])

    half = snapshot_amorphized_half(
        engine, type_map={"Si": 1, "O": 2}, wafer_tag=WAFER_A_TAG)

    assert half.get_chemical_symbols() == ["Si", "O", "Si"]
    assert list(half.get_tags()) == [WAFER_A_TAG] * 3
    assert np.allclose(half.get_cell(), box)
    assert list(half.get_pbc()) == [True, True, False]
    assert np.allclose(half.get_positions(), positions)


def test_snapshot_survives_projectile_deletion():
    """A composition the cascade changed reads back from type ids alone.

    The type map still carries the projectile (Ar), but no Ar atom
    survives the re-anneal, so the read-back is substrate-only — proving
    positions plus type ids reconstitute the half without the pre-cascade
    species list.
    """
    positions = np.zeros((2, 3))
    engine = MockEngine(
        box=np.eye(3), positions=[positions], types=[np.array([1, 2])])

    half = snapshot_amorphized_half(
        engine, type_map={"O": 1, "Si": 2, "Ar": 3},
        wafer_tag=WAFER_B_TAG)

    assert half.get_chemical_symbols() == ["O", "Si"]
    assert "Ar" not in half.get_chemical_symbols()


# ---------------------------------------------------------------------
# flip_in_z — mirror the top half so its activated face points down.
# ---------------------------------------------------------------------

def test_flip_sends_top_atom_to_the_bottom():
    """The highest atom becomes the lowest; x, y, species, cell survive."""
    atoms = Atoms(
        "SiOSi",
        positions=[[1.0, 2.0, 0.0], [1.0, 2.0, 5.0], [1.0, 2.0, 10.0]],
        cell=np.diag([8.0, 8.0, 30.0]), pbc=(True, True, False))

    flipped = flip_in_z(atoms)
    flipped_z = flipped.get_positions()[:, 2]

    # Mirror about the z-center (5.0): 0<->10, 5 fixed.
    assert flipped_z.tolist() == [10.0, 5.0, 0.0]
    assert np.allclose(flipped.get_positions()[:, :2],
                       atoms.get_positions()[:, :2])
    assert flipped.get_chemical_symbols() == ["Si", "O", "Si"]
    assert np.allclose(flipped.get_cell(), atoms.get_cell())


def test_flip_of_empty_half_is_a_noop():
    """An empty half has nothing to mirror and comes back empty."""
    assert len(flip_in_z(Atoms())) == 0


# ---------------------------------------------------------------------
# drop_disconnected — ejecta removal by bonded-cluster connectivity.
# ---------------------------------------------------------------------

def test_drop_disconnected_removes_detached_ejectum():
    """An atom adrift in the vacuum is not in the largest cluster."""
    # A bonded chain of three, plus one sputtered atom 20 Å away.
    atoms = Atoms(
        "Si" * 4,
        positions=[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0],
                   [0.0, 0.0, 20.0]],
        cell=np.diag([50.0, 50.0, 50.0]), pbc=(True, True, False))

    kept = drop_disconnected(atoms, bond_cutoff=1.5)

    assert len(kept) == 3
    assert kept.get_positions()[:, 2].max() < 10.0     # the ejectum is gone


def test_drop_disconnected_preserves_tags_on_survivors():
    """The kept atoms carry their wafer tag through the cut."""
    atoms = _grid_slab(6.0, tag=WAFER_A_TAG)
    kept = drop_disconnected(atoms, bond_cutoff=2.5)

    assert len(kept) == len(atoms)                     # all connected
    assert set(kept.get_tags()) == {WAFER_A_TAG}


# ---------------------------------------------------------------------
# assemble_amorphized_pair — the barrier stage end to end.
# ---------------------------------------------------------------------

def test_assemble_stacks_tags_ranges_and_open_box():
    """A clean assembly: A bottom, B top, tags split, z-open periodic."""
    half_a = _grid_slab(6.0)
    half_b = _grid_slab(6.0)

    pair = assemble_amorphized_pair(
        half_a, half_b, _IDENTITY_MATCH,
        bond_cutoff=2.5, initial_gap=5.0, clash_floor=2.0,
        grip_vacuum=10.0)

    # No ejecta in either half, so every atom survives.
    assert len(pair.atoms) == len(half_a) + len(half_b)
    # Periodic in the plane, open along z.
    assert list(pair.atoms.get_pbc()) == [True, True, False]
    # A tagged bottom, B tagged top, in build order (A then B).
    tags = pair.atoms.get_tags()
    assert set(tags[:len(half_a)]) == {WAFER_A_TAG}
    assert set(tags[len(half_a):]) == {WAFER_B_TAG}
    # A's base sits at grip_vacuum and B stacks entirely above A.
    assert pair.wafer_a_z_range[0] == pytest.approx(10.0)
    assert pair.wafer_b_z_range[0] > pair.wafer_a_z_range[1]
    # The interface plane sits between the two slabs.
    assert (pair.wafer_a_z_range[1]
            < pair.interface_z < pair.wafer_b_z_range[0])
    # A big enough gap needs no clash relief.
    assert pair.initial_gap_adjustment == pytest.approx(0.0)
    assert pair.type_map == {"Si": 1}


def test_assemble_relieves_and_records_a_clash():
    """A gap too small to clear the floor is backed off and recorded."""
    half_a = _grid_slab(6.0)
    half_b = _grid_slab(6.0)
    clash_floor = 2.0

    pair = assemble_amorphized_pair(
        half_a, half_b, _IDENTITY_MATCH,
        bond_cutoff=2.5, initial_gap=1.0, clash_floor=clash_floor,
        grip_vacuum=10.0)

    # The gap was lifted, and the lift is recorded rather than aborting.
    assert pair.initial_gap_adjustment > 0.0
    # After relief no cross-slab pair is closer than the floor.
    positions = pair.atoms.get_positions()
    tags = pair.atoms.get_tags()
    lateral_cell = np.asarray(pair.atoms.get_cell())
    minimum = _min_cross_distance(
        positions[tags == WAFER_A_TAG],
        positions[tags == WAFER_B_TAG], lateral_cell)
    assert minimum >= clash_floor - 1.0e-6


def test_assemble_asserts_commensurability():
    """Two halves that do not share a lateral cell are refused (§2.6)."""
    half_a = _grid_slab(6.0)
    half_b = _grid_slab(7.0)          # a different lateral cell

    with pytest.raises(ValueError, match="lateral cell"):
        assemble_amorphized_pair(
            half_a, half_b, _IDENTITY_MATCH,
            bond_cutoff=2.5, initial_gap=3.0, clash_floor=2.0)
