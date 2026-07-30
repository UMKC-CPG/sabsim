"""Unit tests for the scratch mirror tree (deploy.scratch).

These exercise the mirror-tree pattern with no cluster and no LAMMPS:
tmp_path stands in for both the project tree and the scratch root, and
``$SABSIM_SCRATCH``/``$HOME`` are pointed at it. The cases worth having
are the ones where being wrong costs something real — refusing to
destroy a directory that is not ours, and refusing a spec-supplied name
that would escape the scratch root.
"""

import os
from pathlib import Path

import pytest

from sabsim.deploy.scratch import (
    INTERMEDIATE_LINK_NAME,
    ScratchError,
    job_scratch,
    member_scratch,
    mirror_path,
    scratch_root,
)


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    """A fake home + scratch root, and a job directory inside the home."""
    home = tmp_path / "home"
    scratch = tmp_path / "scratch"
    job = home / "CPG" / "cpg-repo" / "sabsim" / "jobs" / "bulk_si"
    job.mkdir(parents=True)
    scratch.mkdir()
    monkeypatch.setenv("SABSIM_SCRATCH", str(scratch))
    monkeypatch.setenv("HOME", str(home))
    return {"home": home, "scratch": scratch, "job": job}


def test_scratch_root_is_never_guessed(monkeypatch):
    """An unset SABSIM_SCRATCH is an error, not a plausible default."""
    monkeypatch.delenv("SABSIM_SCRATCH", raising=False)
    with pytest.raises(ScratchError, match="not set"):
        scratch_root()


def test_mirror_key_is_the_path_below_home(deployment):
    """The job's path under $HOME becomes its key under the root."""
    mirror = mirror_path(deployment["job"])
    expected = (deployment["scratch"] / "CPG" / "cpg-repo" / "sabsim"
                / "jobs" / "bulk_si")
    assert mirror == expected


def test_mirror_path_creates_nothing(deployment):
    """Computing a mirror path is pure — a dry run must be free."""
    mirror = mirror_path(deployment["job"])
    assert not mirror.exists()


def test_nested_job_directories_keep_their_nesting(deployment):
    """`jobs/` may nest; the key preserves it rather than flattening.

    Two jobs sharing a leaf name under different groupings must not
    collide, which is the whole reason the key is the path (see the
    module docstring) rather than the job's own name.
    """
    first = deployment["home"] / "CPG" / "jobs" / "2026-07" / "run"
    second = deployment["home"] / "CPG" / "jobs" / "2026-08" / "run"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    assert mirror_path(first) != mirror_path(second)


def test_job_scratch_creates_the_mirror_and_links_it(deployment):
    """The mirror exists and `intermediate` points at it."""
    mirror = job_scratch(deployment["job"])
    link = deployment["job"] / INTERMEDIATE_LINK_NAME

    assert mirror.is_dir()
    assert link.is_symlink()
    assert Path(os.readlink(link)) == mirror
    assert link.resolve() == mirror.resolve()


def test_job_scratch_is_idempotent(deployment):
    """Safe to call at the top of every run."""
    first = job_scratch(deployment["job"])
    second = job_scratch(deployment["job"])
    assert first == second


def test_a_stale_link_is_repointed(deployment):
    """A link left over from another root is replaced, not honored."""
    link = deployment["job"] / INTERMEDIATE_LINK_NAME
    link.symlink_to(deployment["scratch"] / "somewhere-old")

    mirror = job_scratch(deployment["job"])
    assert Path(os.readlink(link)) == mirror


def test_intermediate_link_survives_a_concurrent_create(
        deployment, monkeypatch):
    """A peer rank creating the link first must not crash us (MPI race).

    This reproduces the deadlock the deployment three-job smoke exposed:
    on a FRESH job directory every MPI rank races to create
    ``intermediate``, and the losers hit ``FileExistsError``. The winner's
    link is exactly the state we wanted, so ``job_scratch`` must accept it
    rather than raise — otherwise the losing ranks halt while the winner
    waits at the next collective, and the run hangs. Simulated here by a
    ``symlink_to`` that creates the link (a peer) THEN raises, exactly the
    order a real race produces.
    """
    job = deployment["job"]
    mirror = mirror_path(job)
    real_symlink_to = Path.symlink_to

    def racing_symlink_to(self, target, target_is_directory=False):
        real_symlink_to(
            self, target, target_is_directory=target_is_directory)
        raise FileExistsError(17, "File exists")

    monkeypatch.setattr(Path, "symlink_to", racing_symlink_to)

    # Must not raise, and the link must end up pointing at the mirror.
    assert job_scratch(job) == mirror
    link = job / INTERMEDIATE_LINK_NAME
    assert link.is_symlink()
    assert Path(os.readlink(link)) == mirror


def test_a_real_directory_in_the_way_is_never_destroyed(deployment):
    """`intermediate` as a real directory is data, not ours to delete.

    The whole module exists to be trusted with mkdir and symlink; the
    moment it deletes something a user put there, it is not.
    """
    real = deployment["job"] / INTERMEDIATE_LINK_NAME
    real.mkdir()
    (real / "precious.dat").write_text("someone's data")

    with pytest.raises(ScratchError, match="NOT a symlink"):
        job_scratch(deployment["job"])
    assert (real / "precious.dat").read_text() == "someone's data"


def test_member_scratch_keys_by_study_then_member(deployment):
    """Inside a job the key is identity, not path."""
    member = member_scratch(deployment["job"], "sab-v1", "si-sio2")
    assert member.is_dir()
    assert member == job_scratch(deployment["job"]) / "sab-v1" / "si-sio2"


@pytest.mark.parametrize("bad_name", ["..", ".", "", "a/b", "../escape"])
def test_a_name_that_would_escape_the_root_is_refused(
        deployment, bad_name):
    """Spec-supplied names are untrusted as path material.

    A member named `..` would put its scratch outside the job's mirror,
    breaking the one invariant (everything lands under the scratch root)
    that makes this module safe to hand a mkdir to.
    """
    with pytest.raises(ScratchError):
        member_scratch(deployment["job"], "sab-v1", bad_name)


def test_a_missing_job_directory_is_an_error(deployment):
    """Scratch mirrors a job that exists; it does not invent one."""
    with pytest.raises(ScratchError, match="does not exist"):
        job_scratch(deployment["home"] / "no" / "such" / "job")
