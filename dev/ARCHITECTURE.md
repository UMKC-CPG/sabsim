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
(BUILD) — that batch is our edge.

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
  experiment can be run several ways and compared.
- **Programmatic / turn-key entry [BUILD].** Per `VISION.md` goal 2,
  the controller is exposed as a library-style programmatic interface,
  not just a hand-run script, so another researcher can point the
  pipeline at a different material pair and drive it from their own
  code. Hand-editable settings are a convenience side door, not the
  main entrance.
- **Structure builder — ASE [ADOPT · glue · recipes BUILD].** Builds
  slab and facing-pair models (steps 3, 5): ASE is the adopted
  toolkit, and the SAB-specific slab and facing-pair construction
  **recipes layered on it are ours to build** (`VISION.md` goal 5).
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
  ours.
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
- **Bond characterization — Imago + Kaleidoscope
  [engine ADOPT · protocol BUILD · our edge].**
  Kaleidoscope fans the chosen step-8 snapshots out as a batch of
  Imago analyses across the cluster and harvests the bonding numbers.
  This is exactly the batch we validated in the prior session — a
  live four-structure SLURM campaign (silicon, diamond, graphite,
  silica) on the rulisp-lab partition that proved cross-node
  dispatch, worker parallelism, and cache-on-rerun end to end.
- **Quality gate [BUILD].** The outer-loop acceptance test: does the
  trained model reproduce the real-world SAB quantities we care about
  (stiffness, surface energies, a reference bond strength)? This is
  the scientific heart of the deliverable.

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
- **Outer orchestrator — OPEN.** Three candidates, light to heavy:
  - *Snakemake (light):* files-produce-files; simple, teachable,
    portable. Weak at loops and keeps no queryable history.
  - *jobflow (middle):* Python-based; handles loops and a moderate
    history. A sensible step-up.
  - *AiiDA (heavy):* best-in-class provenance, but heavy, steep, and
    hard to leave. Justified eventually because the deliverable is
    *traceable advice*.
  - *Recommendation:* start lean (Snakemake, or a little of the Parsl
    code we already understand), provenance by discipline, graduate
    under real pressure (`VISION.md` principle 6).

**Cross-project dependencies (Imago side).** SABSIM relies on a few
Imago deliverables maturing in parallel: a fast, lightweight step-8
analysis mode; the ASE adapter (so snapshots can cross into Imago);
and a good initial-guess potential database that makes large, cheap
analyses possible.

---

## 5. Development Checkpoints

<!-- Git tag / branching strategy for design baselines. -->

To be established for this repository. The prior Imago/Kaleidoscope
effort used numbered checkpoints (for example C68, C69) tagged in git
with matching TODO entries and doc revisions; a similar scheme is the
likely starting point once the vision and architecture stabilize.
This first-pass mapping is the natural first baseline to tag.
