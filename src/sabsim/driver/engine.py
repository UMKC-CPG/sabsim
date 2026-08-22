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
    def types(self) -> np.ndarray:
        """Return the per-atom LAMMPS type ids as an (N,) int array.

        In atom-id order, row-for-row with :meth:`positions`. The
        amorphized-half read-back (``structure/amorphized_assembly``) needs
        the SPECIES of each surviving atom, not just its position:
        sputtering and the projectile deletion change the composition, so
        the pre-cascade species list no longer matches the survivors.
        Mapped back to chemical symbols through the half's type map, these
        ids reconstitute the ASE ``Atoms`` that crosses the build->assemble
        seam (ARCHITECTURE §4.3).
        """

    @abstractmethod
    def atom_ids(self) -> np.ndarray:
        """Return the survivors' LAMMPS atom ids, ascending, row-for-row
        with :meth:`positions` and :meth:`types`.

        The press/pull control loop pairs positions with the BUILDER's
        per-atom wafer-tag array. That array is keyed by ORIGINAL atom id
        (the build order is the id order, so atom id ``k`` carries tag
        ``tags[k-1]``). When a free surface EVAPORATES or SPUTTERS atoms
        under a long run, the survivors keep their original ids but those
        ids are no longer the dense ``1..N`` set — there are gaps. Exposing
        the surviving ids lets a caller re-index the full tag array onto the
        survivors (``tags[atom_ids - 1]``) so the row-for-row pairing holds
        even after loss. With nothing lost the ids ARE ``1..N`` and the
        re-index is the identity, matching the original contract.
        """

    @abstractmethod
    def normal_stress(self) -> float:
        """Return the global normal (zz) stress, in metal pressure units.

        The dual contact criterion confirms contact only when the
        running average of this has turned positive (§9.3).
        """

    @abstractmethod
    def in_plane_stress(self) -> float:
        """Return the mean in-plane (xx, yy) stress, metal pressure units.

        The average of the pressure tensor's xx and yy components. The
        biaxial-stiffness measurement (DESIGN.md §2.4) reads this across a
        small in-plane strain sweep; the slope of stress vs strain is the
        biaxial modulus. Same sign convention as :meth:`normal_stress` --
        positive under compression -- so a stretched (positive-strain)
        slab reports a negative (tension) stress.
        """

    @abstractmethod
    def grip_reaction(self, side: str) -> float:
        """Return the summed z reaction force (eV/Å) on a grip.

        ``side`` is ``"bottom"`` or ``"top"``. Both are read so the pull
        force curve and the settle-reference net force are available, and
        their sum is a free Newton's-third-law check (§5.4, §9.4).

        SIGN — POSITIVE IN TENSION. This is the force the GRIP exerts on
        the MATERIAL: what a testing machine's load cell reads, positive
        while the grip pulls the material apart. It is therefore the
        NEGATIVE of the force the material exerts on the grip, which is
        what a raw ``fix setforce`` / ``compute reduce sum fz`` hands
        back — an implementation owes the flip (see
        :class:`~sabsim.driver.lammps_engine.LammpsEngine`).

        This convention is part of the CONTRACT, not an implementation
        detail, because it is invisible at the seam: a sign error here
        does not crash, it silently flips the sign of the §8.4 work of
        separation. Stating it is what keeps the mock and the real
        engine from each picking their own — which they did, and
        disagreed, until stage 4 measured it.

        Two consequences worth keeping in view. The §8.4 integrand is
        then positive over a pull, so M1 integrates to a POSITIVE work,
        as "the integral of resisting force" intends. And the flip is
        applied to BOTH grips, never one, so the third-law cancellation
        the settle gate (§9.4) depends on still holds: negating both
        leaves their sum zero at a balanced reference.
        """

    @abstractmethod
    def step(self) -> int:
        """Return the engine's ABSOLUTE MD step count.

        This is the timestep counter the engine keeps across a whole run,
        NOT the pull loop's per-process burst index. The within-run resume
        (§13) keys the pull's grip displacement to THIS value, so that a
        run restarted in a fresh process still reports where the grip
        physically sits: a saved state preserves the step count, a fresh
        burst counter resets to zero (`DESIGN.md` §11.1).
        """

    @abstractmethod
    def write_restart(self, path: str) -> None:
        """Write the engine's complete state to a restart file at ``path``.

        One half of the resume checkpoint pair (§13.2): the atoms, their
        velocities, the box, and the step count — enough to continue the
        dynamics exactly across a process boundary. The progress ledger is
        the other half, written beside it. Callers write to a temporary
        name and rename, so a kill mid-write leaves no half-pair
        (`DESIGN.md` §11.2).
        """

    @abstractmethod
    def read_restart(self, path: str) -> None:
        """Restore the engine's state from the restart file at ``path``.

        The inverse of :meth:`write_restart`: it restores the atoms,
        velocities, box, and step count, but NOT the run's fixes and
        computes. The grips, integrator, and recording are re-issued by
        the caller after this returns (press/pull §13.3), exactly as a
        fresh setup would issue them.
        """

    def is_primary(self) -> bool:
        """Whether THIS rank owns the run's shared-FILE writes (§13.2).

        Under MPI a member runs on many ranks that all issue the same
        collective commands and read the same collective read-backs, so a
        shared artifact must be written by ONE rank or the N ranks race on
        the one path. This reports that rank. It is a CONCRETE default of
        True — a single process is always its own primary, which is what
        every login-node test and the mock want — and only the real
        multi-rank engine overrides it (:class:`~sabsim.driver.lammps_
        engine.LammpsEngine`). The engine state itself is written
        COLLECTIVELY (all ranks, one file), so only the ledger and the
        atomic renames consult this (:func:`sabsim.driver.resume.
        write_checkpoint`).
        """
        return True


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
            types=None,
            normal_stress=None,
            in_plane_stress=None,
            bottom_reaction=None,
            top_reaction=None,
            energies=None,
            primary_rank: bool = True) -> None:
        self.received_commands: list = []
        # Which rank this mock stands in for: True (the default) is a lone
        # primary process, as every single-process test wants; a test sets
        # it False to check that a NON-primary rank writes no shared files
        # (§13.2, :func:`sabsim.driver.resume.write_checkpoint`).
        self._is_primary = primary_rank
        # The modelled ABSOLUTE step count. The mock runs no dynamics, but
        # it TRACKS this so the §13 resume logic can be tested against it:
        # every ``run N`` advances it by N, exactly as a real timestep
        # would, and a restart round-trip carries it across a fresh mock.
        self._step = 0
        self._energy = energy
        self._box = np.eye(3) if box is None else np.asarray(box, float)
        self._atom_count = atom_count
        self._positions = _Script(positions)
        self._types = _Script(types)
        self._normal_stress = _Script(normal_stress)
        self._in_plane_stress = _Script(in_plane_stress)
        self._bottom_reaction = _Script(bottom_reaction)
        self._top_reaction = _Script(top_reaction)
        self._energies = _Script(energies)

    def commands(self, lines: Sequence[str]) -> None:
        """Record the commands, and advance the step on any ``run``.

        The mock runs no dynamics, but it MODELS the step counter so the
        resume logic (§13) can be exercised against it: a ``run N``
        advances the absolute step by N, just as LAMMPS's timestep would,
        so a write_restart/read_restart round-trip restores a meaningful
        step. Every other command is only recorded.
        """
        for line in lines:
            self.received_commands.append(line)
            fields = line.split()
            if len(fields) >= 2 and fields[0] == "run":
                try:
                    self._step += int(fields[1])
                except ValueError:
                    pass          # not a plain "run N"; nothing to advance

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
        """Return the next scripted position frame, else empty.

        The frame's length is remembered so :meth:`atom_ids` can hand back
        a matching id set on the very next call — the pairing the press/pull
        realignment relies on.
        """
        frame = np.asarray(self._positions.next(np.zeros((0, 3))), float)
        self._last_atom_count = int(frame.shape[0])
        return frame

    def atom_ids(self) -> np.ndarray:
        """Return dense ascending ids over the last positions frame.

        The mock models no id gaps (it drops no atoms), so the surviving
        ids are simply ``1..N`` for the N atoms the most recent
        :meth:`positions` returned. Re-indexing a builder tag array by these
        (``tags[atom_ids - 1]``) is therefore the identity, exactly as a
        loss-free real run would be. Falls back to the preset atom count if
        asked before any positions frame has been served.
        """
        count = getattr(self, "_last_atom_count", self._atom_count)
        return np.arange(1, count + 1, dtype=int)

    def types(self) -> np.ndarray:
        """Return the next scripted per-atom type frame, else empty.

        Row-for-row with :meth:`positions`, so a test scripts the two
        together to play back an amorphized half whose composition the
        cascade changed (the read-back the assembly consumes).
        """
        return np.asarray(self._types.next(np.zeros((0,), int)), int)

    def normal_stress(self) -> float:
        """Return the next scripted normal stress, else zero."""
        return float(self._normal_stress.next(0.0))

    def in_plane_stress(self) -> float:
        """Return the next scripted mean in-plane stress, else zero.

        A test scripts a SERIES (one per strain in the sweep) so the
        biaxial-stiffness fit is exercised against a known slope.
        """
        return float(self._in_plane_stress.next(0.0))

    def grip_reaction(self, side: str) -> float:
        """Return the next scripted reaction for the named grip."""
        script = (self._bottom_reaction if side == "bottom"
                  else self._top_reaction)
        return float(script.next(0.0))

    def step(self) -> int:
        """Return the modelled absolute step (advanced by ``run`` cmds)."""
        return self._step

    def write_restart(self, path: str) -> None:
        """Model a restart write by saving JUST the step to ``path``.

        The mock has no atoms to serialize; its whole modelled state is
        the step counter, so a one-line file carrying that integer is a
        faithful stand-in. It is enough to let a FRESH mock read the file
        back and resume at the right step, which is exactly what the §13
        resume logic is tested against.
        """
        with open(path, "w", encoding="utf-8") as restart_file:
            restart_file.write(str(self._step))

    def read_restart(self, path: str) -> None:
        """Restore the modelled step from a mock restart file at ``path``."""
        with open(path, encoding="utf-8") as restart_file:
            self._step = int(restart_file.read().strip())

    def is_primary(self) -> bool:
        """Report the preset rank role (True unless a test sets otherwise)."""
        return self._is_primary
