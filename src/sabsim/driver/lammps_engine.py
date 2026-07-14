"""The real LAMMPS :class:`Engine` adapter — an UNVALIDATED skeleton.

This is the one piece the mock cannot de-risk (see the slice-4/5 ledger).
It implements the :class:`~sabsim.driver.engine.Engine` seam by wrapping
the LAMMPS Python binding, so the same orchestration that runs against
``MockEngine`` on the login node runs against real LAMMPS on a compute
node — unchanged — once this adapter is filled in and debugged.

**What is real here and what is not.** Every method below contains the
best-effort binding call it should use; none has been RUN against live
LAMMPS. The binding's API SURFACE is confirmed, though: a pure import
(no instance, no run) on this environment's LAMMPS verified the
constructor keywords (``cmdargs``, ``comm``), the three ``LMP_*``
constants, and that every method called here exists (``commands_list``,
``get_thermo``, ``extract_box``, ``extract_fix``, ``extract_compute``,
``get_natoms``). What remains are RUNTIME facts an import cannot show,
each marked ``# VERIFY`` and to be checked on a compute node: the
``extract_fix`` component index and its 0-vs-1 base, the SIGN and units
of the extracted stress and the grip reactions, and that the gathered
atom order matches the builder's tag order. This module imports cleanly
with NO LAMMPS present too (the binding is imported lazily inside the
constructor), so its shape is reviewable and its interface-completeness
testable on the login node; nothing instantiates it until the cluster.

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
        is valid after a ``run`` (or a ``run 0``). VERIFY it reflects the
        current state and not a stale step when called mid-loop.
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

        ``gather_atoms`` returns every atom ordered by id on every rank,
        which is what the control loop needs to split by wafer tag.
        VERIFY the id order matches the builder's write order (the tag
        array in :class:`~sabsim.structure.slab_builder.BuiltPair`), so a
        position row and its tag line up.
        """
        return self._lmp.numpy.gather_atoms("x", 1, 3).reshape(-1, 3)

    def normal_stress(self) -> float:
        """Return the global normal (zz) stress, in metal pressure units.

        Read as the ``pzz`` thermo keyword (the zz pressure-tensor
        component). VERIFY the SIGN convention the dual contact criterion
        expects: §9.3 wants this POSITIVE when the surfaces load each
        other; LAMMPS reports pressure positive under compression, so a
        sign flip may be needed here.
        """
        return float(self._lmp.get_thermo("pzz"))     # VERIFY sign

    def grip_reaction(self, side: str) -> float:
        """Return the summed z reaction force (eV/Å) on a grip.

        The bottom grip is held by ``fix setforce``, which exposes the
        total pre-zero force on the group as a global 3-vector; the top
        grip's reaction is the ``compute reduce sum fz`` scalar. VERIFY:
        the ``extract_fix`` component index (is fz index 2, and is the
        index 0- or 1-based in this binding?), and the SIGN of each — the
        pull curve wants the force resisting the drive.
        """
        if side == "bottom":
            return float(self._lmp.extract_fix(
                _BOTTOM_GRIP_FIX, self._style_global, self._type_vector,
                2, 0))                                  # VERIFY index/base
        return float(self._lmp.extract_compute(
            _TOP_GRIP_COMPUTE, self._style_global, self._type_scalar))
