"""The typed records the pipeline produces during execution (§1).

These are the outputs of executing a member: both the artifacts that
flow BETWEEN stages (Potential, Slab, Structure, …) and the execution
RESULTS (MemberResult, StudyReport) that ``exec_one_member`` and
``exec_full_study`` return. They contrast with the input records in
:mod:`sabsim.spec.records`, which a human writes; everything here the
pipeline itself produces. Each stage of ``exec_one_member`` hands the
next a typed artifact, and ``run_to_contract`` (see
:mod:`sabsim.pipeline.contracts`) checks it against the contract the
next stage depends on. In the walking skeleton (ARCHITECTURE.md §5,
wave 0) most are light placeholders — the point of W0 is that a
well-formed artifact travels EVERY seam, not that any physics is real —
but the provenance stamp and the member/study results are the permanent
shapes that later waves fill in behind the same contracts.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, is_dataclass

from sabsim.pipeline.measures import MeasureVector
from sabsim.spec.records import MemberSpecification


def content_fingerprint(record: object) -> str:
    """Return a short, stable content fingerprint of a dataclass record.

    DESIGN.md §1.4 identifies a protocol by the CONTENT of its knobs, not
    a version number, so two specs with the same values fingerprint the
    same and a single changed knob changes the fingerprint. We serialize
    the record canonically (sorted keys) and hash it; the result is
    provenance the report can carry (DESIGN.md §1.6).
    """
    if not is_dataclass(record):
        raise TypeError("content_fingerprint expects a dataclass record")
    canonical = json.dumps(asdict(record), sort_keys=True, default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return digest[:16]         # 16 hex chars is ample to tell specs apart


@dataclass(frozen=True)
class Provenance:
    """Which potential ran and the exact protocol it ran under (§1.6).

    This is the stamp every :class:`MemberResult` carries so a number can
    always be traced to the potential generation, the master seed, and
    the fingerprinted protocol that produced it.
    """

    potential_ref: str             # the potential generation identifier
    potential_kind: str            # e.g. "classical-stand-in", "mlip"
    master_seed: int               # reproduces the whole ensemble
    protocol_fingerprint: str      # content fingerprint of the protocol


def build_provenance(
        potential: "Potential",
        member: MemberSpecification) -> Provenance:
    """Assemble the provenance stamp for one member's run (§1.6)."""
    return Provenance(
        potential_ref=member.potential_ref,
        potential_kind=potential.kind,
        master_seed=member.ensemble.master_seed,
        protocol_fingerprint=content_fingerprint(member.protocol),
    )


# ---------------------------------------------------------------------
# Stage artifacts. Placeholders in W0, but each is the real seam the
# later-wave module will produce (ARCHITECTURE.md §5.1).
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class Potential:
    """A loadable interatomic potential the member looks up (§1, §1.6).

    The skeleton satisfies the POTENTIAL_CONTRACT with a classical
    ``pair_style`` stand-in; the bootstrap wave later satisfies the same
    contract with the trained MLIP, through this same artifact.
    """

    kind: str                      # "classical-stand-in" in the skeleton
    pair_style: str                # the loadable interface (§1)
    loadable: bool                 # False marks an unusable potential


@dataclass(frozen=True)
class SharedCell:
    """The coincidence cell both slabs are built to share (DESIGN §2.3).

    A placeholder in W0 — a Si/Si pair has no mismatch, so the shared
    cell is trivial and the real coincidence matcher stays dormant until
    the Si/SiO2 milestone (ARCHITECTURE.md §5, wave 3).
    """

    note: str


@dataclass(frozen=True)
class DerivedLattices:
    """Per-material conventional cells relaxed under the model (§2.2).

    The handoff from the lattice-derivation step to the build: each wafer's
    material identity maps to the conventional cell the current model
    relaxed the bulk to — NOT the CIF's published scale, which §2.2
    forbids. Cells are nested tuples of floats (JSON-friendly for
    provenance, and numpy-free so the walking-skeleton import stays light);
    ``rescale_crystal_to_cell`` accepts them directly. Keyed by identity so
    a same-material pair (Si/Si) derives the lattice once and shares it.
    ``provenance`` records the model the cells were relaxed under.
    """

    cells: dict          # identity -> 3x3 conventional cell, nested tuples
    provenance: str

    def cell_for(self, identity: str):
        """The relaxed conventional cell for one material (a 3x3 of floats)."""
        return self.cells[identity]


@dataclass(frozen=True)
class Slab:
    """One wafer's slab, built to the shared cell (DESIGN §2).

    ``data_file`` is set once the slab has a durable on-disk form the next
    stage reads (the amorphized half the assembly loads, ARCHITECTURE
    §4.3); it stays None for the W0 placeholder that writes no file.
    """

    identity: str                  # the material this slab is made of
    note: str                      # a placeholder description in W0
    data_file: str | None = None   # the slab's file on disk, if written


@dataclass(frozen=True)
class HalfHandle:
    """One pristine standalone half on disk, ready to be amorphized (§7.1).

    What ``build_halves`` hands the activation stage for ONE wafer:
    everything needed to amorphize it, and NOTHING about the other half,
    so each is a self-contained unit (the fan-out unit, ARCHITECTURE §4.3).
    The activation stage RE-READS the slab geometry from ``data_file``
    (never a warm in-memory object), so the unit is restartable and
    identical whether it runs in the member's own job or a separate one.
    ``type_map`` declares the beam species (a zero-atom type) so the
    cascade can create projectiles against it; ``wafer_tag`` records which
    wafer this is — bottom A or top B (the assembly invariant, DESIGN §2.6).
    """

    data_file: str                 # the pristine standalone half on disk
    type_map: dict                 # species symbol -> type id, beam declared
    identity: str                  # the material (report + reference lookup)
    wafer_tag: int                 # WAFER_A_TAG (bottom) / WAFER_B_TAG (top)


@dataclass(frozen=True)
class Verdict:
    """A pass/fail gate outcome with the reason it reached it."""

    passed: bool
    reason: str


@dataclass(frozen=True)
class ActivatedSlabs:
    """Both amorphized slabs AND both activation verdicts (§10.1).

    The activation gate (DESIGN.md §3.5) is enforced at this seam: the
    ACTIVATED_SLABS_CONTRACT checks both verdicts passed, so a failed
    amorphization halts the pipeline here rather than downstream.
    """

    slab_a: Slab
    slab_b: Slab
    verdict_a: Verdict
    verdict_b: Verdict


@dataclass(frozen=True)
class Structure:
    """The assembled facing pair handed to the bond/debond MD (§2, §5).

    Carries the labeled groups (frozen base, thermostat border, NVE
    interior, activated skin, grips) that cross the build->press->pull
    seam. ``data_file`` is the assembled pair on disk the press loads (set
    by the real assembly stage, None for the W0 placeholder).
    """

    note: str
    labeled_groups: tuple[str, ...]
    data_file: str | None = None   # the assembled pair's file, if written
    # The assembled pair as a live builder object (atoms + tags + z-ranges
    # + type map), carried in-memory for the press/pull driver, which needs
    # the per-wafer geometry a plain data file does not record. None for the
    # W0 placeholder; a # C-EXPANSION point (Approach C would re-read it from
    # the file in the press job, ARCHITECTURE.md §4.3).
    built: object = None


@dataclass(frozen=True)
class PressOutcome:
    """Did the pair bond under the press, and a note on how (§5.2)."""

    bonded: bool
    note: str


@dataclass(frozen=True)
class PullOutcome:
    """One rung of the pull-rate ladder: the rate and its curve (§5.4, §9.6).

    Beyond the rate and a note, a real pull carries the REDUCED force curve
    the analyzer integrates into the work of separation (§8.4): the grip
    displacements, the tension-positive resisting force at each, and the
    frame of complete separation the integral stops at. ``complete`` is
    False (and the curves empty) for a pull that never separated, or for
    the W0 placeholder.
    """

    rate_value: float
    rate_unit: str
    note: str
    complete: bool = False
    separation_index: int | None = None
    grip_displacement: tuple = ()      # Å, per recorded frame
    force_vs_grip: tuple = ()          # eV/Å, tension-positive, per frame
    # False when the run lost an atom out of the open-z box (§9.6). The
    # curve is then void: the analyzer must refuse it rather than
    # integrate a system whose atom count changed underneath it.
    atoms_conserved: bool = True
    # Atom pairs still spanning the interface when the pull stopped.
    # Zero is what complete separation MEANS (§5.5); reporting it makes
    # a result that stopped with material still joining the two wafers
    # visible instead of buried in the number.
    bridges_at_separation: int | None = None
    # Whether this rung was RESUMED from a checkpoint, and whether the
    # §13.4 trust guard was overridden to do so. Recorded so the history
    # stays honest about how the number was produced (VISION goal 3); a
    # resumed pull is the SAME measurement, not a lesser one (§11.5).
    resumed: bool = False
    override_used: bool = False


@dataclass(frozen=True)
class BondDebondResult:
    """One press outcome, one reference, and a pull PER RATE (§9.1).

    Named for what it is at this seam — not a bare trajectory, but the
    structured result the analyzer reads: the press verdict, the
    zero-load reference, and the ladder of pulls (DESIGN.md §5.4).
    """

    press: PressOutcome
    reference_ok: bool             # the §5.3 gated zero-load reference
    pulls: tuple[PullOutcome, ...]


@dataclass(frozen=True)
class GateReport:
    """The per-member diagnostic verdict (DESIGN.md §7).

    In v1 the gate only REPORTS; it never acts (VISION principle 5). W0
    fills the permanent shape with a skeleton summary; the live gate and
    its five-way diagnosis (§7.7) land in wave 1.
    """

    summary: str
    acted: bool                    # always False in v1 (report only)
    measures_seen: tuple[str, ...]  # which measure names it read


@dataclass(frozen=True)
class MemberResult:
    """One member's self-standing report (PSEUDOCODE.md §1).

    ``trusted`` is False for a walking-skeleton member whose number is
    plumbing, not physics (ARCHITECTURE.md §5.3); later waves flip it to
    True as the stand-ins are replaced behind the same contracts.
    """

    specification: MemberSpecification
    potential: Provenance
    measures: MeasureVector
    gate: GateReport
    trusted: bool


@dataclass(frozen=True)
class RelationOutcome:
    """The graded result of one declared relation (DESIGN.md §7.4).

    A relation is reported, never used to restrict (DESIGN.md §1.1), so
    even an untrusted or unresolved outcome is carried with the reason.
    """

    kind: str
    members: tuple[str, ...]
    value: float | None            # None when the relation is unresolved
    unit: str
    trusted: bool                  # False if any related member is
    note: str


@dataclass(frozen=True)
class StudyReport:
    """The whole study's output: per-member reports plus relations (§1)."""

    study_name: str
    member_results: tuple[MemberResult, ...]
    relation_outcomes: tuple[RelationOutcome, ...]
