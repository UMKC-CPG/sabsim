"""Tests for the ``sabsim`` command-line entry point (sabsim.cli).

Login-node tests only: they exercise the DRY-RUN path (the walking-
skeleton stages, no LAMMPS) and the argument handling. The live path
opens LAMMPS and is guarded to refuse running outside an allocation,
which is checked here without ever reaching the engine.
"""

from __future__ import annotations

import os

import pytest

from sabsim.cli import main
from tests.unit.support import PROJECT_TEMPLATE, project_in


@pytest.fixture
def run_home(tmp_path, monkeypatch):
    """A throwaway project folder: SABSIM_SCRATCH set, CWD moved into it.

    The project folder is where the project file sits, so a test copies
    the template in as ``sabsim.toml`` and runs from there, keeping its
    stage folders and scratch mirror isolated under ``tmp_path``.
    """
    monkeypatch.setenv("SABSIM_SCRATCH", str(tmp_path / "scratch"))
    home = tmp_path / "si_sio2"
    home.mkdir()
    monkeypatch.chdir(home)
    return home


def test_dry_run_returns_zero(run_home, capsys):
    """`sabsim run <spec> --dry-run` runs the skeleton and succeeds."""
    spec = project_in(run_home)
    assert main(["run", spec, "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "pair 'si_sio2'" in output
    assert "relation" not in output


def test_missing_spec_returns_two(run_home):
    """A spec path that does not exist is a clean error, not a traceback."""
    assert main(["run", "does_not_exist.toml", "--dry-run"]) == 2


def test_default_spec_name_is_sabsim_toml(run_home):
    """With no spec argument the command looks for sabsim.toml here."""
    # None present -> the default name is what it reports as missing.
    assert main(["run", "--dry-run"]) == 2
    # Drop a sabsim.toml in place (a copy of the template) -> it runs.
    project_in(run_home)
    assert main(["run", "--dry-run"]) == 0


def test_dry_run_lands_in_the_projects_folder(run_home, tmp_path,
                                              monkeypatch):
    """The run's home is the project file's folder, not the CWD."""
    spec = project_in(run_home)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert main(["run", spec, "--dry-run"]) == 0
    assert (run_home / "analysis_si_sio2" / "measure_vector.toml").is_file()
    assert not list(elsewhere.iterdir())


def test_live_run_off_allocation_is_refused(run_home, monkeypatch):
    """A real run (no --dry-run) outside an srun step is refused, so LAMMPS
    is never spawned on the login node."""
    monkeypatch.delenv("SLURM_PROCID", raising=False)
    assert main(["run", PROJECT_TEMPLATE]) == 2


def test_no_subcommand_prints_help_and_returns_two(capsys):
    """Bare `sabsim` prints help and exits non-zero."""
    assert main([]) == 2


def test_dry_run_does_not_combine_with_a_job_flag(run_home, capsys):
    """`--dry-run --prep-surf1` is refused: dry-run is the whole-chain
    check, a job flag a real per-job run."""
    code = main(["run", PROJECT_TEMPLATE, "--dry-run", "--prep-surf1"])
    output = capsys.readouterr().err
    assert code == 2
    assert "does not combine" in output


def test_a_job_flag_takes_the_live_path_and_is_guarded(run_home,
                                                       monkeypatch):
    """A per-job run (e.g. --bond) is a live run, so it hits the
    allocation guard and never spawns LAMMPS on the login node."""
    monkeypatch.delenv("SLURM_PROCID", raising=False)
    assert main(["run", PROJECT_TEMPLATE, "--bond"]) == 2


def test_all_four_job_flags_are_offered(run_home, monkeypatch):
    """Every registry job has its flag; each takes the guarded live path."""
    monkeypatch.delenv("SLURM_PROCID", raising=False)
    for flag in ("--prep-surf1", "--prep-surf2", "--bond", "--analysis"):
        assert main(["run", PROJECT_TEMPLATE, flag]) == 2


def test_job_flags_are_mutually_exclusive(run_home):
    """Two job flags at once is an argparse error (exits non-zero)."""
    with pytest.raises(SystemExit):
        main(["run", PROJECT_TEMPLATE, "--prep-surf1", "--bond"])


def test_only_is_gone(run_home):
    """`--only` belonged to the study-of-members design; it is refused."""
    with pytest.raises(SystemExit):
        main(["run", PROJECT_TEMPLATE, "--dry-run", "--only", "x"])


_RC_TEMPLATE = os.path.abspath(os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "share", "templates", "deployment_rc.toml"))


def test_prepare_missing_spec_returns_two(run_home):
    """`sabsim prepare` with no spec is a clean error, not a traceback."""
    assert main(["prepare", "does_not_exist.toml"]) == 2


def test_prepare_missing_rc_returns_two(run_home):
    """`sabsim prepare` with a spec but no deployment rc is a clean error."""
    project_in(run_home)
    assert main(["prepare"]) == 2          # default deployment.toml absent


def test_prepare_writes_scripts_and_guide(run_home, monkeypatch, capsys):
    """`sabsim prepare` with spec + rc + roots writes the four scripts,
    the four stage folders, and a guide into the project folder."""
    monkeypatch.setenv("SABSIM_SHARE", "/cluster/VAST/rulisp-lab/cpg")
    project_in(run_home)
    (run_home / "deployment.toml").write_text(
        open(_RC_TEMPLATE, encoding="utf-8").read())

    code = main(["prepare"])
    output = capsys.readouterr().out
    assert code == 0
    assert "wrote" in output and ".slurm" in output
    scripts = sorted(path.name for path in run_home.glob("*.slurm"))
    assert scripts == ["analysis_si_sio2.slurm", "bond_si_sio2.slurm",
                       "prep_surf1_si.library.slurm", "prep_surf1_si.slurm",
                       "prep_surf2_sio2.library.slurm",
                       "prep_surf2_sio2.slurm"]
    assert (run_home / "SUBMISSION_GUIDE.md").is_file()
    assert (run_home / "prep_surf2_sio2").is_dir()


# ---------------------------------------------------------------------
# The `command` file (ARCHITECTURE §4.2, Imago's convention).
# ---------------------------------------------------------------------

def test_the_real_entry_records_its_command_line(run_home, monkeypatch,
                                                  capsys):
    """`sabsim init .` from the console appends a dated Cmnd block."""
    from sabsim.cli import COMMAND_RECORD_FILE, record_command
    monkeypatch.setattr("sys.argv", ["sabsim", "init", "."])
    record_command()
    record_command(["sabsim", "prepare"])
    text = (run_home / COMMAND_RECORD_FILE).read_text()
    blocks = [b for b in text.split("\n\n") if b.strip()]
    assert len(blocks) == 2
    assert blocks[0].startswith("Date: ")
    assert blocks[0].endswith("Cmnd: sabsim init .")
    assert blocks[1].endswith("Cmnd: sabsim prepare")


def test_main_with_an_argument_vector_records_nothing(run_home, capsys):
    """A test or module calling main(argv) writes no `command` file."""
    from sabsim.cli import COMMAND_RECORD_FILE
    main(["init", "."])
    assert not (run_home / COMMAND_RECORD_FILE).exists()
