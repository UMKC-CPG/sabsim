"""Unit tests for the resume checkpoint primitives (driver.resume).

These pin the honest core of the §13 checkpoint pair with no LAMMPS: the
pair is written atomically and read back only when BOTH halves are
present, and a ledger that ran past the last saved state is trimmed to it.
Everything runs against ``MockEngine``, which models just the step counter
the checkpoint stamps and restores.
"""

import json
import os

from sabsim.driver.engine import MockEngine
from sabsim.driver.resume import (
    Checkpoint,
    Ledger,
    load_checkpoint,
    reconcile,
    write_checkpoint,
)


def _sample_ledger() -> Ledger:
    """A small four-sample ledger to round-trip and trim."""
    return Ledger(
        sample_steps=[1000, 2000, 3000, 4000],
        displacement=[0.1, 0.2, 0.3, 0.4],
        force=[1.0, 0.8, 0.4, 0.05],
        opening=[2.0, 4.0, 6.5, 9.0],
        bridges=[12.0, 5.0, 1.0, 0.0],
        starting_atom_count=8799,
        input_hash="")


def test_write_then_load_round_trips_the_pair(tmp_path):
    """A written pair loads back with its ledger intact and step stamped.

    ``write_checkpoint`` stamps ``saved_step`` from the engine, so the
    ledger that comes back records exactly the step the state was saved at
    (§13.2).
    """
    checkpoint_dir = str(tmp_path / "checkpoints")
    engine = MockEngine(atom_count=8799)
    engine.commands(["run 4000"])            # engine now at step 4000
    ledger = _sample_ledger()

    write_checkpoint(engine, ledger, checkpoint_dir)
    loaded = load_checkpoint(checkpoint_dir)

    assert isinstance(loaded, Checkpoint)
    assert loaded.ledger.saved_step == 4000
    assert loaded.ledger.sample_steps == [1000, 2000, 3000, 4000]
    assert loaded.ledger.bridges == [12.0, 5.0, 1.0, 0.0]
    assert loaded.ledger.starting_atom_count == 8799
    assert os.path.exists(loaded.engine_state)


def test_write_leaves_no_temporary_files(tmp_path):
    """After a clean write only the two final files remain — no .tmp.

    The temp-then-rename discipline (§13.2) must not leave the partial
    names behind, or a later reader could not tell a finished pair from a
    write that was interrupted.
    """
    checkpoint_dir = str(tmp_path / "checkpoints")
    engine = MockEngine(atom_count=64)
    engine.commands(["run 1000"])

    write_checkpoint(engine, _sample_ledger(), checkpoint_dir)

    present = sorted(os.listdir(checkpoint_dir))
    assert present == ["engine.restart", "ledger.json"]


def test_only_the_primary_rank_writes_the_pair(tmp_path):
    """A non-primary rank writes no shared files, so no pair appears.

    Under MPI the engine state is written collectively, but the ledger and
    the atomic renames are the PRIMARY rank's alone, or the ranks race on
    one path (§13.2). A non-primary rank must therefore leave no complete
    checkpoint; the primary rank, given the same call, writes the pair.
    """
    checkpoint_dir = str(tmp_path / "checkpoints")

    non_primary = MockEngine(atom_count=64, primary_rank=False)
    non_primary.commands(["run 1000"])
    write_checkpoint(non_primary, _sample_ledger(), checkpoint_dir)
    # No ledger, so no checkpoint — a non-primary rank made nothing usable.
    assert load_checkpoint(checkpoint_dir) is None
    assert not os.path.exists(os.path.join(checkpoint_dir, "ledger.json"))

    primary = MockEngine(atom_count=64, primary_rank=True)
    primary.commands(["run 1000"])
    write_checkpoint(primary, _sample_ledger(), checkpoint_dir)
    assert load_checkpoint(checkpoint_dir) is not None


def test_load_reports_none_on_a_half_pair(tmp_path):
    """A lone restart (or lone ledger) is treated as no checkpoint at all.

    The pair discipline of §13.2 refuses to restore from half a pair, so
    a directory with only one file must load as ``None`` — a fresh start,
    not a corrupt resume.
    """
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir()

    # Only the engine half present.
    (checkpoint_dir / "engine.restart").write_text("4000")
    assert load_checkpoint(str(checkpoint_dir)) is None

    # Swap to only the ledger half present.
    (checkpoint_dir / "engine.restart").unlink()
    (checkpoint_dir / "ledger.json").write_text(
        json.dumps({"sample_steps": []}))
    assert load_checkpoint(str(checkpoint_dir)) is None


def test_load_reports_none_when_nothing_is_there(tmp_path):
    """An empty (or absent) directory is a fresh start, never a resume."""
    assert load_checkpoint(str(tmp_path / "does_not_exist")) is None


def test_reconcile_drops_samples_past_the_saved_step():
    """A ledger that ran past the saved state is trimmed back to it.

    The engine is saved on a coarser cadence than the ledger is appended
    (§13.2), so on resume the ledger can carry samples beyond the restored
    step. Those are dropped, and ``saved_step`` is set to where the atoms
    actually are, so the record and the restored atoms agree.
    """
    reconciled = reconcile(_sample_ledger(), restored_step=2000)

    assert reconciled.sample_steps == [1000, 2000]
    assert reconciled.displacement == [0.1, 0.2]
    assert reconciled.force == [1.0, 0.8]
    assert reconciled.opening == [2.0, 4.0]
    assert reconciled.bridges == [12.0, 5.0]
    assert reconciled.saved_step == 2000
    # The scalars ride through untouched — the baseline is not re-measured.
    assert reconciled.starting_atom_count == 8799


def test_reconcile_keeps_everything_when_there_is_no_overhang():
    """When the saved step is at or past the last sample, nothing drops."""
    reconciled = reconcile(_sample_ledger(), restored_step=4000)

    assert reconciled.sample_steps == [1000, 2000, 3000, 4000]
    assert reconciled.saved_step == 4000
