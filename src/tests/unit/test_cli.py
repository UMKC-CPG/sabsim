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
