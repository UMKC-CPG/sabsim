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
from ase.build import make_supercell
from ase.data import atomic_numbers
from ase.io import read as ase_read
from ase.io import write as ase_write
from pymatgen.analysis.interfaces.zsl import ZSLGenerator

# EVERY ASE read and write in SABSIM passes ``parallel=False``. That is
# not a speed setting; omitting it is a correctness bug, and it cost one
# eight-hour cluster job to find. When several processes are running
# under MPI, ASE silently promotes its file reads and writes into
# COLLECTIVE operations: process zero alone touches the disk and then
# broadcasts the result to every other process, so all of them must take
# part or none may continue. SABSIM runs its own message passing and
# already decides for itself which process writes a file, so a hidden
# broadcast inside a read leaves the two schemes talking past each
# other. One process waits inside ASE's broadcast while its peers wait
# at a barrier of ours, and the run either deadlocks outright or — the
# nastier failure — hands those peers an empty result, which ASE's
# reader reports as a file containing no structures at all. Reading
# serially costs nothing at these file sizes: every process simply
# parses the same few hundred kilobytes for itself.
from pymatgen.core import Lattice, Structure
from pymatgen.core.surface import SlabGenerator
from pymatgen.io.ase import AseAtomsAdaptor

# Provenance tags — which of the two bonding partners an atom was built
# in (DESIGN.md §6), distinct from its chemical species. A cross-interface
# bond is later one whose endpoints carry different tags; a transferred
# atom is one that ends in the fragment whose tag it does not share.
# Wafer A is the BOTTOM slab and wafer B the TOP by construction (see
# BuiltPair), so these tags also split the pair into bottom vs top. They
# are DEFINED in the dependency-free `wafer_tags` module and re-exported
# here (so the driver can import them without pulling in pymatgen/ASE).
from sabsim.structure.wafer_tags import WAFER_A_TAG, WAFER_B_TAG

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
    # The tiling GEOMETRY the strained assembly (§2.4) needs, carried from
    # the Zur-McGill match rather than thrown away: each slab's whole-number
    # 2x2 tiling matrix (§2.3's tiling_A / tiling_B) and its supercell's two
    # in-plane vectors. Defaults are None — the identity path and any match
    # reconstructed from a manifest/SharedCell do not tile — and the values
    # are nested tuples (not arrays) so the match stays serialisable and
    # comparable. The two supercells differ by the misfit strain, which the
    # tiler splits between the slabs.
    substrate_tiling: tuple = None  # 2x2 whole-number tiling of slab A
    film_tiling: tuple = None       # 2x2 whole-number tiling of slab B
    substrate_cell: tuple = None    # slab A supercell in-plane vectors, Å
    film_cell: tuple = None         # slab B supercell in-plane vectors, Å
    # The HONEST per-axis strain (§2.4): the largest PRINCIPAL strain
    # either slab feels on the even-split shared cell, as a fraction.
    # Unlike `residual_strain` above -- a rotation-invariant scalar that
    # divides by the longest edge squared and so HIDES a big strain on a
    # short axis (a thin ribbon reads deceptively low) -- this is the true
    # per-direction ceiling (`_worst_axis_strain`), what §2.4's split and
    # any ribbon-averse ranking should read. None when reconstructed from
    # a manifest (no supercell vectors to measure).
    worst_axis_strain: float = None


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

    **Oxidation states are stripped here, and this is the only place it
    happens.** Many published CIFs label sites by ION rather than by
    element — the shipped alpha-quartz file writes ``O2-`` and ``Si4+``.
    Read literally, a site's species then stringifies to ``"O2-"``, which
    is not a chemical symbol: it matches no entry in the §4.7 potential
    registry, no key in a LAMMPS type map, and no reference-data filename
    (§3.5). Every one of those lookups is keyed on the bare element.

    Stripping at LOAD rather than at each point of use is deliberate. The
    alternative — every consumer remembering to ask for ``.symbol`` — is
    a rule that must be re-obeyed by code nobody has written yet, and the
    failure it prevents is quiet: a species set that silently matches
    nothing, surfacing much later as a puzzling registry miss. One
    conversion at the boundary makes the whole pipeline downstream of it
    unable to see a charge label at all.

    Charge is not information we lose. SABSIM's data files are written
    ``atom_style atomic`` and are charge-free at this fidelity (§2.6),
    and the classical form chosen for silica in v1 is deliberately
    charge-free too (§4.7). A form that DOES carry charges assigns them
    from its own parameterization, never from a structure file's labels.
    """
    crystal = Structure.from_file(str(cif_path))
    # In-place on the pymatgen object; older releases return None, so the
    # structure is returned explicitly rather than through the call.
    crystal.remove_oxidation_states()
    return crystal


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


def orthogonalize_in_plane(slab: Atoms) -> Atoms:
    """Reduce the surface cell's in-plane tilt into LAMMPS's legal range.

    Despite the name this is a tilt REDUCTION, not a forced squaring. A
    pymatgen-cut surface cell often carries an in-plane tilt (for the
    Si(100) cell the second vector's x-component is ``-a_x``). Two things
    demand it be tamed: LAMMPS rejects — or fails to round-trip through a
    restart — a box whose tilt exceeds half the box length, AND the
    cascade gate's in-plane minimum-image math assumes an ORTHOGONAL cell
    (`activation_gate.py`). Replacing the second vector ``b`` with ``b -
    round(b_x / a_x) * a`` is a valid LATTICE operation (``b`` stays a
    lattice vector, the crystal is unchanged) that folds the tilt into the
    reduced range; for a COMMENSURATE face like Si(100)/(111) it lands on
    exactly zero, but a general oblique cell keeps a legal, non-zero tilt.

    SCOPE (see ARCHITECTURE, general-lattice support): this reduces only
    the b-against-a (xy) tilt, by a single subtraction, and never forms a
    supercell. It does NOT touch xz/yz, nor square a cell that needs
    doubling to become orthogonal. Such genuinely oblique or low-symmetry
    triclinic faces are outside v1's Si/SiO2 scope, and would still be
    mis-measured by the gate's orthogonal-cell min-image. Atoms are
    re-wrapped into the reduced cell. Returns the same object, modified.
    """
    cell = np.array(slab.get_cell())
    if abs(cell[0][0]) > 0.0:
        cell[1] = cell[1] - round(cell[1][0] / cell[0][0]) * cell[0]
    slab.set_cell(cell, scale_atoms=False)
    slab.wrap()
    return slab


def build_standalone_half(
        crystal: Structure,
        miller_face: tuple[int, int, int],
        identity: str,
        projectile_species,
        min_slab_thickness: float = 8.0,
        min_vacuum: float = 10.0,
        lateral_repeat: int = 1,
        termination_index: int = 0,
        matched_cell=None,
        shared_cell=None) -> StandaloneHalf:
    """Cut ONE wafer alone in vacuum, beam species declared (§4.3, §7.1).

    The step-3 builder for a single bonding partner. It cleaves the slab
    with the existing per-wafer :func:`build_slab` (which already opens the
    vacuum the cascade's open top needs), tiles it ``lateral_repeat`` times
    in the plane (a bigger surface spreads the dose so a single impact does
    not dominate — a §3.6 sizing knob, not physics), removes the surface
    cell's in-plane tilt (:func:`orthogonalize_in_plane`, required for
    LAMMPS and the gate), and builds the type map the amorphization runs
    under: the union of the slab's own species and the ``projectile_
    species`` the beam adds (the activation element, plus a co-deposit if
    the protocol names one). Declaring the beam here — not at bombardment
    time — is what lets the written data file carry the beam as an atom
    type with a mass, so LAMMPS can create projectile atoms against it
    (:func:`write_standalone_half`).

    ``projectile_species`` is an iterable of chemical symbols; passing it
    in (rather than reading the member here) keeps this builder decoupled
    from the protocol record and directly testable. ``identity`` is the
    material label carried for provenance and the report.

    **The strained coincidence cell (§2.4).** When ``matched_cell`` and
    ``shared_cell`` are given — a genuine lattice mismatch — the freshly cut
    slab is first built as its Zur-McGill matched supercell and strained onto
    the shared cell (:func:`tile_slab_to_shared_cell`) BEFORE the dose tiling,
    so both wafers of a dissimilar pair emerge on one commensurate cell.
    ``matched_cell`` is this slab's own matched supercell vectors
    (``match.film_cell`` for slab A, ``match.substrate_cell`` for slab B).
    Strain is applied here, at build, because amorphous material has no
    lattice to strain cleanly (§2.4). For the Si/Si identity case both are
    left ``None`` and the half is cut on its own lattice, as before — that
    case needs neither supercell nor strain. In both paths the
    ``lateral_repeat`` dose tiling then multiplies whatever cell resulted,
    which is strain-neutral (identical copies).
    """
    slab = build_slab(
        crystal, miller_face, min_slab_thickness, min_vacuum,
        termination_index)
    # A real mismatch: build the matched supercell and strain it onto the
    # shared cell (§2.4) before any dose tiling. Identity leaves both None
    # and cuts on the crystal's own lattice.
    if matched_cell is not None and shared_cell is not None:
        slab = tile_slab_to_shared_cell(slab, matched_cell, shared_cell)
    if lateral_repeat > 1:
        slab = slab.repeat((lateral_repeat, lateral_repeat, 1))
    slab = orthogonalize_in_plane(slab)
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


def _worst_axis_strain(
        substrate_cell: np.ndarray,
        film_cell: np.ndarray) -> float:
    """Largest PER-AXIS principal strain either slab feels (§2.3, §2.4).

    The rotation-invariant scalar :func:`_residual_strain` divides the
    metric-tensor difference by the LONGEST edge squared, so a severe
    strain on a SHORT axis barely registers -- a thin ribbon can read
    ~0.9% overall while one axis is really strained ~2.5%. This returns
    the honest ceiling instead. Bring both matched supercells into one
    plane with their true lengths (:func:`_coplanar_2d`), remove the twist
    (:func:`_polar_rotation`), and take the EVEN-split shared cell (§2.4) --
    exactly the steps :func:`even_split_shared_cell` uses. Then for each
    slab take the PRINCIPAL strains: the singular values of the
    deformation gradient carrying its own matched cell onto the shared
    cell, minus one. Return the largest magnitude over BOTH slabs and BOTH
    axes, as a fraction (0 = exact). This is the per-direction stretch or
    compression no axis choice can hide, and it is what the §2.4 split and
    any ribbon-averse match ranking should read.
    """
    substrate, film = _coplanar_2d(substrate_cell, film_cell)
    twist = _polar_rotation(substrate @ np.linalg.inv(film))
    film_aligned = film @ twist.T
    shared = 0.5 * (substrate + film_aligned)
    worst = 0.0
    for own in (substrate, film_aligned):
        deformation = shared.T @ np.linalg.inv(own.T)
        principal = np.linalg.svd(deformation, compute_uv=False) - 1.0
        worst = max(worst, float(np.max(np.abs(principal))))
    return worst


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
        worst_axis_strain=_worst_axis_strain(
            best.substrate_sl_vectors, best.film_sl_vectors),
        match_area=float(best.match_area),
        is_identity=(strain <= _IDENTITY_STRAIN_TOLERANCE),
        substrate_tiling=_whole_tuples(best.substrate_transformation),
        film_tiling=_whole_tuples(best.film_transformation),
        substrate_cell=_float_tuples(best.substrate_sl_vectors),
        film_cell=_float_tuples(best.film_sl_vectors))


def _whole_tuples(matrix) -> tuple:
    """A whole-number 2x2 tiling matrix as nested int tuples (§2.3)."""
    return tuple(
        tuple(int(round(entry)) for entry in row)
        for row in np.asarray(matrix))


def _float_tuples(vectors) -> tuple:
    """Supercell vectors as nested float tuples — serialisable, comparable."""
    return tuple(
        tuple(float(component) for component in row)
        for row in np.asarray(vectors))


def _polar_rotation(deformation: np.ndarray) -> np.ndarray:
    """The rotation part of a 2x2 deformation's polar decomposition.

    Any 2x2 deformation splits UNIQUELY into a pure rotation followed by a
    symmetric stretch (the polar decomposition ``M = rotation @ stretch``).
    When ``M`` carries one matched supercell onto the other (§2.3), that
    rotation IS the discovered twist and the stretch IS the misfit strain,
    so peeling the rotation off is exactly how we separate "the two slabs
    sit turned relative to each other" from "the two slabs are stretched
    relative to each other". The rotation is read from the singular-value
    decomposition (``rotation = U @ Vᵀ``), and a reflection — which a raw
    SVD can return when the deformation nearly flips an axis — is corrected
    back to a proper rotation so we never accidentally mirror a slab.
    """
    left_vectors, _stretch, right_vectors = np.linalg.svd(deformation)
    rotation = left_vectors @ right_vectors
    if np.linalg.det(rotation) < 0.0:
        # A negative determinant means SVD handed back a reflection; flip
        # the last left singular vector to turn it into a true rotation.
        left_vectors = left_vectors.copy()
        left_vectors[:, -1] *= -1.0
        rotation = left_vectors @ right_vectors
    return rotation


def _promote_to_3d(cell: np.ndarray) -> np.ndarray:
    """Return the two cell vectors as a 2x3 array (pad a zero z if 2D)."""
    matrix = np.asarray(cell, dtype=float)
    if matrix.shape[1] == 2:
        matrix = np.column_stack([matrix, np.zeros(len(matrix))])
    return matrix


def _rotation_between(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    """A 3x3 rotation mapping unit vector ``source`` onto ``target``.

    Rodrigues' formula for the minimal rotation between two directions. The
    caller pre-aligns the two to the same hemisphere, so the antiparallel
    degenerate case cannot arise and identity covers the already-aligned one.
    """
    axis = np.cross(source, target)
    sine = np.linalg.norm(axis)
    cosine = float(np.dot(source, target))
    if sine < 1.0e-12:
        return np.eye(3)
    skew = np.array([[0.0, -axis[2], axis[1]],
                     [axis[2], 0.0, -axis[0]],
                     [-axis[1], axis[0], 0.0]])
    return np.eye(3) + skew + skew @ skew * ((1.0 - cosine) / sine ** 2)


def _coplanar_2d(substrate_cell, film_cell) -> tuple:
    """Bring both matched supercells into ONE plane and express them in 2D.

    The Zur-McGill supercell vectors are 3D, and for two slabs cut on
    DIFFERENT crystal faces the two cells can live in DIFFERENT planes:
    SiO2(100)'s surface vectors tilt out of the xy-plane, LiNbO3(001)'s lie
    in it. Naively dropping the z component (the old ``[:, :2]``) then
    SHORTENS the tilted cell -- SiO2's true 4.869 A edge reads as 4.217 A --
    so the even split lands BELOW both materials and over-compresses the
    build (the ~24 GPa the T-16/T-17 oxide cells carried, which amorphized
    the crystal before any impact). Instead we ROTATE the film's plane onto
    the substrate's (a rigid 3D rotation, so the film's true lengths and its
    in-plane twist survive -- the caller's polar decomposition still removes
    the twist), then express both cells in an orthonormal basis of the
    substrate plane. That drop to 2D is lossless. For cells already
    co-planar in xy (Si/Si, and every 2D array the tests pass) the rotation
    is the identity and the basis is (x, y), so the plain-midpoint and
    twist-removal behaviours are exactly preserved.
    """
    substrate3 = _promote_to_3d(substrate_cell)
    film3 = _promote_to_3d(film_cell)
    substrate_normal = np.cross(substrate3[0], substrate3[1])
    substrate_normal = substrate_normal / np.linalg.norm(substrate_normal)
    film_normal = np.cross(film3[0], film3[1])
    film_normal = film_normal / np.linalg.norm(film_normal)
    # The cross-product normal's sign is arbitrary handedness; align the two
    # to the same hemisphere so the plane-aligning rotation is the minimal
    # one and never a spurious 180-degree flip.
    if np.dot(film_normal, substrate_normal) < 0.0:
        film_normal = -film_normal
    film3 = film3 @ _rotation_between(film_normal, substrate_normal).T
    # Orthonormal basis of the shared (substrate) plane; both cells project
    # onto it with NO length lost, since both now lie in that plane.
    first = substrate3[0] / np.linalg.norm(substrate3[0])
    second = substrate3[1] - np.dot(substrate3[1], first) * first
    second = second / np.linalg.norm(second)
    basis = np.array([first, second])
    return substrate3 @ basis.T, film3 @ basis.T


def even_split_shared_cell(
        substrate_cell: np.ndarray,
        film_cell: np.ndarray) -> np.ndarray:
    """The shared in-plane cell that splits the misfit EVENLY (§2.4).

    The Zur-McGill match (§2.3) returns each slab's own matched supercell —
    ``substrate_cell`` for slab B and ``film_cell`` for slab A — and the two
    are almost never identical: they differ by the misfit strain and,
    because the slabs may sit rotated in the plane, by a twist. Both slabs
    must end up in ONE shared cell, and §2.4 asks WHERE between their two
    natural sizes that cell should sit. This computes the EVEN split — the
    cell halfway between them — which is §2.4's baseline (the
    stiffness-and-thickness weighting comes later, once the elastic
    constants exist).

    Averaging the two supercells naively would be wrong when there is a
    twist: adding a rotated cell to an unrotated one mixes orientation into
    the size. So we first undo the twist. The deformation ``substrate_cell @
    inverse(film_cell)`` carries the film supercell onto the substrate one;
    its rotation part (:func:`_polar_rotation`) is the twist. We rotate the
    film cell into the substrate's frame with that twist, and only THEN take
    the midpoint. The result lives in the substrate's frame; each slab is
    later strained onto it (:func:`tile_slab_to_shared_cell`), the film
    absorbing the twist as part of its map. Because the midpoint is
    equidistant from both aligned cells, each slab feels half the misfit —
    the even split. The two supercells may lie in DIFFERENT planes (slabs
    cut on different faces), so they are first rotated into one plane and
    expressed in 2D with their true lengths (:func:`_coplanar_2d`) — NOT
    projected by dropping z, which would shorten a tilted cell and shrink
    the shared cell below both materials.
    """
    # Bring both cells into one plane, expressed in 2D with their TRUE
    # lengths (a naive z-drop would shorten an out-of-plane cell and shrink
    # the shared cell below both materials -- see :func:`_coplanar_2d`).
    substrate, film = _coplanar_2d(substrate_cell, film_cell)
    # Carry the film supercell onto the substrate one; the rotation part of
    # that map is the twist between the two slabs (§2.3).
    film_to_substrate = substrate @ np.linalg.inv(film)
    twist = _polar_rotation(film_to_substrate)
    # Rotate the film cell into the substrate frame (rows are vectors, so
    # the rotation acts on the right as ``film @ twistᵀ``), then split the
    # misfit evenly by taking the midpoint of the two aligned cells.
    film_aligned = film @ twist.T
    return 0.5 * (substrate + film_aligned)


def tile_slab_to_shared_cell(
        slab: Atoms,
        matched_cell: np.ndarray,
        shared_cell: np.ndarray) -> Atoms:
    """Build the slab's matched supercell and strain it onto the shared cell.

    The geometric heart of the strained-coincidence assembly (§2.3, §2.4),
    built on pymatgen's own supercell construction rather than a hand-rolled
    one. ``matched_cell`` is THIS slab's Zur-McGill matched supercell — the
    two in-plane vectors ``match.film_cell`` (slab A) or
    ``match.substrate_cell`` (slab B) carry — and ``shared_cell`` is the
    even-split cell both slabs land on (:func:`even_split_shared_cell`).

    The supercell transform is derived the way pymatgen's
    ``CoherentInterfaceBuilder`` does it (``coherent_interfaces.
    get_2d_transform``): the integer matrix that carries the slab's OWN
    primitive surface cell exactly onto ``matched_cell`` is
    ``matched_cell @ pseudo-inverse(primitive)``. Feeding the raw Zur-McGill
    TILING matrix to ``make_supercell`` instead was the old bug — ASE reads
    that matrix in a different basis and built a long 1xN strip (e.g. 189 Å)
    that, forced onto the compact shared cell, sheared atoms into ~0.8 Å
    overlaps. Deriving the transform from the matched VECTORS is basis-proof,
    and we VERIFY the built supercell reproduces them (as pymatgen does)
    rather than trusting the round.

    With the supercell already AT the matched cell's shape, straining it onto
    ``shared_cell`` (``set_cell(..., scale_atoms=True)``, holding fractional
    positions so the z/vacuum vector and the layer spacing ride along
    untouched) is a pure ~few-percent stretch — plus, for slab A, the rigid
    twist that rotates it into slab B's frame, which is an isometry and so
    squashes nothing. Because ``shared_cell`` is the even split OF the two
    matched cells, it is always close to each one, so this stretch is small
    for BOTH slabs — the reason no case (ribbon or oblique or twisted) shears.
    Both slabs set to the identical ``shared_cell`` emerge commensurate to
    numerical noise, which the assembly's commensurability assertion checks
    (:func:`sabsim.structure.amorphized_assembly._assert_commensurate`).
    """
    # pymatgen's get_2d_transform: the integer supercell matrix that carries
    # the slab's primitive surface cell onto its matched coincidence cell.
    primitive = np.asarray(slab.get_cell())[:2, :2]
    matched = np.asarray(matched_cell, dtype=float)[:, :2]
    supercell_transform = np.eye(3)
    supercell_transform[:2, :2] = np.rint(matched @ np.linalg.pinv(primitive))
    tiled = make_supercell(slab, supercell_transform)

    # VERIFY the supercell reproduces the matched vectors before straining: a
    # mismatch means the slab and match are inconsistent, and we refuse rather
    # than silently shear (the same guard pymatgen's builder raises).
    built = np.asarray(tiled.get_cell())[:2, :2]
    if not np.allclose(built, matched, atol=1.0e-6):
        raise ValueError(
            "supercell transform did not reproduce the matched cell; the "
            "slab and coincidence match are inconsistent (§2.4)")

    # Strain the correctly-shaped supercell onto the shared cell: a pure
    # in-plane stretch (plus the rigid twist for slab A), z left as cut.
    strained_cell = np.asarray(tiled.get_cell()).copy()
    strained_cell[:2, :2] = np.asarray(shared_cell, dtype=float)[:, :2]
    strained_cell[:2, 2] = 0.0
    tiled.set_cell(strained_cell, scale_atoms=True)
    return tiled


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
    pair = assemble_facing_pair(slab_a, slab_b, match, gap, grip_vacuum)
    # Drive the assembled cell's in-plane tilt to zero — the same lattice
    # reduction build_standalone_half applies to a single slab (§2.6). A
    # pymatgen coincidence cell can lean all the way to LAMMPS's skew
    # limit; read_data tolerates that, but write_restart / read_restart
    # cannot round-trip it (atoms mis-bin at the limit and are dropped),
    # so a pull that must be resumable needs the pair orthogonal. On a
    # cell that is already square this is a no-op, so Si(100) and other
    # orthogonal faces are unchanged.
    orthogonalize_in_plane(pair.atoms)
    return pair


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
    # parallel=False: this write must NOT become an MPI collective, since
    # its callers already guard it to one process (see the imports note).
    ase_write(
        path, atoms, format="lammps-data", parallel=False,
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


def read_standalone_half(
        data_file: str, type_map: dict, identity: str) -> StandaloneHalf:
    """Re-read a standalone half from its data file (§4.3, §10.1).

    The inverse of :func:`write_standalone_half`, and the read-back the
    amorphization stage uses: it opens a fresh engine per half and re-reads
    the pristine geometry FROM DISK rather than leaning on a warm in-memory
    object (ARCHITECTURE.md §4.3), so each unit is restartable and
    job-boundary-safe. ASE reads the LAMMPS data file's positions and box;
    the species behind each type id are supplied from ``type_map`` (the
    same map the file was written under), because a LAMMPS ``atomic`` data
    file records species only by mass, not symbol. The beam type carries no
    atoms in a pristine half, so the read-back is substrate-only; the full
    ``type_map`` (beam included) rides along for the cascade to create
    projectiles against.
    """
    atomic_number_of_type = {
        type_id: atomic_numbers[symbol]
        for symbol, type_id in type_map.items()}
    # parallel=False: every process reads the file for itself. Letting
    # ASE broadcast it instead deadlocks against SABSIM's own message
    # passing (see the note beside the imports).
    atoms = ase_read(
        data_file, format="lammps-data", atom_style="atomic",
        parallel=False, Z_of_type=atomic_number_of_type)
    return StandaloneHalf(
        atoms=atoms, type_map=dict(type_map), identity=identity)


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


def bulk_type_map(crystal: Structure, cells_per_axis: int) -> dict:
    """The bulk block's species type map WITHOUT writing it (§2.2).

    The MPI-safe companion to :func:`write_bulk_data`: every rank derives
    the identical, deterministic type map (to build the matching
    :class:`~sabsim.driver.commands.ForceModel` under the STRUCTURAL-1a
    species-order contract), while only ONE rank writes the data file the
    engine then reads. Same species order as ``write_bulk_data``.
    """
    return _type_map_of(bulk_atoms(crystal, cells_per_axis))


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
    # parallel=False for the same reason as every other ASE call here.
    ase_write(
        path, atoms, format="lammps-data", parallel=False,
        atom_style="atomic", specorder=species_order, masses=True)
    return type_map


def rescale_crystal_to_cell(
        crystal: Structure, conventional_cell: np.ndarray) -> Structure:
    """Return the crystal on a model-derived conventional cell (§2.2).

    The working lattice comes from relaxing the bulk under the current
    model (:func:`sabsim.driver.bulk_relax.derive_lattice`), NOT the CIF's
    published scale. This sets the crystal onto that derived cell while
    keeping the FRACTIONAL coordinates, so the basis rides along and the
    symmetry is preserved. It applies the FULL 3x3 cell, so it works for
    any shape — cubic through triclinic — carrying whatever tilt the
    relaxation found. The CIF still fixes the symmetry, basis, and
    connectivity; only the SCALE (and any relaxed tilt) is replaced.

    NOTE (§2.2 follow-on): this replaces the CELL. A crystal with internal
    degrees of freedom the symmetry does not pin (e.g. SiO2) also has
    relaxed INTERNAL coordinates the bulk relaxation found; reading those
    back is a separate refinement, tracked. For a basis fixed by symmetry
    (e.g. diamond Si) the fractional coordinates do not move, so the cell
    is the whole story.
    """
    return Structure(
        Lattice(np.asarray(conventional_cell, dtype=float)),
        crystal.species, crystal.frac_coords)
