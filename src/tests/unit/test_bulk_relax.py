"""Unit tests for the bulk-relaxation orchestration (driver.bulk_relax).

Slice 4's logic is written against the engine seam, so these run it end
to end against MockEngine with no LAMMPS: the command stream is a
periodic-box, box/relax minimization; the lattice constant is DERIVED
from the relaxed box (not the CIF's scale, DESIGN §2.2); and relax_bulk
reads the mock's preset box/energy back into a BulkRelaxation.
"""

import numpy as np

from sabsim.driver.bulk_relax import (
    MinimizeSettings,
    bulk_relax_commands,
    cubic_lattice_constant,
    relax_bulk,
)
from sabsim.driver.commands import classical_si_stand_in
from sabsim.driver.engine import MockEngine


def test_bulk_relax_commands_are_periodic_and_relax_the_box():
    """A p p p box, the force model, box/relax, and a minimize line."""
    model = classical_si_stand_in({"Si": 1})
    commands = bulk_relax_commands("bulk.data", model)
    assert "boundary p p p" in commands
    assert "pair_style sw" in commands
    assert "fix relax_box all box/relax iso 0.0 vmax 0.001" in commands
    assert "min_style cg" in commands
    assert any(c.startswith("minimize ") for c in commands)


def test_minimize_line_carries_the_settings():
    """The minimize command reflects the convergence settings."""
    model = classical_si_stand_in({"Si": 1})
    settings = MinimizeSettings(
        energy_tolerance=1e-6, force_tolerance=1e-6,
        max_iterations=500, max_evaluations=5000)
    commands = bulk_relax_commands("bulk.data", model, settings)
    assert "minimize 1e-06 1e-06 500 5000" in commands


def test_cubic_lattice_constant_divides_out_the_replication():
    """The lattice constant is the box edge over the cells per axis."""
    box = np.diag([10.86, 10.86, 10.86])
    assert cubic_lattice_constant(box, cells_per_axis=2) == 5.43


def test_relax_bulk_derives_the_lattice_from_the_relaxed_box():
    """relax_bulk reads the mock's box/energy into a BulkRelaxation."""
    # The mock pretends the relaxation reached a=5.4309 (SW Si), a value
    # DIFFERENT from the CIF's 5.43 starting scale — the point of §2.2.
    edge = 5.4309 * 2
    engine = MockEngine(
        energy=-296.0, box=np.diag([edge, edge, edge]), atom_count=64)
    model = classical_si_stand_in({"Si": 1})

    result = relax_bulk(engine, "bulk.data", model, cells_per_axis=2)

    assert result.lattice_constant == 5.4309
    assert result.potential_energy == -296.0
    assert result.atom_count == 64
    # The orchestration really issued the relaxation stream to the engine.
    assert "fix relax_box all box/relax iso 0.0 vmax 0.001" in (
        engine.received_commands)
