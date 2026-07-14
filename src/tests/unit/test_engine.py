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
