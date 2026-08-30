"""Where a run's bulky intermediates live (ARCHITECTURE.md §4.1).

A run produces far more bytes than it produces insight: LAMMPS data
files, strided trajectory dumps, per-phase logs. Those belong on the
cluster's scratch filesystem — "large trajectories go on scratch, not
home" (§4.1). But a scratch path is long, machine-specific, and easy to
lose track of, so this module follows the MIRROR-TREE pattern this
group's other codes already use (imago, olcao): scratch holds a mirror
of the project's own directory layout, and each project folder holds
a symlink named ``intermediate`` pointing into it.

That buys two things at once. The project folder stays small and
legible while the bytes live where the sysadmins want them; and a
reader who lands in a project folder follows ONE obvious link to the
data instead of
reconstructing a path from memory. A scratch directory nothing points at
is an orphan — it survives only as long as someone remembers it exists.

**Keyed by path down to the project, then by STAGE FOLDER inside it.**
The mirror is keyed by the project directory's PATH, because ``jobs/``
may nest several levels before the project itself
(``jobs/2026-07/si_sio2/``) and that nesting is the researcher's own
organisation: flattening it to a bare folder name would collide across
groups and would throw the grouping away. WITHIN a project the mirror
simply repeats the project's own four stage folders — ``prep_surf1_<a>``,
``prep_surf2_<b>``, ``bond_<a>_<b>``, ``analysis_<a>_<b>`` (ARCHITECTURE
§1, revised 2026-08-30 (Paul)) — so a reader who knows the project
tree already knows the scratch tree. Nothing is keyed by a study or a
pair name any more; the earlier ``<mirror>/<study>/<member>`` keying
doubled the project's name inside its own mirror and is gone.

**Two homes with one name.** Each stage has a folder in the PROJECT
for its DELIVERABLES — manifests, ledgers, gate reports, the
activated-half handoff, the measure vector: small, precious, kept with
the project — and the same-named folder under ``intermediate/`` for
its BULK — dumps, LAMMPS logs, data files, generated inputs: large,
regenerable, on scratch (PSEUDOCODE §14.3). :func:`deliverable_directory`
gives the first, :func:`stage_scratch` the second.

**A rerun never overwrites.** Every run of a stage works in a FRESH
``run-<scheduler job id>/`` subfolder of the stage's bulk folder
(:func:`run_subfolder`; a dated name when no scheduler is present), so
a second attempt sits beside the first instead of on top of it, and
the deliverable manifest records which run it came from.

**A link is a convenience, never evidence.** `VISION.md` goal 3 wants
every number traceable to its exact inputs, and a symlink is machine
state: it can be repointed, broken, or absent, and it says nothing about
where a number came from six months ago. So the paths here are for
USING, and the manifest records provenance by resolving them itself.

Which is also why the scratch root is used as CONFIGURED rather than
resolved through its mounts. On this cluster ``$HOME/data`` is a link to
``/mnt/pixstor/data/<user>``; baking that mount into every symlink would
leak a sysadmin's implementation detail into the project tree and would
strand the links the day the mount moves. The configured form is the
stable, human-readable one — and it is what the group's other codes
already write, so an ``intermediate`` link here reads like the ones in
imago and olcao. The manifest resolves at record time, when a frozen,
unambiguous string is exactly what is wanted.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

# The deployment variable naming the per-user, write-heavy, regenerable
# tier of the three roots (§4.1): SABSIM_SCRATCH (here), SABSIM_SHARE
# (group, read-mostly, authoritative), SABSIM_LOCAL (personal override).
SCRATCH_ROOT_VARIABLE = "SABSIM_SCRATCH"

# The link's name inside each project folder. Deliberately the SAME word
# imago and olcao use, so the muscle memory carries across codes.
INTERMEDIATE_LINK_NAME = "intermediate"


class ScratchError(Exception):
    """A scratch location could not be resolved or safely linked."""


def scratch_root() -> Path:
    """The one root SABSIM may write bulky intermediates under.

    Read from ``$SABSIM_SCRATCH``. It is deliberately NOT defaulted:
    guessing a location and writing gigabytes into it is how a home
    quota dies, and the entire point of the deployment layer is that
    "where to run" is stated rather than inferred (`VISION.md`
    principle 1). An unset variable is a configuration error the caller
    should see immediately, not a silent fallback to somewhere plausible.

    Expanded (``~`` becomes the home directory) but NOT resolved through
    its mounts — see the module docstring on why the configured form is
    the one that belongs in a link.
    """
    configured = os.environ.get(SCRATCH_ROOT_VARIABLE)
    if not configured:
        raise ScratchError(
            f"{SCRATCH_ROOT_VARIABLE} is not set. It must name the "
            f"directory this machine reserves for SABSIM's regenerable "
            f"run output (ARCHITECTURE.md §4.1); there is no default, "
            f"because writing run output to a guessed location is not "
            f"a safe thing to do.")
    return Path(configured).expanduser()


def mirror_path(project_directory) -> Path:
    """The scratch path mirroring ``project_directory`` — no side effects.

    The project's path relative to ``$HOME`` becomes the key under the
    scratch root, so ``~/sabsim/jobs/si_sio2`` mirrors to
    ``$SABSIM_SCRATCH/sabsim/jobs/si_sio2``. A project tree
    living OUTSIDE ``$HOME`` still gets a mirror: its absolute path is
    used as the key with the leading separator dropped. That keeps the
    one invariant that matters — every byte lands under the scratch root
    — at the cost of a longer path.

    The project side IS resolved before the key is taken, because
    ``$HOME`` and the project can reach the same directory by different
    routes (here ``$HOME`` is ``/home/<user>`` while the repo sits under
    ``/cluster/pixstor/home/<user>``); without resolving both, the
    project would not appear to be under the home at all.

    Pure: it computes a path and creates nothing, so a caller can report
    where output WOULD go (a dry run, an error message) without touching
    the filesystem.
    """
    job = Path(project_directory).expanduser().resolve()
    home = Path.home().resolve()
    try:
        relative_key = job.relative_to(home)
    except ValueError:
        relative_key = Path(*job.parts[1:])
    return scratch_root() / relative_key


def job_scratch(project_directory) -> Path:
    """Create a project's scratch mirror, link it, and return the mirror.

    The project directory is the run's HOME — the folder holding
    ``sabsim.toml`` — and the mirror is its whole scratch tree; the
    per-stage folders hang beneath it (:func:`stage_scratch`).
    Idempotent: safe to call at the top of every run. Returns the
    RESOLVED mirror path for the manifest to record (see the module
    docstring on why the link is not the record).
    """
    job = Path(project_directory).expanduser().resolve()
    if not job.is_dir():
        raise ScratchError(
            f"project directory {job} does not exist (or is not a "
            f"directory); create it before asking for its scratch.")
    mirror = mirror_path(job)
    mirror.mkdir(parents=True, exist_ok=True)
    _refresh_intermediate_link(job, mirror)
    return mirror


def stage_scratch(project_directory, stage_folder: str) -> Path:
    """The BULK directory for ONE stage of a project, on scratch.

    ``<mirror of the project>/<stage folder>`` — the same folder name
    the project itself uses for that stage's deliverables (module
    docstring). Creates the directory (and the project's mirror and
    ``intermediate`` link, if needed) and returns the resolved absolute
    path. The bulk of one run goes into a fresh :func:`run_subfolder`
    beneath it, so this is the stage's HOME across runs, not any one
    run's working directory.
    """
    _check_single_path_segment("stage folder", stage_folder)
    stage_directory = job_scratch(project_directory) / stage_folder
    stage_directory.mkdir(parents=True, exist_ok=True)
    return stage_directory


def deliverable_directory(project_directory, stage_folder: str) -> Path:
    """The DELIVERABLES directory for ONE stage: in the project itself.

    ``<project>/<stage folder>`` — small, precious outputs (manifests,
    ledgers, gate reports, the activated-half handoff, the measure
    vector) that a person keeps with the project and reads without
    following the ``intermediate`` link (module docstring). Created if
    absent; an existing folder is left exactly as it is, since it may
    already hold a prepared surface's recipe and environment library.
    """
    _check_single_path_segment("stage folder", stage_folder)
    project = Path(project_directory).expanduser().resolve()
    if not project.is_dir():
        raise ScratchError(
            f"project directory {project} does not exist (or is not a "
            f"directory); a stage's deliverables need a project to live in.")
    directory = project / stage_folder
    directory.mkdir(parents=True, exist_ok=True)
    return directory


# The scheduler variable that names the running job; its value labels
# the run's working subfolder so a person can match a folder to the
# scheduler's own accounting (``sacct``) at a glance.
SCHEDULER_JOB_VARIABLE = "SLURM_JOB_ID"

# The prefix every run subfolder carries, so the run folders sort
# together and are told apart from a stage's other contents by sight.
RUN_SUBFOLDER_PREFIX = "run-"


def run_subfolder(stage_directory) -> Path:
    """Make a FRESH working subfolder for one run of a stage.

    Named ``run-<scheduler job id>`` when the process runs under the
    scheduler, else ``run-<YYYYmmdd-HHMMSS>`` from the wall clock, so
    a login-node dry run and a compute-node job both get a name a
    person can read. A rerun NEVER overwrites an earlier run: if the
    name is already taken — the same job id re-entering a stage, or
    two dated runs started within one second — this REFUSES rather
    than reusing the folder, because the earlier run's bytes are the
    evidence a comparison would be made against (Paul, 2026-08-30).

    MPI-SAFE in the same sense as the ``intermediate`` link: under a
    parallel run every rank asks for the same name, so ``mkdir`` is
    allowed to find the folder already made by a peer rank in this run
    — but only when the folder is EMPTY, which is what distinguishes a
    peer's fresh creation from an earlier run's finished output.
    """
    stage_directory = Path(stage_directory)
    job_id = os.environ.get(SCHEDULER_JOB_VARIABLE)
    if job_id:
        label = job_id
    else:
        label = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_directory = stage_directory / f"{RUN_SUBFOLDER_PREFIX}{label}"
    try:
        run_directory.mkdir(parents=False, exist_ok=False)
    except FileExistsError:
        if run_directory.is_dir() and not any(run_directory.iterdir()):
            return run_directory        # a peer rank made it, this run
        raise ScratchError(
            f"{run_directory} already exists and holds an earlier run's "
            f"output; a rerun never overwrites. Move or rename that "
            f"folder by hand if it is truly disposable.")
    return run_directory


def _refresh_intermediate_link(job_directory: Path, mirror: Path) -> None:
    """Point ``<job>/intermediate`` at the mirror, without destroying.

    Repointing a STALE LINK is routine — a job tree gets moved, or the
    scratch root changes between machines — so an existing symlink is
    replaced silently. An existing real file or directory is NEVER
    touched: that is someone's data sitting where the link belongs, and
    deleting it to make room for a convenience link would trade the
    user's bytes for our tidiness. Refuse and say so instead.

    MPI-SAFE. Under a parallel run EVERY rank calls this against the SAME
    project folder, so two ranks can both pass the checks below and both
    try to create the link; the loser lands on a ``FileExistsError``. A
    concurrent create that points where we wanted IS success (the same
    idempotence the ``mkdir(exist_ok=True)`` beside it already has), so it
    is accepted, not raised — otherwise a fresh project folder deadlocks
    the run (the losers halt while the winner waits at the next barrier).
    """
    link = job_directory / INTERMEDIATE_LINK_NAME
    if link.is_symlink():
        if Path(os.readlink(link)) == mirror:
            return
        link.unlink(missing_ok=True)   # repoint a stale link (race-safe)
    elif link.exists():
        raise ScratchError(
            f"{link} already exists and is NOT a symlink, so it is not "
            f"ours to replace. Move or remove it by hand if the scratch "
            f"mirror link belongs there.")
    try:
        link.symlink_to(mirror, target_is_directory=True)
    except FileExistsError:
        # A peer rank created the link between our check and here. If it
        # now points to the mirror we wanted, that is the state we were
        # after; anything else — a real file appeared — is re-raised.
        if not (link.is_symlink()
                and Path(os.readlink(link)) == mirror):
            raise


def _check_single_path_segment(label: str, value: str) -> None:
    """Reject a name that is not usable as ONE path segment.

    A stage folder's name carries the wafers' material labels, which
    come from a human-written project file, so it is untrusted as path
    material. A name of ``..`` or ``a/b`` would place a stage's scratch
    outside its project's mirror, breaking the invariant
    that every write lands under the scratch root — which is exactly the
    invariant that lets this module be trusted with a mkdir at all.
    """
    if not value or value in (".", ".."):
        raise ScratchError(
            f"{label} name {value!r} cannot be used as a directory name.")
    separators = [os.sep] + ([os.altsep] if os.altsep else [])
    if any(separator in value for separator in separators):
        raise ScratchError(
            f"{label} name {value!r} contains a path separator; it must "
            f"name a single directory, not a path.")
