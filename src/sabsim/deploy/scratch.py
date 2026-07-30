"""Where a run's bulky intermediates live (ARCHITECTURE.md §4.1).

A run produces far more bytes than it produces insight: LAMMPS data
files, strided trajectory dumps, per-phase logs. Those belong on the
cluster's scratch filesystem — "large trajectories go on scratch, not
home" (§4.1). But a scratch path is long, machine-specific, and easy to
lose track of, so this module follows the MIRROR-TREE pattern this
group's other codes already use (imago, olcao): scratch holds a mirror
of the project's own directory layout, and each job directory holds a
symlink named ``intermediate`` pointing into it.

That buys two things at once. The job directory stays small and legible
while the bytes live where the sysadmins want them; and a reader who
lands in a job directory follows ONE obvious link to the data instead of
reconstructing a path from memory. A scratch directory nothing points at
is an orphan — it survives only as long as someone remembers it exists.

**Keyed by path down to the job, then by study and member inside it.**
The mirror is keyed by the job directory's PATH, because ``jobs/`` may
nest several levels before the job itself (``jobs/2026-07/si-ladder/``)
and that nesting is the researcher's own organisation: flattening it to
a bare job name would collide across groups and would throw the grouping
away. WITHIN a job the key changes to study and member, because that is
the identity the pipeline iterates over and the manifest records — a
path cannot express "member 3 of study X" without inventing a naming
convention that the spec already has.

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
from pathlib import Path

# The deployment variable naming the per-user, write-heavy, regenerable
# tier of the three roots (§4.1): SABSIM_SCRATCH (here), SABSIM_SHARE
# (group, read-mostly, authoritative), SABSIM_LOCAL (personal override).
SCRATCH_ROOT_VARIABLE = "SABSIM_SCRATCH"

# The link's name inside each job directory. Deliberately the SAME word
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


def mirror_path(job_directory) -> Path:
    """The scratch path mirroring ``job_directory`` — no side effects.

    The job's path relative to ``$HOME`` becomes the key under the
    scratch root, so ``~/CPG/cpg-repo/sabsim/jobs/bulk_si`` mirrors to
    ``$SABSIM_SCRATCH/CPG/cpg-repo/sabsim/jobs/bulk_si``. A job tree
    living OUTSIDE ``$HOME`` still gets a mirror: its absolute path is
    used as the key with the leading separator dropped. That keeps the
    one invariant that matters — every byte lands under the scratch root
    — at the cost of a longer path.

    The job side IS resolved before the key is taken, because ``$HOME``
    and the project can reach the same directory by different routes
    (here ``$HOME`` is ``/home/<user>`` while the repo sits under
    ``/cluster/pixstor/home/<user>``); without resolving both, the job
    would not appear to be under the home at all.

    Pure: it computes a path and creates nothing, so a caller can report
    where output WOULD go (a dry run, an error message) without touching
    the filesystem.
    """
    job = Path(job_directory).expanduser().resolve()
    home = Path.home().resolve()
    try:
        relative_key = job.relative_to(home)
    except ValueError:
        relative_key = Path(*job.parts[1:])
    return scratch_root() / relative_key


def job_scratch(job_directory) -> Path:
    """Create a job's scratch mirror, link it, and return the mirror.

    Idempotent: safe to call at the top of every run. Returns the
    RESOLVED mirror path for the manifest to record (see the module
    docstring on why the link is not the record).
    """
    job = Path(job_directory).expanduser().resolve()
    if not job.is_dir():
        raise ScratchError(
            f"job directory {job} does not exist (or is not a "
            f"directory); create it before asking for its scratch.")
    mirror = mirror_path(job)
    mirror.mkdir(parents=True, exist_ok=True)
    _refresh_intermediate_link(job, mirror)
    return mirror


def member_scratch(job_directory, study_name: str,
                   member_name: str) -> Path:
    """The scratch directory for ONE member of ONE study.

    Inside a job the key is identity, not path: ``<mirror>/<study>/
    <member>``. Creates the directory (and the job's mirror and link, if
    needed) and returns the resolved absolute path.
    """
    _check_single_path_segment("study", study_name)
    _check_single_path_segment("member", member_name)
    member_directory = job_scratch(job_directory) / study_name / member_name
    member_directory.mkdir(parents=True, exist_ok=True)
    return member_directory


def _refresh_intermediate_link(job_directory: Path, mirror: Path) -> None:
    """Point ``<job>/intermediate`` at the mirror, without destroying.

    Repointing a STALE LINK is routine — a job tree gets moved, or the
    scratch root changes between machines — so an existing symlink is
    replaced silently. An existing real file or directory is NEVER
    touched: that is someone's data sitting where the link belongs, and
    deleting it to make room for a convenience link would trade the
    user's bytes for our tidiness. Refuse and say so instead.

    MPI-SAFE. Under a parallel run EVERY rank calls this against the SAME
    job directory, so two ranks can both pass the checks below and both
    try to create the link; the loser lands on a ``FileExistsError``. A
    concurrent create that points where we wanted IS success (the same
    idempotence the ``mkdir(exist_ok=True)`` beside it already has), so it
    is accepted, not raised — otherwise a fresh job directory deadlocks
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

    Study and member names come from a human-written spec, so they are
    untrusted as path material. A name of ``..`` or ``a/b`` would place
    a member's scratch outside its job's mirror, breaking the invariant
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
