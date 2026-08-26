"""Derive the working lattice by relaxing the bulk (DESIGN.md §2.2).

This is slice 4: the FIRST use of the force engine, and the smallest.
DESIGN.md §2.2 forbids building the box on the CIF's published lattice —
a model has its OWN equilibrium spacing, and building on someone else's
leaves it strained (prior art's −30 to −40 GPa at step zero). So the
working lattice is DERIVED here: relax a bulk block to zero pressure
under the current model and read the equilibrium cell back. At the cold
start (§2.2) "the current model" is the universal foundation MLIP; the
same routine re-derives the lattice under the trained committee once it
exists. This is exactly where the walking skeleton's hardcoded 5.43 Å is
retired.

The routine is written against the :class:`~sabsim.driver.engine.Engine`
seam, so it is fully tested against ``MockEngine`` here; the real
LAMMPS-binding adapter drops in unchanged behind the same interface on a
compute node. The relaxation itself is a minimization, not dynamics, so
it is cheap and deterministic given the potential.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from sabsim.driver.commands import ForceModel, force_model_commands


@dataclass(frozen=True)
class MinimizeSettings:
    """Convergence settings for the bulk minimization (§2.2).

    These are numerical knobs — their influence on the answer must vanish
    as they tighten (DESIGN.md §1.2). The defaults are reasonable
    starting points, flagged as a §2.2 numeric follow-on, not converged
    values; ``energy_tolerance`` and ``force_tolerance`` are LAMMPS's
    ``etol``/``ftol``.
    """

    energy_tolerance: float = 1.0e-8
    force_tolerance: float = 1.0e-8
    max_iterations: int = 1000
    max_evaluations: int = 10000


@dataclass(frozen=True)
class BulkRelaxation:
    """The result of relaxing a bulk block under the current model (§2.2).

    The derived, model-consistent geometry the structure builder then cuts
    slabs on — NOT the CIF's published scale. ``conventional_cell`` is the
    FULL relaxed conventional cell (the replicated block's cell divided by
    the replication), which supports ANY symmetry — cubic, tetragonal,
    triclinic — and is what the crystal is rescaled to. ``lattice_
    constant`` is the cubic convenience value (the cell edge length) kept
    for the report and the cubic case; it is meaningful only when the cell
    is cubic. ``potential_energy`` is the relaxed bulk energy, which the
    surface-energy calculation (§2.5) later references per atom.
    """

    relaxed_cell: np.ndarray       # 3x3 relaxed block box vectors, Å
    conventional_cell: np.ndarray  # 3x3 relaxed conventional cell, Å
    lattice_constant: float        # cubic convenience edge, Å
    potential_energy: float        # relaxed bulk energy, eV
    atom_count: int


def bulk_relax_commands(
        data_file: str,
        force_model: ForceModel,
        settings: MinimizeSettings = MinimizeSettings(),
        coupling: str = "iso") -> list:
    """The LAMMPS command stream for a variable-cell bulk relaxation.

    A bulk block is periodic in ALL three directions (``p p p``, unlike
    the open-z slab box), loaded with the given force model, and
    minimized while the cell relaxes to zero pressure (``fix box/relax``).
    ``coupling`` is ``iso`` for a cubic crystal (uniform scaling keeps the
    cell cubic, so one lattice constant results); ``aniso`` or ``tri``
    suit lower-symmetry crystals, a §2 follow-on.

    When ``force_model`` is a message-passing MLIP (``needs_atom_map`` —
    the universal foundation model, §4.7), ``atom_modify map yes`` is
    inserted right after ``atom_style`` and BEFORE the ``read_data`` that
    creates the atoms: the graph network gathers per-atom features across
    the neighbor graph, so the global atom map must already exist. A
    model whose ``needs_atom_map`` is false leaves the preamble untouched.
    """
    lines = [
        "units metal",
        "atom_style atomic",
        "boundary p p p",
        f"read_data {data_file}",
        *force_model_commands(force_model),
        f"fix relax_box all box/relax {coupling} 0.0 vmax 0.001",
        "min_style cg",
        f"minimize {settings.energy_tolerance:g} "
        f"{settings.force_tolerance:g} "
        f"{settings.max_iterations} {settings.max_evaluations}",
    ]
    if force_model.needs_atom_map:
        # After atom_style (index 1), before read_data: the atom map the
        # GNN neighbor gather needs must exist when the atoms are created.
        lines.insert(2, "atom_modify map yes")
    return lines


def bulk_relax_subprocess_script(
        data_file: str,
        force_model: ForceModel,
        relaxed_data_file: str,
        settings: MinimizeSettings = MinimizeSettings(),
        coupling: str = "iso") -> list:
    """The bulk box-relax as a STANDALONE script for the bundle engine (§4.4).

    The same relaxation as :func:`bulk_relax_commands`, but terminated with
    a ``write_data`` so the caller reads the relaxed cell back from a FILE
    rather than from a live :class:`Engine`. This is the out-of-process
    path taken when the model is the universal MLIP (DESIGN §4.7): that
    model lives in deepmd's own self-contained bundle and cannot load into
    sabsim's in-process engine (ARCHITECTURE §4.1/§4.4), so the §2.2
    lattice derivation runs as the bundle's ``lmp -in <script>`` exactly as
    the cascade does, and hands its geometry back through the file handoff.
    ``nocoeff`` keeps the written file to structure + box — all the reader
    needs — instead of echoing pair coefficients we never read back.
    """
    return [
        *bulk_relax_commands(data_file, force_model, settings, coupling),
        f"write_data {relaxed_data_file} nocoeff",
    ]


def read_data_box(data_path: str) -> tuple[np.ndarray, int]:
    """Parse the periodic cell (and atom count) from a LAMMPS data file.

    The out-of-process bulk relax writes its relaxed geometry with
    ``write_data``; this reads the cell back (the §4.4 file handoff). A
    data file states the box DIRECTLY as its edges — ``xlo xhi``,
    ``ylo yhi``, ``zlo zhi`` and the optional ``xy xz yz`` tilts — so the
    cell vectors follow with NO bound-vs-actual conversion (unlike a dump's
    ``ITEM: BOX BOUNDS``, which reports shifted bounds): ``a =
    (xhi-xlo, 0, 0)``, ``b = (xy, yhi-ylo, 0)``, ``c = (xz, yz, zhi-zlo)``.
    Returns ``(cell 3x3 in Å, atom_count)``; reading stops at the ``Atoms``
    section, since the whole box lives in the header above it.
    """
    x_lo = x_hi = y_lo = y_hi = z_lo = z_hi = None
    tilt_xy = tilt_xz = tilt_yz = 0.0
    atom_count = None
    with open(data_path, encoding="utf-8") as data_file:
        for raw_line in data_file:
            line = raw_line.strip()
            if line.startswith("Atoms"):
                break                 # header is done; box is above here
            if line.endswith("xlo xhi"):
                x_lo, x_hi = (float(value) for value in line.split()[:2])
            elif line.endswith("ylo yhi"):
                y_lo, y_hi = (float(value) for value in line.split()[:2])
            elif line.endswith("zlo zhi"):
                z_lo, z_hi = (float(value) for value in line.split()[:2])
            elif line.endswith("xy xz yz"):
                tilt_xy, tilt_xz, tilt_yz = (
                    float(value) for value in line.split()[:3])
            elif line.endswith(" atoms"):
                atom_count = int(line.split()[0])
    if None in (x_lo, x_hi, y_lo, y_hi, z_lo, z_hi):
        raise ValueError(
            f"no complete box (xlo/ylo/zlo lines) in data file {data_path}")
    cell = np.array([
        [x_hi - x_lo, 0.0, 0.0],
        [tilt_xy, y_hi - y_lo, 0.0],
        [tilt_xz, tilt_yz, z_hi - z_lo]], dtype=float)
    return cell, (atom_count if atom_count is not None else 0)


def conventional_cell(cell: np.ndarray, cells_per_axis: int) -> np.ndarray:
    """The relaxed conventional cell from a relaxed block (§2.2).

    The relaxed block is the conventional cell replicated ``cells_per_
    axis`` times along each axis, and ``box/relax`` deforms it uniformly,
    so the conventional cell is simply the relaxed block's cell divided by
    that replication. This is the FULL 3x3 cell — it carries any tilt a
    lower-symmetry crystal relaxes into, so the caller can rescale a
    non-cubic crystal to it, not just a cubic edge.
    """
    return np.asarray(cell, dtype=float) / cells_per_axis


def cubic_lattice_constant(
        cell: np.ndarray, cells_per_axis: int) -> float:
    """The cubic lattice constant from a relaxed box (§2.2 convenience).

    The first box edge length over the replication. Meaningful only when
    the relaxed cell is cubic; the general geometry is
    :func:`conventional_cell`. Kept for the report and the cubic case.
    """
    return float(np.linalg.norm(cell[0]) / cells_per_axis)
