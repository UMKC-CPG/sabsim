"""The one ordered job registry (PSEUDOCODE.md §14.2, DESIGN.md §10.3).

A member's eight steps are prepared and run as THREE per-kind jobs —
``activate`` → ``bond`` → ``analyze`` (DESIGN.md §10.2) — submitted in
order with a human checkpoint between each. The real safeguard against
the two deployment commands drifting apart is that this set of jobs is
defined ONCE, here, as a small ordered table. Both the ``run`` selector's
flags (§14.3) and the ``prepare`` writer (§14.4) read from it, so the
truth about WHAT the jobs are and IN WHAT ORDER they run is never written
twice. Inserting a fourth kind later (say a relax between activate and
bond) is one entry here; the flags, the written filenames, and the
guided index all follow (DESIGN.md §10.3).

Each entry pins the CONTIGUOUS **sub-stage** of the §1 member chain a job
owns — a run of adjacent pipeline stages (its ``stages`` list): a section
of the whole stage sequence, not a piece of any one stage — and,
crucially, the on-disk artifact it READS at entry and WRITES at exit.
That file handoff (ARCHITECTURE.md §4.3) is exactly what lets a job
submitted on its own start mid-chain: it re-reads its entry artifact in a
fresh process rather than inheriting a warm object (§14.3, §14.6).
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------
# Artifact names — the LOGICAL handoff points between jobs (§14.2, §14.6).
# These name the mid-chain artifacts, not their on-disk filenames: what
# files a name maps to (a manifest plus any referenced payloads) is the
# §14.6 write_artifact/read_artifact concern, kept out of this data table.
# ---------------------------------------------------------------------

# The assembled facing pair the activate job writes and bond reads: the
# atoms (a LAMMPS data file) plus the labeled-group geometry bond cannot
# re-derive — z-ranges, interface plane, the measured activated skin
# (§14.6, DESIGN.md §2.6).
ASSEMBLED_PAIR = "assembled_pair"

# The press/pull result the bond job writes and analyze reads: each
# rung's reduced fields and curves, plus the press verdicts (§14.6).
PULL_RESULTS = "pull_results"

# The measure vector the analyze job writes — the §4 machine-readable
# schema the quality gate reads (DESIGN.md §6.6). The last artifact in
# the chain, so no later job reads it.
MEASURE_VECTOR = "measure_vector"

# The sentinel a job's ``reads`` carries when it starts from the study
# spec itself rather than a prior job's file — the activate job's entry
# (§14.2: ``reads = NONE``). Kept explicit so "starts from the spec" is
# stated, not signalled by an absent field.
FROM_SPEC = None


@dataclass(frozen=True)
class JobKind:
    """One kind of member job: its resource class, sub-stage, and handoffs.

    ``name`` is the job's verb (``"activate"`` / ``"bond"`` / ``"analyze"``),
    which is also the ``run`` flag and the generated script's semantic
    filename (no ordinal, DESIGN.md §10.5). ``resource_class`` is the
    abstract class a deployment rc resolves to a real partition
    (:meth:`sabsim.deploy.config.DeploymentConfig.partition_for`).

    ``stages`` names the pipeline operations this job runs — the adjacent
    stages that make up its sub-stage of the §1 chain — using the
    sequencer's stage-set method names
    (:class:`~sabsim.pipeline.skeleton_stages.StageSet`) for traceability
    to §14.2. It is DESCRIPTIVE, not the dispatcher: ``run_member_job``
    branches on ``name``, not by iterating this list. Each maps to the
    algorithm stage §14.2 lists (build→``build_slabs``,
    activate→``activate_surfaces``, assemble→``assemble_pair``;
    bond→press/settle/pull, all inside one ``bond_debond`` method;
    analyze→``run_analyzer`` with the mocked characterization merged in).

    ``reads`` is the artifact this job re-reads at entry (or
    :data:`FROM_SPEC` for the activate job, which starts from the spec),
    and ``writes`` is the artifact its final stage leaves for the NEXT
    job — the file handoff that makes a mid-chain start possible
    (ARCHITECTURE.md §4.3, §14.3).
    """

    name: str
    resource_class: str
    stages: tuple[str, ...]
    reads: str | None
    writes: str


# The ordered registry itself. Order is submission order — activate, then
# bond, then analyze — and it is the SINGLE source of that order (§10.3).
JOB_REGISTRY: tuple[JobKind, ...] = (
    JobKind(
        name="activate",
        # GPU by default: the universal-MLIP cascade runs on the GPU
        # (DESIGN.md §10.2/§4.7, revised 2026-08-08). The build/assemble
        # geometry rides along on the GPU node's CPU — cheap. A classical
        # CPU cascade is the deployment-expressed opt-in.
        resource_class="gpu",
        stages=("build", "activate", "assemble"),
        reads=FROM_SPEC,                 # starts from the study spec
        writes=ASSEMBLED_PAIR,
    ),
    JobKind(
        name="bond",
        resource_class="gpu",
        stages=("bond_debond",),         # press → settle → pull ladder
        reads=ASSEMBLED_PAIR,
        writes=PULL_RESULTS,
    ),
    JobKind(
        name="analyze",
        resource_class="cpu",
        stages=("analyze", "characterize"),
        reads=PULL_RESULTS,
        writes=MEASURE_VECTOR,
    ),
)


# The job names in submission order — a convenience for the CLI (which
# offers one mutually-exclusive flag per name) and the writer (which
# loops members × jobs in this order). Derived from the registry, never
# written down a second time (§10.3).
JOB_NAMES: tuple[str, ...] = tuple(job.name for job in JOB_REGISTRY)


def registry_lookup(job_name: str) -> JobKind:
    """Return the :class:`JobKind` for ``job_name``, or a loud stop.

    The ``run`` selector calls this with the one job flag it was given
    (§14.3). An unknown name — a flag no registry entry defines — is a
    clear error listing the valid names, never a silent miss, so a typo in
    a generated script fails readably rather than running the wrong
    sub-stage.
    """
    for job in JOB_REGISTRY:
        if job.name == job_name:
            return job
    raise KeyError(
        f"no job kind named '{job_name}' in the registry; the member "
        f"jobs are {list(JOB_NAMES)}")
