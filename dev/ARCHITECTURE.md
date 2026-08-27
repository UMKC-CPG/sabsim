# Architecture

> **Document hierarchy:** VISION → **ARCHITECTURE** → DESIGN →
> PSEUDOCODE → Code. For goals and principles, see `VISION.md`.
>
> **Status:** The full VISION → ARCHITECTURE → DESIGN → PSEUDOCODE chain
> is written, and the project is in the CODE phase, building the walking
> skeleton outward (see `TODO.md`). The big architectural decisions are
> settled here; a few boundaries — the outer-orchestrator choice among
> them — remain open and are tracked in `TODO.md`.

---

## 1. Repository Layout

```
sabsim/
  dev/
    VISION.md         Goals and principles
    ARCHITECTURE.md   This document
    DESIGN.md         Algorithmic design
    PSEUDOCODE.md     Algorithm specifications
    TODO.md           Task list by level
    PRIOR_ART.md      Existing overlapping work and reusable assets
  src/                Source code (orchestrator, quality gate, glue)
  src/tests/          Test suite
  share/              Version-controlled reference data (gate criteria)
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
   (universal MLIP + ZBL cascade; the gentle heal rides the bond
   stage — see §2.3)
5. Build the facing-pair (two amorphized surfaces toward each other)
   (the ORDER is fixed by the physics — each surface is activated alone
   in vacuum before the two halves ever meet; what IS a setting is
   activation on / off, §5.3)
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
split (§2.3): the violent Ar cascade runs on a **universal foundation
MLIP + ZBL** (a broad pre-trained model; the classical + ZBL fallback
was deprecated 2026-08-26), while the **per-pair committee** the pipeline
trains is never asked to reproduce cascades — only the foundation model
is.

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
- **Member specification — the study, and five groups of knobs [BUILD].**
  Per `VISION.md` goal 2 and principle 1, everything a user changes to
  point the pipeline at a new study lives in one editable place, apart
  from the fixed machinery. `DESIGN.md` §1 refines this in two ways.
  First, the configured object is a **study** — a set of members plus the
  **relations** among them — because the bond-outcome criterion is a
  *ratio* between two members and so belongs to neither one alone. A
  member
  remains self-contained and independently reproducible, and a study may
  be assembled after the fact from members that already exist. Each
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
  and deployment, which lives in a separate document (§4.1) that the
  member specification cannot express.
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
  member is reachable within time constraints; *iterating* over them
  (composition, dopant, activation level, pressure, temperature,
  crystal face) is deferred to the outer-loop coupling and convergence
  work still open in `TODO.md`. The design stays open-ended for that
  future sweep. v1 fixes the material knobs to the **Si/SiO2** pair
  (covalent, a Maszara calibration anchor) and additionally runs a
  **Si/Si same-material reference**, because the bond-outcome metric
  calibrates on the *relative* Si-Si-to-Si-SiO2 ratio (`VISION.md`
  goal 4) — one system yields only a point, the ratio needs both. Si/Si
  reuses the same {Si, O} potential (Si is a subset of its species) and
  has no lattice mismatch, so it is a cheap second member under the *same*
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
  A **v1 cell-shape boundary** rides on this construction, worth stating
  where the pair's cell is solved. The assembled pair's in-plane cell is
  driven **orthogonal** before it is written — a lattice reduction that
  zeroes any *removable* tilt (`slab_builder.orthogonalize_in_plane`),
  the same step a standalone half already takes. It is physics-preserving
  (a relabeling of the periodic cell; no atom moves relative to its
  neighbors) and not cosmetic: a pymatgen coincidence cell can lean to
  **twice LAMMPS's skew limit**, which `read_data` tolerates but a
  restart round-trip (the within-run resume, `DESIGN.md` §11) silently
  mis-bins, dropping atoms.
  On an already-square face (e.g. Si(100)) it is a no-op. The catch is
  that it removes only a *removable* tilt: a genuinely oblique face — a
  hexagonal surface, or a non-reducible triclinic cell — stays oblique,
  and the activation gate's minimum-image is written for an **orthogonal
  cell** (scalar per-axis wrapping), so it would mis-measure such a face.
  v1's Si and SiO2 faces all reduce to orthogonal, so this bounds nothing
  we run today; a general-triclinic minimum-image is the work that lifts
  it (tracked in `TODO.md`).
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
  violent Ar cascade runs on a UNIVERSAL foundation MLIP + ZBL (a
  classical + ZBL potential is the secondary fallback); the per-pair
  committee takes over only for the gentle post-cascade anneal and
  steps 6-7. Surface
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
  the config *generator* need not be the production potential, and a
  **universal foundation MLIP is that generator** — the 2026-08-21
  decision, promoting the earlier "optionally warm-started from a
  foundation MLIP" note to the primary path and retiring the separate
  hand-built-DFT seed. (1) **Generate** every hard config on the
  universal foundation MLIP: the violent Ar cascade on **foundation
  MLIP + ZBL** (a well-validated classical silica potential — BKS or
  Vashishta, not an arbitrary Tersoff set — with a ZBL overlay is the
  secondary fallback), and the pressed interface and the
  press/settle/pull on the *same* foundation MLIP — so all the hard
  configs are manufactured with **no per-pair MLIP**, breaking the
  circularity. The hand-built near-equilibrium DFT structures are no
  longer a required seed STAGE, but they remain REQUIRED TRAINING DATA
  — Collection 1 of the settled recipe (DESIGN §4.8 part 2), six
  families: bulk ground state, bulk strained, bulk melt-quench
  amorphous, clean surfaces, rattled snapshots, warm NVT/NPT runs.
  Collection 2 (DESIGN §4.8 part 5) is the five the protocol visits:
  amorphized surface, initial joint cell, relaxed joint cell, pressed
  cell, pulled cell. Eleven families, all required (settled
  2026-08-23); earlier text here called Collection 1 "optional", which
  contradicted DESIGN §4.8 and was corrected. (2) **Label** a selected subset with
  VASP, **train** the per-pair committee, and **refine** with ALF —
  rerun the protocol, let committee / UDD uncertainty flag configs,
  VASP-label those, retrain, until committee uncertainty across a full
  protocol run falls below threshold. (3) **Convergence** is the
  potential-quality gate plus that uncertainty threshold; it hands off
  to the interface check of STRUCTURAL 3. The **production** run — the
  one that emits the bond number — then uses the trained **committee**,
  whose spread is the uncertainty signal a single foundation model
  cannot give.
  **Division of labor + safeguards.** The distinction is between two
  MLIPs. The **per-pair committee** — the production potential — is
  *not* asked to reproduce cascades or Ar chemistry; that role belongs
  to the **universal foundation MLIP + ZBL**, which owns the violent
  step-4 cascade (a classical + ZBL potential is the secondary
  fallback), so the committee's species set stays {Si, O} and the
  deferred question of where ZBL lives is settled (in the cascade).
  Because glasses are kinetically trapped, the foundation-model
  amorphous structure is trusted only as a *starting basin*: it is
  corrected downstream (VASP labels + committee re-anneal + ALF) and
  **validated** — g(r), ring and coordination statistics against DFT
  and experiment — as an added check in the potential-quality gate,
  anchored by small DFT melt-quench cells. A fidelity ladder keeps that
  starting glass a rung, not a ceiling: foundation-MLIP cascade ->
  committee re-anneal -> eventually MLIP melt-quench (once the committee
  has molten-regime coverage it makes the glass itself). The bootstrap
  *pattern* is pair-generic — the universal foundation model is the
  default generator for every pair — and a classical potential or a DFT
  melt-quench is the fallback where the foundation model is untrusted.
- **Bootstrap — the potential manufactory [BUILD, 2026-08-26].** The
  code that runs steps 1–2: it reads a FORCE-MODEL RECIPE (the third
  input file, `DESIGN.md` §4.8; template `dev/templates/
  force_model_recipe.toml`), manufactures the training structures,
  writes and harvests the VASP labels, and — later — hands the labels to
  ALF to train the committee and refines by uncertainty. It lives in
  `src/sabsim/bootstrap/` behind its own verb, `sabsim bootstrap`, with
  one sub-verb per phase (`generate`, `label`, `harvest`; `train` and
  `refine` follow), because the bootstrap runs on a third clock — once
  per material domain, before any study — and must never be confused
  with the three per-member jobs. Like `sabsim prepare` it is a WRITER:
  `label` writes a VASP job array and submits nothing. Its runs are
  their own jobs, routed by a `[usage.label]` block of the deployment rc
  (CPU `vasp_gam` by default; the CUDA build is a switch of the same
  block), never by the member map (§4.1). The generation phase does no
  MD of its own for the hard configurations: it harvests the frames the
  ordinary member jobs record when run with `--dump-visuals` under the
  universal model (`PSEUDOCODE.md` §11.3, "generate mode is a consumer
  difference"), and builds only the calm Collection-1 structures itself.
  First slice built: recipe + generate + label/harvest, silicon only.
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
  of members or close the loop — candidates unchanged, light to heavy:
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
independently — "thin orchestration" (`VISION.md` principle 3) made
concrete.

**Dispatch substrate.** Parsl is the project's common dispatch technology
— ALF uses it, Kaleidoscope uses it, and our own Tier-C submission will
too, as *separate* Parsl instances. v1 begins dead-simple with plain
`sbatch` scripts; Parsl-driven submission arrives with automation.

**Linking = file contracts on a shared filesystem.** Steps are decoupled
through on-disk file formats, so passing data between them is just
reading and writing on the cluster's shared parallel filesystem — no
explicit staging. Large trajectories go on scratch, not home.

**Three roots, split by access pattern.** "Scratch, not home" needs
somewhere to point, so every path the pipeline reads or writes resolves
under one of three roots, each named by an environment variable. The
split is by how a file is *used*, not what it contains, because that is
what decides who may write it, whether losing it matters, and whether it
is safe to purge:

- **`SABSIM_SCRATCH`** — per-user, write-heavy, regenerable, purgeable.
  Run output: LAMMPS data files, trajectory dumps, per-phase logs.
- **`SABSIM_SHARE`** — group, read-mostly, authoritative, expensive to
  recreate. The install (LAMMPS / ALF / SABSIM), source potentials,
  reference datasets.
- **`SABSIM_LOCAL`** — per-user, read-mostly, an override. A personal
  copy of anything otherwise found in `SABSIM_SHARE`.

None is defaulted. Guessing a location and writing gigabytes into it is
how a home quota dies, and principle 1 is that "where to run" is
*stated*, not inferred — so an unset root is an error the caller sees at
once, never a silent fallback to somewhere plausible.

**The roots are set by a sourced shell rc, upstream of Python.** They
have to be established before any SABSIM code runs, for two reasons that
both rule out the deployment config as their home. `SABSIM_SHARE` names
the *install* itself, so the code that would read a config file cannot
run until the root that locates it is already known; and the resolution
rule just below finds that very config *through* the roots, so putting
the roots inside it is a circular lookup. The mechanism is instead the
one this group's other codes already use (imago's `imagorc`): a
machine-local file of plain `export` lines, kept at `.sabsim/sabsimrc`
inside the user's own clone of the repository, sourced by the same
activation alias that loads the environment. Living in the clone means
the rc travels with the checkout and needs no separate bookkeeping;
being sourced by the alias means all three roots are live in the shell
before the first `python` starts. The installer *generates* this file
fully populated, and the user is guided to edit it to match their own
machine — which keeps faith with "none is defaulted": the values are
stated in a file the user owns rather than inferred by code, and the
generator is exactly the "defaults exist only as a generator that emits
a complete file" escape hatch (`DESIGN.md` §1.4). That generation starts
from a *tracked* template, `dev/templates/sabsimrc`, sitting beside the
study-spec and deployment-rc templates — the distributable source of
truth that carries the lab's own paths as a WORKED example, exactly as
`deployment_rc.toml` does, not as code-level defaults. The v1 install
instantiates it by copying the template to `.sabsim/sabsimrc`, guarded so
an already-edited rc is never clobbered; the user then edits that copy.
A smarter emit-with-detected-values generator can replace the copy later
without touching the template or this contract, because the tracked
template is the invariant either way.

**Two install shapes share the one rc mechanism** (a system-wide
administrator install, serving every user at once, is deferred). For a
*single user*, the clone, the install, and the rc all sit in that user's
own space, and `SABSIM_LOCAL` stays inert. For a *group-leader* install,
the leader installs once into a group-readable location that every
user's `SABSIM_SHARE` points at, while each user's own rc still names a
per-user `SABSIM_SCRATCH` — precisely the per-user-write / group-read
split the three roots were drawn along, and the case where `SABSIM_LOCAL`
finally earns its keep: a personal potential shadowing the group's copy,
recorded by the manifest (below) so the override is auditable rather than
silent.

**How the package installs — pip today, a compiled backend when Fortran
arrives.** SABSIM is a Python package (`src/sabsim`, with inter-module
imports and a console entry point), so it installs with `pip install -e .
--no-deps` into the environment the rc activates: *editable*, so the
working tree stays live with no reinstall as it is developed, and
`--no-deps`, so pip never re-resolves the numpy / ASE / pymatgen / mpi4py
/ LAMMPS-binding stack the conda+venv layer pins by hand to match the
LAMMPS ABI. That install is precisely what lets a generated script
(`DESIGN.md` §10.5) stay lean: `python -m sabsim` and the `sabsim`
command both resolve from the activated environment, so no script has to
restate a `PYTHONPATH`. This is deliberately NOT the CMake-driven install
the group's Fortran codes use (imago) — pip understands packages, entry
points, and the editable link, whereas a CMake copy-to-bin would
hand-roll, worse, what pip gives for free. The two reconcile the day
SABSIM grows Fortran, and the choice then follows how that Fortran is
USED. Fortran *called from* Python (an imported subroutine) switches the
build backend to one that drives CMake or Meson under `pip install`
itself — `scikit-build-core`, or `meson-python` as numpy/scipy now use —
keeping the editable install and the `sabsim` command intact. Standalone
Fortran *executables* invoked as subprocesses (imago's shape, and how
SABSIM already drives LAMMPS) instead get their own small CMake build
that installs the binaries into `SABSIM_SHARE/bin` beside the other
engines, with the Python side untouched. Either way the CMake experience
carries over; neither path abandons pip for the package itself.

**The environment that package installs into is a reproducible two-layer
recipe (`install/`), built on ONE MPI: conda OpenMPI 5.0.10.** The stack
is a conda/mamba base (`install/environment.yml`: Python 3.11 + the binary
ML/inference stack — deepmd-kit, pytorch, tensorflow, CUDA — the
scientific core, and `mpi4py`) with a venv layered on top
(`install/build_venv.sh`: the editable `sabsim` and ALF, and the pinned
`ase`/`pymatgen`/`parsl`). Its shape was learned by diagnosing real
compute-node failures (probe 15520412; launcher jobs 15551533/15551674,
2026-07-31). **The MPI is conda OpenMPI 5.0.10, and it is forced, not
chosen**: deepmd-kit pulls it into the env, and the conda Python's
`DT_RPATH=$ORIGIN/../lib` — searched *before* `LD_LIBRARY_PATH` — makes
its `libmpi` the one every in-process `import` loads. It is also the right
answer: conda's 5.0.10 ships UCX and drives this cluster's InfiniBand
fabric at ~12 GB/s (UCX selects `rc_mlx5`), so no site-compiled OpenMPI is
needed. `mpi4py` therefore comes from conda too, matching that `libmpi`.
**LAMMPS is not a conda/pip package**: such a package leaves a competing
`liblammps.so` that the RPATH loads ahead of anything else, and its glibc
floor kills it on the 2.28 nodes. Instead LAMMPS is a *source* build made
on the cluster (el8-native, glibc-safe) and linked against this env's
conda OpenMPI 5.0.10. It installs to a *versioned prefix* with a
`PKG_PYTHON=OFF` ctypes wrapper, selected per job by `PYTHONPATH` — a
`family("lammps")` module over the conda build (§4.4), NOT dropped into the
venv, which holds only one `lammps`. It shares the one MPI because its
RPATH resolves this env's conda `libmpi`. The site `cpg_lammps` modules
link site OpenMPI 4.1.5, so they cannot share `mpi4py`'s conda-5.0.10
communicator (they run only in the LAMMPS-owns-MPI model, §4.4); they stay
a documented fallback, not the primary. **The launcher**
is `srun --mpi=pmix` (or `mpirun`) after `unset SLURM_MEM_PER_NODE
SLURM_MEM_PER_CPU SLURM_MEM_PER_GPU` — the allocation exports those
mutually-exclusive, which otherwise aborts the nested daemon launch, so
every generated run script bakes in the unset. The recipe was built under
a transitional name (`sabsim_dev`) alongside the older working env and
adopted — the old env removed and this one renamed to `sabsim` — only
after it passed the engine, activate, and bond checks (2026-08-05), never
by mutating the live env in place.

**Resolution: `SABSIM_LOCAL` first, then `SABSIM_SHARE`.** For any
shared input — a potential, a reference dataset, the deployment config
itself — look in the override, fall back to the group copy. This is the
ordinary override path (`$HOME/.local` before `/usr`), and the config
obeys it too, so the scheme is self-consistent top to bottom.
`SABSIM_SCRATCH` is outside it: per-user output has nothing to override.

The SABSIM-specific catch is provenance. `VISION.md` goal 3 wants every
number traceable to its exact inputs, so **the manifest records the
resolved absolute path and the fingerprint of whatever actually won** —
never the logical name. An override that is not recorded is a silent
reproducibility hole: two people get different numbers from "the same"
study because one had a personal potential shadowing the group's, and
nothing in either record says so. Recorded, the override is auditable;
unrecorded, it is a trap. That recording is the only machinery v1 builds
here — `SABSIM_LOCAL` is **declared but inert**, an empty override that
every lookup falls straight through, until someone needs one. The seam
costs nothing now and cannot be retrofitted cheaply later.

**Scratch is a mirror tree, linked from the project.** Run output is
bulky, and a scratch path is long, machine-specific, and easy to lose
track of. So scratch holds a *mirror* of the project's own directory
layout, and each job directory carries a symlink named `intermediate`
pointing into it — the pattern this group's other codes (imago, olcao)
already use, so the muscle memory carries across. The job directory
stays small and legible while the bytes live where the sysadmins want
them, and a reader who lands in a job directory follows one obvious link
instead of reconstructing a path. The link matters more than it looks:
a scratch directory nothing points at is an orphan that survives only as
long as someone remembers it exists.

The mirror is keyed **by path down to the job, then by identity inside
it**. Path, because `jobs/` may nest several levels before the job
itself (`jobs/2026-07/si-ladder/`) and that nesting is the researcher's
own organisation — flattening it to a bare job name would collide across
groups and discard the grouping. Identity inside, because within a job
the pipeline iterates over studies and members, and a path cannot
express "member 3 of study X" without reinventing a naming convention
the spec already has. The realization is `sabsim/deploy/scratch.py`;
`jobs/` is untracked, since nothing in it is needed to reproduce a run
once the manifest holds the resolved path.

A link is a convenience, never evidence. The roots are therefore used as
*configured* rather than resolved through their mounts — on the current
cluster `$HOME/data` is a link to `/mnt/pixstor/data/<user>`, and baking
that into every symlink would leak a sysadmin's implementation detail
into the project tree and strand the links the day the mount moves. The
manifest resolves at record time, which is exactly when a frozen,
unambiguous string is what is wanted.

**Driving the Tier-C engines — a native binding behind an ASE membrane.**
The LAMMPS Tier-C runs (the step-4 cascade and the step-6/7 press/pull)
are driven through LAMMPS's **Python binding**, not by emitting a static
input script. The press/pull is a stateful, multi-phase protocol whose
transitions are decided mid-run — the `DESIGN.md` §5.2 dual contact
criterion reads a running-average normal stress to know when contact is
real — and it is fix- and group-heavy (frozen base, Langevin border, NVE
interior, moving grips, load control). A persistent in-process driver
expresses all of that and reads forces and stresses back without a disk
round-trip: this
is the "persistent LAMMPS driver" `DESIGN.md` §3 chose over prior art's
fresh-process-per-phase. **ASE is the structure membrane** (`VISION.md`
principle 4): the builder hands the driver an ASE `Atoms` object and
takes frames back as `Atoms`, so the common currency crossing every seam
is ASE while the fix-heavy MD rides LAMMPS's native channel. **LAMMPS
dumps stay the durable trajectory artifact** the analyzer consumes and
`run_to_contract` guards, so the file-contract model above and a
hand-rerunnable reproducer both survive; the live read-back is only for
control decisions. **The binding sits behind a narrow driver
interface** — a handful of operations (issue commands, run, and read
back energy, positions, forces, stress, and grip reactions), with two
implementations: the real LAMMPS adapter and a lightweight mock. This is
§5.1's "the contract is the unit of stability" applied to the LAMMPS
boundary — it lets the mid-run press/pull control logic be tested on a
login node with no engine, and it is the SAME seam the classical
stand-in and the trained MLIP swap behind.
**Parallelism comes from running the binding under
MPI** — `mpirun -np N python driver.py`, each rank building a `lammps`
instance over `MPI_COMM_WORLD`, so LAMMPS domain-decomposes and scales
exactly as `lmp_mpi` does; the binding is not single-core. The FIRST
discipline this imposes: control decisions key on GLOBAL, collective
quantities (a thermo `pzz`, a summed grip force) so every rank decides
identically and stays in lockstep, or are computed on rank 0 and
broadcast — never on rank-local data, which would desync the ranks.

**The SECOND discipline: SABSIM owns the communicator, and no library
may post a collective on it unasked.** Scientific Python libraries
commonly notice that MPI is active and quietly make their own file
access collective — rank 0 alone reads the file and broadcasts the
result to every other rank, which must all take part or none may
proceed. ASE does exactly this to `read` and `write`. That convenience
is incompatible with a pipeline that already decides for itself which
rank writes a file: a read issued inside a `rank == 0` guard becomes a
broadcast waiting on peers that never call it, and two DIFFERENT
collectives posted on one communicator is undefined behavior rather than
an error anyone reports — it surfaces as a deadlock, or as peers handed
an empty result they cannot distinguish from an empty file. So every
third-party file operation is placed in EXPLICITLY SERIAL mode (for ASE,
`parallel=False`), which leaves one rule in force: only SABSIM's own
code posts collectives on `MPI_COMM_WORLD`. Reads then run per-rank and
writes stay guarded to one rank — exactly the arrangement §4.3's file
handoff already assumes. This is the same "the contract is the unit of
stability" instinct as the driver seam: a library may cross our
boundary with data, never with control over our ranks.

The standalone `lmp_mpi` executable is kept as a hand-rerunnable reproducer
(the driver can dump the exact script) and a fallback, NOT as the source
of parallelism. The whole `mpirun` invocation is the submitted `bond-md`
job, so a native crash is a failed job the sequencer halts on cleanly
(wall 4) — that job boundary is the isolation.

**Deployment / resource layer — the "where to run" knob.** Per
`VISION.md` principle 1, every site-specific and resource choice lives in
an editable deployment config, never in code: resource *class* (CPU vs
GPU partition), node / core / GPU counts, walltime, memory, and
module / environment setup. This is the concrete form of the
Settings / deployment-separation module (§2.3), and is emphatically
**not** the prior-art anti-pattern of baking partition names and site
details into emitted scripts (`PRIOR_ART.md` §1.2 item 7). Routing is
**per job, not per step**, because the pipeline is CPU/GPU-heterogeneous
and step 4 in particular can straddle both — its cascade runs on a
universal MLIP on a GPU (the classical CPU option was deprecated
2026-08-26), with the gentle heal riding the bond job:

| Work                                   | Resource class |
|----------------------------------------|----------------|
| VASP labeling (step 1 / inside ALF)    | CPU (MPI)      |
| DeePMD training (inside ALF)           | GPU            |
| Ar cascade — universal MLIP + ZBL      | GPU            |
| MLIP heal + §3.5 gate (§3.4)            | rides BOND (pre-press) |
| Press / settle / pull (bond)           | GPU (`deepmd`) |
| Imago (step 8)                         | CPU            |

**Settled (this table ↔ `DESIGN.md` §10.2): the activate job's class
follows the cascade potential.** Step 4's cascade dominates the activate
job, and the cascade runs on the universal MLIP, so activate is GPU work.
(Resolved 2026-08-06, superseding the earlier CPU-only-activate
assumption; the classical CPU opt-in that briefly existed was deprecated
2026-08-26.)

**The heal + gate ride the BOND job, not activate (revised 2026-08-08).**
The earlier design ran a per-slab MLIP re-anneal as a tail of the activate
job and placed the §3.5 gate as a human-inspected checkpoint BETWEEN
activate and bond. `DESIGN.md` §3.4 revised that: the heal is done once, on
the ASSEMBLED pair at a wide gap, under the production committee — whose
engine lives in the bond job — so the heal is the bond job's FIRST phase and
the §3.5 gate runs there, on each healed surface, before the vacuum is
scissored and the press begins. So the activate job is now cascade-ONLY
(build → cascade → assemble at the wide gap → write the pair), and the
checkpoint moves into the bond job's pre-press phase: a failed gate aborts
the bond before its expensive press/settle/pull, so it still guards the
scarce GPU it was meant to, just one job later. The human inspection point
moves with it — the gate verdict is a bond-job artifact now, not an activate
one.

**Structure of the deployment config — two concerns, one file.** The
config separates *what the machine has* from *how each kind of work uses
it*, because the two change on different clocks:

- **Hardware section** — the machine's inventory: partitions, cores and
  GPUs per node, memory, walltime ceilings, the module / environment
  stack, the scheduler. Stable; it changes only when the machine does, so
  it is the **per-cluster swap unit** — retargeting to a new HPC rewrites
  this section and nothing above it.
- **Usage section** — keyed by **kind of member job**, not by script or
  by tool: the three per-kind jobs `activate` / `bond` / `analyze` that a
  member is prepared as (`DESIGN.md` §10.2). Each block names a resource
  *class* (CPU or GPU), a size (node / GPU counts, walltime), and the
  module(s) that job switches on. This is mostly machine-independent — an
  activate job wants "CPU, ~1 node" on any cluster — so it travels with
  the pipeline, not with the site. This REPLACES an earlier tool-kind
  keying (`cascade-md` / `bond-md` / direct `vasp` / `sequence`); the
  member-job axis is the one DESIGN §10 fixed and PSEUDOCODE §14 loads.

The seam between the two is the word **class**: a usage block names an
abstract class plus a size, and the hardware section binds that class to
*this* machine's concrete partition, so retargeting is a one-section
swap. Keying usage by *kind of member job* rather than by script follows
from "routing is per job, not per step" and `VISION.md` principle 7: the
three member jobs want different machines (activate and analyze CPU, bond
GPU — `DESIGN.md` §10.2), and each switches on only the tool it needs, so
one key per member job keeps those resource shapes from lumping together.

**The Tier-B boundary — not all resource config is ours.** The usage
section covers the three **Tier-C** member jobs (`activate` / `bond` /
`analyze`) — the LAMMPS cascade and assembly, the press / pull, and the
measure. It carries no `sequence` footprint: `sabsim` writes scripts and
the human submits them (`DESIGN.md` §10.1), so the **Tier-A** sequencer
never claims an allocation of its own — its control flow runs INSIDE each
member job. **Tier B is excluded by design:** ALF (DeePMD training and
the VASP-inside-ALF labeling) and Kaleidoscope (Imago characterization)
each own their own Parsl + SLURM submission (the "no Parsl in Parsl" rule
and wall 5), so the deployment config *points at* their configs rather
than duplicating them — DeePMD GPU counts live in ALF's Parsl config, not
here. The bootstrap's direct VASP labelling jobs (steps 1-2) are likewise NOT
among the three member jobs (`PSEUDOCODE.md` §14.5): manufacturing the
potential is a separate upstream process. They ARE routed by this same
rc, through their own `[usage.label]` block (partition, module, binary
— `vasp_gam` on the CPU build by default, the CUDA build as a switch),
which `sabsim bootstrap label` reads to write its job array
(2026-08-26); the member map still routes only its three consumers.

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
6. **Large trajectory I/O** — scratch vs home. ADDRESSED above by the
   three roots and the scratch mirror tree; what remains for DESIGN is
   the trajectory's own size budget (`frame_stride`, the §2 frame
   budget), not where it lands.

**Current target machine (one instance; the model stays generic).**
Today's cluster is a **SLURM** system with a shared **PixStor** parallel
filesystem and a lab-owned partition (`rulisp-lab`) spanning CPU and GPU
nodes — the partition the Kaleidoscope step-8 batch was validated on.
Nothing above depends on those specifics: any SLURM-plus-shared-filesystem
HPC with CPU and GPU partitions instantiates the same three-tier model by
swapping the deployment config.

### 4.2 Run artifacts, reporting, and provenance

Where a run's outputs land, how they are organized, and how a result is
made legible — VISION goal 3 (traceability across the six codes) made
concrete. The intent below is firm; the exact names and sub-layout are
expected to ADAPT to practical realities met during implementation.

**Runs land in the SUBMISSION directory.** A user works in a per-member
job directory — `jobs/<study>/<member>/` — and submits from there, so the
result appears where they already are, not in a separate root. One
directory holds one member (one material pair + protocol + seed); a study
of several members is a set of sibling directories under `jobs/<study>/`,
with a study-level roll-up (below) at that parent.

**Per-run subdirectories, with a `latest` pointer.** Re-running a member
(a new seed, a tweaked energy) must never silently clobber the previous
result, so each run writes a timestamped/id'd subdirectory (`run-<id>/`)
and updates a `latest` symlink to it — "open the latest report" stays one
step while the history is preserved.

**Small keepable things in the job dir; large raw data on scratch.** The
report, the canonical structured result, the manifest index, and the
provenance record are small and are written INTO the run subdirectory. The
large raw data — the strided trajectories, the LAMMPS logs, the data files
— stay on `SABSIM_SCRATCH`, reached from the job directory through the
existing `intermediate` symlink (§4.1) but under clear, human-readable
names (`<member>_cascade.dump`, `<member>_pull.dump`), so opening one is
`ovito intermediate/<member>_cascade.dump`. A single endpoint frame may
also sit directly in the job directory as a cheap convenience, though the
trajectory is the artifact that conveys the dynamics.

**The manifest is the index, and provenance is first-class.** One manifest
per run points at every piece — report, structured result, the scratch
trajectories (by resolved path + fingerprint), logs — so all of a run is
discoverable from one file. It records what makes the run reproducible
(VISION goal 3): the git commit of the code, the resolved member spec, the
master seed and its derivations, the potential and reference data used
(with their `real`/stand-in flags), the software versions, and the host. A
study roll-up aggregates the member manifests and their structured results,
and is where the §7 cross-member comparison (the Si/Si vs Si/SiO2 ratio)
surfaces.

The algorithmic shape — the canonical result schema, the swappable report
renderer, and the standard visualization-dump columns — is `DESIGN.md` §9.

### 4.3 Member execution sequence — file-handoff stages, serial slabs

A member is not one run; it is a CHAIN of stages, several of which open a
LAMMPS engine and hand their result to the next through a FILE. §4.1 fixed
the linking rule — steps decouple through file contracts on the shared
filesystem. This section applies that rule at the altitude of a single
bonding member: what the stages are, which of them touch a compute node,
and why the file handoff holds even though a member runs its stages
SERIALLY. The file handoff is NOT a concession to a parallel future: it is
how the simulator takes its input, how each result becomes a durable
record, and how a crash mid-chain keeps the finished stages. Parallelism
is a bonus the files happen to also enable (below), never their reason.

**Every LAMMPS stage is a self-contained data-file → data-file unit.** A
stage opens an engine, loads the data file its predecessor wrote, does its
work, writes a data file (and its trajectory dump, §4.2), and closes. The
sequencer never holds a live engine across stages; it passes PATHS. Three
reasons make the file the currency, NONE about parallelism. First, it is
how the simulator takes input at all — LAMMPS loads a slab by `read_data`
on a file, not from an in-memory object, so the structure builder writes a
file before any bombardment can read it (the ASE membrane, `VISION.md`
principle 4). Second, the file each stage writes IS the run's durable
record (§4.2, §9): the amorphized half on disk is at once the assembly's
input and the archived artifact. Third, a stage that writes its result
before the next begins survives a crash — the finished stages stay
finished, and a native crash is a failed job the sequencer halts on
cleanly (wall 4). The file ALSO lets a stage run wherever its resource
class is served (§4.1's per-job routing), which is the bonus the optional
fan-out (below) trades on. The live in-process read-back §4.1 describes is
WITHIN a stage (the press's mid-run contact test), never across the seam
between two.

**The chain for a bonding member.** With activation on, steps 3–5 are not
one build; they are a chain with one independent pair in the middle:

```
relax-bulk (per material)      small LAMMPS, once per potential
        v
solve-shared-cell              pymatgen, no LAMMPS, once
        v
build-standalone-halves        ASE, no LAMMPS, geometry once
        v
  +-----+-----+                SERIAL: one half, then the other (§4.3)
  v           v
amorphize   amorphize          cascade + re-anneal + gate (LAMMPS)
 half A      half B
  v           v
  +-----+-----+                BARRIER: assemble needs both halves
        v
   assemble                    read both data files back, flip top
        v
  press -> pull -> analyze     LAMMPS, then analysis
```

Two facts drive everything below. First, **each half is built and
amorphized ALONE, in vacuum** — the whole point of surface-activated
bonding is that each surface is prepared before the two ever meet
(`DESIGN.md` §3.1). So step 3 builds each half ALONE with the existing
per-half `build_slab` (which already cuts in vacuum) and emits two
STANDALONE half-cells, not the assembled pair; the cascade stage adds the
beam species to each half so it can create projectiles. The crystalline
all-in-one `build_facing_pair` is the activation-OFF null path (Si/Si with
no cascade), not the bonding path. Second, **the two amorphizations are
independent** — different materials, separate engines, no shared state
until `assemble` reads both halves' data files back and stacks them
(`DESIGN.md` §2.6). Assembly is the BARRIER: the first stage that needs
both halves at once.

**The units are independent, but v1 runs them SERIALLY (Approach A).** In
principle the two halves — and, above them, the N amorphization
realizations the bond metric averages over (STRUCTURAL 4), each a
different master seed — are independent and could run at once.
`relax-bulk`, `solve-shared-cell`, and the half GEOMETRY (`build-halves`)
are deterministic and SHARED across realizations, computed once; what
repeats per realization is writing a fresh half data file and amorphizing
it, then `assemble` through `pull`. But v1 does NOT fan those units out
(Approach A): the two halves are bombarded one after the other, each
using its job's FULL core allocation, rather than split into concurrent
jobs. That concurrency choice is ORTHOGONAL to how the serial chain is
handed to the scheduler, which the next paragraph settles.

**The serial chain is submitted as THREE per-kind jobs.** Approach A
keeps the independent units serial; it does NOT make the whole member a
single submission. The chain is cut where the HARDWARE KIND changes and
a human should stop to look — into **activate** (CPU: build and amorphize
both halves, then assemble), **bond** (GPU: press, settle, pull), and
**analyze** (CPU: measure) — three jobs submitted in order, each watched
to completion and checked before the next is sent (`DESIGN.md` §10.2).
The cut costs nothing precisely because every stage already hands off
through a file (above): a job boundary is just a file-handoff seam the
human elects to pause at. So a member runs as three sequential per-kind
jobs, and the two-halves-serial choice of Approach A lives INSIDE the
activate job.

**Why serial slabs, not two-at-once inside one job.** Running the two
halves concurrently in a single job would mean SPLITTING that job's cores
between them — and for a fixed core count that is no faster than running
them in turn on all the cores, while being markedly more code to steer two
core-groups through different work. The one case where fewer-cores-per-
slab genuinely wins — a slab too small to use the whole allocation
efficiently — is captured BETTER by submitting each slab as its own
smaller job and letting the scheduler run them together, never by
splitting cores in-process. So in-process cross-slab concurrency is a
DOMINATED option and is not built. The parallelism v1 relies on is the two
levels it already has: different MEMBERS run as independent job sets, and
each single bombardment is itself a multi-core (MPI) simulator run.

**The separate-job fan-out stays available, for free, through the files
(Approach C).** Should the small-slab efficiency win ever be wanted, the
file handoff already allows it: submit the independent half/realization
amorphizations as separate jobs (a SLURM array or a dependency graph),
each in its own scratch subtree, with a barrier before assembly, joined by
the manifest (§4.2) — a change of SUBMISSION WRAPPER, never of stage code.
To keep that option open (and to keep the serial loop clean and
restartable), each amorphization is written as a pure function of (which
half, which seed) with NO cross-iteration state, and the sites where the
serial loop would become separate jobs are marked `# C-EXPANSION` in the
code. They are available extension points, not planned work: the loop
over (half, seed), the per-unit scratch subtree, the assemble barrier, and
the engine lifetime.

**The build → amorphize handoff: a per-half handle.** `build-halves` writes
the two pristine standalone slabs to files and hands the amorphization a
small HANDLE per half — the file path, the species→type numbering (with
the beam declared), the material identity, and which wafer it is (bottom A
/ top B). The amorphization RE-READS the slab geometry from the file
rather than leaning on an in-memory object, so it stays a self-contained
"read a file, do the work, write a file" unit: restartable after a crash,
and identical whether it runs in the member's own job or, later, a
separate one. `build-halves` is the FIRST stage to write real files, so
the sequencer threads it the run's scratch directory EXPLICITLY (the
traceable form, not a path the stage rebuilds from identity), keeping every
written byte traceable to its inputs (`VISION.md` goal 3).

This keeps the "don't build something that must be torn apart" discipline
without paying for concurrency the plan does not need: the serial member
chain and the optional separate-job fan-out share the same stage code and
the same files — only the submission wrapper differs.

### 4.4 Engine acquisition — the LAMMPS module scheme

§4.1 fixes how the engine RUNS; this fixes how the engine BINARY is
obtained. The two are kept separate on purpose, so the choice of LAMMPS
build never leaks into the orchestration. The Engine seam (§4.1,
`LammpsEngine`) imports a `lammps` Python module and drives it; it does
NOT know or care which LAMMPS binary answers. That knowledge lives
entirely in the runtime environment, selected by a modulefile — so a
different engine build is a deployment knob, not a code change.

**Source-built and conda-linked, because the code forces one MPI.** The
engine build is not a free choice: §4.1 establishes that sabsim loads
LAMMPS *in-process* and shares one `MPI_COMM_WORLD` between `mpi4py` and
`liblammps` (`cli.py`, `lammps_engine.py`, `live_stages.py`), so both MUST
link the SAME `libmpi`. The conda Python's `DT_RPATH` already forces that
`libmpi` to be the env's conda OpenMPI 5.0.10 (§4.1). An engine linking
any other MPI cannot share the communicator. The site `cpg_lammps` builds
(adopted from Imago; SITE toolchain gcc 12.3.0 / **OpenMPI 4.1.5**) link
the wrong `libmpi`: they load and run in the LAMMPS-*owns*-MPI model
(verified, job 15580445) but CANNOT share `mpi4py`'s communicator without
also building a site-4.1.5 `mpi4py` — so "adopt the site engine" does not
actually avoid a build (VISION principle 2 is about avoiding *net*
machinery, and here adopting costs more of it, not less). The engine is
therefore a **source build made on the cluster, linked against this env's
conda OpenMPI 5.0.10** (`install/build_lammps.sh`): el8-native and
glibc-safe (no symbol above GLIBC_2.14, so it starts on the 2.28 nodes),
`PKG_PYTHON=OFF` so one pure-ctypes wrapper serves any Python and
`LammpsEngine` imports it unchanged, with an RPATH to the conda libs so it
finds that one `libmpi`. The conda 5.0.10 is not the "slow and fragile"
TCP fallback an earlier draft feared: it ships UCX and drives this
cluster's InfiniBand at ~12 GB/s (`rc_mlx5`, job 15551674). The site
`cpg_lammps` modules remain a DOCUMENTED, zero-maintenance FALLBACK for
the LAMMPS-owns-MPI model (job 15580445), not the primary.

**Selection is still the module scheme, now over the conda-built
prefixes.** The engine binary is obtained exactly as before — the run
loads a module (`module use <cpg modulefiles>` + `module load
cpg_lammps_conda/<version>`) in the job's bring-up, no source edit — but
the modules point at the conda-built prefixes and are THIN over the active
`sabsim` env: because the binary's RPATH already resolves conda
`libmpi`/`libstdc++`, a module need only put the ctypes wrapper on
`PYTHONPATH`, the potentials on `LAMMPS_POTENTIALS`, and (for deepmd) the
plugin path on `DEEPMD_LMP_PLUGIN`. They declare `family("lammps")`, so
versions are mutually exclusive: exactly one engine is ever on the path.
Publishing a rebuild is repointing a prefix; a NEW version is a second
modulefile beside the first. Feature parity is deliberate and verified
(job 15683172): the conda build carries the 25 packages every style the
pipeline emits needs; only `ML-HDNNP` and `VORONOI` are dropped, neither
used by any code path, both restorable from the recipe if a later study
needs them.

**The DeePMD engine is a second version, not a fork.** The machine-
learned-potential runs (§2.2's force model, once the trained MLIP exists)
need `pair_style deepmd`, supplied by deepmd-kit's prebuilt LAMMPS
plugin. That plugin is ABI-locked to the LAMMPS release it was built
against (LAMMPS 2024.08.29): a single LAMMPS utility signature changed
after that release, so the plugin loads into a 2024.08.29 engine and
refuses a newer one. The response is not to rebuild deepmd, but to
publish a second engine at the matching version — `cpg_lammps_conda/
2024.08.29-deepmd`, the SAME conda-linked recipe as the default engine
with only the LAMMPS version changed. sabsim selects it exactly as it
selects any engine (the module line, plus the `deployment_rc.toml` usage
block for the bond job kind); the Engine seam is untouched. Reaching the
plugin at run time is cheaper than on the site toolchain: NO `libstdc++`
preload is needed (the conda env already ships a new-enough `libstdc++`
for the backend's CXXABI), and the plugin is loaded EXPLICITLY by a LAMMPS
input line (`plugin load $DEEPMD_LMP_PLUGIN`) so its own dependencies
resolve — never auto-loaded via an inherited `LAMMPS_PLUGIN_PATH`, which
the job scripts `unset`. This engine is deepmd-kit **3.1.3** (dual TF +
PyTorch backend), and it loads a model frozen by the group's separate
deepmd **2.2.10 / TensorFlow** training stack DIRECTLY — a real 2.2.10
`.pb` ran a force step through it with no conversion (job 15686597) — so
the training→inference path needs no bridge. A second, deliberately older
engine thus coexists with the default and is chosen per job, with no
change to the pipeline that drives it.

**The universal cascade engine is OUT-OF-PROCESS, by necessity.** The two
engines above are conda-linked so they load in-process and share the
sabsim env's one `libmpi`. The universal foundation MLIP that drives the
DEFAULT cascade (`DESIGN.md` §4.7) cannot be built that way: it runs only
inside deepmd-kit's OWN self-contained offline-installer bundle — its own
torch, its own LAMMPS, its own MPI — because a self-built stack crashes
these DPA models (the bundle is the one that runs them). That bundle cannot
be imported into the sabsim process or share its communicator, so the
universal cascade breaks the in-process assumption above and is run
DIFFERENTLY: the activate stage's CASCADE is assembled into one
self-contained script (`driver/cascade.build_activate_script`) and run as
the bundle's `lmp -in <script>` in a subprocess, its AMORPHIZED structure
handed back through a file (the §4.3 file-handoff model,
`driver/cascade_subprocess`). This is sound because the cascade needs NO
mid-run read-back: every impact is seed-derived and each cascade ends on an
in-LAMMPS halt, so the sabsim process builds the slab before and reads the
amorphized structure back for assembly after, from a dump rather than a live
engine. The heal and the §3.5 gate do NOT ride this subprocess — §3.4 moved
them to the bond job, so the activate stage is cascade-only. The bundle is
selected by the in-repo `SABSIM_CASCADE_ENGINE_PREFIX` env (a per-machine,
GPU-architecture-specific prefix, so a path rather than a checked-in
module), and the subprocess is launched in a fully-reset environment so no
sabsim-side torch or plugin path leaks in and crashes it. The classical
cascade is unaffected — a built-in LAMMPS pair style keeps running
in-process on CPU through `LammpsEngine` — so only the universal (GPU) path
leaves the process. Because the activate stage no longer re-anneals, the
subprocess needs no classical potential and the activate job carries no
`LAMMPS_POTENTIALS`; the heal that would have needed it now runs under the
committee in the bond job (§3.4).

**The §2.2 lattice derivation rides the SAME subprocess (universal path).**
Once the §2.2 bulk relax derives the working lattice under the universal
MLIP rather than a classical seed (`DESIGN.md` §2.2/§4.7 — so the cell and
the cascade agree), it inherits the same out-of-process necessity: the
bundle's model will not load in-process. So the DEFAULT derivation is
assembled as a
standalone `fix box/relax` + `minimize` script
(`driver/bulk_relax.bulk_relax_subprocess_script`) and run through the same
`driver/cascade_subprocess.run_activate_subprocess` the cascade uses. The
one difference from the cascade handoff is the read-back: a box relax
CHANGES the cell, so the script ends with `write_data` and the caller reads
the relaxed cell (and atom count) back with `bulk_relax.read_data_box` —
whereas the cascade leaves the box fixed and reads only atoms from a dump.
The primary rank drives the one GPU
subprocess while peers wait at a barrier, then every rank reads the same
handoff file — deterministic, so the derived cell agrees across ranks.

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
  file-contracts-on-shared-filesystem linking model (§4.1), and the
  member specification itself (`DESIGN.md` §1). A seam schema, once
  written,
  changes only by deliberate amendment with a recorded note — the same
  discipline the design chain itself uses.
- **A walking skeleton before any depth.** Build the thinnest end-to-end
  thread first: a member spec for the **Si/Si** reference → structure
  builder
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

| Steps | Buildable unit        | Tool                    | DESIGN §   |
|-------|-----------------------|-------------------------|------------|
| 3, 5  | Structure builder     | ASE                     | §2         |
| 4     | Activation            | LAMMPS + ZBL            | §3         |
| 1, 2  | Bootstrap (training)  | VASP · ALF/DeePMD       | §4         |
| 6, 7  | Bond/debond MD        | LAMMPS + MLIP           | §5         |
| 8     | Characterization      | Imago/Kaleidoscope      | §8         |
| —     | Frame                 | member-spec·schema·gate | §1, §6, §7 |

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
  the stand-in **behind the same `pair_style` seam**, and the
  potential-quality gate's bulk/surface half switches on. Started
  2026-08-26 with the recipe, the Collection-1 generators, the frame
  harvester and the VASP labeller on silicon (`src/sabsim/bootstrap/`);
  the ALF training bridge and the refine loop follow.
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

One design freedom to protect from Wave 0 — and one phantom freedom to
stop protecting (retracted 2026-07-23). Steps 3/4/5 are **not**
reorderable, and no setting should pretend they are: surface-activated
bonding *means* each surface is prepared alone, in vacuum, before the two
halves ever meet, so build → amorphize → assemble is fixed by the physics
(§4.3, `DESIGN.md` §3.1). An earlier §2.1 called the ordering a setting;
that claim is withdrawn, and no reorder engine is owed at any level.
The freedom that genuinely exists is **activation on or off**, and it is
the one the skeleton must keep live: with activation off the builder
takes the crystalline all-in-one path (`build_facing_pair`, the Si/Si
null test), and with it on the chain runs per half and assembles from two
data files. Both paths must stay reachable behind the same structure
contract; hard-wiring either would forfeit the choice that is real.

### 5.4 Consequence for PSEUDOCODE

The immediate next level obeys the same spine: **breadth-first shallow,
then depth-first per module.** The first pseudocode pass covers control
flow and the seam schemas — the Tier-A sequencer, member-spec
load/validate,
the structure contract, the measure schema, the gate's precedence chain —
which is the walking skeleton expressed as pseudocode. The deep per-module
algorithms (the coincidence matcher, the UDD bias, the detector
prominence math) are filled in as each module is implemented, behind a
contract that is already frozen and skeleton-tested. Writing them all to
full depth up front would front-load the stable-behind-a-contract work
before a single seam had been validated — a form of coding into a box in
its own right.

**"Depth" is recursive and uneven, not a fixed ladder of numbered
levels.** After the shallow first pass there is no global "level 2, level
3" applied uniformly. Going deep on a module means applying this same
method one level down inside it — first lay out its internal control flow
and sub-contracts shallowly, then recurse only into the parts that need
it — and the recursion **bottoms out at the PSEUDOCODE↔Code boundary**:
stop refining when the next step would add only language syntax, not an
algorithmic decision. Because that boundary sits at a different depth for
different pieces, one module's depth is uneven by nature — inside the
structure builder the strain split is essentially one weighted formula
(one level from code) while the coincidence-matcher search needs a
sub-pass of its own. So "pass 2 on a module" is loose shorthand; the
honest structure is **per-module recursion to code-readiness**, and how
many sub-passes a module takes is set by its own complexity, not by a
counter. A `/refine` should read "depth-first" this way — not as a
uniform ladder.

### 5.5 Checkpoints and baselines

The prior Imago/Kaleidoscope effort used numbered checkpoints (for
example C68, C69) tagged in git with matching TODO entries and doc
revisions; a similar scheme is the natural fit, with each **wave**
(§5.3) and the **Si/SiO2 transition** as baseline tags. This first-pass
design mapping is the natural first baseline to tag.
