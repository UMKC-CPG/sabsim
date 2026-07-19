"""Map the driver's activation result onto the pipeline contract (§10.1).

The surface-activation DRIVER (:mod:`sabsim.driver.cascade`) judges a
re-annealed slab with the full §3.5 metric gate and returns a rich
:class:`~sabsim.driver.activation_gate.ActivationVerdict` — the AND over
every metric, the MEASURED amorphization depth, the per-metric detail, and
a reason that names the first failure. The PIPELINE, one tier up, gates on
a deliberately small artifact: the :class:`~sabsim.pipeline.exec_artifacts.
Verdict` (a ``passed`` flag and a ``reason`` string) that the
``ACTIVATED_SLABS_CONTRACT`` checks at the build->activate->assemble seam.

This module is the one-way translation between them. It is the pipeline's
job, not the driver's: the driver knows physics and stays ignorant of the
contract shape, while the pipeline reads the driver's result and distils it
to the pass/fail record the contract understands (ARCHITECTURE.md §5.1,
the Tier-A calls Tier-B edge). Keeping the map here — pure, tested, with no
engine and no LAMMPS — means the eventual live ``activate_surfaces`` stage
(which opens an engine per wafer on a compute node, PSEUDOCODE.md §10.1)
only has to CALL the driver and hand its two results here; the distillation
is already settled and covered.

The ``reason`` string is not cosmetic: it is the human-readable trace that
rides the contract and lands in the report, so it carries the two facts a
reader most wants — how deep the activated skin is, and, on a failure,
which metric fell short and by how much.
"""

from __future__ import annotations

from sabsim.driver.cascade import ActivationResult
from sabsim.pipeline.exec_artifacts import ActivatedSlabs, Slab, Verdict


def verdict_from_activation(result: ActivationResult) -> Verdict:
    """Distil one surface's activation result to a contract Verdict (§10.1).

    ``result`` is what :func:`sabsim.driver.cascade.activate_surface`
    returns: the gate's :class:`ActivationVerdict` plus the cascade note
    (how many impacts were delivered). We map it to the simple
    :class:`Verdict` the ``ACTIVATED_SLABS_CONTRACT`` reads, preserving in
    the reason the measured skin depth and — on a failure — the failing
    metric that the gate already named (measured value vs threshold).

    On a PASS the reason records the depth and the delivered dose, so a
    reader sees at a glance how thick a skin this activation authored and
    under how many impacts. On a FAILURE the gate's own reason is carried
    verbatim behind the depth, because it already spells out which metric
    fell short and by how much (or that no reference resolved, or that
    there were no atoms to judge — every non-pass path the gate can take).
    """
    gate = result.verdict
    depth = gate.activated_depth
    if gate.passed:
        metric_count = len(gate.per_metric)
        return Verdict(
            passed=True,
            reason=(
                f"activated: {depth:.1f} Å skin, all {metric_count} "
                f"metrics passed ({result.cascade.note})"))
    return Verdict(
        passed=False,
        reason=(
            f"activation gate failed [{depth:.1f} Å skin]: {gate.reason}"))


def activated_slabs_from_results(
        slab_a: Slab,
        slab_b: Slab,
        result_a: ActivationResult,
        result_b: ActivationResult) -> ActivatedSlabs:
    """Assemble the ACTIVATED_SLABS artifact from both surfaces (§10.1).

    Each surface is activated INDEPENDENTLY in its own engine, before the
    two ever face each other (DESIGN.md §3.1); this gathers the two driver
    results into the single :class:`ActivatedSlabs` the contract checks,
    mapping each surface's rich gate verdict to its contract
    :class:`Verdict`. A failed verdict on EITHER surface makes the artifact
    contract-invalid, so the pipeline halts at this seam rather than
    carrying an un-activated slab downstream (DESIGN.md §10.1).
    """
    return ActivatedSlabs(
        slab_a=slab_a,
        slab_b=slab_b,
        verdict_a=verdict_from_activation(result_a),
        verdict_b=verdict_from_activation(result_b))
