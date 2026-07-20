"""Tests for the standalone half-cell builder and its data file (§4.3).

A bonding member prepares each surface ALONE before the two ever meet
(`ARCHITECTURE.md` §4.3): step 3 emits two standalone half-cells, each in
its own vacuum box, and each written to a LAMMPS data file the activation
stage loads. These tests exercise that builder and writer on the login
node with the shipped Si CIF — no LAMMPS — with special attention to the
one thing a half must get right that a plain cut slab need not: declaring
the beam species so the cascade can create projectile atoms against it.
"""

from __future__ import annotations

import os

import numpy as np
from ase.io import read as ase_read

import sabsim.structure
from sabsim.structure.slab_builder import (
    build_standalone_half,
    load_crystal,
    write_standalone_half,
)

# The Si diamond CIF shipped as reference data — the same authoritative
# structure the other structure tests cut from.
_SI_CIF = os.path.join(
    os.path.dirname(sabsim.structure.__file__), "data", "si_diamond.cif")
_SI_100 = (1, 0, 0)


def test_standalone_half_is_a_silicon_slab_in_vacuum():
    """The half is a non-empty Si slab with vacuum along its z box."""
    half = build_standalone_half(
        load_crystal(_SI_CIF), _SI_100, identity="Si",
        projectile_species={"Ar"})

    assert half.identity == "Si"
    assert len(half.atoms) > 0
    assert set(half.atoms.get_chemical_symbols()) == {"Si"}
    # The z box vector is taller than the atoms' z extent — vacuum was
    # opened for the cascade's open top (the beam comes down into it).
    z_positions = half.atoms.get_positions()[:, 2]
    atom_span = z_positions.max() - z_positions.min()
    box_height = half.atoms.get_cell()[2, 2]
    assert box_height > atom_span


def test_type_map_declares_the_beam_but_the_slab_has_none():
    """The beam species is in the type map, with no beam atom present yet.

    The cascade CREATES beam atoms mid-run, so the half must declare the
    beam type up front — but contain none of it at build time.
    """
    half = build_standalone_half(
        load_crystal(_SI_CIF), _SI_100, identity="Si",
        projectile_species={"Ar"})

    # Both species mapped, ordered deterministically by symbol (Ar < Si).
    assert half.type_map == {"Ar": 1, "Si": 2}
    # ...but not one argon atom exists in the built slab.
    assert "Ar" not in half.atoms.get_chemical_symbols()


def test_a_codeposit_species_also_joins_the_type_map():
    """A co-deposit species is declared alongside the primary beam."""
    half = build_standalone_half(
        load_crystal(_SI_CIF), _SI_100, identity="Si",
        projectile_species={"Ar", "O"})

    # Union of {Si} with {Ar, O}, ordered by symbol: Ar, O, Si.
    assert half.type_map == {"Ar": 1, "O": 2, "Si": 3}


def test_written_data_file_declares_the_beam_type_with_a_mass(tmp_path):
    """The data file carries the beam as an atom type with a mass, 0 atoms.

    This is the whole point of declaring the beam early: LAMMPS can only
    ``create_atoms`` of a type its data file declared, so the file must
    show the beam's atom type and its ``Masses`` line even with no beam
    atom in the ``Atoms`` section.
    """
    half = build_standalone_half(
        load_crystal(_SI_CIF), _SI_100, identity="Si",
        projectile_species={"Ar"})
    data_path = tmp_path / "half_si.data"
    write_standalone_half(half, str(data_path))

    text = data_path.read_text()
    # Two atom types declared (Si and the beam Ar), both with masses.
    assert "2 atom types" in text
    assert "# Ar" in text and "# Si" in text
    # Argon's atomic mass appears in the Masses section (~39.9 amu).
    assert "39.9" in text

    # The file is loadable and round-trips to a Si-only slab (no Ar atom
    # was written, only the Ar type declaration).
    reloaded = ase_read(str(data_path), format="lammps-data",
                        atom_style="atomic")
    assert set(reloaded.get_chemical_symbols()) <= {"Si", "X"}
    assert len(reloaded) == len(half.atoms)


def test_beam_species_already_in_the_slab_is_not_duplicated():
    """Declaring a beam species the slab already has changes no type id.

    The type map is a UNION, so asking to declare Si as a 'beam' on a Si
    slab leaves a single Si type, not two.
    """
    half = build_standalone_half(
        load_crystal(_SI_CIF), _SI_100, identity="Si",
        projectile_species={"Si"})

    assert half.type_map == {"Si": 1}
    assert np.array_equal(
        sorted(set(half.atoms.get_chemical_symbols())), ["Si"])
