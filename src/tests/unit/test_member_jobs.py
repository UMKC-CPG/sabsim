"""Unit tests for the run selector (sabsim.pipeline.member_jobs).

These prove the §14.3 property that matters most: three member jobs run
as SEPARATE calls, sharing one member scratch, hand work to each other
through on-disk artifacts alone — activate writes the assembled pair, a
fresh bond call re-reads it and writes the pull results, a fresh analyze
call re-reads both and writes the measure vector. A fake stage set stands
in for the LAMMPS stages, so the orchestration and the file hand-off are
exercised with no compute node; the stages themselves are tested
elsewhere.
"""

import os
import tomllib

import pytest
from ase import Atoms

from sabsim.deploy.registry import (
    ASSEMBLED_PAIR,
    MEASURE_VECTOR,
    PULL_RESULTS,
    JobKind,
    registry_lookup,
)
from sabsim.pipeline.exec_artifacts import (
    ActivatedSlabs,
    BondDebondResult,
    HalfHandle,
    Potential,
    PressOutcome,
    PullOutcome,
    SharedCell,
    Slab,
    Structure,
    Verdict,
)
from sabsim.pipeline.handoff import HandoffError
from sabsim.pipeline.measures import (
    Measure,
    MeasureStatus,
    MeasureVector,
    Verdicts,
)
from sabsim.pipeline.member_jobs import _select_members, run_member_job
from sabsim.pipeline.skeleton_stages import StageSet
from sabsim.spec import load_and_validate_study
from sabsim.structure.slab_builder import (
    WAFER_A_TAG,
    WAFER_B_TAG,
    BuiltPair,
    SurfaceMatch,
)

_TEMPLATE_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "dev", "templates", "study_spec.toml"))


def _member():
    """A real MemberSpecification, loaded from the study-spec template.

    Loading (not the §1.5 reference check) is all we need, so no CIF files
    have to exist — the member carries the protocol, ensemble, and
    potential_ref the analyze job's provenance and gate read.
    """
    return load_and_validate_study(_TEMPLATE_PATH).members[0]


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


def _fake_stage_set() -> StageSet:
    """A stage set whose every body returns a contract-valid record.

    No LAMMPS: each stage ignores its inputs and returns the minimal
    artifact its seam's contract accepts, so run_member_job's control flow
    and artifact hand-off can be tested on any machine.
    """
    return StageSet(
        resolve_potential=lambda member: Potential(
            kind="classical-stand-in", pair_style="sw", loadable=True),
        build=lambda *a, **k: (
            HalfHandle("a.data", {"Si": 1}, "Si", WAFER_A_TAG),
            HalfHandle("b.data", {"Si": 1}, "Si", WAFER_B_TAG),
            SharedCell(note="identity")),
        activate=lambda *a, **k: ActivatedSlabs(
            slab_a=Slab("Si", "a"), slab_b=Slab("Si", "b"),
            verdict_a=Verdict(True, "ok"), verdict_b=Verdict(True, "ok")),
        assemble=lambda *a, **k: Structure(
            note="pair", labeled_groups=("interface_z",),
            data_file=None, built=_built_pair()),
        bond_debond=lambda *a, **k: _bond_debond(),
        analyze=lambda *a, **k: MeasureVector(
            measures=(Measure(
                name="mechanical_work_of_separation", value=1.5,
                uncertainty=0.0, realization_count=1,
                unit_native="eV/angstrom^2", unit_si="J/m^2",
                fidelity="classical-stand-in", method="stub",
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


# ---------------------------------------------------------------------
# Each job writes its exit artifact; a fresh next job reads it.
# ---------------------------------------------------------------------

def test_activate_writes_the_assembled_pair(tmp_path):
    """The activate job starts from the spec and writes ASSEMBLED_PAIR."""
    result = run_member_job(
        _member(), str(tmp_path), registry_lookup("activate"),
        _fake_stage_set())
    assert result.artifact_written == ASSEMBLED_PAIR
    assert result.job_name == "activate"
    assert (tmp_path / "assembled_pair.manifest.toml").is_file()
    assert (tmp_path / "assembled_pair.atoms.extxyz").is_file()
    assert (tmp_path / "assembled_pair.data").is_file()


def test_bond_reads_the_pair_and_writes_pull_results(tmp_path):
    """A fresh bond job reconstructs the pair from disk, writes results."""
    stages = _fake_stage_set()
    run_member_job(
        _member(), str(tmp_path), registry_lookup("activate"), stages)
    result = run_member_job(
        _member(), str(tmp_path), registry_lookup("bond"), stages)
    assert result.artifact_written == PULL_RESULTS
    assert (tmp_path / "pull_results.manifest.toml").is_file()


def test_analyze_reads_both_and_writes_the_measure_vector(tmp_path):
    """A fresh analyze job reads both artifacts, writes the measures."""
    stages = _fake_stage_set()
    member = _member()
    run_member_job(member, str(tmp_path), registry_lookup("activate"),
                   stages)
    run_member_job(member, str(tmp_path), registry_lookup("bond"), stages)
    result = run_member_job(
        member, str(tmp_path), registry_lookup("analyze"), stages)

    assert result.artifact_written == MEASURE_VECTOR
    measure_file = tmp_path / "measure_vector.toml"
    assert measure_file.is_file()
    with measure_file.open("rb") as handle:
        record = tomllib.load(handle)
    assert record["member"] == member.name
    measure_names = {m["name"] for m in record["measures"]}
    assert "mechanical_work_of_separation" in measure_names


def test_three_separate_jobs_complete_the_chain(tmp_path):
    """The headline: three separate calls, one scratch, end to end.

    This is exactly what three separate submissions do — no in-memory
    object survives between them, so a chain that completes proves every
    hand-off went through the files.
    """
    stages = _fake_stage_set()
    member = _member()
    for job_name in ("activate", "bond", "analyze"):
        run_member_job(member, str(tmp_path), registry_lookup(job_name),
                       stages)
    with (tmp_path / "measure_vector.toml").open("rb") as handle:
        record = tomllib.load(handle)
    assert record["verdicts"]["bonded"] is True


# ---------------------------------------------------------------------
# The loud stops.
# ---------------------------------------------------------------------

def test_bond_without_an_assembled_pair_halts(tmp_path):
    """A bond job with no pair in scratch stops, naming the artifact."""
    with pytest.raises(HandoffError, match=ASSEMBLED_PAIR):
        run_member_job(
            _member(), str(tmp_path), registry_lookup("bond"),
            _fake_stage_set())


def test_run_member_job_rejects_an_unknown_job(tmp_path):
    """A job kind run_member_job has no sub-stage for is a loud stop."""
    phantom = JobKind(
        name="relax", resource_class="cpu", stages=("relax",),
        reads=None, writes="relaxed")
    with pytest.raises(ValueError, match="relax"):
        run_member_job(
            _member(), str(tmp_path), phantom, _fake_stage_set())


# ---------------------------------------------------------------------
# --only member selection.
# ---------------------------------------------------------------------

def test_select_members_narrows_to_a_subset():
    """--only keeps exactly the named members, in study order."""
    study = load_and_validate_study(_TEMPLATE_PATH)
    wanted = study.members[0].name
    selected = _select_members(study, [wanted])
    assert tuple(m.name for m in selected) == (wanted,)


def test_select_members_rejects_an_unknown_name():
    """--only naming a member the study lacks is a loud stop."""
    study = load_and_validate_study(_TEMPLATE_PATH)
    with pytest.raises(ValueError, match="ghost"):
        _select_members(study, ["ghost"])


def test_select_members_default_is_every_member():
    """No --only runs every member the study defines."""
    study = load_and_validate_study(_TEMPLATE_PATH)
    assert _select_members(study, None) == study.members
