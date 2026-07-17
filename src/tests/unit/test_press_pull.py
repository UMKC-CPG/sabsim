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

from sabsim.driver.commands import classical_si_stand_in
from sabsim.driver.engine import MockEngine
from sabsim.driver.press_pull import (
    RunControl,
    press_and_bond,
    pull_at_rate,
    settle_reference,
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
