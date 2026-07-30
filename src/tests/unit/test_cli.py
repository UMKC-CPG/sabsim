"""Tests for the ``sabsim`` command-line entry point (sabsim.cli).

Login-node tests only: they exercise the DRY-RUN path (the walking-skeleton
stages, no LAMMPS) and the argument handling. The live path opens LAMMPS and
is guarded to refuse running outside an allocation, which is checked here
without ever reaching the engine.
"""

from __future__ import annotations

import os

import pytest

from sabsim.cli import main

_TEMPLATE = os.path.abspath(os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "dev", "templates", "study_spec.toml"))


@pytest.fixture
def run_home(tmp_path, monkeypatch):
    """A throwaway run home: SABSIM_SCRATCH set, CWD moved into it.

    The command's job directory IS the current directory, so a test run
    must chdir into a scratch-backed temp dir to keep its output isolated.
    """
    monkeypatch.setenv("SABSIM_SCRATCH", str(tmp_path / "scratch"))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_dry_run_returns_zero(run_home):
    """`sabsim run <spec> --dry-run` runs the skeleton and succeeds."""
    assert main(["run", _TEMPLATE, "--dry-run"]) == 0


def test_dry_run_only_filters_and_relation_degrades(run_home, capsys):
    """`--only` runs just that member; a relation over the rest is
    reported unresolved, never a crash."""
    code = main(["run", _TEMPLATE, "--dry-run", "--only", "si-si-reference"])
    output = capsys.readouterr().out
    assert code == 0
    assert "member 'si-si-reference'" in output
    assert "member 'si-sio2'" not in output          # excluded from the run
    assert "relation" in output and "unresolved" in output


def test_missing_spec_returns_two(run_home):
    """A spec path that does not exist is a clean error, not a traceback."""
    assert main(["run", "does_not_exist.toml", "--dry-run"]) == 2


def test_default_spec_name_is_sabsim_toml(run_home):
    """With no spec argument the command looks for sabsim.toml here."""
    # None present -> the default name is what it reports as missing.
    assert main(["run", "--dry-run"]) == 2
    # Drop a sabsim.toml in place (a copy of the template) -> it runs.
    (run_home / "sabsim.toml").write_text(
        open(_TEMPLATE, encoding="utf-8").read())
    assert main(["run", "--dry-run"]) == 0


def test_live_run_off_allocation_is_refused(run_home, monkeypatch):
    """A real run (no --dry-run) outside an srun step is refused, so LAMMPS
    is never spawned on the login node."""
    monkeypatch.delenv("SLURM_PROCID", raising=False)
    assert main(["run", _TEMPLATE]) == 2


def test_no_subcommand_prints_help_and_returns_two(capsys):
    """Bare `sabsim` prints help and exits non-zero."""
    assert main([]) == 2


def test_dry_run_does_not_combine_with_a_job_flag(run_home, capsys):
    """`--dry-run --activate` is refused: dry-run is the whole-chain check.

    A single job cannot be exercised by the placeholder stages (their
    assembled pair has no built geometry to hand across a boundary), so the
    two are kept apart with a readable message rather than a deep failure.
    """
    code = main(["run", _TEMPLATE, "--dry-run", "--activate"])
    output = capsys.readouterr().err
    assert code == 2
    assert "does not combine" in output


def test_a_job_flag_takes_the_live_path_and_is_guarded(run_home,
                                                       monkeypatch):
    """A per-job run (e.g. --bond) is a live run, so it hits the
    allocation guard and never spawns LAMMPS on the login node."""
    monkeypatch.delenv("SLURM_PROCID", raising=False)
    assert main(["run", _TEMPLATE, "--bond"]) == 2


def test_job_flags_are_mutually_exclusive(run_home):
    """Two job flags at once is an argparse error (exits non-zero)."""
    with pytest.raises(SystemExit):
        main(["run", _TEMPLATE, "--activate", "--bond"])


_RC_TEMPLATE = os.path.abspath(os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "dev", "templates", "deployment_rc.toml"))


def test_prepare_missing_spec_returns_two(run_home):
    """`sabsim prepare` with no spec is a clean error, not a traceback."""
    assert main(["prepare", "does_not_exist.toml"]) == 2


def test_prepare_missing_rc_returns_two(run_home):
    """`sabsim prepare` with a spec but no deployment rc is a clean error."""
    (run_home / "sabsim.toml").write_text(
        open(_TEMPLATE, encoding="utf-8").read())
    assert main(["prepare"]) == 2          # default deployment.toml absent


def test_prepare_writes_scripts_and_guide(run_home, monkeypatch, capsys):
    """`sabsim prepare` with spec + rc + roots writes scripts and a guide."""
    monkeypatch.setenv("SABSIM_SHARE", "/cluster/VAST/rulisp-lab/cpg")
    (run_home / "sabsim.toml").write_text(
        open(_TEMPLATE, encoding="utf-8").read())
    (run_home / "deployment.toml").write_text(
        open(_RC_TEMPLATE, encoding="utf-8").read())

    code = main(["prepare"])
    output = capsys.readouterr().out
    assert code == 0
    assert "wrote" in output and ".slurm" in output
    assert list(run_home.glob("*.slurm"))
    assert (run_home / "SUBMISSION_GUIDE.md").is_file()
