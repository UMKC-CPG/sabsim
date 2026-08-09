"""The seam guard and the contracts it enforces (PSEUDOCODE.md §1).

Every pipeline stage is routed through one guard, ``run_to_contract``.
The sequencer never calls a stage and hopes: it runs the stage, then
refuses to let the pipeline advance unless the stage's output satisfies
the contract the NEXT stage depends on, halting loudly instead of
passing a bad artifact downstream (ARCHITECTURE.md §4.1, §5.1). This is
the "gate, don't warn" rule that the prior-art failure of quoting an
incomplete run as a result would have been caught by (DESIGN.md §5.7).

A contract here is a name plus a validator: a function that inspects an
artifact and returns a failure reason, or None if the artifact is good.
The validators are shape checks in W0 — the depth-first schema detail is
a later concern (PSEUDOCODE.md §1) — but the guard around them is the
permanent structure.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sabsim.pipeline.exec_artifacts import (
    ActivatedSlabs,
    BondDebondResult,
    DerivedLattices,
    HalfHandle,
    Potential,
    SharedCell,
    Structure,
)
from sabsim.pipeline.measures import MeasureStatus, MeasureVector


class PipelineHalt(Exception):
    """Raised when a stage produces a contract-invalid artifact.

    Halting is deliberate: a contract-invalid artifact stops the whole
    pipeline (ARCHITECTURE.md §4.1) rather than corrupting every stage
    downstream. The message names the seam and the reason.
    """


@dataclass(frozen=True)
class Contract:
    """A named check on the artifact passing one seam (PSEUDOCODE §1)."""

    name: str
    validate: Callable[[object], str | None]   # returns a reason, or None


def check_contract(artifact: object, contract: Contract) -> str | None:
    """Return the contract's failure reason for ``artifact``, or None."""
    return contract.validate(artifact)


def halt_pipeline(reason: str) -> None:
    """Stop the pipeline at a broken seam, loudly (ARCHITECTURE §4.1)."""
    raise PipelineHalt(reason)


def run_to_contract(work: Callable[[], object], contract: Contract):
    """Run one stage, then hold its output to the next stage's contract.

    ``work`` is a zero-argument callable — the stage with its inputs
    already supplied, written ``lambda: stage(args)`` at the call site,
    so a stage of any arity fits this one guard signature. If the result
    fails ``contract`` the pipeline halts; otherwise the artifact is
    returned for the next stage.
    """
    artifact = work()
    failure = check_contract(artifact, contract)
    if failure is not None:
        halt_pipeline(f"contract '{contract.name}' not met: {failure}")
    return artifact


# ---------------------------------------------------------------------
# The named contracts referenced at the sequencer's call sites. Each is
# the shape the NEXT stage depends on (PSEUDOCODE.md §1).
# ---------------------------------------------------------------------

def _validate_potential(artifact: object) -> str | None:
    """A usable potential the member can load (POTENTIAL_CONTRACT, §1)."""
    if not isinstance(artifact, Potential):
        return "expected a Potential artifact"
    if not artifact.loadable:
        return "potential is not loadable"
    if not artifact.pair_style:
        return "potential has no pair_style interface"
    return None


def _validate_derived_lattices(artifact: object) -> str | None:
    """A model-relaxed cell per material (DERIVED_LATTICES_CONTRACT, §2.2).

    The lattice-derivation step feeds the build the conventional cell each
    material relaxed to under the current model; the build cuts slabs on it
    rather than the CIF's published scale. The contract only checks the
    handoff is well-formed and non-empty — which material each cell belongs
    to is the build's lookup, and physical fidelity is the §7 gate's.
    """
    if not isinstance(artifact, DerivedLattices):
        return "expected a DerivedLattices artifact"
    if not artifact.cells:
        return "no derived lattice for any material"
    return None


def _validate_slabs(artifact: object) -> str | None:
    """Two half-handles plus their shared cell (SLABS_CONTRACT, §7.1).

    build_halves emits two STANDALONE halves on disk as HalfHandles (the
    build->amorphize file handoff, ARCHITECTURE §4.3), not the assembled
    pair; each handle must name a data file and declare the beam species in
    its type map, so the activation stage can create projectiles against it.
    """
    if not (isinstance(artifact, tuple) and len(artifact) == 3):
        return "expected (handle_a, handle_b, shared_cell)"
    handle_a, handle_b, shared = artifact
    for label, handle in (("A", handle_a), ("B", handle_b)):
        if not isinstance(handle, HalfHandle):
            return f"half {label} must be a HalfHandle artifact"
        if not handle.data_file:
            return f"half {label} names no data file on disk"
        if not handle.type_map:
            return f"half {label} declares no species type map"
    if not isinstance(shared, SharedCell):
        return "missing the shared coincidence cell"
    return None


def _validate_activated(artifact: object) -> str | None:
    """Both slabs amorphized (ACTIVATED, §10.1, revised 2026-08-08).

    The §3.5 gate no longer rides this seam — it moved to the bond flow
    (DESIGN §3.4), which gates each healed surface before pressing. So this
    checks only that the artifact carries both amorphized slabs; the
    pass/fail halt is now in the bond flow.
    """
    if not isinstance(artifact, ActivatedSlabs):
        return "expected an ActivatedSlabs artifact"
    if artifact.slab_a is None or artifact.slab_b is None:
        return "an activated slab is missing"
    return None


def _validate_structure(artifact: object) -> str | None:
    """An assembled pair with labeled groups (STRUCTURE_CONTRACT, §3)."""
    if not isinstance(artifact, Structure):
        return "expected a Structure artifact"
    if not artifact.labeled_groups:
        return "structure carries no labeled groups"
    return None


def _validate_bond_debond(artifact: object) -> str | None:
    """A gated press plus at least one pull (BOND_DEBOND, §9.1, §3.4)."""
    if not isinstance(artifact, BondDebondResult):
        return "expected a BondDebondResult artifact"
    # The §3.5 activation gate moved into the bond flow (§3.4, revised
    # 2026-08-08): a failed healed-surface verdict halts HERE, before the
    # press is trusted. Checked FIRST so the halt reason is the gate's own,
    # not a downstream symptom. When absent (the retired narrow-gap path or a
    # skeleton stub that never gated) it is simply not enforced.
    for surface, verdict in (("A", artifact.activation_a),
                             ("B", artifact.activation_b)):
        if verdict is not None and not verdict.passed:
            return (f"surface {surface} failed the §3.5 activation gate: "
                    f"{verdict.reason}")
    if artifact.press is None:
        return "no press outcome recorded"
    if not artifact.pulls:
        return "the pull-rate ladder produced no pulls"
    return None


def _validate_measure_vector(artifact: object) -> str | None:
    """Every measure carries a status (MEASURE_VECTOR_CONTRACT, §4)."""
    if not isinstance(artifact, MeasureVector):
        return "expected a MeasureVector artifact"
    for measure in artifact.measures:
        if not isinstance(measure.status, MeasureStatus):
            return f"measure '{measure.name}' has no valid status"
    return None


POTENTIAL_CONTRACT = Contract("POTENTIAL_CONTRACT", _validate_potential)
DERIVED_LATTICES_CONTRACT = Contract(
    "DERIVED_LATTICES_CONTRACT", _validate_derived_lattices)
SLABS_CONTRACT = Contract("SLABS_CONTRACT", _validate_slabs)
ACTIVATED_SLABS_CONTRACT = Contract(
    "ACTIVATED_SLABS_CONTRACT", _validate_activated)
STRUCTURE_CONTRACT = Contract("STRUCTURE_CONTRACT", _validate_structure)
BOND_DEBOND_CONTRACT = Contract(
    "BOND_DEBOND_CONTRACT", _validate_bond_debond)
MEASURE_VECTOR_CONTRACT = Contract(
    "MEASURE_VECTOR_CONTRACT", _validate_measure_vector)
