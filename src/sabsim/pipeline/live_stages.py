"""The REAL pipeline stage bodies (ARCHITECTURE.md §4.3, §5.1).

These are the physics-bearing counterparts of the walking-skeleton stubs
in :mod:`sabsim.pipeline.skeleton_stages`: they build real slabs, open a
real ``LammpsEngine`` per half, and produce real amorphized structures.
They speak the SAME contracts the stubs do, so the sequencer runs either
set behind the same seams (the stub set on the login node for control-flow
tests, this set on a compute node for a real run).

The build->amorphize->assemble chain here is exactly ARCHITECTURE.md §4.3:

* :func:`build_halves` (step 3) cuts each wafer ALONE, writes it to a
  LAMMPS data file under the member's scratch, and returns a
  :class:`~sabsim.pipeline.exec_artifacts.HalfHandle` per half — the
  build->amorphize file handoff. Login-node work (no LAMMPS).
* the activation stage (step 4) opens a ``LammpsEngine`` per half, re-reads
  the pristine half from its handle, runs the cascade -> re-anneal -> gate
  driver, and writes the amorphized half back. Compute-node work.
* the assembly stage (step 5) reads both amorphized halves back and stacks
  them into a facing pair (:mod:`sabsim.structure.amorphized_assembly`).

The module imports cleanly with NO LAMMPS present — ``LammpsEngine``
imports the binding lazily inside its constructor — so the login node can
build halves and review the whole chain; only the activation stage's
``LammpsEngine(...)`` call needs a compute node.

SIZING is a documented STAND-IN. How big a slab and how much vacuum a half
needs is the open slab-size <-> bombardment-energy <-> DFT-cost three-way
accommodation (DESIGN.md §3.6, and the TODO follow-on): the constants below
make a workable Si cell for the smoke integration, they are NOT pinned
physical v1 values. Only ``minimum_bulk_thickness`` is read from the spec
today; the rest are pinned together once the DFT budget is known.
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
    _projectile_species,
    activate_surface,
    derive_seeds,
)
from sabsim.driver.cascade_potential import classical_force_model
from sabsim.driver.commands import (
    CascadeGeometry,
    ForceModel,
    _rate_slug,
    deepmd_model,
    stage_dump_file,
    to_metal,
)
from sabsim.pipeline.activation_adapter import activated_slabs_from_results
from sabsim.pipeline.exec_artifacts import (
    HalfHandle,
    SharedCell,
    Slab,
    Structure,
)
from sabsim.pipeline.run_options import trajectory_options
from sabsim.spec.references import resolve_crystal_file
from sabsim.spec.records import MemberSpecification
from sabsim.structure.amorphized_assembly import (
    assemble_amorphized_pair,
    snapshot_amorphized_half,
)
from sabsim.structure.slab_builder import (
    WAFER_A_TAG,
    WAFER_B_TAG,
    SurfaceMatch,
    build_standalone_half,
    load_crystal,
    read_standalone_half,
    write_lammps_data,
    write_standalone_half,
)

# Cascade engineering knobs and the bond cutoff, all documented STAND-INS.
_GEOMETRY = CascadeGeometry()           # 4 Å base + 6 Å border + 10 Å spawn
_CONTROL = CascadeControl(cascade_step_cap=20000)   # halt backstop
_BOND_CUTOFF = 2.8   # Å: Si first-g(r)-minimum stand-in (§6.3, TODO)

# Sizing PINNED from the 2026-07-21 energy x dose sweep (DESIGN.md §3.6),
# no longer smoke-test stand-ins. This is the cell that produced 20 clean
# activation points — zero sputtered atoms at every energy and dose tried
# — so it is the geometry the measured 7 Å depth threshold refers to, and
# changing any of the three invalidates that threshold.
#
# WIDTH is the one that bit us: a narrow cell concentrates a given AREAL
# dose onto few impacts, over-deepening the skin and making the result an
# artifact of the box rather than of the beam. Ten tiles (~38 Å) spreads
# the dose the way a broad beam does. THICKNESS must hold the frozen base
# and the thermostatted border AND still leave undamaged bulk beneath the
# skin (the §2.5 criterion, depth + bulk); 55 Å leaves ~45 Å of bulk under
# a 10 Å skin. VACUUM only has to clear the spawn height for the beam.
_MIN_SLAB_THICKNESS = 55.0     # Å: frozen base + border + undamaged bulk
_MIN_VACUUM = 30.0             # Å: room above the surface for the beam spawn
_LATERAL_REPEAT = 10           # tile n x n so one impact does not dominate


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


def _member_species_union(member: MemberSpecification) -> frozenset:
    """Every element either wafer contributes, read from the crystals.

    STRUCTURAL 1a puts ONE potential over the union of the pair's species,
    and DESIGN.md §4.3 makes that concrete as a single global type map
    shared by every member "so type index k means the same element
    everywhere". A half cut ALONE would otherwise declare only its own
    elements — a silicon half in a Si/SiO2 member would carry no oxygen
    type — and two consequences follow that this function exists to
    prevent. The force-model lookup is keyed on (species, domain)
    (§4.8), so a silicon-only half could not resolve the member's
    declared silicon-and-silica domain at all. And the assembly would
    have to reconcile two different type maps rather than one.

    The union is read from the CRYSTALS rather than parsed out of the
    material labels, because the CIF is the authoritative structure
    (§1.2) and a label like "SiO2" is a human name we have promised not
    to treat as a source of truth.
    """
    symbols = set()
    for wafer in (member.material.wafer_a, member.material.wafer_b):
        crystal = load_crystal(_resolve_cif(wafer.cif_source))
        # A pymatgen Structure, so the elements come off its composition
        # rather than an ASE-style symbol list. ``load_crystal`` already
        # stripped any oxidation states, so these are bare symbols;
        # ``.symbol`` is belt-and-braces and costs nothing.
        symbols.update(
            element.symbol for element in crystal.composition.elements)
    return frozenset(symbols)


def _build_one_half(
        wafer,
        member: MemberSpecification,
        scratch_directory: str,
        wafer_tag: int,
        declared_species: frozenset,
        comm=None) -> HalfHandle:
    """Cut ONE wafer alone, write its data file, return its handle (§7.1).

    Loads the wafer's crystal, builds a standalone half in vacuum with the
    beam species declared, writes it to a LAMMPS data file under the
    member's scratch, and hands back the :class:`HalfHandle` the
    amorphization stage re-reads it from. ``wafer_tag`` fixes the assembly
    role (bottom A / top B) that rides on the handle.

    ``declared_species`` are the elements this half must DECLARE whether
    or not it contains any — the beam, plus every element the other wafer
    contributes (:func:`_member_species_union`). Declaring a type with no
    atoms is the mechanism already used for the beam, which the half also
    never contains at build time.
    """
    crystal = load_crystal(_resolve_cif(wafer.cif_source))
    half = build_standalone_half(
        crystal, wafer.surface_face, wafer.identity,
        declared_species,
        min_slab_thickness=_MIN_SLAB_THICKNESS,
        min_vacuum=_MIN_VACUUM, lateral_repeat=_LATERAL_REPEAT)
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
        member: MemberSpecification,
        potential,
        scratch_directory: str,
        comm=None) -> tuple[HalfHandle, HalfHandle, SharedCell]:
    """Build both wafers as standalone half files (step 3, §4.3, §7.1).

    The real build stage: each wafer is cut ALONE in vacuum and written to
    its own data file under the member's scratch, returned as a
    :class:`HalfHandle` the activation stage loads on its own engine — the
    build->amorphize file handoff. Wafer A is the bottom half, B the top
    (the assembly invariant, DESIGN.md §2.6). This is login-node work: no
    engine is opened here.

    The shared cell is a STAND-IN: the wave-3 coincidence matcher (§7.6) is
    not built, so each half is cut on its own lattice. That is exact for
    the Si/Si identity case (the two halves already share a lateral cell);
    a genuine mismatch (Si/SiO2) would produce two halves the assembly's
    commensurability assert correctly REFUSES until the matcher lands.
    """
    # Both halves declare the SAME types: the beam, plus every element
    # either wafer contributes (§4.3's one global type map). A half whose
    # own crystal lacks one of them still declares it, with no atoms of
    # that type — exactly how the beam is already carried.
    declared_species = frozenset(
        _projectile_species(member)) | _member_species_union(member)
    handle_a = _build_one_half(
        member.material.wafer_a, member, scratch_directory, WAFER_A_TAG,
        declared_species, comm)
    handle_b = _build_one_half(
        member.material.wafer_b, member, scratch_directory, WAFER_B_TAG,
        declared_species, comm)
    shared = SharedCell(
        note="Si/Si identity shared cell (wave-3 matcher dormant, §7.6)")
    return handle_a, handle_b, shared


# ---------------------------------------------------------------------
# Step 4 — the engine-provider activation stage (COMPUTE NODE). Opens a
# LammpsEngine per half, re-reads the pristine half, runs the driver's
# cascade -> re-anneal -> gate, and writes the amorphized half back.
# ---------------------------------------------------------------------

# Bringing up a NEW material means running a potential that has not yet
# cleared the §3.5 activation gate — the run is what PRODUCES the evidence
# the gate would judge. The registry refuses such a form by default. This
# environment variable is the deliberate, per-run override: it lives
# outside the code so nobody is tempted to flip ``validated=True`` in the
# registry before the evidence exists, and because it must be set in the
# job script it stays visible in the run's own record. Anything produced
# under it is PROVISIONAL and must be reported that way.
_UNVALIDATED_POTENTIAL_VARIABLE = "SABSIM_ALLOW_UNVALIDATED_POTENTIAL"


def _unvalidated_potentials_allowed() -> bool:
    """Whether this run may use a not-yet-gate-cleared potential."""
    setting = os.environ.get(_UNVALIDATED_POTENTIAL_VARIABLE, "")
    return setting.strip().lower() in {"1", "true", "yes", "on"}


# An EXPLICIT deepmd-model override, for validating the trained-MLIP force
# path through the pipeline BEFORE the §11 bootstrap resolves a committee
# (the seam the classical stand-in normally fills, §4.5). When set to a
# frozen model file, the bonded pair presses and pulls under THAT DeePMD
# model instead of the classical registry entry. It is a validation hook,
# not the production path — the model it names has NOT cleared the §7
# potential-quality gate, so anything produced under it is provisional;
# like the unvalidated-potential flag above, it lives in the environment
# so a run that used it shows the override in its own record.
_DEEPMD_MODEL_OVERRIDE_VARIABLE = "SABSIM_DEEPMD_MODEL"


def _deepmd_model_override() -> str | None:
    """The frozen DeePMD model path this run was told to bond under, or None.

    Returns the model file named by ``SABSIM_DEEPMD_MODEL`` after checking
    it exists — a named-but-absent model is a loud stop, never a silent
    fall-through to the classical stand-in, because that would quietly run
    a different experiment than the one the override asked for.
    """
    model_path = os.environ.get(_DEEPMD_MODEL_OVERRIDE_VARIABLE, "").strip()
    if not model_path:
        return None
    if not os.path.isfile(model_path):
        raise FileNotFoundError(
            f"{_DEEPMD_MODEL_OVERRIDE_VARIABLE} names a DeePMD model that "
            f"does not exist: {model_path}")
    return model_path


def _stage_trajectory(
        output_directory: str,
        member: MemberSpecification,
        stage: str) -> tuple:
    """Where this stage records frames, and how densely — or nowhere.

    Returns ``(path, stride)`` when this invocation asked for visual
    output, and ``(None, stride)`` otherwise, so a caller can pass both
    straight through to a driver that treats ``None`` as "do not record".
    Centralised here so every dynamic stage names its file the same way
    and honours the one switch (:mod:`sabsim.pipeline.run_options`).
    """
    options = trajectory_options()
    stride = options.stride_or(member.numerical.frame_stride)
    if not options.enabled:
        return None, stride
    return stage_dump_file(output_directory, member.name, stage), stride


class _PullRungPaths(NamedTuple):
    """The self-contained paths for one pull rung (`DESIGN.md` §11.3)."""

    directory: str
    checkpoint_directory: str
    log_file: str
    trajectory_file: str | None
    trajectory_stride: int


def _pull_rung_paths(
        scratch_directory: str,
        member: MemberSpecification,
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
    trajectory_file, stride = _stage_trajectory(directory, member, "pull")
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


def _reanneal_force_model(
        type_map: dict,
        substrate: set,
        domain: str,
        allow_unvalidated: bool = False) -> ForceModel:
    """The gentle re-anneal potential, NULLing the deleted beam type.

    v1's 'MLIP' is a classical stand-in (DESIGN.md §4.5), resolved from
    the material's registry entry rather than hard-coded — silicon gets
    Stillinger-Weber, silicon+oxygen gets the Munetoh Tersoff, and a new
    material needs a registry row rather than a code change.

    After the cascade deletes the beam atoms the beam TYPE is still
    declared, so the classical form maps it to NULL and a no-op ``zero``
    pair style is overlaid to satisfy those dead type pairs. That
    bookkeeping now lives in
    :func:`~sabsim.driver.cascade_potential.classical_force_model`, which
    the press/pull stages share, so both describe a material identically.

    ``domain`` comes from the member specification (DESIGN.md §4.8) and
    selects among forms registered for the same species. It is passed
    rather than inferred because the cell cannot reveal it: a silica
    wafer and a silicon wafer facing a silica wafer present the same
    species set and want different forms.
    """
    return classical_force_model(
        type_map, substrate, allow_unvalidated=allow_unvalidated,
        domain=domain)


def activate_one_half(
        handle: HalfHandle,
        member: MemberSpecification,
        seed: int,
        output_directory: str,
        comm=None) -> tuple:
    """Amorphize ONE half on its own engine, write it back (§4.3, §10.1).

    Opens a ``LammpsEngine`` (compute node), RE-READS the pristine half
    from its handle's data file (never a warm object), runs the driver's
    cascade -> re-anneal -> §3.5 gate, then SNAPSHOTS the re-annealed
    surface out of the still-open engine and writes it back as the
    amorphized half (an extended-XYZ file, which round-trips the wafer tag
    the assembly reads). Returns the driver's rich
    :class:`~sabsim.driver.cascade.ActivationResult` and the amorphized
    file's path. The ``LammpsEngine`` import inside is lazy, so this module
    still loads with no LAMMPS present.
    """
    from sabsim.driver.lammps_engine import LammpsEngine

    built = read_standalone_half(
        handle.data_file, handle.type_map, handle.identity)
    substrate = frozenset(handle.type_map) - _projectile_species(member)
    mlip = _reanneal_force_model(
        handle.type_map, substrate, member.material_domain,
        allow_unvalidated=_unvalidated_potentials_allowed())

    role = "a" if handle.wafer_tag == WAFER_A_TAG else "b"
    log_file = os.path.join(output_directory, f"log.activation_{role}")
    engine = LammpsEngine(
        command_line_args=["-screen", "none", "-log", log_file], comm=comm)
    trajectory_file, stride = _stage_trajectory(
        output_directory, member, f"activation_{role}")
    result = activate_surface(
        engine, built, member, mlip, handle.data_file, seed,
        _GEOMETRY, _CONTROL,
        allow_unvalidated_potential=_unvalidated_potentials_allowed(),
        trajectory_file=trajectory_file, trajectory_stride=stride)
    # Snapshot BEFORE closing: the re-annealed state is still live here.
    amorphized_atoms = snapshot_amorphized_half(
        engine, handle.type_map, handle.wafer_tag)
    engine.close()

    # The snapshot above is COLLECTIVE — under multiple MPI ranks every
    # rank holds the full atom set — but only ONE rank may write the file,
    # or the ranks race on it. Rank 0 writes; the barrier makes the file
    # visible to every rank before any returns (so a caller that reads it
    # back on any rank finds it there).
    amorphized_file = os.path.join(
        output_directory, f"amorphized_{role}.extxyz")
    rank = comm.Get_rank() if comm is not None else 0
    if rank == 0:
        # parallel=False is REQUIRED here, not optional. Under MPI, ASE
        # turns a write into a collective in which process zero writes
        # and then broadcasts to its peers — but this call sits inside a
        # guard that only process zero enters, so that broadcast would
        # wait forever on peers that are sitting at the barrier just
        # below. See the note beside the ASE imports in
        # sabsim.structure.slab_builder for the whole story.
        ase_write(amorphized_file, amorphized_atoms,
                  format="extxyz", parallel=False)
    if comm is not None:
        comm.Barrier()
    return result, amorphized_file


def activate_surfaces_live(
        handle_a: HalfHandle,
        handle_b: HalfHandle,
        member: MemberSpecification,
        potential,
        scratch_directory: str,
        comm=None):
    """Amorphize BOTH halves independently, gate each (step 4, §10.1).

    Each half is activated on its OWN engine, SERIALLY (ARCHITECTURE.md
    §4.3 — serial slabs), from a reproducible per-half seed derived from
    the member's one master seed. The two rich verdicts are distilled to
    the contract :class:`~sabsim.pipeline.exec_artifacts.Verdict` through
    the adapter, and the amorphized-half file paths ride on the returned
    slabs' ``data_file`` for the assembly to read. A failed gate on either
    half makes the returned ``ActivatedSlabs`` contract-invalid, so the
    sequencer halts at this seam (§10.1).
    """
    half_seeds = derive_seeds(member.ensemble.master_seed, 2)
    result_a, amorphized_a = activate_one_half(
        handle_a, member, half_seeds[0], scratch_directory, comm)
    result_b, amorphized_b = activate_one_half(
        handle_b, member, half_seeds[1], scratch_directory, comm)

    slab_a = Slab(
        identity=handle_a.identity, note="amorphized half A (bottom)",
        data_file=amorphized_a)
    slab_b = Slab(
        identity=handle_b.identity, note="amorphized half B (top)",
        data_file=amorphized_b)
    return activated_slabs_from_results(slab_a, slab_b, result_a, result_b)


# ---------------------------------------------------------------------
# Step 5 — the assembly BARRIER stage. Reads both amorphized halves back
# and stacks them into a facing pair (DESIGN.md §2.6).
# ---------------------------------------------------------------------

def assemble_pair_live(
        activated,
        shared: SharedCell,
        member: MemberSpecification,
        scratch_directory: str,
        comm=None) -> Structure:
    """Assemble the two amorphized halves into a facing pair (step 5, §2.6).

    The BARRIER stage: it reads BOTH amorphized halves back from the files
    the activation stage wrote (the wafer tag rides along in the XYZ), flips
    the top half so its activated face meets the interface, removes ejecta,
    places the halves surface-to-surface at the protocol gap, and relieves
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
    structure = (_assemble_on_one_rank(activated, member, scratch_directory)
                 if rank == 0 else None)
    if comm is not None:
        structure = comm.bcast(structure, root=0)
    return structure


def _assemble_on_one_rank(
        activated,
        member: MemberSpecification,
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

    lateral_cell = np.asarray(half_a.get_cell())
    match_area = float(np.linalg.norm(
        np.cross(lateral_cell[0], lateral_cell[1])))
    identity_match = SurfaceMatch(
        residual_strain=0.0, match_area=match_area, is_identity=True)

    built = assemble_amorphized_pair(
        half_a, half_b, identity_match,
        bond_cutoff=_BOND_CUTOFF,
        initial_gap=to_metal(member.protocol.initial_gap, "distance"),
        clash_floor=to_metal(member.numerical.clash_floor, "distance"))

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
        built=built)


# ---------------------------------------------------------------------
# Steps 6-7 — the press/pull bond-debond stage (COMPUTE NODE). Sequences
# the driver's three phases (press -> settle -> pull ladder) into one
# BondDebondResult, a fresh engine per pull rung (PSEUDOCODE.md §9.1).
# ---------------------------------------------------------------------

def _bonded_force_model(
        type_map: dict,
        substrate,
        domain: str,
        allow_unvalidated: bool = False) -> ForceModel:
    """The potential the bonded pair presses and pulls under (§4.5).

    Resolved from the material's registry entry, the same way the
    re-anneal is, so the pair is pressed and pulled under exactly the
    potential its surfaces were annealed under.

    This previously mapped EVERY declared type to ``Si`` — harmless for
    the Si/Si null test, where that is the truth, but wrong for any other
    material: it would have described a silica wafer as though every
    oxygen were a silicon. Each type now carries its own element, and a
    projectile type still declared with no atoms left becomes ``NULL``.
    The trained MLIP drops in behind this same ``pair_style`` seam.

    ``domain`` is the member's declared regime (DESIGN.md §4.8), and
    passing the SAME one the re-anneal used is what makes the promise
    above literal — anneal and press resolve to one registry entry.

    The one exception is the EXPLICIT deepmd override
    (:func:`_deepmd_model_override`): when a run names a frozen DeePMD
    model, the pair presses and pulls under THAT model — the trained-MLIP
    force path this stand-in is a placeholder for — dropping in behind the
    very ``pair_style`` seam the docstring promises. This validates the
    deepmd path end-to-end (job 15686597 proved the engine alone); the
    §11 bootstrap replaces the override with a resolved committee later.
    """
    model_path = _deepmd_model_override()
    if model_path is not None:
        return deepmd_model(model_path)
    return classical_force_model(
        type_map, substrate, allow_unvalidated=allow_unvalidated,
        domain=domain)


def run_bond_debond_md_live(
        structure: Structure,
        potential,
        member: MemberSpecification,
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
    )

    built = structure.built
    force_model = _bonded_force_model(
        built.type_map,
        frozenset(built.type_map) - _projectile_species(member),
        member.material_domain,
        allow_unvalidated=_unvalidated_potentials_allowed())
    seed = member.ensemble.master_seed
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
        scratch_directory, member, "press")
    press = press_and_bond(
        press_engine, built, member, force_model, structure.data_file, seed,
        trajectory_file=press_trajectory,
        trajectory_stride=press_stride)
    reference = None
    if press.contact_reached:
        reference = settle_reference(
            press_engine, member, reference_data_file=reference_file)
    press_engine.close()

    ladder = member.numerical.pull_rate_ladder
    if not press.contact_reached or reference is None:
        pulls = tuple(
            PullOutcome(
                rate_value=rate.value, rate_unit=rate.unit,
                note="no contact under the press — not pulled (§5.2)")
            for rate in ladder)
        return BondDebondResult(
            press=PressOutcome(bonded=False, note=press.note),
            reference_ok=False, pulls=pulls)

    # One fresh engine per pull rung, each in its OWN directory so it can
    # be resumed from its own checkpoints without touching another rung
    # (§11.3). Passing checkpoint_dir turns resume ON: the rung writes a
    # checkpoint pair on the cadence and, if one is already present,
    # continues from it rather than starting over (§13.3).
    pulls = []
    for rate in ladder:
        rung = _pull_rung_paths(scratch_directory, member, rate)
        pull_engine = LammpsEngine(
            command_line_args=["-screen", "none", "-log", rung.log_file],
            comm=comm)
        result = pull_at_rate(
            pull_engine, built, member, force_model, reference_file, rate,
            seed, output_directory=rung.directory,
            trajectory_file=rung.trajectory_file,
            trajectory_stride=rung.trajectory_stride,
            checkpoint_dir=rung.checkpoint_directory)
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
            bonded=True, note="contact reached and held (§9.3)"),
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
        member: MemberSpecification):
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
    seeds = member.ensemble.amorphization_count

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
        fidelity="classical-stand-in", method=method, status=status)
    thermodynamic = Measure(
        name="work_of_adhesion_mlip",
        value=None, uncertainty=None, realization_count=seeds,
        unit_native="eV/angstrom^2", unit_si="J/m^2",
        fidelity="mlip", method="not computed in v1 (wave 2)",
        status=MeasureStatus.UNRESOLVED)
    return MeasureVector(
        measures=(mechanical, thermodynamic),
        verdicts=Verdicts(
            bonded=bond_debond.press.bonded, contact_quality=None))


# ---------------------------------------------------------------------
# The live stage set (ARCHITECTURE.md §5.1). The real bodies for the steps
# that have them, reusing the W0 stubs where no live body exists yet: the
# potential is still the classical stand-in (resolve_potential), and step-8
# characterization is still mocked (run_characterization). The sequencer
# runs this set on a compute node; W0_STAGES on the login node.
# ---------------------------------------------------------------------

from sabsim.pipeline.skeleton_stages import (        # noqa: E402
    StageSet,
    resolve_potential,
    run_characterization,
)

LIVE_STAGES = StageSet(
    resolve_potential=resolve_potential,
    build=build_halves,
    activate=activate_surfaces_live,
    assemble=assemble_pair_live,
    bond_debond=run_bond_debond_md_live,
    analyze=run_analyzer_live,
    characterize=run_characterization)
