"""The deployment run selector — one job, or the whole chain (§14.3).

This is ``run`` and ``run_pair_job`` made real: the line that lives
INSIDE each generated deployment script (``sabsim run <spec>
--prep-surf1 | --prep-surf2 | --bond | --analysis``). It runs within an
allocation and submits nothing itself (DESIGN.md §10.1); the human
submits the scripts in the order the guide gives.

Giving NO job flag runs the whole pair chain end to end — the
sequencer's :func:`~sabsim.pipeline.sequencer.exec_full_project`.
Giving one flag runs exactly the stage that
:data:`~sabsim.deploy.registry.JOB_REGISTRY` assigns to that job, and —
the property that makes a separate submission possible — it ENTERS by
re-reading the earlier stages' deliverables from their stage folders in
the project rather than inheriting a warm in-memory object (§14.3,
§14.6). The per-job path and the whole-chain path call the SAME stage
functions in the sequencer, so they cannot drift apart; every stage is
routed through the same ``run_to_contract`` guard, so a bad artifact
halts the job loudly (ARCHITECTURE.md §5.1).

Nothing here trains a potential or chooses a physics default. Which
force models a pair runs under is written in its project file (the
``[potential]`` block, DESIGN.md §1.6) and read by each stage from
``pair.potential``; the trained committee the bootstrap (a separate
upstream process) will produce drops in there, so the same four jobs
run either, unchanged (DESIGN.md §1.2, §14).
"""

from __future__ import annotations

from dataclasses import dataclass

from sabsim.deploy.registry import (
    JOB_NAMES,
    JobKind,
    registry_lookup,
)
from sabsim.pipeline.sequencer import (
    analysis_stage,
    bond_stage,
    exec_full_project,
    prep_stage,
)
from sabsim.spec.loader import load_and_validate_project
from sabsim.spec.records import Project, stage_folders
from sabsim.spec.references import check_project_references

# The wafer tags, inlined so this module stays free of the slab builder's
# pymatgen import (WAFER_A_TAG / WAFER_B_TAG in structure.slab_builder).
_WAFER_A_TAG = 1
_WAFER_B_TAG = 2


@dataclass(frozen=True)
class JobRunResult:
    """What ONE pair job produced — its name and where it left its work.

    A per-job submission does not return a project report (that is the
    whole-chain run's shape); it writes a deliverable for the NEXT job
    into its own stage folder and reports which one, so the human
    driving the submission knows the checkpoint landed and what to
    submit next (DESIGN.md §10.5).
    """

    pair_label: str
    job_name: str
    artifact_written: str
    deliverable_directory: str


def run(project_spec_path, project_directory, stage_set, comm=None,
        job_flag=None):
    """Run one pair job, or the whole chain (§14.3).

    ``job_flag`` is at most one of the registry's job names
    (``"prep_surf1"`` / ``"prep_surf2"`` / ``"bond"`` / ``"analysis"``),
    or ``None`` for the whole chain (§10.4). With no flag this delegates
    to :func:`~sabsim.pipeline.sequencer.exec_full_project` and returns
    its :class:`~sabsim.pipeline.exec_artifacts.ProjectReport`. With a
    flag it runs that one job and returns a :class:`JobRunResult`.

    ``project_directory`` is the project folder (None = the folder the
    project file was read from); ``stage_set`` selects the stub or live
    bodies and ``comm`` is the MPI communicator its engines use — the
    same two the sequencer threads.
    """
    if job_flag is None:
        return exec_full_project(
            project_spec_path, project_directory, stage_set, comm)

    project = load_and_validate_project(project_spec_path)
    if project_directory is not None:
        project = Project(
            description=project.description, pair=project.pair,
            project_directory=str(project_directory))
    # Phase-three reference check, the same one exec_full_project runs
    # before spending node-hours (DESIGN.md §1.5): the file is executable
    # in principle, but does everything it points at exist? A job is
    # held only to the environment libraries IT opens (§10.2,
    # 2026-09-28): a prep job its own surface's, bond and analysis none.
    job = registry_lookup(job_flag)
    check_project_references(
        project, libraries_needed=libraries_a_job_opens(job))
    return run_pair_job(project, job, stage_set, comm)


# Which wafer's environment library each prep job opens, by the stage
# folder the job fills (DESIGN §10.2). Any other job opens none.
_LIBRARY_ROLE_OF_PREP_FOLDER = {
    "prep_surf1": "wafer_a",
    "prep_surf2": "wafer_b",
}


def libraries_a_job_opens(job: JobKind) -> tuple:
    """The wafer roles whose environment library this job will open.

    The surface 1 prep opens wafer A's library and the surface 2 prep
    wafer B's, each to judge its own healed half at the §3.5 gate; the
    bond and analysis jobs open neither. Holding a job to a library it
    never reads tied the two surfaces together for no physical reason
    (LEDGER T-45).
    """
    role = _LIBRARY_ROLE_OF_PREP_FOLDER.get(job.folder_key)
    return (role,) if role is not None else ()


def run_pair_job(project: Project, job: JobKind, stage_set,
                 comm=None) -> JobRunResult:
    """Run ONE job's stage of the §1 chain for the project's pair (§14.3).

    The job ENTERS by re-reading the earlier stages' deliverables from
    their stage folders (or from the project file itself, for a prep
    job) and EXITS by writing its own deliverable into its stage folder
    for the next job to read — the file hand-off (ARCHITECTURE.md §4.3)
    that lets this process need NONE of the stages before it. The stage
    bodies are the sequencer's own (:mod:`sabsim.pipeline.sequencer`),
    so a per-job run and a whole-chain run do the identical work.
    """
    pair = project.pair
    folders = stage_folders(pair)
    home = project.project_directory
    if job.name == "prep_surf1":
        written = prep_stage(pair, _WAFER_A_TAG, home, folders,
                             stage_set, comm)
    elif job.name == "prep_surf2":
        written = prep_stage(pair, _WAFER_B_TAG, home, folders,
                             stage_set, comm)
    elif job.name == "bond":
        written = bond_stage(pair, home, folders, stage_set, comm)
    elif job.name == "analysis":
        analysis_stage(pair, home, folders, stage_set, comm)
        from sabsim.deploy.scratch import deliverable_directory
        written = str(deliverable_directory(home, folders.analysis))
    else:
        raise ValueError(
            f"run_pair_job does not know job kind '{job.name}'; the "
            f"registry defines {list(JOB_NAMES)}")
    return JobRunResult(
        pair_label=pair.pair_label, job_name=job.name,
        artifact_written=job.writes, deliverable_directory=written)
