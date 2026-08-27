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

    # The DEFAULT activate is the universal cascade — a GPU job that runs the
    # deepmd bundle out-of-process (§4.1, §3.4 cascade-only).
    assert "#SBATCH --partition=gpu,requeue" in text          # gpu partition name
    assert "#SBATCH --account=general" in text            # default_account
    assert "#SBATCH --nodes=1" in text                # activate nodes
    assert "#SBATCH --ntasks-per-node=1" in text      # one rank, one GPU
    assert "#SBATCH --mem=48G" in text                # activate memory 48 GB
    assert "#SBATCH --gres=gpu:H100:1" in text        # one H100 (gpu_type)
    assert "#SBATCH --time=12:00:00" in text          # activate walltime 12h
    assert "module use /cluster/VAST/rulisp-lab/cpg/modulefiles" in text
    # NO in-process LAMMPS module: the engine is the deepmd bundle, reached
    # out-of-process by the env below, not `module load`.
    assert "module load cpg_lammps" not in text
    # The per-kind [usage.activate.environment] rides as `export` lines; NO
    # LAMMPS_POTENTIALS (activate is cascade-only, §3.4), and NO model
    # choice — which model runs is the study file's [potential] block.
    assert "export SABSIM_CASCADE_ENGINE_PREFIX=" in text
    assert "SABSIM_CASCADE_MLIP_MODEL" not in text
    assert "SABSIM_ALLOW_UNVALIDATED_POTENTIAL" not in text
    assert "LAMMPS_POTENTIALS" not in text
    assert 'export SABSIM_SHARE="/cluster/VAST/rulisp-lab/cpg"' in text
    # The launcher clears the mutually-exclusive memory exports first, or
    # the nested daemon launch aborts (ARCHITECTURE §4.1).
    assert "unset SLURM_MEM_PER_NODE SLURM_MEM_PER_CPU SLURM_MEM_PER_GPU" \
        in text
    assert f"--activate --only {member}" in text
    assert f"{member}_bond.slurm" in text            # the "submit next" hint


def test_bond_script_is_gpu(roots_set, tmp_path):
    """The bond script routes to the GPU partition and the deepmd engine."""
    prepare(_SPEC, _RC, tmp_path)
    member = _members()[0]
    text = (tmp_path / f"{member}_bond.slurm").read_text()

    assert "#SBATCH --partition=gpu,requeue" in text
    assert "#SBATCH --ntasks-per-node=1" in text      # one rank, one GPU
    assert "#SBATCH --gres=gpu:H100:1" in text       # the committee of one
    assert "#SBATCH --mem=32G" in text               # bond memory 32 GB
    assert "#SBATCH --time=18:00:00" in text         # bond walltime 18h
    assert "module load cpg_lammps_conda/2024.08.29-deepmd" in text
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


def test_per_kind_environment_is_exported_in_sorted_order(
        roots_set, tmp_path):
    """An [usage.<kind>.environment] table becomes `export` lines (§4.4).

    This is how the universal-cascade activate job points
    SABSIM_CASCADE_ENGINE_PREFIX at the deepmd bundle. The template ends in
    the analyze block, so the env table appended here lands on analyze; the
    exports appear in that job's script, sorted for a deterministic script.
    """
    with open(_RC, encoding="utf-8") as rc_file:
        rc_text = rc_file.read()
    rc_text += '\n[usage.analyze.environment]\nZED = "z"\nALPHA = "a"\n'
    rc_path = tmp_path / "rc_with_env.toml"
    rc_path.write_text(rc_text, encoding="utf-8")

    prepare(_SPEC, str(rc_path), tmp_path)
    text = (tmp_path / f"{_members()[0]}_analyze.slurm").read_text()

    assert 'export ALPHA="a"' in text
    assert 'export ZED="z"' in text
    # Sorted: ALPHA before ZED, so the emitted script is stable.
    assert text.index('export ALPHA="a"') < text.index('export ZED="z"')
    # A block with no environment table emits no such block: the activate
    # script (no environment here) carries none of these.
    activate = (tmp_path / f"{_members()[0]}_activate.slurm").read_text()
    assert "export ALPHA=" not in activate


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


def test_gpus_over_partition_stops_before_writing(roots_set, tmp_path):
    """A per-kind GPU request over its partition's count is refused (§10.6)."""
    # The gpu partition has 4 gpus_per_node; ask the GPU jobs (which
    # state "gpus_per_node  = 1", two spaces) for 8 each.
    rc_text = open(_RC, encoding="utf-8").read().replace(
        "gpus_per_node  = 1", "gpus_per_node  = 8")
    rc = tmp_path / "deployment.toml"
    rc.write_text(rc_text, encoding="utf-8")

    with pytest.raises(DeploymentError, match="over the"):
        prepare(_SPEC, rc, tmp_path)
    assert not list(tmp_path.glob("*.slurm"))


def test_dump_visuals_rides_every_generated_run_line(roots_set, tmp_path):
    """`prepare --dump-visuals` puts the flag on each job's run line."""
    entries = prepare(_SPEC, _RC, tmp_path, dump_visuals=True)
    for entry in entries:
        text = (tmp_path / entry.script_name).read_text()
        assert "--dump-visuals" in text
    plain = prepare(_SPEC, _RC, tmp_path, dump_visuals=False)
    assert all("--no-dump-visuals" in (tmp_path / e.script_name).read_text()
               for e in plain)
