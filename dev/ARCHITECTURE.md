# Architecture

> **Document hierarchy:** VISION → **ARCHITECTURE** → DESIGN →
> PSEUDOCODE → Code. For goals and principles, see `VISION.md`.
>
> **Status:** First-pass mapping of the planning notes into the
> chain. The big architectural decisions are captured here, but the
> outer-orchestrator choice and several boundaries are still open —
> see `TODO.md`. Treat this as a baseline to refine, not a settled
> design.

---

## 1. Repository Layout

```
sabsim/
  dev/
    VISION.md         Goals and principles
    ARCHITECTURE.md   This document
    DESIGN.md         Algorithmic design (not yet started)
    PSEUDOCODE.md     Algorithm specifications (not yet started)
    TODO.md           Task list by level
    PRIOR_ART.md      Existing overlapping work and reusable assets
  src/                Source code (orchestrator, quality gate, glue)
  tests/              Test suite
  CLAUDE.md           AI assistant guidance
```

SABSIM is the **orchestration project**: the code we write here wires
together many *external* programs. Two tools from the prior effort are
sibling projects it depends on, not modules inside this repository:

- **Imago** — an all-electron electronic-structure "calculator." It
  models *all* electrons (no pseudopotential shortcut), giving rare
  accuracy for fine bonding and spectroscopy. Method: OLCAO.
- **Kaleidoscope** — a deliberately thin batch manager that dispatches
  Imago runs (locally or on a SLURM cluster via Parsl), caches
  results, and tracks success and failure. Built library-first.

Cross-project dependencies on Imago deliverables are listed in §4.

---

## 2. Module Map

The central architectural fact: **SABSIM is a heterogeneous,
multi-code workflow** — many *different* programs wired together, with
feedback loops. The work is grouped below by *kind of job*, because
that is what makes the right tool obvious. Each group is tagged
**[BUILD]** (our novel contribution) or **[ADOPT]** (mature external
machinery we drive but do not write).

### 2.1 The eight pipeline steps

```
1. Generate training data — many physics calcs on Si, SiO2, GaN, LiNbO3
2. Train a machine-learned interatomic potential (MLIP)
3. Build wafer slab models
4. Amorphize ("activate") the model surfaces
   (classical+ZBL cascade, then a gentle MLIP anneal — see §2.3)
5. Build the facing-pair (two amorphized surfaces toward each other)
   (steps 3-5 may be reordered; ordering should be a setting)
6. Press the slabs together and let them settle  (uses the MLIP)
7. Pull them back apart                           (uses the MLIP)
8. Characterize the interface bonding from snapshots of steps 6-7
```

### 2.2 Work groups and their tools

The **Origin** column marks whether the tool is adopted (ADOPT) or
still undecided (OPEN); the **Tool** column names it. The **Protocol**
column marks what *we* build on top of that adopted tool. Splitting
origin from protocol keeps `VISION.md` principle 2 (adopt the tool) and
goal 5 (build only the novel layer) legible at a glance — the tool is
never ours to write; the protocol usually is.

| Steps | Kind of work      | Tool               | Origin | Protocol |
|-------|-------------------|--------------------|--------|----------|
| 1     | many physics calcs| VASP               | ADOPT  | —        |
| 2     | ML pot. training  | ALF (pluggable)    | ADOPT  | plugin   |
| 3, 5  | build structures  | ASE                | ADOPT  | BUILD    |
| 4     | disorder surfaces | LAMMPS             | ADOPT  | BUILD    |
| 6, 7  | atom-motion sims  | LAMMPS + the MLIP  | ADOPT  | BUILD    |
| 8     | electron analysis | Imago/Kaleidoscope | ADOPT  | BUILD    |
| all   | wiring the steps  | outer orchestrator | OPEN   | BUILD    |

A "—" in the Protocol column means we only *drive* that tool with
settings and write no protocol of our own (step 1). Step 2 is nearly
that — the ALF active-learning loop is a black box we configure — save
for one thin, config-selected **backend plugin** we maintain (the
"plugin" tag; see §2.3), which needs no fork of ALF. Note step 8: Imago
and Kaleidoscope are our own prior tools, so we *reuse* them as the
engine (ADOPT) and build the step-8 characterization batch on top
(BUILD) — that batch is our edge. Step 4's LAMMPS row hides a potential
split (§2.3): the violent Ar cascade runs on an adopted classical + ZBL
potential and only the gentle post-cascade anneal uses the MLIP, so the
MLIP is never asked to reproduce cascades.

### 2.3 Module responsibilities (single responsibility each)

- **Outer controller [BUILD].** Owns the SAB quality-gate loop — the
  project's "brain." Starts as simple Python; grows heavier only if
  forced (see §4 and `VISION.md` principle 6).
- **Settings / deployment separation [BUILD].** Per `VISION.md`
  principle 1, the "what to run" (which materials, precision, how many
  snapshots — the control parameters) lives in human-editable settings,
  kept separate from the "where to run" (which cluster, node counts,
  walltime — the deployment), and both kept separate from the fixed
  machinery. Deployment stays a freely-turnable knob so the *same*
  experiment can be run several ways and compared. The execution
  realization of this — the three tiers, the resource-class deployment
  layer, and the HPC walls — is §4.1.
- **Programmatic / turn-key entry [BUILD].** Per `VISION.md` goal 2,
  the controller is exposed as a library-style programmatic interface,
  not just a hand-run script, so another researcher can point the
  pipeline at a different material pair and drive it from their own
  code. Hand-editable settings are a convenience side door, not the
  main entrance.
- **Run specification — the study, and five groups of knobs [BUILD].**
  Per `VISION.md` goal 2 and principle 1, everything a user changes to
  point the pipeline at a new study lives in one editable place, apart
  from the fixed machinery. `DESIGN.md` §1 refines this in two ways.
  First, the configured object is a **study** — a set of runs plus the
  **relations** among them — because the bond-outcome criterion is a
  *ratio* between two runs and so belongs to neither one alone. A run
  remains self-contained and independently reproducible, and a study may
  be assembled after the fact from runs that already exist. Each
  relation declares its own **contrast** (the fields it deliberately
  varies) and its **controls** (the fields it holds fixed) — the
  precondition cannot be a fixed rule, because a study comparing two
  *protocols* on one material pair needs the protocol to differ. Every
  relation emits a **difference set** sorting each differing field as
  contrasted, *entailed* (it differs because of the contrast and cannot
  be removed without it — Si/Si has no lattice mismatch and Si/SiO2
  does), or *incidental* (nobody decided to vary it — the dangerous
  kind). **Report, never restrict:** a relation whose controls disagree,
  or which is confounded by more than one contrast, is still computed
  and still reported; only the gate's *verdict* is withheld. Refusing to
  evaluate and refusing to certify are different acts, and SABSIM
  performs only the second — the scientist comparing many pairs run many
  ways is who this is for, and they routinely learn from comparisons no
  automated criterion can grade.
  Second, the knobs split into **five** groups, not two, divided by a
  sharp test: *a numerical setting's influence on the answer must vanish
  as it is refined; a protocol knob's influence on the answer* is *the
  physics.* The five are material, protocol, numerical (tolerances,
  cutoffs, strides, windows, budgets), ensemble (the master seed and the
  realization count — a coordinate one samples, not a knob one tunes),
  and deployment, which lives in a separate document (§4.1) that the run
  specification cannot express.
  - **Material knobs:** per wafer, a crystal structure and one surface
    face (its Miller indices), plus the material identity itself —
    **never a lattice constant**, which §2.2 derives from the potential
    (hand-typed literature values are the root cause of prior art's
    −30 to −40 GPa step-zero pressure, `PRIOR_ART.md` §1.6).
  - **Protocol knobs:** the activation species — **argon by default,
    with a co-species such as iron as the first accommodated secondary**,
    kept generic so the projectile set is a knob (its ZBL channels are
    derived from the species, not hand-enumerated); the activation
    energy and angle of incidence; the **dose as a fluence** (ions·Å⁻²,
    so it is cell-size-independent — the impact count follows from it and
    the surface area); and the press/separate settings (load or pressure,
    press depth and duration, separation speed). v1 freezes each to a
    single value; the design admits distributions (energy/angle spread)
    later.
  v1 **freezes every protocol knob to a single value** so one complete
  run is reachable within time constraints; *iterating* over them
  (composition, dopant, activation level, pressure, temperature,
  crystal face) is deferred to the outer-loop coupling and convergence
  work still open in `TODO.md`. The design stays open-ended for that
  future sweep. v1 fixes the material knobs to the **Si/SiO2** pair
  (covalent, a Maszara calibration anchor) and additionally runs a
  **Si/Si same-material reference**, because the bond-outcome metric
  calibrates on the *relative* Si-Si-to-Si-SiO2 ratio (`VISION.md`
  goal 4) — one system yields only a point, the ratio needs both. Si/Si
  reuses the same {Si, O} potential (Si is a subset of its species) and
  has no lattice mismatch, so it is a cheap second run under the *same*
  frozen protocol. Ionic / polar pairs such as
  SiO2/LiNbO3 are supported by keeping the structure builder and the
  potential species-generic, with hooks documented for the extra
  polar-slab and long-range-electrostatics work those pairs need (see
  the MLIP-training bullet and `PRIOR_ART.md` §1.2).
- **Structure builder — ASE [ADOPT · glue · recipes BUILD].** Builds
  slab and facing-pair models (steps 3, 5): ASE is the adopted
  toolkit, and the SAB-specific slab and facing-pair construction
  **recipes layered on it are ours to build** (`VISION.md` goal 5). A
  working polar-slab symmetrizer for surfaces like LiNbO₃ (0001) and
  GaN — which carry a dipole pymatgen cannot remove unaided — already
  exists in prior art (`PRIOR_ART.md` §1.2).
  **Facing-pair lattice matching (STRUCTURAL 4, 2026-07-08).**
  Constructing the step-5 pair of two dissimilar crystals in one
  periodic box is where lateral lattice mismatch bites — but surface
  activation softens it, and the softening is physical, not a trick.
  Amorphizing each surface is exactly what lets dissimilar materials
  bond, because the interface becomes an amorphous–amorphous contact
  with **no registry requirement**; imposing a tight coincidence lattice
  *there* would manufacture an epitaxial order the real process does not
  have. The constraint instead relocates to the crystalline
  **substrates** beneath the thin activated skins: the periodic box must
  suit each substrate lattice, but the amorphous interlayer **buffers
  residual misfit**, so a looser tolerance — hence a smaller coincidence
  supercell — suffices. So step 5 is: pick a coincidence supercell of
  the two substrate lattices within a relaxed misfit tolerance, apply
  the small residual as **recorded substrate strain** (provenance,
  `VISION.md` goal 3), and let the activated layers absorb the rest.
  v1 (decided 2026-07-08) bonds a **crystalline SiO2 substrate —
  β-cristobalite, the closest-to-Si polymorph — to crystalline Si**, so
  v1 genuinely exercises the coincidence matcher — our Si/cristobalite
  pairing is new build, but prior art now offers a worked example to
  adapt (`PRIOR_ART.md` §1.5): a 16×SiO2 ≈ 15×LiNbO3 coincidence cell
  (≈77.9 Å) cutting a 4.78% raw mismatch to ~1.8% residual strain
  applied *before* amorphization, the same rationale we give. The
  matcher is written **pair-generic** (any two lattices, tolerance-
  driven) so future pairs reuse it: it searches whole-number tiling
  matrices over *both* surface vectors plus a relative in-plane twist
  (the Zur-McGill construction, adopted from `pymatgen`), so it never
  assumes equal cell lengths, a particular cell angle, or a twist of
  zero. Prior art's 16:15 cell is a hand-derived constant, not a solved
  one, and its two slabs are in fact strained to cells 0.9% apart — so
  it is a worked *example* to check ourselves against, not a method to
  inherit (`DESIGN.md` §2). Two structural consequences: the **facing
  pair, not the slab, is the object the builder constructs** — the
  shared lateral cell is an invariant of the pair, so per-slab
  construction cannot precede solving for it — and the lattice constants
  the matcher works from come from a **bulk relaxation under the current
  potential** (referenced to VASP), not from literature values, so the
  recorded residual strain is true for the potential that will actually
  run the dynamics. That makes the structure builder a **consumer of
  step 2's potential**, and the shared cell is re-derived whenever an
  ALF round changes the committee. The exact
  faces (a material knob), coincidence indices, tolerance, and strain
  split (weighted by each slab's stiffness *and* thickness, not split
  evenly) are DESIGN work. Two downstreams: the applied substrate strain
  is a configuration dimension the MLIP must cover (STRUCTURAL 1b), and
  because the interface is a disordered amorphous contact the bond
  metric should be **averaged over amorphization realizations**, not
  read from a single seed.
  Just as importantly, ASE is the **translator** that converts a
  structure between programs' file formats — including carrying a
  step-7 snapshot into Imago for step 8. ASE is the busiest tool but
  is *always glue, never the compute engine*. One caveat: that Imago
  crossing is not free — the ASE adapter that makes it possible is
  finicky, real work to write, and the interop is cheap only once
  that adapter exists (it is a cross-project dependency; see §4).
- **Surface-dynamics engine — LAMMPS + MLIP
  [engine ADOPT · protocol BUILD].** Runs the amorphize (step 4) and
  press / separate (steps 6, 7) molecular dynamics. The engine is
  adopted; the *protocol* (how we activate, press, and separate) is
  ours. A working Ar-bombardment *amorphize* recipe (step 4),
  validated on SiO₂ with classical potentials, already exists in prior
  art and is a strong starting point (`PRIOR_ART.md` §1.2); the press /
  separate protocol there is designed but unbuilt. That prior-art
  validation is of the *recipe* — that it reliably *disorders* the
  surface (g(r), coordination, ~29 Å depth) — **not** of the classical
  amorphous *structure*'s accuracy, which SABSIM checks separately (see
  the MLIP-training and potential-quality bullets). Per STRUCTURAL 1b the
  violent Ar cascade runs on a classical + ZBL potential; the MLIP takes
  over only for the gentle post-cascade anneal and steps 6-7. Surface
  activation is designed as a pluggable **mechanism** — energetic-particle
  bombardment (an ion or fast-atom beam, identical in classical MD) is
  v1's implementation, and the seam leaves room for other methods (e.g.
  plasma) without reworking step 4 (see DESIGN §3).
- **Training-data physics — VASP [ADOPT].** Produces the varied
  atom-configuration-and-forces training set (step 1). Chosen over
  Imago deliberately — see note below.
- **MLIP training — ALF active-learning loop
  [engine ADOPT · backend plugin BUILD].** Turns training data into the
  fast approximate potential (step 2). The adopted inner loop is LANL
  **ALF** (Active Learning Framework); its make-data / train / find-gaps
  cycle is a **black box** we configure, not fork (`VISION.md`
  principle 5, inner loop).
  **Decision — the MLIP backend is a config-selected plugin, not a
  fork.** ALF loads its trainer and ensemble calculator by dotted path,
  so *which potential we actually train* is a documented knob
  (`VISION.md` principle 1): **DeePMD** (primary), **SNAP** (a "how
  cheap can we go" benchmark), and **HIPPYNN** (ALF's default, kept as
  the accuracy reference). DeePMD is primary because it is cheaper at
  inference and deploys through a first-class `pair_style deepmd` in the
  step-6/7 LAMMPS runs (SNAP is native `pair_style snap`); a cheaper,
  LAMMPS-native potential therefore simplifies *both* the training side
  here and the production side downstream. What *we* build is only a
  thin backend plugin — an ANI-HDF5 → DeePMD data converter plus
  train / load adapters, referenced by dotted path with no change to
  ALF's source (prototype at `prototypes/alf_deepmd/`, converter unit-
  tested). Uncertainty-driven dynamics (UDD) is a *potential-agnostic*
  knob in this same loop — the sampling bias lives inside ALF's
  committee calculator, so it applies to any backend; that mechanism is
  a DESIGN-level detail, noted here only so the seam is on record.
  **Decision — one multi-species potential spanning the pair
  (STRUCTURAL 1a, 2026-07-08).** A bonded interface puts A-atoms and
  B-atoms in the same neighbor shell — an environment present in neither
  bulk — and once the wafers intermix there is no way to assign a
  per-material potential atom by atom. So the MLIP is a SINGLE potential
  over the union of the pair's species (Si/SiO2 -> {Si, O};
  SiO2/LiNbO3 -> {Si, O, Li, Nb}), trained on cross-interface configs as
  well as each bulk and surface. It is therefore a **per-pair bespoke
  artifact** — retargeting to a new pair means a new potential (the
  retarget-cost RISK in `TODO.md`). DeePMD is natively multi-element, so
  the backend already supports this; the joint fit is harder but is
  exactly where ALF's active learning concentrates data. That the
  training set MUST contain interface configs is a requirement handed to
  the bootstrap-coverage work (STRUCTURAL 1b).
  **v1 scope + a fidelity caveat.** v1 targets **Si/SiO2** — genuinely
  dissimilar yet covalent and a Maszara calibration anchor — for which a
  SHORT-RANGE MLIP (DeePMD `se_e2_a`) is defensible. Strongly ionic /
  ferroelectric pairs (LiNbO3, GaN) are a documented future target: they
  may need a long-range electrostatics extension (e.g. DPLR), and a
  macroscopic slab dipole is itself a long-range object a short-range
  potential cannot represent — the same root as the **polar-slab dipole
  problem** (the mirror symmetrizer in `PRIOR_ART.md` §1.2 and the
  structure-builder bullet), so symmetrizing a polar slab is also what
  makes a short-range MLIP tenable there. The species-union machinery
  stays pair-generic, with documented hooks so an ionic/polar pair can
  be added later without reworking the design.
  **Bootstrap coverage — breaking the circularity (STRUCTURAL 1b,
  2026-07-08).** Steps 4/6/7 run MD *on* the MLIP, yet the configs they
  visit (amorphized surface, pressed interface, breaking bonds) are what
  the MLIP must be trained on — circular. Active learning is the escape:
  the config *generator* need not be the production potential. (1)
  **Seed** a first DeePMD on hand-built near-equilibrium DFT — bulk Si,
  bulk cristobalite, their surfaces, the *strained* substrates
  STRUCTURAL 4 introduces, moderate-T rattled snapshots (optionally
  warm-started from a foundation MLIP). (2) **Generate** the hard configs
  with a cheaper generator: the violent Ar cascade runs on a
  well-validated classical silica potential (BKS or Vashishta, not an
  arbitrary Tersoff set) with a ZBL overlay — so amorphous-surface
  configs are manufactured with no MLIP, breaking the circularity; the
  pressed interface and separation run on the seed MLIP. (3) **Label** a
  selected subset with VASP, **train** DeePMD, and **refine** with ALF —
  rerun the protocol, let committee / UDD uncertainty flag configs,
  VASP-label those, retrain, until committee uncertainty across a full
  protocol run falls below threshold. (4) **Convergence** is the
  potential-quality gate plus that uncertainty threshold; it hands off to
  the interface check of STRUCTURAL 3.
  **Division of labor + safeguards.** The MLIP is *not* asked to
  reproduce cascades or Ar chemistry: the classical + ZBL potential owns
  the violent step-4 cascade, and the MLIP takes over only for the gentle
  post-cascade anneal and steps 6-7 — so its species set stays {Si, O}
  and the deferred question of where ZBL lives is settled (in the
  cascade). Because glasses are kinetically trapped, a gentle anneal
  cannot fix a badly-wrong classical topology, so the classical structure
  is trusted only as a *starting basin*: it is corrected downstream (VASP
  labels + MLIP re-anneal + ALF) and **validated** — g(r), ring and
  coordination statistics against DFT and experiment — as an added check
  in the potential-quality gate, anchored by small DFT melt-quench cells.
  A fidelity ladder keeps the classical structure a rung, not a ceiling:
  classical cascade -> MLIP re-anneal (v1) -> eventually MLIP melt-quench
  (once the MLIP has molten-regime coverage the MLIP itself makes the
  glass). For a future pair lacking a trustworthy classical potential the
  generator swaps to a foundation MLIP or a DFT melt-quench; the
  bootstrap *pattern* is unchanged.
- **Bond characterization — Imago + Kaleidoscope
  [engine ADOPT · protocol BUILD · our edge].**
  Kaleidoscope fans the chosen step-8 snapshots out as a batch of
  Imago analyses across the cluster, then caches and tracks which
  succeeded — dispatch and bookkeeping only, per `VISION.md` principle 3.
  Turning the raw returns into bonding numbers is **not** Kaleidoscope's
  job; it is SABSIM's harvester (below). This is exactly the batch we
  validated in the prior session — a live four-structure SLURM campaign
  (silicon, diamond, graphite, silica) on the rulisp-lab partition that
  proved cross-node dispatch, worker parallelism, and cache-on-rerun end
  to end.
  `DESIGN.md` §8 refines SABSIM's side of the cross-project seam into
  **four artifacts**, all buildable and testable before Imago can run:
  - **snapshot selector** (§8.3) — three detectors (hold PE minima,
    pull PE maxima, σ_zz drop spikes) run on the interface-subcell atom
    set, gated by prominence and merged by event, plus the always-
    included relaxed endpoints; a pure function of the trajectory;
  - **skeleton preparer** (§8.4) — turns each selected snapshot into a
    ready Imago input (structure in OLCAO format, full basis and Γ-point
    sampling per `PRIOR_ART.md` §1.2, run settings). Imago inherits the
    OLCAO input *format* (file-layout and command-sequence tweaks only),
    but not its `$OLCAO_RC` working-directory-as-config convention; the
    preparer is a pure function of structure + settings, testable
    against a known-good input with no Imago present;
  - **manifest** (§8.5) — the whole interface to Kaleidoscope: one list
    of self-describing units keyed by content fingerprint (§1.4);
  - **harvester** (§8.6) — collects the returns, parses Imago's native
    channel, and emits §6.6 measure records, reporting **coverage by
    detector class** because all-electron runs fail on the hard,
    signal-carrying frames rather than at random.

  Only **execution** waits on the cross-project deliverables (the RISK
  item in `TODO.md`); the four artifacts above do not. Keeping the seam
  explicit lets the Imago track advance to the execution boundary on our
  schedule, not theirs.
- **Two separate checks and the diagnosis that routes between them —
  potential quality vs. bond outcome [BUILD].** Once folded into a
  single "quality gate," the two checks are different in kind and must
  stay apart; the third sub-item below is the routing logic, not a
  third check:
  - **Potential-quality gate.** Is the trained MLIP any good on its
    own terms? — **equilibrium lattice constants**, elastic stiffness,
    surface energies, and similar
    properties checked against VASP and experiment. A failure here is
    a *model* problem, so the outer-loop remedy fits: add training
    data where the potential is weak (§3). The lattice constants are
    load-bearing beyond the gate: the structure builder matches on them
    and records the residual strain from them (see the structure-builder
    bullet), so a potential with a wrong lattice builds a wrong box.
    It also **validates the
    amorphous surface structure** — g(r), ring and coordination
    statistics against DFT and experiment, anchored by small DFT
    melt-quench cells — so a wrong classical starting glass is caught
    here rather than propagating into the interface and the bond number
    (STRUCTURAL 1b). **Interface-fidelity check (STRUCTURAL 3,
    2026-07-08).** The bulk/surface properties above do NOT probe the
    one region that matters most — the bonded interface — so a potential
    can pass them yet be wrong exactly where the bond number is read. The
    gate therefore also validates the interface, with two complementary
    signals: (i) **committee / UDD uncertainty along the whole
    press-then-pull trajectory** (endpoints AND the bond-breaking
    pathway) — cheap, always available, catching extrapolation the
    potential *knows* about; and (ii) an **all-electron ΔE cross-check on
    interface subcells** — the STRUCTURAL-2 MLIP-vs-reference
    work-of-adhesion comparison — catching the potential being
    *confidently wrong* (committee agrees but is off). The reference is
    VASP on a small interface subcell (available now, the always-on
    backstop) or Imago at interface scale once that pipeline is
    ready. Together they make interface-coverage failure *visible*
    instead of letting it masquerade as a protocol failure.
  - **Bond-debond outcome metric.** The scientific deliverable: the
    **work of separation per unit area** (joules per square meter) of
    the pressed-then-pulled interface — kept **pluggable** so several
    measures can be compared (the same "open the method, fix the
    interface" stance as the MLIP backend). It is anchored to
    **surface-activated** (not thermal-fusion) bonding energies for
    silicon-to-silicon and silicon-to-silicon-dioxide from razor-blade
    crack-opening (Maszara) tests, used as **relative** anchors —
    trends and ratios, since a fast nanoscale pull-apart cannot hit an
    absolute experimental fracture energy. A bad outcome number can
    stem from the *protocol* (activation, press, separate), which more
    training data will not fix — so it does not feed the same remedy as
    the potential gate. The work-of-separation-per-area unit was
    independently arrived at in prior art (`PRIOR_ART.md` §1.2), and the
    OLCAO analysis plan there (its `DESIGN.md` §5) is reusable input for
    step-8 characterization.
  - **Diagnosis — routing a bad bond number (STRUCTURAL 3).** The two
    checks keep their two remedies (potential problem -> add data;
    protocol problem -> data won't help), but the interface-fidelity
    check above closes the hole where an interface-coverage failure was
    silently filed as *protocol*. A bad bond number is read along an
    ordered chain, because each test is interpretable only given the
    ones before it. **Five outcomes** (`DESIGN.md` §7.6 refines the
    original three): if a check the chain depends on could not be
    evaluated -> `undiagnosed`, since a test that did not run may not be
    counted as passed; else if the measurement is invalid — truncated
    trajectory, atoms lost, an internal consistency check failed, an
    uncertainty abort -> `void`, and a void measurement is **never
    diagnosed**, because diagnosing a number nobody believes is worse
    than reporting nothing; else if the bulk/surface gate fails ->
    `bulk_model`, add data; else if the interface-fidelity check fails
    -> `interface_coverage`, add *interface* training data (still the
    data remedy, now correctly targeted); else -> `protocol`
    (activation, press, separate), which more data will not fix.
    The `void` outcome is not a new idea but an inherited one: `DESIGN.md`
    §5 already refuses truncated trajectories and §6.5 already requires
    internal checks to pass.
    Because `protocol` is the last branch, it is reached **by
    elimination**, and elimination is sound only if the alternatives are
    exhaustive — we have enumerated exactly two ways for a potential to
    be at fault. The gate therefore reports the cause **and, separately,
    the basis on which it was reached** (`direct_evidence` when a named
    protocol check fired, `by_elimination` when none did). Nothing is
    discarded, a reader can weigh inference differently from
    observation, and a study whose protocol verdicts are mostly reached
    by elimination is telling us our protocol checks are too sparse.
    In v1 all of this is a REPORTED diagnostic label, not an automated
    action (the gate is a reporter); wiring it to `data_targeting` is
    the future closed loop (§3).
- **Bond-outcome analyzer — the pluggable measure set
  [BUILD · resolved from STRUCTURAL 2, 2026-07-08].** The bond-outcome
  check above does not reduce to one number; it emits a small **measure
  vector**, produced by a dedicated analyzer kept distinct from the
  LAMMPS engine that ran the trajectory and from the Imago/Kaleidoscope
  batch that produced the electronic data. Two families of measure, by
  the physics they capture:
  - **Mechanical (dissipative; path- and rate-dependent).** The MD
    **work-integral** — force integrated over the step-7 pull, per unit
    area. It is pure post-processing of a trajectory LAMMPS already
    recorded, so it is **always available with no Imago at all**: the
    headline number and the deliverable's schedule fallback, and the
    measure commensurable with the dissipative Maszara crack-opening
    test.
  - **Thermodynamic (reversible; energy difference of relaxed states).**
    The work of adhesion, (energy_separated − energy_bonded) per unit
    area, computed at **two fidelities of the same quantity**: an
    MLIP-fidelity value from a quasi-static LAMMPS relax-and-energy
    sequence (cheap enough to trace a whole energy-versus-separation
    curve) and an OLCAO all-electron value from Imago on the relaxed
    bonded and separated endpoints (accurate, a few states; or VASP on a
    small interface subcell as the always-on backstop before Imago is
    ready — the same all-electron reference STRUCTURAL 3's interface
    check uses). Because
    they are the same difference at different fidelity, their
    **disagreement is a direct interface-region check on the
    potential** — the probe STRUCTURAL 3 asks for. It is reference-free:
    both states hold the same atoms, so per-atom energy zero-points
    cancel; read it as a trend/ratio, per the relative-calibration
    stance.
  Imago also yields **bond descriptors** — effective charge Q*, bond
  order, coordination — along the snapshot series: the qualitative
  "what kind of bond formed" companions to the energies. Generally the
  mechanical W_sep ≥ the thermodynamic work of adhesion; the gap is the
  dissipation and their ratio is itself an observable, so the gate
  reports the vector and does not expect the entries to agree. Prior art
  both confirms and de-risks this (`PRIOR_ART.md` §1.5): its bond/debond
  design defines the same two measures, and its classical pipeline has
  already run the mechanical pull end to end — a concrete protocol
  template for steps 5-7, though its interface number is uncalibrated
  because a placeholder pair potential stands exactly where SABSIM's
  trained MLIP will.
- **v1 gate is a reporter, not a controller [BUILD].** In v1 both
  checks above only *evaluate and report* pass/fail; automatically
  closing the outer loop on their verdicts is deferred (see §4 and
  `VISION.md` principle 5).

> **Why VASP, not Imago, for step 1.** Imago's OLCAO method uses a
> fixed set of atom-centered building blocks tuned for near-
> equilibrium geometries; the wildly distorted shapes that argon
> bombardment produces are a poor fit for that basis. VASP's PAW
> method already reconstructs much all-electron detail, and the truly
> extreme close-approach is handled by a splined ZBL repulsion. So:
> VASP for the dynamic, distorted configs (step 1); Imago for the
> calm, bonded interfaces (step 8).

> **Why an MLIP at all — the multiscale ladder.** Simulation methods
> sit on a ladder of size scales: electrons at the fine end (VASP,
> Imago), then atoms in motion (LAMMPS), then mesoscale / continuum
> at the coarse end. No single method spans the whole ladder. The
> fine-grained codes reach *up* it by acting as **data producers**:
> run the accurate-but-expensive electron-scale calculations (step
> 1), distill them into a fast approximate potential (step 2), then
> run *that* potential on the large press / separate models (steps
> 6-7) a first-principles code could never afford directly. The MLIP
> is that bridge — which is why step 2 exists at all.

---

## 3. Dependency Graph

The whole pipeline in one picture (data flows downward; the controller
owns the loop):

```
OUTER CONTROLLER  (simple Python first; heavier only if forced)
   |  owns the SAB quality-gate loop — the "brain"
   |
   |   [ADOPT] VASP --training data--> ALF (pluggable) --> MLIP
   |                                      ^ (inner loop hidden inside)
   |
   |   [BUILD] ASE builds slabs --> LAMMPS amorphize
   |              --> ASE builds the pair --> LAMMPS press / separate
   |                     |  snapshots out
   |              ASE converts the snapshots
   |                     |
   +-- [OUR EDGE] Kaleidoscope batch --> Imago analysis (step 8)
                          |
                  quality gate: pass our SAB tests? --> loop back
```

The step-8 batch layer, expanded (each layer is ignorant of the one
below it — the separation that lets pieces be swapped):

```
controller   "analyze these N interface snapshots"
   |
Kaleidoscope  the bookkeeper: holds the list, checks the cache,
   |          hands out work, collects results
   |
dispatcher    decides WHERE each unit runs (here, or on the cluster)
   |
Imago         the doer: runs the all-electron physics
```

The outer quality-gate loop, expressed as control flow (the
repetition lives in ordinary program logic, *not* in the wiring
diagram — the wiring stays an acyclic graph):

```
while not passes_our_SAB_quality_tests:
    model  = train_using_existing_tools(training_data)  # inner, adopt
    report = run_our_SAB_validation_tests(model)        # OUR tests
    if report.good_enough():
        break
    training_data += data_targeting(report.weaknesses)  # add the gap
```

> **v1 runs one pass of this loop, by hand.** In v1 the body executes
> once and *reports*; a human reads the verdict and decides whether to
> add data and rerun. The `while` shown here is the eventual automated
> target, not the first milestone (`VISION.md` principle 5). Note too
> that `run_our_SAB_validation_tests` is really the two distinct
> checks of §2.3 — potential quality (bulk/surface AND interface
> fidelity) and bond outcome. The `data_targeting` line fixes potential
> problems — including interface-coverage failures, which the
> interface-fidelity check (STRUCTURAL 3) routes here rather than into
> the protocol bucket — while a genuine protocol failure needs a
> different remedy.

---

## 4. Build System

<!-- How to build, install, and run. Dependencies listed here. -->

This is the design phase; there is no build yet. The intended external
dependencies, by work group, are:

- **VASP** — training-data physics (step 1).
- **LAMMPS** — surface dynamics (steps 4, 6, 7).
- **ASE** (Atomic Simulation Environment) — structure building and
  format translation (steps 3, 5, and snapshot transport into step 8).
- **ALF** (LANL Active Learning Framework) — MLIP training (step 2),
  driven through **Parsl** (the same dispatch substrate Kaleidoscope
  uses). Its MLIP backend is a **config-selected plugin — DeePMD
  (primary) | SNAP | HIPPYNN** (§2.3); only a thin backend plugin is
  ours, with no ALF fork.
- **Imago** + **Kaleidoscope** (which uses **Parsl** for SLURM
  dispatch) — bond characterization (step 8).
- **Outer orchestrator — the thin Tier-A sequencer.** The execution
  model is now settled at three tiers (§4.1); this covers only the
  outermost. Its **dispatch substrate is Parsl** — what ALF and
  Kaleidoscope already use — so our own Tier-C submission aligns on one
  stack (separate instances, never nested; §4.1). **v1 starts
  dead-simple with plain `sbatch` scripts**; Parsl-driven submission
  arrives with automation. Still OPEN is only the *heavier workflow /
  provenance manager* that may sit on top once we query across hundreds
  of runs or close the loop — candidates unchanged, light to heavy:
  **Snakemake** (files-produce-files, weak at loops), **jobflow**
  (Python loops + moderate history), **AiiDA** (best-in-class provenance,
  heavy, hard to leave). Recommendation stands: provenance by discipline,
  graduate under real pressure (`VISION.md` principle 6).

**Cross-project dependencies (Imago side).** SABSIM relies on a few
Imago deliverables maturing in parallel: a fast, lightweight step-8
analysis mode; the ASE adapter (so snapshots can cross into Imago);
and a good initial-guess potential database that makes large, cheap
analyses possible.

### 4.1 Execution and resource model on HPC

How the heterogeneous pipeline actually runs on a cluster. Kept at
architecture altitude — config formats and Parsl executor details are
DESIGN work; the walls at the end are forward-notes so DESIGN avoids
them.

**Three tiers, kept separate.**
- **Tier A — a thin outer sequencer (ours).** Runs the eight steps in
  order and owns the quality-gate loop. In v1 it is hand-run or a simple
  script: launch a step, wait, check the output contract, launch the
  next.
- **Tier B — two adopted Parsl sub-orchestrators, treated as black
  boxes.** ALF (step 2) drives its own Parsl to fan out VASP labeling and
  DeePMD training; Kaleidoscope (step 8) drives its own Parsl to fan out
  Imago runs. Tier A invokes each as one opaque step and waits — it never
  looks inside.
- **Tier C — plain jobs Tier A submits directly:** the VASP training runs
  (when not inside ALF) and the LAMMPS amorphize / press / separate runs.

**Rule — no Parsl inside Parsl.** ALF and Kaleidoscope each stand up
their own Parsl kernel; wrapping them in an outer Parsl workflow would
nest Parsl in Parsl, which is fragile. So the outer tier stays a
lightweight sequencer and each Parsl tool owns its own SLURM submission
independently — "thin orchestration" (`VISION.md` principle 6) made
concrete.

**Dispatch substrate.** Parsl is the project's common dispatch technology
— ALF uses it, Kaleidoscope uses it, and our own Tier-C submission will
too, as *separate* Parsl instances. v1 begins dead-simple with plain
`sbatch` scripts; Parsl-driven submission arrives with automation.

**Linking = file contracts on a shared filesystem.** Steps are decoupled
through on-disk file formats, so passing data between them is just
reading and writing on the cluster's shared parallel filesystem — no
explicit staging. Large trajectories go on scratch, not home.

**Deployment / resource layer — the "where to run" knob.** Per
`VISION.md` principle 1, every site-specific and resource choice lives in
an editable deployment config, never in code: resource *class* (CPU vs
GPU partition), node / core / GPU counts, walltime, memory, and
module / environment setup. This is the concrete form of the
Settings / deployment-separation module (§2.3), and is emphatically
**not** the prior-art anti-pattern of baking partition names and site
details into emitted scripts (`PRIOR_ART.md` §1.2 item 7). Routing is
**per job, not per step**, because the pipeline is CPU/GPU-heterogeneous
and one step can straddle both — step 4 runs a classical + ZBL cascade on
CPU and then a gentle MLIP anneal on GPU:

| Work                                   | Resource class |
|----------------------------------------|----------------|
| VASP labeling (step 1 / inside ALF)    | CPU (MPI)      |
| DeePMD training (inside ALF)           | GPU            |
| Classical + ZBL Ar cascade (step 4)    | CPU            |
| MLIP re-anneal + press / separate      | GPU (`deepmd`) |
| Imago (step 8)                         | CPU            |

**Execution walls, flagged for DESIGN.**
1. **Parsl-in-Parsl** — avoided by the tier separation above.
2. **CPU/GPU routing** — every job carries a resource class the
   deployment layer maps; never assume a single partition.
3. **Site-specifics in code** — externalize all of it.
4. **The persistent control process** — a long-lived controller cannot
   sit on a login node (it is killed). Fine for v1 (hand-run); automation
   later must run it inside a job or use a submit-and-monitor manager.
5. **ALF's Parsl config for the target machine** — a bounded setup task
   (a CPU-QM executor + a GPU-train executor), not a fork. The bootstrap
   loop (STRUCTURAL 1b) is the most execution-intensive part: ALF's Parsl
   interleaved with our LAMMPS protocol runs.
6. **Large trajectory I/O** — scratch vs home.

**Current target machine (one instance; the model stays generic).**
Today's cluster is a **SLURM** system with a shared **PixStor** parallel
filesystem and a lab-owned partition (`rulisp-lab`) spanning CPU and GPU
nodes — the partition the Kaleidoscope step-8 batch was validated on.
Nothing above depends on those specifics: any SLURM-plus-shared-filesystem
HPC with CPU and GPU partitions instantiates the same three-tier model by
swapping the deployment config.

---

## 5. Development Trajectory and Checkpoints

<!-- How the design becomes working code without backtracking, plus the
git tag / branching strategy for baselines. -->

SABSIM glues six external codes to several novel components of our own, so
the danger is coding — or pseudocoding — ourselves into a box that forces
wide backtracking. The design already did most of the work that prevents
this: nearly every seam, plugin point, and first-class fallback it chose
exists to let modules be built, swapped, and tested independently. This
section makes that latent property an explicit development policy.

**The spine, in one sentence:** freeze the contracts between steps first,
put the cheapest possible stand-in behind each one, get a wrong-but-well-
formed number to fall out of the whole eight-step pipeline as early as
possible, then deepen each module behind its already-stable contract — in
an order set by risk, not by step number.

### 5.1 The policy — six practices

- **The contract is the unit of stability, not the module.**
  Backtracking happens when a change inside one module forces changes in
  its neighbours; the cure is that neighbours depend only on a module's
  *contract*, never its internals. The design already named these
  contracts: the labeled-group structure contract crossing the 3→4→5→6→7
  seam (`DESIGN.md` §2.6), the measure-vector schema the gate reads by
  name and status (`DESIGN.md` §6.6), the manifest and its content-
  fingerprint identity into Kaleidoscope (`DESIGN.md` §8.5, §1.4), the
  file-contracts-on-shared-filesystem linking model (§4.1), and the run
  specification itself (`DESIGN.md` §1). A seam schema, once written,
  changes only by deliberate amendment with a recorded note — the same
  discipline the design chain itself uses.
- **A walking skeleton before any depth.** Build the thinnest end-to-end
  thread first: a run spec for the **Si/Si** reference → structure builder
  → a **classical potential standing in for the MLIP** behind `pair_style`
  → LAMMPS press/pull → analyzer emitting only the mechanical work-
  integral (needs no Imago) → gate reports a verdict. It touches every
  seam under real data flow with no VASP, no ALF, no Imago. Its number is
  deliberately **not trusted** — a plumbing test, its verdict withheld
  (`report, never restrict`, `DESIGN.md` §1) — because the point is that
  the bytes flow and the schemas hold. Seams get stress-tested when they
  are cheapest to move.
- **Every module has a cheap stand-in behind its contract.** Generalize
  the fidelity ladder (classical → MLIP re-anneal → melt-quench, §2.3) to
  *every* module: a classical potential for the MLIP, the VASP subcell (or
  a schema-valid mock) for Imago, a token cascade for activation, hand-
  built seed data for ALF. A stand-in that satisfies the contract **is**
  the module's contract test, not throwaway work, and it keeps the whole
  pipeline runnable at all times — "the pipeline always runs" is the
  strongest anti-backtracking invariant available.
- **Build order by risk and blast radius, not by step number.** Steps 1
  (VASP) and 8-execution (Imago) are the lowest *design* risk and the
  highest *external-dependency* risk — adopt-and-wait, not ours to
  schedule — so they come late; our uncertainty and our edge live in the
  middle of the pipeline, and that is where construction concentrates.
- **A per-module definition of done.** A module is *done to contract*
  when it has a frozen schema, a golden input/output fixture, a contract
  test that passes independently of the neighbouring tools, and
  provenance emission. Two such fixtures already exist — the
  `prototypes/alf_deepmd` converter round-trip and the validated four-
  structure Kaleidoscope campaign. A module never advances past a red
  contract test.
- **Prior art's failure modes are coding policy from line one.** Prior
  art failed by drift, not design: a `NOTE_INCOMPLETE` trajectory quoted
  as a result, a newest-file-wins fetch reading the wrong run, a hardcoded
  well-depth string disagreeing with the code, warnings that decorated
  instead of gating. The design answered each — gates stop rather than
  warn (`DESIGN.md` §5.7); identifiers are explicit, never newest-file-
  wins (§5.7, §8.5); no hidden defaults, the loader rejects an incomplete
  spec (§1.4); outputs are machine-readable, never prose (§6.6). These are
  enforced from the first commit, not rediscovered.

### 5.2 Eight steps are five buildable units plus a frame

The pipeline's eight steps do not map one-to-one onto modules: three
DESIGN sections cover two steps each, and three cover none — they are the
frame that wraps every step.

| Steps | Buildable unit        | Tool                | DESIGN §   |
|-------|-----------------------|---------------------|------------|
| 3, 5  | Structure builder     | ASE                 | §2         |
| 4     | Activation            | LAMMPS + ZBL        | §3         |
| 1, 2  | Bootstrap (training)  | VASP · ALF/DeePMD   | §4         |
| 6, 7  | Bond/debond MD        | LAMMPS + MLIP       | §5         |
| 8     | Characterization      | Imago/Kaleidoscope  | §8         |
| —     | Frame                 | run-spec·schema·gate| §1, §6, §7 |

So construction sequences five units and a frame, not eight steps in
numeric order.

### 5.3 The deepening waves

Every step is present from the start; fidelity rises in waves.

- **Wave 0 — the Si/Si walking skeleton.** Steps 1+2 *skipped* (classical
  stand-in); step 3 real but minimal; step 4 stubbed; step 5 real but
  **trivial**, because Si/Si has no lattice mismatch and the coincidence
  matcher is effectively identity — which is exactly why Si/Si is the
  right skeleton pair; steps 6+7 real on the classical potential; step 8
  mocked against a schema-valid fixture; the frame real throughout.
  Output: one untrusted number with full provenance.
- **Wave 1 — deepen what is ours and needs no MLIP.** Step 4 becomes real
  amorphization with its pass/fail gate; the analyzer grows from one
  measure to the full Imago-free vector; the gate's diagnosis chain goes
  live.
- **Wave 2 — the bootstrap, for real (steps 1+2 together).** VASP
  labeling + ALF + the DeePMD committee + UDD; the trained MLIP replaces
  the classical stand-in **behind the same `pair_style` seam**, and the
  potential-quality gate's bulk/surface half switches on.
- **Wave 3 — the Si/Si → Si/SiO2 transition.** A *milestone, not a step*,
  and the single most important "prove it here" gate: the coincidence
  matcher (step 5), the real dissimilar amorphous–amorphous interface, and
  STRUCTURAL 1a/1b/3/4 all become load-bearing at once, having been
  dormant behind the Si/Si choice until now.
- **Wave 4 — characterization execution (step 8).** The four SABSIM-side
  artifacts, fixture-tested back in Waves 1–2, connect to real Imago when
  it lands; until then the VASP subcell backstop carries the all-electron
  measure, and the Imago variants come online last — the schedule
  insurance the design already guaranteed (`DESIGN.md` §8.8).

One design freedom to protect from Wave 0: steps 3/4/5 are reorderable by
setting (§2.1), so the structure builder and the activator must stay
**order-agnostic behind the structure contract** — neither may assume it
ran before or after the other. Hard-wiring build→amorphize→assemble in
the skeleton would quietly forfeit that freedom.

### 5.4 Consequence for PSEUDOCODE

The immediate next level obeys the same spine: **breadth-first shallow,
then depth-first per module.** The first pseudocode pass covers control
flow and the seam schemas — the Tier-A sequencer, run-spec load/validate,
the structure contract, the measure schema, the gate's precedence chain —
which is the walking skeleton expressed as pseudocode. The deep per-module
algorithms (the coincidence matcher, the UDD bias, the detector
prominence math) are filled in as each module is implemented, behind a
contract that is already frozen and skeleton-tested. Writing them all to
full depth up front would front-load the stable-behind-a-contract work
before a single seam had been validated — a form of coding into a box in
its own right.

### 5.5 Checkpoints and baselines

The prior Imago/Kaleidoscope effort used numbered checkpoints (for
example C68, C69) tagged in git with matching TODO entries and doc
revisions; a similar scheme is the natural fit, with each **wave**
(§5.3) and the **Si/SiO2 transition** as baseline tags. This first-pass
design mapping is the natural first baseline to tag.
