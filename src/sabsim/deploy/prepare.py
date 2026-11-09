"""The `sabsim prepare` writer (PSEUDOCODE.md §14.4, §14.5; DESIGN §10).

`prepare` is the WRITER of the deployment consumer (`submit` is the
hand, :mod:`sabsim.deploy.submit`; `run` is the executor,
:mod:`sabsim.pipeline.pair_jobs`). It reads BOTH inputs — the project
file (one wafer pair) and the machine-local deployment rc — and emits
one ready-to-submit script per job of the registry
(:mod:`sabsim.deploy.registry`: the two surface preparations, the
bond, the analysis) plus a submission guide. It **submits nothing**
(§10.1): a long-lived submit-and-watch process cannot sit on a login
node, so the person hands the scripts over — with `sabsim submit`
(§10.12), which the guide and every "what next" line name first, or
by typing the guide's `sbatch` lines — and inspects each gate before
the next.

The scripts are named after the STAGE FOLDERS they fill (ARCHITECTURE §1,
revised 2026-08-30): ``prep_surf1_si.slurm`` runs the job whose deliverables
land in ``prep_surf1_si/`` and whose bulk lands in
``intermediate/prep_surf1_si/``, so a reader of the project folder sees
ONE name per stage. `prepare` also makes the four stage folders if they
do not exist yet, never touching one that does — a prep folder may
already hold a prepared surface's recipe and environment library.

Because it runs on the login node, it must FAIL THERE, readably — an
unset root or a walltime over its partition ceiling stops here with a
clear message, rather than a script that dies on a compute node an hour
into a job (§10.5, §10.6).

The generated script is deliberately LEAN (§10.5, the (A) faithful form):
scheduler directives, the module lines, the three roots baked in as a
frozen snapshot, and the `sabsim run` line — and nothing else. The Python
interpreter, the launcher, and the potential files come from the
ACTIVATED INSTALL (the sourced ``.sabsim/sabsimrc`` + the installed
package), so they are not hand-named in every script.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from sabsim.deploy.config import (
    DeploymentConfig,
    DeploymentError,
    Partition,
    UsageBlock,
    load_deployment,
)
from sabsim.deploy.registry import (
    JOB_REGISTRY,
    JobKind,
    jobs_depending_on,
    registry_lookup,
)
from sabsim.deploy.init_project import RECIPE_FILENAME
from sabsim.deploy.roots import LocationRoots, resolve_location_roots
from sabsim.driver.environment_library import LIBRARY_MANIFEST_FILE
from sabsim.spec.loader import load_and_validate_project
from sabsim.spec.records import stage_folders

# The submission guide's filename — a descriptively named guided index
# dropped beside the scripts (§10.5: a submission GUIDE, never `index` or
# `readme`).
GUIDE_FILENAME = "SUBMISSION_GUIDE.md"

# The generated scripts' extension.
SCRIPT_EXTENSION = ".slurm"
# A surface's environment-library build is named after its prep folder
# plus this suffix: `prep_surf1_si.library.slurm` (§10.2, 2026-09-10).
LIBRARY_SUFFIX = ".library"


@dataclass(frozen=True)
class SubmissionEntry:
    """One prepared job: which job, which stage folder, which script.

    The ORDER of these entries IS the submission order (§10.5) — the guide
    and the returned tuple both preserve it, so a human (or a test) reads
    the sequence off one list, never a filename ordinal. ``depends_on``
    repeats the registry's dependency list by job name so the guide can
    be rendered from the entries alone.
    """

    job_name: str
    stage_folder: str
    script_name: str
    depends_on: tuple[str, ...]


# A surface's library build is named `library_surf<n>` in the guide and
# in `submit`'s job list (§10.2 step 0); the prefix is spelled once.
LIBRARY_JOB_PREFIX = "library_surf"


def library_job_name(surface_number: int) -> str:
    """The guide's name for surface ``surface_number``'s library build."""
    return f"{LIBRARY_JOB_PREFIX}{surface_number}"


def library_surface_number(job_name: str) -> int | None:
    """Which surface a library-build job name belongs to, else None.

    ``library_surf1`` -> 1, ``library_surf2`` -> 2; a pair job's name
    (``bond``) is not a library build and yields None.
    """
    if not job_name.startswith(LIBRARY_JOB_PREFIX):
        return None
    return int(job_name[len(LIBRARY_JOB_PREFIX):])


def submission_entries(folders) -> tuple[SubmissionEntry, ...]:
    """The guide's job list: every script, in submission order (§10.5).

    This is the ONE statement of what a project submits and what each
    submission waits on, read by both `prepare` (which renders a script
    per entry and prints the guide from them) and `submit` (which hands
    the scripts to the scheduler, §10.12). First the two library builds
    — step 0 of §10.2, one per surface, independent of everything —
    then the registry's jobs in its order, each prep job holding on its
    own surface's library build as well as on whatever the registry
    says. ``folders`` is the pair's ``StageFolders`` record, which names
    the stage folders and so the scripts.
    """
    entries = []
    library_names = {}
    for surface_number, prep_folder in ((1, folders.prep_surf1),
                                        (2, folders.prep_surf2)):
        name = library_job_name(surface_number)
        library_names[f"prep_surf{surface_number}"] = name
        entries.append(SubmissionEntry(
            job_name=name, stage_folder=prep_folder,
            script_name=_semantic_name(_library_stem(prep_folder)),
            depends_on=()))
    for job in JOB_REGISTRY:
        stage_folder = job.folder(folders)
        depends_on = job.depends_on
        if job.name in library_names:
            depends_on = (library_names[job.name], *job.depends_on)
        entries.append(SubmissionEntry(
            job_name=job.name, stage_folder=stage_folder,
            script_name=_semantic_name(stage_folder),
            depends_on=depends_on))
    return tuple(entries)


def prepare(project_spec_path, deployment_rc_path,
            project_directory=None,
            dump_visuals: bool = True) -> tuple[SubmissionEntry, ...]:
    """Write one script per job plus a guide, into the project (§14.4).

    ``project_directory`` is where the scripts, the guide and the four
    stage folders are made AND the run's home (each script ``cd``s there
    before launching, matching the CLI's CWD-is-home rule, §14.3). It
    defaults to the folder holding the project file, which is where a
    project's things belong (ARCHITECTURE §1); a test may point it
    elsewhere. Returns the submission entries in order; also drops the
    guide beside the scripts. Raises
    :class:`~sabsim.deploy.config.DeploymentError` on the login-node gates
    (unset root, walltime over ceiling) before writing anything.

    ``dump_visuals`` (the default) puts ``--dump-visuals`` on every
    generated run line, so each dynamic stage (cascade, press, settle, pull)
    records a trajectory for viewing — the standing rule that a dynamic run
    leaves a movie behind as its evidence; ``False`` writes
    ``--no-dump-visuals`` instead.
    """
    # The roots gate FIRST (§10.5): resolve the three location roots, or
    # stop on the login node naming the missing one — before any file is
    # written, so a misconfigured environment fails cleanly.
    roots = resolve_location_roots()

    deployment = load_deployment(deployment_rc_path)
    validated = load_and_validate_project(project_spec_path)
    spec_path = os.path.abspath(project_spec_path)
    if project_directory is None:
        project_directory = validated.project_directory
    project_directory = Path(project_directory)
    folders = stage_folders(validated.pair)

    # Validate every job against its walltime and GPU ceilings BEFORE
    # writing any script, so a bad walltime does not leave a half-written
    # set of scripts behind (§10.6, the cheap checks).
    for job in JOB_REGISTRY:
        usage, partition = _resolve_usage_and_partition(deployment, job)
        _check_walltime_ceiling(job, usage, partition)
        _check_gpu_ceiling(job, usage, partition)

    # The submission order and dependency graph come from ONE place
    # (`submission_entries`), shared with `sabsim submit` (§10.12), so
    # the guide and the submitter can never disagree about what is
    # held on what. Here each entry is rendered into its script.
    entries = submission_entries(folders)
    prep_usage, prep_partition = _resolve_usage_and_partition(
        deployment, registry_lookup("prep_surf1"))
    for entry in entries:
        # The stage folder itself: made if absent, left alone if present
        # (a prep folder may already hold its recipe and library).
        (project_directory / entry.stage_folder).mkdir(
            parents=True, exist_ok=True)
        surface_number = library_surface_number(entry.job_name)
        if surface_number is not None:
            # Step 0 (§10.2, 2026-09-10): a surface's environment-library
            # build, from the prep usage block, NOT a registry job — it
            # runs on the bootstrap's clock.
            script = render_library_script(
                validated, surface_number, prep_usage, prep_partition,
                deployment, roots, project_directory)
        else:
            job = registry_lookup(entry.job_name)
            usage, partition = _resolve_usage_and_partition(deployment, job)
            script = render_job_script(
                validated, job, usage, partition, deployment, roots,
                spec_path, project_directory, dump_visuals=dump_visuals)
        _write_script(project_directory / entry.script_name, script)

    _write_guide(project_directory, validated, tuple(entries))
    return tuple(entries)


def render_job_script(
        project, job: JobKind, usage: UsageBlock, partition: Partition,
        deployment: DeploymentConfig, roots: LocationRoots,
        spec_path: str, project_directory: Path,
        dump_visuals: bool = False) -> str:
    """Render one job's submission script — the lean §10.5 form (§14.5).

    In order (§14.5): scheduler directives from the partition/usage/
    account; the ``module use`` roots then the ``module load`` list; the
    three roots baked in as frozen values; the launcher + ``sabsim run``
    line inside the allocation; and a success line naming what to check
    and the next job to submit. The deepmd ``plugin load`` is NOT here —
    the bond job's LAMMPS input issues it (ARCHITECTURE.md §4.4); this only
    loads the module that exports its path.

    The scheduler job NAME is the stage folder's name, so ``squeue``
    reads like the project folder does (§14.5).
    """
    folders = stage_folders(project.pair)
    stem = job.folder(folders)
    lines = _script_header(
        stem, [f"# {stem} — the {job.name} job of this project.",
               "# Generated by `sabsim prepare` (DESIGN §10). Deliverables "
               "land",
               "# in the folder of the same name",
               "# beside this script; bulk output under intermediate/ "
               "(§10.8)."],
        usage, partition, deployment, roots, project_directory)

    # (4) The run's home is the PROJECT folder (CWD, §14.3), then the
    # launcher INSIDE the allocation (§4.1) — python + mpirun on PATH from
    # the activated install.
    lines += [
        "# The run's home is the project folder (the CLI takes CWD), so",
        "# relative paths mean the same thing whichever folder you submit",
        "# from (§14.5).",
        f'cd "{project_directory}"',
        "",
        *_launch_lines(),
        f'srun --mpi=pmix -n "${{SLURM_NTASKS}}" python -m sabsim run \\',
        f'    {spec_path} {job.flag}'
        + (" --dump-visuals" if dump_visuals else " --no-dump-visuals"),
        "",
    ]

    # (5) On success, what to check and the next job to submit (§10.5),
    # reinforcing the guide. The "next" is read off the registry's
    # dependency lists, so an inserted job carries the hint for free.
    lines.append(_success_line(job, folders))

    return "\n".join(lines) + "\n"


def render_library_script(
        project, surface_number: int, usage: UsageBlock,
        partition: Partition, deployment: DeploymentConfig,
        roots: LocationRoots, project_directory: Path) -> str:
    """Render one surface's environment-library build (§10.2, 2026-09-10).

    The same header as a pair job (directives from the prep usage
    block, modules, frozen roots, per-kind environment), then a run
    line that is NOT ``sabsim run``: the bootstrap's own
    ``generate --skip-collection2``, with the PREP FOLDER as its home,
    because that is where the recipe is and where the library must
    land for the gate to find it (ARCHITECTURE §1). The build refuses
    to overwrite a library already there — the deliverable is precious
    (§10.8) — and exits successfully at once, so the guide's chained
    form can always include it: a second submission of the chain
    costs seconds here, and a person who changed the recipe moves the
    old library aside first.
    """
    folders = stage_folders(project.pair)
    prep_folder = (folders.prep_surf1 if surface_number == 1
                   else folders.prep_surf2)
    stem = _library_stem(prep_folder)
    prep_directory = project_directory / prep_folder
    # The prep job this build feeds: what its success line says to
    # submit next.
    prep_job = registry_lookup(f"prep_surf{surface_number}")
    lines = _script_header(
        stem, [f"# {stem} — build surface {surface_number}'s ENVIRONMENT "
               f"LIBRARY (DESIGN §3.5),",
               f"# from the recipe in {prep_folder}/, into that folder. "
               "Step 0 of the",
               "# guide: once per recipe, on the bootstrap's clock, not a "
               "job of the",
               "# pair chain (DESIGN §10.2). Generated by `sabsim "
               "prepare`."],
        usage, partition, deployment, roots, project_directory)
    lines += [
        "# The bootstrap's home is the PREP folder: the recipe is read",
        "# there and the library is written there (ARCHITECTURE §1).",
        f'cd "{prep_directory}"',
        "",
        "# Never overwrite a library (§10.8). To rebuild after changing",
        "# the recipe, move environment_library.toml and .npz aside.",
        f'if [ -f "{LIBRARY_MANIFEST_FILE}" ]; then',
        f'    echo "{stem}: {prep_folder}/{LIBRARY_MANIFEST_FILE} is '
        f'already there; left untouched."',
        "    exit 0",
        "fi",
        "",
        *_launch_lines(),
        'srun --mpi=pmix -n "${SLURM_NTASKS}" python -m sabsim bootstrap '
        "generate \\",
        f"    {RECIPE_FILENAME} --skip-collection2",
        "",
        f'echo "{stem} done. Check the self-check numbers in '
        f'{prep_folder}/{LIBRARY_MANIFEST_FILE}. Next, unless already '
        f'queued: {_next_submission(prep_job, folders)}"',
    ]
    return "\n".join(lines) + "\n"


def _next_submission(job: JobKind, folders) -> str:
    """How a printed hint names the next job to hand to the scheduler.

    The `sabsim submit` line first (§10.12) — it is what a person
    types — then the bare ``sbatch`` line it stands for, so the hint
    still names the script and still works by hand. No backticks: the
    text sits inside a script's double-quoted ``echo``, where a
    backtick would run the words between as a command.
    """
    script = _semantic_name(job.folder(folders))
    return (f"sabsim submit {job.submit_word} "
            f"(by hand: sbatch {script})")


def _library_stem(prep_folder: str) -> str:
    """``<prep folder>.library`` — the library build's name and file stem."""
    return f"{prep_folder}{LIBRARY_SUFFIX}"


def _launch_lines() -> list:
    """The launcher preamble every generated script shares (§4.1)."""
    return [
        "# Launch inside the allocation (§4.1). `srun --mpi=pmix` is the",
        "# primary launcher (§4.1), NOT mpirun: mpirun's remote daemon does",
        "# not preserve the venv on other nodes, so a remote rank falls back",
        "# to the conda-env python that lacks the editable sabsim (diagnosed",
        "# job 15697153); srun carries the activated venv to every node. The",
        "# allocation also exports SLURM_MEM_PER_NODE/_CPU/_GPU as mutually",
        "# exclusive, which aborts the nested launch, so clear them first.",
        "unset SLURM_MEM_PER_NODE SLURM_MEM_PER_CPU SLURM_MEM_PER_GPU",
    ]


def _script_header(
        stem: str, purpose: list, usage: UsageBlock, partition: Partition,
        deployment: DeploymentConfig, roots: LocationRoots,
        project_directory: Path) -> list:
    """Lines (1)-(3b) of every generated script (§14.5).

    The shebang and purpose comment; the scheduler directives from the
    partition, usage block and account; ``module use`` roots then the
    ``module load`` list; the three roots frozen at prepare time; and
    the per-kind environment. Shared by the pair jobs and the library
    builds so the two never drift.
    """
    lines: list = ["#!/bin/bash"]
    lines += purpose
    lines += [
        "# Lean by design (§10.5): scheduler directives, modules, frozen",
        "# roots, and the run line. The interpreter, launcher, and",
        "# potentials come from the activated install (the sourced",
        "# .sabsim/sabsimrc), so they are NOT restated here.",
    ]

    # (1) Scheduler directives — the §10.7 field set, with values filled
    # from the rc.
    lines += [
        f"#SBATCH --job-name={stem}",
        f"#SBATCH --partition={partition.name}",
        f"#SBATCH --account={deployment.default_account}",
        f"#SBATCH --nodes={usage.nodes}",
        f"#SBATCH --ntasks-per-node={usage.tasks_per_node}",
    ]
    # A GPU request is emitted ONLY when the job asks for accelerators
    # (usage.gpus_per_node > 0); a CPU job states 0 and gets no --gres
    # line, so the scheduler does not route it to a GPU node needlessly.
    gres = _slurm_gres(usage, partition)
    if gres is not None:
        lines.append(f"#SBATCH --gres={gres}")
    lines += [
        f"#SBATCH --mem={_slurm_memory(usage)}",
        f"#SBATCH --time={_slurm_walltime(usage)}",
        f"#SBATCH --output={project_directory}/{stem}-%j.out",
        f"#SBATCH --error={project_directory}/{stem}-%j.err",
        "",
        "set -euo pipefail",
        "",
    ]

    # (2) module use <roots>, THEN module load <per-kind tools> (§4.4).
    if deployment.module_paths or usage.modules:
        lines.append(
            "# The CPG modulefile tree is not on the default path (§4.4).")
        lines += [f"module use {path}"
                  for path in deployment.module_paths]
        lines += [f"module load {name}" for name in usage.modules]
        if usage.venv:
            lines += [
                "# This job's own Python environment, activated AFTER the",
                "# modules so its interpreter wins on PATH (§4.4).",
                f'source "{usage.venv}/bin/activate"',
            ]
        lines.append("")

    # (3) The three roots, FROZEN at prepare time (§10.5, §1.4): the script
    # names the exact locations it used, reproducible even if the rc later
    # changes. SABSIM_LOCAL is written only when an override is set.
    lines += [
        "# Location roots, frozen at prepare time (§10.5, §1.4).",
        f'export SABSIM_SCRATCH="{roots.scratch}"',
        f'export SABSIM_SHARE="{roots.share}"',
    ]
    if roots.local is not None:
        lines.append(f'export SABSIM_LOCAL="{roots.local}"')
    lines.append("")

    # (3b) Per-kind environment from the rc's [usage.<kind>.environment]
    # (ARCHITECTURE §4.4): machine-specific knobs the job needs but that are
    # not science settings — e.g. the universal-cascade prep jobs point
    # SABSIM_CASCADE_ENGINE_PREFIX at the deepmd bundle. Emitted before the
    # launch, in the block's own (sorted) order, so the script is
    # deterministic. A block with no environment emits nothing here.
    if usage.environment:
        lines.append("# Per-kind environment, frozen from the rc (§4.4).")
        lines += [f'export {name}="{value}"'
                  for name, value in usage.environment]
        lines.append("")
    return lines


def _success_line(job: JobKind, folders) -> str:
    """The ``echo`` a script prints on success: what to check, what next.

    A prep job's successor (bond) also needs the OTHER prep to have
    finished, so the line says so rather than inviting a premature
    submit; the last job in the chain announces the measure vector.
    The next job is named as its `sabsim submit` line (§10.12), and
    the line says "unless already queued" because a person who
    submitted several jobs at once has the successor waiting in the
    queue already and must not send it a second time.
    """
    stem = job.folder(folders)
    successors = jobs_depending_on(job.name)
    if not successors:
        return (f'echo "{job.name} done ({stem}). The measure vector is '
                f'written in {stem}/; the pair chain is complete."')
    parts = []
    for successor in successors:
        command = _next_submission(successor, folders)
        others = [name for name in successor.depends_on
                  if name != job.name]
        if others:
            parts.append(
                f"once {' and '.join(others)} has also finished, "
                f"{command}")
        else:
            parts.append(command)
    return (f'echo "{job.name} done ({stem}). Check its deliverables in '
            f'{stem}/. Next, unless already queued: {"; ".join(parts)}"')


# ---------------------------------------------------------------------
# The login-node gates (§10.5, §10.6) and the small formatting helpers.
# ---------------------------------------------------------------------

def _resolve_usage_and_partition(
        deployment: DeploymentConfig, job: JobKind) -> tuple:
    """Look up a job's usage block and the partition it resolves to.

    The block is found by the job's ``usage_key`` — ``prep`` for both
    surface preparations, else the job's own name (§14.2). Both lookups
    can fail loudly (a kind with no ``[usage.*]`` block, or a usage block
    routing to an undefined resource class); those are the same
    executability refusals :func:`~sabsim.deploy.config.load_deployment`
    already makes, surfaced here by job name.
    """
    usage = deployment.usage.get(job.usage_key)
    if usage is None:
        raise DeploymentError(
            f"the deployment rc has no [usage.{job.usage_key}] block, so "
            f"the '{job.name}' job cannot be prepared; the rc defines "
            f"{sorted(deployment.usage)}")
    partition = deployment.partition_for(job.usage_key)
    return usage, partition


def _check_walltime_ceiling(
        job: JobKind, usage: UsageBlock, partition: Partition) -> None:
    """Refuse a per-kind walltime over its partition ceiling (§10.6).

    The one cheap check the writer earns: it compares two numbers already
    written in the rc and predicts NOTHING about run length. A request the
    scheduler would bounce after submission is refused here instead, on
    the login node, where the message is readable.
    """
    if usage.walltime.in_hours() > partition.max_walltime.in_hours():
        raise DeploymentError(
            f"[usage.{job.usage_key}] asks for {usage.walltime.value} "
            f"{usage.walltime.unit} walltime, over the "
            f"'{usage.resource_class}' partition ceiling of "
            f"{partition.max_walltime.value} {partition.max_walltime.unit} "
            f"(partition '{partition.name}', job '{job.name}'). Lower the "
            f"walltime or raise the partition's max_walltime.")


def _slurm_gres(usage: UsageBlock, partition: Partition) -> str | None:
    """Format a usage block's GPU request as a SLURM ``--gres`` value.

    Returns ``"gpu:<count>"`` — or ``"gpu:<type>:<count>"`` when the
    partition names its card model (``gpu_type``) — when the job asks for
    accelerators, or ``None`` when it asks for none (a CPU-only job), so
    the caller emits the directive only for a GPU job. The count is what
    the person wrote in ``gpus_per_node`` — the writer requests it
    verbatim and predicts nothing, exactly as it does for ranks and
    walltime (DESIGN.md §10.6).
    """
    if usage.gpus_per_node <= 0:
        return None
    if partition.gpu_type:
        return f"gpu:{partition.gpu_type}:{usage.gpus_per_node}"
    return f"gpu:{usage.gpus_per_node}"


def _check_gpu_ceiling(
        job: JobKind, usage: UsageBlock, partition: Partition) -> None:
    """Refuse a per-kind GPU request its partition cannot satisfy (§10.6).

    The GPU twin of :func:`_check_walltime_ceiling` — another cheap check
    that predicts nothing, only comparing two numbers already in the rc.
    A CPU-only job (``gpus_per_node == 0``) needs no accelerator, so it is
    skipped. A job asking for GPUs from a partition that declares none, or
    for more per node than the partition has, is bounced here on the login
    node with a readable reason instead of by the scheduler after submit.
    """
    if usage.gpus_per_node <= 0:
        return
    available = partition.capacity.get("gpus_per_node")
    if available is None:
        raise DeploymentError(
            f"[usage.{job.usage_key}] asks for {usage.gpus_per_node} GPU(s) "
            f"per node, but its '{usage.resource_class}' partition "
            f"('{partition.name}') declares no gpus_per_node. Route it to a "
            f"partition that has GPUs, or set gpus_per_node = 0.")
    if usage.gpus_per_node > available:
        raise DeploymentError(
            f"[usage.{job.usage_key}] asks for {usage.gpus_per_node} GPU(s) "
            f"per node, over the '{usage.resource_class}' partition's "
            f"{int(available)} (partition '{partition.name}'). Lower the "
            f"request or move to a partition with more GPUs.")


def _slurm_walltime(usage: UsageBlock) -> str:
    """Format a usage block's walltime as SLURM ``HH:MM:SS``."""
    total_seconds = int(round(usage.walltime.in_hours() * 3600.0))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


# SLURM's own single-letter size suffixes for ``--mem``, keyed by the same
# unit words :data:`~sabsim.deploy.config._MEGABYTES_PER_UNIT` accepts.
# Kept here, not in the config record, because the letter is a SLURM
# spelling detail — the walltime split the same way (Duration reduces the
# unit; this writer formats it for the scheduler).
_SLURM_MEMORY_SUFFIX = {
    "mb": "M", "m": "M", "megabyte": "M", "megabytes": "M",
    "gb": "G", "g": "G", "gigabyte": "G", "gigabytes": "G",
    "tb": "T", "t": "T", "terabyte": "T", "terabytes": "T",
}


def _slurm_memory(usage: UsageBlock) -> str:
    """Format a usage block's per-node memory as a SLURM ``--mem`` value.

    A whole request in a unit SLURM spells with a letter (e.g. 16 GB) is
    emitted verbatim as ``16G`` so the generated script reads the way the
    rc does. Anything else — a fractional amount, or a unit with no SLURM
    letter — falls back to whole megabytes (``--mem``'s native unit).
    Calling ``in_megabytes`` first also makes an unknown unit a loud stop
    here, the same refusal the loader would already have raised.
    """
    megabytes = usage.memory.in_megabytes()
    suffix = _SLURM_MEMORY_SUFFIX.get(usage.memory.unit.lower())
    if suffix is not None and usage.memory.value == int(usage.memory.value):
        return f"{int(usage.memory.value)}{suffix}"
    return f"{int(round(megabytes))}M"


def _semantic_name(stage_folder: str) -> str:
    """The script filename: ``<stage folder>.slurm`` — no ordinal (§10.5).

    The script carries the SAME name as the folder it fills, so the
    script, the deliverables folder and the bulk folder under
    ``intermediate/`` are one name to a reader (§14.4).
    """
    return f"{stage_folder}{SCRIPT_EXTENSION}"


# ---------------------------------------------------------------------
# On-disk writers — the scripts and the guide.
# ---------------------------------------------------------------------

def _write_script(path: Path, text: str) -> None:
    """Write a generated script and mark it executable."""
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def submission_waves(
        entries: tuple[SubmissionEntry, ...]
        ) -> tuple[tuple[SubmissionEntry, ...], ...]:
    """The pair jobs grouped into waves a person submits together.

    A wave is every pair job whose upstream pair jobs all sit in
    earlier waves: the two preps, then bond, then analysis. The library
    builds are left out — `sabsim submit` puts one in front of its prep
    job by itself, when that library is missing (§10.12) — so each wave
    is exactly the job words of ONE `sabsim submit` line in the guide's
    step-by-step form. Read off the entries' own dependency lists, so
    an inserted job finds its wave for free.
    """
    pair_entries = [entry for entry in entries
                    if library_surface_number(entry.job_name) is None]
    pair_names = {entry.job_name for entry in pair_entries}
    # The entries arrive in submission order, so every job a pair job
    # waits on already has its wave number when that job is reached.
    wave_of: dict[str, int] = {}
    for entry in pair_entries:
        upstream_waves = [wave_of[name] for name in entry.depends_on
                          if name in pair_names]
        wave_of[entry.job_name] = 1 + max(upstream_waves, default=-1)
    wave_count = 1 + max(wave_of.values(), default=-1)
    return tuple(
        tuple(entry for entry in pair_entries
              if wave_of[entry.job_name] == wave_number)
        for wave_number in range(wave_count))


def _write_guide(
        project_directory: Path, project,
        entries: tuple[SubmissionEntry, ...]) -> None:
    """Drop the submission guide beside the scripts (§10.5, §14.4).

    The guide is where ORDER lives (semantic filenames carry no ordinal)
    and it is written around `sabsim submit` (§10.12), the command a
    person actually types. In order it gives: the jobs as the DEPENDENCY
    GRAPH in plain words (library builds, the two surface preparations,
    the bond once both have finished, the analysis); the step-by-step
    form, one `sabsim submit` line per wave with the folders to check
    in between; the all-at-once form for a person who trusts the gates;
    the dry run and the card and node overrides; and last the bare
    ``sbatch --dependency=afterok:...`` chain those commands stand for,
    so the by-hand route is never lost. Every script reinforces it by
    printing its own "what to submit next" line on success.
    """
    by_name = {entry.job_name: entry for entry in entries}
    lines = [
        f"# Submission guide — {project.pair.pair_label}",
        "",
        f"{project.description}",
        "",
        "Generated by `sabsim prepare` (DESIGN.md §10). Each script fills",
        "the stage folder of the same name: deliverables beside this guide,",
        "bulk output under `intermediate/` (§10.8).",
        "",
        "You do not need to type `sbatch` yourself. `sabsim submit`, run in",
        "this folder, hands the scripts to the scheduler in the order below,",
        "holds each job until the jobs it waits for have succeeded, prints",
        "the job ids, and exits (§10.12). It watches nothing: checking each",
        "result is still yours to do (§10.2), and each script prints, on",
        "success, what to check and what to submit next.",
        "",
        "## The jobs, in order",
        "",
    ]
    step = 0
    for entry in entries:
        step += 1
        if not entry.depends_on:
            when = "independent — runs in either order, or together"
        else:
            waits = " and ".join(
                f"`{by_name[name].script_name}`" for name in entry.depends_on)
            verb = "has" if len(entry.depends_on) == 1 else "have"
            when = f"after {waits} {verb} finished"
        lines.append(f"{step}. `{entry.script_name}` "
                     f"({entry.job_name}; {when})")
    lines += [
        "",
        "The two `.library` builds each make their surface's environment",
        "library ONCE per recipe (§3.5). `sabsim submit` puts a build in",
        "front of its prep job only when that prep folder holds no library",
        "yet, and says so when it skips one.",
        "",
        "## Step by step, checking each result",
        "",
        "```bash",
    ]
    # One `sabsim submit` line per wave of jobs that may go together,
    # with the folders to look in before the next wave is sent (§10.2).
    waves = submission_waves(entries)
    for wave_number, wave in enumerate(waves):
        job_words = " ".join(
            registry_lookup(entry.job_name).submit_word for entry in wave)
        lines.append(f"sabsim submit {job_words}")
        if wave_number + 1 < len(waves):
            folders_to_check = " and ".join(
                f"{entry.stage_folder}/" for entry in wave)
            lines.append(
                f"# when finished, check {folders_to_check} — then:")
    # The first job's word, for the two override examples below.
    example_word = registry_lookup(waves[0][0].job_name).submit_word
    lines += [
        "```",
        "",
        "A job named on the line is held only on the other jobs named with",
        "it. A job it depends on that is NOT named is taken as already run",
        "and checked — that is what submitting one job alone means.",
        "",
        "## All at once, for a person who trusts the gates",
        "",
        "```bash",
        "sabsim submit all",
        "```",
        "",
        "Every job is queued now and held (`afterok`) on the jobs it depends",
        "on, so a job that fails holds back every job waiting on it.",
        "",
        "## Looking first, and choosing a card or a node",
        "",
        "- `sabsim submit all --dry-run` prints the `sbatch` lines it would",
        "  issue and submits nothing.",
        f"- `sabsim submit {example_word} --gpu V100` asks for that card",
        "  model (V100 is only an example) on every GPU job named, keeping",
        "  each script's card count, in the GPU partitions that hold it.",
        f"- `sabsim submit {example_word} --node <name>` pins the named jobs",
        "  to one node and asks for the card that node carries.",
        "",
        "Neither choice is remembered or written into a script: the scripts",
        "keep saying what `deployment.toml` said. Submit from the shell in",
        "which the install is active (`which python` prints the install's",
        "own): every job inherits that shell's environment, and `sabsim",
        "submit` stops before the first job when the `python` a job would",
        "inherit is not the install's.",
        "",
        "## The same chain by hand",
        "",
        "`sabsim submit all` issues these lines when neither library exists",
        "yet. They are here to show what it does, and for a scheduler option",
        "it does not offer. A `.library` script exits at once, successfully,",
        "when its library is already there, so it may always stay in a",
        "hand-typed chain:",
        "",
        "```bash",
    ]
    for entry in entries:
        variable = _shell_variable(entry.job_name)
        if not entry.depends_on:
            lines.append(
                f"{variable}=$(sbatch --parsable {entry.script_name})")
        else:
            ids = ":".join(f"${_shell_variable(name)}"
                           for name in entry.depends_on)
            lines.append(
                f"{variable}=$(sbatch --parsable "
                f"--dependency=afterok:{ids} {entry.script_name})")
    lines += ["```", ""]
    (project_directory / GUIDE_FILENAME).write_text(
        "\n".join(lines), encoding="utf-8")


def _shell_variable(job_name: str) -> str:
    """A shell variable name holding one job's scheduler id in the guide."""
    return f"{job_name}_id"

