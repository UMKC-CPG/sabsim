"""The real LAMMPS :class:`Engine` adapter — VALIDATED against LAMMPS.

This is the one piece the mock cannot de-risk (see the slice-4/5 ledger).
It implements the :class:`~sabsim.driver.engine.Engine` seam by wrapping
the LAMMPS Python binding, so the same orchestration that runs against
``MockEngine`` on the login node runs against real LAMMPS on a compute
node, unchanged.

**Validation status (stage 4, LAMMPS 22 Jul 2025, 1 and 4 MPI ranks).**
Every read-back below has now been RUN against live LAMMPS and checked
against an independent reference — a second LAMMPS code path, or a known
physical state — rather than against its own assumption. Resolved:
``extract_fix``'s component index is 0-BASED (fz is index 2), ``pzz`` is
positive in compression and so already matches what §9.3 asks for, and
``gather_atoms`` returns atoms in the builder's own write order under
both 1 and 4 ranks.

Two things the walking skeleton got WRONG, which only a live engine could
show, are worth remembering as evidence for why this seam is worth its
cost. ``positions`` called ``lmp.numpy.gather_atoms``, which does not
exist — the numpy wrapper has no such method, and the pure import that
"confirmed the API surface" never listed it. And the grip reactions came
back with the OPPOSITE sign to the one the mock scripted, which would
have integrated §8.4 to a negative work of separation while failing
nothing: see :meth:`LammpsEngine.grip_reaction`.

The module still imports cleanly with NO LAMMPS present (the binding is
imported lazily inside the constructor), so its shape stays reviewable
and its interface-completeness testable on the login node.

**Where it runs.** LAMMPS runs on a COMPUTE node, launched with
``srun -n N python``; it MUST NOT be spawned from the login node. Under
MPI each rank constructs one :class:`LammpsEngine` with the shared
communicator, and the single persistent instance lives across the whole
press -> settle -> pull sequence (ARCHITECTURE.md §4.1) — the point of a
persistent in-process driver.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from sabsim.driver.engine import Engine

# The fix/compute identifiers the driver reads back from. These are the
# names slice 2's command generators emit (`fix hold_bottom ... setforce`
# and `compute top_reaction top_grip reduce sum fz`), so the adapter and
# the command stream must agree on them.
_BOTTOM_GRIP_FIX = "hold_bottom"
_TOP_GRIP_COMPUTE = "top_reaction"


class LammpsEngine(Engine):
    """An :class:`Engine` backed by a live LAMMPS instance (compute node).

    Construct one per MPI rank with the shared communicator; it holds a
    persistent LAMMPS handle for the whole member run. Use it as a
    context manager (``with LammpsEngine(...) as engine:``) so the handle
    is always closed, or call :meth:`close` explicitly.
    """

    def __init__(
            self,
            command_line_args: Sequence[str] | None = None,
            comm=None) -> None:
        # Lazy import: keep this module loadable with no LAMMPS present,
        # so the login node can review and interface-test the adapter.
        from lammps import (
            LMP_STYLE_GLOBAL,
            LMP_TYPE_SCALAR,
            LMP_TYPE_VECTOR,
            lammps,
        )

        self._style_global = LMP_STYLE_GLOBAL
        self._type_vector = LMP_TYPE_VECTOR
        self._type_scalar = LMP_TYPE_SCALAR
        # cmdargs quiets the log/screen; comm is the mpi4py communicator
        # under `srun -n N python` (None -> LAMMPS's own MPI_COMM_WORLD).
        self._lmp = lammps(
            cmdargs=list(command_line_args) if command_line_args else None,
            comm=comm)

    # -- lifecycle ----------------------------------------------------

    def close(self) -> None:
        """Free the LAMMPS instance (and its MPI resources)."""
        if self._lmp is not None:
            self._lmp.close()
            self._lmp = None

    def __enter__(self) -> "LammpsEngine":
        return self

    def __exit__(self, *exception) -> None:
        self.close()

    # -- the Engine interface -----------------------------------------

    def commands(self, lines: Sequence[str]) -> None:
        """Issue an ordered list of commands (maps to commands_list)."""
        self._lmp.commands_list(list(lines))

    def energy(self) -> float:
        """Return the potential energy in eV (the ``pe`` thermo value).

        ``get_thermo`` reads the most recent thermo evaluation, so this
        is valid after a ``run`` (or a ``run 0``).

        VERIFIED on a compute node (stage 4) that the value is FRESH and
        not cached across a chunked loop: five successive ``run 50``
        chunks under NVE at 300 K returned five distinct energies. This
        matters because the §9.4 settle gate reads this once per chunk
        and tests the series for drift — a cached value would read as a
        perfectly flat line and pass a reference that never settled.
        """
        return float(self._lmp.get_thermo("pe"))

    def box(self) -> np.ndarray:
        """Return the simulation box as a 3x3 array of cell vectors.

        Built from ``extract_box`` in the LAMMPS triclinic convention:
        a along x, b with an xy tilt, c with xz/yz tilts.
        """
        boxlo, boxhi, xy, yz, xz, _periodicity, _changed = (
            self._lmp.extract_box())
        length_x = boxhi[0] - boxlo[0]
        length_y = boxhi[1] - boxlo[1]
        length_z = boxhi[2] - boxlo[2]
        return np.array([
            [length_x, 0.0, 0.0],
            [xy, length_y, 0.0],
            [xz, yz, length_z],
        ])

    def atom_count(self) -> int:
        """Return the number of atoms (maps to get_natoms)."""
        return int(self._lmp.get_natoms())

    def positions(self) -> np.ndarray:
        """Return the atom positions as an (N, 3) array, in atom-id order.

        ``gather_atoms`` is COLLECTIVE: every rank gets all N atoms
        ordered by atom id, regardless of which rank owns them. That is
        what the control loop needs, because it pairs this array
        row-for-row with the builder's tag array (``press_pull`` §9.5) —
        a rank-local view would pair a position with another atom's tag.
        Note this lives on the plain LAMMPS object and NOT on its
        ``numpy`` wrapper, which has no ``gather_atoms``; it hands back a
        flat ctypes buffer of 3N doubles (``dtype=1``, ``count=3``) that
        is copied into a real array here.

        VERIFIED on a compute node (stage 4): the gathered id order is
        1..N and matches the builder's write order exactly, under both 1
        and 4 MPI ranks, so a position row and its tag line up.
        """
        flat_positions = self._lmp.gather_atoms("x", 1, 3)
        return np.array(flat_positions, dtype=float).reshape(-1, 3)

    def types(self) -> np.ndarray:
        """Return per-atom LAMMPS type ids as an (N,) int array, id-ordered.

        The species half of the same collective read-back as
        :meth:`positions`: ``gather_atoms("type", ...)`` gathers every
        atom's integer type across ranks in atom-id order, so type row i
        and position row i belong to the same atom. The count is 1 int per
        atom (``dtype=0`` for int, ``count=1``), against ``x``'s 3 doubles.
        The amorphized-half read-back needs this because sputtering and the
        projectile deletion change the composition, so the pre-cascade
        species list no longer describes the survivors (Engine contract).
        """
        flat_types = self._lmp.gather_atoms("type", 0, 1)
        return np.array(flat_types, dtype=int)

    def normal_stress(self) -> float:
        """Return the global normal (zz) stress, in metal pressure units.

        Read as the ``pzz`` thermo keyword (the zz pressure-tensor
        component). NO sign flip is applied, and none is needed.

        VERIFIED on a compute node (stage 4) against bulk silicon held at
        three known volumes, which pins the convention from the physics
        rather than from the documentation:

        ==================  ==================
        state               pzz
        ==================  ==================
        compressed (a*0.98)     +67820 bar
        near equilibrium           -76 bar
        dilated    (a*1.02)     -54800 bar
        ==================  ==================

        So LAMMPS reports pressure POSITIVE under compression, and §9.3
        wants this positive exactly when the surfaces load (compress)
        each other. The two conventions already agree — the skeleton's
        worry that "a sign flip may be needed" was unfounded.
        """
        return float(self._lmp.get_thermo("pzz"))

    def grip_reaction(self, side: str) -> float:
        """Return the summed z reaction force (eV/Å) on a grip.

        The bottom grip is held by ``fix setforce``, which exposes the
        total pre-zero force on the group as a global 3-vector; the top
        grip's reaction is the ``compute reduce sum fz`` scalar.

        The component index is VERIFIED on a compute node (stage 4)
        against an independent ``compute reduce sum fx/fy/fz`` on the
        same group, with the atoms randomly displaced so the three
        components were distinct and no degeneracy could hide a mix-up:
        the index is 0-BASED, so fz is index 2 (``i=3`` raises), and both
        read-backs reproduced their reference to all printed digits. The
        indexing below is therefore correct as written.

        SIGN — the ``-`` below is REQUIRED by the Engine contract, which
        asks for the force the GRIP exerts on the MATERIAL (positive in
        tension, the load-cell sense). LAMMPS reports the opposite: both
        ``fix setforce``'s stored vector and ``compute reduce sum fz``
        give the force the MATERIAL exerts ON the grip. Measured on a
        compute node (stage 4), displacing ONLY the top grip so the
        wafer genuinely strains, RAW LAMMPS values were:

        ==========================  ==================
        drive (top grip only)       raw fz
        ==========================  ==================
        pulled up   (stretch)          -2.3034 eV/Å
        held        (rest)             +0.0049 eV/Å
        pushed down (squash)           +3.4269 eV/Å
        ==========================  ==================

        Raw, a pull reads NEGATIVE, which would have integrated §8.4 to
        a negative work of separation without ever failing — the mock
        meanwhile scripted a pull POSITIVE. Negating restores tension-
        positive and reconciles the two.

        The flip is applied to BOTH sides deliberately. Negating one
        grip only would break the §9.4 settle gate, whose third-law
        check reads ``|top + bottom|`` and expects zero at a balanced
        reference: with one side flipped that sum becomes ``2*|F|`` and
        a perfectly settled state would read as maximally unsettled.
        Negating both leaves the sum invariant.
        """
        if side == "bottom":
            return -float(self._lmp.extract_fix(
                _BOTTOM_GRIP_FIX, self._style_global, self._type_vector,
                2, 0))
        return -float(self._lmp.extract_compute(
            _TOP_GRIP_COMPUTE, self._style_global, self._type_scalar))

    # -- resume seam (§13) --------------------------------------------

    def step(self) -> int:
        """Return the absolute timestep (the ``step`` thermo value).

        Like :meth:`energy`, this reads the most recent thermo evaluation,
        so it is valid after a ``run`` (or ``run 0``). The resume keys the
        pull's grip displacement to this rather than to a per-process
        burst index, so a restarted run stays consistent (`DESIGN.md`
        §11.1, `PSEUDOCODE.md` §13.5).
        """
        return int(self._lmp.get_thermo("step"))

    def write_restart(self, path: str) -> None:
        """Write a LAMMPS binary restart to ``path`` (§13.2 pair half).

        Maps to the ``write_restart`` command, which saves the atoms,
        their velocities, the box, and the timestep — the engine half of
        the checkpoint pair. The caller writes to a temporary name and
        renames, so a kill mid-write never leaves a half-pair.
        """
        self._lmp.commands_list([f"write_restart {path}"])

    def read_restart(self, path: str) -> None:
        """Read a LAMMPS binary restart from ``path``, restoring the state.

        Maps to the ``read_restart`` command. It restores atoms,
        velocities, box, and timestep, but NOT fixes and computes — the
        grips, integrator, and recording are re-issued by the caller after
        this returns (`PSEUDOCODE.md` §13.3), as a fresh setup would.
        """
        self._lmp.commands_list([f"read_restart {path}"])
