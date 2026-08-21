"""The deployment run selector — one job, or the whole chain (§14.3).

This is ``run`` and ``run_member_job`` made real: the line that lives
INSIDE each generated deployment script (`sabsim run <spec> --activate |
--bond | --analyze`). It runs within an allocation and submits nothing
itself (DESIGN.md §10.1); the human submits the scripts in order.

Giving NO job flag runs the whole member chain end to end — the existing
:func:`~sabsim.pipeline.sequencer.exec_full_study`, which also grades the
study's relations. Giving one flag runs exactly the contiguous sub-stage
of the §1 chain that :data:`~sabsim.deploy.registry.JOB_REGISTRY` assigns
to that job, and — the property that makes a separate submission possible —
it ENTERS by re-reading its ``reads`` artifact from the member scratch
rather than inheriting a warm in-memory object (§14.3, §14.6). Every
stage is routed through the SAME ``run_to_contract`` guard the whole-chain
run uses, so a bad artifact halts the job loudly (ARCHITECTURE.md §5.1).

Nothing here trains a potential or chooses a physics default. The force
model each job resolves is the ONE lookup every member does behind the §1
``resolve_potential`` seam — the classical stand-in today, the trained
committee once the bootstrap (a separate upstream process) produces one —
so the same three jobs run either, unchanged (DESIGN.md §1.2, §14).
"""

from __future__ import annotations

from dataclasses import dataclass

from sabsim.deploy.registry import (
    ASSEMBLED_PAIR,
    MEASURE_VECTOR,
    PULL_RESULTS,
    JobKind,
    registry_lookup,
)
from sabsim.deploy.scratch import member_scratch
from sabsim.pipeline.contracts import (
    ACTIVATED_SLABS_CONTRACT,
    BOND_DEBOND_CONTRACT,
    DERIVED_LATTICES_CONTRACT,
    MEASURE_VECTOR_CONTRACT,
    POTENTIAL_CONTRACT,
    SLABS_CONTRACT,
    STRUCTURE_CONTRACT,
    run_to_contract,
)
from sabsim.pipeline.exec_artifacts import MemberResult, build_provenance
from sabsim.pipeline.handoff import read_artifact, write_artifact
from sabsim.pipeline.measures import merge_measures
from sabsim.spec.loader import load_and_validate_study
from sabsim.spec.references import check_study_references


@dataclass(frozen=True)
class JobRunResult:
    """What ONE member job produced — its name and the artifact it wrote.

    A per-job submission does not return a study report (that is the
    whole-chain run's shape); it writes a hand-off artifact for the NEXT
    job and reports which one, so the human driving the submission knows
    the checkpoint landed and what to submit next (DESIGN.md §10.5).
    """

    member_name: str
    job_name: str
    artifact_written: str


def run(study_spec_path, job_directory, stage_set, comm=None,
        job_flag=None, only=None):
    """Run one member job across the study, or the whole chain (§14.3).

    ``job_flag`` is at most one of ``"activate"`` / ``"bond"`` /
    ``"analyze"``, or ``None`` for the whole member chain (§10.4). With no
    flag this delegates to :func:`~sabsim.pipeline.sequencer.exec_full_study`
    — every member end to end, then the declared relations — and returns
    its :class:`~sabsim.pipeline.exec_artifacts.StudyReport`. With a flag
    it runs that one job for each selected member and returns a tuple of
    :class:`JobRunResult`, one per member.

    ``only`` narrows a multi-member study to a subset BY NAME (the
    ``--only`` case); a name not in the study is a loud stop, never a
    silent no-op. ``stage_set`` selects the stub or live bodies and
    ``comm`` is the MPI communicator its engines use — the same two the
    sequencer threads.
    """
    if job_flag is None:
        # The whole-chain path is exactly the existing sequencer entry,
        # which also grades relations (§1); a per-job run never does.
        from sabsim.pipeline.sequencer import exec_full_study
        return exec_full_study(
            study_spec_path, job_directory, stage_set, comm, only=only)

    validated = load_and_validate_study(study_spec_path)
    # Phase-three reference check, the same one exec_full_study runs before
    # spending node-hours (DESIGN.md §1.5): the spec is executable in
    # principle, but does everything it points at exist?
    check_study_references(validated)
    job = registry_lookup(job_flag)

    return tuple(
        run_member_job(
            member,
            member_scratch(job_directory, validated.name, member.name),
            job, stage_set, comm)
        for member in _select_members(validated, only))


def run_member_job(member, scratch_directory, job: JobKind,
                   stage_set, comm=None) -> JobRunResult:
    """Run ONE job's contiguous sub-stage of the §1 chain, one member (§14.3).

    The job ENTERS by re-reading its ``reads`` artifact from the member
    scratch (or from the spec itself, for the activate job) and EXITS by
    writing its ``writes`` artifact there for the next job to read — the
    file hand-off (ARCHITECTURE.md §4.3) that lets this process need NONE
    of the stages before it. Each stage is guarded by ``run_to_contract``
    exactly as the whole-chain run guards it, so a bad artifact halts here.

    The three sub-stages reuse the sequencer's own stage calls (§1),
    differing only in that they start from ``scratch``'s artifact rather
    than the previous in-memory handle. The potential is the lookup
    every job does (``resolve_potential``): classical stand-in now,
    trained committee later, the SAME seam.
    """
    potential = run_to_contract(
        lambda: stage_set.resolve_potential(member), POTENTIAL_CONTRACT)

    if job.name == "activate":
        # Starts from the spec (reads = NONE): derive the working lattice
        # (step 2b, DESIGN.md §2.2) under the current model, build both
        # halves, activate each surface, assemble the pair — then write
        # the pair for bond. The whole-chain sequencer runs derive_lattices
        # before build; this per-job path MUST do the same, or build
        # receives the scratch directory in the DerivedLattices slot and
        # fails (the regression when step 2b was wired, commit cf92d30).
        derived_lattices = run_to_contract(
            lambda: stage_set.derive_lattices(
                member, potential, scratch_directory, comm),
            DERIVED_LATTICES_CONTRACT)
        handle_a, handle_b, shared = run_to_contract(
            lambda: stage_set.build(
                member, potential, derived_lattices, scratch_directory,
                comm),
            SLABS_CONTRACT)
        activated = run_to_contract(
            lambda: stage_set.activate(
                handle_a, handle_b, member, potential,
                scratch_directory, comm),
            ACTIVATED_SLABS_CONTRACT)
        structure = run_to_contract(
            lambda: stage_set.assemble(
                activated, shared, member, scratch_directory, comm),
            STRUCTURE_CONTRACT)
        _publish(comm, lambda: write_artifact(
            scratch_directory, ASSEMBLED_PAIR, structure))
        return JobRunResult(member.name, job.name, ASSEMBLED_PAIR)

    if job.name == "bond":
        # Re-reads the assembled pair, presses/settles/pulls, and writes
        # the pull results for analyze. No stage before it runs here.
        structure = read_artifact(scratch_directory, ASSEMBLED_PAIR)
        bond_debond = run_to_contract(
            lambda: stage_set.bond_debond(
                structure, potential, member, scratch_directory, comm),
            BOND_DEBOND_CONTRACT)
        _publish(comm, lambda: write_artifact(
            scratch_directory, PULL_RESULTS, bond_debond))
        return JobRunResult(member.name, job.name, PULL_RESULTS)

    if job.name == "analyze":
        # Reads the pull results (its ``reads`` artifact) AND re-reads the
        # earlier assembled pair from the same member scratch, because the
        # measure needs the interface geometry the pull result does not
        # carry (run_analyzer reads structure.built's cell). Both artifacts
        # persist in the one member scratch, so this is a plain re-read.
        structure = read_artifact(scratch_directory, ASSEMBLED_PAIR)
        bond_debond = read_artifact(scratch_directory, PULL_RESULTS)
        measures = run_to_contract(
            lambda: stage_set.analyze(structure, bond_debond, member),
            MEASURE_VECTOR_CONTRACT)
        characterization = run_to_contract(
            lambda: stage_set.characterize(structure, bond_debond, member),
            MEASURE_VECTOR_CONTRACT)
        measures = merge_measures(measures, characterization)
        # The gate READS the vector and REPORTS; in v1 it never acts (§7).
        from sabsim.pipeline.sequencer import evaluate_member_gates
        gate = evaluate_member_gates(measures, member, potential)
        result = MemberResult(
            specification=member,
            potential=build_provenance(potential, member),
            measures=measures, gate=gate, trusted=False)
        _publish(comm, lambda: write_artifact(
            scratch_directory, MEASURE_VECTOR, result))
        return JobRunResult(member.name, job.name, MEASURE_VECTOR)

    raise ValueError(
        f"run_member_job does not know job kind '{job.name}'; the "
        f"registry defines {[j for j in ('activate', 'bond', 'analyze')]}")


def _select_members(validated, only):
    """Return the members to run, honouring ``--only`` (§14.3).

    ``only`` is None (every member) or an iterable of names; a name the
    study does not define is a loud stop, matching exec_full_study so the
    two entry points reject the same way.
    """
    members = validated.members
    if only is None:
        return members
    wanted = set(only)
    present = {member.name for member in members}
    missing = wanted - present
    if missing:
        raise ValueError(
            f"--only names members not in the study: {sorted(missing)}; "
            f"the study has {sorted(present)}")
    return tuple(m for m in members if m.name in wanted)


def _publish(comm, write_action) -> None:
    """Run a WRITE on the primary rank, then publish it with a barrier.

    A hand-off artifact must be written by exactly ONE rank and be visible
    to every rank before any of them proceeds (the §4.1 serial-IO
    discipline the live stages already follow). With no communicator
    (a W0 or single-process run) the write is plain. The read side needs
    no such guard — every rank reads the finished file for itself.
    """
    if comm is None:
        write_action()
        return
    if comm.Get_rank() == 0:
        write_action()
    comm.Barrier()
