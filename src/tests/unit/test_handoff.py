"""Unit tests for the mid-chain handoff artifacts (sabsim.pipeline.handoff).

These pin the property the whole separate-submission design rests on
(PSEUDOCODE.md §14.6): a mid-chain record written by one job is
reconstructed FAITHFULLY by the next, from files alone. The assembled
pair's per-wafer tags and geometry survive the round trip (they cannot be
re-derived from a LAMMPS data file, DESIGN.md §2.6), and the pull result's
reduced curves come back intact. A missing artifact is a loud stop, not a
confusing failure deep inside a stage.
"""

import numpy as np
import pytest
from ase import Atoms

from sabsim.deploy.registry import ASSEMBLED_PAIR, PULL_RESULTS
from sabsim.pipeline.exec_artifacts import (
    BondDebondResult,
    PressOutcome,
    PullOutcome,
    Structure,
)
from sabsim.pipeline.handoff import (
    HandoffError,
    read_artifact,
    read_assembled_pair,
    read_pull_results,
    write_artifact,
    write_assembled_pair,
    write_pull_results,
)
from sabsim.structure.slab_builder import (
    WAFER_A_TAG,
    WAFER_B_TAG,
    BuiltPair,
    SurfaceMatch,
)


def _built_pair() -> BuiltPair:
    """A small but complete BuiltPair standing in for a real assembly.

    Two wafer-A atoms (bottom) and one wafer-B atom (top), so the per-atom
    tags are non-trivial and the round trip has something to preserve.
    """
    atoms = Atoms(
        symbols=["Si", "Si", "O"],
        positions=[[0.0, 0.0, 2.0], [1.5, 1.5, 3.0], [0.5, 0.5, 9.0]],
        cell=[[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 20.0]],
        pbc=(True, True, False))
    atoms.set_tags([WAFER_A_TAG, WAFER_A_TAG, WAFER_B_TAG])
    return BuiltPair(
        atoms=atoms,
        interface_z=6.0,
        wafer_a_z_range=(2.0, 3.0),
        wafer_b_z_range=(9.0, 9.0),
        type_map={"Si": 1, "O": 2},
        match=SurfaceMatch(
            residual_strain=0.0, match_area=16.0, is_identity=True),
        initial_gap_adjustment=0.75)


def _structure(built: BuiltPair) -> Structure:
    """Wrap a BuiltPair in the Structure the assemble stage returns."""
    return Structure(
        note="assembled Si/O test pair",
        labeled_groups=(
            "wafer_a_z_range", "wafer_b_z_range", "interface_z",
            "activated_skin"),
        data_file=None,
        built=built)


# ---------------------------------------------------------------------
# ASSEMBLED_PAIR — the geometry and the per-wafer tags survive.
# ---------------------------------------------------------------------

def test_assembled_pair_round_trips_geometry(tmp_path):
    """The manifest's scalar geometry comes back exactly."""
    built = _built_pair()
    write_assembled_pair(tmp_path, _structure(built))

    read = read_assembled_pair(tmp_path)
    assert read.note == "assembled Si/O test pair"
    assert read.labeled_groups == (
        "wafer_a_z_range", "wafer_b_z_range", "interface_z",
        "activated_skin")
    got = read.built
    assert got.interface_z == 6.0
    assert got.wafer_a_z_range == (2.0, 3.0)
    assert got.wafer_b_z_range == (9.0, 9.0)
    assert got.initial_gap_adjustment == 0.75
    assert got.type_map == {"Si": 1, "O": 2}
    assert got.match.is_identity is True
    assert got.match.match_area == 16.0


def test_assembled_pair_preserves_atoms_and_tags(tmp_path):
    """Positions, species, cell, and the per-wafer tags all round-trip.

    The tags are the load-bearing part: a LAMMPS data file cannot carry
    them, so if the extended-XYZ payload did not, the bond job could not
    tell the two wafers apart (DESIGN.md §2.6, the driver's grips).
    """
    built = _built_pair()
    write_assembled_pair(tmp_path, _structure(built))
    got = read_assembled_pair(tmp_path).built

    assert list(got.atoms.get_chemical_symbols()) == ["Si", "Si", "O"]
    assert list(got.atoms.get_tags()) == [
        WAFER_A_TAG, WAFER_A_TAG, WAFER_B_TAG]
    assert np.allclose(
        got.atoms.get_positions(), built.atoms.get_positions())
    assert np.allclose(got.atoms.get_cell(), built.atoms.get_cell())


def test_assembled_pair_data_file_is_written_and_pointed_at(tmp_path):
    """The reconstructed Structure points at a real LAMMPS data file."""
    write_assembled_pair(tmp_path, _structure(_built_pair()))
    read = read_assembled_pair(tmp_path)
    assert read.data_file.endswith("assembled_pair.data")
    assert (tmp_path / "assembled_pair.data").is_file()


def test_writing_a_pair_with_no_built_is_refused(tmp_path):
    """A W0 placeholder structure (built=None) cannot be handed across."""
    placeholder = Structure(
        note="w0", labeled_groups=("interface_z",),
        data_file=None, built=None)
    with pytest.raises(HandoffError, match="built"):
        write_assembled_pair(tmp_path, placeholder)


# ---------------------------------------------------------------------
# PULL_RESULTS — the whole result, curves included, round-trips.
# ---------------------------------------------------------------------

def _bond_debond() -> BondDebondResult:
    """A two-rung pull result: one separated rung, one that did not."""
    return BondDebondResult(
        press=PressOutcome(bonded=True, note="contact held"),
        reference_ok=True,
        pulls=(
            PullOutcome(
                rate_value=1.0e-4, rate_unit="1/ps", note="separated",
                complete=True, separation_index=2,
                grip_displacement=(0.0, 1.0, 2.0),
                force_vs_grip=(0.10, 0.25, 0.0),
                atoms_conserved=True, bridges_at_separation=0),
            PullOutcome(
                rate_value=1.0e-3, rate_unit="1/ps",
                note="did not separate", complete=False)))


def test_pull_results_round_trip_is_exact(tmp_path):
    """The whole BondDebondResult comes back equal, curves and all.

    The records are frozen dataclasses with value equality, so an exact
    ``==`` is the strongest statement that nothing was lost or reshaped.
    """
    original = _bond_debond()
    write_pull_results(tmp_path, original)
    assert read_pull_results(tmp_path) == original


# ---------------------------------------------------------------------
# The name-keyed façade and the missing-artifact stop.
# ---------------------------------------------------------------------

def test_write_and_read_artifact_dispatch_by_name(tmp_path):
    """write_artifact/read_artifact route by the registry artifact name."""
    write_artifact(tmp_path, ASSEMBLED_PAIR, _structure(_built_pair()))
    write_artifact(tmp_path, PULL_RESULTS, _bond_debond())

    assert read_artifact(tmp_path, PULL_RESULTS) == _bond_debond()
    assert read_artifact(tmp_path, ASSEMBLED_PAIR).built.interface_z == 6.0


def test_reading_a_missing_artifact_is_a_loud_stop(tmp_path):
    """A job asked to start from an unwritten artifact halts, naming it."""
    with pytest.raises(HandoffError, match=PULL_RESULTS):
        read_artifact(tmp_path, PULL_RESULTS)
