"""Derive the working lattice by relaxing the bulk (DESIGN.md §2.2).

This is slice 4: the FIRST use of the force engine, and the smallest.
DESIGN.md §2.2 forbids building the box on the CIF's published lattice —
a model has its OWN equilibrium spacing, and building on someone else's
leaves it strained (prior art's −30 to −40 GPa at step zero). So the
working lattice is DERIVED here: relax a bulk block to zero pressure
under the current model and read the equilibrium cell back. At the cold
start (§2.2) "the current model" is the classical stand-in; the same
routine re-derives the lattice under the trained committee once it
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
from sabsim.driver.engine import Engine


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

    ``lattice_constant`` is the derived, model-consistent value the
    structure builder then cuts slabs on — NOT the CIF's published
    scale. ``potential_energy`` is the relaxed bulk energy, which the
    surface-energy calculation (§2.5) later references per atom.
    """

    relaxed_cell: np.ndarray       # 3x3 relaxed box vectors, Å
    lattice_constant: float        # derived cubic a, Å
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
    """
    return [
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


def cubic_lattice_constant(
        cell: np.ndarray, cells_per_axis: int) -> float:
    """Derive the cubic lattice constant from a relaxed box (§2.2).

    The relaxed block is the conventional cell replicated ``cells_per_
    axis`` times along each axis, so the lattice constant is the box edge
    length divided by that replication. Only the cubic case is derived
    here; a lower-symmetry crystal reports its full relaxed cell and its
    per-axis constants come with the ``aniso`` relaxation (a §2 follow-on).
    """
    return float(np.linalg.norm(cell[0]) / cells_per_axis)


def relax_bulk(
        engine: Engine,
        data_file: str,
        force_model: ForceModel,
        cells_per_axis: int,
        settings: MinimizeSettings = MinimizeSettings(),
        coupling: str = "iso") -> BulkRelaxation:
    """Relax a bulk block and read the derived lattice back (§2.2).

    Issues the relaxation command stream through the engine seam, then
    reads the relaxed box, energy, and atom count and derives the cubic
    lattice constant. Because it talks only to :class:`Engine`, this runs
    identically against ``MockEngine`` (login node, this slice) and the
    real LAMMPS adapter (compute node, later).
    """
    engine.commands(
        bulk_relax_commands(data_file, force_model, settings, coupling))
    cell = np.asarray(engine.box(), dtype=float)
    return BulkRelaxation(
        relaxed_cell=cell,
        lattice_constant=cubic_lattice_constant(cell, cells_per_axis),
        potential_energy=engine.energy(),
        atom_count=engine.atom_count())
