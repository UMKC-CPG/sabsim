"""The `sabsim prepare` writer (PSEUDOCODE.md §14.4, §14.5; DESIGN §10).

`prepare` is the WRITER half of the deployment consumer (`run` is the
executor, :mod:`sabsim.deploy`/`sabsim.pipeline.pair_jobs`). It reads
BOTH inputs — the project file (one wafer pair) and the machine-local
deployment rc — and emits one ready-to-submit script per job of the
registry (:mod:`sabsim.deploy.registry`: the two surface preparations,
the bond, the analysis) plus a submission guide. It **submits nothing**
(§10.1): a long-lived submit-and-watch process cannot sit on a login
node, so the human submits the scripts and inspects each gate before
the next.

The scripts are named after the STAGE FOLDERS they fill (ARCHITECTURE
§1, revised 2026-08-30 (Paul)): ``prep_surf1_si.slurm`` runs the job
whose deliverables land in ``prep_surf1_si/`` and whose bulk lands in
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
)
from sabsim.deploy.roots import LocationRoots, resolve_location_roots
from sabsim.spec.loader import load_and_validate_project
from sabsim.spec.records import stage_folders

# The submission guide's filename — a descriptively named guided index
# dropped beside the scripts (§10.5: a submission GUIDE, never `index` or
# `readme`).
GUIDE_FILENAME = "SUBMISSION_GUIDE.md"

# The generated scripts' extension.
SCRIPT_EXTENSION = ".slurm"


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
    generated run line, so each dynamic stage (cascade, press, settle,
    pull) records a trajectory for viewing — the standing rule (Paul,
    2026-08-26) that a dynamic run leaves a movie behind as its evidence;
    ``False`` writes ``--no-dump-visuals`` instead.
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

    entries = []
    for job in JOB_REGISTRY:
        usage, partition = _resolve_usage_and_partition(deployment, job)
        stage_folder = job.folder(folders)
        # The stage folder itself: made if absent, left alone if present
        # (a prep folder may already hold its recipe and library).
        (project_directory / stage_folder).mkdir(parents=True, exist_ok=True)
        script = render_job_script(
            validated, job, usage, partition, deployment, roots,
            spec_path, project_directory, dump_visuals=dump_visuals)
        script_name = _semantic_name(stage_folder)
        _write_script(project_directory / script_name, script)
        entries.append(SubmissionEntry(
            job_name=job.name, stage_folder=stage_folder,
            script_name=script_name, depends_on=job.depends_on))

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
    lines: list = ["#!/bin/bash"]

    lines += [
        f"# {stem} — the {job.name} job of this project.",
        "# Generated by `sabsim prepare` (DESIGN §10). Deliverables land",
        "# in the folder of the same name",
        "# beside this script; bulk output under intermediate/ (§10.8).",
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

    # (4) The run's home is the PROJECT folder (CWD, §14.3), then the
    # launcher INSIDE the allocation (§4.1) — python + mpirun on PATH from
    # the activated install.
    lines += [
        "# The run's home is the project folder (the CLI takes CWD), so",
        "# relative paths mean the same thing whichever folder you submit",
        "# from (§14.5).",
        f'cd "{project_directory}"',
        "",
        "# Launch inside the allocation (§4.1). `srun --mpi=pmix` is the",
        "# primary launcher (§4.1), NOT mpirun: mpirun's remote daemon does",
        "# not preserve the venv on other nodes, so a remote rank falls back",
        "# to the conda-env python that lacks the editable sabsim (diagnosed",
        "# job 15697153); srun carries the activated venv to every node. The",
        "# allocation also exports SLURM_MEM_PER_NODE/_CPU/_GPU as mutually",
        "# exclusive, which aborts the nested launch, so clear them first.",
        "unset SLURM_MEM_PER_NODE SLURM_MEM_PER_CPU SLURM_MEM_PER_GPU",
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


def _success_line(job: JobKind, folders) -> str:
    """The ``echo`` a script prints on success: what to check, what next.

    A prep job's successor (bond) also needs the OTHER prep to have
    finished, so the line says so rather than inviting a premature
    submit; the last job in the chain announces the measure vector.
    """
    stem = job.folder(folders)
    successors = jobs_depending_on(job.name)
    if not successors:
        return (f'echo "{job.name} done ({stem}). The measure vector is '
                f'written in {stem}/; the pair chain is complete."')
    parts = []
    for successor in successors:
        script = _semantic_name(successor.folder(folders))
        others = [name for name in successor.depends_on
                  if name != job.name]
        if others:
            parts.append(
                f"once {' and '.join(others)} has also finished, submit: "
                f"sbatch {script}")
        else:
            parts.append(f"then submit: sbatch {script}")
    return (f'echo "{job.name} done ({stem}). Check its deliverables in '
            f'{stem}/, {"; ".join(parts)}"')


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


def _write_guide(
        project_directory: Path, project,
        entries: tuple[SubmissionEntry, ...]) -> None:
    """Drop the submission guide beside the scripts (§10.5, §14.4).

    The guide is where ORDER lives (semantic filenames carry no ordinal).
    It reads as the DEPENDENCY GRAPH in plain words: the two surface
    preparations first, in either order or together; the bond once both
    have finished and their gate reports are to the person's liking;
    then the analysis. It also prints the one-line chained form for a
    person who trusts the gates — ``sbatch --dependency=afterok:...`` —
    reinforced by every script printing its own "submit next" line on
    success.
    """
    by_name = {entry.job_name: entry for entry in entries}
    lines = [
        f"# Submission guide — {project.pair.pair_label}",
        "",
        f"{project.description}",
        "",
        "Generated by `sabsim prepare` (DESIGN.md §10). Each script fills",
        "the stage folder of the same name: deliverables beside this guide,",
        "bulk output under `intermediate/` (§10.8). Submit the jobs in the",
        "order below, checking each result before submitting the next",
        "(§10.2). Each script also prints, on success, what to check and",
        "the next job to submit.",
        "",
        "## Step by step",
        "",
    ]
    step = 0
    for entry in entries:
        step += 1
        if not entry.depends_on:
            when = "independent — submit in either order, or together"
        else:
            waits = " and ".join(
                f"`{by_name[name].stage_folder}`" for name in entry.depends_on)
            when = f"after {waits} has finished and been checked"
        lines.append(f"{step}. `sbatch {entry.script_name}` "
                     f"({entry.job_name}; {when})")
    lines += [
        "",
        "## Chained form, for a person who trusts the gates",
        "",
        "Submit everything at once and let the scheduler hold each job",
        "until the ones it depends on succeed (`afterok`):",
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

