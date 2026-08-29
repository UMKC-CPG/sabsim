"""Unit tests for the §3.5 gate-verdict -> report distiller (§3.5, §6).

These pin the one-way translation from the driver's rich
:class:`ActivationVerdict` (all metrics, measured depth, per-metric
detail, named failure) down to the report's small :class:`Verdict` (a flag
and a reason). Revised 2026-08-08 (§3.4): the gate moved to the bond flow,
so the distiller now takes an :class:`ActivationVerdict` DIRECTLY (no
cascade note). It is pure — no engine, no LAMMPS — so every path is
exercised here with hand-built verdicts: a clean pass, a metric failure,
the unresolved-reference case, and the two-surface gather.
"""

from sabsim.driver.activation_gate import ActivationVerdict, MetricVerdict
from sabsim.pipeline.activation_adapter import (
    activated_slabs_from_results,
    verdict_from_activation,
)
from sabsim.pipeline.exec_artifacts import ActivatedSlabs, Slab, Verdict


def _gate(passed, depth, reason, per_metric=None):
    """Build an :class:`ActivationVerdict` — the gate's per-surface output.

    Hand-made so the distiller can be tested on the exact verdict shape each
    gate path produces, without any engine.
    """
    return ActivationVerdict(
        passed=passed, activated_depth=depth,
        per_metric=per_metric or {}, reason=reason)


def test_pass_carries_depth_and_metric_count_and_passes():
    """A passing gate maps to a passing Verdict naming the depth."""
    per_metric = {
        "radial_distribution": MetricVerdict(
            "radial_distribution", 2.37, "Si stand-in", 0.30, True),
        "amorphization_depth": MetricVerdict(
            "amorphization_depth", 32.4, "Si stand-in", 20.0, True),
    }
    verdict = verdict_from_activation(_gate(True, 32.4, "", per_metric))

    assert isinstance(verdict, Verdict)
    assert verdict.passed is True
    # The reason surfaces the measured skin depth and the metric count, so
    # the report can trace how thick a skin this activation authored.
    assert "32.4 Å skin" in verdict.reason
    assert "all 2 metrics passed" in verdict.reason


def test_metric_failure_carries_the_gate_reason():
    """A failed metric maps to a failing Verdict quoting the gate reason."""
    gate_reason = ("coordination: measured 0.02 vs (0.05, 0.6) "
                   "(Si stand-in)")
    verdict = verdict_from_activation(
        _gate(False, 4.1, gate_reason))

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
        _gate(False, 0.0, gate_reason))

    # The no-defaults discipline (DESIGN §3.5) survives the map: an
    # unresolved reference can never come out the other side as a pass.
    assert verdict.passed is False
    assert gate_reason in verdict.reason


def test_no_atoms_maps_to_a_failure():
    """An empty structure ('no atoms to judge') fails, not crashes."""
    verdict = verdict_from_activation(
        _gate(False, 0.0, "no atoms to judge"))

    assert verdict.passed is False
    assert "no atoms to judge" in verdict.reason


def test_activated_slabs_gathers_both_surfaces_and_their_verdicts():
    """Two healed slabs and two §3.5 verdicts become one ACTIVATED_SLABS.

    Revised 2026-08-28: the gate runs in the activation stage again, so
    the verdicts ride the artifact the contract checks before assembly.
    """
    slab_a = Slab(identity="Si", note="bottom")
    slab_b = Slab(identity="Si", note="top")
    passed = ActivationVerdict(
        passed=True, activated_depth=7.0, per_metric={}, reason="")
    activated = activated_slabs_from_results(slab_a, slab_b, passed, passed)

    assert isinstance(activated, ActivatedSlabs)
    assert activated.slab_a is slab_a
    assert activated.slab_b is slab_b
    assert activated.verdict_a is passed and activated.verdict_b is passed
