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

    @abstractmethod
    def positions(self) -> np.ndarray:
        """Return the atom positions as an (N, 3) array, in id order.

        The press/pull control loop reads these to measure the interface
        opening between the two density dividing surfaces (§2.6, §9.3).
        """

    @abstractmethod
    def normal_stress(self) -> float:
        """Return the global normal (zz) stress, in metal pressure units.

        The dual contact criterion confirms contact only when the
        running average of this has turned positive (§9.3).
        """

    @abstractmethod
    def grip_reaction(self, side: str) -> float:
        """Return the summed z reaction force (eV/Å) on a grip.

        ``side`` is ``"bottom"`` or ``"top"``. Both are read so the pull
        force curve and the settle-reference net force are available, and
        their sum is a free Newton's-third-law check (§5.4, §9.4).
        """


class _Script:
    """Yield preset values one per call, repeating the last when spent.

    Lets :class:`MockEngine` play back a SEQUENCE of read-backs — an
    opening that closes, a stress that turns positive — so the control
    loop's mid-run decisions are exercised. A read-back with no script
    falls back to a fixed value.
    """

    def __init__(self, values) -> None:
        self._values = list(values) if values is not None else []
        self._index = 0

    def next(self, fallback):
        """Return the next scripted value, or ``fallback`` if unscripted."""
        if not self._values:
            return fallback
        value = self._values[min(self._index, len(self._values) - 1)]
        self._index += 1
        return value


class MockEngine(Engine):
    """A canned :class:`Engine` for login-node testing — no physics.

    It records every command it is handed (so a test can assert the
    stream that WOULD run) and returns preset read-backs. The static
    read-backs (``energy``, ``box``, ``atom_count``) suit the bulk relax
    (slice 4); the SCRIPTED read-backs (``positions``, ``normal_stress``,
    the grip reactions, and a per-call ``energies`` series) let a test
    play the press closing and the pull separating past the control loop
    (slice 5). It relaxes and steps nothing — its job is to exercise the
    orchestration, not to compute.
    """

    def __init__(
            self,
            energy: float = 0.0,
            box: np.ndarray | None = None,
            atom_count: int = 0,
            positions=None,
            normal_stress=None,
            bottom_reaction=None,
            top_reaction=None,
            energies=None) -> None:
        self.received_commands: list = []
        self._energy = energy
        self._box = np.eye(3) if box is None else np.asarray(box, float)
        self._atom_count = atom_count
        self._positions = _Script(positions)
        self._normal_stress = _Script(normal_stress)
        self._bottom_reaction = _Script(bottom_reaction)
        self._top_reaction = _Script(top_reaction)
        self._energies = _Script(energies)

    def commands(self, lines: Sequence[str]) -> None:
        """Record the commands rather than run them."""
        self.received_commands.extend(lines)

    def energy(self) -> float:
        """Return the next scripted energy, else the fixed one."""
        return float(self._energies.next(self._energy))

    def box(self) -> np.ndarray:
        """Return the preset (pretend-relaxed) simulation box."""
        return self._box

    def atom_count(self) -> int:
        """Return the preset atom count."""
        return self._atom_count

    def positions(self) -> np.ndarray:
        """Return the next scripted position frame, else empty."""
        return np.asarray(self._positions.next(np.zeros((0, 3))), float)

    def normal_stress(self) -> float:
        """Return the next scripted normal stress, else zero."""
        return float(self._normal_stress.next(0.0))

    def grip_reaction(self, side: str) -> float:
        """Return the next scripted reaction for the named grip."""
        script = (self._bottom_reaction if side == "bottom"
                  else self._top_reaction)
        return float(script.next(0.0))
