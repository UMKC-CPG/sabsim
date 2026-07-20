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

# Provenance tags — which of the two bonding partners an atom was built
# in (DESIGN.md §6), distinct from its chemical species. A cross-interface
# bond is later one whose endpoints carry different tags; a transferred
# atom is one that ends in the fragment whose tag it does not share.
# Wafer A is the BOTTOM slab and wafer B the TOP by construction (see
# BuiltPair), so these tags also split the pair into bottom vs top.
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
    grip, thermostat-border, and interior regions BY POSITION, so this
    builder need not know the MD protocol (option C, DESIGN.md §2.6).
    ``match`` carries the coincidence provenance the member records
    (DESIGN.md §2.1).

    The A/B labels are the two bonding partners (the same A/B as the
    §6 work-of-adhesion math, W = gamma_A + gamma_B - gamma_AB). By
    CONSTRUCTION wafer A is always assembled as the BOTTOM slab and
    wafer B as the TOP, so ``wafer_a_z_range`` is invariably the bottom
    slab's z-extent and ``wafer_b_z_range`` the top slab's — the driver
    relies on that invariant to know which grip is which.
    """

    atoms: Atoms
    interface_z: float                    # where the two slabs face
    # A = bottom slab, B = top slab (invariant of assembly, see above).
    wafer_a_z_range: tuple[float, float]  # low, high z of wafer A (bottom)
    wafer_b_z_range: tuple[float, float]  # low, high z of wafer B (top)
    type_map: dict                        # species symbol -> LAMMPS type
    match: SurfaceMatch                   # the coincidence provenance
    # How far the initial gap was BACKED OFF to relieve a cross-slab
    # clash (Å), recorded rather than aborting the member (DESIGN §2.6).
    # Zero for the crystalline stack (no amorphous roughness to clash);
    # the amorphized assembly (:mod:`sabsim.structure.amorphized_assembly`)
    # sets it to the lift it applied.
    initial_gap_adjustment: float = 0.0


@dataclass
class StandaloneHalf:
    """One wafer cut ALONE in vacuum, ready to be bombarded (§4.3, §7.1).

    The chain for a bonding member prepares each surface BY ITSELF before
    the two ever meet (`ARCHITECTURE.md` §4.3): step 3 emits two standalone
    half-cells, each in its own vacuum box, and the activation stage loads
    one onto its own engine to amorphize it. This is that half — the single
    slab plus the type map the cascade needs — as distinct from the
    assembled :class:`BuiltPair` (two slabs facing, z-ranges set) the press
    later runs on.

    ``type_map`` is the one place a half differs from a plain cut slab: it
    already DECLARES the beam species (and any co-deposit), even though no
    beam atom exists in ``atoms`` yet. The cascade CREATES those atoms mid-
    run (``create_atoms`` on the projectile type), and LAMMPS can only make
    an atom of a type its data file declared — so the beam species must be
    in the map, and thus in the written data file's atom-type count and
    ``Masses`` section, from the start (see :func:`write_standalone_half`).
    """

    atoms: Atoms
    type_map: dict                 # species symbol -> LAMMPS type id, with
    #                                the beam species declared (see above)
    identity: str                  # the material this half is made of


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


def build_standalone_half(
        crystal: Structure,
        miller_face: tuple[int, int, int],
        identity: str,
        projectile_species,
        min_slab_thickness: float = 8.0,
        min_vacuum: float = 10.0,
        termination_index: int = 0) -> StandaloneHalf:
    """Cut ONE wafer alone in vacuum, beam species declared (§4.3, §7.1).

    The step-3 builder for a single bonding partner. It cleaves the slab
    with the existing per-wafer :func:`build_slab` (which already opens the
    vacuum the cascade's open top needs), then builds the type map the
    amorphization will run under: the union of the slab's own species and
    the ``projectile_species`` the beam adds (the activation element, plus
    a co-deposit if the protocol names one). Declaring the beam here — not
    at bombardment time — is what lets the written data file carry the beam
    as an atom type with a mass, so LAMMPS can create projectile atoms
    against it (:func:`write_standalone_half`).

    ``projectile_species`` is an iterable of chemical symbols; passing it
    in (rather than reading the member here) keeps this builder decoupled
    from the protocol record and directly testable. ``identity`` is the
    material label carried for provenance and the report.

    STAND-IN (retired at wave 3, DESIGN.md §2.4): this cuts each half on
    the crystal's own lattice and does NOT yet tile it to a shared
    coincidence cell or apply the split misfit strain — the Si/Si identity
    case needs neither, and the strained dissimilar assembly lands with the
    coincidence matcher (§7.6). The seam is the same: a later wave threads
    the shared cell and strain through here without changing the half's
    shape.
    """
    slab = build_slab(
        crystal, miller_face, min_slab_thickness, min_vacuum,
        termination_index)
    type_map = _type_map_with_species(slab, projectile_species)
    return StandaloneHalf(
        atoms=slab, type_map=type_map, identity=identity)


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


def _type_map_with_species(atoms: Atoms, extra_species) -> dict:
    """Map the present species PLUS extras to stable 1-based type ids.

    The general form: the union of the atoms' own chemical symbols and any
    ``extra_species`` given (e.g. the beam a standalone half must declare
    but does not yet contain), ordered by symbol so the mapping is
    deterministic and a species always gets the same type across runs
    (needed for the potential's type map, STRUCTURAL 1a). With no extras it
    is just the present-species map (:func:`_type_map_of`).
    """
    symbols = sorted(set(atoms.get_chemical_symbols()) | set(extra_species))
    return {symbol: index for index, symbol in enumerate(symbols, start=1)}


def _type_map_of(atoms: Atoms) -> dict:
    """Map each element present to a stable 1-based LAMMPS type id.

    The common case of :func:`_type_map_with_species` with no extras —
    every type in the map is a species actually in ``atoms``.
    """
    return _type_map_with_species(atoms, ())


def _write_atoms_as_lammps_data(
        atoms: Atoms, type_map: dict, path: str) -> None:
    """Write atoms as a LAMMPS data file, species order from a type map.

    The shared writer behind :func:`write_lammps_data` (a facing pair) and
    :func:`write_standalone_half` (one wafer). ``atom_style atomic`` (no
    charges — the classical Si potential and the {Si,O} MLIP are both
    charge-free at this fidelity), and the species order is pinned to
    ``type_map`` so LAMMPS type ids match the potential's expectation.
    Every type in the map is written, including one the map DECLARES but
    ``atoms`` does not yet contain (the standalone half's beam species):
    ASE emits it in the atom-type count and the ``Masses`` section with
    zero atoms of it, which is exactly what lets the cascade create beam
    atoms against that type later.

    ``masses=True`` is REQUIRED, not cosmetic: ASE omits the ``Masses``
    section by default, and LAMMPS then rejects any run with "Not all
    per-type masses are set". Writing them keeps the data file
    self-contained, so no separate ``mass`` command has to be threaded
    through the command generator to make the file loadable.
    """
    species_order = sorted(type_map, key=lambda symbol: type_map[symbol])
    ase_write(
        path, atoms, format="lammps-data",
        atom_style="atomic", specorder=species_order, masses=True)


def write_lammps_data(built: BuiltPair, path: str) -> None:
    """Write the facing pair as a LAMMPS data file (the ASE membrane)."""
    _write_atoms_as_lammps_data(built.atoms, built.type_map, path)


def write_standalone_half(half: StandaloneHalf, path: str) -> None:
    """Write one standalone half as a LAMMPS data file (§4.3, §7.1).

    The activation stage loads this file onto its own engine to bombard the
    surface. It declares the BEAM species as an atom type with a mass but
    zero atoms (the half's ``type_map`` carries it, see
    :class:`StandaloneHalf`), so LAMMPS can ``create_atoms`` the projectile
    against that type mid-cascade. Same self-contained ``atomic``-style
    file as the facing pair, through the shared writer above.
    """
    _write_atoms_as_lammps_data(half.atoms, half.type_map, path)


def bulk_atoms(crystal: Structure, cells_per_axis: int) -> Atoms:
    """Replicate a crystal's cell into a periodic bulk block (§2.2).

    The bulk relaxation (:mod:`sabsim.driver.bulk_relax`) needs a fully
    periodic block, not a slab: the crystal converted to an ASE object
    and replicated ``cells_per_axis`` times along each axis. No surface,
    no vacuum — this is the model's own equilibrium lattice being found,
    not a surface being cut.
    """
    block = AseAtomsAdaptor.get_atoms(crystal)
    return block * (cells_per_axis, cells_per_axis, cells_per_axis)


def write_bulk_data(
        crystal: Structure, cells_per_axis: int, path: str) -> dict:
    """Write a bulk block to a LAMMPS data file; return its type map.

    The companion to :func:`write_lammps_data` for the §2.2 relaxation:
    same ASE membrane, ``atom_style atomic``, deterministic species
    order, and the same required ``masses=True`` (see that function —
    LAMMPS will not run a data file whose per-type masses are unset).
    The returned type map lets the caller build the matching
    :class:`~sabsim.driver.commands.ForceModel` under the same
    species-order contract (STRUCTURAL 1a).
    """
    atoms = bulk_atoms(crystal, cells_per_axis)
    type_map = _type_map_of(atoms)
    species_order = sorted(
        type_map, key=lambda symbol: type_map[symbol])
    ase_write(
        path, atoms, format="lammps-data",
        atom_style="atomic", specorder=species_order, masses=True)
    return type_map
