"""The Tier-A sequencer: the top-level control flow (PSEUDOCODE.md §1).

This is ``exec_full_study`` and ``exec_one_member`` made real. The
sequencer owns the eight pipeline steps and the (v1-open) quality-gate
loop, running each member to a self-standing report and then grading
whatever relations the study declared. Every stage is routed through
the ``run_to_contract`` guard, so the pipeline advances only while each
stage produces a contract-valid artifact and HALTS loudly otherwise
(ARCHITECTURE.md §4.1, §5.1).

In the walking skeleton (ARCHITECTURE.md §5, wave 0) the stage bodies
are stand-ins (:mod:`sabsim.pipeline.skeleton_stages`), so the number a
member produces is plumbing, not physics — every ``MemberResult`` is
stamped ``trusted=False``. What is REAL here is the control flow, the
contract guarding, the provenance stamp, and the machine-readable
emission; later waves deepen the stages behind these same seams.
"""

from __future__ import annotations

from sabsim.pipeline.contracts import (
    ACTIVATED_SLABS_CONTRACT,
    BOND_DEBOND_CONTRACT,
    MEASURE_VECTOR_CONTRACT,
    POTENTIAL_CONTRACT,
    SLABS_CONTRACT,
    STRUCTURE_CONTRACT,
    run_to_contract,
)
from sabsim.pipeline.exec_artifacts import (
    GateReport,
    MemberResult,
    Provenance,
    RelationOutcome,
    StudyReport,
    build_provenance,
)
from sabsim.pipeline.measures import (
    MeasureStatus,
    MeasureVector,
    merge_measures,
)
from sabsim.pipeline.skeleton_stages import (
    activate_surfaces,
    assemble_pair,
    build_slabs,
    resolve_potential,
    run_analyzer,
    run_bond_debond_md,
    run_characterization,
)
from sabsim.spec.loader import load_and_validate_study
from sabsim.spec.records import MemberSpecification, Relation


def exec_full_study(study_specification) -> StudyReport:
    """Run a whole study: every member, then the declared relations (§1).

    Loads and validates the spec, executes each member independently to
    a self-standing report, then grades the optional relations at the
    study level (there may be none). Returns the :class:`StudyReport`;
    also emits the machine-readable record (DESIGN.md §6.6).
    """
    study = load_and_validate_study(study_specification)

    member_results = tuple(
        exec_one_member(member) for member in study.members)

    # Relations are an OPTIONAL comparison layer graded only after every
    # member has produced its measure vector (DESIGN.md §1.1).
    relation_outcomes = evaluate_relations(
        study.relations, member_results)

    report = StudyReport(
        study_name=study.name,
        member_results=member_results,
        relation_outcomes=relation_outcomes)
    emit_study(report)
    return report


def exec_one_member(
        member: MemberSpecification) -> MemberResult:
    """Run the eight-step pipeline for ONE member (PSEUDOCODE.md §1).

    Each stage is wrapped in ``run_to_contract``: the stage runs, then
    the pipeline advances only if its output satisfies the contract the
    NEXT stage depends on. In v1 the quality-gate loop executes its body
    ONCE and reports (VISION principle 5); the closed loop is a future
    target, so it is not iterated here.
    """
    # The potential is a CONTRACT, not a fixed implementation. The
    # skeleton satisfies it with a classical stand-in; the bootstrap
    # wave later satisfies it with the trained MLIP through this seam.
    potential = run_to_contract(
        lambda: resolve_potential(member),
        POTENTIAL_CONTRACT)

    # Steps 3-4-5. Their order is a setting (the builder and activator
    # are order-agnostic behind their contracts, DESIGN.md §5.3); v1
    # uses the only physically sensible order, build -> activate ->
    # assemble.
    slab_a, slab_b, shared = run_to_contract(
        lambda: build_slabs(member, potential),
        SLABS_CONTRACT)

    # A FAILED activation gate is contract-invalid and halts HERE: the
    # ACTIVATED_SLABS_CONTRACT checks both verdicts passed (§10.1).
    activated = run_to_contract(
        lambda: activate_surfaces(slab_a, slab_b, member, potential),
        ACTIVATED_SLABS_CONTRACT)
    slab_a = activated.slab_a      # rebind to the activated slabs; the
    slab_b = activated.slab_b      # verdicts rode the contract check

    structure = run_to_contract(
        lambda: assemble_pair(slab_a, slab_b, shared, member),
        STRUCTURE_CONTRACT)

    # Steps 6-7: press then pull, over the rate ladder. The result is a
    # BondDebondResult (§9.1), not a bare trajectory.
    bond_debond = run_to_contract(
        lambda: run_bond_debond_md(structure, potential, member),
        BOND_DEBOND_CONTRACT)

    # The analyzer turns that into a measure vector (DESIGN.md §6); in
    # the skeleton only the mechanical measure is present, the rest
    # report `unresolved`.
    measures = run_to_contract(
        lambda: run_analyzer(structure, bond_debond, member),
        MEASURE_VECTOR_CONTRACT)

    # Step 8 characterization (DESIGN.md §8), MOCKED in the skeleton.
    characterization = run_to_contract(
        lambda: run_characterization(structure, bond_debond, member),
        MEASURE_VECTOR_CONTRACT)
    measures = merge_measures(measures, characterization)

    # The gate READS the measure vector and REPORTS; in v1 it never acts
    # and never edits a measure (DESIGN.md §7).
    gate = evaluate_member_gates(measures, member, potential)

    result = MemberResult(
        specification=member,
        potential=build_provenance(potential, member),
        measures=measures,
        gate=gate,
        trusted=False)              # walking-skeleton plumbing (§5.3)
    emit_member(result)
    return result


def evaluate_member_gates(
        measures: MeasureVector,
        member: MemberSpecification,
        potential) -> GateReport:
    """Read the measure vector and report a verdict (DESIGN.md §7).

    In wave 0 the live gate and its five-way diagnosis (§7.7) are not
    built yet, so this collects the measure names it saw and states
    plainly that the result is untrusted skeleton plumbing.
    """
    measures_seen = tuple(
        measure.name for measure in measures.measures)
    return GateReport(
        summary=("wave 0 walking skeleton: measures collected, not "
                 "graded (the live §7 gate lands in wave 1); result is "
                 "untrusted."),
        acted=False,
        measures_seen=measures_seen)


def evaluate_relations(
        relations: tuple[Relation, ...],
        member_results: tuple[MemberResult, ...]) -> tuple:
    """Grade each declared relation across the member results (§7.4).

    A relation is REPORTED, never used to restrict (DESIGN.md §1.1): an
    unresolved or untrusted outcome is still returned, with the reason.
    Returns an empty tuple when the study declared no relations.
    """
    results_by_name = {
        result.specification.name: result
        for result in member_results}
    return tuple(
        _evaluate_one_relation(relation, results_by_name)
        for relation in relations)


def _evaluate_one_relation(
        relation: Relation,
        results_by_name: dict) -> RelationOutcome:
    """Grade one relation; v1 knows the `ratio` kind (DESIGN.md §7.4).

    The ratio divides the first related member's measure by the second's
    (e.g. Si/SiO2 over Si/Si). If either measure is missing or
    unresolved, or the kind is one v1 does not evaluate, the outcome is
    unresolved with a note — never an exception.
    """
    measure_name = relation.measures[0]
    values = []
    trusted = True
    for member_name in relation.members:
        result = results_by_name[member_name]
        trusted = trusted and result.trusted
        measure = result.measures.by_name(measure_name)
        if (measure is None or measure.status != MeasureStatus.OK
                or measure.value is None):
            values.append(None)
        else:
            values.append(measure.value)

    if relation.kind != "ratio" or len(values) != 2:
        return RelationOutcome(
            kind=relation.kind, members=relation.members,
            value=None, unit="dimensionless", trusted=trusted,
            note=f"kind '{relation.kind}' not evaluated in v1")

    numerator, denominator = values
    if numerator is None or denominator is None or denominator == 0.0:
        return RelationOutcome(
            kind=relation.kind, members=relation.members,
            value=None, unit="dimensionless", trusted=trusted,
            note=f"unresolved: measure '{measure_name}' missing or zero")

    return RelationOutcome(
        kind=relation.kind, members=relation.members,
        value=numerator / denominator, unit="dimensionless",
        trusted=trusted,
        note=f"ratio of '{measure_name}' over {relation.members}")


# ---------------------------------------------------------------------
# Machine-readable emission (DESIGN.md §6.6). to_record builds a plain,
# JSON-serializable view; emit_* are the emission seam. Persisting to
# the §4.1 file contract on the shared filesystem is a later-wave slice.
# ---------------------------------------------------------------------

def _measure_to_record(measure) -> dict:
    """Serialize one Measure to a plain dict (no bare numbers, §6.6)."""
    return {
        "name": measure.name,
        "value": measure.value,
        "uncertainty": measure.uncertainty,
        "realization_count": measure.realization_count,
        "unit_native": measure.unit_native,
        "unit_si": measure.unit_si,
        "fidelity": measure.fidelity,
        "method": measure.method,
        "status": measure.status.value,
    }


def _provenance_to_record(provenance: Provenance) -> dict:
    """Serialize the provenance stamp to a plain dict (§1.6)."""
    return {
        "potential_ref": provenance.potential_ref,
        "potential_kind": provenance.potential_kind,
        "master_seed": provenance.master_seed,
        "protocol_fingerprint": provenance.protocol_fingerprint,
    }


def _member_to_record(result: MemberResult) -> dict:
    """Serialize one member's result to a plain dict."""
    return {
        "member": result.specification.name,
        "trusted": result.trusted,
        "potential": _provenance_to_record(result.potential),
        "measures": [
            _measure_to_record(measure)
            for measure in result.measures.measures],
        "gate": {
            "summary": result.gate.summary,
            "acted": result.gate.acted,
            "measures_seen": list(result.gate.measures_seen),
        },
    }


def to_record(report: StudyReport) -> dict:
    """Build the whole study's machine-readable record (DESIGN.md §6.6)."""
    return {
        "study": report.study_name,
        "members": [
            _member_to_record(result)
            for result in report.member_results],
        "relations": [
            {
                "kind": outcome.kind,
                "members": list(outcome.members),
                "value": outcome.value,
                "unit": outcome.unit,
                "trusted": outcome.trusted,
                "note": outcome.note,
            }
            for outcome in report.relation_outcomes],
    }


def emit_member(result: MemberResult) -> dict:
    """Emit one member's machine-readable record (the emission seam)."""
    return _member_to_record(result)


def emit_study(report: StudyReport) -> dict:
    """Emit the study's machine-readable record (the emission seam).

    Wave 0 returns the record; writing it to the §4.1 file contract on
    the shared filesystem is a later slice.
    """
    return to_record(report)
