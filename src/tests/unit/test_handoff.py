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


def test_assembled_pair_carries_the_verdicts_and_heal_steps(tmp_path):
    """The §3.5 verdicts and heal markers ride the pair manifest (§10.1).

    Revised 2026-08-28: the gate runs in the activation stage, so the bond
    and analyze jobs learn the verdict from the assembled pair they read.
    """
    from dataclasses import replace
    from sabsim.driver.activation_gate import (
        ActivationVerdict,
        MetricVerdict,
    )
    verdict = ActivationVerdict(
        passed=True, activated_depth=5.5,
        per_metric={
            "coordination": MetricVerdict(
                name="coordination", measured=0.91,
                reference="share/activation/Si.toml", threshold=(0.05, 0.6),
                passed=True),
            "amorphization_depth": MetricVerdict(
                name="amorphization_depth", measured=5.5,
                reference="share/activation/Si.toml", threshold=5.0,
                passed=True)},
        reason="")
    structure = replace(
        _structure(_built_pair()),
        activation_a=verdict, activation_b=None,
        heal_start_step_a=42000, heal_start_step_b=None)
    write_assembled_pair(tmp_path, structure)
    back = read_assembled_pair(tmp_path)
    assert back.activation_b is None
    assert back.activation_a.passed is True
    assert back.activation_a.activated_depth == 5.5
    assert back.activation_a.per_metric["coordination"].threshold == (
        0.05, 0.6)
    assert back.heal_start_step_a == 42000
    assert back.heal_start_step_b is None


def test_pull_results_carry_the_stage_ledger(tmp_path):
    """The press/settle stage ledger round-trips; absent markers stay None."""
    from dataclasses import replace
    from sabsim.pipeline.exec_artifacts import StageLedger
    ledger = StageLedger(press_start=0, contact=3000, hold_end=153000,
                         settle_start=153000, settle_end=None)
    original = _bond_debond()
    with_ledger = replace(
        original, press=replace(original.press, stage_steps=ledger))
    write_pull_results(tmp_path, with_ledger)
    back = read_pull_results(tmp_path)
    assert back.press.stage_steps == ledger
    assert back == with_ledger


# ---------------------------------------------------------------------
# ACTIVATED_HALF — the prep job's deliverable (revised 2026-08-30): one
# healed half, its verdict, its wafer tag and the shared cell it was
# cut on round-trip through its prep folder, and bond refuses two
# halves that were not built for each other.
# ---------------------------------------------------------------------

def _healed_half_file(directory, name, lateral=4.0):
    """A tiny healed-half atoms file with the given in-plane cell."""
    atoms = Atoms(
        symbols=["Si", "Si"],
        positions=[[0.0, 0.0, 1.0], [1.0, 1.0, 3.0]],
        cell=[[lateral, 0.0, 0.0], [0.0, lateral, 0.0], [0.0, 0.0, 20.0]],
        pbc=(True, True, False))
    atoms.set_tags([WAFER_A_TAG, WAFER_A_TAG])
    path = directory / name
    from ase.io import write as ase_write
    ase_write(str(path), atoms, format="extxyz")
    return str(path)


def _half(data_file, wafer_tag, shared=None, heal_step=1200):
    from sabsim.driver.activation_gate import ActivationVerdict
    from sabsim.pipeline.exec_artifacts import (
        ActivatedHalf,
        SharedCell,
        Slab,
    )
    verdict = ActivationVerdict(
        passed=True, activated_depth=7.5, per_metric={},
        reason="all metrics passed")
    return ActivatedHalf(
        slab=Slab(identity="Si", note="healed", data_file=data_file,
                  species=frozenset({"Si"}), heal_start_step=heal_step),
        verdict=verdict, wafer_tag=wafer_tag,
        shared=shared or SharedCell(note="identity"),
        run_id="run-4242")


def test_activated_half_round_trips_through_its_folder(tmp_path):
    """Slab, verdict, tag, shared cell, heal step and run id all return."""
    from sabsim.deploy.registry import ACTIVATED_HALF
    from sabsim.pipeline.handoff import read_activated_half
    work = tmp_path / "run"
    work.mkdir()
    prep = tmp_path / "prep_surf1_si"
    prep.mkdir()
    source = _healed_half_file(work, "amorphized_a.extxyz")
    write_artifact(str(prep), ACTIVATED_HALF, _half(source, WAFER_A_TAG))

    back = read_activated_half(str(prep))
    assert back.wafer_tag == WAFER_A_TAG
    assert back.slab.identity == "Si"
    assert back.slab.species == frozenset({"Si"})
    assert back.slab.heal_start_step == 1200
    assert back.verdict.passed and back.verdict.activated_depth == 7.5
    assert back.shared.is_identity is True
    assert back.run_id == "run-4242"
    # The payload was COPIED into the prep folder: the deliverable does
    # not point back at the run's scratch folder.
    assert back.slab.data_file == str(prep / "activated_half.extxyz")
    assert read_artifact(str(prep), ACTIVATED_HALF).wafer_tag == (
        WAFER_A_TAG)


def test_a_placeholder_half_has_no_payload(tmp_path):
    """A W0 half (no atoms file) writes only its manifest and reads back
    with no file, which is what the placeholder assembly expects."""
    from sabsim.pipeline.handoff import (
        read_activated_half,
        write_activated_half,
    )
    write_activated_half(str(tmp_path), _half(None, WAFER_B_TAG))
    back = read_activated_half(str(tmp_path))
    assert back.slab.data_file is None
    assert back.wafer_tag == WAFER_B_TAG


def test_bond_refuses_halves_from_different_cells(tmp_path):
    """Two halves with different in-plane cells are refused by name."""
    from sabsim.pipeline.exec_artifacts import SharedCell
    from sabsim.pipeline.handoff import check_shared_cells_agree
    file_a = _healed_half_file(tmp_path, "a.extxyz", lateral=4.0)
    file_b = _healed_half_file(tmp_path, "b.extxyz", lateral=4.5)
    half_a = _half(file_a, WAFER_A_TAG)
    half_b = _half(file_b, WAFER_B_TAG)
    with pytest.raises(HandoffError, match="in-plane cells"):
        check_shared_cells_agree(half_a, half_b)
    # Same atoms but a different match provenance is refused too.
    strained = _half(file_a, WAFER_B_TAG, shared=SharedCell(
        note="mismatch", residual_strain=0.02, match_area=40.0,
        is_identity=False))
    with pytest.raises(HandoffError, match="same shared cell"):
        check_shared_cells_agree(half_a, strained)
    # Two A halves can never be bonded: bond needs a bottom and a top.
    with pytest.raises(HandoffError, match="wafer tag"):
        check_shared_cells_agree(half_a, _half(file_a, WAFER_A_TAG))
    # And two matching halves pass quietly.
    check_shared_cells_agree(half_a, _half(file_a, WAFER_B_TAG))
