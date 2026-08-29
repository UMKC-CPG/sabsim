"""Unit tests for the bulk-relaxation orchestration (driver.bulk_relax).

Slice 4's logic is written against the engine seam, so these run it end
to end against MockEngine with no LAMMPS: the command stream is a
periodic-box, box/relax minimization; the lattice is DERIVED from the
relaxed box (not the CIF's scale, DESIGN §2.2); and derive_lattice reads
the mock's preset box/energy back into a BulkRelaxation.
"""

import numpy as np

from sabsim.driver.bulk_relax import (
    MinimizeSettings,
    bulk_relax_commands,
    conventional_cell,
    cubic_lattice_constant,
)
from tests.unit.support import stand_in_force_model
from sabsim.driver.engine import MockEngine


def test_bulk_relax_commands_are_periodic_and_relax_the_box():
    """A p p p box, the force model, box/relax, and a minimize line."""
    model = stand_in_force_model({"Si": 1})
    commands = bulk_relax_commands("bulk.data", model)
    assert "boundary p p p" in commands
    assert "pair_style zero 6.0" in commands
    assert "fix relax_box all box/relax iso 0.0 vmax 0.001" in commands
    assert "min_style cg" in commands
    assert any(c.startswith("minimize ") for c in commands)


def test_minimize_line_carries_the_settings():
    """The minimize command reflects the convergence settings."""
    model = stand_in_force_model({"Si": 1})
    settings = MinimizeSettings(
        energy_tolerance=1e-6, force_tolerance=1e-6,
        max_iterations=500, max_evaluations=5000)
    commands = bulk_relax_commands("bulk.data", model, settings)
    assert "minimize 1e-06 1e-06 500 5000" in commands


def test_cubic_lattice_constant_divides_out_the_replication():
    """The lattice constant is the box edge over the cells per axis."""
    box = np.diag([10.86, 10.86, 10.86])
    assert cubic_lattice_constant(box, cells_per_axis=2) == 5.43


def test_conventional_cell_divides_a_general_box_by_replication():
    """The full cell — with tilt — divides out the replication (non-cubic)."""
    # A tetragonal, tilted block: a != c and a non-zero xy tilt survive.
    block = np.array([[8.0, 0.4, 0.0], [0.0, 8.0, 0.0], [0.0, 0.0, 10.0]])
    derived = conventional_cell(block, cells_per_axis=2)
    assert np.allclose(
        derived, [[4.0, 0.2, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 5.0]])




def _deepmd_bulk_model():
    """A message-passing MLIP force model (needs_atom_map), no ZBL."""
    from sabsim.driver.commands import ForceModel
    return ForceModel(
        pair_style="deepmd model.pt2",
        pair_coeff=("* * Si",),
        needs_atom_map=True)


def test_bulk_relax_commands_map_the_atoms_for_a_deepmd_model():
    """A message-passing MLIP gets atom_modify map yes BEFORE read_data.

    The GNN neighbor gather needs the global atom map to exist when the
    atoms are created, so the line must precede the read. The earlier
    in-process path never needed it, so it was absent until the universal
    §2.2 derivation arrived (DESIGN §4.7).
    """
    commands = bulk_relax_commands("bulk.data", _deepmd_bulk_model())
    assert "atom_modify map yes" in commands
    assert commands.index("atom_modify map yes") < commands.index(
        "read_data bulk.data")




def test_subprocess_script_ends_by_writing_the_relaxed_data():
    """The out-of-process script hands its geometry back through a file."""
    from sabsim.driver.bulk_relax import bulk_relax_subprocess_script
    script = bulk_relax_subprocess_script(
        "bulk.data", _deepmd_bulk_model(), "relaxed.data")
    assert script[-1] == "write_data relaxed.data nocoeff"
    # It is the full relaxation, not just the write.
    assert "fix relax_box all box/relax iso 0.0 vmax 0.001" in script


def test_read_data_box_reads_an_orthogonal_cell_and_count(tmp_path):
    """An orthogonal write_data box parses to a diagonal cell (no tilt)."""
    from sabsim.driver.bulk_relax import read_data_box
    data = tmp_path / "relaxed.data"
    data.write_text(
        "LAMMPS data file\n\n"
        "64 atoms\n1 atom types\n\n"
        "0.0 10.8618 xlo xhi\n"
        "0.0 10.8618 ylo yhi\n"
        "0.0 10.8618 zlo zhi\n\n"
        "Masses\n\n1 28.085\n\n"
        "Atoms # atomic\n\n1 1 0.0 0.0 0.0\n")
    cell, atom_count = read_data_box(str(data))
    assert atom_count == 64
    assert np.allclose(cell, np.diag([10.8618, 10.8618, 10.8618]))


def test_read_data_box_reconstructs_a_triclinic_cell(tmp_path):
    """Tilt factors become the cell's off-diagonal vectors, directly.

    A data file states the box as its edges, so the vectors are
    a=(xhi-xlo,0,0), b=(xy,yhi-ylo,0), c=(xz,yz,zhi-zlo) with NO
    bound-vs-actual conversion (unlike a dump's ITEM: BOX BOUNDS).
    """
    from sabsim.driver.bulk_relax import read_data_box
    data = tmp_path / "tri.data"
    data.write_text(
        "LAMMPS data file\n\n"
        "8 atoms\n\n"
        "0.0 5.0 xlo xhi\n"
        "0.0 6.0 ylo yhi\n"
        "0.0 7.0 zlo zhi\n"
        "0.5 0.2 0.3 xy xz yz\n\n"
        "Atoms\n\n1 1 0.0 0.0 0.0\n")
    cell, _ = read_data_box(str(data))
    assert np.allclose(
        cell, [[5.0, 0.0, 0.0], [0.5, 6.0, 0.0], [0.2, 0.3, 7.0]])


def test_read_data_box_raises_when_the_box_is_missing(tmp_path):
    """A data file with no box lines is a loud parse failure."""
    import pytest
    from sabsim.driver.bulk_relax import read_data_box
    data = tmp_path / "nobox.data"
    data.write_text("LAMMPS data file\n\n8 atoms\n\nAtoms\n\n1 1 0 0 0\n")
    with pytest.raises(ValueError, match="no complete box"):
        read_data_box(str(data))
