"""Minimal Si structure building for the walking skeleton (DESIGN.md §2).

Wave-0 stand-in for the step-3 / step-5 structure builder. It makes real
diamond-silicon (100) slabs with ASE, stacks two into a facing pair with
a gap, tags each atom with the wafer it came from, and writes the pair
as a LAMMPS data file the driver can read. This is deliberately the
MINIMAL builder ARCHITECTURE.md §5 asks for at wave 0:

* Si/Si has no lattice mismatch, so there is NO coincidence matcher here
  (that arrives with the Si/SiO2 milestone, wave 3).
* The slab size is a small fixed stand-in, NOT the §2.5 converged
  thickness — a wave-0 number, flagged as such.
* The lattice constant is a placeholder near silicon's equilibrium;
  DESIGN.md §1.3 / §2.2 says it must be DERIVED by relaxing the bulk
  under the potential, which is wired in when the driver lands.

ASE is the structure membrane (VISION principle 4): every slab is an ASE
``Atoms`` object, and the only thing leaving this module for LAMMPS is a
data file written from it. Each atom carries a PROVENANCE tag (which
wafer it was built in), kept separate from its chemical species
(DESIGN.md §6) — the tag is bookkeeping the potential never sees.
"""

from __future__ import annotations

from dataclasses import dataclass

from ase import Atoms
from ase.build import bulk
from ase.io import write as ase_write

# Placeholder silicon lattice constant (Å). NOT a setting (DESIGN.md
# §1.3): the real value is derived by relaxing bulk Si under the
# potential (§2.2). This wave-0 stand-in sits near the Stillinger-Weber
# / experimental equilibrium so the skeleton builds a sane cell.
SILICON_LATTICE_CONSTANT = 5.43

# Provenance tags — which wafer an atom was built in (DESIGN.md §6),
# distinct from its species. A cross-interface bond later is one whose
# endpoints carry different tags; a transferred atom is one that ends in
# the fragment whose tag it does not share.
WAFER_A_TAG = 1
WAFER_B_TAG = 2


@dataclass
class BuiltPair:
    """A facing pair of slabs plus the geometry the driver needs.

    ``atoms`` is the whole assembled pair as one ASE object; the
    per-wafer z-ranges and the interface plane let the driver carve the
    frozen-base, thermostat-border, interior, and grip regions BY
    POSITION, so this builder need not know the MD protocol.
    """

    atoms: Atoms
    interface_z: float                    # where the two slabs face
    wafer_a_z_range: tuple[float, float]  # low, high z of wafer A
    wafer_b_z_range: tuple[float, float]  # low, high z of wafer B
    type_map: dict                        # species symbol -> LAMMPS type


def build_diamond_slab(
        element: str = "Si",
        cells_in_plane: tuple[int, int] = (2, 2),
        cells_through_thickness: int = 4,
        lattice_constant: float = SILICON_LATTICE_CONSTANT) -> Atoms:
    """Build one diamond-(100) slab as an ASE ``Atoms`` object.

    A conventional cubic diamond cell is replicated ``cells_in_plane`` in
    x and y and ``cells_through_thickness`` in z. Its native [001] faces
    ARE the (100) planes we want (the ratified Si face), so no rotation
    is needed. The block is returned periodic in all three directions;
    the caller opens the z surfaces when it stacks the pair.
    """
    conventional_cell = bulk(
        element, "diamond", a=lattice_constant, cubic=True)
    slab = conventional_cell * (
        cells_in_plane[0], cells_in_plane[1], cells_through_thickness)
    return slab


def stack_facing_pair(
        wafer_a: Atoms,
        wafer_b: Atoms,
        gap: float,
        grip_vacuum: float = 10.0) -> BuiltPair:
    """Stack two slabs into a facing pair separated by ``gap`` (§2.6).

    Wafer A sits at the bottom, wafer B above it with ``gap`` ångström of
    empty space between their facing (100) surfaces. Vacuum of
    ``grip_vacuum`` pads the outer ends, giving the free surfaces the
    grips attach to and room for the pull. The cell stays periodic in
    the plane and open along z. Each atom is tagged by wafer so the
    provenance survives into the trajectory (DESIGN.md §6).
    """
    lower = wafer_a.copy()
    upper = wafer_b.copy()

    # Sit the lower slab with its base at grip_vacuum, then place the
    # upper slab a gap above the top of the lower slab.
    lower_positions = lower.get_positions()
    lower_height = lower_positions[:, 2].max() - lower_positions[:, 2].min()
    lower.translate((0.0, 0.0, grip_vacuum - lower_positions[:, 2].min()))

    lower_top = grip_vacuum + lower_height
    upper_positions = upper.get_positions()
    upper.translate(
        (0.0, 0.0, lower_top + gap - upper_positions[:, 2].min()))
    upper_height = (upper_positions[:, 2].max()
                    - upper_positions[:, 2].min())

    lower.set_tags([WAFER_A_TAG] * len(lower))
    upper.set_tags([WAFER_B_TAG] * len(upper))

    pair = lower + upper

    # Give the box its lateral size from the slabs and an open z tall
    # enough for both slabs, the gap, and vacuum on each outer end.
    lateral_cell = wafer_a.get_cell()
    total_z = 2.0 * grip_vacuum + lower_height + gap + upper_height
    pair.set_cell(
        [lateral_cell[0], lateral_cell[1], [0.0, 0.0, total_z]])
    pair.set_pbc((True, True, False))

    interface_z = lower_top + 0.5 * gap
    return BuiltPair(
        atoms=pair,
        interface_z=interface_z,
        wafer_a_z_range=(grip_vacuum, lower_top),
        wafer_b_z_range=(lower_top + gap, lower_top + gap + upper_height),
        type_map=_type_map_of(pair))


def _type_map_of(atoms: Atoms) -> dict:
    """Map each element present to a stable 1-based LAMMPS type id.

    Ordered by chemical symbol so the mapping is deterministic and the
    same species always gets the same type across runs (needed for the
    potential's type map, STRUCTURAL 1a).
    """
    symbols = sorted(set(atoms.get_chemical_symbols()))
    return {symbol: index for index, symbol in enumerate(symbols, start=1)}


def write_lammps_data(
        built: BuiltPair, path: str) -> None:
    """Write the facing pair as a LAMMPS data file (the ASE membrane).

    Uses ``atom_style atomic`` (no charges — the classical Si potential
    and the {Si,O} MLIP are both charge-free at this fidelity) and pins
    the species order to ``built.type_map`` so LAMMPS type ids match the
    potential's expectation.
    """
    species_order = sorted(
        built.type_map, key=lambda symbol: built.type_map[symbol])
    ase_write(
        path, built.atoms, format="lammps-data",
        atom_style="atomic", specorder=species_order)
