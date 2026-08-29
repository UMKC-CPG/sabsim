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
    DERIVED_LATTICES_CONTRACT,
    MEASURE_VECTOR_CONTRACT,
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
from sabsim.pipeline.skeleton_stages import W0_STAGES
from sabsim.deploy.scratch import member_scratch
from sabsim.spec.loader import load_and_validate_study
from sabsim.spec.references import check_study_references
from sabsim.spec.records import MemberSpecification, Relation


def exec_full_study(
        study_specification, job_directory,
        stage_set=W0_STAGES, comm=None, only=None) -> StudyReport:
    """Run a whole study: every member, then the declared relations (§1).

    Loads and validates the spec, executes each member independently to
    a self-standing report, then grades the optional relations at the
    study level (there may be none). Returns the :class:`StudyReport`;
    also emits the machine-readable record (DESIGN.md §6.6).

    ``job_directory`` is the run's home on the shared filesystem
    (ARCHITECTURE.md §4.1); each member's bulky intermediates go in its
    scratch subtree, keyed by study + member identity (§4.2 mirror) and
    threaded EXPLICITLY into the stages that write files, so every written
    byte stays traceable to its inputs (VISION.md goal 3). It is a required
    argument — there is no default run home (DESIGN.md §1.4, no hidden
    defaults).

    ``stage_set`` chooses WHICH bodies run at each seam (ARCHITECTURE.md
    §5.1): the default ``W0_STAGES`` is the login-node walking skeleton (no
    LAMMPS); a real run passes ``LIVE_STAGES`` (from
    :mod:`sabsim.pipeline.live_stages`) and the MPI ``comm`` its engines
    use. The control flow and the contracts are identical either way.

    ``only`` restricts the run to a subset of members BY NAME (an iterable
    of member names, or None for all) — the ``sabsim run --only`` case,
    for testing or re-running a single member. A name not in the study is
    an error, never a silent no-op. Relations are still graded over
    whatever members ran (an unresolved relation is reported, not fatal).
    """
    study = load_and_validate_study(study_specification)
    # Phase three (DESIGN.md §1.5): the spec parsed and is executable in
    # principle — but does everything it POINTS AT actually exist? This
    # needs the filesystem and the registry rather than the file's text,
    # which is why it is separate from the loader, and it runs HERE
    # because here is the last moment before node-hours are spent. The
    # skeleton never opens the §3.5 gate, so only a live stage set is
    # held to the environment library (DESIGN §3.5, 2026-08-29).
    check_study_references(
        study, activation_gate_will_run=stage_set is not W0_STAGES)

    members = study.members
    if only is not None:
        wanted = set(only)
        present = {member.name for member in members}
        missing = wanted - present
        if missing:
            raise ValueError(
                f"--only names members not in the study: "
                f"{sorted(missing)}; the study has {sorted(present)}")
        members = tuple(m for m in members if m.name in wanted)

    member_results = tuple(
        exec_one_member(
            member,
            member_scratch(job_directory, study.name, member.name),
            stage_set, comm)
        for member in members)

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
        member: MemberSpecification,
        scratch_directory,
        stage_set=W0_STAGES,
        comm=None) -> MemberResult:
    """Run the eight-step pipeline for ONE member (PSEUDOCODE.md §1).

    Each stage is wrapped in ``run_to_contract``: the stage runs, then
    the pipeline advances only if its output satisfies the contract the
    NEXT stage depends on. In v1 the quality-gate loop executes its body
    ONCE and reports (VISION principle 5); the closed loop is a future
    target, so it is not iterated here.

    ``scratch_directory`` is this member's own scratch subtree (threaded in
    by :func:`exec_full_study`); the file-writing stages — ``build`` first —
    receive it explicitly rather than rebuild it from identity
    (ARCHITECTURE.md §4.3). ``stage_set`` selects the stub or live body at
    each seam, and ``comm`` is the MPI communicator its engines use (unused
    by the stubs). The control flow below is identical for either set.
    """
    # Which force models this member runs under is written in its study
    # file (the [potential] block, DESIGN.md §1.6); each stage reads
    # member.potential itself, so nothing is looked up and passed along.
    derived_lattices = run_to_contract(
        lambda: stage_set.derive_lattices(
            member, scratch_directory, comm),
        DERIVED_LATTICES_CONTRACT)

    # Steps 3-4-5. Their order is a setting (the builder and activator
    # are order-agnostic behind their contracts, DESIGN.md §5.3); v1
    # uses the only physically sensible order, build -> activate ->
    # assemble. build rescales each crystal to its derived lattice, writes
    # each standalone half under the member's scratch, and returns the two
    # HANDLES (§7.1, the build->amorphize seam).
    handle_a, handle_b, shared = run_to_contract(
        lambda: stage_set.build(
            member, derived_lattices, scratch_directory, comm),
        SLABS_CONTRACT)

    # Cascade-only (§3.4, revised 2026-08-08): activation just amorphizes
    # each half, and the ACTIVATED_SLABS_CONTRACT checks only that both
    # amorphized slabs are present (§10.1). The §3.5 gate moved to the bond
    # flow, so the pass/fail activation HALT now falls there, not here. Each
    # call re-reads its half from the handle's data file, amorphizes it, and
    # writes the amorphized half back for assembly to read.
    activated = run_to_contract(
        lambda: stage_set.activate(
            handle_a, handle_b, member, scratch_directory, comm),
        ACTIVATED_SLABS_CONTRACT)

    # Assembly reads both amorphized halves back and stacks them; it
    # consumes the ActivatedSlabs (both amorphized slabs) directly.
    structure = run_to_contract(
        lambda: stage_set.assemble(
            activated, shared, member, scratch_directory, comm),
        STRUCTURE_CONTRACT)

    # Steps 6-7: press then pull, over the rate ladder. The result is a
    # BondDebondResult (§9.1), not a bare trajectory.
    bond_debond = run_to_contract(
        lambda: stage_set.bond_debond(
            structure, member, scratch_directory, comm),
        BOND_DEBOND_CONTRACT)

    # The analyzer turns that into a measure vector (DESIGN.md §6); in
    # the skeleton only the mechanical measure is present, the rest
    # report `unresolved`.
    measures = run_to_contract(
        lambda: stage_set.analyze(structure, bond_debond, member),
        MEASURE_VECTOR_CONTRACT)

    # Step 8 characterization (DESIGN.md §8), MOCKED in the skeleton.
    characterization = run_to_contract(
        lambda: stage_set.characterize(structure, bond_debond, member),
        MEASURE_VECTOR_CONTRACT)
    measures = merge_measures(measures, characterization)

    # The gate READS the measure vector and REPORTS; in v1 it never acts
    # and never edits a measure (DESIGN.md §7).
    gate = evaluate_member_gates(measures, member)

    result = MemberResult(
        specification=member,
        potential=build_provenance(member),
        measures=measures,
        gate=gate,
        trusted=False)              # walking-skeleton plumbing (§5.3)
    emit_member(result)
    return result


def evaluate_member_gates(
        measures: MeasureVector,
        member: MemberSpecification) -> GateReport:
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
    missing = []
    for member_name in relation.members:
        result = results_by_name.get(member_name)
        if result is None:
            # A related member did not run — e.g. `--only` excluded it, or
            # a subset run. The relation is UNRESOLVED and reported, never
            # an exception (DESIGN.md §1.1, report never restrict).
            missing.append(member_name)
            values.append(None)
            trusted = False
            continue
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

    if missing:
        return RelationOutcome(
            kind=relation.kind, members=relation.members,
            value=None, unit="dimensionless", trusted=False,
            note=f"unresolved: related member(s) did not run: {missing}")

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
        "universal_model": provenance.universal_model,
        "production_weights": provenance.production_weights,
        "master_seed": provenance.master_seed,
        "protocol_fingerprint": provenance.protocol_fingerprint,
    }


def _verdicts_to_record(measures: MeasureVector) -> dict | None:
    """Serialize the vector's press Verdicts, or None if it carries none.

    The bond decision is read once by the §4 analyzer and rides the
    vector as its own field (not a measure), so it is emitted alongside
    the measures rather than folded into them.
    """
    verdicts = measures.verdicts
    if verdicts is None:
        return None
    return {
        "bonded": verdicts.bonded,
        "contact_quality": verdicts.contact_quality,
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
        "verdicts": _verdicts_to_record(result.measures),
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
