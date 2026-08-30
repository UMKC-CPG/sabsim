"""Walking-skeleton stage bodies (ARCHITECTURE.md §5, wave 0).

These are the eight pipeline steps' stand-ins. Each returns a
schema-valid placeholder artifact so a well-formed number can travel
every seam (PSEUDOCODE.md §1); NONE of them is physics yet. Later waves
replace each body behind its already-frozen contract: the LAMMPS
press/pull for steps 6-7 first, then the real activator, the
bootstrap-trained MLIP, and the Si/SiO2 coincidence matcher
(ARCHITECTURE.md §5.1). The signatures and the artifacts they exchange
are the permanent part.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sabsim.pipeline.exec_artifacts import (
    ActivatedHalf,
    ActivatedSlabs,
    BondDebondResult,
    DerivedLattices,
    HalfHandle,
    PressOutcome,
    PullOutcome,
    Slab,
    SharedCell,
    Structure,
)

# Wafer provenance tags — bottom A / top B (the assembly invariant, DESIGN
# §2.6). The authoritative constants live in structure.slab_builder
# (WAFER_A_TAG / WAFER_B_TAG); they are inlined here so the W0 stub stays
# free of that module's heavy pymatgen import.
_WAFER_A_TAG = 1
_WAFER_B_TAG = 2
from sabsim.pipeline.measures import (
    Measure,
    MeasureStatus,
    MeasureVector,
    Verdicts,
)
from sabsim.spec.records import PairSpecification

# What the structure builder contributes to region definition, crossing
# the build->press->pull seam. Under option C (labeled-group ownership,
# 2026-07-15) the builder records only the zone GEOMETRY — the per-wafer
# z-ranges each stage's driver carves its depth zones from (DESIGN.md
# §2.6) — plus the ONE measured set the driver cannot re-carve, the
# activated_skin. Placeholder pairship in W0; the real z-ranges live on
# slab_builder.BuiltPair, wired into the pipeline at slice 1b. Wafer A is
# the bottom slab and wafer B the top by construction (see BuiltPair).
_LABELED_GROUPS = (
    "wafer_a_z_range", "wafer_b_z_range", "interface_z",
    "activated_skin",
)


def _placeholder_handle(
        wafer, beam: str, scratch_directory: str,
        wafer_tag: int) -> HalfHandle:
    """A W0 half-handle: the seam's shape, without writing a file.

    Names a data-file path under ``scratch_directory`` (never written in
    W0) and a minimal beam-declaring type map, enough to satisfy the
    SLABS_CONTRACT and exercise the handle seam; the real
    :func:`sabsim.pipeline.live_stages.build_halves` writes the file.
    """
    role = "a" if wafer_tag == _WAFER_A_TAG else "b"
    type_map = {wafer.identity: 1, beam: 2}     # substrate + beam declared
    return HalfHandle(
        data_file=f"{scratch_directory}/half_{role}.data",
        type_map=type_map, identity=wafer.identity, wafer_tag=wafer_tag)


def derive_lattices(
        pair: PairSpecification,
        scratch_directory: str | None = None,
        comm=None) -> DerivedLattices:
    """Derive each material's working lattice (DESIGN.md §2.2 — W0 stub).

    The real step relaxes a bulk block under the current model to find the
    lattice the slabs are cut on (retiring the CIF's published scale). W0
    opens no engine, so it cannot relax — it returns a PLACEHOLDER cell per
    material identity, enough to exercise the derive->build seam without a
    compute node. The live body
    (:func:`sabsim.pipeline.live_stages.derive_lattices_live`) does the
    real relaxation through this same contract.
    """
    placeholder = (
        (5.43, 0.0, 0.0), (0.0, 5.43, 0.0), (0.0, 0.0, 5.43))
    identities = {
        pair.material.wafer_a.identity, pair.material.wafer_b.identity}
    return DerivedLattices(
        cells={identity: placeholder for identity in identities},
        provenance="walking-skeleton stand-in (no relaxation)")


def build_slabs(
        pair: PairSpecification,
        derived_lattices: DerivedLattices,
        scratch_directory: str,
        comm=None) -> tuple[HalfHandle, HalfHandle, SharedCell]:
    """Build both wafers as standalone half-handles (DESIGN.md §2, §7.1).

    W0 returns PLACEHOLDER handles — no data file is written, ``derived_
    lattices`` is accepted (the live build rescales each crystal to it) but
    ignored here, and the coincidence matcher stays dormant (a Si/Si pair
    has no lattice mismatch, wave 3) — so the pipeline's control flow and
    the build->amorphize handle seam are exercised without a compute node.
    The real :func:`sabsim.pipeline.live_stages.build_halves` writes two
    standalone slab files under ``scratch_directory`` and returns real
    handles through this same contract.
    """
    beam = pair.protocol.activation_species
    handle_a = _placeholder_handle(
        pair.material.wafer_a, beam, scratch_directory, _WAFER_A_TAG)
    handle_b = _placeholder_handle(
        pair.material.wafer_b, beam, scratch_directory, _WAFER_B_TAG)
    shared = SharedCell(note="trivial shared cell (Si/Si, no mismatch)")
    return handle_a, handle_b, shared


def _placeholder_verdict():
    """A PASSING placeholder verdict, so the W0 contracts flow."""
    from sabsim.driver.activation_gate import ActivationVerdict
    return ActivationVerdict(
        passed=True, activated_depth=0.0, per_metric={},
        reason="placeholder verdict (wave 0): nothing was gated")


def activate_surface(
        handle: HalfHandle,
        shared: SharedCell,
        pair: PairSpecification,
        scratch_directory: str | None = None,
        comm=None) -> ActivatedHalf:
    """Amorphize and gate ONE half — a prep job's stage (§10.1, §14.3).

    Revised 2026-08-30 (Paul): each surface is prepared by its own prep
    job, so this is the per-surface form the sequencer and the prep job
    both call. W0 writes nothing and opens no engine: it returns a
    placeholder slab with a PASSING placeholder verdict, carrying the
    handle's wafer tag and the shared cell it was (notionally) cut on,
    so the ACTIVATED_HALF_CONTRACT is met and the pipeline flows. The
    REAL body is :func:`sabsim.pipeline.live_stages.activate_one_surface_
    live`, which runs the cascade + heal out-of-process and gates the
    healed half (§3.5).
    """
    slab = Slab(identity=handle.identity, note="placeholder (wave 0)")
    return ActivatedHalf(
        slab=slab, verdict=_placeholder_verdict(),
        wafer_tag=handle.wafer_tag, shared=shared)


def activate_surfaces(
        handle_a: HalfHandle,
        handle_b: HalfHandle,
        pair: PairSpecification,
        scratch_directory: str | None = None,
        comm=None) -> ActivatedSlabs:
    """Amorphize each half's surface and gate it (DESIGN.md §3, §10.1).

    (``scratch_directory`` and ``comm`` are accepted so this stub shares
    the uniform stage signature the real
    :func:`sabsim.pipeline.live_stages.activate_surfaces_live` uses; W0
    writes nothing and opens no engine, so it ignores them.)

    W0 stubs the amorphization, returning two placeholder slabs with
    PASSING placeholder verdicts, so the ACTIVATED_SLABS_CONTRACT (both
    slabs present, both gates passed, §10.1) is satisfied and the
    pipeline flows. The REAL body is
    :func:`sabsim.pipeline.live_stages.activate_surfaces_live`: it runs
    each half's cascade + heal as one out-of-process session
    (:mod:`sabsim.driver.cascade`), gates the healed half (§3.5), and
    writes it back. It is not called here because it needs a compute
    node the W0 login-node skeleton has no access to. The seam does not
    change: the sequencer carries the :class:`ActivatedSlabs` forward.
    """
    slab_a = Slab(identity=handle_a.identity, note="placeholder (wave 0)")
    slab_b = Slab(identity=handle_b.identity, note="placeholder (wave 0)")
    placeholder = _placeholder_verdict()
    return ActivatedSlabs(slab_a=slab_a, slab_b=slab_b,
                          verdict_a=placeholder, verdict_b=placeholder)


def assemble_pair(
        activated: ActivatedSlabs,
        shared: SharedCell,
        pair: PairSpecification,
        scratch_directory: str | None = None,
        comm=None) -> Structure:
    """Assemble the facing pair from the activated slabs (DESIGN.md §7).

    W0 returns a placeholder pair (no file written); the real
    :func:`sabsim.pipeline.live_stages.assemble_pair_live` reads both
    amorphized halves back and stacks them. Both take the same arguments.
    """
    return Structure(
        note=(f"placeholder pair: {activated.slab_a.identity}/"
              f"{activated.slab_b.identity}"),
        labeled_groups=_LABELED_GROUPS)


def run_bond_debond_md(
        structure: Structure,
        pair: PairSpecification,
        scratch_directory: str | None = None,
        comm=None) -> BondDebondResult:
    """Press then pull, over the rate ladder (DESIGN.md §5, §9.1).

    W0 returns a placeholder press outcome and one placeholder pull per
    rung of the spec's ladder, so the BOND_DEBOND_CONTRACT is satisfied.
    The real press/pull is
    :func:`sabsim.pipeline.live_stages.run_bond_debond_md_live`, which
    sequences the validated driver phases behind this same contract.
    (``scratch_directory`` and ``comm`` are accepted for the uniform stage
    signature; the stub ignores them.)
    """
    pulls = tuple(
        PullOutcome(
            rate_value=rung.value,
            rate_unit=rung.unit,
            note="placeholder pull (wave 0)")
        for rung in pair.numerical.pull_rate_ladder
    )
    return BondDebondResult(
        press=PressOutcome(bonded=True, note="stubbed press (wave 0)"),
        reference_ok=True,
        pulls=pulls)


def run_analyzer(
        structure: Structure,
        result: BondDebondResult,
        pair: PairSpecification) -> MeasureVector:
    """Turn the bond/debond result into a measure vector (DESIGN.md §6).

    W0 emits ONE well-formed mechanical measure — the single untrusted
    number that proves the pipeline is wired end to end — and marks the
    higher-fidelity measures ``unresolved``, exactly as PSEUDOCODE.md §1
    describes for the skeleton. The value is a stand-in, not physics;
    the pair it belongs to is flagged untrusted.

    The press outcome is read ONCE here into the vector's
    :class:`Verdicts` (PSEUDOCODE.md §4): the bond decision is a fact
    about the run, not an averaged measure, so it is surfaced directly
    rather than dropped. ``contact_quality`` stays None in W0, where the
    press is stubbed and only the ``bonded`` flag is meaningful.
    """
    verdicts = Verdicts(
        bonded=result.press.bonded,
        contact_quality=None)      # §5.2 fraction not computed in W0
    seeds = pair.ensemble.amorphization_count
    mechanical = Measure(
        name="mechanical_work_of_separation",
        value=1.0,                 # placeholder stand-in, not physics
        uncertainty=0.0,
        realization_count=seeds,
        unit_native="eV/angstrom^2",
        unit_si="J/m^2",
        fidelity="placeholder",
        method="walking-skeleton stub",
        status=MeasureStatus.OK)
    thermodynamic = Measure(
        name="work_of_adhesion_mlip",
        value=None,
        uncertainty=None,
        realization_count=seeds,
        unit_native="eV/angstrom^2",
        unit_si="J/m^2",
        fidelity="mlip",
        method="not computed in wave 0",
        status=MeasureStatus.UNRESOLVED)
    return MeasureVector(
        measures=(mechanical, thermodynamic),
        verdicts=verdicts)


def run_characterization(
        structure: Structure,
        result: BondDebondResult,
        pair: PairSpecification) -> MeasureVector:
    """Step-8 characterization (DESIGN.md §8), MOCKED in the skeleton.

    Returns schema-valid ``unresolved`` records for the all-electron and
    descriptor measures, so the MEASURE_VECTOR_CONTRACT holds while the
    real Imago/VASP seam waits on wave 4.
    """
    seeds = pair.ensemble.amorphization_count
    all_electron = Measure(
        name="work_of_adhesion_allelectron",
        value=None, uncertainty=None, realization_count=seeds,
        unit_native="eV/angstrom^2", unit_si="J/m^2",
        fidelity="all-electron",
        method="mocked in wave 0", status=MeasureStatus.UNRESOLVED)
    descriptors = Measure(
        name="bond_descriptors",
        value=None, uncertainty=None, realization_count=seeds,
        unit_native="none", unit_si="none",
        fidelity="all-electron",
        method="mocked in wave 0", status=MeasureStatus.UNRESOLVED)
    return MeasureVector(measures=(all_electron, descriptors))


# ---------------------------------------------------------------------
# The stage set — which body runs at each seam. The sequencer takes a
# StageSet and calls its stages, so the SAME control flow runs either the
# W0 stubs (login node, no LAMMPS) or the real live_stages (compute node)
# behind the same contracts (ARCHITECTURE.md §5.1). This is the switch:
# W0_STAGES here; LIVE_STAGES in sabsim.pipeline.live_stages.
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class StageSet:
    """The eight stage bodies the sequencer calls, as one swappable set.

    Every stage in a set shares a uniform signature so the sequencer's call
    sites do not change between the stub and the live set: ``build``,
    ``activate_surface``, ``assemble`` and ``bond_debond`` take the
    stage's working directory (and, where an engine runs, the MPI
    communicator); a stub simply ignores what it does not use. Swapping
    the set is the ONLY difference between a login-node control-flow run
    and a real compute-node run.

    ``activate_surface`` is the per-surface form (revised 2026-08-30):
    the prep job for surface N calls it once, for its own half; the
    whole-chain run calls it twice, once per half.
    """

    derive_lattices: Callable      # (pair, scratch, comm)
    build: Callable                # (pair, lattices, scratch, comm)
    activate_surface: Callable     # (handle, shared, pair, scratch, comm)
    assemble: Callable             # (activated, shared, pair, scratch)
    bond_debond: Callable          # (structure, pair, scratch, comm)
    analyze: Callable              # (structure, bond_debond, pair)
    characterize: Callable         # (structure, bond_debond, pair)


# The walking-skeleton set: every stage a login-node stub (no LAMMPS), the
# sequencer's default so W0 control-flow tests need no compute node.
W0_STAGES = StageSet(
    derive_lattices=derive_lattices,
    build=build_slabs,
    activate_surface=activate_surface,
    assemble=assemble_pair,
    bond_debond=run_bond_debond_md,
    analyze=run_analyzer,
    characterize=run_characterization)
