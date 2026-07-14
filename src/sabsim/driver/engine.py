"""The narrow seam between the pipeline and LAMMPS (ARCHITECTURE §4.1).

Everything the driver does to a live simulation goes through one small
interface, :class:`Engine`. The orchestration — the bulk relaxation
(slice 4) and later the press/pull control loop (slice 5) — talks ONLY
to this interface, so it can be written and fully tested with no LAMMPS
present, against :class:`MockEngine`. The real adapter that wraps the
LAMMPS Python binding is a SECOND implementation of the same interface;
swapping it in changes nothing above this seam.

The interface is deliberately shaped to mirror calls the LAMMPS binding
actually supports — issue commands, then extract a value — so the mock is
not wishful: ``commands`` maps to ``lmp.commands_list``; ``energy`` to a
thermo/compute extract; ``box`` to the simulation box; ``atom_count`` to
``lmp.get_natoms``. Slice 5 extends the interface with the per-atom
read-backs the press/pull needs (positions, forces, normal stress, grip
reactions); slice 4 needs only the four below.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

import numpy as np


class Engine(ABC):
    """The one interface the orchestration uses to drive a simulation.

    An implementation issues LAMMPS commands and reads a handful of
    quantities back. Two implementations exist: :class:`MockEngine` (for
    login-node testing) and, later, the real LAMMPS-binding adapter. The
    orchestration cannot tell them apart, which is what lets every line
    of control logic be tested before any compute-node run.
    """

    @abstractmethod
    def commands(self, lines: Sequence[str]) -> None:
        """Issue an ordered list of LAMMPS command strings (§9.2)."""

    @abstractmethod
    def energy(self) -> float:
        """Return the current potential energy in eV."""

    @abstractmethod
    def box(self) -> np.ndarray:
        """Return the current simulation box as a 3x3 array of vectors."""

    @abstractmethod
    def atom_count(self) -> int:
        """Return the number of atoms currently in the simulation."""


class MockEngine(Engine):
    """A canned :class:`Engine` for login-node testing — no physics.

    It records every command it is handed (so a test can assert the
    stream that WOULD run) and returns preset read-backs. It relaxes
    nothing: its job is to exercise the orchestration, not to compute. A
    test hands it the relaxed box and energy it should pretend to have
    reached, and checks that the orchestration derives the right result
    from them.
    """

    def __init__(
            self,
            energy: float,
            box: np.ndarray,
            atom_count: int) -> None:
        self.received_commands: list = []
        self._energy = energy
        self._box = np.asarray(box, dtype=float)
        self._atom_count = atom_count

    def commands(self, lines: Sequence[str]) -> None:
        """Record the commands rather than run them."""
        self.received_commands.extend(lines)

    def energy(self) -> float:
        """Return the preset potential energy."""
        return self._energy

    def box(self) -> np.ndarray:
        """Return the preset (pretend-relaxed) simulation box."""
        return self._box

    def atom_count(self) -> int:
        """Return the preset atom count."""
        return self._atom_count
