"""Unit tests for the engine seam and its mock (sabsim.driver.engine).

The whole point of the seam is that the orchestration can be tested with
no LAMMPS, so these pin the mock's behavior: it IS an Engine, it records
the commands it was handed (rather than running them), and it returns the
preset read-backs the orchestration reads.
"""

import numpy as np

from sabsim.driver.engine import Engine, MockEngine


def test_mock_engine_is_an_engine():
    """The mock satisfies the Engine interface the real adapter will."""
    engine = MockEngine(energy=-5.0, box=np.eye(3) * 10.0, atom_count=64)
    assert isinstance(engine, Engine)


def test_mock_records_commands_instead_of_running_them():
    """Commands are recorded so a test can assert the stream (no run)."""
    engine = MockEngine(energy=-5.0, box=np.eye(3) * 10.0, atom_count=64)
    engine.commands(["units metal", "run 10"])
    engine.commands(["run 20"])
    assert engine.received_commands == ["units metal", "run 10", "run 20"]


def test_mock_returns_the_preset_readbacks():
    """The mock hands back exactly the energy, box, and count it was set."""
    box = np.diag([10.0, 11.0, 12.0])
    engine = MockEngine(energy=-42.0, box=box, atom_count=128)
    assert engine.energy() == -42.0
    assert engine.atom_count() == 128
    assert np.array_equal(engine.box(), box)


def test_mock_step_starts_at_zero_and_advances_on_run():
    """The modelled step tracks ``run N`` so §13 resume can be tested.

    A fresh mock is at step 0; each ``run N`` advances the absolute step
    by N, exactly as LAMMPS's timestep would, while any other command
    leaves it untouched. This is the read-back the pull keys its grip
    displacement to (`PSEUDOCODE.md` §13.5).
    """
    engine = MockEngine(atom_count=64)
    assert engine.step() == 0
    engine.commands(["velocity all create 300.0 12345", "run 1000"])
    assert engine.step() == 1000
    engine.commands(["run 500"])
    assert engine.step() == 1500
    # A non-run command (and a malformed "run") never moves the step.
    engine.commands(["thermo 100", "run"])
    assert engine.step() == 1500


def test_mock_restart_round_trips_the_step(tmp_path):
    """write_restart then read_restart on a FRESH mock restores the step.

    This is the round-trip the resume relies on across a process
    boundary: the killed run's engine saved its step, and a brand-new
    engine picks it up (`PSEUDOCODE.md` §13.2, §13.3). The mock models
    only the step, which is all the orchestration test needs.
    """
    restart_path = str(tmp_path / "engine.restart")
    interrupted = MockEngine(atom_count=64)
    interrupted.commands(["run 7000"])
    interrupted.write_restart(restart_path)

    resumed = MockEngine(atom_count=64)
    assert resumed.step() == 0            # fresh process starts at zero
    resumed.read_restart(restart_path)
    assert resumed.step() == 7000         # restored to where the kill hit
