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
    ``match`` carries the coincidence provenance the pair records
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
    # clash (Å), recorded rather than aborting the pair (DESIGN §2.6).
    # Zero for the crystalline stack (no amorphous roughness to clash);
    # the amorphized assembly (:mod:`sabsim.structure.amorphized_assembly`)
    # sets it to the lift it applied.
    initial_gap_adjustment: float = 0.0
    # Each wafer's DECLARED material species set — the key its §3.5
    # activation reference is loaded by (DESIGN.md §3.5). Recorded per
    # wafer, NOT from the global type_map, so the gate can tell a SiO2
    # wafer ({O, Si}) from a LiNbO3 wafer ({Li, Nb, O}) and judge each
    # against its own reference. Declared (from the pre-cascade half), not
    # inferred from survivors, so a fully-sputtered species does not change
    # the key. None on the crystalline/identity path and any pair built
    # before this field existed; the gate then falls back to the global
    # type_map (unchanged for a same-material pair, where the two coincide).
    wafer_a_species: frozenset = None
    wafer_b_species: frozenset = None


@dataclass
class StandaloneHalf:
    """One wafer cut ALONE in vacuum, ready to be bombarded (§4.3, §7.1).

    The chain for a bonding pair prepares each surface BY ITSELF before
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
    and the universal foundation MLIP that runs every stage is
    charge-free too (§4.7). A form that DOES carry charges assigns them
    from its own parameterization, never from a structure file's labels.
    """
    crystal = Structure.from_file(str(cif_path))
    # In-place on the pymatgen object; older releases return None, so the
    # structure is returned explicitly rather than through the call.
    crystal.remove_oxidation_states()
    return crystal


# How closely two numbers that should be equal must agree when the
# builder checks the cleaving tool's record against the slab it was
# handed: relative, on squared lengths and on the cosine of an angle.
_ORIENTATION_TOLERANCE = 1.0e-6


def slab_top_normal(cell_vectors) -> np.ndarray:
    """The unit normal of a slab's surface, pointing out of its TOP.

    The surface is the plane of the first two cell vectors; the top is
    the side the third vector points to.
    """
    cell = np.array(cell_vectors, dtype=float)
    normal = np.cross(cell[0], cell[1])
    normal = normal / np.linalg.norm(normal)
    return normal if np.dot(normal, cell[2]) > 0.0 else -normal


def face_sense(crystal: Structure, cut_slab,
               miller_face: tuple[int, int, int]) -> int:
    """+1 when a cut slab's top IS the face asked for, -1 when it is
    the opposite face and the slab must be turned over (DESIGN §2.5).

    The face names the slab's top: its outward normal is the face's
    own reciprocal-lattice vector ``h a* + k b* + l c*`` in the
    crystal file's axes. pymatgen returns either side up — the same
    slab for GaN (001) and (00-1) — but it RECORDS the slab cell's
    three vectors in the crystal's lattice coordinates
    (``scale_factor``), and the third is the way to the top. So the
    sense is the sign of ``h u + k v + l w`` for that third vector
    ``[u v w]``.

    The record is trusted only after it is shown to describe the slab
    that was handed over: the same lengths and angles (the slab cell
    is the record rigidly rotated), the same handedness (rotated, not
    mirrored), and an in-plane pair perpendicular to the face's
    normal. Anything else is refused rather than oriented by guess.
    """
    face = np.array(miller_face, dtype=float)
    recorded = np.array(cut_slab.scale_factor, dtype=float)
    in_crystal_frame = recorded @ crystal.lattice.matrix
    slab_cell = np.array(cut_slab.lattice.matrix, dtype=float)
    face_normal = (
        face @ crystal.lattice.reciprocal_lattice_crystallographic.matrix)

    lengths_and_angles = in_crystal_frame @ in_crystal_frame.T
    same_shape = np.allclose(
        lengths_and_angles, slab_cell @ slab_cell.T, rtol=0.0,
        atol=_ORIENTATION_TOLERANCE * np.abs(lengths_and_angles).max())
    same_hand = (np.linalg.det(in_crystal_frame)
                 * np.linalg.det(slab_cell)) > 0.0
    plane_normal = np.cross(in_crystal_frame[0], in_crystal_frame[1])
    alignment = abs(np.dot(plane_normal, face_normal)) / (
        np.linalg.norm(plane_normal) * np.linalg.norm(face_normal))
    in_the_face = alignment > 1.0 - _ORIENTATION_TOLERANCE
    if not (same_shape and same_hand and in_the_face):
        raise ValueError(
            f"the slab cut for face {tuple(miller_face)} does not match "
            f"the cleaving tool's own record of it (same shape: "
            f"{same_shape}, same handedness: {same_hand}, in the face: "
            f"{in_the_face}), so which side is its top cannot be told; "
            f"the slab is refused rather than oriented by guess "
            f"(DESIGN §2.5)")
    way_to_the_top = float(np.dot(in_crystal_frame[2], face_normal))
    return 1 if way_to_the_top > 0.0 else -1


def turn_slab_over(slab: Atoms) -> Atoms:
    """Turn a slab over so its bottom becomes its top (DESIGN §2.5).

    A ROTATION by half a turn about an in-plane axis, never a mirror: a
    mirror would turn a handed crystal (quartz) into its twin. The axis
    is perpendicular to the surface normal AND to the third cell
    vector, so that vector is carried exactly onto its own negative and
    the turned slab keeps the same cell height and vacuum. The first
    cell vector is carried along; the second is carried along and
    negated — negating a lattice vector leaves the lattice as it was —
    which makes the cell right-handed again. Atoms are wrapped back
    into the cell, where a slab centred in the vacuum stays centred.
    Returns a new object.
    """
    cell = np.array(slab.get_cell(), dtype=float)
    normal = slab_top_normal(cell)
    axis = np.cross(cell[2], normal)
    if np.linalg.norm(axis) < _ORIENTATION_TOLERANCE * np.linalg.norm(
            cell[2]):
        # The third vector is along the normal, so every in-plane axis
        # reverses both; the first cell vector is one.
        axis = cell[0]
    axis = axis / np.linalg.norm(axis)
    # Half a turn about a unit axis u sends p to 2 (p.u) u - p. The
    # matrix is symmetric, so it acts the same on rows as on columns.
    half_turn = 2.0 * np.outer(axis, axis) - np.eye(3)
    turned = slab.copy()
    turned.set_cell(
        [cell[0] @ half_turn, -(cell[1] @ half_turn), cell[2]],
        scale_atoms=False)
    turned.set_positions(slab.get_positions() @ half_turn)
    turned.wrap()
    return turned


def slab_terminations(
        crystal: Structure,
        miller_face: tuple[int, int, int],
        min_slab_thickness: float = 8.0,
        min_vacuum: float = 10.0) -> list:
    """Every termination of a face, as ASE slabs, in builder order.

    A face can usually be cut on more than one atomic plane; each cut
    is a TERMINATION. :func:`build_slab` takes one of these by its
    position in this list, and ``sabsim catalog add`` describes all of
    them (DESIGN.md §10.11), so both read the one list made here.

    Every slab is returned the RIGHT WAY UP: its top is the face that
    was asked for, sign included (:func:`face_sense`), so (001) and
    (00-1) are the two sides of the same cuts.
    """
    generator = SlabGenerator(
        crystal, miller_index=tuple(miller_face),
        min_slab_size=min_slab_thickness, min_vacuum_size=min_vacuum,
        center_slab=True)
    terminations = []
    for cut_slab in generator.get_slabs():
        slab = AseAtomsAdaptor.get_atoms(cut_slab)
        if face_sense(crystal, cut_slab, miller_face) < 0:
            slab = turn_slab_over(slab)
        terminations.append(slab)
    return terminations


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

    The slab's TOP is the face asked for, sign included: (00-1) is the
    other side of the (001) cut, not the same slab (§2.5).
    """
    candidates = slab_terminations(
        crystal, miller_face, min_slab_thickness, min_vacuum)
    if termination_index >= len(candidates):
        raise IndexError(
            f"termination {termination_index} out of range: the "
            f"{miller_face} face has {len(candidates)} termination(s)")
    return candidates[termination_index]


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
    in (rather than reading the pair here) keeps this builder decoupled
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
    # One number repeats both edges alike (the bootstrap's clean
    # surfaces); a pair repeats each edge its own number of times (the
    # project box, :func:`~sabsim.pipeline.live_stages.box_repeats`).
    if isinstance(lateral_repeat, (int, np.integer)):
        lateral_repeat = (int(lateral_repeat), int(lateral_repeat))
    repeat_first, repeat_second = (int(n) for n in lateral_repeat)
    if repeat_first > 1 or repeat_second > 1:
        slab = slab.repeat((repeat_first, repeat_second, 1))
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
    film_aligned = _film_turned_onto_substrate(substrate, film)
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
    and judges every candidate by what it would BUILD (revised
    2026-09-28, DESIGN §2.3; LEDGER T-45):

    * each candidate's two supercells are put in counterclockwise
      order, and the film's is tried in every equivalent description
      of the same lattice (:func:`_best_film_description`);
    * its strain is the PER-AXIS strain of the §2.4 shared cell — the
      largest stretch or compression, along any direction, either
      crystal undergoes (:func:`_worst_axis_strain`);
    * a candidate over ``misfit_tolerance`` is rejected (pymatgen's own
      length tolerance is only a pre-filter: it compares edge lengths
      and an unsigned angle, and so admits pairs that cannot be built);
    * of the survivors the LEAST strained is taken, the smaller area
      breaking a tie.

    For identical lattices (Si/Si) the winner is the primitive surface
    cell at zero strain, which is the matcher's null test.
    """
    vectors_a = _surface_vectors(slab_a)
    vectors_b = _surface_vectors(slab_b)
    generator = ZSLGenerator(
        max_area=max_area, max_length_tol=misfit_tolerance)
    survivors = []
    least_rejected = None
    for candidate in generator(vectors_a, vectors_b):
        substrate_cell, substrate_tiling = _counterclockwise(
            np.asarray(candidate.substrate_sl_vectors, dtype=float),
            np.asarray(candidate.substrate_transformation, dtype=float))
        film_cell, film_tiling, strain = _best_film_description(
            substrate_cell,
            np.asarray(candidate.film_sl_vectors, dtype=float),
            np.asarray(candidate.film_transformation, dtype=float))
        if strain > misfit_tolerance:
            if least_rejected is None or strain < least_rejected:
                least_rejected = strain
            continue
        survivors.append((
            round(strain, _STRAIN_RANKING_DECIMALS),
            float(candidate.match_area), len(survivors),
            substrate_cell, substrate_tiling, film_cell, film_tiling,
            strain))
    if not survivors:
        nearest = ("" if least_rejected is None else
                   f" (the least strained candidate needs "
                   f"{100.0 * least_rejected:.2f} %)")
        raise ValueError(
            f"no coincidence cell within the area budget ({max_area:g} "
            f"A^2) whose built per-axis strain is within the misfit "
            f"tolerance ({100.0 * misfit_tolerance:g} %){nearest} (§2.3): "
            f"loosen misfit_tolerance or raise max_coincidence_area")
    (_, area, _, substrate_cell, substrate_tiling, film_cell,
     film_tiling, strain) = min(survivors, key=lambda row: row[:3])
    residual = _residual_strain(substrate_cell, film_cell)
    return SurfaceMatch(
        residual_strain=residual,
        worst_axis_strain=strain,
        match_area=area,
        is_identity=(residual <= _IDENTITY_STRAIN_TOLERANCE),
        substrate_tiling=_whole_tuples(substrate_tiling),
        film_tiling=_whole_tuples(film_tiling),
        substrate_cell=_float_tuples(substrate_cell),
        film_cell=_float_tuples(film_cell))


# Two candidates whose strains agree to this many decimals are ranked by
# area: a difference in the fifth decimal of a strain is arithmetic
# noise, not a reason to build a larger cell.
_STRAIN_RANKING_DECIMALS = 4

# The descriptions of ONE lattice that keep its edges in the same
# rotational order: the pair as given, both edges reversed, and the two
# exchanges of the edges with one reversed. Each is a whole-number
# matrix of determinant +1 applied to the two edge vectors (and to the
# tiling, which maps the primitive surface cell onto them).
_SAME_ORDER_DESCRIPTIONS = (
    np.array([[1.0, 0.0], [0.0, 1.0]]),
    np.array([[-1.0, 0.0], [0.0, -1.0]]),
    np.array([[0.0, 1.0], [-1.0, 0.0]]),
    np.array([[0.0, -1.0], [1.0, 0.0]]),
)


def _turns_counterclockwise(cell: np.ndarray) -> bool:
    """True when edge 1 to edge 2 turns counterclockwise seen from +z.

    The slabs are cut with the surface normal along +z, so the sign of
    the z component of ``edge_1 x edge_2`` is the rotational order.
    """
    edges = _promote_to_3d(cell)
    return float(np.cross(edges[0], edges[1])[2]) > 0.0


def _counterclockwise(cell: np.ndarray, tiling: np.ndarray) -> tuple:
    """The cell and its tiling with the edges in counterclockwise order.

    Reversing edge 2 describes the SAME lattice (the reversed vector is
    a lattice vector too) in the opposite rotational order; the tiling
    row that builds edge 2 is reversed with it.
    """
    if _turns_counterclockwise(cell):
        return cell, tiling
    reverse_second = np.array([[1.0, 0.0], [0.0, -1.0]])
    return reverse_second @ cell, reverse_second @ tiling


def _best_film_description(
        substrate_cell: np.ndarray, film_cell: np.ndarray,
        film_tiling: np.ndarray) -> tuple:
    """The film supercell described so it best fits the substrate's.

    pymatgen pairs edge 1 with edge 1 and edge 2 with edge 2, but
    compares only lengths and an unsigned angle, so the pairing it
    reports may be a mirror image or have its edges exchanged (DESIGN
    §2.3). The film's cell is put in counterclockwise order and each
    same-order description of its lattice is measured against the
    substrate; the one of least per-axis strain is returned, with its
    tiling and that strain.
    """
    film_cell, film_tiling = _counterclockwise(film_cell, film_tiling)
    best = None
    for description in _SAME_ORDER_DESCRIPTIONS:
        described = description @ film_cell
        strain = _worst_axis_strain(substrate_cell, described)
        if best is None or strain < best[2]:
            best = (described, description @ film_tiling, strain)
    return best


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
    # Turn the film cell onto the substrate cell (the twist, §2.3), then
    # split the misfit evenly: the midpoint of the two aligned cells.
    film_aligned = _film_turned_onto_substrate(substrate, film)
    return 0.5 * (substrate + film_aligned)


def _film_turned_onto_substrate(
        substrate: np.ndarray, film: np.ndarray) -> np.ndarray:
    """The film cell rotated so its edges lie along the substrate's.

    Both cells are 2x2 with ONE EDGE VECTOR PER ROW. The linear map that
    carries each film edge onto the corresponding substrate edge acts
    on a vector from the left, ``map @ film_edge = substrate_edge``, so
    with rows as vectors it is ``substrate.T @ inverse(film.T)``. Its
    rotation part is the twist, and rotating each film edge by it is
    ``film @ twist.T``.

    CORRECTED 2026-09-28 (DESIGN §2.4, LEDGER T-45). The rotation used
    to be taken from ``substrate @ inverse(film)``, a different matrix:
    for a square cell it is the TRANSPOSE of the right one, so the
    angle came out with the wrong sign, and for an elongated cell the
    angle itself was wrong. The film was turned AWAY from the
    substrate, and the midpoint of two misaligned cells is shorter than
    either — 20 % short for silicon (100) on quartz (001), 0.4 % for
    the 5.4-degree oxide cell of LEDGER T-20.

    The two cells must be listed in the SAME rotational order (both
    counterclockwise). A clockwise film against a counterclockwise
    substrate is a mirror image, which no rotation can align; that is
    refused here rather than forced (:func:`match_surfaces` puts every
    candidate in counterclockwise order before it reaches this).
    """
    if np.linalg.det(substrate) * np.linalg.det(film) <= 0.0:
        raise ValueError(
            "the two matched cells list their edges in opposite "
            "rotational order (one clockwise, one counterclockwise): "
            "no rotation aligns a cell with its mirror image (§2.3)")
    twist = _polar_rotation(substrate.T @ np.linalg.inv(film.T))
    return film @ twist.T


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
    live project runs on it; for now it is exercised directly on Si/Si.
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
    charges — the foundation MLIP and the {Si,O} committee are both
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
        path, _without_stale_type_array(atoms), format="lammps-data",
        parallel=False, atom_style="atomic", specorder=species_order,
        masses=True)


def _without_stale_type_array(atoms: Atoms) -> Atoms:
    """A copy of ``atoms`` with any leftover LAMMPS ``type`` array gone.

    A structure read back from a LAMMPS dump keeps the dump's raw type
    ids in ``atoms.arrays["type"]``, and ASE's data-file writer (3.29)
    PREFERS that array to the ``specorder`` it is handed: it numbers the
    atoms by the stale ids while writing the ``Masses`` section in the
    requested order. When the two orders differ — a melt-quench frame
    whose MD stage numbered {O: 1, Si: 2}, re-written for the descriptor
    stage under {Si: 1, O: 2} — every atom silently changes species on
    disk, and nothing downstream can notice (LEDGER T-42: the silica
    environment library read 0.000 of its own glass as disordered).
    Dropping the array makes the CHEMICAL SYMBOLS the only source of an
    atom's type, which is what ``type_map`` promises.
    """
    if "type" not in atoms.arrays:
        return atoms
    cleaned = atoms.copy()
    del cleaned.arrays["type"]
    return cleaned


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
        path, _without_stale_type_array(atoms), format="lammps-data",
        parallel=False, atom_style="atomic", specorder=species_order,
        masses=True)
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
