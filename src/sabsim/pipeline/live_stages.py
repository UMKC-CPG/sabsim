"""The REAL pipeline stage bodies (ARCHITECTURE.md §4.3, §5.1).

These are the physics-bearing counterparts of the walking-skeleton stubs
in :mod:`sabsim.pipeline.skeleton_stages`: they build real slabs, open a
real ``LammpsEngine`` per half, and produce real amorphized structures.
They speak the SAME contracts the stubs do, so the sequencer runs either
set behind the same seams (the stub set on the login node for control-flow
tests, this set on a compute node for a real run).

The build->amorphize->assemble chain here is exactly ARCHITECTURE.md §4.3:

* :func:`build_halves` (step 3) cuts each wafer ALONE, writes it to a
  LAMMPS data file under the pair's scratch, and returns a
  :class:`~sabsim.pipeline.exec_artifacts.HalfHandle` per half — the
  build->amorphize file handoff. Login-node work (no LAMMPS).
* the activation stage (step 4) re-reads each pristine half from its
  handle, runs the cascade OUT-OF-PROCESS under the universal MLIP (the
  deepmd bundle's own LAMMPS), and writes the amorphized half back.
  Compute-node work; cascade-only (§3.4).
* the assembly stage (step 5) reads both amorphized halves back and stacks
  them into a facing pair (:mod:`sabsim.structure.amorphized_assembly`).

The module imports cleanly with NO LAMMPS present — ``LammpsEngine``
imports the binding lazily inside its constructor — so the login node can
build halves and review the whole chain; only the stages that open an
engine or spawn the bundle need a compute node.

SIZING is carried by the project's ``[numerical]`` block, not pinned in
this module. Slab thickness is the §2.5 CRITERION — enough undamaged
crystal beneath the amorphized skin — enforced as a floor over the chosen
``slab_thickness``, the project's ``required_activated_depth``,
and the ``minimum_bulk_thickness`` cushion (:func:`_effective_slab_thickness`).
The lateral dose footprint (``target_footprint_area``), the ``slab_vacuum``,
and the §2.2 ``bulk_cells_per_axis`` are likewise spec inputs. The template
defaults reproduce the §3.6-pinned Si cell, so the measured 7 Å depth
threshold that cell anchors is preserved; a new material re-tunes them
against the same slab-size <-> bombardment-energy <-> DFT-cost trade.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import NamedTuple

import numpy as np
from ase.io import read as ase_read
from ase.io import write as ase_write

from sabsim.driver.cascade import (
    CascadeControl,
    CascadeOutcome,
    _projectile_species,
    build_activate_script,
    derive_bombardment_spec,
    derive_seeds,
)
from sabsim.driver.bulk_relax import (
    bulk_relax_subprocess_script,
    conventional_cell,
    cubic_lattice_constant,
    read_data_box,
)
from sabsim.driver.activation_gate import (
    activation_gate,
    load_activation_references,
)
from sabsim.driver.cascade_potential import (
    resolve_cascade_generator,
    universal_force_model,
)
from sabsim.driver.cascade_subprocess import (
    read_dump_structure,
    run_activate_subprocess,
)
from sabsim.driver.environment_library import load_environment_library
from sabsim.driver.commands import (
    CascadeGeometry,
    ForceModel,
    _rate_slug,
    deepmd_model,
    stage_dump_file,
    to_metal,
)
from sabsim.pipeline.activation_adapter import (
    activated_slabs_from_results,
    verdict_from_activation,
)
from sabsim.pipeline.exec_artifacts import (
    ActivatedHalf,
    DerivedLattices,
    HalfHandle,
    SharedCell,
    Slab,
    Structure,
)
from sabsim.pipeline.run_options import trajectory_options
from sabsim.spec.references import resolve_crystal_file
from sabsim.spec.records import PairSpecification
from sabsim.structure.amorphized_assembly import (
    amorphized_half_from_arrays,
    assemble_amorphized_pair,
)
from sabsim.structure.slab_builder import (
    WAFER_A_TAG,
    WAFER_B_TAG,
    SurfaceMatch,
    build_standalone_half,
    bulk_type_map,
    even_split_shared_cell,
    load_crystal,
    match_surfaces,
    read_standalone_half,
    rescale_crystal_to_cell,
    write_bulk_data,
    write_lammps_data,
    write_standalone_half,
)

# Cascade engineering knobs and the bond cutoff, all documented STAND-INS.
_GEOMETRY = CascadeGeometry()           # 4 Å base + 6 Å border + 10 Å spawn
_CONTROL = CascadeControl(cascade_step_cap=20000)   # halt backstop
_BOND_CUTOFF = 2.8   # Å: Si first-g(r)-minimum stand-in (§6.3, TODO)

# Slab SIZING now lives in the spec's [numerical] block, no longer pinned
# here (§2.5, §3.6). Four inputs shape each half: the total
# ``slab_thickness`` (the §3.6 convergence value), the build-time
# ``required_activated_depth`` and the ``minimum_bulk_thickness``
# cushion that together form the §2.5 thickness FLOOR
# (:func:`_effective_slab_thickness`), the ``slab_vacuum`` above the face
# for the beam spawn, and the §2.2 ``bulk_cells_per_axis`` relax-block
# size. The width that once "bit us" — a narrow cell over-deepening the
# skin — is likewise the project's ``target_footprint_area``
# (:func:`box_repeats`). The defaults reproduce the §3.6-pinned Si
# cell (55 Å thick, ~38 Å wide), so the measured 7 Å depth threshold that
# cell anchors is preserved.


def _publish_file(comm, write_action) -> None:
    """Write a handoff file on ONE rank, then publish it to the others.

    Every stage that hands a file to the next stage faces the same
    situation under MPI: all ranks hold the same data and would all
    happily write it, but they would be writing the SAME path at the
    same moment and would corrupt each other's output. So exactly one
    rank writes.

    The barrier afterwards is not decoration. Without it the other ranks
    race ahead and may try to read a file that rank 0 has not finished —
    or not started — writing, which is how a stage ends up parsing a
    half-written structure. Blocking here means that when this function
    returns, the file is on disk and every rank may read it.

    ``write_action`` is a no-argument callable performing the write, so
    each caller keeps its own writer and format while the rank
    discipline lives in exactly one place.
    """
    rank = comm.Get_rank() if comm is not None else 0
    if rank == 0:
        write_action()
    if comm is not None:
        comm.Barrier()


def _resolve_cif(cif_source: str) -> str:
    """Find a wafer's crystal file (delegates to the shared resolver).

    The search rules live in :mod:`sabsim.spec.references` so that
    phase-three validation and the stages that actually open the file
    look in exactly the same places. A checker searching different
    locations than the loader would either pass runs that then fail, or
    fail runs that would have worked.
    """
    return resolve_crystal_file(cif_source)


def _pair_species_union(pair: PairSpecification) -> frozenset:
    """Every element either wafer contributes, read from the crystals.

    STRUCTURAL 1a puts ONE potential over the union of the pair's species,
    and DESIGN.md §4.3 makes that concrete as a single global type map
    shared by every pair "so type index k means the same element
    everywhere". A half cut ALONE would otherwise declare only its own
    elements — a silicon half in a Si/SiO2 pair would carry no oxygen
    type — and two consequences follow that this function exists to
    prevent. The force-model lookup is keyed on (species, domain)
    (§4.8), so a silicon-only half could not resolve the pair's
    declared silicon-and-silica domain at all. And the assembly would
    have to reconcile two different type maps rather than one.

    The union is read from the CRYSTALS rather than parsed out of the
    material labels, because the CIF is the authoritative structure
    (§1.2) and a label like "SiO2" is a human name we have promised not
    to treat as a source of truth.
    """
    symbols = set()
    for wafer in (pair.material.wafer_a, pair.material.wafer_b):
        crystal = load_crystal(_resolve_cif(wafer.cif_source))
        # A pymatgen Structure, so the elements come off its composition
        # rather than an ASE-style symbol list. ``load_crystal`` already
        # stripped any oxidation states, so these are bare symbols;
        # ``.symbol`` is belt-and-braces and costs nothing.
        symbols.update(
            element.symbol for element in crystal.composition.elements)
    return frozenset(symbols)


def _coupling_for(crystal) -> str:
    """The ``box/relax`` cell coupling matched to the crystal's symmetry.

    ``iso`` for a cubic cell (one uniform scale keeps it cubic), ``aniso``
    for an orthogonal but non-cubic cell (each axis relaxes independently),
    ``tri`` for anything with a non-right angle (all six cell DOF relax).
    Choosing by symmetry keeps a high-symmetry crystal from picking up a
    spurious tilt while still supporting the general, non-cubic case (§2.2).
    """
    a, b, c = crystal.lattice.abc
    orthogonal = all(
        abs(angle - 90.0) < 1.0 for angle in crystal.lattice.angles)
    if not orthogonal:
        return "tri"
    if abs(a - b) < 1.0e-4 and abs(b - c) < 1.0e-4:
        return "iso"
    return "aniso"


def derive_lattices_live(
        pair: PairSpecification,
        scratch_directory: str,
        comm=None) -> DerivedLattices:
    """Derive each material's working lattice under the model (§2.2, step 2b).

    The FIRST use of the force engine and the smallest: for each UNIQUE
    material in the pair (a Si/Si pair derives once), it replicates the
    crystal into a periodic bulk block, relaxes the box to zero pressure
    under the current model, and reads the equilibrium conventional cell
    back — the cell the build then cuts slabs on, retiring the CIF's
    published scale (which would leave the box stressed at step zero,
    §2.2). "The current model" is universal-first (DESIGN §4.7): by default
    the block relaxes under the SAME universal MLIP the cascade then
    bombards under, so the working lattice and the amorphizing potential
    agree — a cell equilibrated under one description and bombarded under
    another starts stressed (the offset that detonated the oxide bring-up).
    That model lives in deepmd's own bundle and cannot load in-process
    (ARCHITECTURE §4.1/§4.4), so the universal derivation runs OUT-OF-
    PROCESS through the same file handoff as ``activate``
    (:func:`~sabsim.driver.bulk_relax.bulk_relax_subprocess_script`, read
    back by :func:`~sabsim.driver.bulk_relax.read_data_box`). Compute-node
    work: the bulk data file is written by one rank, and the one GPU
    subprocess is driven by the primary rank while peers wait at a barrier.
    """
    cells: dict = {}
    provenance: list = []
    allow_unvalidated = pair.potential.allow_unvalidated
    rank = comm.Get_rank() if comm is not None else 0
    # The §2.2 bulk-relax block size is a spec knob (numerical), not pinned.
    bulk_cells = pair.numerical.bulk_cells_per_axis
    for wafer in (pair.material.wafer_a, pair.material.wafer_b):
        if wafer.identity in cells:
            continue                     # same material: derive once
        crystal = load_crystal(_resolve_cif(wafer.cif_source))
        type_map = bulk_type_map(crystal, bulk_cells)
        coupling = _coupling_for(crystal)
        bulk_file = os.path.join(
            str(scratch_directory), f"bulk_{wafer.identity}.data")
        _publish_file(comm, lambda: write_bulk_data(
            crystal, bulk_cells, bulk_file))

        # Relax under the foundation MLIP out-of-process in its bundle
        # (§4.7), then read the relaxed cell back.
        model = universal_force_model(
            type_map, pair.potential.universal_weights,
            allow_unvalidated=allow_unvalidated,
            model_name=pair.potential.universal_model)
        relaxed_file = os.path.join(
            str(scratch_directory), f"relaxed_bulk_{wafer.identity}.data")
        script = bulk_relax_subprocess_script(
            bulk_file, model, relaxed_file, coupling=coupling)
        if rank == 0:
            run_activate_subprocess(
                script, str(scratch_directory), relaxed_file,
                script_name=f"derive_{wafer.identity}.in",
                log_name=f"log.derive_{wafer.identity}")
        if comm is not None:
            comm.Barrier()
        relaxed_block_cell, _ = read_data_box(relaxed_file)
        derived_cell = conventional_cell(relaxed_block_cell, bulk_cells)
        lattice_edge = cubic_lattice_constant(relaxed_block_cell, bulk_cells)
        note = "universal MLIP (out-of-process)"

        cells[wafer.identity] = tuple(
            tuple(float(component) for component in row)
            for row in derived_cell)
        provenance.append(
            f"{wafer.identity}: a~{lattice_edge:.4f} A, {note}")
    return DerivedLattices(cells=cells, provenance="; ".join(provenance))


def _effective_slab_thickness(pair) -> float:
    """The §2.5 thickness FLOOR: enough bulk beneath the damaged skin.

    A cut slab must keep enough undamaged crystal under the amorphized skin
    to behave like a real substrate, which §2.5 states as the criterion
    ``thickness >= required_activated_depth + minimum_bulk_thickness``.
    The skin depth is only MEASURED after bombardment (§3.5), but the slab
    is cut before that, so the depth term is the depth the project REQUIRES
    the activation to reach (``[protocol.activation]
    required_activated_depth``, the same number the §3.5 gate demands;
    revised 2026-08-28).

    v1 does NOT derive the thickness from that sum — it FIXES the thickness
    by the §3.6 convergence study (``slab_thickness``, the measurement-
    anchored 55 Å Si cell) and uses the criterion as a floor: the larger of
    the chosen thickness and the required minimum. So the anchored cell is
    preserved wherever it already satisfies the criterion (55 > 7 + 30 for
    the Si default), while any material whose estimated skin is deeper than
    the chosen thickness allows automatically gets a thicker slab. The
    caller records the resulting margin (:func:`build_halves`).
    """
    chosen = to_metal(pair.numerical.slab_thickness, "distance")
    required = (
        to_metal(pair.protocol.required_activated_depth, "distance")
        + to_metal(pair.numerical.minimum_bulk_thickness, "distance"))
    return max(chosen, required)


def box_repeats(base_cell, target_area: float,
                minimum_width: float) -> tuple:
    """How many times to repeat each edge of the matched cell (§2.4).

    The coincidence match fixes the SHAPE of the shared cell; the box
    the simulation runs in is that cell repeated a whole number of
    times along each of its two edges. Two requirements set the two
    numbers (DESIGN §2.4, revised 2026-09-28, Paul):

    * the box must be at least ``minimum_width`` across in each
      direction — narrower than twice the force model's interaction
      radius an atom feels its own periodic copy, and a collision
      cascade meets itself;
    * the box area must reach ``target_area``, the dose-spreading
      footprint of §3.6, so no single impact dominates the dose.

    The WIDTH in the direction of an edge is the perpendicular distance
    between the two sides the OTHER edge runs along: the cell's area
    divided by the other edge's length. For a rectangle that is the
    edge's own length; for a slanted cell it is shorter. Each edge is
    first repeated until the box is wide enough its way, and then the
    NARROWER direction is repeated once more for as long as that brings
    the area closer to the target — so a long thin cell becomes a nearly square
    box instead of a long thin one repeated equally both ways (the
    9.4 A oxide ribbon of LEDGER T-18). Repeating is strain-neutral: it
    lays down identical copies of an already-matched cell.

    ``base_cell`` is the 2x2 in-plane cell, one edge vector per row.
    Returns ``(repeats of edge 1, repeats of edge 2)``.
    """
    cell = np.asarray(base_cell, dtype=float)[:2, :2]
    area = abs(float(np.linalg.det(cell)))
    if area <= 0.0:
        return (1, 1)
    edge_lengths = np.linalg.norm(cell, axis=1)
    widths = (area / float(edge_lengths[1]), area / float(edge_lengths[0]))
    repeats = [max(1, int(np.ceil(minimum_width / width - 1.0e-9)))
               for width in widths]
    while True:
        narrower = (0 if repeats[0] * widths[0] <= repeats[1] * widths[1]
                    else 1)
        grown = list(repeats)
        grown[narrower] += 1
        area_now = repeats[0] * repeats[1] * area
        area_grown = grown[0] * grown[1] * area
        # The target is a size to come CLOSE to, not a floor: stop when
        # one more repeat would leave the area further from it.
        if abs(area_grown - target_area) >= abs(area_now - target_area):
            return (repeats[0], repeats[1])
        repeats = grown


def _standalone_half(
        wafer, pair, derived_lattices, declared_species,
        lateral_repeat=1,
        matched_cell=None, shared_cell=None):
    """Cut ONE wafer's standalone half in memory (no file yet, §2.2/§7.1).

    Loads the wafer's crystal, RESCALES it to the model-derived lattice for
    its material (:func:`rescale_crystal_to_cell`, §2.2 — so the slab is
    cut on the model's own spacing, not the CIF's), and builds the
    standalone half in vacuum with the beam species declared. Split out
    from the write so :func:`build_halves` can hold both slabs at once.

    ``lateral_repeat`` defaults to 1 — the PRIMITIVE surface cell the
    coincidence match (§2.3) operates on, since that runs on primitive
    lattices, not the tiled dose footprint. :func:`build_halves` passes the
    dose-spreading footprint tiling explicitly, sized from the project's
    ``target_footprint_area`` and ``minimum_cell_width``
    (:func:`box_repeats`, §2.4).
    ``matched_cell`` and ``shared_cell`` carry the §2.4 strained-tiling
    geometry for a real mismatch (this wafer's own matched supercell vectors
    and the shared cell both wafers are strained onto); they stay ``None``
    for the identity case, which needs neither. ``declared_species`` are the
    elements this half must DECLARE whether or not it contains any — the
    beam, plus every element the other wafer contributes
    (:func:`_pair_species_union`) — the mechanism already used for the
    beam, which the half also never contains at build.
    """
    crystal = load_crystal(_resolve_cif(wafer.cif_source))
    crystal = rescale_crystal_to_cell(
        crystal, derived_lattices.cell_for(wafer.identity))
    return build_standalone_half(
        crystal, wafer.surface_face, wafer.identity,
        declared_species,
        min_slab_thickness=_effective_slab_thickness(pair),
        min_vacuum=to_metal(pair.numerical.slab_vacuum, "distance"),
        lateral_repeat=lateral_repeat,
        termination_index=wafer.termination_index,
        matched_cell=matched_cell, shared_cell=shared_cell)


def _write_half(half, wafer, scratch_directory, wafer_tag, comm):
    """Write a built half to its data file and return its handle (§7.1)."""
    role = "a" if wafer_tag == WAFER_A_TAG else "b"
    data_file = os.path.join(
        str(scratch_directory), f"half_{role}_{wafer.identity}.data")
    # Every rank cut an identical slab (the build is deterministic), so
    # only one of them may write it — see _publish_file.
    _publish_file(comm, lambda: write_standalone_half(half, data_file))
    return HalfHandle(
        data_file=data_file, type_map=half.type_map,
        identity=wafer.identity, wafer_tag=wafer_tag)


def build_halves(
        pair: PairSpecification,
        derived_lattices: DerivedLattices,
        scratch_directory: str,
        comm=None) -> tuple[HalfHandle, HalfHandle, SharedCell]:
    """Build both wafers as standalone half files (step 3, §4.3, §7.1).

    The real build stage: each wafer is cut ALONE in vacuum — on the
    model-derived lattice ``derive_lattices_live`` produced (§2.2), not the
    CIF's scale — and written to its own data file under the pair's
    scratch, returned as a :class:`HalfHandle` the activation stage loads
    on its own engine (the build->amorphize file handoff). Wafer A is the
    bottom half, B the top (the assembly invariant, DESIGN.md §2.6). This
    stays login-node work: the engine already ran upstream in the
    lattice-derivation step, so no engine is opened here — only geometry.

    The two surface lattices are MATCHED with the real Zur-McGill search
    (:func:`match_surfaces`, §2.3) and the result travels forward on the
    :class:`SharedCell`. For a same-material pair the match is the identity
    (zero strain), so the halves already share a lateral cell and are cut on
    their own lattice. A genuine mismatch resolves to a non-identity match,
    and each footprint half is then tiled by its whole-number matrix and
    strained onto the EVEN-split shared cell (§2.4) so the pair emerges
    commensurate — exactly what the assembly's commensurability assert
    demands (§2.6).
    """
    # Both halves declare the SAME types: the beam, plus every element
    # either wafer contributes (§4.3's one global type map). A half whose
    # own crystal lacks one of them still declares it, with no atoms of
    # that type — exactly how the beam is already carried.
    declared_species = frozenset(
        _projectile_species(pair)) | _pair_species_union(pair)
    # The coincidence match runs FIRST, on the PRIMITIVE surface cells
    # (lateral repeat 1), because the matcher's area budget
    # (max_coincidence_area) is for the primitive cell and — for a mismatch
    # — the footprint halves cannot be cut until the tiling is known.
    primitive_a = _standalone_half(
        pair.material.wafer_a, pair, derived_lattices, declared_species,
        lateral_repeat=1)
    primitive_b = _standalone_half(
        pair.material.wafer_b, pair, derived_lattices, declared_species,
        lateral_repeat=1)
    match = match_surfaces(
        primitive_a.atoms, primitive_b.atoms,
        max_area=to_metal(pair.numerical.max_coincidence_area, "area"),
        misfit_tolerance=pair.numerical.misfit_tolerance)
    # For a real mismatch, derive the shared cell and each wafer's tiling
    # so the footprint halves are cut strained onto ONE commensurate cell
    # (§2.4). Slab A is the matcher's 'film', slab B its 'substrate', so
    # each takes its own whole-number matrix. Identity needs neither.
    if match.is_identity:
        shared_cell = None
        matched_cell_a = matched_cell_b = None
        # Identity: no strain onto a shared cell, so one dose tile IS one
        # primitive surface cell — use its in-plane area as the base.
        base_cell = np.asarray(primitive_a.atoms.get_cell())[:2, :2]
    else:
        shared_cell = even_split_shared_cell(
            match.substrate_cell, match.film_cell)
        # Slab A is the matcher's 'film', slab B its 'substrate', so each
        # takes its OWN matched supercell vectors (the tiler derives the
        # supercell transform from these, §2.4).
        matched_cell_a = match.film_cell
        matched_cell_b = match.substrate_cell
        # Mismatch: both halves are first strained onto the shared cell, so
        # one dose tile IS the shared cell — its area is the footprint base.
        base_cell = np.asarray(shared_cell)[:, :2]
    # Size the dose-spreading footprint from the project's target area (§3.6),
    # retiring the hardcoded 10x10. BOTH halves take the SAME tiling so they
    # stay commensurate; the tiling is strain-neutral (identical copies), so
    # growing the footprint for statistics never touches the match strain.
    footprint_repeat = box_repeats(
        base_cell,
        to_metal(pair.numerical.target_footprint_area, "area"),
        to_metal(pair.numerical.minimum_cell_width, "distance"))
    # Now build BOTH footprint halves (the dose tiling), on the shared cell
    # for a mismatch; neither is written until both exist.
    half_a = _standalone_half(
        pair.material.wafer_a, pair, derived_lattices, declared_species,
        lateral_repeat=footprint_repeat,
        matched_cell=matched_cell_a, shared_cell=shared_cell)
    half_b = _standalone_half(
        pair.material.wafer_b, pair, derived_lattices, declared_species,
        lateral_repeat=footprint_repeat,
        matched_cell=matched_cell_b, shared_cell=shared_cell)
    handle_a = _write_half(
        half_a, pair.material.wafer_a, scratch_directory, WAFER_A_TAG,
        comm)
    handle_b = _write_half(
        half_b, pair.material.wafer_b, scratch_directory, WAFER_B_TAG,
        comm)
    # Record the §2.5 thickness margin actually achieved: how much undamaged
    # crystal sits beneath the estimated skin, above the required cushion.
    thickness = _effective_slab_thickness(pair)
    required = (
        to_metal(pair.protocol.required_activated_depth, "distance")
        + to_metal(pair.numerical.minimum_bulk_thickness, "distance"))
    shared = SharedCell(
        note=(f"{half_a.identity}/{half_b.identity} coincidence match "
              f"(strain {match.residual_strain:.4f}, "
              f"{'identity' if match.is_identity else 'mismatch'}); "
              f"slab {thickness:.1f} A, §2.5 bulk margin "
              f"{thickness - required:.1f} A"),
        residual_strain=match.residual_strain,
        match_area=match.match_area,
        is_identity=match.is_identity)
    return handle_a, handle_b, shared


# ---------------------------------------------------------------------
# Step 4 — the activation stage (COMPUTE NODE). For each half: re-read the
# pristine half, run the cascade out-of-process under the universal MLIP,
# and write the amorphized half back (cascade-only, §3.4).
# ---------------------------------------------------------------------

def _stage_trajectory(
        output_directory: str,
        pair: PairSpecification,
        stage: str) -> tuple:
    """Where this stage records frames, and how densely — or nowhere.

    Returns ``(path, stride)`` when this invocation asked for visual
    output, and ``(None, stride)`` otherwise, so a caller can pass both
    straight through to a driver that treats ``None`` as "do not record".
    Centralised here so every dynamic stage names its file the same way
    and honours the one switch (:mod:`sabsim.pipeline.run_options`).
    """
    options = trajectory_options()
    stride = options.stride_or(pair.numerical.frame_stride)
    if not options.enabled:
        return None, stride
    return stage_dump_file(output_directory, pair.pair_label, stage), stride


class _PullRungPaths(NamedTuple):
    """The self-contained paths for one pull rung (`DESIGN.md` §11.3)."""

    directory: str
    checkpoint_directory: str
    log_file: str
    trajectory_file: str | None
    trajectory_stride: int


def _pull_rung_paths(
        scratch_directory: str,
        pair: PairSpecification,
        rate) -> _PullRungPaths:
    """Lay out one pull rung's OWN directory and return its paths (§11.3).

    Each rate is a separate pull, so it gets its own ``pull_<rate>/``
    directory holding its log, its (optional) trajectory, and its resume
    ``checkpoints/`` subdir — so resuming one rung never reaches into
    another's state (`DESIGN.md` §11.3, `PSEUDOCODE.md` §13.3). The
    directory is created here so the engine's log can be written into it;
    the ``checkpoints/`` subdir is created lazily by the first checkpoint
    write, so a rung that never checkpoints leaves none behind.
    """
    directory = os.path.join(
        scratch_directory, f"pull_{_rate_slug(rate)}")
    os.makedirs(directory, exist_ok=True)
    trajectory_file, stride = _stage_trajectory(directory, pair, "pull")
    return _PullRungPaths(
        directory=directory,
        checkpoint_directory=os.path.join(directory, "checkpoints"),
        log_file=os.path.join(directory, "log.pull"),
        trajectory_file=trajectory_file,
        trajectory_stride=stride)


def _pull_note(result) -> str:
    """The human-facing one-line verdict for a pull rung (§9.6, §13.6).

    States whether the rung separated, lost atoms, or ran out of budget,
    and — for a resumed rung — that the number was produced across a
    continuation (and whether the trust guard was overridden), so the
    report stays honest about how it was made (`VISION.md` goal 3). A
    resumed pull is the SAME measurement; the marker is provenance, not a
    downgrade (§11.5).
    """
    if result.complete:
        note = "separated"
    elif not result.atoms_conserved:
        note = "LOST ATOMS — result void (§9.6)"
    else:
        note = "did not fully separate within the pull budget"
    if result.resumed:
        note += (" [resumed; trust override]" if result.override_used
                 else " [resumed]")
    return note


def _wafer_of(pair: PairSpecification, handle: HalfHandle):
    """The wafer a half handle stands for, by its A/B tag (§2.6)."""
    if str(handle.wafer_tag).upper().endswith("B"):
        return pair.material.wafer_b
    return pair.material.wafer_a


def activate_one_half(
        handle: HalfHandle,
        pair: PairSpecification,
        seed: int,
        output_directory: str,
        comm=None,
        library=None) -> tuple:
    """Cascade, heal and GATE one half, out-of-process (§10.1, §3.4).

    ``library`` is THIS wafer's environment library (each surface has
    its own, in its ``prep_surfN_<label>/`` folder of the project —
    DESIGN §1.2/§3.5); when a caller passes none it is loaded here for
    the wafer the handle's tag names, so a single-half invocation still
    works.

    The cascade runs on the universal foundation MLIP, which lives in
    deepmd's own self-contained bundle and cannot load into this process
    (ARCHITECTURE §4.1/§4.4). So the whole activate session — the
    cascade and, since 2026-08-28, the heal that follows it on the same
    engine — is assembled by
    :func:`~sabsim.driver.cascade.build_activate_script` and run as the
    bundle's ``lmp -in <script>`` in ONE subprocess; the HEALED structure
    is read back from a dump file (the §4.3 file handoff), and the §3.5
    gate judges it here, in this process. Returns ``(CascadeOutcome,
    amorphized_file, verdict, heal_start_step)``: the healed half on
    disk, its gate verdict, and the step its heal began at.
    """
    built = read_standalone_half(
        handle.data_file, handle.type_map, handle.identity)
    if library is None:
        library, _warnings = load_environment_library(
            pair, _wafer_of(pair, handle))
    # The universal cascade force model (deepmd + ZBL); it refuses unless the
    # run opted into the not-yet-gate-cleared model (§4.7).
    cascade_force_model = resolve_cascade_generator(
        built.type_map, _projectile_species(pair),
        weights_path=pair.potential.universal_weights,
        allow_unvalidated=pair.potential.allow_unvalidated,
        model_name=pair.potential.universal_model)

    spec = derive_bombardment_spec(built, pair)
    projectile_types = [
        built.type_map[species]
        for species in _projectile_species(pair)
        if species in built.type_map]

    role = "a" if handle.wafer_tag == WAFER_A_TAG else "b"
    dump_path = os.path.join(output_directory, f"activated_{role}.dump")
    marker_path = os.path.join(
        output_directory, f"activated_{role}.heal_step")
    # Honour the invocation's trajectory switch (run_options): with frames
    # on, the out-of-process cascade records the WHOLE bombardment as a
    # movie, the same as the in-process press and pull stages.
    trajectory_file, trajectory_stride = _stage_trajectory(
        output_directory, pair, f"activate_{role}")
    script = build_activate_script(
        built, pair, cascade_force_model, handle.data_file, spec,
        seed, projectile_types, dump_path, marker_path, _GEOMETRY,
        _CONTROL, trajectory_file=trajectory_file,
        trajectory_stride=trajectory_stride)

    # Only the primary rank drives the one-GPU subprocess and writes the
    # shared files; peers wait at the barrier, then every rank reads the
    # handoff back (deterministic, so the gate agrees across ranks).
    rank = comm.Get_rank() if comm is not None else 0
    if rank == 0:
        run_activate_subprocess(
            script, output_directory, dump_path,
            script_name=f"activate_{role}.in",
            log_name=f"log.activation_{role}")
    if comm is not None:
        comm.Barrier()

    positions, type_ids = read_dump_structure(dump_path)
    cell = built.atoms.get_cell()
    heal_start_step = _read_heal_marker(marker_path)
    cascade_outcome = CascadeOutcome(
        impacts_run=spec.impact_count,
        note=f"delivered {spec.impact_count} impacts of "
             f"{spec.projectile_symbol} at "
             f"{spec.impact_energy:.0f} eV, then healed, out-of-process "
             f"(§10.4, §10.5, §4.3)")
    # The §3.5 gate, on the HEALED half (§3.4, revised 2026-08-28). The
    # dump is substrate-only (the projectile was stripped before the
    # heal) with its free surface on top, exactly as the gate's metrics
    # assume; the reference is keyed by THIS wafer's declared species,
    # and "crystalline" is judged against the surface's environment
    # library (revised 2026-08-29): the descriptor engine runs its own
    # out-of-process bundle call on rank 0 and every rank reads back.
    species = frozenset(handle.type_map) - _projectile_species(pair)
    symbol_of_type = {type_id: symbol
                      for symbol, type_id in handle.type_map.items()}
    symbols = [symbol_of_type[int(type_id)] for type_id in type_ids]
    gate_directory = os.path.join(output_directory, f"gate_{role}")
    if rank == 0:
        os.makedirs(gate_directory, exist_ok=True)
    if comm is not None:
        comm.Barrier()
    verdict = activation_gate(
        positions, np.asarray(cell, dtype=float), symbols,
        load_activation_references(species),
        to_metal(pair.protocol.required_activated_depth, "distance"),
        library, pair.numerical.disorder_scatter_multiple,
        to_metal(pair.numerical.depth_bin_width, "distance"),
        work_directory=gate_directory,
        descriptor_vectors=_describe_on_one_rank(
            positions, cell, symbols, library, gate_directory, comm))
    amorphized_atoms = amorphized_half_from_arrays(
        positions, type_ids, cell, handle.type_map, handle.wafer_tag)
    amorphized_file = os.path.join(
        output_directory, f"amorphized_{role}.extxyz")
    if rank == 0:
        ase_write(amorphized_file, amorphized_atoms,
                  format="extxyz", parallel=False)
    if comm is not None:
        comm.Barrier()
    return cascade_outcome, amorphized_file, verdict, heal_start_step


def _describe_on_one_rank(
        positions, cell, symbols, library, gate_directory, comm):
    """Run the descriptor engine on rank 0 and share its vectors.

    The engine is one out-of-process bundle ``lmp`` call, like the
    cascade: one rank drives it and the others receive the result by
    broadcast, so every rank judges the identical verdict (§4.1).
    """
    from sabsim.driver.descriptors import describe_structure
    rank = comm.Get_rank() if comm is not None else 0
    vectors = None
    if rank == 0:
        vectors = describe_structure(
            positions, np.asarray(cell, dtype=float), symbols,
            library.settings, gate_directory, "gate")
    if comm is not None:
        vectors = comm.bcast(vectors, root=0)
    return vectors


def _read_heal_marker(marker_path: str) -> int | None:
    """The step the heal began at, from the one-line marker the session
    wrote (``heal_surface_commands``); None if the file is absent."""
    try:
        with open(marker_path, encoding="utf-8") as marker:
            return int(float(marker.read().split()[0]))
    except (OSError, IndexError, ValueError):
        return None


def activate_one_surface_live(
        handle: HalfHandle,
        shared: SharedCell,
        pair: PairSpecification,
        scratch_directory: str,
        comm=None) -> ActivatedHalf:
    """Activate, heal and gate ONE surface — a prep job's stage (§10.1).

    Revised 2026-08-30 (Paul): each surface is prepared by its own prep
    job in its own folder, so the live activation stage works one half
    at a time. The half's seed is derived from the pair's one master
    seed by its wafer tag (surface 1 takes the first of the two seeds,
    surface 2 the second), so the two surfaces of a same-material pair
    are DIFFERENT realizations, and either prep job reproduces its half
    alone. The surface's environment library is loaded from its prep
    folder and checked before any cascade; a temperature warning, if
    any, is said out loud. Returns the :class:`ActivatedHalf` the prep
    job hands bond, carrying the shared cell the half was cut on.
    """
    wafer = _wafer_of(pair, handle)
    half_seeds = derive_seeds(pair.ensemble.master_seed, 2)
    seed = half_seeds[0 if handle.wafer_tag == WAFER_A_TAG else 1]
    library, warnings = load_environment_library(pair, wafer)
    rank = comm.Get_rank() if comm is not None else 0
    if rank == 0:
        for warning in warnings:
            print(f"sabsim: WARNING — {warning}", flush=True)
    _outcome, amorphized_file, verdict, heal_step = activate_one_half(
        handle, pair, seed, scratch_directory, comm, library)
    role = "A (bottom)" if handle.wafer_tag == WAFER_A_TAG else "B (top)"
    species = frozenset(handle.type_map) - _projectile_species(pair)
    slab = Slab(
        identity=handle.identity, note=f"healed activated half {role}",
        data_file=amorphized_file, species=species,
        heal_start_step=heal_step)
    return ActivatedHalf(
        slab=slab, verdict=verdict, wafer_tag=handle.wafer_tag,
        shared=shared)


def activate_surfaces_live(
        handle_a: HalfHandle,
        handle_b: HalfHandle,
        pair: PairSpecification,
        scratch_directory: str,
        comm=None):
    """Amorphize BOTH halves independently (step 4, §10.1).

    The whole-chain convenience: both halves in ONE process, one after
    the other, each from the same per-half seed the per-surface stage
    (:func:`activate_one_surface_live`) would use — so a chain run and
    two separate prep jobs produce the identical surfaces. Each yields a
    HEALED slab and its §3.5 verdict (revised 2026-08-28); the
    healed-half file paths ride on the returned slabs' ``data_file`` for
    the assembly to read, and the
    verdicts ride the ``ActivatedSlabs`` so the contract halts a failed
    activation before anything is assembled.
    """
    half_seeds = derive_seeds(pair.ensemble.master_seed, 2)
    # The environment libraries the §3.5 gate judges against — ONE PER
    # WAFER, each from its own prep folder of the project
    # (DESIGN §1.2/§3.5, revised 2026-08-29) — loaded and checked before
    # any cascade; a temperature warning, if any, is said out loud.
    library_a, warnings_a = load_environment_library(
        pair, pair.material.wafer_a)
    library_b, warnings_b = load_environment_library(
        pair, pair.material.wafer_b)
    rank = comm.Get_rank() if comm is not None else 0
    if rank == 0:
        for warning in warnings_a + warnings_b:
            print(f"sabsim: WARNING — {warning}", flush=True)
    _outcome_a, amorphized_a, verdict_a, heal_a = activate_one_half(
        handle_a, pair, half_seeds[0], scratch_directory, comm, library_a)
    _outcome_b, amorphized_b, verdict_b, heal_b = activate_one_half(
        handle_b, pair, half_seeds[1], scratch_directory, comm, library_b)

    # Each wafer's DECLARED material species: the half's pre-cascade type
    # map minus the projectile beam. This is what the §3.5 gate keys the
    # wafer's activation reference by (DESIGN.md §3.5), so it is recorded
    # here from the declared map rather than inferred from the survivors.
    projectile = _projectile_species(pair)
    species_a = frozenset(handle_a.type_map) - projectile
    species_b = frozenset(handle_b.type_map) - projectile
    slab_a = Slab(
        identity=handle_a.identity, note="healed activated half A (bottom)",
        data_file=amorphized_a, species=species_a, heal_start_step=heal_a)
    slab_b = Slab(
        identity=handle_b.identity, note="healed activated half B (top)",
        data_file=amorphized_b, species=species_b, heal_start_step=heal_b)
    return activated_slabs_from_results(slab_a, slab_b, verdict_a, verdict_b)


# ---------------------------------------------------------------------
# Step 5 — the assembly BARRIER stage. Reads both amorphized halves back
# and stacks them into a facing pair (DESIGN.md §2.6).
# ---------------------------------------------------------------------

def assemble_pair_live(
        activated,
        shared: SharedCell,
        pair: PairSpecification,
        scratch_directory: str,
        comm=None) -> Structure:
    """Assemble the two amorphized halves into a facing pair (step 5, §2.6).

    The BARRIER stage: it reads BOTH amorphized halves back from the files
    the activation stage wrote (the wafer tag rides along in the XYZ), flips
    the top half so its activated face meets the interface, removes ejecta,
    places the halves surface-to-surface at the protocol's press-start
    opening (``initial_gap``, §2.6 revised 2026-08-28), and relieves
    any clash — all in :func:`sabsim.structure.amorphized_assembly.
    assemble_amorphized_pair`. The assembled pair is written to a LAMMPS
    data file the press will load, and the per-wafer z-ranges + interface
    plane travel forward as the Structure's labeled-group geometry
    (option C, DESIGN.md §2.6).

    RUNS ON ONE RANK, AND THAT IS NOT AN OPTIMISATION. Unlike the stages
    on either side of it, this one is pure geometry: no LAMMPS, nothing
    domain-decomposed, so every rank would compute the IDENTICAL answer.
    That is merely wasteful in time — but it is fatal in memory, because
    the clash check compares every A atom with every B atom and so holds
    matrices of N_A x N_B doubles (~1 GB for two 4400-atom halves). One
    copy is fine; thirty-two copies of it on one node is 32 GB, and the
    first full run was OUT-OF-MEMORY killed here. So rank 0 does the work
    and broadcasts the result, which doubles as the synchronisation that
    publishes the written file to every rank.
    """
    rank = comm.Get_rank() if comm is not None else 0
    structure = (
        _assemble_on_one_rank(activated, shared, pair, scratch_directory)
        if rank == 0 else None)
    if comm is not None:
        structure = comm.bcast(structure, root=0)
    return structure


def _assemble_on_one_rank(
        activated,
        shared: SharedCell,
        pair: PairSpecification,
        scratch_directory: str) -> Structure:
    """The assembly itself, executed by a single rank (see above)."""
    # parallel=False on both: this rank reads the halves itself rather
    # than letting ASE broadcast them, which would collide with SABSIM's
    # own message passing (slab_builder's ASE imports note) — and here
    # the peers are not even in this function to take part.
    half_a = ase_read(
        activated.slab_a.data_file, format="extxyz", parallel=False)
    half_b = ase_read(
        activated.slab_b.data_file, format="extxyz", parallel=False)

    # The real coincidence match rides forward on the SharedCell (§2.3),
    # rebuilt here as the SurfaceMatch the assembler reads — no longer
    # fabricated from one half's cell.
    match = SurfaceMatch(
        residual_strain=shared.residual_strain,
        match_area=shared.match_area,
        is_identity=shared.is_identity)

    built = assemble_amorphized_pair(
        half_a, half_b, match,
        bond_cutoff=_BOND_CUTOFF,
        initial_gap=to_metal(pair.protocol.initial_gap, "distance"),
        clash_floor=to_metal(pair.numerical.clash_floor, "distance"),
        wafer_a_species=activated.slab_a.species,
        wafer_b_species=activated.slab_b.species)

    pair_file = os.path.join(scratch_directory, "assembled_pair.data")
    # Already on the single assembling rank, so this is a plain write;
    # the caller's broadcast is what publishes it to the other ranks.
    write_lammps_data(built, pair_file)
    return Structure(
        note=(f"assembled amorphized pair "
              f"{activated.slab_a.identity}/{activated.slab_b.identity}; "
              f"gap adjust {built.initial_gap_adjustment:.2f} Å"),
        labeled_groups=(
            "wafer_a_z_range", "wafer_b_z_range", "interface_z",
            "activated_skin"),
        data_file=pair_file,
        built=built,
        activation_a=activated.verdict_a,
        activation_b=activated.verdict_b,
        heal_start_step_a=activated.slab_a.heal_start_step,
        heal_start_step_b=activated.slab_b.heal_start_step)


# ---------------------------------------------------------------------
# Steps 6-7 — the press/pull bond-debond stage (COMPUTE NODE). Sequences
# the driver's three phases (press -> settle -> pull ladder) into one
# BondDebondResult, a fresh engine per pull rung (PSEUDOCODE.md §9.1).
# ---------------------------------------------------------------------

def _bonded_force_model(potential, type_map: dict) -> ForceModel:
    """The potential the bonded pair heals, presses and pulls under (§4.5).

    ``potential`` is the project's ``[potential]`` block; the pair runs under
    its ``production_weights`` — today a single frozen DeePMD file (a
    committee of one), later the ALF-trained committee the pair's
    ``potential_ref`` resolves to — behind the ``pair_style`` seam. The
    file's existence was checked at load time (phase three), so a missing
    model stops on the login node, never here. ``type_map`` is the
    assembled pair's, so the elements ride the ``pair_coeff`` line in type
    order (see :func:`~sabsim.driver.commands.deepmd_model`).
    """
    return deepmd_model(potential.production_weights, type_map)


def run_bond_debond_md_live(
        structure: Structure,
        pair: PairSpecification,
        scratch_directory: str,
        comm=None):
    """Press the pair, settle a reference, pull it apart per rate (§9.1).

    Sequences the three driver phases (:mod:`sabsim.driver.press_pull`) into
    one :class:`~sabsim.pipeline.exec_artifacts.BondDebondResult`. The press
    and the settle share ONE engine (the settle re-reads no file); each pull
    rung then opens its OWN fresh engine reading the settled reference the
    settle wrote (a per-rung restore, §9.6). The assembled pair's live
    builder object (``structure.built``) supplies the per-wafer geometry the
    driver carves zones from. If the press never reaches contact, the ladder
    is reported as un-pulled (a first-class "did not bond" outcome, §5.2),
    never faked. Compute-node work: the ``LammpsEngine`` import is lazy.
    """
    from sabsim.driver.lammps_engine import LammpsEngine
    from sabsim.driver.press_pull import (
        press_and_bond,
        pull_at_rate,
        settle_reference,
    )
    from sabsim.pipeline.exec_artifacts import (
        BondDebondResult,
        PressOutcome,
        PullOutcome,
        StageLedger,
    )

    built = structure.built
    force_model = _bonded_force_model(pair.potential, built.type_map)
    seed = pair.ensemble.master_seed
    reference_file = os.path.join(scratch_directory, "settled_reference.data")

    # Press + settle on one shared engine.
    press_engine = LammpsEngine(
        command_line_args=[
            "-screen", "none",
            "-log", os.path.join(scratch_directory, "log.press")],
        comm=comm)
    # The press dump stays open through the settle on this same engine,
    # so the two record as one movie of contact and relaxation.
    press_trajectory, press_stride = _stage_trajectory(
        scratch_directory, pair, "press")
    press = press_and_bond(
        press_engine, built, pair, force_model, structure.data_file, seed,
        trajectory_file=press_trajectory,
        trajectory_stride=press_stride)
    # The §5.6 conservation baseline is the ASSEMBLED pair, checked at every
    # stage boundary from here on — a pair that lost atoms in the press is
    # VOID, not "bonded" (the T-18 blind spot: the old baseline was taken
    # at pull start, after the press had already ejected 93 % of the atoms).
    assembled_atom_count = len(built.atoms.get_tags())
    reference = None
    if press.contact_reached and press.atoms_conserved:
        reference = settle_reference(
            press_engine, pair, reference_data_file=reference_file,
            expected_atom_count=assembled_atom_count)
    press_engine.close()

    # The stage ledger (§9.3, DESIGN §5.5): where each phase fell in the
    # step count, written into the manifest beside the outcome.
    stage_steps = StageLedger(
        press_start=press.press_start_step,
        contact=press.contact_step,
        hold_end=press.hold_end_step,
        settle_start=(reference.settle_start_step
                      if reference is not None else None),
        settle_end=(reference.settle_end_step
                    if reference is not None else None))

    ladder = pair.numerical.pull_rate_ladder
    void = (not press.atoms_conserved
            or (reference is not None and not reference.atoms_conserved))
    if void or not press.contact_reached or reference is None:
        why = ("LOST ATOMS before the pull — result VOID (§5.6)" if void
               else "no contact under the press — not pulled (§5.2)")
        note = press.note
        if reference is not None and not reference.atoms_conserved:
            note = f"{press.note}; settle LOST ATOMS — VOID (§5.6)"
        pulls = tuple(
            PullOutcome(
                rate_value=rate.value, rate_unit=rate.unit, note=why)
            for rate in ladder)
        return BondDebondResult(
            press=PressOutcome(bonded=False, note=note,
                               stage_steps=stage_steps),
            reference_ok=False, pulls=pulls)

    # One fresh engine per pull rung, each in its OWN directory so it can
    # be resumed from its own checkpoints without touching another rung
    # (§11.3). Passing checkpoint_dir turns resume ON: the rung writes a
    # checkpoint pair on the cadence and, if one is already present,
    # continues from it rather than starting over (§13.3).
    pulls = []
    for rate in ladder:
        rung = _pull_rung_paths(scratch_directory, pair, rate)
        pull_engine = LammpsEngine(
            command_line_args=["-screen", "none", "-log", rung.log_file],
            comm=comm)
        result = pull_at_rate(
            pull_engine, built, pair, force_model, reference_file, rate,
            seed, output_directory=rung.directory,
            trajectory_file=rung.trajectory_file,
            trajectory_stride=rung.trajectory_stride,
            checkpoint_dir=rung.checkpoint_directory,
            expected_atom_count=assembled_atom_count)
        pull_engine.close()
        pulls.append(PullOutcome(
            rate_value=rate.value, rate_unit=rate.unit,
            note=_pull_note(result),
            complete=result.complete,
            separation_index=result.separation_index,
            grip_displacement=tuple(result.grip_displacement),
            force_vs_grip=tuple(result.force_vs_grip),
            atoms_conserved=result.atoms_conserved,
            bridges_at_separation=result.bridges_at_separation,
            resumed=result.resumed,
            override_used=result.override_used))

    return BondDebondResult(
        press=PressOutcome(
            bonded=True, note="contact reached and held (§9.3)",
            stage_steps=stage_steps),
        reference_ok=reference.settled,
        pulls=tuple(pulls))


# ---------------------------------------------------------------------
# The bond-outcome analyzer (DESIGN.md §6, §8). Turns the reduced pull
# curves into the measure vector — the mechanical work of separation (M1)
# is the one measure real here; the higher-fidelity ones stay unresolved.
# ---------------------------------------------------------------------

def run_analyzer_live(
        structure: Structure,
        bond_debond,
        pair: PairSpecification):
    """Reduce the bond-debond result to a measure vector (§6, §8.4).

    Computes the mechanical work of separation (M1) — the area under each
    pull's resisting-force curve up to complete separation, per unit
    interface area (:func:`sabsim.driver.analysis.work_of_separation`). The
    SLOWEST rate that fully separated is reported as the headline value (it
    is the closest to the quasi-static work, §5.4); if no rung separated the
    measure is honestly UNRESOLVED. The higher-fidelity (MLIP / all-electron)
    measures stay unresolved here — they are the wave-2 / wave-4 work. The
    press bond decision rides the vector's verdicts (§4).
    """
    from sabsim.driver.analysis import work_of_separation
    from sabsim.pipeline.measures import (
        Measure,
        MeasureStatus,
        MeasureVector,
        Verdicts,
    )

    cell = np.asarray(structure.built.atoms.get_cell())
    interface_area = float(np.linalg.norm(np.cross(cell[0], cell[1])))
    seeds = pair.ensemble.amorphization_count

    # Slowest-rate rung that fully separated (rungs are in ladder order;
    # the smallest rate is the most quasi-static, §5.4).
    works = []
    for pull in bond_debond.pulls:
        # A pull that lost atoms is VOID, not merely incomplete: the box
        # deleted material midway, so the force curve describes a system
        # that no longer exists. It is refused before it can be
        # integrated (§9.6) rather than quietly averaged in.
        if (pull.complete and pull.separation_index is not None
                and pull.atoms_conserved):
            work = work_of_separation(
                pull.grip_displacement, pull.force_vs_grip,
                pull.separation_index, interface_area)
            if work is not None:
                works.append((pull.rate_value, work))
    works.sort(key=lambda rate_work: rate_work[0])   # ascending rate

    if works:
        value = works[0][1]                          # slowest rung
        status = MeasureStatus.OK
        method = "MD work integral, slowest separated rung (§8.4)"
    else:
        value = None
        status = MeasureStatus.UNRESOLVED
        method = "no pull rung fully separated (§9.6)"

    mechanical = Measure(
        name="mechanical_work_of_separation",
        value=value, uncertainty=0.0, realization_count=seeds,
        unit_native="eV/angstrom^2", unit_si="J/m^2",
        fidelity="deepmd-committee-of-one", method=method, status=status)
    thermodynamic = Measure(
        name="work_of_adhesion_mlip",
        value=None, uncertainty=None, realization_count=seeds,
        unit_native="eV/angstrom^2", unit_si="J/m^2",
        fidelity="mlip", method="not computed in v1 (wave 2)",
        status=MeasureStatus.UNRESOLVED)

    # Surface the §3.5 activation gate result for each HEALED surface. The
    # verdicts ride the assembled pair (§10.1, revised 2026-08-28: the gate
    # runs in the activation stage and the pair carries what it was built
    # from). Only a PASS reaches here — a failed gate halted the pair
    # before assembly — so this reports the MEASURED skin depth (closing
    # the §2.5 estimate) with the gate's own summary as the method. Absent
    # on a skeleton stub, in which case nothing is emitted.
    activation_measures = []
    for surface, verdict in (("a", structure.activation_a),
                             ("b", structure.activation_b)):
        if verdict is None:
            continue
        report = verdict_from_activation(verdict)
        activation_measures.append(Measure(
            name=f"activated_depth_{surface}",
            value=verdict.activated_depth, uncertainty=0.0,
            realization_count=seeds,
            unit_native="angstrom", unit_si="m",
            fidelity="structural-metric (§3.5)",
            method=report.reason,
            status=(MeasureStatus.OK if verdict.passed
                    else MeasureStatus.UNRESOLVED)))

    return MeasureVector(
        measures=(mechanical, thermodynamic, *activation_measures),
        verdicts=Verdicts(
            bonded=bond_debond.press.bonded, contact_quality=None))


# ---------------------------------------------------------------------
# The live stage set (ARCHITECTURE.md §5.1). The real bodies for the steps
# that have them, reusing ONE W0 stub where no live body exists yet: step-8
# characterization is still mocked (run_characterization) — a placeholder
# a reader should know is one. The sequencer runs this set on a compute
# node; W0_STAGES on the login node.
# ---------------------------------------------------------------------

from sabsim.pipeline.skeleton_stages import (        # noqa: E402
    StageSet,
    run_characterization,
)


LIVE_STAGES = StageSet(
    derive_lattices=derive_lattices_live,
    build=build_halves,
    activate_surface=activate_one_surface_live,
    assemble=assemble_pair_live,
    bond_debond=run_bond_debond_md_live,
    analyze=run_analyzer_live,
    characterize=run_characterization)
