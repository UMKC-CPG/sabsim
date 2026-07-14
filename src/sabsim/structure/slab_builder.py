"""General slab and facing-pair structure builder (DESIGN.md §2).

This is the step-3 / step-5 structure builder, written ONCE to serve any
material instead of a script per crystal. A wafer is described by a
crystal-structure file (a CIF — the authoritative structure, DESIGN.md
§1.2) plus the Miller indices of the face to expose, and the same code
path builds silicon, silicon dioxide, or any other crystal from that
pair of inputs. Silicon-on-silicon is simply the first INPUT we run it
on, and it doubles as the coincidence matcher's identity/null test
(DESIGN.md §2.548).

The heavy geometry is ADOPTED, not hand-written (VISION principle 2):
pymatgen cleaves the slab (``SlabGenerator``) and matches the two surface
lattices (the Zur-McGill construction, ``ZSLGenerator`` — DESIGN.md
§2.3). ASE is the structure membrane (VISION principle 4): every slab
leaves this module as an ASE ``Atoms`` object, and the only thing handed
to LAMMPS is a data file written from one.

Two quantities are deliberately STAND-INS at this stage, each flagged
where it is used and retired when the force engine lands:

* **The lattice scale.** The CIF's cell is a starting geometry; the
  working lattice is derived by relaxing the bulk under the current
  model (DESIGN.md §2.2). Until that relaxation exists the slab is cut
  on the CIF's own scale — honest provenance, not a converged number.
* **The termination.** Where a face admits several terminations, §2.5
  selects by computed surface energy, which needs the force model. Until
  then the first candidate is used, exactly as documented in §2.5.

And one case is deferred to wave 3, refused rather than faked: the
strained-coincidence assembly of a REAL lattice mismatch (DESIGN.md
§2.4). Slice 1 assembles the IDENTITY / commensurate pair — two slabs
that already share a surface cell, which is Si/Si and its null test —
and raises for a genuine mismatch, so nothing unphysical slips through.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from ase import Atoms
from ase.io import write as ase_write
from pymatgen.analysis.interfaces.zsl import ZSLGenerator
from pymatgen.core import Structure
from pymatgen.core.surface import SlabGenerator
from pymatgen.io.ase import AseAtomsAdaptor

# Provenance tags — which wafer an atom was built in (DESIGN.md §6),
# distinct from its chemical species. A cross-interface bond is later one
# whose endpoints carry different tags; a transferred atom is one that
# ends in the fragment whose tag it does not share.
WAFER_A_TAG = 1
WAFER_B_TAG = 2

# Below this residual-strain magnitude the two surface lattices count as
# already coincident — the identity case the null test checks and the
# only case slice 1 assembles (DESIGN.md §2.4 owns the rest).
_IDENTITY_STRAIN_TOLERANCE = 1.0e-6


@dataclass
class SurfaceMatch:
    """The coincidence match between two slabs' surface lattices (§2.3).

    Produced by the adopted Zur-McGill search: the smallest shared cell
    that carries both surfaces within tolerance. ``residual_strain`` is a
    rotation-invariant magnitude of the deformation one surface must
    absorb to meet the other (the full tensor split is §2.4); it is ~0
    for an exact match. ``is_identity`` marks the null case where the two
    lattices already coincide — the only case slice 1 goes on to
    assemble.
    """

    residual_strain: float          # scalar strain magnitude (0 = exact)
    match_area: float               # area of the shared cell, in Å²
    is_identity: bool               # True when the surfaces coincide


@dataclass
class BuiltPair:
    """A facing pair of slabs plus the geometry the driver needs (§2.6).

    ``atoms`` is the whole assembled pair as one ASE object; the
    per-wafer z-ranges and the interface plane let the driver carve the
    frozen-base, thermostat-border, interior, and grip regions BY
    POSITION, so this builder need not know the MD protocol. ``match``
    carries the coincidence provenance the member records (DESIGN.md
    §2.1).
    """

    atoms: Atoms
    interface_z: float                    # where the two slabs face
    wafer_a_z_range: tuple[float, float]  # low, high z of wafer A
    wafer_b_z_range: tuple[float, float]  # low, high z of wafer B
    type_map: dict                        # species symbol -> LAMMPS type
    match: SurfaceMatch                   # the coincidence provenance


def load_crystal(cif_path) -> Structure:
    """Read a wafer's crystal from its CIF (the authoritative structure).

    The CIF fixes the crystal's symmetry, basis, and connectivity
    (DESIGN.md §1.2). Its cell SCALE is only a starting geometry — the
    working lattice constant is derived by relaxation (§2.2) — so nothing
    here treats the file's lattice constant as final.
    """
    return Structure.from_file(str(cif_path))


def build_slab(
        crystal: Structure,
        miller_face: tuple[int, int, int],
        min_slab_thickness: float = 8.0,
        min_vacuum: float = 10.0,
        termination_index: int = 0) -> Atoms:
    """Cleave one slab along a Miller face, as an ASE ``Atoms`` (§2.5).

    pymatgen's ``SlabGenerator`` does the cleaving for ANY crystal and
    face; the result is converted to an ASE object (the membrane). Where
    a face admits several terminations, §2.5 selects by computed surface
    energy — which needs the force model — so until that lands the
    ``termination_index``-th candidate (the first by default) is used: a
    documented stand-in, not a silent "first candidate is sufficient".
    """
    generator = SlabGenerator(
        crystal, miller_index=tuple(miller_face),
        min_slab_size=min_slab_thickness, min_vacuum_size=min_vacuum,
        center_slab=True)
    candidates = generator.get_slabs()
    if termination_index >= len(candidates):
        raise IndexError(
            f"termination {termination_index} out of range: the "
            f"{miller_face} face has {len(candidates)} termination(s)")
    return AseAtomsAdaptor.get_atoms(candidates[termination_index])


def _surface_vectors(slab: Atoms) -> np.ndarray:
    """Return a slab's two in-plane surface vectors as a 2x3 array.

    A slab's ASE cell keeps its first two vectors in the surface plane
    and the third along the normal (with vacuum), so the first two rows
    ARE the surface lattice the coincidence search operates on.
    """
    return np.asarray(slab.get_cell()[:2])


def _residual_strain(
        substrate_vectors: np.ndarray,
        film_vectors: np.ndarray) -> float:
    """Rotation-invariant magnitude of the misfit strain (DESIGN §2.3).

    A pure rotation between the two matched cells is TWIST, not strain
    (§2.3), so we compare rotation-invariant metric tensors — each
    cell's matrix of vector dot-products — rather than the raw vectors.
    The result is the largest metric difference relative to the
    substrate, which is 0 for an exact (identity) match. Splitting the
    full strain tensor into entailed and incidental parts is §2.4's job
    at wave 3; here we need only the magnitude for the null test.
    """
    substrate = np.asarray(substrate_vectors)
    film = np.asarray(film_vectors)
    metric_substrate = substrate @ substrate.T
    metric_film = film @ film.T
    scale = np.max(np.abs(metric_substrate))
    return float(np.max(np.abs(metric_film - metric_substrate)) / scale)


def match_surfaces(
        slab_a: Atoms,
        slab_b: Atoms,
        max_area: float = 400.0,
        misfit_tolerance: float = 0.05) -> SurfaceMatch:
    """Find the shared coincidence cell (Zur-McGill, adopted — §2.3).

    Runs pymatgen's ``ZSLGenerator`` on the two slabs' surface vectors
    and keeps the SMALLEST matched cell within the area and misfit
    budgets — the same "smallest survivor" rule DESIGN.md §2.3 states.
    For identical lattices (Si/Si) the smallest match is the primitive
    surface cell at zero strain, which is the matcher's null test.
    """
    vectors_a = _surface_vectors(slab_a)
    vectors_b = _surface_vectors(slab_b)
    generator = ZSLGenerator(
        max_area=max_area, max_length_tol=misfit_tolerance)
    matches = list(generator(vectors_a, vectors_b))
    if not matches:
        raise ValueError(
            "no coincidence cell within the area/misfit budget (§2.3): "
            "loosen misfit_tolerance or raise max_area")
    best = min(matches, key=lambda match: match.match_area)
    strain = _residual_strain(
        best.substrate_sl_vectors, best.film_sl_vectors)
    return SurfaceMatch(
        residual_strain=strain,
        match_area=float(best.match_area),
        is_identity=(strain <= _IDENTITY_STRAIN_TOLERANCE))


def assemble_facing_pair(
        slab_a: Atoms,
        slab_b: Atoms,
        match: SurfaceMatch,
        gap: float,
        grip_vacuum: float = 10.0) -> BuiltPair:
    """Stack two matched slabs into a facing pair (DESIGN.md §2.6).

    Wafer A sits at the bottom, wafer B a ``gap`` of ångström above it,
    with ``grip_vacuum`` of empty space padding the outer ends for the
    grips and the pull. The box stays periodic in the plane and open
    along z, and each atom is tagged by wafer so provenance survives into
    the trajectory (§6).

    Slice 1 handles the IDENTITY / commensurate case only — two slabs
    that already share a surface cell (Si/Si and its null test). The
    strained-coincidence assembly of a REAL mismatch is DESIGN.md §2.4
    and lands at wave 3; it is REFUSED here rather than faked, so no
    unphysical geometry can slip downstream.
    """
    if not match.is_identity:
        raise NotImplementedError(
            "strained coincidence assembly of a real lattice mismatch "
            "lands at wave 3 (DESIGN.md §2.4); slice 1 builds the "
            "identity/commensurate pair (e.g. Si/Si) only")

    lower = slab_a.copy()
    upper = slab_b.copy()

    # Sit the lower slab with its base at grip_vacuum, then place the
    # upper slab a gap above the top of the lower slab.
    lower_z = lower.get_positions()[:, 2]
    lower_height = lower_z.max() - lower_z.min()
    lower.translate((0.0, 0.0, grip_vacuum - lower_z.min()))

    lower_top = grip_vacuum + lower_height
    upper_z = upper.get_positions()[:, 2]
    upper_height = upper_z.max() - upper_z.min()
    upper.translate((0.0, 0.0, lower_top + gap - upper_z.min()))

    lower.set_tags([WAFER_A_TAG] * len(lower))
    upper.set_tags([WAFER_B_TAG] * len(upper))
    pair = lower + upper

    # The lateral box comes from the (shared) surface cell; z is open and
    # tall enough for both slabs, the gap, and vacuum on each outer end.
    lateral_cell = slab_a.get_cell()
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
        type_map=_type_map_of(pair),
        match=match)


def build_facing_pair(
        cif_a,
        miller_face_a: tuple[int, int, int],
        cif_b,
        miller_face_b: tuple[int, int, int],
        gap: float,
        min_slab_thickness: float = 8.0,
        grip_vacuum: float = 10.0,
        max_area: float = 400.0,
        misfit_tolerance: float = 0.05) -> BuiltPair:
    """Build a facing pair end to end from two CIFs and two faces (§2).

    The one entry point that ties the steps together: read each crystal
    from its CIF, cleave each slab along its face, match the two surface
    lattices, and assemble the pair. This is what a later slice wires
    into the ``build_slabs`` / ``assemble_pair`` pipeline stages once the
    live study runs on it; for now it is exercised directly on Si/Si.
    """
    slab_a = build_slab(
        load_crystal(cif_a), miller_face_a,
        min_slab_thickness, grip_vacuum)
    slab_b = build_slab(
        load_crystal(cif_b), miller_face_b,
        min_slab_thickness, grip_vacuum)
    match = match_surfaces(slab_a, slab_b, max_area, misfit_tolerance)
    return assemble_facing_pair(slab_a, slab_b, match, gap, grip_vacuum)


def _type_map_of(atoms: Atoms) -> dict:
    """Map each element present to a stable 1-based LAMMPS type id.

    Ordered by chemical symbol so the mapping is deterministic and the
    same species always gets the same type across runs (needed for the
    potential's type map, STRUCTURAL 1a).
    """
    symbols = sorted(set(atoms.get_chemical_symbols()))
    return {symbol: index for index, symbol in enumerate(symbols, start=1)}


def write_lammps_data(built: BuiltPair, path: str) -> None:
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
