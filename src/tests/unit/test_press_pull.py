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

from sabsim.driver.commands import RegionGeometry, classical_si_stand_in
from sabsim.driver.engine import MockEngine
from sabsim.driver.press_pull import (
    RunControl,
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
    "..", "..", "..", "dev", "templates", "study_spec.toml"))

_MODEL = classical_si_stand_in({"Si": 1})
_LOWER_Z = np.linspace(0.0, 10.0, 100)   # a wafer-A slab, top surface ~10


def _member():
    """The first template member — a real MemberSpecification."""
    return load_and_validate_study(_TEMPLATE_PATH).members[0]


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
    # Openings ~6, ~4, ~2 (upper-bottom minus lower-top ~9.5); the gap
    # threshold is 2.5, so only the third frame is closed. The stress
    # turns positive over the same three chunks.
    frames = [_frame(15.0), _frame(13.0), _frame(11.0)]
    engine = MockEngine(
        positions=frames, normal_stress=[-1.0, 0.5, 1.0])

    result = press_and_bond(
        engine, _fake_built(), _member(), _MODEL, "pair.data", seed=1)

    assert result.contact_reached
    assert result.chunks_to_contact == 2
    # After contact it holds for press_duration (150 ps / 1 fs steps).
    assert "run 150000" in engine.received_commands


def test_press_reports_no_contact_within_the_budget():
    """A gap that never closes is reported, not forced (§9.3)."""
    engine = MockEngine(positions=[_frame(15.0)], normal_stress=[1.0])
    result = press_and_bond(
        engine, _fake_built(), _member(), _MODEL, "pair.data", seed=1,
        control=RunControl(max_chunks=3))
    assert not result.contact_reached
    assert result.chunks_to_contact is None


# ---------------------------------------------------------------------
# settle_reference — the two zero-load gates (§9.4).
# ---------------------------------------------------------------------

def test_settle_passes_a_flat_balanced_reference():
    """A flat PE and canceling grip reactions settle the reference."""
    engine = MockEngine(
        energies=[-100.0, -100.0, -100.0, -100.0],
        bottom_reaction=[1.0, 1.0, 1.0, 1.0],
        top_reaction=[-1.0, -1.0, -1.0, -1.0],
        atom_count=64)
    result = settle_reference(
        engine, _member(), RunControl(equilibrate_chunks=4))
    assert result.settled
    assert result.report.force_ok and result.report.drift_ok


def test_settle_reports_a_drifting_reference_as_unsettled():
    """A PE still sliding fails the drift gate and is not integrated."""
    engine = MockEngine(
        energies=[-100.0, -100.0, -90.0, -80.0],
        bottom_reaction=[1.0] * 4, top_reaction=[-1.0] * 4,
        atom_count=64)
    result = settle_reference(
        engine, _member(), RunControl(equilibrate_chunks=4))
    assert not result.settled
    assert not result.report.drift_ok


def test_settle_releases_the_drive_and_writes_the_reference():
    """Settle unloads the press, then writes the reference the pull reads."""
    engine = MockEngine(
        energies=[-100.0] * 4, bottom_reaction=[1.0] * 4,
        top_reaction=[-1.0] * 4, atom_count=64)
    result = settle_reference(
        engine, _member(), RunControl(equilibrate_chunks=4),
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
