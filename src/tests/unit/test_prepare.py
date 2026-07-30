"""Unit tests for the prepare writer (sabsim.deploy.prepare).

These pin §14.4/§14.5 against the real templates: one lean script per
(member, job) in submission order, the scheduler directives and modules
filled from the rc, the roots baked in, and NOT the transitional env the
throwaway scripts carry (the (A) faithful form). Both login-node gates —
an unset root and a walltime over its ceiling — stop before any file is
written.
"""

import os

import pytest

from sabsim.deploy import DeploymentError, prepare
from sabsim.deploy.prepare import GUIDE_FILENAME
from sabsim.spec import load_and_validate_study

_TEMPLATES = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "dev", "templates"))
_SPEC = os.path.join(_TEMPLATES, "study_spec.toml")
_RC = os.path.join(_TEMPLATES, "deployment_rc.toml")


@pytest.fixture
def roots_set(monkeypatch, tmp_path):
    """Set the two required roots (and clear the optional override)."""
    monkeypatch.setenv("SABSIM_SCRATCH", str(tmp_path / "scratch"))
    monkeypatch.setenv("SABSIM_SHARE", "/cluster/VAST/rulisp-lab/cpg")
    monkeypatch.delenv("SABSIM_LOCAL", raising=False)


def _members():
    return [m.name for m in load_and_validate_study(_SPEC).members]


def test_writes_three_scripts_per_member_plus_guide(roots_set, tmp_path):
    """One script per (member, job), in registry order, plus the guide."""
    entries = prepare(_SPEC, _RC, tmp_path)

    assert len(entries) == 3 * len(_members())
    assert [e.job_name for e in entries[:3]] == [
        "activate", "bond", "analyze"]
    for entry in entries:
        assert (tmp_path / entry.script_name).is_file()
        assert entry.script_name.endswith(".slurm")
    assert (tmp_path / GUIDE_FILENAME).is_file()


def test_activate_script_directives_and_run_line(roots_set, tmp_path):
    """The activate script fills directives from the rc and runs the job."""
    prepare(_SPEC, _RC, tmp_path)
    member = _members()[0]
    text = (tmp_path / f"{member}_activate.slurm").read_text()

    assert "#SBATCH --partition=general" in text     # cpu partition name
    assert "#SBATCH --account=cpg" in text           # default_account
    assert "#SBATCH --nodes=2" in text               # activate nodes
    assert "#SBATCH --ntasks-per-node=32" in text    # activate tasks_per_node
    assert "#SBATCH --time=12:00:00" in text         # activate walltime 12h
    assert "module use /cluster/VAST/rulisp-lab/cpg/modulefiles" in text
    assert "module load cpg_lammps/22Jul2025" in text
    assert 'export SABSIM_SHARE="/cluster/VAST/rulisp-lab/cpg"' in text
    assert f"--activate --only {member}" in text
    assert f"{member}_bond.slurm" in text            # the "submit next" hint


def test_bond_script_is_gpu(roots_set, tmp_path):
    """The bond script routes to the GPU partition and the deepmd engine."""
    prepare(_SPEC, _RC, tmp_path)
    member = _members()[0]
    text = (tmp_path / f"{member}_bond.slurm").read_text()

    assert "#SBATCH --partition=gpu" in text
    assert "#SBATCH --ntasks-per-node=4" in text     # bond tasks_per_node
    assert "#SBATCH --time=18:00:00" in text         # bond walltime 18h
    assert "module load cpg_lammps/2024.08.29-deepmd" in text
    assert f"--bond --only {member}" in text


def test_analyze_is_terminal_and_loads_no_science_module(
        roots_set, tmp_path):
    """Analyze has no next job and loads no module (v1, DESIGN §10.5)."""
    prepare(_SPEC, _RC, tmp_path)
    member = _members()[0]
    text = (tmp_path / f"{member}_analyze.slurm").read_text()

    assert "#SBATCH --time=04:00:00" in text         # analyze walltime 4h
    assert "module load" not in text                 # analyze modules = []
    assert "chain is complete" in text               # terminal, no next


def test_scripts_are_lean_no_transitional_env(roots_set, tmp_path):
    """(A) faithful to §10.5: no PYTHONPATH / LAMMPS_POTENTIALS in a script.

    The interpreter, launcher, and potentials come from the activated
    install, so a faithful script does NOT restate them — unlike the
    throwaway jobs/* scripts.
    """
    prepare(_SPEC, _RC, tmp_path)
    member = _members()[0]
    text = (tmp_path / f"{member}_activate.slurm").read_text()
    assert "PYTHONPATH" not in text
    assert "LAMMPS_POTENTIALS" not in text


def test_roots_gate_stops_before_writing(monkeypatch, tmp_path):
    """An unset required root stops prepare before any script is written."""
    monkeypatch.setenv("SABSIM_SCRATCH", str(tmp_path))
    monkeypatch.delenv("SABSIM_SHARE", raising=False)
    with pytest.raises(DeploymentError, match="SABSIM_SHARE"):
        prepare(_SPEC, _RC, tmp_path)
    assert not list(tmp_path.glob("*.slurm"))


def test_walltime_over_ceiling_stops_before_writing(roots_set, tmp_path):
    """A per-kind walltime over its partition ceiling is refused (§10.6)."""
    # activate runs on the cpu partition (ceiling 48h); ask for 100h.
    rc_text = open(_RC, encoding="utf-8").read().replace(
        "value = 12.0", "value = 100.0")
    rc = tmp_path / "deployment.toml"
    rc.write_text(rc_text, encoding="utf-8")

    with pytest.raises(DeploymentError, match="over the"):
        prepare(_SPEC, rc, tmp_path)
    assert not list(tmp_path.glob("*.slurm"))
