"""Assemble two independently amorphized halves into a facing pair (§2.6).

This is the BARRIER stage of the member chain (`ARCHITECTURE.md` §4.3):
the first stage to see BOTH wafers. Each half was activated ALONE in its
own vacuum cell, on its own engine, and its amorphized final state was
written to a LAMMPS data file (the §4.3 file handoff, which is also the
run's durable record, §9). Assembly reads those two states back and
stacks them into the single facing pair the press/pull driver runs on.

The read-back does NOT come straight from a data file here — it comes
through the :class:`~sabsim.driver.engine.Engine` seam, which is what
lets this whole module be exercised on a login node with ``MockEngine``
and no LAMMPS. :func:`snapshot_amorphized_half` is the one engine-facing
bridge; everything below it (:func:`flip_in_z`, :func:`drop_disconnected`,
:func:`assemble_amorphized_pair`) is pure ASE geometry.

Four §2.6 decisions live here, each answering a specific prior-art error:

* **Flip the top half.** Both halves are bombarded on their +z top face
  (the open cascade box, §3.3). Stacked as built, the bottom half's
  activated face already points up toward the interface, but the top
  half's points up and AWAY. So the top half is mirrored in z, turning
  its activated face down to meet the bond plane. Missing this silently
  bonds an activated face to a pristine one.
* **The surface is a dividing plane, not the highest atom.** An activated
  surface is rough; a single asperity or adatom must not set the gap for
  the whole interface. The surface is where the number-density profile
  falls to half its interior value (:mod:`sabsim.driver.analysis`).
* **Ejecta go by connectivity.** A sputtered atom adrift in the vacuum is
  not part of the slab; the slab is its largest bonded cluster. NOT "cut
  at the first 4 Å z-gap" (prior art, one unlucky adatom from truncating
  the slab).
* **The clash is relieved, not fatal.** After placement the minimum
  cross-slab distance is checked; if it violates the floor the gap is
  backed off and the adjustment RECORDED, rather than aborting the member.
"""

from __future__ import annotations

import numpy as np
from ase import Atoms
from ase.neighborlist import neighbor_list

from sabsim.driver.analysis import dividing_surface
from sabsim.driver.engine import Engine
from sabsim.structure.slab_builder import (
    WAFER_A_TAG,
    WAFER_B_TAG,
    BuiltPair,
    SurfaceMatch,
    _type_map_of,
)

# Two lateral cells count as the same shared cell when their in-plane
# vectors agree to this many ångström — the commensurability §2.6 ASSERTS
# rather than assumes (prior art adopted one slab's box and ignored the
# other's). It is a numerical-noise tolerance, not a misfit budget: both
# halves were tiled to the SAME solved cell (§2.1), so any real difference
# is a bug, not a strain to absorb.
_LATERAL_CELL_TOLERANCE = 1.0e-6


# ---------------------------------------------------------------------
# The engine-facing read-back — the one bridge from a live/mock engine to
# an ASE half. Everything below this is pure geometry (§2.6).
# ---------------------------------------------------------------------

def snapshot_amorphized_half(
        engine: Engine,
        type_map: dict,
        wafer_tag: int) -> Atoms:
    """Read one amorphized half back off an engine as an ASE ``Atoms``.

    The activation stage left the damaged, re-annealed slab live in its
    engine; this reconstitutes it as an ASE object the assembly can stack.
    It reads three things across the seam — the positions, the per-atom
    LAMMPS type ids, and the box — because positions ALONE cannot rebuild
    the half: sputtering and the projectile deletion changed the
    composition, so the pre-cascade species list no longer describes the
    survivors. The type ids are mapped back to chemical symbols through
    ``type_map`` (the cascade cell's symbol->id map, inverted here), and
    the whole half is tagged ``wafer_tag`` so its provenance survives into
    the assembled pair (§6).

    The box is carried in as the ASE cell with the slab periodicity
    (periodic in the plane, open along z), matching how the half was
    simulated. Assembly re-solves the z-box once both halves are placed;
    the lateral cell is what the commensurability assertion checks.
    """
    return amorphized_half_from_arrays(
        engine.positions(), engine.types(), engine.box(),
        type_map, wafer_tag)


def amorphized_half_from_arrays(
        positions,
        type_ids,
        box,
        type_map: dict,
        wafer_tag: int) -> Atoms:
    """Reconstitute one amorphized half from raw arrays (§6, §4.3).

    The array-only core of :func:`snapshot_amorphized_half`, split out so
    the SAME reconstruction serves both activate paths: the in-process one
    passes the live engine's read-backs, the out-of-process one passes the
    positions and type ids parsed from the subprocess's dump file plus the
    slab's own cell (:func:`sabsim.driver.cascade_subprocess.read_dump_
    structure`). The type ids are mapped back to chemical symbols through
    ``type_map`` (inverted here), and the whole half is tagged ``wafer_tag``
    so its provenance survives into the assembled pair.
    """
    positions = np.asarray(positions, dtype=float)
    type_ids = np.asarray(type_ids, dtype=int)
    box = np.asarray(box, dtype=float)

    # Invert the symbol->type map so a survivor's type id names its
    # species. The map may still carry the projectile (it was built for
    # the cascade cell), but no projectile atom survives the re-anneal.
    symbol_of_type = {type_id: symbol
                      for symbol, type_id in type_map.items()}
    symbols = [symbol_of_type[int(type_id)] for type_id in type_ids]

    half = Atoms(
        symbols=symbols, positions=positions, cell=box,
        pbc=(True, True, False))
    half.set_tags([wafer_tag] * len(half))
    return half


# ---------------------------------------------------------------------
# Pure-ASE geometry: flip, ejecta removal, placement, clash relief.
# ---------------------------------------------------------------------

def flip_in_z(atoms: Atoms) -> Atoms:
    """Mirror a half in z so its activated (+z) face points DOWN (§2.6).

    The top half is bombarded on its +z top like the bottom half, so its
    activated face points up and away once stacked; mirroring about the
    half's own z-center turns that face down to meet the interface. The
    mirror maps ``z_min <-> z_max`` and leaves x, y, the species, the
    tags, and the cell untouched — a rigid reflection, no atom created or
    destroyed. An empty half is returned unchanged (nothing to mirror).
    """
    flipped = atoms.copy()
    if len(flipped) == 0:
        return flipped
    positions = flipped.get_positions()
    z_values = positions[:, 2]
    z_center = 0.5 * (z_values.min() + z_values.max())
    positions[:, 2] = 2.0 * z_center - positions[:, 2]
    flipped.set_positions(positions)
    return flipped


def _largest_bonded_cluster(atoms: Atoms, bond_cutoff: float) -> list:
    """Indices of the atoms in the largest bonded cluster (§2.6).

    Two atoms are BONDED when within ``bond_cutoff`` under the half's own
    periodicity (in-plane periodic, z open), the same neighbour relation
    the cascade physics uses. The bonded graph's connected components are
    found with a union-find over the neighbour-list edges, and the largest
    component's atom indices are returned — that component IS the slab, and
    any atom outside it is ejecta adrift in the vacuum.
    """
    atom_count = len(atoms)
    # `neighbor_list("ij", ...)` returns the two endpoint-index arrays of
    # every within-cutoff pair, honouring the atoms' pbc/cell.
    first_atom, second_atom = neighbor_list("ij", atoms, bond_cutoff)

    # Union-find with path halving — iterative, so a slab of thousands of
    # atoms cannot blow the recursion limit.
    parent = list(range(atom_count))

    def find_root(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]      # path halving
            node = parent[node]
        return node

    for left, right in zip(first_atom, second_atom):
        root_left, root_right = find_root(int(left)), find_root(int(right))
        if root_left != root_right:
            parent[root_left] = root_right

    # Tally each component's size by its root, then take the biggest.
    size_of_root: dict = {}
    root_of_atom = [find_root(index) for index in range(atom_count)]
    for root in root_of_atom:
        size_of_root[root] = size_of_root.get(root, 0) + 1
    largest_root = max(size_of_root, key=size_of_root.get)
    return [index for index in range(atom_count)
            if root_of_atom[index] == largest_root]


def drop_disconnected(atoms: Atoms, bond_cutoff: float) -> Atoms:
    """Keep only the largest bonded cluster; drop sputtered ejecta (§2.6).

    An atom that is not part of the slab's largest connected cluster is
    not part of the slab. A half with zero or one atom has nothing to
    disconnect and is returned as a copy. Tags, cell, and periodicity ride
    along on the surviving atoms (ASE fancy-indexing preserves them).
    """
    if len(atoms) <= 1:
        return atoms.copy()
    keep = _largest_bonded_cluster(atoms, bond_cutoff)
    return atoms[keep]


def _lateral_image_shifts(lateral_cell: np.ndarray) -> list:
    """The nine in-plane image shifts for a minimum-image search (§2.6).

    The lateral cell's first two vectors define the in-plane periodicity;
    a cross-slab distance must be measured to the NEAREST periodic image,
    not the raw one, or an atom near the box edge would look far from its
    true neighbour just across the boundary. For a 2-D cell the nearest
    image is among the 3x3 block of shifts ``n1*a1 + n2*a2`` with each n in
    {-1, 0, 1}; we return their (dx, dy) in-plane parts.
    """
    in_plane_a = np.asarray(lateral_cell[0])[:2]
    in_plane_b = np.asarray(lateral_cell[1])[:2]
    shifts = []
    for tile_a in (-1, 0, 1):
        for tile_b in (-1, 0, 1):
            shifts.append(tile_a * in_plane_a + tile_b * in_plane_b)
    return shifts


def _cross_slab_inplane_sq_and_gap(
        positions_a: np.ndarray,
        positions_b: np.ndarray,
        lateral_cell: np.ndarray) -> tuple:
    """Per cross-pair minimum-image in-plane distance² and vertical gap.

    For every (A atom, B atom) pair this returns two matrices (rows = B
    atoms, columns = A atoms): the SQUARED in-plane separation under the
    nearest periodic image, and the signed vertical gap ``z_B - z_A``.
    Splitting the distance this way is what lets the clash be relieved by a
    pure vertical LIFT: the in-plane part is fixed by the (unshifted)
    lateral placement, and only the vertical gap changes when B rises.
    """
    a_x, a_y, a_z = positions_a[:, 0], positions_a[:, 1], positions_a[:, 2]
    b_x, b_y, b_z = positions_b[:, 0], positions_b[:, 1], positions_b[:, 2]
    raw_dx = b_x[:, None] - a_x[None, :]
    raw_dy = b_y[:, None] - a_y[None, :]
    best_inplane_sq = None
    for shift_dx, shift_dy in _lateral_image_shifts(lateral_cell):
        delta_x = raw_dx + shift_dx
        delta_y = raw_dy + shift_dy
        inplane_sq = delta_x * delta_x + delta_y * delta_y
        best_inplane_sq = (inplane_sq if best_inplane_sq is None
                           else np.minimum(best_inplane_sq, inplane_sq))
    vertical_gap = b_z[:, None] - a_z[None, :]
    return best_inplane_sq, vertical_gap


def _min_cross_distance(
        positions_a: np.ndarray,
        positions_b: np.ndarray,
        lateral_cell: np.ndarray) -> float:
    """Closest approach between any A atom and any B atom (§2.6).

    The minimum over all cross-slab pairs of the full 3-D minimum-image
    distance. Infinite when either half is empty (no pair to clash).
    """
    if len(positions_a) == 0 or len(positions_b) == 0:
        return float("inf")
    inplane_sq, vertical_gap = _cross_slab_inplane_sq_and_gap(
        positions_a, positions_b, lateral_cell)
    distances = np.sqrt(inplane_sq + vertical_gap * vertical_gap)
    return float(distances.min())


def _required_clash_lift(
        positions_a: np.ndarray,
        positions_b: np.ndarray,
        lateral_cell: np.ndarray,
        clash_floor: float) -> float:
    """The vertical lift of B that clears the clash floor exactly (§2.6).

    A pair can only clash if its fixed in-plane distance is already below
    the floor; for such a pair the vertical gap needed to reach exactly the
    floor is ``sqrt(clash_floor² - inplane²)``, and the lift it demands is
    that needed gap minus the current one. The single lift that clears
    EVERY pair is the largest such demand (a pair already clear demands a
    non-positive lift and cannot lower the result). Applying that one lift
    puts the tightest pair exactly on the floor and every other pair above
    it — a closed-form clash relief, no iteration.
    """
    if len(positions_a) == 0 or len(positions_b) == 0:
        return 0.0
    inplane_sq, vertical_gap = _cross_slab_inplane_sq_and_gap(
        positions_a, positions_b, lateral_cell)
    floor_sq = clash_floor * clash_floor
    can_clash = inplane_sq < floor_sq
    if not np.any(can_clash):
        return 0.0
    needed_gap = np.sqrt(np.clip(floor_sq - inplane_sq, 0.0, None))
    lift_demanded = needed_gap - vertical_gap
    return float(max(0.0, lift_demanded[can_clash].max()))


def _assert_commensurate(half_a: Atoms, half_b: Atoms) -> None:
    """Assert the two halves already share a lateral cell (§2.6).

    Both halves were tiled to the SAME solved coincidence cell (§2.1), so
    their in-plane cell vectors must agree to numerical noise. Assembly
    ASSERTS this rather than assuming it — prior art adopted one slab's box
    and never looked at the other's, so a mismatch rode through silently.
    """
    cell_a = np.asarray(half_a.get_cell())[:2, :2]
    cell_b = np.asarray(half_b.get_cell())[:2, :2]
    if not np.allclose(cell_a, cell_b, atol=_LATERAL_CELL_TOLERANCE):
        raise ValueError(
            "the two halves do not share a lateral cell (DESIGN §2.6): "
            f"A in-plane {cell_a.tolist()} vs B in-plane "
            f"{cell_b.tolist()} — they were not tiled to the same "
            "coincidence cell, which is a builder bug, not a strain")


def assemble_amorphized_pair(
        half_a: Atoms,
        half_b: Atoms,
        match: SurfaceMatch,
        *,
        bond_cutoff: float,
        initial_gap: float,
        clash_floor: float,
        grip_vacuum: float = 10.0,
        bin_width: float = 1.0,
        wafer_a_species: frozenset = None,
        wafer_b_species: frozenset = None) -> BuiltPair:
    """Stack two amorphized halves into a facing pair (DESIGN §2.6, §7.5).

    The BARRIER stage. ``half_a`` and ``half_b`` are the two amorphized
    halves already read back through :func:`snapshot_amorphized_half`; both
    were bombarded on their +z top. In order (§7.5): ASSERT they share a
    lateral cell; drop each half's sputtered ejecta by connectivity; FLIP
    the top half so its activated face turns down; find each facing surface
    as a density dividing plane (not the highest atom); place B an
    ``initial_gap`` above A measured surface-to-surface; relieve any
    cross-slab clash by lifting B until the minimum cross distance clears
    ``clash_floor``, recording the lift; and record the per-wafer z-ranges
    and interface plane the driver carves its zones from (option C).

    Wafer A is the BOTTOM slab and B the TOP, the assembly invariant the
    driver relies on (§2). There is NO registry search: an amorphous-
    amorphous contact has none (STRUCTURAL 4) — the lateral offset is an
    ensemble realization variable, never tuned here. All lengths are in
    ångström. Returns the same :class:`BuiltPair` the crystalline stack
    produces, so the press/pull driver consumes either identically.
    """
    _assert_commensurate(half_a, half_b)

    # Ejecta first, so a stray sputtered atom sets neither the dividing
    # surface nor the clash. Then flip B so its activated face points down.
    lower = drop_disconnected(half_a, bond_cutoff)
    upper = drop_disconnected(half_b, bond_cutoff)
    upper = flip_in_z(upper)

    # Sit A with its base at grip_vacuum (empty space below for its grip).
    lower_positions = lower.get_positions()
    lower.translate((0.0, 0.0, grip_vacuum - lower_positions[:, 2].min()))

    # A's facing surface is its TOP dividing plane; B (now flipped) faces
    # the interface with its BOTTOM dividing plane. Both are half-density
    # crossings, robust to roughness and adatoms (§2.6).
    surface_a = dividing_surface(
        lower.get_positions()[:, 2], "top", bin_width)
    surface_b_current = dividing_surface(
        upper.get_positions()[:, 2], "bottom", bin_width)

    # Place B so its bottom dividing surface sits initial_gap above A's top
    # dividing surface — the gap is measured SURFACE-TO-SURFACE (§2.6).
    place_shift = (surface_a + initial_gap) - surface_b_current
    upper.translate((0.0, 0.0, place_shift))

    # Relieve any clash: lift B until the closest cross-slab approach
    # clears the floor, and RECORD the lift rather than aborting (§2.6).
    lateral_cell = np.asarray(lower.get_cell())
    clash_lift = _required_clash_lift(
        lower.get_positions(), upper.get_positions(), lateral_cell,
        clash_floor)
    upper.translate((0.0, 0.0, clash_lift))

    # The effective gap grew by the lift; the interface plane sits midway
    # between the two final dividing surfaces.
    surface_b_final = surface_a + initial_gap + clash_lift
    interface_z = 0.5 * (surface_a + surface_b_final)

    lower.set_tags([WAFER_A_TAG] * len(lower))
    upper.set_tags([WAFER_B_TAG] * len(upper))
    pair_atoms = lower + upper

    # A tall, z-open box: the lateral cell is A's (both share it), and z
    # spans the stacked atoms with grip_vacuum padding each outer end.
    lower_low = float(lower.get_positions()[:, 2].min())
    lower_high = float(lower.get_positions()[:, 2].max())
    upper_low = float(upper.get_positions()[:, 2].min())
    upper_high = float(upper.get_positions()[:, 2].max())
    total_z = upper_high + grip_vacuum
    pair_atoms.set_cell(
        [lateral_cell[0], lateral_cell[1], [0.0, 0.0, total_z]])
    pair_atoms.set_pbc((True, True, False))

    return BuiltPair(
        atoms=pair_atoms,
        interface_z=interface_z,
        wafer_a_z_range=(lower_low, lower_high),
        wafer_b_z_range=(upper_low, upper_high),
        type_map=_type_map_of(pair_atoms),
        match=match,
        initial_gap_adjustment=clash_lift,
        wafer_a_species=wafer_a_species,
        wafer_b_species=wafer_b_species)
