"""The `sabsim submit` hand (DESIGN.md §10.12, PSEUDOCODE.md §14.10).

`prepare` writes the scripts and a guide whose chained form is six
``sbatch --parsable`` lines, each job held on the ones before it with
``afterok``. `submit` types that chain for the person: it reads the
project file to learn the stage-folder names (and so the script
names), submits the jobs it is asked for in the registry's order, holds
each on the named jobs it depends on, and exits the moment the last
scheduler id is back. It WATCHES NOTHING — the login-node wall
(ARCHITECTURE.md §4.1) forbids a process that lives there, not a call
that returns at once — and it never rewrites a script: a GPU or node
override goes on the ``sbatch`` line, where it outranks the script's
directives, so the scripts on disk keep saying what the rc said.

Three rules decide what is submitted (§10.12):

* **Only what is named.** A job on the line is held on another job on
  the line it depends on, and NOT on an absent one — an absent
  upstream job is one the person has already run and checked, which
  is what submitting ``bond`` alone means. ``all`` names every job.
* **A library build only when the library is missing.** A prep job's
  environment-library build (§10.2 step 0) is put in front of it, and
  the prep job held on it, exactly when the prep folder has no library
  manifest; otherwise the build is skipped and the command says so.
* **A missing script is a clear stop** naming ``sabsim prepare``, before
  anything is submitted.

The scheduler call is a plain function argument so the test suite can
stand in a double for ``sbatch`` and read back exactly what would have
been issued; ``--dry-run`` prints those lines and calls nothing.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from sabsim.deploy.prepare import (
    SubmissionEntry,
    library_job_name,
    library_surface_number,
    submission_entries,
)
from sabsim.deploy.registry import JOB_NAMES
from sabsim.driver.environment_library import LIBRARY_MANIFEST_FILE
from sabsim.spec.loader import load_and_validate_project
from sabsim.spec.records import stage_folders

# The word that names every job at once on the command line.
ALL_JOBS = "all"

# The job choices the verb offers: the registry's names with dashes,
# matching the `run` flags without their leading dashes, plus `all`.
JOB_CHOICES: tuple[str, ...] = tuple(
    name.replace("_", "-") for name in JOB_NAMES) + (ALL_JOBS,)

# The script directive that states a job's GPU request, as `prepare`
# writes it: `#SBATCH --gres=gpu:<model>:<count>` (model optional).
_GRES_DIRECTIVE = re.compile(
    r"^#SBATCH\s+--gres=gpu(?::(?P<model>[^:\s]+))?:(?P<count>\d+)\s*$",
    re.MULTILINE)

# A scheduler takes the sbatch options and the script path and returns
# the new job's id as a string.
Scheduler = Callable[[Sequence[str], Path], str]


class SubmitError(Exception):
    """A readable login-node stop: nothing was submitted."""


@dataclass(frozen=True)
class Submission:
    """One job as it was (or would be) handed to the scheduler.

    ``options`` is the exact option list placed before the script on
    the ``sbatch`` line; ``job_id`` is the scheduler's id, or a
    ``<name_id>`` placeholder on a dry run.
    """

    job_name: str
    script_name: str
    options: tuple[str, ...]
    job_id: str


def sbatch_scheduler(options: Sequence[str], script: Path) -> str:
    """Issue one real ``sbatch`` and return the job id it prints.

    ``--parsable`` makes sbatch print the bare id (or ``id;cluster``);
    anything else on stdout, or a non-zero exit, is turned into a
    :class:`SubmitError` carrying the scheduler's own words.
    """
    completed = subprocess.run(
        ["sbatch", *options, str(script)], capture_output=True,
        text=True, check=False)
    if completed.returncode != 0:
        reason = completed.stderr.strip() or completed.stdout.strip()
        hint = ""
        if "node configuration is not available" in reason:
            hint = (" — the request (card model, count, memory) does not "
                    "fit any node it may use; with --node, check the "
                    "node's card against the script's --gres line, or "
                    "name the card with --gpu")
        raise SubmitError(f"sbatch refused {script.name}: {reason}{hint}")
    job_id = completed.stdout.strip().split(";")[0]
    if not job_id:
        raise SubmitError(f"sbatch printed no job id for {script.name}")
    return job_id


# A full card's model name as the scheduler's `Gres` column spells it
# (`gpu:V100:1(S:0-71)` -> V100); a MIG slice such as `1g.10gb` is not
# a card a generated script can ask for by that name and is passed over.
_CARD_MODEL = re.compile(r"gpu:(?P<model>[A-Z][A-Za-z0-9]*):\d+")

# Looks up the card model a node carries, or None for a CPU node.
NodeCardLookup = Callable[[str], "str | None"]


def node_card_model(node: str) -> str | None:
    """Ask the scheduler which card model ``node`` carries (§10.12).

    Reads ``sinfo``'s ``Gres`` column for the one node; a node with no
    GPU, an unknown node, or a cluster without ``sinfo`` yields None,
    and the caller leaves the script's own request alone.
    """
    try:
        completed = subprocess.run(
            ["sinfo", "-h", "-N", "-n", node, "-O", "Gres:120"],
            capture_output=True, text=True, check=False)
    except OSError:
        return None
    match = _CARD_MODEL.search(completed.stdout)
    return match.group("model") if match else None


def gpu_count_in_script(script_path: Path) -> int | None:
    """The GPU count a generated script asks for, or None for a CPU job.

    Read off its ``#SBATCH --gres=gpu:<model>:<count>`` directive, so a
    ``--gpu`` override keeps the count the rc chose (a two-card bond job
    stays a two-card job on the new model, §10.12).
    """
    match = _GRES_DIRECTIVE.search(script_path.read_text(encoding="utf-8"))
    return int(match.group("count")) if match else None


def requested_job_names(choices: Sequence[str]) -> tuple[str, ...]:
    """Turn the command-line choices into registry job names, in order.

    ``all`` expands to every registry job; otherwise each dashed choice
    (``prep-surf1``) becomes its registry name (``prep_surf1``). The
    result keeps the REGISTRY's order whatever order the person typed,
    and names each job once.
    """
    if ALL_JOBS in choices:
        return tuple(JOB_NAMES)
    wanted = {choice.replace("-", "_") for choice in choices}
    unknown = wanted - set(JOB_NAMES)
    if unknown:
        raise SubmitError(
            f"no such job(s) {sorted(unknown)}; the choices are "
            f"{list(JOB_CHOICES)}")
    return tuple(name for name in JOB_NAMES if name in wanted)


def plan_submissions(
        project_directory: Path, entries: Sequence[SubmissionEntry],
        job_names: Sequence[str]) -> tuple[list[SubmissionEntry], list[str]]:
    """Choose which entries to submit, and say what was skipped.

    Returns the entries to submit, in the guide's order, and a list of
    notices. A requested prep job brings its library build along only
    when its prep folder holds no library manifest (§10.2 step 0);
    an existing library produces a notice instead.
    """
    by_name = {entry.job_name: entry for entry in entries}
    chosen: set[str] = set(job_names)
    notices = []
    for job_name in job_names:
        if not job_name.startswith("prep_surf"):
            continue
        surface_number = int(job_name[len("prep_surf"):])
        prep_entry = by_name[job_name]
        manifest = project_directory / prep_entry.stage_folder \
            / LIBRARY_MANIFEST_FILE
        library_name = library_job_name(surface_number)
        if manifest.is_file():
            notices.append(
                f"{prep_entry.stage_folder}/ already holds its environment "
                f"library; the {library_name} build is skipped")
        else:
            chosen.add(library_name)
    selected = [entry for entry in entries if entry.job_name in chosen]
    return selected, notices


def submit(project_spec_path, job_choices: Sequence[str],
           project_directory=None, gpu_type: str | None = None,
           node: str | None = None, dry_run: bool = False,
           scheduler: Scheduler = sbatch_scheduler,
           node_card_lookup: NodeCardLookup = node_card_model
           ) -> tuple[tuple[Submission, ...], tuple[str, ...]]:
    """Hand the named jobs' scripts to the scheduler (§14.10).

    ``job_choices`` are the command-line words (``prep-surf1``, ...,
    ``all``). ``project_directory`` defaults to the folder holding the
    project file, where `prepare` put the scripts. ``gpu_type`` replaces
    the card model on every GPU job's request, keeping each script's
    count; ``node`` pins every job to that node AND, when no
    ``gpu_type`` is given, asks the scheduler (``node_card_lookup``)
    which card that node carries and requests it, since a script's own
    card model is the rc's and a pinned node may carry another (the
    2026-11-08 refusal: H100 asked of a V100 node). With ``dry_run`` the
    ``sbatch`` lines are planned and returned with ``<name_id>``
    placeholders and ``scheduler`` is never called. Returns the
    submissions in order and the notices (skipped library builds).
    Raises :class:`SubmitError` before anything is submitted when a
    needed script is missing or a job name is unknown.
    """
    validated = load_and_validate_project(project_spec_path)
    if project_directory is None:
        project_directory = validated.project_directory
    project_directory = Path(project_directory)
    job_names = requested_job_names(job_choices)
    entries = submission_entries(stage_folders(validated.pair))
    selected, notices = plan_submissions(
        project_directory, entries, job_names)

    # A pinned node decides the card: the script asks for the rc's
    # model, which the node may not carry, and Slurm refuses the pair
    # outright ("Requested node configuration is not available").
    if node and not gpu_type:
        gpu_type = node_card_lookup(node)
        if gpu_type:
            notices.append(f"{node} carries {gpu_type} cards; GPU jobs "
                           f"will ask for that model")
        else:
            notices.append(f"{node} reports no GPU; each script's own "
                           f"request is kept")

    # Every needed script must be there BEFORE the first sbatch, so a
    # half-submitted chain is impossible (§10.12).
    missing = [entry.script_name for entry in selected
               if not (project_directory / entry.script_name).is_file()]
    if missing:
        raise SubmitError(
            f"no script(s) {missing} in {project_directory} — run "
            f"`sabsim prepare` there first")

    submissions = []
    job_ids: dict[str, str] = {}
    for entry in selected:
        script = project_directory / entry.script_name
        options = ["--parsable"]
        # Held only on the named jobs it depends on; an absent upstream
        # job is one already run and checked (§10.12).
        held_on = [job_ids[name] for name in entry.depends_on
                   if name in job_ids]
        if held_on:
            options.append("--dependency=afterok:" + ":".join(held_on))
        if gpu_type:
            count = gpu_count_in_script(script)
            if count is not None:
                options.append(f"--gres=gpu:{gpu_type}:{count}")
        if node:
            options.append(f"--nodelist={node}")
        if dry_run:
            job_id = f"<{entry.job_name}_id>"
        else:
            job_id = scheduler(options, script)
        job_ids[entry.job_name] = job_id
        submissions.append(Submission(
            job_name=entry.job_name, script_name=entry.script_name,
            options=tuple(options), job_id=job_id))
    return tuple(submissions), tuple(notices)


def describe_submission(submission: Submission) -> str:
    """The ``sbatch`` line a submission stands for, for printing."""
    return "sbatch " + " ".join(
        [*submission.options, submission.script_name])


def is_library_build(submission: Submission) -> bool:
    """True for a surface's environment-library build (§10.2 step 0)."""
    return library_surface_number(submission.job_name) is not None


__all__ = [
    "ALL_JOBS",
    "JOB_CHOICES",
    "Submission",
    "SubmitError",
    "describe_submission",
    "gpu_count_in_script",
    "is_library_build",
    "node_card_model",
    "plan_submissions",
    "requested_job_names",
    "sbatch_scheduler",
    "submit",
]

