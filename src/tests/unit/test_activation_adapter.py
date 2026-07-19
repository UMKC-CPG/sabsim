"""Unit tests for the activation-result -> contract adapter (§10.1).

These pin the one-way translation from the driver's rich
:class:`ActivationVerdict` (all metrics, measured depth, per-metric
detail, named failure) down to the pipeline's small
:class:`Verdict` (a flag and a reason). The adapter is pure — no engine,
no LAMMPS — so every path is exercised here with hand-built driver
results: a clean pass, a metric failure, the unresolved-reference case,
and the two-surface gather that builds the ACTIVATED_SLABS artifact.
"""

from sabsim.driver.activation_gate import ActivationVerdict, MetricVerdict
from sabsim.driver.cascade import ActivationResult, CascadeOutcome
from sabsim.pipeline.activation_adapter import (
    activated_slabs_from_results,
    verdict_from_activation,
)
from sabsim.pipeline.exec_artifacts import ActivatedSlabs, Slab, Verdict


def _result(passed, depth, reason, per_metric=None, note="6 impacts"):
    """Build an ActivationResult without running a cascade or a gate.

    Wraps a hand-made :class:`ActivationVerdict` and a stub
    :class:`CascadeOutcome`, so the adapter can be tested on the exact
    verdict shape each path produces without any engine.
    """
    verdict = ActivationVerdict(
        passed=passed, activated_depth=depth,
        per_metric=per_metric or {}, reason=reason)
    cascade = CascadeOutcome(impacts_run=6, note=note)
    return ActivationResult(verdict=verdict, cascade=cascade)


def test_pass_carries_depth_and_dose_and_passes():
    """A passing gate maps to a passing Verdict naming depth and dose."""
    per_metric = {
        "radial_distribution": MetricVerdict(
            "radial_distribution", 2.37, "Si stand-in", 0.30, True),
        "amorphization_depth": MetricVerdict(
            "amorphization_depth", 32.4, "Si stand-in", 20.0, True),
    }
    verdict = verdict_from_activation(
        _result(True, 32.4, "", per_metric, note="30 impacts of Ar"))

    assert isinstance(verdict, Verdict)
    assert verdict.passed is True
    # The reason surfaces the measured skin depth, the metric count, and
    # the cascade note (the delivered dose), so the report can trace it.
    assert "32.4 Å skin" in verdict.reason
    assert "all 2 metrics passed" in verdict.reason
    assert "30 impacts of Ar" in verdict.reason


def test_metric_failure_carries_the_gate_reason():
    """A failed metric maps to a failing Verdict quoting the gate reason."""
    gate_reason = ("coordination: measured 0.02 vs (0.05, 0.6) "
                   "(Si stand-in)")
    verdict = verdict_from_activation(
        _result(False, 4.1, gate_reason))

    assert verdict.passed is False
    # The depth still rides along (a thin skin is diagnostic), and the
    # gate's own named-failure reason is carried verbatim behind it.
    assert "4.1 Å skin" in verdict.reason
    assert gate_reason in verdict.reason
    assert verdict.reason.startswith("activation gate failed")


def test_unresolved_reference_maps_to_a_faithful_failure():
    """No reference -> a failing Verdict that says so (no silent pass)."""
    gate_reason = "no activation reference found (no share/ file for Xe)"
    verdict = verdict_from_activation(
        _result(False, 0.0, gate_reason))

    # The no-defaults discipline (DESIGN §3.5) survives the map: an
    # unresolved reference can never come out the other side as a pass.
    assert verdict.passed is False
    assert gate_reason in verdict.reason


def test_no_atoms_maps_to_a_failure():
    """An empty structure ('no atoms to judge') fails, not crashes."""
    verdict = verdict_from_activation(
        _result(False, 0.0, "no atoms to judge"))

    assert verdict.passed is False
    assert "no atoms to judge" in verdict.reason


def test_activated_slabs_gathers_both_surfaces():
    """Two results become one ACTIVATED_SLABS with both mapped verdicts."""
    slab_a = Slab(identity="Si", note="bottom")
    slab_b = Slab(identity="Si", note="top")
    activated = activated_slabs_from_results(
        slab_a, slab_b,
        _result(True, 30.0, ""),
        _result(True, 28.0, ""))

    assert isinstance(activated, ActivatedSlabs)
    assert activated.slab_a is slab_a
    assert activated.slab_b is slab_b
    assert activated.verdict_a.passed and activated.verdict_b.passed
    assert "30.0 Å skin" in activated.verdict_a.reason
    assert "28.0 Å skin" in activated.verdict_b.reason


def test_activated_slabs_carries_a_failure_through():
    """If one surface fails, its verdict rides in unaltered (contract halts).

    The adapter does not decide the halt — it faithfully records each
    surface's verdict; the ACTIVATED_SLABS_CONTRACT is what rejects the
    artifact when either verdict failed (DESIGN §10.1).
    """
    activated = activated_slabs_from_results(
        Slab(identity="Si", note="bottom"),
        Slab(identity="Si", note="top"),
        _result(True, 30.0, ""),
        _result(False, 3.0, "amorphization_depth: measured 3.0 vs 20.0"))

    assert activated.verdict_a.passed is True
    assert activated.verdict_b.passed is False
    assert "amorphization_depth" in activated.verdict_b.reason
