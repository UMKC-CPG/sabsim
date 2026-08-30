"""The one ordered job registry (PSEUDOCODE.md §14.2, DESIGN.md §10.3).

A project is ONE wafer pair, and its work is prepared and run as FOUR
jobs — one per STAGE FOLDER of the project (ARCHITECTURE.md §1, revised
2026-08-30 (Paul)): ``prep_surf1`` and ``prep_surf2`` prepare the two
surfaces independently (each builds its own half in the shared cell,
bombards it, heals it, and gates it), ``bond`` brings the two halves
together and presses, settles and pulls them apart, and ``analysis``
reduces the pull into the measure vector. The real safeguard against
the two deployment commands drifting apart is that this set of jobs is
defined ONCE, here, as a small ordered table. Both the ``run``
selector's flags (§14.3) and the ``prepare`` writer (§14.4) read from
it, so the truth about WHAT the jobs are, IN WHAT ORDER they run, and
WHICH may run side by side is never written twice. Inserting a fifth
kind later (say a relax between the preps and bond) is one entry here;
the flags, the written filenames, and the guided index all follow
(DESIGN.md §10.3).

Each entry pins the CONTIGUOUS **sub-stage** of the §1 pair chain a job
owns — a run of adjacent pipeline stages (its ``stages`` list): a
section of the whole stage sequence, not a piece of any one stage —
and, crucially, the on-disk artifacts it READS at entry and WRITES at
exit, each named together with the STAGE FOLDER that holds it. That
file handoff (ARCHITECTURE.md §4.3) is exactly what lets a job
submitted on its own start mid-chain: it re-reads its entry artifacts
in a fresh process rather than inheriting a warm object (§14.3, §14.6).
The two prep jobs read nothing and depend on nothing, which is what
lets the scheduler run them at once — the ARCHITECTURE.md §4.3
"Approach C" fan-out, arriving for free through the files.
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------
# Artifact names — the LOGICAL handoff points between jobs (§14.2, §14.6).
# These name the mid-chain artifacts, not their on-disk filenames: what
# files a name maps to (a manifest plus any referenced payloads) is the
# §14.6 write_artifact/read_artifact concern, kept out of this data table.
# ---------------------------------------------------------------------

# The healed, gated half a prep job writes into ITS OWN prep folder and
# the bond job reads from BOTH prep folders: the atoms (a LAMMPS data
# file) plus the manifest bond cannot re-derive — which wafer it is, the
# shared cell it was built in, the heal step and the gate verdict
# (§14.6, DESIGN.md §10.2, revised 2026-08-30).
ACTIVATED_HALF = "activated_half"

# The assembled facing pair — bond's INTERNAL record after it has read
# both halves, checked that their shared cells agree and stacked them
# (§14.6, DESIGN.md §2.6). Kept as a named artifact because the
# whole-chain sequencer and the resume path still hand it across a
# seam; no JOB reads it from another job any more.
ASSEMBLED_PAIR = "assembled_pair"

# The press/pull result the bond job writes and analysis reads: each
# rung's reduced fields and curves, plus the press verdicts (§14.6).
PULL_RESULTS = "pull_results"

# The measure vector the analysis job writes — the §4 machine-readable
# schema the quality gate reads (DESIGN.md §6.6). The last artifact in
# the chain, so no later job reads it.
MEASURE_VECTOR = "measure_vector"


# ---------------------------------------------------------------------
# Stage-folder KEYS. A job names WHICH of the project's four stage
# folders it fills by the attribute name on the spec layer's
# ``StageFolders`` record (``stage_folders(pair)``, PSEUDOCODE.md §2), so
# the registry stays a pure data table that never spells a folder name
# — the folder names carry the wafers' material labels and are the spec
# layer's to derive. ``JobKind.folder`` turns the key into the name.
# ---------------------------------------------------------------------
PREP_SURF1_FOLDER = "prep_surf1"
PREP_SURF2_FOLDER = "prep_surf2"
BOND_FOLDER = "bond"
ANALYSIS_FOLDER = "analysis"


@dataclass(frozen=True)
class JobKind:
    """One kind of pair job: its usage, sub-stage, folder, and handoffs.

    ``name`` is the job's verb (``"prep_surf1"`` / ``"prep_surf2"`` /
    ``"bond"`` / ``"analysis"``); the ``run`` flag is that name with
    underscores turned into dashes (``--prep-surf1``), and the generated
    script's filename is the stage folder's own name (no ordinal,
    DESIGN.md §10.5, §14.5).

    ``usage_key`` names the ``[usage.*]`` block of the deployment rc
    that says how this kind of job runs: ``"prep"`` for BOTH prep jobs
    (the two surfaces want the same hardware), else the job's own name.
    ``resource_class`` is the abstract class that block is EXPECTED to
    route to (``"gpu"`` / ``"cpu"``) — descriptive, so a reader of this
    table sees the design intent (DESIGN.md §10.2); the rc's own
    ``partition`` key is what actually routes.

    ``folder_key`` names WHICH stage folder this job fills, as an
    attribute of the spec layer's ``StageFolders`` record; :meth:`folder`
    resolves it to the folder's name for one pair. Deliverables land in
    ``<project>/<folder>/`` and bulk in ``intermediate/<folder>/``
    (§14.3).

    ``stages`` names the pipeline operations this job runs — the
    adjacent stages that make up its sub-stage of the §1 chain — using
    the sequencer's stage-set method names for traceability to §14.2.
    It is DESCRIPTIVE, not the dispatcher: ``run_pair_job`` branches on
    ``name``, not by iterating this list.

    ``reads`` lists the artifacts this job re-reads at entry as
    ``(folder_key, artifact name)`` pairs — EMPTY for a prep job, which
    starts from the project file — and ``writes`` is the artifact its
    final stage leaves in ITS OWN folder for a later job: the file
    handoff that makes a mid-chain start possible (ARCHITECTURE.md
    §4.3, §14.3). ``depends_on`` lists the job names that must have
    FINISHED first; empty for both preps, which is what lets them run
    side by side.
    """

    name: str
    usage_key: str
    resource_class: str
    folder_key: str
    stages: tuple[str, ...]
    reads: tuple[tuple[str, str], ...]
    writes: str
    depends_on: tuple[str, ...]

    @property
    def flag(self) -> str:
        """The ``sabsim run`` flag for this job, e.g. ``--prep-surf1``.

        Spelled from the name in ONE place so the CLI parser and the
        writer's run line agree by construction (§10.3).
        """
        return "--" + self.name.replace("_", "-")

    def folder(self, folders) -> str:
        """The NAME of the stage folder this job fills, for one pair.

        ``folders`` is the spec layer's ``StageFolders`` record
        (``stage_folders(pair)``, PSEUDOCODE.md §2), whose attributes
        are the four folder names; this job's ``folder_key`` picks one.
        The script that runs this job carries the same name as the
        folder it fills (§14.4), so one name per stage is all a reader
        of the project folder ever sees.
        """
        return getattr(folders, self.folder_key)


# The ordered registry itself. Order is the SUBMISSION order — the two
# preps (in either order, or together), then bond, then analysis — and
# it is the SINGLE source of that order (§10.3).
JOB_REGISTRY: tuple[JobKind, ...] = (
    JobKind(
        name="prep_surf1",
        usage_key="prep",
        # GPU: the universal-MLIP cascade runs on the GPU (DESIGN.md
        # §10.2/§4.7). The build geometry rides along on the GPU node's
        # CPU — cheap.
        resource_class="gpu",
        folder_key=PREP_SURF1_FOLDER,
        stages=("build", "activate"),      # wafer A only, then heal+gate
        reads=(),                          # starts from the project file
        writes=ACTIVATED_HALF,
        depends_on=(),
    ),
    JobKind(
        name="prep_surf2",
        usage_key="prep",
        resource_class="gpu",
        folder_key=PREP_SURF2_FOLDER,
        stages=("build", "activate"),      # wafer B only, then heal+gate
        reads=(),
        writes=ACTIVATED_HALF,
        depends_on=(),                     # INDEPENDENT of prep_surf1
    ),
    JobKind(
        name="bond",
        usage_key="bond",
        resource_class="gpu",
        folder_key=BOND_FOLDER,
        # assemble (checks the two shared cells agree), then the one-time
        # cell relax, press, settle, and the pull ladder — the committee
        # in one process.
        stages=("assemble", "bond_debond"),
        reads=((PREP_SURF1_FOLDER, ACTIVATED_HALF),
               (PREP_SURF2_FOLDER, ACTIVATED_HALF)),
        writes=PULL_RESULTS,
        depends_on=("prep_surf1", "prep_surf2"),
    ),
    JobKind(
        name="analysis",
        usage_key="analysis",
        resource_class="cpu",
        folder_key=ANALYSIS_FOLDER,
        stages=("analyze", "characterize"),
        reads=((BOND_FOLDER, PULL_RESULTS),),
        writes=MEASURE_VECTOR,
        depends_on=("bond",),
    ),
)


# The job names in submission order — a convenience for the CLI (which
# offers one mutually-exclusive flag per name) and the writer (which
# loops the jobs in this order). Derived from the registry, never
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
        f"no job kind named '{job_name}' in the registry; the pair "
        f"jobs are {list(JOB_NAMES)}")


def jobs_depending_on(job_name: str) -> tuple[JobKind, ...]:
    """The jobs that list ``job_name`` among what must finish first.

    Read off the registry (§10.3), so the writer's "submit next" hint
    and the guide's dependency lines follow an inserted job for free.
    Returns an empty tuple for the last job in the chain.
    """
    return tuple(job for job in JOB_REGISTRY if job_name in job.depends_on)
