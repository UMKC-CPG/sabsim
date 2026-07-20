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

import numpy as np
from ase.io import read as ase_read
from ase.io import write as ase_write

from sabsim.driver.cascade import (
    CascadeControl,
    _projectile_species,
    activate_surface,
    derive_seeds,
)
from sabsim.driver.commands import CascadeGeometry, ForceModel, to_metal
from sabsim.pipeline.activation_adapter import activated_slabs_from_results
from sabsim.pipeline.exec_artifacts import (
    HalfHandle,
    SharedCell,
    Slab,
    Structure,
)
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

# Sizing stand-ins (DESIGN.md §3.6; see the module docstring). A workable
# Si smoke cell, NOT pinned physical values.
_MIN_SLAB_THICKNESS = 30.0     # Å: frozen base + border + undamaged bulk
_MIN_VACUUM = 30.0             # Å: room above the surface for the beam spawn
_LATERAL_REPEAT = 3            # tile n x n so one impact does not dominate


def _resolve_cif(cif_source: str) -> str:
    """Resolve a wafer's CIF path (spec paths are repo-root relative).

    A member's ``cif_source`` is written relative to the repo root (e.g.
    ``src/sabsim/structure/data/si_diamond.cif``), the directory runs are
    launched from (VISION.md principle 1 — where to run is stated). An
    absolute path is used as-is; a relative one resolves against the
    current working directory.
    """
    path = Path(cif_source)
    return str(path if path.is_absolute() else Path.cwd() / path)


def _build_one_half(
        wafer,
        member: MemberSpecification,
        scratch_directory: str,
        wafer_tag: int) -> HalfHandle:
    """Cut ONE wafer alone, write its data file, return its handle (§7.1).

    Loads the wafer's crystal, builds a standalone half in vacuum with the
    beam species declared, writes it to a LAMMPS data file under the
    member's scratch, and hands back the :class:`HalfHandle` the
    amorphization stage re-reads it from. ``wafer_tag`` fixes the assembly
    role (bottom A / top B) that rides on the handle.
    """
    crystal = load_crystal(_resolve_cif(wafer.cif_source))
    half = build_standalone_half(
        crystal, wafer.surface_face, wafer.identity,
        _projectile_species(member),
        min_slab_thickness=_MIN_SLAB_THICKNESS,
        min_vacuum=_MIN_VACUUM, lateral_repeat=_LATERAL_REPEAT)
    role = "a" if wafer_tag == WAFER_A_TAG else "b"
    data_file = os.path.join(
        str(scratch_directory), f"half_{role}_{wafer.identity}.data")
    write_standalone_half(half, data_file)
    return HalfHandle(
        data_file=data_file, type_map=half.type_map,
        identity=wafer.identity, wafer_tag=wafer_tag)


def build_halves(
        member: MemberSpecification,
        potential,
        scratch_directory: str) -> tuple[HalfHandle, HalfHandle, SharedCell]:
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
    handle_a = _build_one_half(
        member.material.wafer_a, member, scratch_directory, WAFER_A_TAG)
    handle_b = _build_one_half(
        member.material.wafer_b, member, scratch_directory, WAFER_B_TAG)
    shared = SharedCell(
        note="Si/Si identity shared cell (wave-3 matcher dormant, §7.6)")
    return handle_a, handle_b, shared


# ---------------------------------------------------------------------
# Step 4 — the engine-provider activation stage (COMPUTE NODE). Opens a
# LammpsEngine per half, re-reads the pristine half, runs the driver's
# cascade -> re-anneal -> gate, and writes the amorphized half back.
# ---------------------------------------------------------------------

def _reanneal_force_model(type_map: dict, substrate: set) -> ForceModel:
    """The gentle re-anneal potential, NULLing the deleted beam type.

    v1's 'MLIP' is the classical Stillinger-Weber stand-in (DESIGN.md §4.5).
    After the cascade deletes the beam atoms the beam TYPE is still
    declared, so ``sw`` maps it to NULL — but LAMMPS then needs every
    declared type pair SET even with zero beam atoms, so a no-op ``zero``
    pair style is overlaid to set those dead pairs while ``sw`` does the
    real Si-Si physics. (The trained MLIP would take the same zero overlay.)
    STAND-IN: silicon-specific (``sw Si.sw``); a general re-anneal potential
    is resolved from the material at wave 2 (DESIGN.md §4.5).
    """
    order = sorted(type_map, key=lambda symbol: type_map[symbol])
    labels = " ".join(s if s in substrate else "NULL" for s in order)
    return ForceModel(
        pair_style="hybrid/overlay sw zero 1.0",
        pair_coeff=(f"* * sw Si.sw {labels}", "* * zero"))


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
    mlip = _reanneal_force_model(handle.type_map, substrate)

    role = "a" if handle.wafer_tag == WAFER_A_TAG else "b"
    log_file = os.path.join(output_directory, f"log.activation_{role}")
    engine = LammpsEngine(
        command_line_args=["-screen", "none", "-log", log_file], comm=comm)
    result = activate_surface(
        engine, built, member, mlip, handle.data_file, seed,
        _GEOMETRY, _CONTROL)
    # Snapshot BEFORE closing: the re-annealed state is still live here.
    amorphized_atoms = snapshot_amorphized_half(
        engine, handle.type_map, handle.wafer_tag)
    engine.close()

    amorphized_file = os.path.join(
        output_directory, f"amorphized_{role}.extxyz")
    ase_write(amorphized_file, amorphized_atoms, format="extxyz")
    return result, amorphized_file


def activate_surfaces_live(
        handle_a: HalfHandle,
        handle_b: HalfHandle,
        member: MemberSpecification,
        potential,
        output_directory: str,
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
        handle_a, member, half_seeds[0], output_directory, comm)
    result_b, amorphized_b = activate_one_half(
        handle_b, member, half_seeds[1], output_directory, comm)

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
        member: MemberSpecification,
        shared: SharedCell,
        output_directory: str) -> Structure:
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
    """
    half_a = ase_read(activated.slab_a.data_file, format="extxyz")
    half_b = ase_read(activated.slab_b.data_file, format="extxyz")

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

    pair_file = os.path.join(output_directory, "assembled_pair.data")
    write_lammps_data(built, pair_file)
    return Structure(
        note=(f"assembled amorphized pair "
              f"{activated.slab_a.identity}/{activated.slab_b.identity}; "
              f"gap adjust {built.initial_gap_adjustment:.2f} Å"),
        labeled_groups=(
            "wafer_a_z_range", "wafer_b_z_range", "interface_z",
            "activated_skin"),
        data_file=pair_file)
