"""Unit tests for the Tier-A sequencer (sabsim.pipeline.sequencer).

These pin the walking skeleton's guarantees (ARCHITECTURE.md §5, wave
0): one well-formed number travels the whole eight-step pipeline for
the project's pair; the pair is marked untrusted; the run's record is
machine-readable; the four stages hand off through the project's stage
folders; and a stage that breaks its contract HALTS the pipeline
instead of poisoning it.
"""

import dataclasses
import json
import os

import pytest

from sabsim.pipeline import exec_full_project
from sabsim.pipeline.contracts import (
    SLABS_CONTRACT,
    PipelineHalt,
    check_contract,
    run_to_contract,
)
from sabsim.pipeline.exec_artifacts import content_fingerprint
from sabsim.pipeline.measures import (
    Measure,
    MeasureStatus,
    MeasureVector,
    merge_measures,
)
from sabsim.pipeline.sequencer import to_record
from sabsim.spec.records import stage_folders
from tests.unit.support import project_in, template_pair


@pytest.fixture
def project_file(tmp_path, monkeypatch):
    """A throwaway project: the template copied in, SABSIM_SCRATCH set.

    The sequencer writes each stage's intermediates under the project's
    scratch mirror and its deliverables into the project's stage folders
    (ARCHITECTURE.md §1), so a W0 run needs a real folder and a scratch
    root. A tmp project keeps the control-flow tests login-node-runnable
    and self-contained.
    """
    monkeypatch.setenv("SABSIM_SCRATCH", str(tmp_path / "scratch"))
    home = tmp_path / "si_sio2"
    home.mkdir()
    return project_in(home)


# ---------------------------------------------------------------------
# The pipeline runs end to end and produces a well-formed, untrusted
# project report.
# ---------------------------------------------------------------------

def test_exec_full_project_runs_the_pair(project_file):
    """The project's one pair runs to a self-standing report."""
    report = exec_full_project(project_file)
    assert report.pair_label == "si_sio2"
    assert report.result.specification.pair_label == "si_sio2"
    assert "SiO2" in report.description or "Si" in report.description


def test_the_skeleton_pair_is_untrusted(project_file):
    """A wave-0 pair's number is plumbing, not physics (§5.3)."""
    report = exec_full_project(project_file)
    assert report.result.trusted is False


def test_mechanical_measure_travels_the_pipeline(project_file):
    """The one real measure is present and OK; the rest unresolved."""
    report = exec_full_project(project_file)
    measures = report.result.measures

    mechanical = measures.by_name("mechanical_work_of_separation")
    assert mechanical is not None
    assert mechanical.status is MeasureStatus.OK
    assert mechanical.value is not None
    # The higher-fidelity measures are honestly unresolved in wave 0.
    assert measures.by_name(
        "work_of_adhesion_allelectron").status is (
            MeasureStatus.UNRESOLVED)


def test_gate_reports_but_does_not_act(project_file):
    """v1's gate is a reporter; it never acts (VISION principle 5)."""
    report = exec_full_project(project_file)
    gate = report.result.gate
    assert gate.acted is False
    assert "mechanical_work_of_separation" in gate.measures_seen


def test_the_four_stage_folders_hold_the_deliverables(project_file):
    """A whole-chain run leaves each stage's deliverable in its folder
    and its bulk under the scratch mirror's run folder (§10.8)."""
    exec_full_project(project_file)
    home = os.path.dirname(project_file)
    folders = stage_folders(template_pair())
    for folder in (folders.prep_surf1, folders.prep_surf2):
        assert os.path.isfile(
            os.path.join(home, folder, "activated_half.manifest.toml"))
    assert os.path.isfile(
        os.path.join(home, folders.bond, "pull_results.manifest.toml"))
    assert os.path.isfile(
        os.path.join(home, folders.analysis, "measure_vector.toml"))
    assert os.path.islink(os.path.join(home, "intermediate"))
    mirror = os.path.join(home, "intermediate", folders.bond)
    assert any(name.startswith("run-") for name in os.listdir(mirror))


# ---------------------------------------------------------------------
# The run's output is machine-readable, and provenance is stamped.
# ---------------------------------------------------------------------

def test_project_record_is_json_serializable(project_file):
    """to_record emits a plain, JSON-serializable view (§6.6)."""
    report = exec_full_project(project_file)
    record = to_record(report)
    # Round-trips through JSON without custom encoders.
    restored = json.loads(json.dumps(record))
    assert restored["pair"] == "si_sio2"
    assert restored["result"]["pair"] == "si_sio2"
    assert "relations" not in restored


def test_provenance_stamps_the_fingerprinted_protocol(project_file):
    """The pair result carries a protocol fingerprint (§1.6)."""
    report = exec_full_project(project_file)
    provenance = report.result.potential
    assert provenance.protocol_fingerprint
    assert provenance.universal_model == "DPA-3.1-3M"
    assert provenance.production_weights.endswith("dpa3.pth")
    assert provenance.master_seed == 20260713


def test_fingerprint_is_stable_and_sensitive():
    """The content fingerprint changes iff a knob changes (§1.4)."""
    protocol = template_pair().protocol

    same = content_fingerprint(protocol)
    assert same == content_fingerprint(protocol)      # stable

    nudged = dataclasses.replace(
        protocol,
        activation_energy=dataclasses.replace(
            protocol.activation_energy, value=50.0))
    assert content_fingerprint(nudged) != same        # sensitive


# ---------------------------------------------------------------------
# The contract guard halts a broken seam instead of passing it on.
# ---------------------------------------------------------------------

def test_broken_contract_halts_the_pipeline():
    """A stage output that fails its contract raises PipelineHalt."""
    with pytest.raises(PipelineHalt):
        run_to_contract(lambda: "not slabs", SLABS_CONTRACT)


def test_check_contract_names_the_failure():
    """check_contract returns a reason string for a bad artifact."""
    reason = check_contract("not slabs", SLABS_CONTRACT)
    assert reason is not None
    assert "handle" in reason


def test_merge_measures_rejects_a_name_collision():
    """Two stages emitting the same measure name is an error (§6)."""
    measure = Measure(
        name="dup", value=1.0, uncertainty=0.0, realization_count=1,
        unit_native="eV", unit_si="J", fidelity="x", method="y",
        status=MeasureStatus.OK)
    vector = MeasureVector(measures=(measure,))
    with pytest.raises(ValueError):
        merge_measures(vector, vector)
