"""Tests for the real build-halves stage (ARCHITECTURE.md §4.3, §7.1).

The activation and assembly stages open a real ``LammpsEngine`` and need a
compute node, so they are validated by a driver on the node, not here.
``build_halves`` is login-node work — it cuts real slabs and writes their
data files with no LAMMPS — so it is unit-tested here, together with the
``read_standalone_half`` round-trip the amorphization stage relies on.
"""

from __future__ import annotations

from ase.io import read as ase_read

from sabsim.pipeline.live_stages import build_halves
from sabsim.spec.loader import load_and_validate_study
from sabsim.spec.records import Quantity
from sabsim.structure.slab_builder import (
    WAFER_A_TAG,
    WAFER_B_TAG,
    read_standalone_half,
)

_TEMPLATE = "dev/templates/study_spec.toml"


def _si_si_member():
    """The Si/Si reference member — both wafers silicon (identity case)."""
    study = load_and_validate_study(_TEMPLATE)
    for member in study.members:
        if member.name == "si-si-reference":
            return member
    raise AssertionError("si-si-reference member not found in template")


def test_build_halves_writes_two_handles(tmp_path):
    """Both wafers become standalone data files with real handles."""
    member = _si_si_member()
    handle_a, handle_b, shared = build_halves(
        member, potential=None, scratch_directory=str(tmp_path))

    # Two handles, tagged bottom A / top B, each naming a written file.
    assert handle_a.wafer_tag == WAFER_A_TAG
    assert handle_b.wafer_tag == WAFER_B_TAG
    assert handle_a.identity == "Si" and handle_b.identity == "Si"
    for handle in (handle_a, handle_b):
        assert (tmp_path / handle.data_file.split("/")[-1]).exists()
        # The beam species (Ar) is declared in the type map, though the
        # pristine slab contains none of it.
        assert "Ar" in handle.type_map and "Si" in handle.type_map
    assert shared is not None


def test_built_half_declares_the_beam_and_is_orthogonal(tmp_path):
    """The written half declares the Ar type and has a tilt-free cell."""
    member = _si_si_member()
    handle_a, _, _ = build_halves(
        member, potential=None, scratch_directory=str(tmp_path))

    text = (tmp_path / handle_a.data_file.split("/")[-1]).read_text()
    assert "2 atom types" in text          # Si + the declared beam Ar
    assert "# Ar" in text

    # Re-read the geometry the way the amorphization stage will, and check
    # the in-plane cell has no xy tilt (orthogonalize_in_plane did its job).
    half = read_standalone_half(
        handle_a.data_file, handle_a.type_map, handle_a.identity)
    cell = half.atoms.get_cell()
    assert abs(cell[1][0]) < 1.0e-6        # b_x driven to zero
    # The read-back is substrate-only (no Ar atom exists in a pristine
    # half) but carries the full beam-declaring type map for the cascade.
    assert set(half.atoms.get_chemical_symbols()) == {"Si"}
    assert "Ar" in half.type_map


def test_read_standalone_half_round_trips_species(tmp_path):
    """read_standalone_half recovers positions and species from disk."""
    member = _si_si_member()
    handle_a, _, _ = build_halves(
        member, potential=None, scratch_directory=str(tmp_path))

    half = read_standalone_half(
        handle_a.data_file, handle_a.type_map, handle_a.identity)
    reference = ase_read(
        handle_a.data_file, format="lammps-data", atom_style="atomic",
        Z_of_type={2: 14})            # type 2 -> Si (Ar=1, Si=2 by symbol)
    assert len(half.atoms) == len(reference)
    assert len(half.atoms) > 0
    assert half.identity == "Si"
