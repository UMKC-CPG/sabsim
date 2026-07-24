"""Typed records for a SABSIM study specification (PSEUDOCODE.md §2).

This module is the in-memory shape of the study spec that the loader
(:mod:`sabsim.spec.loader`) produces once it has read and validated the
TOML file the DESIGN.md §1.4 generator emits. Each record mirrors one
knob group from PSEUDOCODE.md §2, and the field names follow that
schema so a reader can hold the design document and the code side by
side without a translation table.

Two design commitments from DESIGN.md are encoded structurally here:

* **No hidden defaults (§1.4).** No knob field carries a default value.
  A study spec must state every value it uses, so a missing key becomes
  an error the loader reports, never a blank the machinery fills in
  silently. Frozen dataclasses with no defaults make that a property of
  the type: you cannot construct a record with a hole in it. (The only
  fields that DO default are the validator-computed outputs on a
  :class:`Relation`, which are results, not settings.)
* **Units travel with values (§1.5).** A number that means something in
  the physical world is a :class:`Quantity`, never a bare float, so the
  loader can check dimensions instead of trusting a lone number. Pure
  counts, seeds, fractions, and Miller indices are dimensionless and
  stay bare.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Quantity:
    """A physical value paired with the unit it is measured in.

    The study spec writes such a value as a TOML inline table —
    ``{ value = 500.0, unit = "eV" }`` (DESIGN.md §1.5) — so the loader
    can validate dimensions rather than trust a bare number. Counts and
    seeds are NOT quantities: they are dimensionless and stay bare.
    """

    value: float
    unit: str


@dataclass(frozen=True)
class MaterialKnobs:
    """What one wafer IS: its crystal (a CIF), its cut face, its label.

    One :class:`MaterialKnobs` describes a single wafer; a member pairs
    two of them (PSEUDOCODE.md §2). The crystal is supplied as a CIF —
    the authoritative structure that fixes symmetry, basis, and
    connectivity for ANY material (DESIGN.md §1.2), so one uniform input
    serves silicon, silicon dioxide, and the rest with no per-material
    code. Two things are deliberately NOT fields here: the CIF's lattice
    SCALE is a starting geometry only — the working lattice constant is
    derived by relaxing the bulk under the potential (§1.3, §2.2) — and
    ``crystal_structure`` is a human-readable LABEL for the report, not
    an authoritative source (the CIF is), so it can never disagree with
    the geometry the builder actually uses.
    """

    identity: str                    # the material itself, e.g. "Si"
    cif_source: str                  # path to the authoritative CIF
    crystal_structure: str           # human label, e.g. "diamond"
    surface_face: tuple[int, int, int]   # Miller indices of the bond face


@dataclass(frozen=True)
class WaferPair:
    """The two facing wafers that make up one member (PSEUDOCODE.md §2).

    A member is a facing pair (DESIGN.md §2.1), so the material group is
    two wafers, not one. ``wafer_a`` and ``wafer_b`` are the two sides
    of the interface being bonded.
    """

    wafer_a: MaterialKnobs
    wafer_b: MaterialKnobs


@dataclass(frozen=True)
class AnnealSchedule:
    """The gentle MLIP re-anneal after amorphization (DESIGN.md §3.4).

    The re-anneal relaxes the damaged skin, holds it briefly, and
    quenches back to room temperature. It is deliberately mild: a
    kinetically trapped glass bounds how far it may go, so it must not
    un-trap the frozen amorphous layer (PSEUDOCODE.md §2).
    """

    hold_temperature: Quantity       # top of the short hold, e.g. 500 K
    hold_duration: Quantity          # how long to hold, e.g. tens of ps
    ensemble: str                    # thermodynamic ensemble, e.g. "nvt"


@dataclass(frozen=True)
class ProtocolKnobs:
    """HOW the experiment is performed (DESIGN.md §1.2, PSEUDOCODE §2).

    Every field here is a physics choice whose influence on the answer
    IS the result, so it is frozen by being written down, not hidden.
    The group spans the three protocol stages the pipeline runs in
    order: surface activation (§3), assembly and press (§5.2), and the
    separation pull (§5.4).
    """

    # --- Activation: the argon-beam amorphization (DESIGN.md §3) ---
    activation_mechanism: str        # which method; v1 = "bombardment"
    activation_species: str          # projectile element, e.g. "Ar"
    activation_cospecies: str | None  # optional co-deposit, else None
    activation_cospecies_fraction: float   # co-deposit fraction if used
    activation_energy: Quantity      # impact energy, e.g. 500 eV
    activation_angle: Quantity       # incidence from the surface normal
    activation_fluence: Quantity     # the dose knob (DESIGN.md §3.6)
    cascade_duration: Quantity       # NVE cascade time per impact (§3.3)
    between_impact_relaxation: Quantity   # border-cool between impacts
    reanneal_schedule: AnnealSchedule     # the post-cascade re-anneal

    # --- Assembly and press: bringing the wafers into contact (§5.2) ---
    initial_gap: Quantity            # slab separation at assembly (§2.6)
    press_control: str               # "load" or "displacement" (§5.2)
    press_load: Quantity             # load/pressure reached under "load"
    press_depth: Quantity            # grip advance under "displacement"
    press_duration: Quantity         # the hold where bonding happens
    press_temperature: Quantity      # thermostat setpoint for the hold
    press_approach_rate: Quantity    # grip approach speed (§9.3 guard)

    # --- Separation: the single-rate special case (§5.4) ---
    # The full v1 pull uses numerical.pull_rate_ladder; this names the
    # one rate used when a member runs at a single speed (PSEUDOCODE §2).
    separation_speed: Quantity


@dataclass(frozen=True)
class NumericalKnobs:
    """HOW CAREFULLY we compute (DESIGN.md §1.2, PSEUDOCODE.md §2).

    A numerical knob's influence on the answer must VANISH as it is
    refined; if a number here moves the result, that is a convergence
    problem, not a physics finding. PSEUDOCODE.md §2 marks several of
    these ``[DEPTH-FIRST]`` — their converging module has not landed, so
    their spec values are provisional — but they are still fields here,
    because a value the run uses must be visible (DESIGN.md §1.4).
    """

    md_timestep: Quantity            # MLIP MD step
    cascade_timestep: Quantity       # smaller step for stiff ZBL impacts
    langevin_damping: Quantity       # border-thermostat damping time
    pull_rate_ladder: tuple[Quantity, ...]   # >=3 rates over a decade
    force_average_window: Quantity   # pull-force smoothing, in DISPLACEMENT
    frame_stride: int                # store one frame per N MD steps
    noise_floor: Quantity            # peak/curve threshold vs thermal RMS
    misfit_tolerance: float          # coincidence-match strain cutoff
    max_coincidence_area: Quantity   # atom-area budget for the match
    minimum_bulk_thickness: Quantity  # undamaged-substrate floor (§2.5)
    clash_floor: Quantity            # minimum cross-slab distance (§2.6)
    contact_grid_spacing: Quantity   # cell size for contact fraction
    contact_gap_threshold: Quantity  # gap that, with stress, marks contact
    bonded_contact_threshold: float  # contact quality above which "bonded"
    reference_pe_drift: Quantity     # max PE drift for a settled reference


@dataclass(frozen=True)
class EnsembleKnobs:
    """WHICH realizations to sample and average (PSEUDOCODE.md §2).

    A seed is a coordinate we SAMPLE, not a knob we tune. There are two
    independent sources of run-to-run spread, so there are two counts:
    the amorphized skin and the thermal state each get their own axis,
    and the §6.6 error bar is taken over their product. One master seed
    reproduces the whole ensemble; every per-realization seed derives
    from it deterministically (DESIGN.md §3.6).
    """

    master_seed: int                 # reproduces the whole ensemble
    amorphization_count: int         # independent cascade realizations
    velocity_count: int              # thermal reseeds per amorph run


@dataclass(frozen=True)
class MemberSpecification:
    """One member: a facing pair run under one protocol (PSEUDOCODE §2).

    A member is the unit that actually runs — it stands alone and
    produces its own result. Studies are assembled from members after
    the fact (DESIGN.md §1.1). ``potential_ref`` names WHICH potential
    generation this member runs under: not a knob but a pointer to an
    upstream artifact (DESIGN.md §1.3, §1.6).

    ``material_domain`` names the structural and chemical REGIME this
    member's structures occupy (DESIGN.md §4.8). It is the other half of
    the force-model lookup key, and it exists because a species set does
    not identify a material model on its own: silicon-and-oxygen is
    covered by one form that spans a silicon wafer, a silica wafer and
    the interface between them, and by another that is better for
    amorphous silica but cannot describe elemental silicon at all.
    Nothing in a cell's composition distinguishes those cases, so the
    specification must say which is meant. Like ``potential_ref`` it is a
    pointer rather than a knob — refining it does not converge anything,
    it selects a different description of the material.

    A note on where this field will eventually live. §4.8 keys the
    force-model RECIPE on (species union, domain) too, so once that
    record exists the domain is properly a property of the artifact
    ``potential_ref`` resolves to, and the two must agree. They agree by
    CONTAINMENT rather than equality: a recipe whose domain is
    ``silicon-and-silica`` legitimately covers a silica-only
    member, because silica lies inside that regime. Checking that
    containment is a follow-on (`TODO.md`), and until the recipe record
    exists this member-level field is what carries the choice.
    """

    name: str                        # member id, referenced by relations
    material: WaferPair              # the two facing wafers
    protocol: ProtocolKnobs          # how it is activated, pressed, pulled
    numerical: NumericalKnobs        # how carefully it is computed
    ensemble: EnsembleKnobs          # which realizations to sample
    potential_ref: str               # the potential generation it uses
    material_domain: str             # the structural/chemical regime


@dataclass(frozen=True)
class Relation:
    """An optional comparison across a subset of a study's members.

    A relation compares members on one or more named MEASURES (§6.6) —
    not one privileged number. It declares what it deliberately varies
    (``contrast``) and what it holds fixed (``controls``); the validator
    fills the computed fields below. A relation is REPORTED, never used
    to restrict (DESIGN.md §1.1): even a confounded one is still
    computed, and only the gate's verdict is withheld.

    The computed fields carry defaults because they are validator
    OUTPUTS, not user settings — the no-defaults rule (DESIGN.md §1.4)
    guards the settings, which are the four fields above them.
    """

    kind: str                        # e.g. "ratio", "sweep"
    members: tuple[str, ...]         # which member ids it relates
    measures: tuple[str, ...]        # which metrics it compares on
    contrast: tuple[str, ...]        # field paths it deliberately varies
    controls: tuple[str, ...]        # field paths it holds fixed
    # --- Computed by the loader's relation validator (PSEUDOCODE §2) ---
    confounded: bool | None = None   # True if more than one contrast
    controls_disagree: bool | None = None   # a control that actually differs
    # sort_differences (entailed vs incidental) is [DEPTH-FIRST] in §2;
    # the full difference set lands with the relation-evaluation module.
    difference_set: object | None = field(default=None)


@dataclass(frozen=True)
class Study:
    """A set of members, optionally tied together by relations (§2).

    The study is the top-level configured object because §7.4's headline
    criterion is a RATIO, which belongs to a PAIR of members and not to
    either one (DESIGN.md §1.1). ``name`` and ``description`` are
    study-level provenance the spec carries for the report.
    """

    name: str
    description: str
    members: tuple[MemberSpecification, ...]
    relations: tuple[Relation, ...]
