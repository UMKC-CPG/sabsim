"""Unit tests for the run selector (sabsim.pipeline.pair_jobs).

These prove the §14.3 property that matters most: the four pair jobs
run as SEPARATE calls, and hand work to each other through on-disk
deliverables in the project's stage folders alone — each prep job
writes its activated half into its own prep folder, a fresh bond call
reads both, checks they were built in the same shared cell, and writes
the pull results into the bond folder, and a fresh analysis call reads
those and writes the measure vector into the analysis folder. A fake
stage set stands in for the LAMMPS stages, so the orchestration and
the file hand-off are exercised with no compute node; the stages
themselves are tested elsewhere.
"""

import dataclasses
import tomllib

import pytest
from ase import Atoms

from sabsim.deploy.registry import (
    ACTIVATED_HALF,
    MEASURE_VECTOR,
    PULL_RESULTS,
    JobKind,
    registry_lookup,
)
from sabsim.driver.activation_gate import ActivationVerdict
from sabsim.pipeline.exec_artifacts import (
    ActivatedHalf,
    BondDebondResult,
    DerivedLattices,
    HalfHandle,
    PressOutcome,
    PullOutcome,
    SharedCell,
    Slab,
    Structure,
)
from sabsim.pipeline.handoff import HandoffError
from sabsim.pipeline.measures import (
    Measure,
    MeasureStatus,
    MeasureVector,
    Verdicts,
)
from sabsim.pipeline.pair_jobs import run, run_pair_job
from sabsim.pipeline.skeleton_stages import StageSet
from sabsim.spec.loader import load_and_validate_project
from sabsim.spec.records import stage_folders
from sabsim.structure.slab_builder import (
    WAFER_A_TAG,
    WAFER_B_TAG,
    BuiltPair,
    SurfaceMatch,
)
from tests.unit.support import project_in


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A throwaway project folder: the template copied in, scratch set.

    Stage folders and their scratch mirrors are made under ``tmp_path``
    as the jobs run, so every test starts from an empty project.
    """
    monkeypatch.setenv("SABSIM_SCRATCH", str(tmp_path / "scratch"))
    home = tmp_path / "si_sio2"
    home.mkdir()
    project_in(home)
    return load_and_validate_project(home / "sabsim.toml")


def _built_pair() -> BuiltPair:
    """A small complete BuiltPair the fake assemble stage returns."""
    atoms = Atoms(
        symbols=["Si", "Si", "O"],
        positions=[[0.0, 0.0, 2.0], [1.5, 1.5, 3.0], [0.5, 0.5, 9.0]],
        cell=[[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 20.0]],
        pbc=(True, True, False))
    atoms.set_tags([WAFER_A_TAG, WAFER_A_TAG, WAFER_B_TAG])
    return BuiltPair(
        atoms=atoms, interface_z=6.0,
        wafer_a_z_range=(2.0, 3.0), wafer_b_z_range=(9.0, 9.0),
        type_map={"Si": 1, "O": 2},
        match=SurfaceMatch(
            residual_strain=0.0, match_area=16.0, is_identity=True),
        initial_gap_adjustment=0.0)


def _bond_debond() -> BondDebondResult:
    """A one-rung pull result the fake bond stage returns."""
    return BondDebondResult(
        press=PressOutcome(bonded=True, note="held"),
        reference_ok=True,
        pulls=(PullOutcome(
            rate_value=1.0e-4, rate_unit="1/ps", note="separated",
            complete=True, separation_index=1,
            grip_displacement=(0.0, 1.0), force_vs_grip=(0.1, 0.0),
            atoms_conserved=True, bridges_at_separation=0),))


# A passing placeholder verdict: the ACTIVATED_HALF_CONTRACT halts on a
# missing or failed §3.5 verdict, so the stub must carry one.
_PASSED = ActivationVerdict(
    passed=True, activated_depth=0.0, per_metric={}, reason="stub")


def _fake_stage_set(shared_note: str = "identity") -> StageSet:
    """A stage set whose every body returns a contract-valid record.

    No LAMMPS: each stage ignores its inputs and returns the minimal
    artifact its seam's contract accepts, so run_pair_job's control flow
    and deliverable hand-off can be tested on any machine. The shared
    cell's note is a knob so a test can make the two prep jobs
    disagree.
    """
    return StageSet(
        derive_lattices=lambda *a, **k: DerivedLattices(
            cells={"Si": ((5.43, 0.0, 0.0), (0.0, 5.43, 0.0),
                          (0.0, 0.0, 5.43))},
            provenance="stub"),
        build=lambda *a, **k: (
            HalfHandle("a.data", {"Si": 1}, "Si", WAFER_A_TAG),
            HalfHandle("b.data", {"Si": 1}, "Si", WAFER_B_TAG),
            SharedCell(note=shared_note)),
        activate_surface=lambda handle, shared, *a, **k: ActivatedHalf(
            slab=Slab("Si", "healed stub"), verdict=_PASSED,
            wafer_tag=handle.wafer_tag, shared=shared),
        assemble=lambda *a, **k: Structure(
            note="pair", labeled_groups=("interface_z",),
            data_file=None, built=_built_pair()),
        bond_debond=lambda *a, **k: _bond_debond(),
        analyze=lambda *a, **k: MeasureVector(
            measures=(Measure(
                name="mechanical_work_of_separation", value=1.5,
                uncertainty=0.0, realization_count=1,
                unit_native="eV/angstrom^2", unit_si="J/m^2",
                fidelity="stand-in", method="stub",
                status=MeasureStatus.OK),),
            verdicts=Verdicts(bonded=True, contact_quality=None)),
        characterize=lambda *a, **k: MeasureVector(
            measures=(Measure(
                name="characterization_stub", value=None,
                uncertainty=None, realization_count=1, unit_native="",
                unit_si="", fidelity="mock", method="wave-4",
                status=MeasureStatus.UNRESOLVED),),
            verdicts=None),
    )


def _job(project, name, stages=None):
    """Run one job of the project under the fake stages."""
    return run_pair_job(project, registry_lookup(name),
                        stages or _fake_stage_set())


# ---------------------------------------------------------------------
# Each job writes its deliverable into its own stage folder; a fresh
# next job reads it from there.
# ---------------------------------------------------------------------

def test_a_prep_job_writes_its_activated_half_into_its_folder(project):
    """prep_surf1 starts from the project file and writes ACTIVATED_HALF
    into prep_surf1_si/ — and touches no other stage folder."""
    folders = stage_folders(project.pair)
    home = project.project_directory
    result = _job(project, "prep_surf1")
    assert result.artifact_written == ACTIVATED_HALF
    assert result.job_name == "prep_surf1"
    assert result.deliverable_directory.endswith(folders.prep_surf1)
    manifest = (f"{home}/{folders.prep_surf1}/"
                "activated_half.manifest.toml")
    with open(manifest, "rb") as handle:
        record = tomllib.load(handle)
    assert record["wafer_tag"] == WAFER_A_TAG
    assert record["run_id"].startswith("run-")
    assert not (f"{home}/{folders.prep_surf2}/"
                "activated_half.manifest.toml").startswith("never")
    import os
    assert not os.path.exists(
        f"{home}/{folders.prep_surf2}/activated_half.manifest.toml")


def test_the_two_prep_jobs_are_independent(project):
    """prep_surf2 runs with no prep_surf1 before it (Approach C)."""
    result = _job(project, "prep_surf2")
    folders = stage_folders(project.pair)
    assert result.deliverable_directory.endswith(folders.prep_surf2)


def test_bond_reads_both_halves_and_writes_pull_results(project):
    """A fresh bond job reconstructs both halves from their prep folders
    and leaves the pull results (and the assembled pair) in bond_/."""
    _job(project, "prep_surf1")
    _job(project, "prep_surf2")
    result = _job(project, "bond")
    folders = stage_folders(project.pair)
    assert result.artifact_written == PULL_RESULTS
    bond_folder = f"{project.project_directory}/{folders.bond}"
    import os
    assert os.path.isfile(f"{bond_folder}/pull_results.manifest.toml")
    assert os.path.isfile(f"{bond_folder}/assembled_pair.manifest.toml")


def test_analysis_reads_the_bond_folder_and_writes_the_measures(project):
    """A fresh analysis job reads bond_/ and writes the measure vector
    into analysis_/, naming the pair."""
    for name in ("prep_surf1", "prep_surf2", "bond"):
        _job(project, name)
    result = _job(project, "analysis")
    assert result.artifact_written == MEASURE_VECTOR
    folders = stage_folders(project.pair)
    measure_file = (f"{project.project_directory}/{folders.analysis}/"
                    "measure_vector.toml")
    with open(measure_file, "rb") as handle:
        record = tomllib.load(handle)
    assert record["pair"] == "si_sio2"
    measure_names = {m["name"] for m in record["measures"]}
    assert "mechanical_work_of_separation" in measure_names
    assert record["verdicts"]["bonded"] is True


def test_four_separate_jobs_complete_the_chain(project):
    """The headline: four separate calls, end to end, files only.

    This is exactly what four separate submissions do — no in-memory
    object survives between them, so a chain that completes proves
    every hand-off went through the stage folders.
    """
    stages = _fake_stage_set()
    for name in ("prep_surf1", "prep_surf2", "bond", "analysis"):
        run_pair_job(project, registry_lookup(name), stages)
    folders = stage_folders(project.pair)
    import os
    assert os.path.isfile(
        f"{project.project_directory}/{folders.analysis}/"
        "measure_vector.toml")


def test_reruns_never_overwrite_an_earlier_run(project, monkeypatch):
    """A second run of a stage gets its own run-<id> folder; the first
    run's bulk folder is left untouched (Paul, 2026-08-30)."""
    from sabsim.deploy.scratch import stage_scratch
    folders = stage_folders(project.pair)
    monkeypatch.setenv("SLURM_JOB_ID", "111")
    _job(project, "prep_surf1")
    monkeypatch.setenv("SLURM_JOB_ID", "222")
    _job(project, "prep_surf1")
    stage_home = stage_scratch(project.project_directory,
                               folders.prep_surf1)
    runs = sorted(path.name for path in stage_home.iterdir()
                  if path.name.startswith("run-"))
    assert runs == ["run-111", "run-222"]


def test_prep_derives_lattices_and_passes_them_to_build(project):
    """Regression: a prep job must run derive_lattices (step 2b) and hand
    its result to build in the DerivedLattices slot (commit cf92d30)."""
    seen = {}

    def _checking_build(pair, lattices, scratch, comm=None):
        seen["lattices_type"] = type(lattices).__name__
        seen["scratch"] = scratch
        return (
            HalfHandle("a.data", {"Si": 1}, "Si", WAFER_A_TAG),
            HalfHandle("b.data", {"Si": 1}, "Si", WAFER_B_TAG),
            SharedCell(note="identity"))

    stages = dataclasses.replace(_fake_stage_set(), build=_checking_build)
    _job(project, "prep_surf1", stages)
    assert seen["lattices_type"] == "DerivedLattices"
    assert "run-" in seen["scratch"]          # the fresh run subfolder


# ---------------------------------------------------------------------
# The loud stops.
# ---------------------------------------------------------------------

def test_bond_without_both_halves_halts(project):
    """A bond job missing a prep deliverable stops, naming the artifact."""
    _job(project, "prep_surf1")
    with pytest.raises(HandoffError, match=ACTIVATED_HALF):
        _job(project, "bond")


def test_bond_refuses_halves_from_different_shared_cells(project):
    """Two halves not built in the same cell are refused before assembly."""
    _job(project, "prep_surf1", _fake_stage_set("identity"))
    _job(project, "prep_surf2", dataclasses.replace(
        _fake_stage_set(),
        build=lambda *a, **k: (
            HalfHandle("a.data", {"Si": 1}, "Si", WAFER_A_TAG),
            HalfHandle("b.data", {"Si": 1}, "Si", WAFER_B_TAG),
            SharedCell(note="other", residual_strain=0.02,
                       match_area=40.0, is_identity=False))))
    with pytest.raises(HandoffError, match="same shared cell"):
        _job(project, "bond")


def test_run_pair_job_rejects_an_unknown_job(project):
    """A job kind run_pair_job has no stage for is a loud stop."""
    phantom = JobKind(
        name="relax", usage_key="relax", resource_class="cpu",
        folder_key="bond", stages=("relax",), reads=(), writes="relaxed",
        depends_on=())
    with pytest.raises(ValueError, match="relax"):
        run_pair_job(project, phantom, _fake_stage_set())


def test_run_with_a_flag_returns_one_job_result(project):
    """`run` with a job flag runs exactly that job for the one pair.

    The bond flag is used because a prep job is (rightly) held to the
    environment libraries by the phase-three check, and this throwaway
    project has none; bond never opens the gate, so it is not.
    """
    _job(project, "prep_surf1")
    _job(project, "prep_surf2")
    result = run(f"{project.project_directory}/sabsim.toml",
                 project.project_directory, _fake_stage_set(),
                 job_flag="bond")
    assert result.job_name == "bond"
    assert result.pair_label == "si_sio2"


def test_run_holds_a_prep_job_to_the_environment_library(project):
    """A prep job without its surface's library is refused on the login
    node, naming the prep folder (DESIGN §1.5, phase three)."""
    from sabsim.spec.loader import SpecificationError
    with pytest.raises(SpecificationError, match="prep_surf1_si"):
        run(f"{project.project_directory}/sabsim.toml",
            project.project_directory, _fake_stage_set(),
            job_flag="prep_surf1")
