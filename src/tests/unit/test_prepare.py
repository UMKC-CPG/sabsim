"""Unit tests for the prepare writer (sabsim.deploy.prepare).

These pin §14.4/§14.5 against the real deployment template and a small
one-pair project file written into ``tmp_path``: one lean script per
job of the registry, NAMED after the stage folder it fills, in
submission order; the four stage folders made (and an existing one left
alone); the scheduler directives and modules filled from the rc; the
roots baked in; the guide rendered as the dependency graph with the
chained ``afterok`` form; and NOT the transitional env the throwaway
scripts carried. Both login-node gates — an unset root and a walltime
over its ceiling — stop before any file is written.
"""

import os

import pytest

from sabsim.deploy import DeploymentError, prepare
from sabsim.deploy.prepare import GUIDE_FILENAME

_TEMPLATES = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "share", "templates"))
_RC = os.path.join(_TEMPLATES, "deployment_rc.toml")
_REPO = os.path.abspath(os.path.join(_TEMPLATES, "..", ".."))

# A complete one-pair project file (DESIGN.md §1.4: nothing hidden), Si on
# wafer A and alpha-quartz silica on wafer B, with the knob values the
# shipped template carries. Written into a fresh project folder by the
# fixture below so the loader's ``project_directory`` is that folder.
_PROJECT_TEXT = f'''
[project]
description     = "Cold SAB of alpha-quartz SiO2 to Si(100), a test project"
potential_ref   = "PENDING-BOOTSTRAP"
material_domain = "silicon-and-silica"

[wafer_a]
material  = "Si"
cif       = "{_REPO}/share/catalog/si_diamond_100/si_diamond.cif"
structure = "diamond"
face      = [1, 0, 0]

[wafer_b]
material  = "SiO2"
cif       = "{_REPO}/share/catalog/sio2_quartz_001/sio2_alpha_quartz.cif"
structure = "alpha-quartz"
face      = [0, 0, 1]

[potential]
universal_model    = "DPA-3.1-3M"
universal_weights  = "$SABSIM_SHARE/share/models/dpa/dpa3.pth"
production_weights = "$SABSIM_SHARE/share/models/dpa/dpa3.pth"
allow_unvalidated  = true

[protocol.activation]
mechanism          = "bombardment"
species            = "Ar"
cospecies          = "none"
cospecies_fraction = 0.0
energy  = {{ value = 75.0, unit = "eV" }}
angle   = {{ value = 0.0, unit = "deg" }}
fluence = {{ value = 0.025, unit = "ions/angstrom^2" }}
required_activated_depth  = {{ value = 7.0, unit = "angstrom" }}
cascade_duration          = {{ value = 0.5, unit = "ps" }}
between_impact_relaxation = {{ value = 0.5, unit = "ps" }}

[protocol.reanneal]
hold_temperature = {{ value = 500.0, unit = "K" }}
hold_duration    = {{ value = 2.0, unit = "ps" }}
ensemble         = "nvt"

[protocol.assembly]
initial_gap = {{ value = 7.0, unit = "angstrom" }}

[protocol.press]
mode          = "load"
pressure      = {{ value = 1.0, unit = "MPa" }}
temperature   = {{ value = 300.0, unit = "K" }}
duration      = {{ value = 150.0, unit = "ps" }}
depth         = {{ value = 5.0, unit = "angstrom" }}
approach_rate = {{ value = 1.0, unit = "m/s" }}

[protocol.pull]
separation_speed = {{ value = 3.2, unit = "m/s" }}

[numerical]
md_timestep      = {{ value = 1.0, unit = "fs" }}
cascade_timestep = {{ value = 0.1, unit = "fs" }}
langevin_damping = {{ value = 0.5, unit = "ps" }}
pull_rate_ladder = [
  {{ value = 1.0, unit = "m/s" }},
  {{ value = 3.2, unit = "m/s" }},
  {{ value = 10.0, unit = "m/s" }},
]
force_average_window   = {{ value = 0.5, unit = "angstrom" }}
frame_stride           = 100
noise_floor            = {{ value = 0.05, unit = "eV/angstrom" }}
misfit_tolerance       = 0.02
max_coincidence_area   = {{ value = 400.0, unit = "angstrom^2" }}
target_footprint_area  = {{ value = 1475.0, unit = "angstrom^2" }}
minimum_bulk_thickness = {{ value = 30.0, unit = "angstrom" }}
slab_thickness         = {{ value = 55.0, unit = "angstrom" }}
slab_vacuum            = {{ value = 30.0, unit = "angstrom" }}
bulk_cells_per_axis    = 3
clash_floor            = {{ value = 1.8, unit = "angstrom" }}
contact_grid_spacing   = {{ value = 5.0, unit = "angstrom" }}
contact_gap_threshold  = {{ value = 2.5, unit = "angstrom" }}
contact_gap_window     = 3
contact_stress_floor   = {{ value = 500.0, unit = "bar" }}
contact_stress_window  = 5
control_interval       = {{ value = 1.0, unit = "ps" }}
press_time_budget      = {{ value = 500.0, unit = "ps" }}
settle_duration        = {{ value = 20.0, unit = "ps" }}
depth_bin_width        = {{ value = 2.0, unit = "angstrom" }}
disorder_scatter_multiple = 3.0
bonded_contact_threshold  = 0.5
reference_pe_drift     = {{ value = 0.001, unit = "eV/atom" }}

[ensemble]
master_seed         = 20260713
amorphization_count = 3
velocity_count      = 1
'''

# The four stage-folder names the fixture pair yields (labels lower-cased).
_PREP_1 = "prep_surf1_si"
_PREP_2 = "prep_surf2_sio2"
_BOND = "bond_si_sio2"
_ANALYSIS = "analysis_si_sio2"


@pytest.fixture
def roots_set(monkeypatch, tmp_path):
    """Set the two required roots (and clear the optional override)."""
    monkeypatch.setenv("SABSIM_SCRATCH", str(tmp_path / "scratch"))
    monkeypatch.setenv("SABSIM_SHARE", "/cluster/VAST/rulisp-lab/cpg")
    monkeypatch.delenv("SABSIM_LOCAL", raising=False)


@pytest.fixture
def project(tmp_path):
    """A fresh project folder holding the one-pair ``sabsim.toml``."""
    folder = tmp_path / "si_sio2"
    folder.mkdir()
    spec = folder / "sabsim.toml"
    spec.write_text(_PROJECT_TEXT, encoding="utf-8")
    return {"folder": folder, "spec": str(spec)}


def test_writes_four_scripts_named_by_stage_folder_plus_guide(
        roots_set, project):
    """One script per registry job, named `<stage folder>.slurm`, after
    the two library builds named `<prep folder>.library.slurm`."""
    entries = prepare(project["spec"], _RC)

    assert [e.job_name for e in entries] == [
        "library_surf1", "library_surf2",
        "prep_surf1", "prep_surf2", "bond", "analysis"]
    assert [e.script_name for e in entries] == [
        f"{_PREP_1}.library.slurm", f"{_PREP_2}.library.slurm",
        f"{_PREP_1}.slurm", f"{_PREP_2}.slurm",
        f"{_BOND}.slurm", f"{_ANALYSIS}.slurm"]
    # Each prep is held on its own surface's library build (§10.2).
    by_name = {e.job_name: e for e in entries}
    assert by_name["prep_surf1"].depends_on == ("library_surf1",)
    assert by_name["prep_surf2"].depends_on == ("library_surf2",)
    assert by_name["library_surf1"].depends_on == ()
    for entry in entries:
        assert (project["folder"] / entry.script_name).is_file()
    assert (project["folder"] / GUIDE_FILENAME).is_file()


def test_scripts_land_in_the_project_folder_by_default(roots_set, project):
    """With no directory given, the project file's folder is the home."""
    prepare(project["spec"], _RC)
    assert (project["folder"] / f"{_BOND}.slurm").is_file()


def test_the_four_stage_folders_are_made(roots_set, project):
    """`prepare` makes the stage folders the scripts will fill (§14.4)."""
    prepare(project["spec"], _RC)
    for name in (_PREP_1, _PREP_2, _BOND, _ANALYSIS):
        assert (project["folder"] / name).is_dir()


def test_an_existing_prep_folder_is_left_alone(roots_set, project):
    """A prepared surface's library survives `prepare` untouched."""
    prepared = project["folder"] / _PREP_1
    prepared.mkdir()
    (prepared / "environment_library.toml").write_text("kept")
    prepare(project["spec"], _RC)
    assert (prepared / "environment_library.toml").read_text() == "kept"


def test_prep_script_directives_and_run_line(roots_set, project):
    """A prep script fills directives from [usage.prep] and runs its job."""
    prepare(project["spec"], _RC)
    text = (project["folder"] / f"{_PREP_1}.slurm").read_text()

    # The DEFAULT prep is the universal cascade — a GPU job that runs the
    # deepmd bundle out-of-process (§4.1, §3.4).
    assert f"#SBATCH --job-name={_PREP_1}" in text     # folder = job name
    assert "#SBATCH --partition=gpu,requeue" in text   # partition name
    assert "#SBATCH --account=general" in text         # default_account
    assert "#SBATCH --nodes=1" in text                 # prep nodes
    assert "#SBATCH --ntasks-per-node=1" in text       # one rank, one GPU
    assert "#SBATCH --mem=48G" in text                 # prep memory 48 GB
    assert "#SBATCH --gres=gpu:H100:1" in text         # one H100 (gpu_type)
    assert "#SBATCH --time=12:00:00" in text           # prep walltime 12h
    assert "module use /cluster/VAST/rulisp-lab/cpg/modulefiles" in text
    # NO in-process LAMMPS module: the engine is the deepmd bundle, reached
    # out-of-process by the env below, not `module load`.
    assert "module load cpg_lammps" not in text
    # The per-kind [usage.prep.environment] rides as `export` lines; NO
    # LAMMPS_POTENTIALS, and NO model choice — which model runs is the
    # project file's [potential] block.
    assert "export SABSIM_CASCADE_ENGINE_PREFIX=" in text
    assert "SABSIM_CASCADE_MLIP_MODEL" not in text
    assert "SABSIM_ALLOW_UNVALIDATED_POTENTIAL" not in text
    assert "LAMMPS_POTENTIALS" not in text
    assert 'export SABSIM_SHARE="/cluster/VAST/rulisp-lab/cpg"' in text
    # The launcher clears the mutually-exclusive memory exports first, or
    # the nested daemon launch aborts (ARCHITECTURE §4.1).
    assert "unset SLURM_MEM_PER_NODE SLURM_MEM_PER_CPU SLURM_MEM_PER_GPU" \
        in text
    assert f'cd "{project["folder"]}"' in text          # home = project
    assert f"{project['spec']} --prep-surf1 --dump-visuals" in text
    assert "--only" not in text                        # one pair, no --only
    # The "submit next" hint: bond, but only once the OTHER prep is done.
    assert f"{_BOND}.slurm" in text
    assert "prep_surf2 has also finished" in text


def test_both_preps_share_the_prep_usage_block(roots_set, project):
    """prep_surf2 reads the same [usage.prep] block as prep_surf1."""
    prepare(project["spec"], _RC)
    text = (project["folder"] / f"{_PREP_2}.slurm").read_text()
    assert f"#SBATCH --job-name={_PREP_2}" in text
    assert "#SBATCH --time=12:00:00" in text
    assert "export SABSIM_CASCADE_ENGINE_PREFIX=" in text
    assert "--prep-surf2" in text
    assert "prep_surf1 has also finished" in text


def test_bond_script_is_gpu(roots_set, project):
    """The bond script routes to the GPU partition and the deepmd engine."""
    prepare(project["spec"], _RC)
    text = (project["folder"] / f"{_BOND}.slurm").read_text()

    assert f"#SBATCH --job-name={_BOND}" in text
    assert "#SBATCH --partition=gpu,requeue" in text
    assert "#SBATCH --ntasks-per-node=1" in text       # one rank, one GPU
    assert "#SBATCH --gres=gpu:H100:1" in text         # the committee of one
    assert "#SBATCH --mem=32G" in text                 # bond memory 32 GB
    assert "#SBATCH --time=18:00:00" in text           # bond walltime 18h
    assert "module load cpg_lammps_conda/deepmd-kit-3.2.0b0" in text
    # The bond job's own venv is activated AFTER the module (§4.4).
    assert 'source "/cluster/VAST/rulisp-lab/cpg/virtual_envs/sabsim-dp3' \
        '/bin/activate"' in text
    assert text.index("module load") < text.index("source \"")
    assert "--bond --dump-visuals" in text
    assert f"then submit: sbatch {_ANALYSIS}.slurm" in text


def test_analysis_is_terminal_and_loads_no_science_module(
        roots_set, project):
    """Analysis has no next job and loads no module (v1, DESIGN §10.5)."""
    prepare(project["spec"], _RC)
    text = (project["folder"] / f"{_ANALYSIS}.slurm").read_text()

    assert "#SBATCH --time=04:00:00" in text           # analysis walltime 4h
    assert "module load" not in text                   # analysis modules = []
    assert "--analysis" in text
    assert "chain is complete" in text                 # terminal, no next


def test_scripts_are_lean_no_transitional_env(roots_set, project):
    """(A) faithful to §10.5: no PYTHONPATH / LAMMPS_POTENTIALS in a script.

    The interpreter, launcher, and potentials come from the activated
    install, so a faithful script does NOT restate them — unlike the
    throwaway jobs/* scripts.
    """
    prepare(project["spec"], _RC)
    text = (project["folder"] / f"{_PREP_1}.slurm").read_text()
    assert "PYTHONPATH" not in text
    assert "LAMMPS_POTENTIALS" not in text


def test_guide_reads_as_the_dependency_graph(roots_set, project):
    """The guide says preps first (together), bond after both, analysis.

    It also prints the chained `sbatch --dependency=afterok:...` form,
    naming both prep ids for bond and the bond id for analysis (§14.4).
    """
    prepare(project["spec"], _RC)
    guide = (project["folder"] / GUIDE_FILENAME).read_text()

    assert "si_sio2" in guide                          # the pair label
    assert "a test project" in guide                   # the description
    assert f"1. `sbatch {_PREP_1}.library.slurm`" in guide
    assert f"2. `sbatch {_PREP_2}.library.slurm`" in guide
    assert "in either order, or together" in guide
    assert f"3. `sbatch {_PREP_1}.slurm`" in guide
    assert f"after `{_PREP_1}.library.slurm` has finished" in guide
    assert f"4. `sbatch {_PREP_2}.slurm`" in guide
    assert f"5. `sbatch {_BOND}.slurm`" in guide
    assert (f"after `{_PREP_1}.slurm` and `{_PREP_2}.slurm` have "
            f"finished") in guide
    assert f"6. `sbatch {_ANALYSIS}.slurm`" in guide
    assert f"after `{_BOND}.slurm` has finished" in guide
    # The chained form, with the scheduler holding each job for the
    # ones it depends on — the library builds first.
    assert (f"library_surf1_id=$(sbatch --parsable "
            f"{_PREP_1}.library.slurm)") in guide
    assert (f"prep_surf1_id=$(sbatch --parsable --dependency=afterok:"
            f"$library_surf1_id {_PREP_1}.slurm)") in guide
    assert ("bond_id=$(sbatch --parsable --dependency=afterok:"
            f"$prep_surf1_id:$prep_surf2_id {_BOND}.slurm)") in guide
    assert ("analysis_id=$(sbatch --parsable --dependency=afterok:"
            f"$bond_id {_ANALYSIS}.slurm)") in guide


def test_per_kind_environment_is_exported_in_sorted_order(
        roots_set, project, tmp_path):
    """An [usage.<kind>.environment] table becomes `export` lines (§4.4).

    This is how the universal-cascade prep jobs point
    SABSIM_CASCADE_ENGINE_PREFIX at the deepmd bundle. An env table
    appended to the analysis block lands in the analysis script, sorted
    for a deterministic script; a block with no environment emits none.
    """
    with open(_RC, encoding="utf-8") as rc_file:
        rc_text = rc_file.read()
    rc_text += '\n[usage.analysis.environment]\nZED = "z"\nALPHA = "a"\n'
    rc_path = tmp_path / "rc_with_env.toml"
    rc_path.write_text(rc_text, encoding="utf-8")

    prepare(project["spec"], str(rc_path))
    text = (project["folder"] / f"{_ANALYSIS}.slurm").read_text()

    assert 'export ALPHA="a"' in text
    assert 'export ZED="z"' in text
    # Sorted: ALPHA before ZED, so the emitted script is stable.
    assert text.index('export ALPHA="a"') < text.index('export ZED="z"')
    bond = (project["folder"] / f"{_BOND}.slurm").read_text()
    assert "export ALPHA=" not in bond


def test_roots_gate_stops_before_writing(monkeypatch, project, tmp_path):
    """An unset required root stops prepare before any script is written."""
    monkeypatch.setenv("SABSIM_SCRATCH", str(tmp_path))
    monkeypatch.delenv("SABSIM_SHARE", raising=False)
    with pytest.raises(DeploymentError, match="SABSIM_SHARE"):
        prepare(project["spec"], _RC)
    assert not list(project["folder"].glob("*.slurm"))


def test_walltime_over_ceiling_stops_before_writing(
        roots_set, project, tmp_path):
    """A per-kind walltime over its partition ceiling is refused (§10.6)."""
    # prep runs on the gpu partition (ceiling 24h); ask for 100h.
    rc_text = open(_RC, encoding="utf-8").read().replace(
        "value = 12.0", "value = 100.0")
    rc = tmp_path / "deployment.toml"
    rc.write_text(rc_text, encoding="utf-8")

    with pytest.raises(DeploymentError, match="over the"):
        prepare(project["spec"], rc)
    assert not list(project["folder"].glob("*.slurm"))


def test_gpus_over_partition_stops_before_writing(
        roots_set, project, tmp_path):
    """A per-kind GPU request over its partition's count is refused (§10.6)."""
    # The gpu partition has 4 gpus_per_node; ask the GPU jobs (which
    # state "gpus_per_node  = 1", two spaces) for 8 each.
    rc_text = open(_RC, encoding="utf-8").read().replace(
        "gpus_per_node  = 1", "gpus_per_node  = 8")
    rc = tmp_path / "deployment.toml"
    rc.write_text(rc_text, encoding="utf-8")

    with pytest.raises(DeploymentError, match="over the"):
        prepare(project["spec"], rc)
    assert not list(project["folder"].glob("*.slurm"))


def test_dump_visuals_rides_every_generated_run_line(roots_set, project):
    """`prepare --dump-visuals` puts the flag on each PAIR job's run line.

    The library builds are bootstrap runs, not `sabsim run`, so the
    flag does not apply to them.
    """
    def pair_jobs(entries):
        return [e for e in entries if not e.job_name.startswith("library")]
    entries = prepare(project["spec"], _RC, dump_visuals=True)
    assert len(pair_jobs(entries)) == 4
    for entry in pair_jobs(entries):
        text = (project["folder"] / entry.script_name).read_text()
        assert "--dump-visuals" in text
    plain = prepare(project["spec"], _RC, dump_visuals=False)
    assert all("--no-dump-visuals" in
               (project["folder"] / e.script_name).read_text()
               for e in pair_jobs(plain))


def test_library_build_runs_the_bootstrap_in_the_prep_folder(
        roots_set, project):
    """The `.library` script: prep resources, prep-folder home, bootstrap
    run line, and a refusal to overwrite an existing library (§10.2)."""
    prepare(project["spec"], _RC)
    text = (project["folder"] / f"{_PREP_2}.library.slurm").read_text()
    assert f"#SBATCH --job-name={_PREP_2}.library" in text
    assert "#SBATCH --gres=gpu:H100:1" in text          # the prep block
    assert f'cd "{project["folder"] / _PREP_2}"' in text
    assert 'if [ -f "environment_library.toml" ]; then' in text
    assert "exit 0" in text
    assert "python -m sabsim bootstrap generate" in text
    assert "recipe.toml --skip-collection2" in text
    assert "sabsim run" not in text
    assert f"then submit: sbatch {_PREP_2}.slurm" in text
