"""Unit tests for the Tier-A sequencer (sabsim.pipeline.sequencer).

These pin the walking skeleton's guarantees (ARCHITECTURE.md §5, wave
0): one well-formed number travels the whole eight-step pipeline for
every member; every member is marked untrusted; relations are graded
and reported; the run's record is machine-readable; and a stage that
breaks its contract HALTS the pipeline instead of poisoning it.
"""

import dataclasses
import json
import os

import pytest

from sabsim.pipeline import exec_full_study
from sabsim.pipeline.contracts import (
    POTENTIAL_CONTRACT,
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
from sabsim.spec.loader import load_and_validate_study

_TEMPLATE_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "dev", "templates", "study_spec.toml"))


# ---------------------------------------------------------------------
# The pipeline runs end to end and produces a well-formed, untrusted
# study report.
# ---------------------------------------------------------------------

def test_exec_full_study_runs_every_member():
    """Both template members run to a self-standing report."""
    report = exec_full_study(_TEMPLATE_PATH)
    assert report.study_name == "sio2-si-sab-v1"
    assert tuple(r.specification.name for r in report.member_results) == (
        "si-sio2", "si-si-reference")


def test_every_skeleton_member_is_untrusted():
    """A wave-0 member's number is plumbing, not physics (§5.3)."""
    report = exec_full_study(_TEMPLATE_PATH)
    assert all(not r.trusted for r in report.member_results)


def test_mechanical_measure_travels_the_pipeline():
    """The one real measure is present and OK; the rest unresolved."""
    report = exec_full_study(_TEMPLATE_PATH)
    measures = report.member_results[0].measures

    mechanical = measures.by_name("mechanical_work_of_separation")
    assert mechanical is not None
    assert mechanical.status is MeasureStatus.OK
    assert mechanical.value is not None
    # The higher-fidelity measures are honestly unresolved in wave 0.
    assert measures.by_name(
        "work_of_adhesion_allelectron").status is (
            MeasureStatus.UNRESOLVED)


def test_gate_reports_but_does_not_act():
    """v1's gate is a reporter; it never acts (VISION principle 5)."""
    report = exec_full_study(_TEMPLATE_PATH)
    gate = report.member_results[0].gate
    assert gate.acted is False
    assert "mechanical_work_of_separation" in gate.measures_seen


def test_ratio_relation_is_graded_and_reported():
    """The declared ratio relation produces a (untrusted) outcome."""
    report = exec_full_study(_TEMPLATE_PATH)
    assert len(report.relation_outcomes) == 1

    ratio = report.relation_outcomes[0]
    assert ratio.kind == "ratio"
    # Both members emit the same placeholder value, so the skeleton
    # ratio is 1.0 — well-formed, and correctly flagged untrusted.
    assert ratio.value == 1.0
    assert ratio.trusted is False


# ---------------------------------------------------------------------
# The run's output is machine-readable, and provenance is stamped.
# ---------------------------------------------------------------------

def test_study_record_is_json_serializable():
    """to_record emits a plain, JSON-serializable view (§6.6)."""
    report = exec_full_study(_TEMPLATE_PATH)
    record = to_record(report)
    # Round-trips through JSON without custom encoders.
    restored = json.loads(json.dumps(record))
    assert restored["study"] == "sio2-si-sab-v1"
    assert len(restored["members"]) == 2


def test_provenance_stamps_the_fingerprinted_protocol():
    """Every member result carries a protocol fingerprint (§1.6)."""
    report = exec_full_study(_TEMPLATE_PATH)
    provenance = report.member_results[0].potential
    assert provenance.protocol_fingerprint
    assert provenance.potential_kind == "classical-stand-in"
    assert provenance.master_seed == 20260713


def test_fingerprint_is_stable_and_sensitive():
    """The content fingerprint changes iff a knob changes (§1.4)."""
    study = load_and_validate_study(_TEMPLATE_PATH)
    protocol = study.members[0].protocol

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
        run_to_contract(lambda: "not a potential", POTENTIAL_CONTRACT)


def test_check_contract_names_the_failure():
    """check_contract returns a reason string for a bad artifact."""
    reason = check_contract("not a potential", POTENTIAL_CONTRACT)
    assert reason is not None
    assert "Potential" in reason


def test_merge_measures_rejects_a_name_collision():
    """Two stages emitting the same measure name is an error (§6)."""
    measure = Measure(
        name="dup", value=1.0, uncertainty=0.0, realization_count=1,
        unit_native="eV", unit_si="J", fidelity="x", method="y",
        status=MeasureStatus.OK)
    vector = MeasureVector(measures=(measure,))
    with pytest.raises(ValueError):
        merge_measures(vector, vector)
