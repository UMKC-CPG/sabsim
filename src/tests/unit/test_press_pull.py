"""Unit tests for the press/pull control loops (driver.press_pull).

Slice 5's logic is written against the engine seam, so these drive each
phase against a SCRIPTED MockEngine with no LAMMPS: the press stops on
the dual contact criterion, the settle gate reports each sub-verdict, and
the pull stops at complete separation. The mock plays back a sequence of
read-backs — an opening that closes, a stress that turns positive, a
force that decays — so the mid-run decisions are genuinely exercised.
"""

import os
from types import SimpleNamespace

import numpy as np
import pytest

from sabsim.driver.commands import RegionGeometry
from tests.unit.support import stand_in_force_model
from sabsim.driver.engine import MockEngine
from sabsim.driver.press_pull import (
    RunControl,
    _positions_with_tags,
    begin_or_resume_pull,
    press_and_bond,
    pull_at_rate,
    settle_reference,
)
from sabsim.driver.resume import (
    Ledger,
    ResumeInputMismatch,
    input_hash,
    write_checkpoint,
)
from sabsim.spec.loader import load_and_validate_study
from sabsim.spec.records import Quantity
from sabsim.structure.slab_builder import WAFER_A_TAG, WAFER_B_TAG


_TEMPLATE_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "share", "templates", "study_spec.toml"))

_MODEL = stand_in_force_model({"Si": 1})
_LOWER_Z = np.linspace(0.0, 10.0, 100)   # a wafer-A slab, top surface ~10



def _member():
    """The first template member — a real MemberSpecification."""
    return load_and_validate_study(_TEMPLATE_PATH).members[0]


def _tuned(**numerical_overrides):
    """The template member with some ``[numerical]`` knobs replaced.

    The driver's chunking is the study's (DESIGN §5.2/§5.3): a test that
    wants a short press budget or settle span says so through the study
    knobs, exactly as a study file would.
    """
    from dataclasses import replace
    member = _member()
    return replace(member, numerical=replace(
        member.numerical, **numerical_overrides))


def _fake_built():
    """A light pair with the tags, cell, and z-ranges the loops read."""
    tags = np.array([WAFER_A_TAG] * 100 + [WAFER_B_TAG] * 100)
    cell = np.array([[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 60.0]])
    atoms = SimpleNamespace(
        get_tags=lambda: tags, get_cell=lambda: cell)
    return SimpleNamespace(
        atoms=atoms, wafer_a_z_range=(0.0, 10.0),
        wafer_b_z_range=(15.0, 25.0), type_map={"Si": 1})


def _frame(upper_low: float):
    """A position frame: wafer A fixed, wafer B starting at upper_low."""
    z_upper = np.linspace(upper_low, upper_low + 10.0, 100)
    positions = np.zeros((200, 3))
    positions[:100, 2] = _LOWER_Z
    positions[100:, 2] = z_upper
    return positions


# ---------------------------------------------------------------------
# press_and_bond — the dual contact criterion stops the approach (§9.3).
# ---------------------------------------------------------------------

def test_press_stops_on_the_dual_contact_criterion():
    """Contact fires when the gap closes AND the stress runs positive."""
    # Geometric openings 6.0, 4.0, 1.9 (the label-free measure of
    # DESIGN §2.6, revised 2026-08-30, reads the whole-system profile
    # crossing to crossing); the gap threshold is 2.5, so only the third
    # frame is closed. The stress turns positive over the same chunks.
    frames = [_frame(16.0), _frame(14.0), _frame(12.0), _frame(12.0),
              _frame(12.0)]
    engine = MockEngine(
        positions=frames,
        normal_stress=[-1000.0, 2000.0, 2000.0, 2000.0, 2000.0])

    result = press_and_bond(
        engine, _fake_built(), _member(), _MODEL, "pair.data", seed=1)

    assert result.contact_reached
    # The gap is a trailing mean over gap_window (3) chunks, so the closed
    # 11.0 frame must hold for three chunks: contact on chunk 4.
    assert result.chunks_to_contact == 4
    # After contact it holds for press_duration (150 ps / 1 fs steps).
    assert "run 150000" in engine.received_commands


def test_press_reports_no_contact_within_the_budget():
    """A gap that never closes is reported, not forced (§9.3)."""
    engine = MockEngine(positions=[_frame(15.0)], normal_stress=[1.0])
    result = press_and_bond(
        engine, _fake_built(),
        _tuned(press_time_budget=Quantity(3.0, "ps")), _MODEL,
        "pair.data", seed=1)
    assert not result.contact_reached
    assert result.chunks_to_contact is None
    assert "press_time_budget" in result.note


def _gapped_built(upper_low: float):
    """A pair whose top wafer's lowest atom sits ``upper_low`` above the
    origin, so the closest-atom gap is ``upper_low - 10`` (wafer A tops at
    10). Used to drive the pre-press relax across the cutoff threshold."""
    tags = np.array([WAFER_A_TAG] * 100 + [WAFER_B_TAG] * 100)
    cell = np.array([[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 60.0]])
    atoms = SimpleNamespace(get_tags=lambda: tags, get_cell=lambda: cell)
    return SimpleNamespace(
        atoms=atoms, wafer_a_z_range=(0.0, 10.0),
        wafer_b_z_range=(upper_low, upper_low + 10.0),
        interface_z=0.5 * (10.0 + upper_low), type_map={"Si": 1})


def _first_drive_index(stream):
    """Index of the first command that installs the press drive."""
    for index, line in enumerate(stream):
        if "drive_top" in line:
            return index
    raise AssertionError("no press drive was installed")


def test_settle_passes_a_flat_balanced_reference():
    """A flat PE and canceling grip reactions settle the reference."""
    engine = MockEngine(
        energies=[-100.0, -100.0, -100.0, -100.0],
        bottom_reaction=[1.0, 1.0, 1.0, 1.0],
        top_reaction=[-1.0, -1.0, -1.0, -1.0],
        atom_count=64)
    result = settle_reference(
        engine, _tuned(settle_duration=Quantity(4.0, "ps")))
    assert result.settled
    assert result.report.force_ok and result.report.drift_ok


def test_settle_reports_a_drifting_reference_as_unsettled():
    """A PE still sliding fails the drift gate and is not integrated."""
    engine = MockEngine(
        energies=[-100.0, -100.0, -90.0, -80.0],
        bottom_reaction=[1.0] * 4, top_reaction=[-1.0] * 4,
        atom_count=64)
    result = settle_reference(
        engine, _tuned(settle_duration=Quantity(4.0, "ps")))
    assert not result.settled
    assert not result.report.drift_ok


def test_settle_releases_the_drive_and_writes_the_reference():
    """Settle unloads the press, then writes the reference the pull reads."""
    engine = MockEngine(
        energies=[-100.0] * 4, bottom_reaction=[1.0] * 4,
        top_reaction=[-1.0] * 4, atom_count=64)
    result = settle_reference(
        engine, _tuned(settle_duration=Quantity(4.0, "ps")),
        reference_data_file="settled.data")
    stream = engine.received_commands
    # The press drive is released BEFORE the minimize, or the reference
    # would settle while still being pressed (§5.3). Template is load
    # mode, so the grip integrator is released too.
    assert "unfix drive_top" in stream
    assert "unfix drive_top_nve" in stream
    assert stream.index("unfix drive_top") < stream.index(
        "minimize 1e-8 1e-8 1000 10000")
    # The settled state is written out and its path returned — the
    # artifact the pull restores from (handing it the original pair data
    # would discard the whole press).
    assert "write_data settled.data" in stream
    assert result.reference_data_file == "settled.data"


# ---------------------------------------------------------------------
# pull_at_rate — stop at complete separation, then reduce (§9.5, §9.6).
# ---------------------------------------------------------------------

def test_pull_stops_at_complete_separation(tmp_path):
    """The pull stops when the interface opens past the cutoff at ~0 force."""
    # Openings ~3, 5, 7, 9; the cutoff is 6, so frames 3-4 are open. The
    # force decays; only the last is within the noise floor (0.05).
    frames = [_frame(12.0), _frame(14.0), _frame(16.0), _frame(18.0)]
    engine = MockEngine(
        positions=frames, top_reaction=[1.0, 0.5, 0.3, 0.02])

    result = pull_at_rate(
        engine, _fake_built(), _member(), _MODEL, "ref.data",
        rate=Quantity(3.2, "m/s"), seed=1,
        output_directory=str(tmp_path))

    assert result.complete
    assert isinstance(result.grip_displacement, np.ndarray)


def test_pull_reports_incomplete_when_it_never_separates(tmp_path):
    """A pull that never opens past the cutoff is flagged incomplete."""
    engine = MockEngine(
        positions=[_frame(12.0)], top_reaction=[1.0])
    result = pull_at_rate(
        engine, _fake_built(), _member(), _MODEL, "ref.data",
        rate=Quantity(3.2, "m/s"), seed=1,
        control=RunControl(max_chunks=3),
        output_directory=str(tmp_path))
    assert not result.complete


def test_a_short_pull_that_separates_still_yields_a_curve(tmp_path):
    """A rung that separates within one averaging window is not lost.

    The regression: the first full end-to-end run's slowest rung
    separated after 0.49 A of travel against a 0.5 A force-average
    window. The averaged curve came back EMPTY, so the separation search
    found nothing and a pull that DID separate was reported unresolved.
    The reduction must degrade to a coarse curve, never to no curve.
    """
    # Open immediately (opening ~7 > 6 cutoff) at the noise floor, so the
    # raw stop fires on the very first chunk -- the shortest record.
    engine = MockEngine(
        positions=[_frame(20.0)], top_reaction=[0.01])
    result = pull_at_rate(
        engine, _fake_built(), _member(), _MODEL, "ref.data",
        rate=Quantity(1.0, "m/s"), seed=1,
        control=RunControl(max_chunks=6),
        output_directory=str(tmp_path))

    assert result.complete, "an immediate clean separation must resolve"
    assert result.grip_displacement.size > 0, "the curve must not vanish"
    assert result.separation_index is not None


def test_pull_completeness_agrees_with_the_reduced_separation(tmp_path):
    """`complete` is true iff the reduced curve has a separation point.

    The two used to be decided by different tests on different data --
    the live loop on raw samples, the analyzer on the smoothed curve --
    so they could disagree. They are now one decision, taken from the
    curves the work integral is computed over.
    """
    # Never opens past the cutoff: no separation on either reading.
    engine = MockEngine(
        positions=[_frame(12.0)], top_reaction=[1.0])
    result = pull_at_rate(
        engine, _fake_built(), _member(), _MODEL, "ref.data",
        rate=Quantity(3.2, "m/s"), seed=1,
        control=RunControl(max_chunks=4),
        output_directory=str(tmp_path))

    assert result.complete == (result.separation_index is not None)
    assert not result.complete


# ---------------------------------------------------------------------
# pull resume — fresh vs. restore, decided by what is on disk (§13.3).
# ---------------------------------------------------------------------

_PULL_RATE = Quantity(3.2, "m/s")


def _matching_hash() -> str:
    """The trust hash the resume tests' inputs (member, ref, rate) yield."""
    return input_hash(_member(), "ref.data", _PULL_RATE)


def _crafted_checkpoint(checkpoint_dir: str, stored_hash: str) -> None:
    """Write a two-sample checkpoint at engine step 2000, via the writer.

    Uses the real :func:`write_checkpoint`, so the pair on disk is exactly
    what a killed run would have left — an engine restart at step 2000 (the
    mock models the step) and a ledger stamped to match. ``stored_hash`` is
    the §13.4 trust field the resume compares against.
    """
    writer_engine = MockEngine()
    writer_engine.commands(["run 2000"])          # engine now at step 2000
    seed_ledger = Ledger(
        sample_steps=[1000, 2000], displacement=[0.1, 0.2],
        force=[1.0, 0.8], opening=[3.0, 4.0], bridges=[5.0, 2.0],
        starting_atom_count=200, input_hash=stored_hash)
    write_checkpoint(writer_engine, seed_ledger, checkpoint_dir)


def test_a_fresh_pull_reads_data_and_seeds_an_empty_ledger():
    """With no checkpoint on disk the pull begins normally (§13.3)."""
    engine = MockEngine(positions=[_frame(12.0)])

    start = begin_or_resume_pull(
        engine, _fake_built(), _member(), _MODEL, "ref.data",
        Quantity(3.2, "m/s"), 1, RegionGeometry(), RunControl(),
        None, None, None)

    assert not start.resumed                        # a fresh start
    assert not start.override_used
    assert start.ledger.sample_steps == []          # nothing accumulated
    assert start.ledger.starting_atom_count == 200  # the §5.6 baseline
    # A fresh run reads the reference with read_data (and so grows the box
    # headroom); it is NOT a restart.
    assert any("read_data" in line for line in engine.received_commands)


def test_a_present_checkpoint_restores_and_reconciles(tmp_path):
    """Finding a pair, the pull restores the engine and trims the ledger.

    The engine comes back at the saved step (the mock models this), the
    ledger reconciles to it, and the setup uses read_restart — never
    read_data, and so never re-grows the already-restored box (§13.3).
    """
    checkpoint_dir = str(tmp_path / "pull_x" / "checkpoints")
    _crafted_checkpoint(checkpoint_dir, _matching_hash())
    engine = MockEngine(positions=[_frame(12.0)])

    start = begin_or_resume_pull(
        engine, _fake_built(), _member(), _MODEL, "ref.data",
        _PULL_RATE, 1, RegionGeometry(), RunControl(),
        checkpoint_dir, None, None)

    assert start.resumed                            # it continued a run
    assert not start.override_used                  # inputs matched cleanly
    assert engine.step() == 2000                    # restored, not zero
    assert start.ledger.sample_steps == [1000, 2000]  # reconciled to it
    assert start.ledger.starting_atom_count == 200  # baseline rides through
    stream = engine.received_commands
    assert not any("read_data" in line for line in stream)
    assert "units metal" in stream                  # restart preamble ran
    # The fixtures are re-issued over the restored box (a restart carries
    # none of them), e.g. the held-grip gauge.
    assert "fix hold_bottom bottom_grip setforce 0.0 0.0 0.0" in stream


def test_pull_writes_a_checkpoint_pair_on_the_cadence(tmp_path):
    """With a checkpoint dir and a due cadence, a pair lands on disk (§13.2).

    A pull that never separates runs its whole budget; the first chunk
    reaches the cadence (1000 steps), so the matched pair is written.
    """
    checkpoint_dir = str(tmp_path / "checkpoints")
    engine = MockEngine(positions=[_frame(12.0)], top_reaction=[1.0])

    pull_at_rate(
        engine, _fake_built(), _member(), _MODEL, "ref.data",
        rate=Quantity(3.2, "m/s"), seed=1,
        control=RunControl(max_chunks=3, checkpoint_cadence=1000),
        output_directory=str(tmp_path), checkpoint_dir=checkpoint_dir)

    assert os.path.exists(os.path.join(checkpoint_dir, "engine.restart"))
    assert os.path.exists(os.path.join(checkpoint_dir, "ledger.json"))


def test_pull_result_flags_a_resumed_rung(tmp_path):
    """pull_at_rate carries the resume fact into its result (§13.6).

    A fresh pull reports resumed=False; one that continued a checkpoint
    reports resumed=True, so the outcome can declare how it was produced.
    """
    fresh_engine = MockEngine(positions=[_frame(20.0)], top_reaction=[0.01])
    fresh = pull_at_rate(
        fresh_engine, _fake_built(), _member(), _MODEL, "ref.data",
        rate=_PULL_RATE, seed=1, control=RunControl(max_chunks=6),
        output_directory=str(tmp_path))
    assert not fresh.resumed

    checkpoint_dir = str(tmp_path / "pull_x" / "checkpoints")
    _crafted_checkpoint(checkpoint_dir, _matching_hash())
    resumed_engine = MockEngine(
        positions=[_frame(20.0)], top_reaction=[0.01])
    resumed = pull_at_rate(
        resumed_engine, _fake_built(), _member(), _MODEL, "ref.data",
        rate=_PULL_RATE, seed=1, control=RunControl(max_chunks=6),
        output_directory=str(tmp_path), checkpoint_dir=checkpoint_dir)
    assert resumed.resumed
    assert not resumed.override_used


# ---------------------------------------------------------------------
# pull resume — the trust guard: warn, and stop (§13.4).
# ---------------------------------------------------------------------

def test_resume_stops_when_the_inputs_differ(tmp_path):
    """A checkpoint from a different run halts the resume before it acts.

    The guard fires when the current inputs hash differently from the run
    the checkpoint was written for — here a deliberately wrong stored
    hash — and it stops rather than stitch new inputs onto old dynamics.
    """
    checkpoint_dir = str(tmp_path / "pull_x" / "checkpoints")
    _crafted_checkpoint(checkpoint_dir, "deadbeefdeadbeef")
    engine = MockEngine(positions=[_frame(12.0)])

    with pytest.raises(ResumeInputMismatch):
        begin_or_resume_pull(
            engine, _fake_built(), _member(), _MODEL, "ref.data",
            _PULL_RATE, 1, RegionGeometry(), RunControl(),
            checkpoint_dir, None, None)
    # It stopped BEFORE touching the engine (the trust check is first).
    assert engine.step() == 0


def test_resume_override_lets_a_mismatch_through(tmp_path, monkeypatch):
    """The deliberate override env var lifts the stop (§13.4)."""
    checkpoint_dir = str(tmp_path / "pull_x" / "checkpoints")
    _crafted_checkpoint(checkpoint_dir, "deadbeefdeadbeef")
    monkeypatch.setenv("SABSIM_RESUME_OVERRIDE", "1")
    engine = MockEngine(positions=[_frame(12.0)])

    start = begin_or_resume_pull(
        engine, _fake_built(), _member(), _MODEL, "ref.data",
        _PULL_RATE, 1, RegionGeometry(), RunControl(),
        checkpoint_dir, None, None)

    assert start.resumed
    assert start.override_used                       # the guard was lifted
    assert engine.step() == 2000                    # proceeded anyway
    assert start.ledger.sample_steps == [1000, 2000]


def test_input_hash_is_stable_but_rate_sensitive(tmp_path):
    """The same inputs hash the same; a different rate hashes differently.

    The rate is the only thing that tells one rung of a member from
    another, so it MUST move the hash (§13.4).
    """
    reference = str(tmp_path / "ref.data")
    with open(reference, "w", encoding="utf-8") as handle:
        handle.write("a settled structure")

    fast = input_hash(_member(), reference, Quantity(3.2, "m/s"))
    slow = input_hash(_member(), reference, Quantity(1.0, "m/s"))
    assert fast != slow
    assert fast == input_hash(_member(), reference, Quantity(3.2, "m/s"))


def test_input_hash_tracks_the_reference_content(tmp_path):
    """A different settled reference in the same path hashes differently."""
    reference = tmp_path / "ref.data"
    reference.write_text("structure A")
    before = input_hash(_member(), str(reference), _PULL_RATE)
    reference.write_text("structure B")
    after = input_hash(_member(), str(reference), _PULL_RATE)
    assert before != after


class _LossyEngine:
    """A minimal stand-in that reports SURVIVORS after atom loss.

    A real free surface evaporates atoms under a long universal-MLIP run,
    leaving the survivors' ids as a NON-consecutive subset of ``1..N``. The
    mock cannot express that (it keeps ids dense), so this tiny engine hands
    back a chosen id set and the matching positions to prove that
    :func:`_positions_with_tags` realigns the full builder tag array onto
    exactly the survivors — the fix for the ``gather_atoms`` crash.
    """

    def __init__(self, survivor_ids, survivor_positions) -> None:
        self._ids = np.asarray(survivor_ids, dtype=int)
        self._positions = np.asarray(survivor_positions, dtype=float)

    def positions(self) -> np.ndarray:
        return self._positions

    def atom_ids(self) -> np.ndarray:
        return self._ids


def test_positions_with_tags_realigns_after_atom_loss():
    """Losing an interior atom must drop its tag, not shift the rest.

    Four atoms are built as wafers ``[A, A, B, B]`` (ids 1..4). Atom id 3
    (the first B atom) evaporates, so the engine returns only ids
    ``[1, 2, 4]``. The realigned tags must be ``[A, A, B]`` — atom 4 keeps
    its B tag because the re-index is BY ID (``tags[id-1]``), not by row
    position, which a naive length-truncation would get wrong.
    """
    full_tags = np.array([WAFER_A_TAG, WAFER_A_TAG,
                          WAFER_B_TAG, WAFER_B_TAG])
    survivor_ids = [1, 2, 4]
    survivor_positions = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0],
                          [3.0, 0.0, 0.0]]
    engine = _LossyEngine(survivor_ids, survivor_positions)

    frame, aligned_tags = _positions_with_tags(engine, full_tags)

    assert frame.shape == (3, 3)
    np.testing.assert_array_equal(
        aligned_tags, [WAFER_A_TAG, WAFER_A_TAG, WAFER_B_TAG])


def test_positions_with_tags_is_identity_without_loss():
    """With every atom present the realignment must be a no-op.

    This guards the backward-compatibility promise: when nothing is lost
    the survivor ids are the dense ``1..N`` and the returned tags equal the
    builder's array unchanged, so the original row-for-row contract holds.
    """
    full_tags = np.array([WAFER_A_TAG, WAFER_B_TAG, WAFER_B_TAG])
    engine = _LossyEngine([1, 2, 3],
                          [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0],
                           [2.0, 0.0, 0.0]])

    _frame, aligned_tags = _positions_with_tags(engine, full_tags)

    np.testing.assert_array_equal(aligned_tags, full_tags)


# ---------------------------------------------------------------------
# §5.6 atom conservation is judged against the ASSEMBLED pair at every
# stage boundary, not only across the pull (the T-18 blind spot).
# ---------------------------------------------------------------------

def test_press_that_loses_atoms_is_void_even_when_contact_fires():
    """A disintegrating pair can fire the stress criterion; it is VOID."""
    frames = [_frame(15.0), _frame(13.0), _frame(11.0), _frame(11.0),
              _frame(11.0)]
    # The assembled pair has 200 atoms (100 per wafer); the engine reports
    # only 150 survivors by the end of the press.
    engine = MockEngine(
        positions=frames,
        normal_stress=[-1000.0, 2000.0, 2000.0, 2000.0, 2000.0],
        atom_count=150)
    result = press_and_bond(
        engine, _fake_built(), _member(), _MODEL, "pair.data", seed=1)
    assert result.contact_reached           # the criterion did fire...
    assert result.atoms_conserved is False  # ...but the result is void
    assert "LOST ATOMS" in result.note


def test_press_that_keeps_every_atom_is_conserved():
    """With every assembled atom still present the press is a measurement."""
    frames = [_frame(15.0), _frame(13.0), _frame(11.0), _frame(11.0),
              _frame(11.0)]
    engine = MockEngine(
        positions=frames,
        normal_stress=[-1000.0, 2000.0, 2000.0, 2000.0, 2000.0],
        atom_count=200)
    result = press_and_bond(
        engine, _fake_built(), _member(), _MODEL, "pair.data", seed=1)
    assert result.atoms_conserved is True
    assert "LOST ATOMS" not in result.note


def test_settle_checks_conservation_against_the_assembled_count():
    """The settle reports a lost atom against the assembled baseline."""
    engine = MockEngine(
        energies=[-100.0, -100.0, -100.0, -100.0],
        bottom_reaction=[0.0] * 4, top_reaction=[0.0] * 4,
        atom_count=199)
    result = settle_reference(
        engine, _member(), expected_atom_count=200)
    assert result.atoms_conserved is False


def test_pull_uses_the_assembled_count_as_its_baseline(tmp_path):
    """An atom lost BEFORE the pull started still voids the rung.

    The engine holds 200 atoms throughout the pull — so a pull-start
    baseline would call it conserved — but the pair was assembled with
    201, so against the §5.6 baseline the rung is void.
    """
    frames = [_frame(11.0), _frame(20.0), _frame(30.0), _frame(40.0),
              _frame(50.0)]
    engine = MockEngine(positions=frames, top_reaction=[0.0] * 5)
    result = pull_at_rate(
        engine, _fake_built(), _member(), _MODEL, "reference.data",
        Quantity(1.0, "m/s"), seed=1, output_directory=str(tmp_path),
        expected_atom_count=201)
    assert result.atoms_conserved is False


# ---------------------------------------------------------------------
# The stage ledger (§9.3, §9.4, DESIGN §5.5): the press and settle record
# the MD step each phase began at, so a movie frame keys to its phase.
# ---------------------------------------------------------------------

def test_press_records_its_stage_ledger_in_engine_steps():
    """press_start, contact and hold_end are read off the engine's clock.

    The mock advances its step by every ``run N``: the cell relax runs no
    steps, so press_start is 0; contact fires after three 1000-step
    chunks; the template's 150 ps hold at 1 fs is 150000 more steps.
    """
    frames = [_frame(15.0), _frame(13.0), _frame(11.0), _frame(11.0),
              _frame(11.0)]
    engine = MockEngine(
        positions=frames,
        normal_stress=[-1000.0, 2000.0, 2000.0, 2000.0, 2000.0])
    result = press_and_bond(
        engine, _fake_built(), _member(), _MODEL, "pair.data", seed=1)
    assert result.contact_reached
    assert result.press_start_step == 0
    assert result.contact_step == 1000 * (result.chunks_to_contact + 1)
    assert result.hold_end_step == result.contact_step + 150000


def test_press_without_contact_still_records_where_it_started():
    """No contact -> no contact/hold markers, but press_start is kept."""
    engine = MockEngine(
        positions=[_frame(30.0)] * 3, normal_stress=[-1.0] * 3)
    result = press_and_bond(
        engine, _fake_built(),
        _tuned(press_time_budget=Quantity(3.0, "ps")), _MODEL,
        "pair.data", seed=1)
    assert not result.contact_reached
    assert result.press_start_step == 0
    assert result.contact_step is None and result.hold_end_step is None


def test_settle_records_its_start_and_end_steps():
    """settle_start is the step the drive came off; settle_end the last."""
    engine = MockEngine(
        energies=[-100.0] * 4, bottom_reaction=[0.0] * 4,
        top_reaction=[0.0] * 4)
    result = settle_reference(
        engine, _tuned(settle_duration=Quantity(4.0, "ps")))
    assert result.settle_start_step == 0
    assert result.settle_end_step == 4 * 1000


def test_bond_flow_opens_with_the_one_time_cell_relax_then_the_drive():
    """No heal, no gate, no scissors: cell relax, then the drive (§9.1)."""
    engine = MockEngine(
        positions=[_frame(11.0)] * 2, normal_stress=[2000.0] * 2)
    press_and_bond(
        engine, _fake_built(),
        _tuned(press_time_budget=Quantity(1.0, "ps")), _MODEL,
        "pair.data", seed=1)
    stream = engine.received_commands
    relax = stream.index(
        "fix combined_cell_relax all box/relax x 0.0 y 0.0 vmax 0.001")
    drive = _first_drive_index(stream)
    assert relax < drive
    assert not any("heal" in line or "scissors" in line
                   or "relax_cap" in line for line in stream)


def test_contact_test_reads_its_window_and_floor_from_the_study():
    """The trailing-mean window and the stress floor are study knobs.

    With the floor raised above the mock's stress, contact never fires
    even though the gap has closed (DESIGN §5.2, revised 2026-08-28).
    """
    strict = _tuned(contact_stress_floor=Quantity(5000.0, "bar"),
                    press_time_budget=Quantity(4.0, "ps"))
    frames = [_frame(11.0)] * 4
    engine = MockEngine(positions=frames, normal_stress=[2000.0] * 4)
    result = press_and_bond(
        engine, _fake_built(), strict, _MODEL, "pair.data", seed=1)
    assert not result.contact_reached


def test_settle_force_gate_is_statistical_not_a_fixed_floor():
    """A noisy but zero-mean net force settles; a biased one does not.

    DESIGN §5.3 (revised 2026-08-28): the net grip force counts as zero
    when its mean lies within two standard errors of zero, floored by
    noise_floor. The scatter below is far above the 0.05 eV/Å floor that
    used to be the whole test, yet it IS zero on average.
    """
    noisy = [0.6, -0.5, 0.4, -0.7, 0.5, -0.4, 0.3, -0.2]
    engine = MockEngine(
        energies=[-100.0] * 8, bottom_reaction=[0.0] * 8,
        top_reaction=noisy, atom_count=64)
    settled = settle_reference(
        engine, _tuned(settle_duration=Quantity(8.0, "ps")))
    assert settled.report.force_ok
    assert settled.report.net_force_threshold > 0.05

    biased = [value + 3.0 for value in noisy]     # a residual load
    engine = MockEngine(
        energies=[-100.0] * 8, bottom_reaction=[0.0] * 8,
        top_reaction=biased, atom_count=64)
    unsettled = settle_reference(
        engine, _tuned(settle_duration=Quantity(8.0, "ps")))
    assert not unsettled.report.force_ok
    assert unsettled.report.net_force_mean == pytest.approx(3.0)

