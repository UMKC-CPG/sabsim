"""Unit tests for the out-of-process cascade engine (ARCHITECTURE §4.3).

The subprocess RUN itself needs a GPU node and the deepmd bundle, so it is
node-validated, not unit-tested. What IS pure and tested here: the engine-
prefix resolution refuses loudly rather than falling through silently, and
the dump reader parses the handoff structure back into the positions and
type ids the gate and the amorphized-half snapshot consume — including a
reordered-column dump, since the reader trusts the ``ITEM: ATOMS`` header
rather than a fixed column order.
"""

import numpy as np
import pytest

from sabsim.driver.cascade_subprocess import (
    read_dump_structure,
    resolve_cascade_engine_prefix,
)


def _write_dump(path, atom_header, rows) -> None:
    """Write a minimal custom LAMMPS dump with the given ATOMS columns."""
    lines = [
        "ITEM: TIMESTEP", "0",
        "ITEM: NUMBER OF ATOMS", str(len(rows)),
        "ITEM: BOX BOUNDS pp pp ff",
        "0.0 10.0", "0.0 10.0", "0.0 20.0",
        f"ITEM: ATOMS {atom_header}",
    ]
    lines += rows
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_read_dump_structure_parses_positions_and_types(tmp_path):
    """The reader returns id-sorted positions and per-atom type ids."""
    dump = tmp_path / "activated.dump"
    # Deliberately out of id order to prove the reader sorts by id.
    _write_dump(dump, "id type x y z", [
        "3 2 3.0 3.1 3.2",
        "1 1 1.0 1.1 1.2",
        "2 1 2.0 2.1 2.2",
    ])
    positions, type_ids = read_dump_structure(str(dump))

    assert np.allclose(positions, [[1.0, 1.1, 1.2],
                                   [2.0, 2.1, 2.2],
                                   [3.0, 3.1, 3.2]])
    # Types follow the same id order: atoms 1 and 2 are Si (1), atom 3 Ar (2).
    assert list(type_ids) == [1, 1, 2]


def test_read_dump_structure_trusts_the_header_column_order(tmp_path):
    """A reordered ATOMS header still parses — columns are read by name."""
    dump = tmp_path / "reordered.dump"
    _write_dump(dump, "type z id x y", [
        "1 9.9 1 1.0 1.1",
        "2 8.8 2 2.0 2.1",
    ])
    positions, type_ids = read_dump_structure(str(dump))

    # z came from the 2nd column, x/y from the 4th/5th, id from the 3rd.
    assert np.allclose(positions, [[1.0, 1.1, 9.9],
                                   [2.0, 2.1, 8.8]])
    assert list(type_ids) == [1, 2]


def test_resolve_engine_prefix_missing_is_a_loud_stop(monkeypatch):
    """No prefix is a loud failure naming the variable, not a fall-through."""
    monkeypatch.delenv("SABSIM_CASCADE_ENGINE_PREFIX", raising=False)
    with pytest.raises(RuntimeError) as caught:
        resolve_cascade_engine_prefix()
    assert "SABSIM_CASCADE_ENGINE_PREFIX" in str(caught.value)


def test_resolve_engine_prefix_nonexistent_dir_is_a_loud_stop(monkeypatch):
    """A prefix that names no directory is refused, not silently used."""
    monkeypatch.setenv(
        "SABSIM_CASCADE_ENGINE_PREFIX", "/no/such/bundle/prefix")
    with pytest.raises(RuntimeError) as caught:
        resolve_cascade_engine_prefix()
    assert "does not exist" in str(caught.value)


def test_resolve_engine_prefix_returns_existing(monkeypatch, tmp_path):
    """A real directory resolves through unchanged."""
    monkeypatch.setenv("SABSIM_CASCADE_ENGINE_PREFIX", str(tmp_path))
    assert resolve_cascade_engine_prefix() == str(tmp_path)
