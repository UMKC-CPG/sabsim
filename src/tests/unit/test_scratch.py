"""Unit tests for the scratch mirror tree (deploy.scratch).

These exercise the mirror-tree pattern with no cluster and no LAMMPS:
tmp_path stands in for both the project tree and the scratch root, and
``$SABSIM_SCRATCH``/``$HOME`` are pointed at it. The cases worth having
are the ones where being wrong costs something real — refusing to
destroy a directory that is not ours, refusing a stage-folder name that
would escape the scratch root, and never letting a rerun land on top
of an earlier run's output (PSEUDOCODE.md §14.3).
"""

import os
from pathlib import Path

import pytest

from sabsim.deploy.scratch import (
    INTERMEDIATE_LINK_NAME,
    RUN_SUBFOLDER_PREFIX,
    ScratchError,
    deliverable_directory,
    job_scratch,
    mirror_path,
    run_subfolder,
    scratch_root,
    stage_scratch,
)


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    """A fake home + scratch root, and a project folder inside the home."""
    home = tmp_path / "home"
    scratch = tmp_path / "scratch"
    job = home / "sabsim" / "jobs" / "si_sio2"
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
    """The project's path under $HOME becomes its key under the root."""
    mirror = mirror_path(deployment["job"])
    expected = deployment["scratch"] / "sabsim" / "jobs" / "si_sio2"
    assert mirror == expected


def test_mirror_path_creates_nothing(deployment):
    """Computing a mirror path is pure — a dry run must be free."""
    mirror = mirror_path(deployment["job"])
    assert not mirror.exists()


def test_nested_project_directories_keep_their_nesting(deployment):
    """`jobs/` may nest; the key preserves it rather than flattening.

    Two projects sharing a leaf name under different groupings must not
    collide, which is the whole reason the key is the path (see the
    module docstring) rather than the project's own name.
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


def test_stage_scratch_repeats_the_projects_folder_names(deployment):
    """The mirror holds the project's own stage folders, nothing else.

    No study or pair key sits between the mirror and the stage folder
    (the earlier keying doubled the project's name inside its mirror);
    ``intermediate/<stage>`` and ``<project>/<stage>`` are one name.
    """
    stage = stage_scratch(deployment["job"], "bond_si_sio2")
    assert stage.is_dir()
    assert stage == job_scratch(deployment["job"]) / "bond_si_sio2"
    link = deployment["job"] / INTERMEDIATE_LINK_NAME
    assert (link / "bond_si_sio2").resolve() == stage.resolve()


def test_deliverable_directory_lives_in_the_project(deployment):
    """Deliverables go beside the project file, not on scratch (§14.3)."""
    folder = deliverable_directory(deployment["job"], "analysis_si_sio2")
    assert folder == deployment["job"].resolve() / "analysis_si_sio2"
    assert folder.is_dir()
    assert not str(folder).startswith(str(deployment["scratch"]))


def test_deliverable_directory_leaves_an_existing_folder_alone(deployment):
    """A prep folder already holding a library is kept exactly as is."""
    prepared = deployment["job"] / "prep_surf1_si"
    prepared.mkdir()
    (prepared / "environment_library.toml").write_text("kept")
    folder = deliverable_directory(deployment["job"], "prep_surf1_si")
    assert (folder / "environment_library.toml").read_text() == "kept"


@pytest.mark.parametrize("bad_name", ["..", ".", "", "a/b", "../escape"])
def test_a_name_that_would_escape_the_root_is_refused(
        deployment, bad_name):
    """Stage-folder names carry human-typed labels: untrusted as paths.

    A folder named `..` would put a stage's scratch outside the
    project's mirror, breaking the one invariant (everything lands under
    the scratch root) that makes this module safe to hand a mkdir to.
    """
    with pytest.raises(ScratchError):
        stage_scratch(deployment["job"], bad_name)
    with pytest.raises(ScratchError):
        deliverable_directory(deployment["job"], bad_name)


def test_run_subfolder_is_named_by_the_scheduler_job(
        deployment, monkeypatch):
    """Under the scheduler the run folder carries the job id (§14.3)."""
    monkeypatch.setenv("SLURM_JOB_ID", "16871414")
    stage = stage_scratch(deployment["job"], "bond_si_sio2")
    run = run_subfolder(stage)
    assert run == stage / f"{RUN_SUBFOLDER_PREFIX}16871414"
    assert run.is_dir()


def test_run_subfolder_off_the_scheduler_is_dated(deployment, monkeypatch):
    """With no scheduler the run folder carries a readable timestamp."""
    monkeypatch.delenv("SLURM_JOB_ID", raising=False)
    stage = stage_scratch(deployment["job"], "bond_si_sio2")
    run = run_subfolder(stage)
    assert run.parent == stage
    assert run.name.startswith(RUN_SUBFOLDER_PREFIX)
    stamp = run.name[len(RUN_SUBFOLDER_PREFIX):]
    assert len(stamp) == len("20260830-120000") and stamp[8] == "-"


def test_a_rerun_never_overwrites_an_earlier_run(deployment, monkeypatch):
    """A run folder that already holds output is refused, not reused.

    The earlier run's bytes are the evidence a comparison is made against
    (DESIGN §10.8); the second attempt must go beside it.
    """
    monkeypatch.setenv("SLURM_JOB_ID", "777")
    stage = stage_scratch(deployment["job"], "bond_si_sio2")
    first = run_subfolder(stage)
    (first / "log.press").write_text("an earlier run's output")
    with pytest.raises(ScratchError, match="never overwrites"):
        run_subfolder(stage)
    assert (first / "log.press").read_text() == "an earlier run's output"


def test_a_peer_ranks_fresh_run_folder_is_accepted(deployment, monkeypatch):
    """Under MPI every rank asks for the same run folder; empty = ours.

    The first rank makes it, the others find it EMPTY and take it as
    this run's — the same idempotence the intermediate link has.
    """
    monkeypatch.setenv("SLURM_JOB_ID", "778")
    stage = stage_scratch(deployment["job"], "bond_si_sio2")
    first = run_subfolder(stage)
    assert run_subfolder(stage) == first


def test_a_missing_project_directory_is_an_error(deployment):
    """Scratch mirrors a project that exists; it does not invent one."""
    with pytest.raises(ScratchError, match="does not exist"):
        job_scratch(deployment["home"] / "no" / "such" / "job")
