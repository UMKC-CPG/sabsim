"""Typed records for a SABSIM project specification (PSEUDOCODE.md §2).

This module is the in-memory shape of the project file that the loader
(:mod:`sabsim.spec.loader`) produces once it has read and validated the
TOML file the DESIGN.md §1.4 generator emits. Each record mirrors one
knob group from PSEUDOCODE.md §2, and the field names follow that
schema so a reader can hold the design document and the code side by
side without a translation table.

Two design commitments from DESIGN.md are encoded structurally here:

* **No hidden defaults (§1.4).** No knob field carries a default value.
  A project file must state every value it uses, so a missing key
  becomes an error the loader reports, never a blank the machinery
  fills in silently. Frozen dataclasses with no defaults make that a
  property of the type: you cannot construct a record with a hole in
  it.
* **Units travel with values (§1.5).** A number that means something in
  the physical world is a :class:`Quantity`, never a bare float, so the
  loader can check dimensions instead of trusting a lone number. Pure
  counts, seeds, fractions, and Miller indices are dimensionless and
  stay bare.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Quantity:
    """A physical value paired with the unit it is measured in.

    The project file writes such a value as a TOML inline table —
    ``{ value = 500.0, unit = "eV" }`` (DESIGN.md §1.5) — so the loader
    can validate dimensions rather than trust a bare number. Counts and
    seeds are NOT quantities: they are dimensionless and stay bare.
    """

    value: float
    unit: str


@dataclass(frozen=True)
class MaterialKnobs:
    """What one wafer IS: its crystal (a CIF), its cut face, its label.

    One :class:`MaterialKnobs` describes a single wafer; a pair holds
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
    # Where this wafer's PREPARATORY work lives: the PREP FOLDER of
    # the project, ``<project>/prep_surf1_<label>/`` for wafer A and
    # ``prep_surf2_<label>/`` for wafer B, the label lower-cased
    # (ARCHITECTURE §1; Paul, 2026-08-30). It holds the force-model
    # recipe, the single-material calculations, the environment
    # library the §3.5 gate judges against, and this surface's own
    # amorphization. Set by the loader from the project file's own
    # location, never typed by hand.
    preparation_directory: str


@dataclass(frozen=True)
class WaferPair:
    """The two facing wafers of the pair (PSEUDOCODE.md §2).

    The material group is two wafers, not one (DESIGN.md §2.1).
    ``wafer_a`` is surface 1 (the bottom half) and ``wafer_b`` is
    surface 2 (the top half) of the interface being bonded; the order
    is fixed so a same-material pair still has two distinct surfaces.
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
    # How deep the activated skin MUST reach: the §3.5 gate's depth
    # threshold and the depth the §2.5 thickness floor builds for — a
    # project choice tied to the dose above, not a material property
    # (DESIGN.md §3.5, revised 2026-08-28).
    required_activated_depth: Quantity
    # NO library path here (revised 2026-08-29 after LEDGER T-39): the
    # environment library the §3.5 gate judges against is found PER
    # SURFACE at ``MaterialKnobs.preparation_directory``, never named
    # in the project file (DESIGN §1.2).
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
    # one rate used when a pair runs at a single speed (PSEUDOCODE §2).
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
    target_footprint_area: Quantity  # in-plane dose-spreading area (§3.6)
    minimum_bulk_thickness: Quantity  # undamaged-crystal cushion (§2.5)
    slab_thickness: Quantity         # chosen total slab thickness (§2.5)
    slab_vacuum: Quantity            # vacuum above the face for the beam
    bulk_cells_per_axis: int         # §2.2 bulk-relax block, per axis
    clash_floor: Quantity            # minimum cross-slab distance (§2.6)
    contact_grid_spacing: Quantity   # cell size for contact fraction
    contact_gap_threshold: Quantity  # gap that, with stress, marks contact
    # The two contact-test settings the press reads (DESIGN §5.2, revised
    # 2026-08-28): how many press chunks the surface-to-surface opening is
    # averaged over before it is compared with the threshold, and the
    # smallest sustained normal-stress magnitude (either sign) that counts
    # as the surfaces genuinely loading each other.
    contact_gap_window: int          # chunks in the opening's trailing mean
    contact_stress_floor: Quantity   # |mean normal stress| floor for contact
    # The press/settle driver's chunking, project knobs since 2026-08-28
    # (DESIGN §5.2/§5.3): the stress running-mean window (chunks), the time
    # the driver advances between read-backs, the time the press may
    # search for contact before reporting "no contact", and the time the
    # zero-load reference equilibrates before its gates.
    contact_stress_window: int       # chunks in the stress running mean
    control_interval: Quantity       # time between driver read-backs
    press_time_budget: Quantity      # contact search limit (a time)
    settle_duration: Quantity        # zero-load equilibration span
    # The §3.5 gate's two measurement knobs (DESIGN §3.5, 2026-08-29):
    # the thickness of one horizontal layer of the disorder-versus-depth
    # profile, and how many library thermal scatters away an atom's
    # neighbourhood may sit and still count as crystalline. Both are
    # numerical by §1.2's test: refine them and the depth must converge.
    depth_bin_width: Quantity        # depth-profile layer thickness
    disorder_scatter_multiple: float # tolerance, in thermal scatters
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
class PotentialSpec:
    """Which force models the project runs under (DESIGN.md §1.6, §4.7).

    One block per project file, and the reason it lives there rather
    than in the environment: the project file is the provenance record,
    so anything that changes the physics must be written there, never
    picked up silently from a shell variable.

    Two models are named, because the pipeline deliberately uses two:

    * ``universal_model`` / ``universal_weights`` — the pre-trained
      foundation model that derives the working lattice (§2.2) and runs
      the ion-beam cascade spliced with ZBL cores (§4.7). The name must
      be a row of the code's table of supported universal models
      (``SUPPORTED_UNIVERSAL_MODELS``, DESIGN §4.7), so a project cannot
      silently run under a model the code has no record of, while the
      project file — not the code — chooses which model runs; the
      weights path says where that model's file is on this machine
      (``$SABSIM_SHARE`` and the other roots are expanded by the loader).
    * ``production_weights`` — the model the gentle stages (heal, press,
      settle, pull) run under. The design target is the ALF-trained
      DeePMD committee named by the pair's ``potential_ref``; until
      the bootstrap that manufactures one exists, this names a single
      frozen DeePMD file (a committee of one) and is the ONLY place that
      choice is recorded.

    ``allow_unvalidated`` is the on-the-record opt-in to run a model that
    has not yet cleared the §3.5 activation gate. Every result produced
    under it is exploratory and is reported as such.
    """
    universal_model: str             # pinned identity, e.g. "DPA-3.1-3M"
    universal_weights: str           # path to that model's weights file
    production_weights: str          # frozen DeePMD model for heal/press/pull
    allow_unvalidated: bool          # exploratory opt-in (DESIGN.md §4.7)


@dataclass(frozen=True)
class PairSpecification:
    """The wafer pair a project runs: two surfaces under one protocol.

    This is the unit that runs and produces a result (PSEUDOCODE.md
    §2). Since 2026-08-30 (Paul) a project holds exactly ONE pair, so
    the pair carries no name of its own: everything derived from it
    (folder names, script names, dump names) uses :attr:`pair_label`,
    which is built from the two wafers' material labels. A reference
    pair — the Si/Si that a Si/SiO2 question is compared against — is a
    separate project folder the person makes and runs themselves
    (DESIGN.md §1.1).

    ``potential_ref`` names WHICH potential generation this pair runs
    under: not a knob but a pointer to an upstream artifact (DESIGN.md
    §1.3, §1.6). ``material_domain`` names the structural and chemical
    REGIME the pair's structures occupy (DESIGN.md §4.8). It exists
    because a species set does not identify a material model on its
    own: carbon spans diamond and graphite, silica runs from quartz to
    an amorphous network, and a model trained on one regime is
    confidently wrong in another. Today no code consumes it — it is
    RECORDED provenance that the §4.8 force-model recipe will be keyed
    on. The recipe's domain and this one agree by CONTAINMENT rather
    than equality: a ``silicon-and-silica`` recipe legitimately covers
    a silica-only pair, because silica lies inside that regime.
    """

    material: WaferPair              # the two facing wafers
    protocol: ProtocolKnobs          # how it is activated, pressed, pulled
    numerical: NumericalKnobs        # how carefully it is computed
    ensemble: EnsembleKnobs          # which realizations to sample
    potential_ref: str               # the potential generation it uses
    material_domain: str             # the structural/chemical regime
    potential: PotentialSpec         # the force models it runs under

    @property
    def pair_label(self) -> str:
        """``<a>_<b>``: both material labels lower-cased and joined.

        The one identity every derived name is built from. Lower-cased
        because it becomes part of folder and file names, and a name
        that differs only by case is a trap on a shell (Paul).
        """
        return (f"{folder_label(self.material.wafer_a.identity)}_"
                f"{folder_label(self.material.wafer_b.identity)}")


def folder_label(material_label: str) -> str:
    """A wafer's material label as it appears in a folder name.

    Lower-cased and otherwise untouched: ``"SiO2"`` becomes ``sio2``.
    The loader has already refused labels that could not name a folder
    (empty, or holding a path separator).
    """
    return material_label.lower()


@dataclass(frozen=True)
class StageFolders:
    """The four stage folder NAMES of a project (ARCHITECTURE.md §1).

    Names, not paths: each lives directly under the project folder and,
    with the same name, under the project's ``intermediate`` scratch
    mirror. The prefix says the stage and the suffix says which
    material(s), so a directory listing reads like the physics: prepare
    surface 1, prepare surface 2, bond the pair, analyse the pair.
    """

    prep_surf1: str                  # e.g. "prep_surf1_si"
    prep_surf2: str                  # e.g. "prep_surf2_sio2"
    bond: str                        # e.g. "bond_si_sio2"
    analysis: str                    # e.g. "analysis_si_sio2"


def stage_folders(pair: PairSpecification) -> StageFolders:
    """The ONE place the project layout is written down (PSEUDOCODE §2).

    For a silicon/silica pair: ``prep_surf1_si``, ``prep_surf2_sio2``,
    ``bond_si_sio2``, ``analysis_si_sio2``. For a same-material pair
    the two prep folders still differ (``prep_surf1_si`` and
    ``prep_surf2_si``), because each surface is amorphized on its own
    with its own seed. Every module that needs a folder name asks here
    rather than spelling the pattern out again.
    """
    return stage_folder_names(pair.material.wafer_a.identity,
                              pair.material.wafer_b.identity)


def stage_folder_names(material_a: str, material_b: str) -> StageFolders:
    """The layout from two bare material labels (PSEUDOCODE §14.7).

    The label-level form of :func:`stage_folders`, for a caller that
    has the two ``material`` strings but no validated pair yet: ``sabsim
    init`` reads them out of a freshly written, possibly half-edited
    ``sabsim.toml`` with the plain TOML parser and needs the folder
    names before any loader would accept the file. Both forms spell the
    pattern here, once.
    """
    label_a = folder_label(material_a)
    label_b = folder_label(material_b)
    return StageFolders(
        prep_surf1=f"prep_surf1_{label_a}",
        prep_surf2=f"prep_surf2_{label_b}",
        bond=f"bond_{label_a}_{label_b}",
        analysis=f"analysis_{label_a}_{label_b}",
    )


@dataclass(frozen=True)
class Project:
    """One project: a single wafer pair and where it lives on disk.

    The project folder is the person's own label (``jobs/si_sio2/``)
    and means nothing to the program; what the program keeps is the
    RESOLVED directory the project file was read from, because every
    stage folder and both prep folders are found beneath it
    (ARCHITECTURE.md §1). ``description`` is free text carried into the
    report as provenance. There is no list of members and no relation
    layer: a comparison between two pairs is made by the person from
    two projects' summaries (DESIGN.md §1.1, revised 2026-08-30).
    """

    description: str
    pair: PairSpecification
    project_directory: str
