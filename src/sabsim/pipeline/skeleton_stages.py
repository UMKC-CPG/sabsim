"""Walking-skeleton stage bodies (ARCHITECTURE.md §5, wave 0).

These are the eight pipeline steps' stand-ins. Each returns a
schema-valid placeholder artifact so a well-formed number can travel
every seam (PSEUDOCODE.md §1); NONE of them is physics yet. Later waves
replace each body behind its already-frozen contract: the classical
LAMMPS press/pull for steps 6-7 first, then the real activator, the
bootstrap-trained MLIP, and the Si/SiO2 coincidence matcher
(ARCHITECTURE.md §5.1). The signatures and the artifacts they exchange
are the permanent part.
"""

from __future__ import annotations

from sabsim.pipeline.exec_artifacts import (
    ActivatedSlabs,
    BondDebondResult,
    Potential,
    PressOutcome,
    PullOutcome,
    Slab,
    SharedCell,
    Structure,
    Verdict,
)
from sabsim.pipeline.measures import (
    Measure,
    MeasureStatus,
    MeasureVector,
    Verdicts,
)
from sabsim.spec.records import MemberSpecification

# The labeled groups the structure builder tags for the MD stages: the
# heat-sink design from DESIGN.md §3 that crosses the build->press->pull
# seam. Placeholder membership in W0, but the names are the real seam.
_LABELED_GROUPS = (
    "frozen_base", "thermostat_border", "nve_interior",
    "activated_skin", "grips",
)


def resolve_potential(member: MemberSpecification) -> Potential:
    """Look up the potential the member runs under (PSEUDOCODE.md §1).

    In W0 this returns a classical ``pair_style`` stand-in regardless of
    the member's ``potential_ref``: the bootstrap that manufactures the
    real MLIP is a separate upstream process (DESIGN.md §4.5, §11) not
    yet built. The stand-in satisfies the same POTENTIAL_CONTRACT the
    trained potential will, which is what lets it be swapped in later.
    """
    return Potential(
        kind="classical-stand-in",
        pair_style="classical (walking-skeleton stand-in)",
        loadable=True,
    )


def build_slabs(
        member: MemberSpecification,
        potential: Potential) -> tuple[Slab, Slab, SharedCell]:
    """Build both wafers' slabs to a shared cell (DESIGN.md §2, §7).

    W0 returns placeholder slabs and a trivial shared cell — a Si/Si
    pair has no lattice mismatch, so the coincidence matcher stays
    dormant until the Si/SiO2 milestone (ARCHITECTURE.md §5, wave 3).
    """
    slab_a = Slab(
        identity=member.material.wafer_a.identity,
        note="placeholder slab (wave 0)")
    slab_b = Slab(
        identity=member.material.wafer_b.identity,
        note="placeholder slab (wave 0)")
    shared = SharedCell(note="trivial shared cell (Si/Si, no mismatch)")
    return slab_a, slab_b, shared


def activate_surfaces(
        slab_a: Slab,
        slab_b: Slab,
        member: MemberSpecification,
        potential: Potential) -> ActivatedSlabs:
    """Amorphize each slab's surface and gate it (DESIGN.md §3, §10.1).

    W0 stubs the amorphization and returns PASSING activation verdicts,
    so the ACTIVATED_SLABS_CONTRACT is satisfied and the pipeline flows.
    The real cascade + §3.5 gate land in a later wave behind this seam.
    """
    passed = Verdict(passed=True, reason="stubbed activation (wave 0)")
    return ActivatedSlabs(
        slab_a=slab_a, slab_b=slab_b,
        verdict_a=passed, verdict_b=passed)


def assemble_pair(
        slab_a: Slab,
        slab_b: Slab,
        shared: SharedCell,
        member: MemberSpecification) -> Structure:
    """Assemble the facing pair from the activated slabs (DESIGN.md §7)."""
    return Structure(
        note=f"placeholder pair: {slab_a.identity}/{slab_b.identity}",
        labeled_groups=_LABELED_GROUPS)


def run_bond_debond_md(
        structure: Structure,
        potential: Potential,
        member: MemberSpecification) -> BondDebondResult:
    """Press then pull, over the rate ladder (DESIGN.md §5, §9.1).

    W0 returns a placeholder press outcome and one placeholder pull per
    rung of the spec's ladder, so the BOND_DEBOND_CONTRACT is satisfied.
    The real classical-LAMMPS press/pull is the very next wave-0 slice,
    dropping in behind this same contract.
    """
    pulls = tuple(
        PullOutcome(
            rate_value=rung.value,
            rate_unit=rung.unit,
            note="placeholder pull (wave 0)")
        for rung in member.numerical.pull_rate_ladder
    )
    return BondDebondResult(
        press=PressOutcome(bonded=True, note="stubbed press (wave 0)"),
        reference_ok=True,
        pulls=pulls)


def run_analyzer(
        structure: Structure,
        result: BondDebondResult,
        member: MemberSpecification) -> MeasureVector:
    """Turn the bond/debond result into a measure vector (DESIGN.md §6).

    W0 emits ONE well-formed mechanical measure — the single untrusted
    number that proves the pipeline is wired end to end — and marks the
    higher-fidelity measures ``unresolved``, exactly as PSEUDOCODE.md §1
    describes for the skeleton. The value is a stand-in, not physics;
    the member it belongs to is flagged untrusted.

    The press outcome is read ONCE here into the vector's
    :class:`Verdicts` (PSEUDOCODE.md §4): the bond decision is a fact
    about the run, not an averaged measure, so it is surfaced directly
    rather than dropped. ``contact_quality`` stays None in W0, where the
    press is stubbed and only the ``bonded`` flag is meaningful.
    """
    verdicts = Verdicts(
        bonded=result.press.bonded,
        contact_quality=None)      # §5.2 fraction not computed in W0
    seeds = member.ensemble.amorphization_count
    mechanical = Measure(
        name="mechanical_work_of_separation",
        value=1.0,                 # placeholder stand-in, not physics
        uncertainty=0.0,
        realization_count=seeds,
        unit_native="eV/angstrom^2",
        unit_si="J/m^2",
        fidelity="classical-stand-in",
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
        member: MemberSpecification) -> MeasureVector:
    """Step-8 characterization (DESIGN.md §8), MOCKED in the skeleton.

    Returns schema-valid ``unresolved`` records for the all-electron and
    descriptor measures, so the MEASURE_VECTOR_CONTRACT holds while the
    real Imago/VASP seam waits on wave 4.
    """
    seeds = member.ensemble.amorphization_count
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
