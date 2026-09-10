# Design

> **Document hierarchy:** VISION → ARCHITECTURE → **DESIGN** → PSEUDOCODE
> → Code. For goals and principles, see `VISION.md`. For repository layout
> and module map, see `ARCHITECTURE.md`.

> **Prior art — read before writing the relevant sections.** Several
> algorithms this document needs already exist, and some now run, in
> Sunita's `bond_debond` pipeline: the reusable kernels are catalogued in
> `PRIOR_ART.md` §1.2, and the newer worked examples plus current status
> are in §1.5. Lift or adapt rather than re-derive:
> - **Surface amorphization (§3):** an Ar-bombardment + ZBL
>   LAMMPS recipe and the thermostat-damping / inter-impact-timing
>   settings that make it disorder the surface — plus the §1.5 lesson
>   that dropping the frozen substrate and `p p f` sputter boundary
>   breaks it.
> - **Amorphization verification (§3, §7):** g(r), partial-g(r),
>   coordination-defect counting, and amorphous-depth estimation — the
>   validation the potential-quality gate needs (add the thresholds and
>   DFT anchor prior art lacks).
> - **Structure building (§2):** a mirror symmetrizer for polar surfaces
>   (LiNbO₃, GaN) in §1.2, and a worked coincidence supercell
>   (16×SiO₂ ≈ 15×LiNbO₃, strained before amorphization) in §1.5.
> - **Bond/debond and measures (§5, §6):** a built-and-run press/pull
>   protocol and an independent J/m² adhesion definition (mechanical and
>   thermodynamic) in §1.5 — but its interface number is uncalibrated
>   (placeholder pair potential), the gap SABSIM's trained MLIP fills.
> - **Step-8 analysis (§8):** a worked OLCAO full-basis / Γ-point / cost
>   plan (§1.2 item 5); OLCAO itself is still unbuilt in prior art.

---

<!-- Each section designs one subsystem: its data structures,
algorithms, mathematical foundations, and key decisions. Reference
VISION.md principles when a choice is motivated by one. Sections are
numbered in reading order but FILLED in a different order — §4 (MLIP
backend + bootstrap) first, as the most mature (already prototyped and
unit-tested). Each heading below carries a one-line scope note and its
sources; bodies are written section by section. -->

## 1. Pair specification and settings layer

This section designs the specification a person writes to point the
pipeline at one wafer pair, and the rules that keep it honest. It was
written last on purpose. §2 through §7 each deposited knobs, tolerances
and seeds as they went, and only with all of them on the table does the
shape of the settings layer become visible — it is not one list but
five, and the divisions between them carry meaning.

Prior art states the problem by contradiction. Its `primeinput.py` reads
a run's parameters out of the directory path it happens to be sitting
in (`jobs/<stage>/<material>/<layer>/<energy>/`) and bakes a partition
name, a personal email address, and module versions into the scripts it
emits (`PRIOR_ART.md` §1.2 item 7). SABSIM inverts this completely:
**the configuration is an object, and the directory is an output.**

### 1.1 The object is a pair, and the comparison is the person's

The top-level object is a **pair**: two wafers facing each other, one
protocol, one number out. One pair lives in one **project folder** —
`jobs/si_sio2/`, say — whose name is the person's own label and means
nothing to the program (`ARCHITECTURE.md` §1). The project's
`sabsim.toml` describes exactly that pair; beneath the pair a
**realization** is one seed.

An earlier version of this section (2026-07 to 2026-08-30) put a
**study** above the pair: a named list of "members" (material pairs)
with declared **relations** among them, so that §7.4's headline ratio —
the work of separation of Si/SiO₂ divided by that of the Si/Si
reference — would have a place to live inside the program. That layer
is retired (revised 2026-08-30 (Paul)). SABSIM no longer models a
study, a member list, or a relation programmatically. The person who
wants the ratio runs the reference pair as a **second project folder**
(`jobs/si_si/`), reads the two measure vectors, and forms the ratio
themselves. The reasons are the same ones that once argued for the
study, now pointing the other way.

**The physics of a ratio still needs shared systematics.** §7.4 trusts
a ratio because the systematic errors common to both pairs cancel to
first order — the pull rate, the cell size, the thermostat, the
mismatch of timescales. That cancellation requires the two projects to
actually share a potential and a protocol, and nothing in the program
now checks it. What the program does instead is make the check EASY:
every measure vector carries the pair's fully resolved specification
(§1.6), so laying two `sabsim.toml` files side by side, or diffing the
two provenance blocks, shows every field that differs. The reader
should sort those differences the way the retired relation machinery
would have:

- **Contrasted** — it differs by design; this is the signal.
- **Entailed** — it differs *because* of the contrast and cannot be
  removed without removing it. Si/Si has no lattice mismatch and
  Si/SiO₂ does; you cannot contrast two material pairs without
  contrasting their mismatch, so the residual-strain systematic is the
  irreducible price of the comparison, not a mistake in it.
- **Incidental** — it differs for no declared reason. These are the
  dangerous ones: an incidental difference is an uncontrolled variable
  nobody decided to vary, and it is the least examined thing in the
  comparison, not the most.

SABSIM cannot know in general which differences break a cancellation;
that judgment rests on physics the settings layer does not encode. What
it can do — and this is all it now claims to do — is refuse to hide
them, by making every specification reconstructible from every output.

**Report, never restrict.** The retired machinery could withhold a
**verdict** on a comparison whose controls disagreed; it could never
refuse to compute it, and that spirit survives the retirement in
stronger form. The scientist who runs many material pairs many
different ways is the person this project is built to serve, and they
routinely learn from comparisons no automated criterion is qualified
to bless. SABSIM hands over each pair's numbers, uncertainties and
provenance; it does not grade comparisons between pairs. A machine that
declined to compute what a scientist asked for, on the grounds that it
would not know how to grade the answer, would have mistaken its role —
and a machine that grades comparisons it cannot understand mistakes it
the other way.

**Why the study layer was more cost than help.** A study composed over
members needed member names, a relation grammar with contrasts and
controls, a validator that could tell an entailed difference from an
incidental one, a `--only` selector to run one member of several, and
a scratch tree keyed by study and member. Every one of those existed
only to automate a comparison the scientist makes better by hand. The
pair, by contrast, must be **self-contained and independently
reproducible** whatever else exists — which it now is by construction,
because nothing else exists in the program to mention it. Sweeps over
dose, load or material remain what §1.8 always said they were: a SET of
project folders, not a feature of the machinery.

**On the word "member."** With the study gone, "member" means exactly
one thing in this document: a **committee member** of §4.4 — one of the
`n_models` machine-learned potentials whose mutual disagreement is the
uncertainty signal. The material pair is a **pair**.

### 1.2 Five groups, divided by what refinement does to them

`ARCHITECTURE.md` §2.3 named two groups, material and protocol, with
deployment held apart. Writing §2 through §7 produced two more, and the
line between them is worth drawing sharply because a great deal depends
on it.

- **Material** — per wafer: the crystal, supplied as a **structure file
  (CIF)** that fixes its symmetry, its atomic basis, and its
  connectivity; one surface face given by its Miller indices; and the
  material identity. The CIF names WHICH crystal, not its scale — the
  lattice constant is still derived by relaxation (§1.3, §2.2), never
  read off the file — so one uniform input serves every material with no
  per-material code. What we are studying. The material identity is a
  LABEL the person chooses (`material = "SiO2"`), and it does one
  concrete job beyond reporting: lower-cased, it names this surface's
  PREPARATION folder in the project — `prep_surf1_<label>/` for wafer
  A, `prep_surf2_<label>/` for wafer B — where everything done to that
  surface before bonding lives: the recipe of single-material
  calculations, the environment library the §3.5 gate judges against,
  and the surface's own amorphization (`ARCHITECTURE.md` §1; revised
  2026-08-30 (Paul)). A homo pair has two folders, `prep_surf1_si/` and
  `prep_surf2_si/`, because it has two surfaces; two crystals of one
  formula that must be told apart get two labels.
- **Protocol** — the activation species, energy, angle of incidence and
  fluence, the activated depth the surface is REQUIRED to reach (the
  §3.5 gate's depth threshold, revised 2026-08-28); the press mode,
  load, depth and duration; the hold temperature; the pull rates of
  §5.4's ladder. How the experiment is performed.
- **Numerical** — tolerances, cutoffs, convergence criteria, the
  committee stride and persistence window of §7.3, the significance
  levels of §7.5, the contact-gap averaging window, stress window,
  stress floor, control interval and press time budget of §5.2, the
  settle duration of §5.3, the depth-profile layer width and the
  disorder scatter multiple of §3.5, slab thickness, cell size. How
  carefully we compute.
- **Ensemble** — the master seed and the realization count.
- **Deployment** — resource class, node counts, walltime, modules. This
  lives in a *separate document* (`ARCHITECTURE.md` §4.1) and the pair
  specification cannot express it at all. That document is a single
  machine-local config with two sections — a hardware inventory (the
  per-cluster swap unit) and a per-**kind-of-job** usage map (§4.1) — and
  it is the ONLY input route outside `sabsim.toml`. The strict-vs-layered
  input question is resolved in favor of strict: the project's
  `sabsim.toml` carries material, protocol, numerical, and ensemble
  **self-completely** (§1.4), and the deployment file is deployment-ONLY —
  it never layers a scientific or numerical default into the spec, so
  nothing that moves the answer can hide in a settings file.

The protocol/numerical line has a crisp test. **A numerical setting is
one whose influence on the answer must vanish as it is refined. A
protocol knob's influence on the answer *is* the physics.** Refine a
tolerance and watch the number move, and you have a convergence problem.
Change the press load and watch the number move, and you have a result.
A settings layer that cannot tell these apart cannot tell numerics from
physics, and neither can any report or database built on top of it.

**Ensemble** is separate because a seed is not a knob you tune, it is a
coordinate you sample. Averaging over seeds is where §6.6's uncertainty
comes from, so a seed is the one setting whose *variation* is the
measurement rather than a threat to it. One **master seed** is recorded;
every per-realization seed is derived from it deterministically, so a
single number reproduces an entire ensemble (§3.6).

The honest boundary case is the **pull rate**. It is physically real —
§6.4's mechanical work is rate-dependent because dissipation is real —
yet §5.4 also uses it as a convergence variable, extrapolating the
ladder toward the quasi-static limit. It is a protocol knob that we
additionally refine, and it sits on the line rather than on one side of
it. The categories are a tool for thinking, not a law of nature, and
§1 says so rather than pretending the boundary is clean everywhere.

### 1.3 What is not a setting

Equally important is the list of quantities a user must **not** be able
to specify, because each is derived, and each has a section that owns
its derivation. Prior art let several of these be typed in by hand, and
paid for it.

- **Lattice constants.** They come from a bulk relaxation under the
  current potential, referenced to VASP (§2.2). Prior art hardcoded
  literature CIF values, and `PRIOR_ART.md` §1.6 traces its Stage-1.5
  step-zero pressure of −30 to −40 GPa directly to that choice. The
  distinction is exact: SABSIM reads the crystal's *symmetry and basis*
  from a CIF but not its *scale* — the CIF cell is a starting geometry
  the relaxation then resizes, so the number that reaches the box is the
  potential's own equilibrium lattice, never the file's. The settings
  supply a material and its crystal (as a CIF) and a surface face; never
  the lattice constant itself.
- **The shared lateral cell, the tiling matrices, and the residual
  strain.** Outputs of the coincidence solver (§2.3), never user knobs.
- **Bond cutoffs.** Derived per species pair from the first minimum of
  that pair's partial g(r) (§6.3).
- **The interface-subcell size.** The outcome of a convergence test run
  with the potential itself (§6.4).
- **The activated depth.** Measured by the validation gate (§3.5), and
  then *consumed* by §2.5's slab-thickness criterion.
- **The potential.** Not a knob but an artifact, referenced by
  generation identifier.

A useful way to read this list: **a setting is a choice; a derived
quantity is a consequence.** Letting a consequence be typed in is how a
pipeline comes to disagree with itself.

### 1.4 No hidden defaults, and no version numbers either

Two rules govern the specification's contents, and they pull in the same
direction.

**Every effective value appears in the input.** The loader **rejects an
incomplete specification** rather than quietly filling it from a default
buried in the machinery. If a number influenced the answer, a reader can
point at where it was written. This is `VISION.md` principle 1 taken
literally, and it is the difference between a knob that was frozen and a
knob that was forgotten. To keep that livable, defaults exist only as a
**generator** — a command that emits a fully-populated specification for
the user to edit — never as a silent fallback at load time. Convenience
lives in writing the file, not in reading it.

**Protocols are identified by their contents, not by a version label.**
A version number imposes a single line of descent on something that
branches: protocols are explored, abandoned, and revisited, and `v2` is
not obviously later than a sibling. So a protocol's identity is a
**fingerprint computed from its own values** — a short digest that two
specifications share exactly when their protocol values agree. It is
recorded in every report, and it is derived, never typed.

The fingerprint serves **provenance**: it answers "which protocol
produced this number?" without anyone having had to name one. It does
**not**, by itself, serve §1.1's precondition, and it is worth being
clear about why. A relation that contrasts protocols *requires* the
fingerprints to differ. So comparability is checked **field by field
against the relation's declared controls**, not by matching one digest
against another. Comparing whole-protocol fingerprints would answer a
question no relation asked.

The field-level comparison is needed regardless, since it is what
produces the difference set. The digest is the cheap identity; the
field comparison is the actual check.

Together these give the v1 freeze its meaning. **"Frozen" means written
down in one place, not absent.** Prior art froze its protocol by
hardcoding it, which is why no result it produced can name the protocol
that produced it.

### 1.5 Units are carried, and validation happens in three phases

Every dimensional setting **names its unit**, exactly as §6.6 requires
of every measure. The dose's general form is a fluence in ions·Å⁻² —
cell-size-independent — from which the impact count follows by the surface
area; §3.2 gives the full rule, including the plain-count shortcut v1 uses
for its single fixed cell. No reader should have to trust a conversion
factor typed into a report string.

Validation splits by WHAT EACH CHECK NEEDS, and the split is not
arbitrary — it is the same shape as §7.2's two-phase potential gate, and
for the same reason. The static pass needs only the file; the resolution
pass needs the environment; the deferred pass needs a measurement the
pipeline must first produce.

- **Static validation, at load.** Types, units, ranges, completeness,
  and the consistency requirements that need nothing from a running
  pipeline. The sharpest of these: **the union of the pair's species
  must equal the potential's global type map** (§4.3), which is
  STRUCTURAL 1a enforced at the earliest possible moment rather than
  discovered at an intermixed interface.
- **Reference resolution, before the first engine opens** (added 2026-07-24). A
  specification can be well-formed and executable in principle while POINTING
  AT things that are not there: a crystal file at a path nobody created, a
  `material_domain` (§4.8) no registry entry covers. These are not type errors,
  so the static pass admits them; and they are not measured quantities, so the
  deferred pass never looks. They surface instead partway through a run, after
  the node-hours that reached them were spent. This phase is separated from the
  static one by a single property: it needs the ENVIRONMENT — a filesystem, the
  registry — rather than the file's text. Since 2026-08-30 it also resolves
  BOTH surfaces' environment libraries,
  `prep_surf1_<a>/environment_library.toml` and
  `prep_surf2_<b>/environment_library.toml` (§3.5), so a project that has
  prepared only one surface is told so on the login node. Keeping it out of the
  loader leaves parsing pure and testable from anywhere, and puts the check at
  the last moment before compute is committed. It reports EVERY unresolved
  reference at once rather than the first, because these failures cluster — a
  moved data directory breaks every crystal path together — and fixing a
  specification one error per run is a bad afternoon. What it cannot yet check
  it NAMES rather than skips: `potential_ref` points at a manufactured force
  model, and the bootstrap that produces one is not built, so there is nothing
  to resolve it against. When that store exists, its lookup belongs here.
- **Deferred validation, at the point of use.** Some requirements
  reference quantities that do not exist until the pipeline has run.
  §2.5's criterion — `slab_thickness >= activated_depth +
  minimum_bulk_thickness` — cannot be checked before §3.5 has *measured*
  the activated depth. That check is registered at load and evaluated
  the moment its input exists.

Both are **gates**, not warnings. A specification that fails static
validation does not run.

But note carefully what these gates judge, because §1.1 forbids the
other thing. They reject a specification that **cannot be executed** — a
species the potential has never heard of, a fluence in the wrong units,
a slab too thin to contain its own activated layer. They never reject a
specification whose *comparisons* would be hard to interpret. Whether
two pairs are worth comparing is a scientific judgment, made by a
person, downstream, with the two specifications in hand (§1.1). Whether
a pair can be performed at all is a mechanical question, answered here.

### 1.6 The specification is the provenance record

`VISION.md` goal 3 asks that every reported number name the simulations,
inputs, code versions and settings that justify it. §5.7, §6.6 and §7.8
each carry a provenance block. §1 is where that obligation is actually
discharged, because the settings object *is* the thing to be recorded.

The requirement, stated as a test: **the effective specification must be
reconstructible from any output the pipeline produces.** Every report
echoes back the fully resolved specification together with its protocol
fingerprint, the potential generation, the master seed, and the version
of every code involved.

This is the direct answer to how prior art came to publish a work of
adhesion computed from a trajectory that its own directory marked
incomplete, alongside a strength read from an entirely different
simulation (`PRIOR_ART.md` §1.7). Neither number could name what
produced it. A number that cannot name its own provenance is not a
result.

### 1.7 Programmatic first, the file second

Per `VISION.md` goal 2, the controller is a library-style programmatic
interface, so another researcher can point the pipeline at a new
material pair from their own code. The canonical specification is
therefore a **typed, validated in-memory object**; the human-editable
file is a *serialization* of it, and the two must round-trip exactly.

The direction matters. If the file were canonical and the object a
parse of it, then the file's syntax would be the schema, and validation
would be advisory. With the object canonical, the schema is the type,
the file is data, and a specification that cannot be constructed cannot
be run. Hand-editable settings are a convenience side door, not the main
entrance.

### 1.8 What we keep, what we replace, and v1

**Keep:** nothing. Prior art has no settings layer — it has a directory
convention.

**Replace:** working-directory-as-configuration (→ the configuration is
an object, the directory an output); site details baked into emitted
scripts (→ a separate deployment document, §4.1, which the pair spec
cannot express); hand-typed lattice constants (→ derived from the
potential, §2.2); hidden defaults (→ the loader rejects an incomplete
specification); an unnamed, unrecorded protocol (→ inline values with a
content fingerprint); and numbers that cannot say where they came from
(→ the specification is reconstructible from any output).

**Frozen for v1:** the project is ONE pair — the **Si/SiO₂ facing pair** — and
the **Si/Si same-material reference** is a second project the person runs
beside it, sharing one potential and one protocol so that §7.4's ratio can be
formed by hand (revised 2026-08-30 (Paul)). Every protocol knob takes a single
value — written down, not hardcoded — and the design already admits
distributions (an energy or angle spread) without changing shape. Iterating
over composition, dopant, activation level, pressure, temperature or crystal
face is the outer-loop sweep deferred in `TODO.md`; §1's contribution to it is
that a sweep becomes a set of specifications rather than an edit to the
machinery.

**Serialization format — TOML** (ratified 2026-07-13), for both the
project's `sabsim.toml` and the deployment rc file. TOML was chosen for its
readable, typed key/value tables and unambiguous parse; a change would
need a concrete blocker. The **schema mechanism** built on top of it
(how required-versus-optional keys are declared and validated) is still
a follow-on.

**Still DESIGN follow-ons:** the schema mechanism; the exact fingerprint
definition (which fields are included, and how a value declared irrelevant to
comparability is excluded); and the values themselves. (The difference-set
classification and the relation grammar were follow-ons of the retired study
layer, §1.1, and are gone with it.) That last one is not a small matter —
**every numeric follow-on left open by §2 through §7 lands in this file**, and
§1's real service is to have given them a single, inspectable home.

## 2. Structure builder

This section designs steps 3 and 5 — cutting each crystalline slab and
assembling the two of them face to face in one periodic box. Prior art
supplies a working polar-slab symmetrizer and a worked 16:15 coincidence
cell (`PRIOR_ART.md` §1.2, §1.5), but its builder is **single-slab**:
the shared lateral cell that ties the pair together is a number the
operator types into two separate config files, and in one generation the
two files disagree, so the "matched" slabs are strained to cells 0.9 %
apart. Everything below follows from putting the *pair* back at the
center.

### 2.1 The facing pair is the primary object

A slab has a lattice; a **pair** has a *shared* lateral cell. That
shared cell is an invariant of the pair, so no slab can be built before
it is solved for. The structure builder therefore takes two materials
and two surface faces, and emits, in one atomic step:

- the **shared lateral cell** both slabs will adopt;
- for each slab, the **integer tiling** that carries its own surface
  lattice into that cell (an output of the solver, never a user knob);
- for each slab, the **residual strain** it must absorb, recorded in
  the pair's provenance record (`VISION.md` goal 3) and passed forward
  as a training-configuration dimension the MLIP must cover (STRUCTURAL
  1b);
- the two slabs themselves, already strained, already tiled.

Prior art's failure is the direct consequence of the opposite choice.
Each material's job file hardcodes the *other* material's lattice
constant as a literal and recomputes the common cell independently — one
using `15 * a_linbo3`, the other `(15*a + 16*a_sio2)/2`. Nothing ever
compares the two answers. With a pair object the shared cell is computed
once and cannot disagree with itself.

### 2.2 The lattices come from the potential, checked against DFT

The matcher needs each material's surface lattice vectors. Taking them
from a published crystallographic file is the obvious move and it is
wrong. The slabs are subsequently evolved by a *potential*, and a
potential has its own equilibrium lattice, which differs from the
experimental one by some small error. Build the box on the experimental
lattice and the potential immediately finds itself compressed or
stretched: prior art hit exactly this, reporting −30 to −40 GPa of
internal pressure at step zero and losing hundreds of atoms, and
absorbed it with a relaxation stage rather than fixing the cell. Worse
for us, the residual strain we *record* would then be wrong by the
potential's own lattice error, and that number is a deliverable.

So SABSIM derives each lattice constant from a **bulk relaxation under
the current production potential** — the same committee that will run steps
6 and 7: the heal, the press, and the pull (revised 2026-08-08, §3.4 — the
heal moved out of step 4 into the bond flow). Step 4 is the exception: its
cascade runs under the universal foundation MLIP with ZBL cores, not
the committee (see below). Two consequences follow:

- The lattice is re-derived **once per potential generation**. Each ALF
  round that changes the committee can change the equilibrium lattice,
  hence the shared cell. The structure builder is therefore *downstream
  of* the MLIP (`ARCHITECTURE.md` §2.1 already orders step 2 before
  step 3), not a one-time preprocessing step.
- The potential's relaxed lattice is compared against a **VASP
  reference**, and the disagreement is reported as a quantity of the
  potential-quality gate (§7) alongside stiffness and surface energy. A
  potential whose lattice constant is off is a potential that will build
  the wrong box; that belongs in the gate, not in a silent relaxation.
  That VASP reference inherits the **production settings block of the
  force model's own recipe** (§4.8) — the same settings that produced
  its training labels — so the disagreement reads as the potential's
  learning error and not partly as a settings mismatch between the two
  sides of the comparison.

**Cold start.** At the very beginning there is no production committee to
relax under — the bootstrap (§4.5) has not yet trained one. So "the
current potential" means the **universal foundation MLIP** — the *same*
chemistry-agnostic model that then runs the step-4 cascade (§4.7). This is
the universal-first decision (§4.7) reaching §2.2: the working lattice and
the amorphizing potential must **agree**, because a cell equilibrated under
one description and bombarded under another starts stressed — precisely the
CIF-vs-model offset that detonated the oxide bring-up (a ribbon relaxed on
one basis, then driven under a lattice the model did not want). Deriving
the cell under the universal MLIP retires that offset at the source
(the analytic-seed opt-in that once sat beside it was removed on
2026-08-26). §2.2's rule is re-applied under the trained committee the
moment it exists, re-deriving the cell then. The step is identical; only
the model beneath it changes. This makes "**derive the lattice by
relaxing the bulk under the current model**" a first-class, named
pipeline step, not a hidden preprocessing detail.

Because the universal MLIP lives in deepmd-kit's own self-contained
bundle (its own torch and MPI) and cannot load into sabsim's in-process
engine (`ARCHITECTURE.md` §4.1/§4.4), the **universal §2.2
derivation runs OUT-OF-PROCESS** through the same file handoff the step-4
cascade uses (`ARCHITECTURE.md` §4.4): the primary rank drives the bundle's
`lmp -in <script>` for a `fix box/relax` + `minimize`, writes the relaxed
cell with `write_data`, and every rank reads the cell back. Its first
*real* execution is still the **smallest** use of the execution layer —
a few-atom bulk relax — and it is exactly the moment the walking
skeleton's hardcoded stand-in lattice is retired: not smuggled into the
plumbing-only skeleton before a force engine exists, and not left
hardcoded once one does.

**One in-plane footprint, two potentials.** A run visits two force
models with slightly different equilibrium lattices — the universal
foundation MLIP + ZBL of the cascade and heal (§3.3, §3.4, §4.7) and the
production committee of the press/pull (§5). They cannot each own the
cell, because the two halves must share **one in-plane footprint** to be
joined (§2.3): that footprint is a single choice for the whole
per-material chain. It is fixed from the **committee-relaxed** bulk
lattices — the committee, not the cascade potential, because the final
measurement runs under the committee, so the joined system must sit
unstressed at *its* spacing. A dissimilar pair carries a small, recorded
in-plane residual strain from matching two materials (§2.4); the
same-material reference carries none.

What re-relaxes at each **force-model handoff** is therefore not the
footprint — that stays fixed — but the **internal atom positions and the
out-of-plane spacing**, under whichever potential is about to run. Per
half: (1) build at the committee footprint; (2) before the cascade, relax
internals + out-of-plane under the cascade potential, so the bombardment
is not run in a slab stressed by the committee↔cascade lattice
difference; (3) bombard (§3.3); (4) strip the projectile (§3.4); (5)
re-relax internals + out-of-plane under the committee — the re-anneal
itself. Only the model changes; the footprint does not. The in-plane
residual of a dissimilar pair is deliberate and cannot be relaxed away
without un-joining the pair; whether the small out-of-plane stress during
the cascade materially biases the amorphization is a §3.6 check to run,
not an assumption. At **cold start** the committee steps do not exist
yet, so both re-relaxations fall back to the cascade/seed potential and
the footprint is re-derived under the committee once it exists — the same
fidelity-ladder refinement the cold-start note above already makes.

### 2.3 Matching two surface lattices

This is the piece prior art does not have, so it is worth setting out in
full rather than naming a citation and moving on.

**The setup.** A crystal surface is periodic in two directions, so it is
described by two vectors lying in the surface plane. Call them `a_1` and
`a_2` for the first slab and `b_1` and `b_2` for the second. Any larger
repeating cell we can cut from the first surface is built by taking
whole-number combinations of its two vectors:

```
supercell_1 = m_11 * a_1 + m_12 * a_2
supercell_2 = m_21 * a_1 + m_22 * a_2
```

The four whole numbers form a 2×2 matrix, `tiling_A`. Its determinant is
exactly how many original surface cells the new cell contains, so it
sets the atom count; we require it to be positive, since a negative
determinant would mirror the surface rather than tile it. The second
slab gets its own whole-number matrix, `tiling_B`.

**The twist.** The two slabs need not share a crystallographic
orientation: the second may sit **rotated in the surface plane** by an
angle `twist_angle` relative to the first. This is a real physical
degree of freedom, and it is the single largest lever on how big the
matched cell has to be, because a relative rotation changes *which*
whole-number combinations line up with the other's. But it is worth
being precise about how the twist ENTERS the search, because in the
adopted algorithm it is not a knob we dial. The Zur-McGill enumerator
(below) searches whole-number tilings of the two lattices at their
GIVEN orientations; whenever a candidate pair of supercells matches in
shape, the rigid rotation that brings one onto the other IS that
candidate's twist, read out afterward rather than imposed beforehand.
So the search DISCOVERS the twist each coincidence cell implies; it does
not step twist across a grid. Prior art holds the twist at zero without
saying so, and so never sees the smaller cells a nonzero discovered
twist would have offered.

An **explicit** twist grid — rotating one lattice by each of a list of
prescribed angles and matching at every one — is needed only when the
twist becomes a **controlled** physical variable in its own right: a
study that deliberately compares, say, bonds formed at 0°, 15°, and 30°.
That is a future study dimension, and it would enter as a protocol knob
(§1.2), not as machinery the matcher always runs. Version 1 bonds at
whatever twist the smallest cell implies, so it reads that twist out and
records it as provenance, and imposes no grid.

**The misfit.** For a candidate `(tiling_A, tiling_B, twist_angle)` the
two supercells are almost never identical, so we ask what deformation
carries the second onto the first. Writing each supercell as a 2×2
matrix whose rows are its two vectors,

```
deformation = supercell_A * inverse(supercell_B_rotated)
misfit_strain = deformation - identity
```

`misfit_strain` is a 2×2 **tensor**, not two numbers. Its diagonal
entries stretch the cell along each direction; its off-diagonal entries
**shear** it, which is what happens whenever the two surfaces have
different cell angles. Prior art applies only a diagonal, two-number
rescale and so cannot match two lattices whose angles differ at all.

**The search.** Enumerate whole-number matrices up to an area limit, at
the two lattices' given orientations, keep every candidate whose largest
strain component is within the misfit tolerance and whose atom count is
within budget, and among the survivors take the smallest cell. Two properties
are worth stating because they are exactly what prior art lacks:

- Nothing in this ever assumes the two surface vectors have equal
  length, or meet at 90° or 120°, or that the same whole number is used
  in both directions. It is correct for any pair of surfaces.
- Allowing off-diagonal whole numbers and a nonzero discovered rotation
  routinely finds a far smaller cell at the same tolerance than the
  diagonal, rotation-free search does. Prior art's restriction is what
  forces its 7.9 nm, ~72,500-atom bilayer — and cell size lands directly
  on the execution walls of `ARCHITECTURE.md` §4.1, so this is a cost
  decision, not a stylistic one.

This construction is due to **Zur and McGill (1984)** and is implemented
in `pymatgen`'s interface-matching tools. We **adopt** the algorithm
rather than rewrite it (`VISION.md` principle 2, goal 5); what we build
around it is the pair object of §2.1, the potential-derived lattices of
§2.2, the strain split of §2.4, and the provenance record. Prior art's
continued-fraction reasoning (approximating the ratio of two lattice
lengths by a fraction of small whole numbers) is not wrong — it is the
one-dimensional shadow of this search, and remains a good way to seed
candidate whole numbers.

**A note on v1.** Si/Si has no mismatch, so the solver must return the
identity tiling, zero twist, and exactly zero strain. That makes a
same-material pair such as the Si/Si reference project
(`ARCHITECTURE.md` §2.3) double as the matcher's null test.

### 2.4 Splitting the residual strain

Both slabs must end up in one cell, but *where that cell sits between
their two natural sizes* is a physical question with a physical answer,
and "split it evenly" is only one special case of it.

Hold a slab of thickness `slab_thickness` at an in-plane strain `strain`
away from its natural size. Per unit of interface area it stores elastic
energy of roughly

```
energy_per_area = 0.5 * biaxial_modulus * slab_thickness * strain^2
```

Each slab pulls the shared cell toward its own natural size with a
stiffness proportional to `biaxial_modulus * slab_thickness`. Minimizing
the total stored energy over the shared cell size puts it at the
**stiffness-weighted average** of the two natural sizes, with the weight
for each slab being `biaxial_modulus * slab_thickness` (divided by the
square of its natural size, a correction that is negligible when the two
sizes are close). Three readings of that one formula:

- **Equal weights give the even split.** That is prior art's ±0.88 %, and
  it is correct only when the two slabs have equal stiffness *and* equal
  thickness. Its own design table has them at 36.62 Å and 54.57 Å.
- **One weight going to infinity gives "one slab takes all the strain."**
  That is what a later prior-art generation silently switched to.
- **In between is the physical answer**, and it is what we use: the
  stiffer, thicker slab moves less. The biaxial modulus is measured
  under the current potential by `driver/biaxial_stiffness` — a small
  in-plane strain sweep on a slab of the material whose stress-vs-strain
  slope is the modulus, a sibling of §2.2's bulk relax against the same
  `Engine` seam — and it is the same elastic constant the §7.2
  potential-quality gate reads. (v1 still applies the even split; wiring
  the measured modulus into the weighted split is the follow-on in
  `TODO.md`.)

Two further points the two-number rescale of prior art misses:

- The split is applied to the **strain tensor** of §2.3, shear included,
  not to a pair of lengths.
- Straining a slab in-plane must let it respond **out of plane**. Prior
  art passes a zero z-component to `apply_strain`, freezing the layer
  spacing and suppressing the Poisson contraction entirely. SABSIM
  strains the lateral cell, then relaxes the out-of-plane coordinates
  under the potential at fixed lateral cell.

Strain is applied **before activation**, because amorphous material has
no lattice to strain cleanly — the one point on which prior art's
reasoning is exactly right, and which we adopt unchanged.

### 2.5 Cutting the slab

Slab generation itself is adopted machinery: cleave the relaxed bulk
along the requested Miller face, tile it to the shared cell, add vacuum.
Three decisions sit on top of it.

**Thickness is a criterion, not a constant.** A slab must retain enough
undamaged crystal beneath the activated skin to behave like a substrate:

```
slab_thickness >= activated_depth + minimum_bulk_thickness
```

`activated_depth` is not guessed — it is measured by the depth profile
of §3.5. This makes step 3 and step 4 mutually dependent, so v1 fixes
thickness by a short convergence study (prior art's one genuinely good
idea here) and records the margin actually achieved.

In code the criterion is a FLOOR, not a formula that sets thickness: the build
takes the larger of the chosen `slab_thickness` and `required_activated_depth +
minimum_bulk_thickness`, where — because the build runs before §3.5 measures
anything — the depth term is the depth the project REQUIRES the activation to
reach (`[protocol.activation] required_activated_depth`, the same number the
§3.5 gate then demands; revised 2026-08-28, retiring the separate build-time
estimate `expected_activated_depth` — the depth you build for is the depth you
require), and it records the resulting margin on the shared-cell provenance.
All terms are project inputs, so a new material re-sizes with no code change,
and the silicon defaults preserve the §3.6-anchored 55 Å cell (55 > 7 + 30)
rather than shrinking it.

**Termination is chosen by surface energy.** Prior art takes
`sym_slabs[0]` with the comment "first candidate is sufficient" — the
first entry of a list, in list order. Where a face admits several
terminations, SABSIM enumerates them and selects by computed surface
energy, which the potential-quality gate already needs anyway.

**How the surface energy is computed.** It is the energy cost, per unit
area, of creating the face — cutting the crystal breaks bonds that were
satisfied in the interior, and that cost per area is what we compare.
For each candidate termination, build a slab, relax it under the current
model (the universal foundation MLIP at bootstrap, the trained committee
after — §2.2), and take

```
surface_energy = (slab_energy - atom_count * bulk_energy_per_atom)
                 / (2 * face_area)
```

with the factor of two because a slab has two faces. The cheapest
termination is the one nature prefers, and the one we keep. For a
**compound** the candidate terminations can expose different proportions
of the elements, so a slab is no longer a whole number of formula units
and the plain subtraction above fails; the surface energy then becomes a
function of how available each element is (for an oxide, how oxygen-rich
the surroundings are), and the termination kept is the one that stays
most stable across the physically allowed range. pymatgen's surface
tooling supplies exactly this, so it arrives with the adopted machinery
rather than hand-rolled. One caveat follows from the recipe: because it
**relaxes a slab under the force model**, surface-energy selection is an
execution-layer activity — it lands with the engine, alongside §2.2's
cold-start relaxation, and since v1's faces are non-polar and Si/Si has
a single termination, it does not bite until the first compound face.

**The polar-slab symmetrizer is a hook, and a gate.** v1's faces are
non-polar, so the four-strategy symmetrization ladder of `PRIOR_ART.md`
§1.2 enters as a documented hook for future ionic and polar pairs
(LiNbO₃, GaN). Two changes when it is switched on. First, when all
strategies fail, prior art prints a warning that the slab "will carry a
macroscopic dipole along z" and **returns it anyway**; an uncancelled
macroscopic dipole is not something a short-range potential can even
represent (see the long-range-electrostatics residual in `TODO.md`), so
this is a hard failure. Second, two of its four strategies symmetrize by
*removing atoms*, which changes stoichiometry and, in an ionic crystal,
net charge — so any strategy that removes atoms must report what it
removed, and the charge-neutrality check must run there rather than
downstream on the assembled bilayer.

### 2.6 Assembling the facing pair

By construction (§2.1) both slabs already share a lateral cell, so
assembly **asserts** commensurability rather than assuming it. Prior
art's assembler adopts one slab's box outright (`box = sio2["box"]`) and
never looks at the other's.

**The two halves arrive independently amorphized, read back from disk.**
Each surface was activated ALONE, in its own vacuum cell, on its own
engine (§3.1, `ARCHITECTURE.md` §4.3); assembly is the BARRIER stage —
the first to see both. So it does not receive two live crystalline slabs
straight from the cutter: it reads each half's amorphized FINAL state
back from the LAMMPS data file its activation stage wrote (the §4.3 file
handoff, which is also the run's durable record, §9), and everything
below — the dividing surface, the ejecta cut, the clash relief — operates
on those two read-back states. The crystalline all-in-one build (both
slabs cut and stacked in one step) is the activation-OFF null path, not
the bonding path.

**Each crossing of that seam is explicitly serial I/O.** A stage runs on
many MPI ranks at once, so "write the half, then read it back" has to say
WHICH rank does what. The rule is the same at every crossing: ONE rank
writes the file, a barrier makes it visible to the rest, and then EVERY
rank reads it independently for itself. Reading per-rank rather than
having one rank read and broadcast is both simpler and measurably faster
here (a few hundred kilobytes parsed from the node's page cache beats
serializing the same structure and shipping it), and it keeps the read a
pure local act with no hidden synchronization inside it. The one thing
this forbids is letting a library supply its own parallel behavior:
ASE will make `read` and `write` collective the moment it detects MPI,
which silently breaks the guard above, so all such calls are pinned to
serial mode (`ARCHITECTURE.md` §4.1, second discipline). Nothing about
the geometry below depends on the rank count.

**The top half is flipped so its activated face meets the interface.**
Both halves are bombarded on their TOP (+z) face — the cascade box is
open at the top and the beam comes down (§3.3). Stacked exactly as built,
the bottom half's activated face already points UP toward the interface,
but the top half's activated face would point up and AWAY, presenting its
pristine back to the bond plane. So the top half is mirrored in z before
placement, turning its activated face down to meet the bottom half's.
Miss this and you bond an activated surface to an unactivated one — a
silent error that would pass every downstream gate while measuring the
wrong interface. (Bombarding the top half from below instead was the
alternative; flipping a finished slab is far cheaper than a second
cascade geometry, so v1 flips.)

**Where is the surface?** Not at the highest atom. An activated surface
is rough, and a single asperity or a still-attached adatom would set the
gap for the whole interface. SABSIM builds the atomic number-density
profile along the surface normal and places the surface plane where that
density falls to half its interior value — the same robustness fix §3.5
applies to the amorphization depth, for the same reason.

**Ejecta.** Sputtered atoms left in the vacuum are removed by
**bonded-cluster connectivity**: an atom that is not part of the slab's
largest connected cluster is not part of the slab. Prior art cuts at the
first 4 Å gap in the z-profile scanning upward, a threshold that is one
unlucky adatom away from truncating the slab.

**The gap and the clash.** The initial separation is a knob, measured
between the two dividing surfaces, and it is the opening the PRESS
STARTS FROM (revised 2026-08-28 (Paul)): each half arrives at assembly
already healed and gated by its own prep job (§3.4, §3.5, §10.2), so
the pair is stacked close — near contact, but with the two faces not
yet loading each other — and the bond job's press begins from there
with no vacuum to cross. (From 2026-08-08 to 2026-08-28 the pair was
assembled WIDER than the potential cutoff so the bond job could heal
both surfaces in one box and then cut the vacuum out; with the heal
back in the activation stage that gap and that cut are gone.) After
placement the minimum cross-slab atomic distance is checked; if it
violates the floor, the gap is backed off and the adjustment is
recorded, rather than aborting the pair as prior art does.

**The opening and the interface plane are GEOMETRIC, never by
provenance (revised 2026-08-30 (Paul), after LEDGER T-40).** Once the
two bodies are in contact, atoms no longer belong to the wafer they
were built in: a press welds them, and a pull tears material off one
face and leaves it on the other — in T-40, sixty atoms of the upper
wafer stayed on the lower one. So "the upper wafer's bottom surface"
cannot be found by taking the atoms LABELLED upper and looking for
their lowest dividing surface: that search lands on the transferred
layer, reads an opening of one ångström across a sixty-ångström vacuum,
puts the interface plane inside the transferred layer, and counts that
layer's own internal bonds as material still joining the wafers — so
the pull can never stop. Every question about where the interface IS
is therefore asked of the WHOLE system's density profile along the
normal, with no atom labels at all: the interface is the widest run of
low density (below the same half-of-bulk threshold the dividing
surfaces use, on the same smoothed profile) that is bounded by material
on BOTH sides — a sputtered atom drifting in the outer vacuum bounds
nothing, so it can never invent a gap. The **opening** is that run's
width, measured crossing to crossing, and zero when no such run exists,
which is what "in contact" means; the **interface plane** is that
run's midpoint. While the bodies are joined there is no gap to find,
and the plane is then the one the assembly recorded (§2.6 above, the
builder's per-wafer z-ranges), which is exact at that moment because
nothing has yet been transferred; the recorded plane is only ever a
placeholder, since nothing is decided on it until a gap has opened.
The labels keep one job: reporting, after the fact, where transferred
material came from. The bridge count (§5.4) was made geometric for the
same reason first; this brings the two measures that feed it into
line, and the T-32 run that seemed to prove the old measure worked
had only a BALANCED transfer that happened to hide the error.

**There is no registry search.** Prior art exposes a `lateral_shift`
knob "to explore different bonding registries." Registry is a
crystalline-epitaxy concept, and STRUCTURAL 4 is precisely the
observation that an amorphous–amorphous contact has none — that is *why*
dissimilar bonding works. The lateral offset survives only as one more
realization variable, alongside the amorphization seed, for the
ensemble the bond metric is averaged over.

**The builder records the zone geometry; each driver carves its own
zones.** The region a stage needs — a frozen base for the cascade, two
grips for the press and pull, a thermostat border and an NVE interior
for both (§3.3) — is a geometric fact, but *which* regions a stage wants
is a protocol fact the builder should not carry. So (option C, resolved
2026-07-15) the builder records only the per-wafer z-ranges and the
interface plane, and each stage's driver carves its own depth zones from
them at open time. The activated skin is the one exception: it is a
*measured*, irregular atom set (§3.5), not a depth cut, so it travels as
an explicit atom set from activation to the press that tracks it. Prior
art re-derived each region ad hoc inside every LAMMPS input, from
hardcoded per-material layer thicknesses; SABSIM carves them once per
stage from the structure's own z-ranges plus a single region-geometry
setting, so the cascade and the pull agree on what "the substrate" means
without either of them re-measuring it.

### 2.7 What we keep, what we replace, and v1

**Keep:** the four-strategy polar symmetrization ladder (as a hook, now
gated); the slab-thickness convergence study; strain applied before
activation; continued fractions as a seed for candidate whole numbers.

**Replace:** the single-slab builder with an operator-typed shared cell
(→ the pair object); the scalar lattice-length match (→ whole-number
matrices plus twist, with a strain *tensor*); literature lattice
constants (→ relaxed under the potential, referenced to DFT); the even
strain split (→ stiffness-and-thickness weighted); the frozen
out-of-plane response (→ relax z at fixed lateral cell); repeat counts
computed by `ceil(target_size / lattice_constant)` and then overridden by
hand (→ repeats are solver outputs); termination by list order (→ by
surface energy); warn-and-continue on an uncancelled dipole (→ hard
fail); the extremal-atom gap and the 4 Å ejecta threshold (→ the
density-profile surface plane and bonded-cluster connectivity); the
registry knob (→ no registry; ensemble over seeds); ad hoc region
selection in every input file (→ z-ranges recorded once, depth zones
carved per stage by its driver — option C, §2.6); and adopting one
slab's box for the pair (→ assert commensurability).

**Frozen for v1:** crystalline **β-cristobalite(100) SiO₂ against
crystalline Si(100)** (ratified 2026-07-13), plus the Si/Si
same-material reference that null-tests the matcher; lattices from the
current committee, checked against VASP; the misfit tolerance and
cell-area budget set to admit the amorphous interlayer's buffering
(STRUCTURAL 4). β-cristobalite is cubic and the closest lattice match to
silicon, so (100) is a clean low-index face on both sides. The face,
the polymorph, and the target material are v1 **defaults**, not freezes:
each is a `sabsim.toml` knob a user may change later. Still DESIGN
follow-ons: the misfit tolerance and cell-area budget values themselves.

## 3. Surface activation (amorphization)

This section designs step 4 — activating each wafer surface by
amorphizing a thin skin so dangling bonds form for the interface to link
across. Prior art gives a *running* cascade recipe and hard-won thermostat
lessons (`PRIOR_ART.md` §1.2, §1.5), but its implementation is narrow:
argon-only, SiO₂-hardcoded metrics, a whole-slab thermostat, a fresh
LAMMPS process and full-slab disk round-trip per impact, and a
report-only "verification." This section keeps its physics and its
lessons while widening the frame to be pair- and mechanism-generic.

### 3.1 Activation is a pluggable mechanism

Surface activation is modeled as an abstraction: a mechanism that takes a
crystalline slab and an activation spec and returns an activated surface
(a thin amorphous, dangling-bond skin) plus a validation verdict. v1
implements one mechanism — **energetic-particle bombardment** — but the
seam lets other methods (plasma, reactive activation) slot in later
without touching step 4's consumers. We frame it as energetic-particle
activation rather than "Ar-ion bombardment" deliberately: an ion beam and
a fast-atom beam — the two things real SAB uses — are identical in
molecular dynamics, and both are one setting of the projectile spec below.

### 3.2 The bombardment spec (generic knobs)

- **Projectile — species-generic.** Argon is the v1 default; a co-species
  (iron first) may be co-deposited at a configurable fraction. The
  projectile mass and, crucially, the **ZBL Z-pair channels are derived
  from the species set** (substrate ∪ projectile), never hand-enumerated
  as in prior art — so a new material or co-species needs no code change.
- **Energy, angle, pattern.** Impact energy, angle of incidence (polar
  and azimuth), and the spatial impact pattern are knobs. v1 freezes each
  to a single value (the v1 protocol-knob freeze), but the design admits
  **distributions** — an energy spread, an angular spread, randomized
  azimuth — since a real beam is neither monoenergetic nor unidirectional.
- **Dose — two forms, one rule.** The general, size-independent form is a
  **fluence** (ions·Å⁻²): a dose per unit surface area, so the same value
  means the same damage whatever the cell size, and it matches how a real
  ion beam is specified. From it the **impact count** follows as fluence ×
  surface area. A plain impact **count** is also accepted as a convenience
  for a single fixed cell (prior art's only knob, here first-class rather
  than the sole option). The rule for which to use: a **fluence** whenever
  cells differ in size — comparing across box sizes, or across materials
  (the Si/SiO₂ pair, whose matched cell is a size neither material sets on
  its own) — and a **count** as a shortcut when the cell is fixed. The
  driver accepts either and converts a fluence to a count internally.
- **A recorded master seed** governs impact positions, velocities, and
  the LAMMPS seeds — both for reproducibility (`VISION.md` goal 3) and so
  the bond metric can be **averaged over amorphization realizations** by
  varying it (STRUCTURAL 4). Prior art's rewrite uses unseeded
  randomness, so its runs are not reproducible; we fix that.

### 3.3 The cascade engine — heat-sink and boundary design

This is the correctness core, and the part prior art gets wrong. The
cascade runs on a **universal foundation MLIP + ZBL** (STRUCTURAL 1b):
a `hybrid/overlay` splice of the universal model `sabsim.toml` names
(§4.7) with **two ZBL hard cores, not one**. The first, longer-range,
covers the projectile-substrate collisions; the second, with a very
short cutoff below the bond length, covers every substrate-substrate
pair. That second core is not optional: a universal model has only a
FINITE, soft short-range repulsion, so under an energetic cascade two
substrate atoms can be driven into each other and fuse; the short ZBL
supplies the missing hard wall while switching off well below the bond,
so normal bonding is untouched (`PRIOR_ART.md` §1.9). There is no other
cascade potential: the analytic forms an earlier draft carried
(Stillinger-Weber, Tersoff, Vashishta, Buckingham) were removed on
2026-08-26 and no fallback replaces them (Paul, 2026-08-28).

The **heat-sink and boundary design** must be:

- a **frozen (or Langevin) bottom substrate layer** that anchors the slab
  and absorbs recoil, so the slab does not drift as a whole;
- a **`p p f` (or shrink-wrap) z-boundary** so sputtered atoms *leave*
  rather than wrap into a periodic image — a true free surface;
- a **Langevin border thermostat** on the lower/side region that drains
  cascade heat at a physical rate, while the interior evolves under
  **NVE** so the collision cascade stays ballistic, not artificially
  quenched;
- the substrate held between impacts at the target temperature — the
  single room-temperature setpoint the whole experiment sits at, which v1
  reuses from the press hold (`press_temperature`); a dedicated activation
  temperature is a possible future knob, not a v1 need.

Why this matters, concretely: prior art's whole-slab NVT over-couples to
the cascade and quenches the damage before it accumulates — its own
documented failure, worked around by detuning the thermostat to a fragile
sweet spot — and the newest tree dropped even the frozen layer and
`p p f`, so it fails to amorphize at all. The frozen-base +
border-thermostat + NVE-interior design is standard radiation-damage
practice and is robust across a *range* of energy and dose, so we design
the root cause rather than inherit a tuned single point.

**Per-impact cycle:** insert the projectile above the surface with the
spec'd velocity → NVE cascade → short border-thermostatted relaxation →
repeat to the target fluence. Two details the cascade needs
(`PRIOR_ART.md` §1.9): the NVE cascade runs with an **adaptive timestep**
that shrinks so no atom moves more than a fraction of an ångström per step
— a fast recoil at a fixed step can jump straight THROUGH the steep ZBL
wall into an overlap — and it is restored to the fixed step for the
thermostatted relaxation (an adaptive step destabilizes the Nose-Hoover
thermostat). That restored step is the **ordinary MD step**, NOT the
tiny cascade step: the cascade step exists only to keep a fast recoil
off the ZBL wall, and by the relaxation the cascade has ended on its
physical-time halt and the deposited energy has thermalized, so nothing
is moving fast enough to require it. Pinning the cool-down to the
cascade step spends TEN TIMES the steps for the same physical duration
— measured at 49% of a whole single-impact run (`install/tests/
LEDGER.md` T-21) — for no physics. The re-anneal (§3.4) already ran at
the MD step; the between-impact relaxation was brought into line with
it on 2026-08-23. And the cascade **duration is sized for the impact
energy** —
a higher-energy impact deposits more and takes longer to dissipate — not a
constant step count that would cut a 500 eV cascade off early. **Execution
uses a persistent LAMMPS driver** — the LAMMPS **Python binding**, held
in-process across every impact (`ARCHITECTURE.md` §4.1), *not* a fresh
process plus a full-slab disk round-trip per impact as prior art does — at
the doses SAB needs (thousands of impacts) that overhead is prohibitive.

### 3.4 The MLIP re-anneal (a SABSIM addition)

Prior art is classical throughout; SABSIM adds a stage it does not have.
After the cascade creates the disorder, the activated surface is
**re-equilibrated under the production MLIP** (gentle, near-equilibrium) so
the final structure is MLIP/DFT-quality rather than cascade-quality — the
first rung of the fidelity ladder (§4.5). This is where the cascade→accurate
correction happens; validation (§3.5) runs *after* it. Its temperature,
duration, and ensemble are design parameters; a kinetically trapped glass
will not fully rearrange, so the cascade start must be a reasonable basin
(the STRUCTURAL 1b safeguards).

**The heal runs PER HALF, in vacuum, at the end of the cascade session
(revised 2026-08-28 (Paul)).** Each amorphized half is healed in the
same LAMMPS session that bombarded it, under the same universal model,
before it is written out and before the two halves ever meet. The
schedule is the project's `[protocol.reanneal]` block, applied as
**anneal, then minimize**: hold the mobile atoms at the hold
temperature for the hold duration, cool them to the press temperature
over the same span, then relax to the nearest local minimum. Anneal
first because the heat is what lets loose atoms and fragments the
cascade left standing proud of the surface find bonds; minimize last so
the surface the gate judges is a 0 K structure. The two halves heal
independently (they run as separate sessions, so in parallel), and
nothing about the heal depends on the other half existing.

**Why it moved back here, and what that dissolved.** From 2026-08-08 to
2026-08-28 the heal was done once on the ASSEMBLED pair, at a gap wider
than the potential cutoff, as the bond job's first phase. That design
had one reason: the heal then ran under the production potential, whose
engine lived only in the bond job. With ONE universal model running both
the cascade and the heal (§4.7), that reason is gone, and the per-half
heal is strictly cheaper — no second engine is opened, no vacuum gap has
to be built and later cut out, and a failed gate halts before any
assembly is done. Physically the two are the same: a surface healed at a
gap beyond the cutoff was already an effectively-free surface. What the
move removed from the bond flow: the wide assembly gap, the vacuum
"scissors", and a damped, displacement-capped pre-relax that had been
scaffolding for a two-potential mismatch that no longer exists.

**Where it runs, and the consequence for the gate.** The heal is the last
phase of the prep job's cascade session, so the §3.5 gate runs in the
prep job too, on the healed half as it is read back, and only a passing
gate makes that half a deliverable. The gate is again the checkpoint
BETWEEN each surface's prep job and the bond job, where a human inspects
the healed surfaces before the bond job's press/settle/pull is submitted
(`ARCHITECTURE.md` §4.1, §10.2; "prep" replaced "activate" 2026-08-30).

**Stripping the projectile.** The cascade embeds the beam species (argon in
v1), which is not part of the activated surface, and the committee's
vocabulary is only {Si, O} (§4.3) — it cannot re-equilibrate a cell that
still DECLARES argon, even emptied of argon atoms. So the projectile is
removed — its atoms AND its declared species — as the **cascade's own
cleanup, after the last impact and before the heal**, so the heal and the
gate see a substrate-only surface and the handed-off half is
substrate-only (the amorphized half the pipeline carries is {Si, O}, as
it always was). The strip is cascade housekeeping, not part of the
heal, and it is issued before the heal begins. This is
distinct from the ejecta cleanup that drops disconnected *substrate*
fragments; that is housekeeping on {Si, O}, this is what makes the {Si,
O}-only committee runnable at all.

### 3.5 The validation gate (pass/fail, not a report)

Prior art's `check_amorphous` only *reports*: it prints a g(r) RMSD
against an optional experimental curve with **no threshold**, its
partial-g(r) pairs are hardcoded to Si/O, and its depth metric scans
top-down and stops at the first crystalline-looking layer, so it can
report 0 Å depth beneath a defective surface (`PRIOR_ART.md` §1.8). SABSIM
makes activation validation a **gate**: a registry of pluggable structural
metrics, each measuring one property of the **healed surface (§3.4)** and
comparing it against a reference with a threshold. Every metric returns a
small verdict — what it measured, which reference it used, the threshold,
and whether it passed — and the gate passes only if *every* metric passes,
naming the first that fails so a halt is diagnosable. The registry is the
same idiom as the §6 measures and the §8 analyzer: adding a metric, or
swapping how one is computed, touches nothing else.

**When and where it runs (revised 2026-08-28, 2026-08-30 (Paul)).** The
gate runs in each surface's PREP job, on the healed half as it is read
back from its own cascade session (§3.4), BEFORE the two halves are
assembled. Each half is one free surface judged against one reference,
and a failed gate halts that surface's prep before any assembly — the
cheapest possible failure. (From
2026-08-08 to 2026-08-28 the gate ran in the bond job on the assembled
pair at a wide gap; that placement followed the heal, and the heal has
moved back here.)

Each surface is judged against **its own material's reference**, keyed by
that wafer's **declared species set** — a SiO2 wafer keys `{O, Si}`, a
LiNbO3 wafer keys `{Li, Nb, O}` — not by the pair's global type map, which
for a dissimilar pair spans both materials and could not tell them apart.
The per-wafer species is recorded on the assembled pair from the
pre-cascade half (so a fully-sputtered species does not change the key),
and a same-material pair falls back to the global map, which then *is* each
wafer's set. Its reference file is that key `.toml` in `share/activation/`
(`O_Si.toml`, `Li_Nb_O.toml`), the same species-keyed lookup silicon uses.

Judgment is **per realization.** Each metric judges ONE healed surface
against its reference; the spread over amorphization seeds is taken ABOVE
this module, by the sequencer's realization ensemble (`PSEUDOCODE.md` §10.8,
STRUCTURAL 4), exactly as the bond metric's spread is. So a metric verdict is
one measurement against one threshold, not an averaged distribution.

**What "crystalline" means here (revised 2026-08-29, Paul).** Until
this revision every metric below rested on a hand-set neighbour count:
an atom was "defective" if it did not have exactly the reference
coordination (four, for silicon) inside a hand-set bond cutoff. That is
a silicon-shaped definition. For lithium niobate there is no single
right neighbour count — lithium sits in a cage of six oxygens, niobium
in an octahedron of six, each oxygen has two niobium and two lithium
neighbours at different distances — so the "ideal" number depends on
which species pair is counted and on exactly where the cutoff is
drawn, and a slightly-too-long cutoff quietly changes the answer.
SABSIM therefore defines crystallinity WITHOUT a coordination number:

- Every atom's neighbourhood is described by its **bispectrum
  components** at a cutoff that reaches THROUGH THE SECOND neighbour
  shell and stops before the third (4.2 Å for silicon; the recipe
  states it per material) — a set of numbers that captures the
  distances AND the angles of the neighbours
  and does not change when the neighbourhood is rotated, shifted, or
  two atoms of the same species are swapped. (The same descriptor a
  SNAP potential is built on; the engine that computes it is a
  pluggable seam, §4.8 part 2, and the SAME engine with the SAME
  settings must be used on both sides of the comparison below.)
- The **environment library** is the set of those descriptors for every
  atom of every species in the material's UNDAMAGED states — the cold
  bulk crystal, the warm bulk crystal, and the clean unbombarded
  surface — computed under the same universal model the slab was built
  with. It is a product of the bootstrap's Collection 1 (§4.8 part 2),
  not a hand-written reference: it exists before the first gate ever
  runs, and it is found PER SURFACE in the project folder, in that
  surface's preparation folder named by the wafer's `material` label
  (`<project>/prep_surfN_<label>/environment_library.toml`, §1.2,
  `ARCHITECTURE.md` §1; revised 2026-08-30). The loader refuses a
  library whose recorded model is not the project's `[potential]
  universal_model`.

  Why per surface, and why no shared repository (Paul, 2026-08-29 after
  LEDGER T-39, and 2026-08-30): a library is built from one recipe, so
  it describes ONE material, and a dissimilar pair such as silicon on
  silica needs two. T-39 halted because one library had been named for
  every pair and the silicon one could not catalogue a silica face. A
  shared, cluster-wide collection keyed by chemical formula was
  considered and rejected: a formula does not identify a crystal
  (quartz and cristobalite are both SiO2), so it would have needed a
  second layer of naming, and a folder many projects write into is a
  folder many projects can quietly break. Keeping the preparation
  inside the project, in the folder of the surface it serves, needs no
  rule to learn; reuse is a copy of that folder into another project
  under the slot it needs there (`prep_surf2_si/`, say). For a homo
  pair the second folder starts as a copy of the first — the library
  is a property of the material, while the amorphization inside the
  folder is the surface's own.
- An atom in the healed slab is **crystalline** if the library holds an
  environment of its species within the library's own THERMAL SCATTER
  of it — "does this neighbourhood exist anywhere in the undamaged
  material?" — and **disordered** otherwise. The tolerance is a
  measured quantity: the scatter of the warm-run environments about
  their cold counterparts, multiplied by the numerical knob
  `disorder_scatter_multiple` of `sabsim.toml` (§1.2's test: refine it
  and the depth must converge, so it is numerical, not protocol).

Asking "does this environment exist in the undamaged material" rather
than "is this what THIS atom used to have" is deliberate: the cascade
moves atoms, and an atom knocked from the top that the heal re-settles
onto a good lattice site deeper down IS crystalline now; the frozen
bottom face and a clean top face are in the library through the
surface family and need no special case; and a multi-site crystal is
judged site by site with nothing declared by hand. Angles count too, so
a silicon atom that keeps four neighbours with badly bent bonds — real
amorphous silicon — is caught, which a neighbour count misses.

The cutoff was first set at the FIRST shell and measured wrong (LEDGER
T-36/T-37): amorphous silicon keeps its first shell almost intact —
four neighbours at the crystal's bond length with only a modest angular
spread — so a first-shell descriptor cannot tell the glass from a warm
crystal at any tolerance (0.3 % of glass atoms flagged). The disorder
lives in the SECOND shell, exactly as this section's g(r) argument says,
and a cutoff through it (4.2 Å) flags 94.5 % of glass atoms while
flagging no warm-crystal atom; a cutoff into the third shell (5.0 Å)
adds noise and separates worse (76 %). The same measurement fixed the
warm-run temperature: the library's thermal scatter must be measured AT
the temperature the gate judges (300 K, the heal's cool-to target) —
600 K runs spread 1.6x wider and swallow the glass (§4.8 part 2).

The library carries its own **self-check**, run when it is built: the
bootstrap's melt-quench amorphous family (§4.8 family 3) is what genuine
disorder looks like under this model, so a sound tolerance must call
nearly every warm-run atom crystalline and nearly every melt-quench atom
disordered. The two fractions are recorded in the library; a tolerance
that cannot separate them is reported at bootstrap time, not discovered
later as a misjudged slab.

**The library's temperature, and a warn/refuse band (Paul, 2026-08-29).**
The tolerance is measured on warm runs at some temperature, and the gate
judges a slab at the temperature the heal cools it to (the press
temperature, §3.4). A slab hotter than the library's warm runs jiggles
more than the library expects, so some of its crystalline atoms would
read as disordered. The library records its warm-run temperature, and
the project LOADER compares: a pair judged at or below it is fine; one
judged above it gets a WARNING that the tolerance was measured a little
tight; one judged more than **20 % above** it is REFUSED. The band is a
criterion of the loader, not a project knob — it is a validation
tolerance in the sense of §7.5, a statement of when the comparison stops
meaning anything. The number follows from how thermal displacement
scales: its amplitude grows roughly with the square root of temperature,
so a slab 20 % hotter scatters about 10 % wider — inside a single
scatter multiple, where a warning is honest and a refusal would be
pedantic. Beyond that the library's tolerance no longer describes the
slab, and a refusal on the login node is cheaper than a misjudged skin
after an hour on a GPU. The remedy is a warm run at the project's
temperature, i.e. a rebuilt library.

The registered metrics, each with what it actually discriminates:

- **g(r) and partial g_AB(r).** The radial pair-correlation function,
  with the species pairs *derived from the species present* (silicon alone
  gives just Si-Si; a compound gives every partial), computed with the
  **density-reference normalization** that is the one genuinely sound
  kernel in prior art (`PRIOR_ART.md` §1.5, §1.8): the near-surface
  amorphized region is ~20% less dense than the crystal beneath, so the
  reference density must be the local slab's, not the whole cell's, or the
  sputtering losses inflate the peaks. What separates amorphous from
  crystalline is not the first-neighbor peak (both have one near 2.35 Å
  for silicon) but the **second-neighbor structure** — sharp and split in
  the crystal, broadened and merged in the amorphous network — and the
  depth of the first minimum. Compared against a reference amorphous g(r).

- **Coordination-number distribution and per-species defect fraction
  (v1, to be re-based on the disorder score above).** The subtlety
  here is why the MEAN coordination is the wrong number: amorphous
  silicon is a continuous random network that stays very nearly
  four-fold, so the average barely moves from the crystal. The signal is
  in the **distribution** — its width, and the fraction of atoms that are
  three- or five-coordinated "defects" — measured per species and compared
  against the crystalline slab (a self-reference) plus an amorphous
  defect-fraction target. This is a real improvement over the Phase-1
  stand-in, which leaned on the mean, and over prior art, which hardcoded
  the species.

- **Ring statistics (v1, silicon-shaped; a follow-on re-bases it).**
  The network-topology check that is absent from
  prior art, and the one metric that separates a *true amorphous network*
  from a *merely defective crystal*: crystalline silicon is a network of
  six-membered rings, while the amorphous network carries five- and
  seven-membered rings. It is computed on the bond graph (bonds taken to
  the first g(r) minimum) through a **pluggable ring-enumeration backend.**
  v1 adopts the `networkx` graph library (VISION principle 2), counting
  King / shortest-path rings — the standard definition for amorphous
  silicon. The backend is a seam because a purpose-built ring tool — the
  group's Imago `bond_analysis.py` already has one — may be worth adopting
  later: being custom-built for ring analysis, it can be extended to ring
  types a general graph library does not offer readily. Such a tool would
  be evaluated for narrowness before adoption (the standing rule) and drops
  in behind this backend seam without disturbing the other metrics.

- **A robust amorphization-depth profile (revised 2026-08-29, Paul).**
  The fraction of DISORDERED atoms (the library definition above) in
  each horizontal layer of thickness `depth_bin_width` (a numerical knob
  of `sabsim.toml`), from the free surface down. The depth is the
  distance from the free surface to the LOWER edge of the deepest layer
  whose disordered fraction still exceeds the **baseline**, scanning the
  WHOLE profile — not stopping at the first crystalline-looking layer,
  which was prior art's 0 Å bug, and not the Phase-1 stand-in's
  top-contiguous walk, which is that bug under another name (LEDGER
  T-34's half B: 0.0 Å reported beneath a visibly disordered skin).
  The baseline is NOT measured on the damaged slab: it is the library's
  own false-alarm rate — the fraction of warm-run atoms the project's
  tolerance calls disordered, computed from the warm-run scatter the
  library records, so it follows the tolerance when a project refines
  it. (The earlier design took the baseline from the "deep third" of
  the slab being judged, and
  the first real run showed why that fails: the deep third contained
  the slab's frozen bottom face, whose atoms are under-coordinated by
  construction, and the polluted baseline swallowed the real skin.)
  Every layer is judged; there is no sparse-layer cut-off, because the
  disorder score is per atom and a layer of four atoms is four
  verdicts, not noise. This metric supplies the MEASURED
  `activated_depth` that the structure builder's thickness criterion
  (§2.5) only estimated a-priori, closing that loop, and that labels
  the activated skin (`PSEUDOCODE.md` §10.7).

**Where the references and thresholds live (revised 2026-08-28 and 2026-08-29,
Paul).** Three kinds of number are told apart. The ENVIRONMENT LIBRARY — what
the undamaged material looks like, atom by atom — is MANUFACTURED by the
bootstrap under the project's own universal model (§4.8 part 2) in the
surface's preparation folder; it is never written by hand, and it carries the
model name, the descriptor settings, the families and frame counts it was built
from, and its self-check fractions, so a reader can tell exactly what
"crystalline" was compared against. The remaining MATERIAL references — what an
amorphous network of this material looks like: the first g(r) peak, and for the
v1 survivors the coordination-defect band, the ring population and the bond
cutoff — are properties of the material, not choices of the experiment, so they
live in an **easily-locatable, version-controlled `share/` directory** in the
repository (`share/activation/<species>.toml`, the discoverable-reference-data
convention Imago uses), auditable and travelling with the code; as each v1
survivor is re-based on the disorder score, its hand-written number leaves that
file. The DEPTH REQUIREMENT is different: how deep the activated skin must
reach is set by the project's own dose and energy budget (§3.6) and changes
from project to project — a demonstration at a light dose cannot and should not
meet a production threshold — so it is a **protocol knob of `sabsim.toml`**,
`[protocol.activation] required_activated_depth`, and the gate reads it from
there. (Until 2026-08-28 it sat in the reference file as `[depth]
target_angstrom`; the first run of the heal-in-activation flow, LEDGER T-33,
halted a 50 eV demonstration on the production 7 Å and made the mismatch
plain.) The same number is the depth the §2.5 thickness floor builds for. For
v1 the material references are **documented STAND-INS anchored to the
literature** (for amorphous silicon: a first g(r) peak near 2.35 Å, a nearly
four-fold network with a few percent three- and five-coordinated defects, and a
five-/six-/seven-ring population), each flagged as a stand-in; the production
template's depth requirement is the **measured** 7 Å re-pinned in §3.6 from
this pipeline's own sweep, pending the work-of-separation study that will
derive it from the bond instead. The real anchors — a DFT / experimental g(r),
and the group's existing amorphous-silicon continuous-random-network model —
replace them as they are prepared; a large real reference need not bloat the
repository, since the reference-data resolver can also read it from the
deployment `SABSIM_SHARE` root (`ARCHITECTURE.md` §4.1). Pinning these numbers
and curves is a §3.6 / STRUCTURAL-1b DESIGN follow-on.

This is the "did the surface activate, and is its structure sane?" check
that feeds the potential-quality gate (§7; STRUCTURAL 1b).

### 3.6 What we keep, what we replace, and v1

**Keep** (re-framed, not copied): the ZBL `hybrid/overlay` splice
(channels generalized, §3.2); the density-reference g(r) normalization
(§3.5); the thermostat/timing values as a *starting range*, understood as
a symptom of the missing heat sink (§3.3).

**Replace:** argon-only species; SiO₂-hardcoded metrics; the whole-slab
thermostat / dropped frozen layer / `p p p` regression; the per-impact
process relaunch and disk round-trip; the report-only "verification";
impact-count dose; unseeded randomness; and working-directory-as-config
(`PRIOR_ART.md` §1.2 item 7).

**Frozen for v1:** mechanism = bombardment; projectile = argon (iron the
first accommodated co-species); **argon energy 500 eV** (ratified
2026-07-13, a user-overridable default — MD amorphization is validated
across 50–500 eV, and 500 eV amorphizes reliably while keeping the
cascade box tractable; a user may go **lower, e.g. 50 eV**, for a
gentler cascade, or higher toward the experimental fast-atom-beam ~1 keV
at the cost of a bigger box); **normal incidence**; the **dose is the
knob and the amorphized skin depth is the measured target**.

**RE-PINNED to 7 Å (2026-07-21), replacing the original ~2–3 nm
target, on measurement.** A 20-point energy × dose sweep on a
4400-atom slab (38.4 Å wide × 55 Å thick; 40–75 eV × 0.010–0.030
ions/Å²) found the skin depth spans only **3.95–10.26 Å and saturates
in BOTH knobs**: energy sets the reachable depth, because it sets the
ion range, while dose only fills in disorder once that range is
saturated. Every one of the 20 points sputtered NOTHING, and every one
passed the g(r), coordination, and ring criteria — failing only the
old 20 Å depth threshold, which nothing in that clean regime can
reach. The energies that WOULD reach 2–3 nm are exactly the ones
(100 eV and up) that over-sputter the slab and paradoxically fail the
gate outright. So 2–3 nm was not a dose that had gone unfound; it was
unreachable at any energy this cell tolerates. This is the §3.6
three-way slab ↔ energy ↔ DFT-cost accommodation resolving in favour
of the tractable cell, which the user already steered toward when the
500 eV default proved to vaporize small slabs. 7 Å sits mid-window,
comfortably above the ~5 Å floor below which the skin degrades into a
rough crystalline surface (mechanical interlock — a DIFFERENT regime,
not the SAB one modelled here). It remains a MEASUREMENT-ANCHORED
OPERATING THRESHOLD, not yet a physics-derived one: the work-of-
separation convergence study (`dev/TODO.md`, the skin-thickness item)
is what will replace it with the thinnest skin that still gives the
converged bond. It is written in `sabsim.toml` as `[protocol.activation]
required_activated_depth` (revised 2026-08-28; a project that runs a
lighter dose states a lighter requirement, and says so). Iterate the
dose until §3.5's depth profile clears it;
v1 freezes the
dose as a direct impact **count** for the single fixed Si/Si cell, the
per-area **fluence** being the general form used once cell sizes differ
(§3.2); **3 amorphization seeds** for the ensemble spread (the cheaper
rung; more seeds tighten the error bar at linear cost). The generator is
the universal foundation MLIP + ZBL of §4.7 (revised 2026-08-26; the
Stillinger-Weber + ZBL form decided 2026-07-17 was removed), with the
two hard cores of §3.3; the heal and the validation gate are both
mandatory, not optional. Energy, angle, and seed count are v1 defaults,
not freezes — each is a `sabsim.toml` knob.

## 4. MLIP backend and bootstrap

This section designs step 2 — turning DFT training data into the fast
DeePMD potential the production MD relies on — and the bootstrap that
makes that potential trustworthy on the first outer-loop pass. The
artifact under design already exists as a reviewed, unit-tested prototype
at `prototypes/alf_deepmd/`; this section documents its contracts and
math and records the decisions frozen for v1.

### 4.1 The backend is a config-selected plugin, not a fork

ALF loads every task and calculator from a dotted import path in its JSON
config (`load_module_from_string` / `load_module_from_config`), and its
own examples already load modules from outside the `alframework` package.
So a DeePMD backend is two small modules on `PYTHONPATH` plus **three
string swaps** versus a HIPPYNN run — with no change to ALF's source
(`VISION.md` principle 2; `ARCHITECTURE.md` §2.3 MLIP training):

- `master_config.ML_task` →
  `sabsim_alf_deepmd.deepmd_interface.train_DEEPMD_ensemble_task`
- `master_config.ML_config_path` → `deepmd_ml_config.json`
- `mlmd_config.ase_calculator` →
  `sabsim_alf_deepmd.deepmd_interface.DEEPMD_ASE_load_ensemble`

Everything else — builders, the VASP QM interface, the sampler core, the
`MLMD_calculator` uncertainty math, queue sizes, Parsl configs — is
untouched. A SNAP backend would be the same shape (swap the trainer for
FitSNAP, return a SNAP committee), which is why the plan keeps SNAP as a
cheap benchmark option.

### 4.2 The two ALF contracts we implement

**Contract 1 — the training task.** `train_DEEPMD_ensemble_task` is a
Parsl `@python_app` on the `alf_ML_executor` with ALF's exact call
signature; it returns `(list_of_success_flags, current_training_id)` and
writes each committee member under `model_path.format(id)/model-NN/`. ALF
accepts the round only when `all(flags)` is true. Internally it (1)
converts ALF's accumulated HDF5 once (§4.3), (2) writes one DeePMD
`input.json` per member — the shared template plus an injected `type_map`,
the training-system list, and a per-member random seed — and (3) trains
the members in parallel, one GPU each (`CUDA_VISIBLE_DEVICES`), shelling
out to `dp train` then `dp freeze`.

**Contract 2 — the ensemble loader.** `DEEPMD_ASE_load_ensemble` returns
a *list of `deepmd.calculator.DP` ASE calculators*, one per member. ALF's
`MLMD_calculator` already derives `energy_stdev` and `forces_stdev` from
any list of ASE calculators, so committee uncertainty (§4.4) works with
**zero DeePMD-specific code**.

### 4.3 The data bridge and the unit math

ALF stores every labelled configuration in an ANI-style HDF5 file (one
group per empirical formula); DeePMD reads its own on-disk "system"
layout. `data_conversion.ani_h5_to_deepmd` is the bridge. Per group it
reads `species` (per-atom symbols, sorted by atomic number),
`coordinates` (n_frames, n_atoms, 3) in Å, `cell` (n_frames, 3, 3) in Å
for periodic systems, and the energy/force datasets.

**The unit round-trip is exact by construction.** ALF stores each value
as `ASE_native × factor`, where the factor comes from the config's
`properties_list` — each entry is `[db_key, "system"|"atomic", factor]`.
The converter simply **divides by the same factor**, recovering the
ASE-native value (eV, eV·Å⁻¹, Å), which is *exactly* DeePMD's native unit
system, so no second conversion is ever applied. This holds for whatever
unit system the factors encode; it is not hard-coded. In the live config
the factors are the atomic-unit constants — energy `27.211386` (the eV
value of 1 Hartree) and forces `51.422067` (the eV·Å⁻¹ value of 1
Hartree/Bohr) — so dividing them out lands every value in eV and eV·Å⁻¹
for DeePMD. Because store-then-convert is the identity, no precision is
lost.

**What is written**, per formula group, is one DeePMD system directory:
`type_map.raw` (the global element ordering), `type.raw` (per-atom type
indices into it), a `nopbc` marker for non-periodic groups, and `set.000/`
holding `coord.npy` (n_frames, n_atoms·3), `energy.npy` (n_frames),
`force.npy` (n_frames, n_atoms·3), and `box.npy` (n_frames, 9) when a cell
was stored. For SAB every configuration is periodic (slabs, interfaces),
so the `box.npy` branch is the one that runs; the `nopbc` branch exists
for gas-phase molecules.

**One global type map — STRUCTURAL 1a made concrete.** The converter
collects every element seen across *all* groups into a single sorted,
stable `type_map` shared by every member and by the later LAMMPS
deployment, so type index k means the same element everywhere. That one
shared element space *is* the "single multi-species potential over the
union of the pair's species" decision: for v1's Si/SiO₂ the map is
{O, Si}; adding a pair extends the map rather than forking the model.

**Validation.** The round-trip is unit-tested
(`tests/test_data_conversion.py`): a synthetic two-group file is written
with ALF's *own* `pyanitools.datapacker` (so the schema matches a real
run), then the converted `coord/energy/force/box` arrays are asserted
equal to the known natives, exercising both the periodic and
non-periodic branches. It passes. The only check left for a live run is
confirming a real `data-*.h5`'s `properties_list` factors match the
config — the math itself is proven.

### 4.4 Committee uncertainty and the UDD bias

**The committee.** `n_models` (default 4) Deep Potentials are trained from
different random seeds — descriptor, fitting-net, and training seeds all
reseeded per member — so they differ only by initialization and data
shuffling. Their disagreement is the uncertainty signal; `MLMD_calculator`
turns the per-member energies and forces into `energy_stdev` (σ_E) and
`forces_stdev`. None of this is DeePMD-specific, which is why the same
sampler drives a DeePMD or a HIPPYNN committee unchanged.

The committee feeds sampling two ways:

- **Uncertainty-triggered capture** (the default sampler): run MD and grab
  a frame whenever σ_E or σ_F exceeds a cutoff (`Escut`, `Fscut`). This
  harvests configurations the potential is *already* unsure about.
- **Biasing-energy UDD** (Kulichenko 2023): the potential-agnostic
  mechanism, baked into `MLMD_calculator` behind a `use_bias` flag. It
  adds a bias energy **E_bias = w · σ_E** — the paper's *linear*
  one-parameter variant, with `w = E_en_bias_weight`, not the Gaussian of
  its Eq. 4 — and the matching bias force **−w · ∂σ_E/∂x** (Eq. 7), both
  computed purely from per-member energies and forces. The bias pushes the
  dynamics *up the uncertainty gradient*, actively driving the trajectory
  into weakly-trained regions instead of waiting to stumble into them.

**Why this matters to us.** UDD is potential-agnostic — the bias reads any
list of ASE calculators — so the DeePMD committee gets it for free, and it
is the engine by which the outer loop steers ALF into the bond-debond
region where the potential is weak (`ARCHITECTURE.md` §2.3 step 2). The
same committee σ is the always-on signal behind STRUCTURAL 3's
interface-fidelity check (§7). Enabling automated UDD needs only one
small, backend-independent ALF-side change — exposing `use_bias` /
`E_en_bias_weight` as `MLMD_calculator` constructor kwargs (or setting
them in the sampler task) rather than the notebook's attribute toggle
(`mlmd.use_bias = True; mlmd.E_en_bias_weight = 0.45`). That change helps
HIPPYNN equally and is tracked in `TODO.md`.

### 4.5 The bootstrap loop (STRUCTURAL 1b, made concrete)

Steps 4/6/7 run MD *on* the potential, but the configurations they visit
are what the potential must be trained on — the circularity STRUCTURAL 1b
resolves by generating those configurations with a *cheaper generator*
than the production model. Expressed through the plugin above, one
bootstrap pass is:

1. **Generator.** The **universal foundation MLIP** is the cheaper
   generator — no separate seed committee is trained (the 2026-08-21
   decision retires that step). The hand-built near-equilibrium DFT
   structures are no longer a SEED STAGE, but they remain REQUIRED
   TRAINING DATA: they are Collection 1 of the settled recipe, §4.8
   part 2, and all six families are required. An earlier draft of this
   step called them "an optional cheap anchor", which contradicted
   §4.8's own argument that the strained cells and the warm runs are
   load-bearing; §4.8 is correct and this step was corrected to match
   (2026-08-23). Retiring the seed STAGE never meant discarding the
   seed DATA.
2. **Generate the hard configs.** Run the violent Ar cascade and the
   heal on the **foundation MLIP + ZBL** to make the healed activated
   surfaces; run the press, settle and pull on the *same* **foundation
   MLIP** to make the assembled, settled, pressed and pulled cells — no
   per-pair committee is needed to generate any of them. These are
   Collection 2 of the settled recipe, §4.8 part 5, and all five
   families are required: the healed activated surface, the assembled
   pair at press start, the settled zero-load reference, the pressed
   cell, and the pulled cell (through failure).
3. **Label, convert, retrain.** VASP labels a selected subset (ALF's
   `QM_task = VASP_ase_calculator_task`); the converter folds it into the
   HDF5 store; `train_DEEPMD_ensemble_task` retrains the committee.
   Interface configurations are labelled as **interface subcells** (§6.4)
   rather than whole production cells — the potential is short-ranged, so
   the training signal is local, and all-electron cost grows steeply with
   atom count. Note the asymmetry: a *training* configuration need only
   be physically valid and relevant, which leaves the subcell choice
   free, whereas the `interface_fidelity` cross-check compares two
   methods and so demands that both see the identical system.
4. **Refine by sampling.** Re-run the protocol under the committee; the
   sampler (uncertainty-triggered and/or UDD-biased, §4.4) flags the
   configurations where σ is high; VASP labels those; retrain. Repeat
   until committee σ across a full protocol run falls below threshold.
   A run that the live monitor of §7.3 aborts is not a wasted run: it
   feeds this step, and the bounded UDD exploration launched from its
   triggering configuration is the most targeted sampler we have.

**Convergence** is that uncertainty threshold together with the
potential-quality gate (§7); this is the hand-off to STRUCTURAL 3. The
division of labor from §3 holds throughout: the foundation MLIP owns
the violent cascade and all config generation, the per-pair committee
owns only the gentle production stages, so the committee's species map
stays {O, Si} and the committee is never asked to reproduce cascades or
Ar.

**What fills the committee's slot in v1 (2026-07-22; updated
2026-08-28).** The loop above is the design; no committee is trained
yet, so the production potential's slot is filled by a stand-in: the
SAME universal foundation MLIP that runs the cascade and the heal (§4.7)
also runs the press, settle and pull of §5 — as a committee of one,
named by `sabsim.toml`'s `[potential] production_weights` and carrying
no uncertainty signal. It wears the same `ForceModel` / `pair_style`
seam the trained committee will, which is precisely what lets the swap
be deferred without disturbing anything upstream of it. Two
consequences are worth stating plainly. First, a material is described
in exactly ONE place — `sabsim.toml`'s `[potential]` block — so
bringing up a new material is a file edit, not a code edit. Second, the
cascade and the quiet stages differ only by ZBL: the cascade splices in
the hard cores of §3.3 because it drives atoms together at keV energies,
while the heal, press, settle and pull, which never approach that
regime, take the model alone. The consumer-side work that finally
replaces this stand-in with a trained committee is tracked as its own
item in `TODO.md`; until it lands, "the MLIP is designed" must not be
read as "the MLIP runs."

### 4.6 Decisions frozen for v1

- **Descriptor `se_e2_a`, r_cut 6.0 Å** (short-range) — consistent with
  STRUCTURAL 1a's short-range-for-covalent scope; a long-range extension
  (DPLR) is the ionic-pair residual, not v1.
- **Committee size `n_models = 4`;** the loss is force-weighted early
  (`start_pref_f = 1000`) relaxing to energy-weighted, over `numb_steps`
  = 4×10⁵ — the prototype template's schedule, tunable at training time.
- **Freeze format** is `.pb` (TensorFlow) or `.pth` (deepmd-kit v3
  PyTorch); the loader accepts either, and SABSIM standardizes on the v3
  PyTorch `.pth`.
- **Sampler thresholds `Escut`, `Fscut`** and the UDD weight
  `E_en_bias_weight` stay tunable knobs; pinning their real values is a
  STRUCTURAL 1b/3 DESIGN follow-on, not fixed here.

### 4.7 The cascade-potential generator: one universal model, named by the user

Sections §3.3 and `PSEUDOCODE.md` §10 run the surface-activation cascade
on a universal foundation MLIP spliced with the two ZBL hard cores of
§3.3, deliberately not the production committee (STRUCTURAL 1b: the
production committee must never be trained on cascade-level distortion
or on the projectile species). The same universal model then runs the
heal (§3.4), and — until a committee is trained — the press, settle and
pull too (§4.5). "Universal" means an off-the-shelf, already-trained
foundation model covering the periodic table with no per-material
fitting, so it dissolves the per-material potential search entirely and
matches the rest of the cascade, which already generalizes across
materials without change: the species-derived ZBL channels (§3.2), the
fluence dose, the frozen-base / border / interior heat sink (§3.3), the
heal (§3.4), and the species-derived gate metrics (§3.5).

**There is exactly one generator, and no fallback (Paul, 2026-08-28).**
An earlier draft of this section designed a ladder — a universal model
by default, a curated analytic form as a per-material option, a DFT
melt-quench as a last resort — with a registry of per-material entries.
That ladder is gone. The analytic forms were removed from the code on
2026-08-26 (they had been validated for silicon only and kept two
potential stories alive at once), and the melt-quench fallback was
struck on 2026-08-28: a material the named universal model cannot
describe is a material SABSIM does not yet cover, and the remedy is a
better universal model, never a second code path. What survives from
that draft is the part that matters for the future: the generator is a
SEAM, and the user — not the code — says which universal model fills
it.

**The user names the model; the code holds a table of the models it
supports.** The `[potential]` block of `sabsim.toml` names the universal
model by its identity (`universal_model`, e.g. "DPA-3.1-3M") and by its
concrete weights file (`universal_weights`); the bootstrap recipe's
`[generator]` block names the same pair for the manufacturing run
(§4.8). The code holds a small TABLE of supported universal models —
one row per model, each recording the model NAME, its source and
license, the exact VERSION (a foundation model is a large network that
shifts between releases, so "DPA" alone would let reproducibility erode
as upstream re-trains), the LAMMPS pair style it loads through, whether
it needs the global atom map, and its validation status. Phase-three
validation (§1.5) checks that the name in `sabsim.toml` is a row in that
table and that the weights file exists. Bringing up a new universal
model — a DPA-4, a MACE release, anything that runs inside LAMMPS — is
a new ROW, never a resolver edit: the cascade driver (`PSEUDOCODE.md`
§10.2) never names a model, it asks the resolver for the setup the
project named. Today the table has ONE row, DPA-3.1-3M; that is a
statement of what has been validated, not a limit of the design.

**The mechanism.** The resolver returns a complete cascade setup:
`pair_style hybrid/overlay deepmd <weights> zbl <long> zbl <short>` —
the universal model composed with the two species-derived ZBL cores
exactly as §3.3 specifies, with the projectile mapped to its real
element (a universal model covers the projectile too, so nothing is
left unmapped). The universal model still needs the ZBL cores because
it is not trained deep in the repulsive regime the cascade visits and
must be treated as out-of-distribution there. The quiet stages ask the
same resolver for the model ALONE, no cores spliced in (§4.5). A
message-passing model needs LAMMPS's global atom map, which the
resolver records and the driver issues before the structure is read.

**Acceptance: "good enough for a scaffold," certified by the gate.** The
cascade potential is scaffolding, not the product. Its only job is to
drive the surface into a *reasonable amorphous basin*; the heal (§3.4)
settles the structure and the §3.5 gate judges the result. So
"acceptable" is defined cheap-to-expensive, and the last rung is the
real arbiter:

1. it exists as a LAMMPS `pair_style`, so it can run at all;
2. it passes the inherent-structure screen — minimize a pristine crystal
   and a damaged configuration under the candidate, and the crystal must
   come out LOWER in energy (a model that ranks the damaged cell below
   the crystal gives a surface a thermodynamic incentive to destroy
   itself, and an activation run self-heats rather than amorphizing);
3. it reproduces the crystal's lattice and density within tolerance — a
   cheap bulk relax, which is also the §2.2 lattice derivation, so the
   slab is built to the lattice the cascade model wants and carries no
   step-zero stress;
4. it survives a probe single-impact cascade with the two ZBL cores in
   place — no fusion, no explosion;
5. its healed surface *passes the §3.5 activation gate* against the
   DFT / experimental references.

Rung 5 needs no new machinery: acceptance is **emergent from the
pipeline we are already building**, not a separate a-priori judgment of
the model's fidelity. Rungs 1–4 are cheap pre-filters that avoid
spending a full activation run only to fail the gate. Every rung is per
material AND per model: passing on silicon licenses nothing about the
oxides.

**The refusal is the default; the opt-in is per-run and visible.** A
table row that has not cleared rung 5 — nobody has yet run this material
through a full activation and watched the §3.5 gate accept the result —
is marked unvalidated, and the resolver REFUSES it, raising rather than
quietly running a model whose fidelity nobody yet has evidence for. But
a material's FIRST activation run is precisely what produces that
evidence, so the refusal cannot be absolute. The escape hatch is the
project's `[potential] allow_unvalidated = true` (revised 2026-08-26;
it was an environment variable before). It lives in `sabsim.toml`
deliberately: no one is tempted to flip the table's status before the
evidence exists, and because `sabsim.toml` is the provenance record
(§1.6) the choice stays in the run's own permanent record. Anything
produced under it is EXPLORATORY, and both the run and any report drawn
from it must say so. A gate-passing activation is what flips the row to
validated.

**Why not a bespoke amorphization model per material?** A tempting
alternative is to train an extra machine-learned potential for each
material, fused with ZBL, dedicated to the cascade — turning the
project's one committee into three models. The design deliberately does
not, for two reasons. The cascade potential is only ever asked to be
scaffold-grade — to land the surface in a reasonable amorphous basin the
heal and §3.5 gate then judge — so spending a full committee's training
cost to clear that low bar buys nothing a foundation model does not
already give for free across the whole periodic table. And STRUCTURAL
1b forbids training the *production* committee on cascade-level
distortion or on the projectile species, so the committee we do train
could not be the amorphization model in any case.

**The one row today: DPA-3.1-3M (adopted 2026-08-25).** The deepmd DPA-3
foundation model, full periodic table via the `MP_traj_v024_alldata_mixu`
branch frozen to a singletask `.pth`, CC-BY-4.0, loaded directly by
`pair_style deepmd` with energy conserved over NVE.

*Why not DPA-2.4-7M, which this section previously named.* That model
FAILS rung 2 on silicon: it ranks a damaged silicon slab 0.378 eV/atom
BELOW the perfect crystal (LEDGER T-21, job 16731025), so under it a
silicon surface has a thermodynamic incentive to destroy itself — the
failure is in the energy ordering, so no amount of force accuracy would
have caught it, and nothing downstream of a wrong basin is worth
computing. DPA-3.1-3M passes the same screen at +0.361 eV/atom. The
earlier preference for DPA-2.4-7M was an ENGINEERING one — it exported
cleanly to AOTInductor `.pt2` while DPA-3.1-3M hit an unbacked-symint
export failure — and that reason no longer binds: LAMMPS loads the
PyTorch `.pth` directly, so no export is needed. The `.pth` is also
PORTABLE where a `.pt2` is architecture-locked, which unpins the cascade
from any one GPU type; the ~2.5x per-step speed of an AOT build is the
only thing given up, and the export patch is documented should it be
worth reclaiming.

**Where it runs.** The deepmd engine is a self-contained bundle with its
own torch and MPI, so the universal cascade runs OUT-OF-PROCESS: the
cascade, the projectile strip and the heal are scripted as one LAMMPS
input and run as the bundle's `lmp` in a subprocess, the healed half
handed back through a file (`ARCHITECTURE.md` §4.1/§4.3/§4.4); the §3.5
gate then judges that file in the sabsim process. The prep job sets
`SABSIM_CASCADE_ENGINE_PREFIX` (the bundle); the weights are named by
the project's `[potential] universal_weights`. The §2.2 lattice
derivation rides the same subprocess. The press, settle and pull run the
same model in-process through the bundle's Python binding (the
`sabsim-dp3` environment, LEDGER T-25), which is what lets the bond
flow read forces and stresses back mid-run (§5).

DPA-3.1-3M is registered unvalidated because it has not yet cleared the
§3.5 gate on any material; its first gate-passing activation flips the
row. The weights are a large deploy-time artifact rather than a
checked-in file, so the table pins the model IDENTITY and `sabsim.toml`
names the concrete artifact path.

Remaining v1 follow-ons (logged in `TODO.md`): running DPA-3.1-3M
through a full activation to clear the §3.5 gate; pinning the
acceptance-check tolerances (the lattice/density band, the probe-cascade
stability criterion); native DP-ZBL as a later close-range refinement of
the `hybrid/overlay` splice.

### 4.8 The force-model recipe, and the settings it fixes once

§4.5 designs the bootstrap LOOP; this section designs the INPUT that
loop consumes. `PSEUDOCODE.md` §11 threads an object it calls the
`pair_specification` through twelve call sites — it seeds the first
committee, drives config generation, chooses what gets labelled, and
decides when to stop — and that object is defined nowhere in the chain.
The pair specification, by contrast, gets the whole of §1: five groups
of knobs, every value carrying its unit, nothing defaulting silently,
validation in three phases, the file itself serving as the provenance
record. The most expensive artifact in the project deserves the same
treatment. This section gives it one.

**Why the force model needs a file of its own.** Three inputs change on
three different clocks. The pair specification says WHAT to simulate,
and a researcher edits it constantly. The deployment configuration says
WHERE to run, and changes when the machine does. The force model is the
third: manufactured once, costing weeks of machine time, then consumed
UNCHANGED by many projects. It cannot live inside `sabsim.toml`,
because it is shared by all of them — whichever project held the recipe
would become a hidden master copy the others drift away from silently,
which is the same failure §1.6 avoids by making the specification the
provenance record rather than one project's private state. (Where the
recipe and its products live on disk is the surface's preparation
folder, `ARCHITECTURE.md` §1; a project that reuses another's model
copies that folder.)

**What the recipe is keyed by, and why the species union is not
enough.** STRUCTURAL 1a fixes ONE model over the union of the pair's
species, and §4.3's global type map makes that concrete. But the species
union states only what the model can REPRESENT; it says nothing about
what the model has been TAUGHT. Those are different claims, and
conflating them is a real hazard: carbon spans diamond and graphite,
boron several allotropes, and silica itself runs from alpha-quartz
through cristobalite to a fully amorphous network. Same composition,
genuinely different chemistry. A model trained on one phase is not
merely untested on another — it is confidently wrong there, which is
the failure mode committee spread is worst at catching. And training a
single model across two distant bonding regimes is not free: the
descriptor must resolve both at once, and data from one regime can
actively degrade the other.

So a recipe is keyed by **the species union TOGETHER WITH a declared
domain** — a named structural and chemical regime the model claims to
cover. This is not a new hazard discovered here; it has already bitten
the code. An earlier per-material potential registry (removed
2026-08-26 with the analytic forms it held) keyed on the species set
alone and needed TWO entries for {Si, O} — a bond-order form that
spanned the Si/SiO₂ interface and a silica-only form unable to describe
elemental silicon at all — and disambiguated them by smuggling a marker
string `_silica_only` into a set that is otherwise chemical elements.
That marker was this section's missing concept, patched in at the point
of pain; the registry key was then lifted to the (species, domain) shape
and the marker retired (2026-07-24), and a resolve that named no domain
for a species set carrying several REFUSED rather than picking one —
because those two forms disagreed about whether elemental silicon can
exist, so choosing
between them by luck would be a silent physics decision. Where exactly
ONE domain is registered, omitting it resolves to that one: nothing is
being guessed, because there is nothing to choose between.

**The domain is declared, and the declaration is checked cheaply.** The
domain carries a short human-readable label, but the label is a handle,
not the truth — the truth is the enumerated starting collection of part
2 below, which states exactly which phases were taught. Two consequences
follow, and they are deliberately at opposite ends of the cost scale. A
pair whose structures fall outside the declared domain is refused at
LOAD time, in §1.5's second validation phase, before a single node-hour
is spent. And the committee spread of §4.4 remains the RUNTIME backstop
for the case where the declaration itself was too generous. The cheap
check catches the obvious mistake; the expensive signal catches the
subtle one. Neither replaces the other.

**The eight parts of a recipe.** Each is stated plainly enough that a
student can read the file and know what was manufactured.

1. **Species union and domain.** The elements the single shared model
   must handle, fixing the type-map ordering every downstream simulation
   inherits (§4.3), together with the declared domain above. This is the
   key a pair's `potential_ref` ultimately resolves against.
2. **The starting collection — COLLECTION 1 of the settled recipe.**
   The calm structures, computed accurately before anything else and
   needing no protocol run to produce. Six families, ALL REQUIRED
   (settled 2026-08-23; the recipe is the eleven families of this part
   and part 5 together, and nothing outside that list is training
   data):

   1. **Bulk ground state** — the perfect crystal of every phase in the
      declared domain, at its relaxed lattice.
   2. **Bulk strained** — uniformly stretched, compressed and sheared
      cells of each bulk phase at several magnitudes, carried PAST the
      reversible range into the regime where bonds begin to fail. This
      subsumes the STRUCTURAL-4 strained substrates.
   3. **Bulk melt-quench amorphous** — the amorphous network of each
      phase, produced by melting and quenching a bulk cell. NOT the
      cascade's amorphized surface (family 7): this one is bulk, has no
      free surface, needs no bombardment, and is small enough to label
      whole. It is the cheapest source of the amorphous chemistry the
      interface is made of, and omitting it would leave that chemistry
      to be learned only from the expensive, surface-contaminated
      cascade configs. The melt is VERIFIED, not assumed (LEDGER T-42,
      2026-09-10): a small perfect periodic cell held at its own
      crystal volume can superheat far past its melting point and only
      vibrate — 72 atoms of quartz did exactly that at 3500 K — and a
      "melt" that never melted is a rattled crystal wearing an
      amorphous label. The test is the one thing that separates a
      liquid from any hot crystal: a liquid keeps travelling, a crystal
      does not. Over the second half of the melt hold the atoms'
      mean-square displacement must keep GROWING (diffusive, so about
      fourfold from one eighth of the hold to four eighths), where a
      crystal's saturates at its vibration amplitude (about onefold).
      The build refuses a melt whose growth is under twofold and says
      which knob to turn — hotter, longer, or a bigger cell — instead
      of letting the §3.5 self-check report a descriptor failure that
      is really a recipe failure.
   4. **Clean surfaces** — the free surface of each phase, unbombarded.
   5. **Rattled snapshots** — moderate-temperature static displacements
      about the cold cell.
   6. **Warm runs** — short runs of each crystal in the NVT and NPT
      ensembles at the temperature the protocol's quiet stages and the
      §3.5 gate run at (300 K for the production project; revised
      2026-08-29 from "modestly elevated", LEDGER T-37).

   Families 2 and 6 are the two whose necessity is easiest to doubt, so
   the argument for them is spelled out below.
   The potential-quality gate (§7.2) already checks elastic stiffness
   against references, so a model taught only relaxed and rattled cells
   would be gated on a property it was never shown — an inconsistency
   this closes. And the protocol IS a deformation experiment: the press
   is compression, the pull is tension, a mismatched interface under
   load carries shear, and a pull that fails through the crystal rather
   than along the interface is an outcome §6 must tell apart from the
   other. The warm runs earn their place for a separate reason. A
   rattled snapshot is a set of uncorrelated static kicks around the
   cold cell; it never shows the model correlated thermal motion or the
   volume a crystal actually takes at temperature. Yet every stage the
   trained model owns — the re-settle, the press, the settle, the pull
   — runs hot. A committee taught only cold and rattled structures
   reports large, meaningless disagreement the instant a warm run
   begins, spending the uncertainty signal exactly where §4.4 needs it
   to mean something. NPT here is what supplies thermal expansion; NVT
   supplies the correlated motion at fixed volume. For each family the
   recipe states how many and how produced.

   **Collection 1 also emits the environment library (added 2026-08-29,
   Paul).** The §3.5 gate's definition of "crystalline" — an atom whose
   second-shell bispectrum matches some environment of the undamaged material —
   needs a catalogue of those environments, and this collection is where they
   already are. So building Collection 1 also writes the library: the
   descriptors of every atom in family 1 (the cold ideal sites), family 6 (the
   same sites with their thermal spread — this is what fixes the gate's
   tolerance, and what its false-alarm baseline is measured on) and family 4
   (the clean faces, so a slab's own surfaces are not mistaken for damage).
   Family 2 is EXCLUDED, because it is carried past the point where bonds fail
   and a broken environment must not be catalogued as crystalline; family 3 is
   not catalogued either, but it is the library's self-check — the disorder
   every tolerance must recognise (§3.5). Three requirements follow. The
   library RECORDS the temperature its warm runs were made at (the lowest, if
   several), and the PROJECT loader compares the temperature at which the gate
   will judge a slab (the heal cools to the press temperature, §3.4) against it
   — a warning if the project is hotter, a refusal if it is more than 20 %
   hotter (§3.5 states the band and why); the recipe itself declares nothing
   about projects it has never seen. The declared surfaces must include the
   FACE the project's slab is cut with (matched by face and species; the
   termination — which atomic plane the clean cut ends on — is deliberately NOT
   matched, because every surface is bombarded to an amorphous skin before the
   gate sees it, so the termination makes no difference; Paul, 2026-08-29),
   checked between library and project at load time, not discovered as a
   mis-flagged face. And the descriptor engine and its settings are recipe
   settings recorded in the library, and the gate uses that record, never its
   own copy, so both sides of the comparison are computed identically. The
   cutoff is stated as a PHYSICAL length — the radius of the first neighbour
   shell — together with the expansion order and per-species weights; the
   engine's own parameters are DERIVED from it and never exposed raw (for
   LAMMPS `compute sna/atom`, whose cutoff is `rcutfac × (R_i + R_j)`, the
   per-species radii are set so that sum equals the physical cutoff, and the
   neighbour list is built at least that wide — the trap LEDGER T-35 fell into;
   `ARCHITECTURE.md` §2.3). The engine is a pluggable seam, bound 2026-08-29 to
   LAMMPS's own bispectrum compute (`ARCHITECTURE.md` §2.3/§4). The strain of a
   matched slab (§2.4, up to ~2 %) is expected to sit inside the thermal
   tolerance; the self-check is the test of that expectation, and adding the
   project's strained bulk cell to the library is the remedy if it fails. The
   purpose is stated out loud, because it is easy to over-invest: this
   collection exists so the FIRST committee does not fly apart, not to make it
   accurate. (It anchors that first committee; it is no longer a separate seed
   STAGE, §4.5 step 1.) Accuracy comes from the configurations the protocol
   actually visits — Collection 2 — and from the refinement loop.
3. **The production reference settings.** The block below.
4. **The accuracy audit.** The block below.
5. **How the hard configurations are manufactured — COLLECTION 2 of
   the settled recipe.** The configurations the protocol itself visits,
   harvested from a bootstrap run. Five families, ALL REQUIRED (settled
   2026-08-23; definitions revised 2026-08-28 (Paul) to the states the
   built flow actually visits), each a state the others do not revisit:

   7. **Healed activated surface** — one per half: the product of the
      violent Ar cascade AFTER the §3.4 heal, read from the tail of
      the activate recording. This is what the activate stage exists
      to make, and the surface the committee will be asked to press.
   8. **Assembled pair at press start** — the two healed halves stacked
      at the §2.6 starting opening, BEFORE any dynamics. Two surfaces
      facing each other, within range but not yet loading each other.
   9. **Settled zero-load reference** — the bonded pair after the press
      drive is released and the structure has settled (§5.3): in
      contact, at rest, under no applied load. This is the state every
      pull starts from, so it is the unloaded contact chemistry the
      model must get right. (It replaces the earlier "relaxed joint
      cell, in contact but not yet loaded", a state the flow no longer
      visits before the press.)
   10. **Pressed cell** — the interface under compression, from the
       first press chunk through the end of the hold.
   11. **Pulled cell** — the separation, INCLUDING the failing and
       failed states, since a pull that fails through the crystal
       rather than along the interface is an outcome §6 must tell apart
       from the other and the model must therefore have seen both.

   Families 8 and 9 are named explicitly because "press and pull" does
   not imply them: they are the un-loaded contact chemistries, visited
   once each and never again. Frames are assigned to families 8–10 by
   the press ledger the bond stage records (§5.5, §5.7): the step at
   which the press drive started, contact was declared, the hold ended,
   and the settle began and ended. Every recorded frame carries its
   step, so the assignment is a lookup, never a guess.

   The recipe states which stages run purely to harvest frames, and on
   WHICH force model each runs — the violent cascade and the heal on the
   foundation MLIP + ZBL form of §4.7, the press, settle and pull on the
   same universal foundation MLIP (§4.5 step 2) — how many, and under
   what conditions. Collection 1 is labelled as whole cells, being small
   by construction; Collection 2 is labelled as the **interface
   subcells** of §6.4, because all-electron cost grows steeply with atom
   count and a production cascade cell is an order of magnitude beyond
   what DFT will take (LEDGER T-21 measured ~1960 atoms for a
   single-impact calibration cell against a routine DFT budget of a few
   hundred).
6. **How a subset is chosen for labelling.** The accurate calculations
   are the cost bottleneck, so the recipe states the budget and the
   selection rule: favour the interface region, prefer configurations
   the committee is least certain about, skip near-duplicates of what
   the store already holds, and frame interface configurations as the
   subcells of §6.4 rather than whole production cells.
7. **The learning-loop settings.** Committee size; the descriptor form
   and its cutoff; training length; how the loss balances energies
   against forces; the two capture thresholds `Escut` and `Fscut`; and
   the UDD bias weight (§4.4, §4.6).
8. **The stopping rule and the resulting name.** The two convergence
   tests of `PSEUDOCODE.md` §11.6 WITH numbers attached — a stopping
   rule phrased as "below threshold" with no threshold is not a stopping
   rule — and the content-derived fingerprint computed from everything
   above, so a changed recipe cannot pass itself off as the model that
   was validated last month.

**Two settings blocks, because a comparison hides two errors.** Parts 3
and 4 are one decision, taken deliberately (2026-07-24). Three of the
five consumers of an accurate calculation are DIFFERENCES against the
model: the relaxed lattice of §2.2, the stiffness and surface energies
of §7.2, and the `interface_fidelity` of §6.4. Each such difference
stacks two errors that mean different things. **Learning error** is how
faithfully the fit absorbed the reference method it was trained on.
**Method error** is how far that reference method itself sits from
physical reality — an error no additional training data can remove,
since more data only teaches the wrong surface more faithfully.

Inherit the training settings everywhere and every difference reads
learning error cleanly and is BLIND to method error: a model trained on
under-resolved labels sails through every gate, graded against the same
under-resolved standard that taught it. Use tighter settings for the
references than for the labels and every difference reads the two mixed
together, blaming the model for a discrepancy baked into its data before
it saw a configuration. Neither is wrong; they answer different
questions, and the mistake is believing either answered both.

So the recipe declares BOTH. The **production block** — the basis
cutoff, the reciprocal-space sampling, the exchange-correlation
treatment, the occupancy smearing, and the electronic and geometric
convergence tolerances — is used for the labels AND for every reference
that gets differenced against the model. The **audit block** is a
tightened set run ONCE per recipe, on a handful of small cells, at
recipe-creation time; the recipe records how far the production block
sits from it. The gate then reports learning error, the recipe reports
method error, and a reader can add them. The audit is a few small
calculations against a budget of thousands of labels, so it is a
rounding error in cost and the only thing standing between us and a
gate that cannot see its own foundation.

**The sampling entry is a RULE, not a grid.** Reciprocal-space sampling
is stated as a spacing, so a few-atom bulk cell and a large amorphous
slab each receive a mesh appropriate to their size. Stated as a fixed
grid it is wasteful on the large cell and wrong on the small one — and
since the subcell of §6.4 is far larger than a typical training
configuration, a fixed grid is exactly what would make one settings
block unable to serve both. This is what makes the inheritance rule
implementable at all.

**The inheritance rule, and the three kinds of reference.** One production
block per recipe, established once and reused unchanged by every consumer that
computes an accurate number for comparison. But the rule binds only the
references we COMPUTE, and the design must not overstate it. §7.2 speaks of
checking "against VASP and experiment" as though those were one category; they
are not, and §3.5's shipped reference file proves it — every number there is a
literature-guided placeholder flagged `real = false` — while the required
amorphization depth, a project knob since 2026-08-28, is neither literature nor
DFT but a value MEASURED by this pipeline's own sweep, and the environment
library (§3.5) is a third thing again, manufactured under the model being
judged. So there are three kinds of reference: values we compute accurately,
values taken from published experiment, and values measured by our own
simulations. Only the first inherits. The other two carry their own provenance
and are compared to as they stand.

**The audited flag, reusing an idiom the project already has twice.**
§4.7's registry marks each entry `validated` and refuses an unvalidated
one absent a deliberate, externally-visible opt-in; §3.5's reference
file marks itself `real`. Both say: this exists, and nobody has yet
earned the right to trust it. The production settings block carries the
same flag — has the audit actually been run against these values, or
are they a plausible guess? A recipe whose settings are unaudited still
manufactures a model, because that is how the first one for any material
must come about, but the model is EXPLORATORY and its record says so,
exactly as a run under `SABSIM_ALLOW_UNVALIDATED_POTENTIAL` does.

**The recipe POINTS AT the reference data; it does not contain it.**
`PSEUDOCODE.md` §11's `bootstrap_potential(pair_specification,
reference_data)` already takes the two as separate objects, and that
separation is right: the reference set includes laboratory measurements
no recipe should pretend to own, and one reference set may serve several
recipes. What the recipe DOES record is which reference set it was
judged against, so the pairing is recoverable from the product afterward
rather than reconstructed by memory.

**Frozen for v1 (2026-07-24).** This section defines what a recipe must
state and why; every NUMBER in it — cutoffs, spacings, tolerances,
committee thresholds, strain magnitudes, labelling budgets — is a
placeholder resolved by the values file, and several cannot honestly be
chosen until the audit of part 4 has been run for the first time. The
(species, domain) key is BUILT — §4.7's registry carries it and the
marker is gone. What remains are follow-ons logged in `TODO.md`: the
record definition `PSEUDOCODE.md` §11's twelve call sites already assume,
carrying a chosen domain on the pair specification so the resolvers can
be handed one instead of relying on the single-domain shortcut, and the
load-time check that refuses a pair whose structures fall outside it.

**Built state (2026-08-26): the recipe is a file, and the first slice is
silicon.** The recipe of the eight parts above is a TOML file,
`recipe.toml` (templates in `share/templates/recipes/`, one per
material), loaded by `src/sabsim/bootstrap/recipe.py` with
`sabsim.toml`'s own discipline: every key required, units carried,
three validation phases. The production settings block
is the LEAN recipe of `dev/notes/vasp-labelling-recipe-lean.md` (chosen cheap
on purpose, to learn the cost by spending): PAW `Si`, `O`, `Li`, `Nb_pv`; PBE;
`ENCUT = 350 eV`; Γ only for every non-bulk system and `KSPACING = 0.5 Å⁻¹` for
the two bulk families; Gaussian smearing 0.1 eV; `EDIFF 1e-4`; single points.
The audit block (part 4) is DECLARED but `audited = false`, so everything the
first recipe manufactures is exploratory, exactly as the flag idiom above
intends. Parts 7–8 (the learning loop and the stopping rule) are parsed when
present but not yet consumed: the first slice builds the recipe, the
Collection-1 generators, the Collection-2 frame harvester, and the direct VASP
labeller (`sabsim bootstrap generate | label | harvest`); the ALF training
bridge and the refine loop follow. Collection 2 is NOT generated by new MD: the
bootstrap harvests the trajectory frames the ordinary prep and bond jobs record
when run with `--dump-visuals` under the universal model (`production_weights`
pointing at the DPA `.pth`), the "consumer difference" of `PSEUDOCODE.md`
§11.3. Interface frames are cut to sub-cells that keep only a couple of
crystalline layers under each activated skin (Paul, 2026-08-26 — the surface
atoms are what the training is for).

## 5. Bond/debond MD protocol

This section designs steps 6 and 7 — pressing the two activated surfaces
together, letting them bond, and pulling them apart while recording the
force that resists. It runs on LAMMPS under the MLIP (`pair_style
deepmd`, GPU; `ARCHITECTURE.md` §4.1) — that is the DESTINATION; until a
committee is trained these stages run on the universal foundation MLIP
as a committee of one, behind the identical seam, for the reasons §4.5
gives. The bond flow is: read the assembled pair → the one-time lateral
cell relax of §5.6 → press → settle → pull. The heal and the §3.5 gate
sit upstream, in the activation stage (§3.4, revised 2026-08-28).

**The whole press/pull runs on one persistent in-process driver.** It is
a single stateful, multi-phase run whose transitions are decided mid-run:
§5.2's dual-contact criterion reads a running-average normal stress to
know when contact is real, §5.3 asserts the grip force has settled before
the pull begins, and §5.4 reads both grip reaction forces as it pulls.
None of that is expressible by emitting a static input script and walking
away, so steps 6-7 are driven through **LAMMPS's Python binding** as a
persistent driver that reads forces and stresses back without a disk
round-trip. This is the same driver §3.3 adopts for the step-4 cascade,
here settled on the Python binding and carried across the entire
press/pull; `ARCHITECTURE.md` §4.1 gives the execution and parallelism
model — the binding runs under MPI (`mpirun -np N python`; on this
cluster a plain `srun -n N python` does NOT work, since it launches N
independent copies that each believe they are alone), so every control
decision above keys on **global, collective** quantities (a thermo
`pzz`, a summed grip force) and stays identical across ranks, and every
library file operation is held to explicitly serial mode so nothing but
our own code posts a collective (§4.1's second discipline). The LAMMPS dump
stays the durable trajectory artifact the analyzer consumes and
`run_to_contract` guards; the live read-back serves only the control
decisions, never replaces the on-disk record.

Prior art built this stage and ran it, which makes it the most dangerous
prior art we have: it produced a number. `PRIOR_ART.md` §1.7 records the
evaluation. The short version is that its interface had no chemistry —
one hand-tuned Morse well applied to every cross-interface element pair
— so nothing would stick, so the protocol was escalated until something
did. What its 3.746 J/m² measures is a well depth and an impact speed.
Every design choice below descends from refusing that trade.

### 5.1 The interface must bond on its own

The failure is a loop. With no interfacial chemistry the surfaces drift
apart; deepening the placeholder well to 1.0 eV (about thirty-eight
times kT) is not enough, because a static press still "leaves the main
slab detached"; so the upper slab is given a 150 m/s downward velocity
and driven into the lower one. The interface that results is a
mechanical interlock, and its measured strength is a readout of the two
numbers that were tuned to produce it.

SABSIM cannot enter that loop, because it has nothing to tune. The MLIP
is one potential over the union of the pair's species (STRUCTURAL 1a),
trained on cross-interface configurations; there is no cross-term to
invent, and **no analogue of `_BOND_XMORSE` exists anywhere in the
design**. Whether two activated surfaces adhere under a given load is
therefore a prediction of the potential, and the protocol's job is to
ask the question, not to guarantee the answer.

So step 6 emits, alongside the bonded structure:

- **a bonded / not-bonded verdict** at the specified load. A no-bond is
  a *result*, reported with its diagnostic label (§7), never a reason to
  escalate the drive;
- **a graded contact-quality measure**, so partial adhesion is
  distinguishable from none: the number of cross-interface bonds per
  unit area, and the fraction of the interface plane in contact, taken
  from the same density-profile and coordination machinery §2.6 and §3.5
  already define.

The graded measure matters because a binary verdict gives §7's diagnosis
nothing to work with. A potential that bonds a tenth of the interface is
failing differently from one that bonds none.

### 5.2 The press is a pluggable control mode

Two ways to bring the surfaces together, one seam, both emitting the
same contract (bonded structure, contact quality, and *both* the load
and the depth actually reached):

- **Load-controlled.** Ramp the normal stress on the top grip to a
  target bonding pressure and hold. This is the experimental knob
  (`ARCHITECTURE.md` §2.3 lists "load or pressure"), and it is the mode
  in which "did it bond?" is a clean question, since the load is the
  input and the approach is the response. Applying a load is setting a
  *force*, and a force accelerates nothing that is not integrated, so
  the driven grip is given mass in this mode — it is the one place a
  grip is not a rigid handle. The pressure then pushes it down and the
  approach is a genuine response; the settle re-freezes it afterward
  (§5.3).
- **Displacement-controlled.** Drive the top grip down at a fixed slow
  rate to a target press depth and hold. Numerically better behaved,
  since the grip cannot accelerate; here the load is the observable.

Running both is a **cross-check with real content**: press by
displacement to depth `d`, read the load `L`; then press by load to `L`
and see whether the depth returns to `d`. A gap between them is
irreversibility in the press itself, and it is measurable for free.

**Frozen for v1: load-controlled**, because it keeps bonding an
observable and matches the experimental knob; the displacement-controlled
mode is implemented at the same seam and run once, on the Si/Si
reference, as the cross-check.

Three constraints bind whichever mode runs.

**No velocity impact.** The approach speed must be far below the
material's sound speed, and the kinetic energy the surfaces acquire must
be far below the bond energy scale, or the press is a collision and the
interface it forms is interlock rather than adhesion.

**The thermostat must not see the drive.** Prior art thermostats a group
containing the drifting slab with a plain `nvt`, so 150 m/s of directed
motion is counted as heat; the thermostat then fights the drive and
never reaches its setpoint (its own log runs about 227 K against a 300 K
target). SABSIM thermostats **a border layer just inside each grip, and
nothing else** — never the grips themselves, and never the interface —
and, where any thermostatted region carries directed motion, removes the
center-of-mass bias from that region's temperature before applying it.
Each border is biased separately, because the two drift differently: in
a pull the upper border rides the driven wafer while the lower one stays
with the held wafer, so a bias removed over both at once would remove
neither's.

**Why the sink sits at the grips and not at the interface.** The layer
stack for the press and pull is the same border-thermostat + NVE-interior
design §3.3 argues for the cascade, but the *reason* does not carry over
and is worth stating in its own right. §3.3 keeps the interior on NVE so
the collision cascade stays ballistic; there is no cascade in a slow
press. The press/pull reason is that **§6.4's M1 is dissipative by
construction**, and §6.5's dissipation identity reads `M1 −
work_of_adhesion_as_fractured` as the energy dissipated in the pull. A
thermostat near the interface would drain exactly that energy — it would
delete the observable rather than merely perturb it. So the interface
must evolve under NVE, and the heat the pull generates has to reach a
sink that is as far from the interface as the slab allows: the border,
just inside the grips. This is the same reasoning that makes the border
non-negotiable rather than decorative — with no sink at all, the
interior is bounded by rigid handles and the dissipated energy has
nowhere to go but into heating the interface it was measured from.
(Consequently the border must actually be integrated; a thermostatted
layer that is never advanced is a reflecting wall, not a sink.)

**Contact begins from a defined gap, and is confirmed by a stress.** The
starting separation is the one §2.6 established between the two
density-profile dividing surfaces, not between extremal atoms. Contact
itself is declared on a **dual criterion**, adapted from prior art's
`find_contact_step` (`PRIOR_ART.md` §1.8) — one of the few pieces of its
design worth taking. The PRIMARY test is that the opening between the
two dividing surfaces has closed to a threshold, judged on a TRAILING
MEAN over the last `contact_gap_window` chunks rather than on a single
reading: one chunk's density-surface reading jumps by ångströms when a
loose atom drifts through the gap, and a single-reading test let the
wafers touch without contact ever being declared. The CONFIRMING test
is that the running-average normal stress across the interface is
SUSTAINED above a floor, `contact_stress_floor`, in magnitude — of
EITHER sign. Compression is the ordinary case: a gap can close on a
single asperity, whereas a normal stress above the floor means the two
surfaces are genuinely loading each other. Tension is the other: a
sustained *tensile* stress across a closed gap is two surfaces that have
already bonded and are pulling on each other, the opposite of an
asperity, and a press too weak to register as compression on a small
footprint would otherwise never declare contact (LEDGER T-30/T-31).
Both the window and the floor are numerical knobs of `sabsim.toml`
(§1.2), carried with their units — the window in chunks, the floor in
bar — and their influence must vanish as they are refined. (Revised
2026-08-28 (Paul); the trailing mean and the two-sided floor were first
applied in code on 2026-08-27 and are recorded here as the design.)
(Prior art measures its gap between extremal atoms, which is exactly the
asperity failure the stress criterion guards against; we fix both.)

**The press is driven in chunks, and the chunking is a project setting
too (revised 2026-08-28, Paul).** The driver advances the simulation a
`control_interval` at a time (a time, ~1 ps), reads the opening and the
stress back between chunks, and decides; that interval is the
resolution of the contact test, of the stage ledger (§5.5), and of the
settle's force series (§5.3), and refining it can only sharpen WHEN
contact is declared, never move the answer. The stress confirmation
averages over the last `contact_stress_window` chunks, the sibling of
the opening's window. And the press may search for contact for at most
`press_time_budget` (a time): a press that has not closed the gap and
loaded the interface within it is REPORTED as "no contact", a
first-class outcome (§5.1), never driven harder. Until 2026-08-28 these
three were constants inside the driver (1000 steps, 5 chunks, 500
chunks); §1.4 says nothing that shapes a run may hide there.

The press then holds at temperature for a specified duration — the hold
is where bonding actually happens — and the structure is relaxed to
define the reference state of §5.3.

### 5.3 The equilibrated zero-load reference state

The pull's force-versus-displacement curve has to start somewhere, and
that somewhere must be a state at rest under no applied load. Prior art
minimizes, re-creates thermal velocities, and begins pulling at once;
its potential energy jumps by 481 eV in the first half picosecond, and
its first genuine force sample already reads −47 eV/Å at five hundredths
of an ångström of displacement. It integrates from a stressed state and
subtracts no baseline.

SABSIM makes the reference state a gated artifact: **release the press
load first** — remove the drive, and in load-controlled mode re-freeze
the driven grip that was given mass in §5.2, so nothing is still pressing
the interface — then minimize, then equilibrate under the thermostat for
`settle_duration` (a numerical knob of `sabsim.toml`, revised
2026-08-28; until then a constant of twenty chunks inside the driver),
reading the two grip reactions and the potential energy back every
`control_interval`, then **assert** two things. First, that the net
force on the grips — the sum of the two reactions, which Newton's third
law says cancels at rest — is ZERO in the statistical sense §5.5 already
uses for the pull's returned force: its mean over the settle lies within
two standard errors of zero, with the configured `noise_floor` as the
floor beneath that test for a noiseless record. (Revised 2026-08-28,
Paul: the earlier fixed test, mean force below `noise_floor`, judged a
visibly settled 252-atom demo unsettled at 0.05 eV/Å against a thermal
scatter several times that — LEDGER T-32; a criterion that calibrates
itself to the noise the system actually has replaces it, and the same
criterion now serves both places a force must be zero.) Second, that
the potential energy has stopped drifting (`reference_pe_drift`). If
either fails, the press did not settle, and that is reported rather
than integrated over. Releasing the load is not a detail: equilibrating while
the press drive is still live would settle a *loaded* state and the
zero-load gate would pass a state that is not at zero load. The settled
state is written to a file, because the pull restores from it on a fresh
instance (§5.4); handing the pull the original pre-press structure
instead would silently throw the press away.

### 5.4 The pull

The bottom grip is held, the top grip is displaced at a constant rate,
and the reaction force is recorded. The grips are carved by the driver
from §2's z-ranges plus a single region-geometry setting (option C, §2.6),
not from a hardcoded per-material layer thickness.

**Both reaction forces are recorded, and their sum is a free correctness
check.** Newton's third law requires the forces on the two grips to
cancel; a drift in the sum means momentum is leaking into the
thermostat or the boundary. In LAMMPS the total force on a held group is
available from the holding fix's own output, which records the sum
*before* zeroing it — so the check costs nothing. Prior art holds its
bottom grip with `fix setforce`, never queries that output, and so
throws the check away.

**Force is time-averaged, and the average's warm-up is discarded.** The
instantaneous force at temperature is noisy, and sparse instantaneous
sampling aliases that noise into the work integral. (Prior art's stated
reason for averaging — that otherwise "the ± thermal noise cancels and
the work of adhesion comes out ~0" — is backwards: cancellation of
zero-mean noise is exactly what an integral should do. The remedy is
right, the reasoning is not.) The averaging window is chosen in units of
**grip displacement**, small compared with a bond length, rather than in
timesteps. Critically, an averaging fix emits zero before its first
window closes; that leading zero is discarded, not recorded. In prior
art it survives as the first point of `debond.dat`, anchoring both the
first trapezoid of the work integral and the three-point line fit that
its "Young's modulus of 181.09 GPa" comes from.

**The peak force is extracted, not selected.** Taking `max()` over a
noisy sample is not a measurement. Prior art's two reported strengths
are both artifacts of doing exactly that: one is the most negative
thermal fluctuation in the first 1.5 ps of a pull whose neighbouring
samples read −36, +38, +3, +21, −30 eV/Å, and the other is the crest of
an unequilibrated loading transient. SABSIM takes the peak from the
averaged curve, after the reference state of §5.3 has certified that no
transient is present, and requires it to stand above the noise floor by
a stated margin; a peak that does not is reported as unresolved.

**The pull-rate ladder is mandatory, and it is physics.** Molecular
dynamics pulls roughly eight orders of magnitude faster than any
experiment, so rate dependence is not a nuisance to be frozen away. It
is also exactly what distinguishes the two entries of the STRUCTURAL 2
measure vector: the **mechanical** work of separation is rate-dependent
because dissipation is, while the **thermodynamic** work of adhesion is
not. Running several rates therefore buys a real internal test — as the
rate falls, the mechanical integral must approach the quasi-static
thermodynamic value from above, never cross below it. v1 runs at least
three rates spanning a decade and reports each measure's rate trend.

**Every number carries an ensemble.** The interface is a disordered
amorphous contact, so the measures are averaged over amorphization
realizations (STRUCTURAL 4) and over thermal-velocity seeds, and
reported as a mean with a spread. Prior art runs one fixed seed, once,
and quotes 3.746 J/m² with no uncertainty at all.

### 5.5 What the pull hands to the analyzer

**Separation is not grip displacement.** The grip moves through the
elastic stretch of both slabs before the interface opens at all, so a
work integral taken over grip displacement contains stored elastic
energy that never belonged to the interface. Prior art defines
separation as the top grip's center-of-mass displacement across a 51.6 Å
bilayer and calls the resulting integral a work of adhesion. Step 7
therefore emits **two curves**:

- force versus **grip displacement** — what a testing machine measures,
  and the quantity the mechanical work integral is taken over;
- force versus **interface opening** — the distance between the two
  slabs' density-profile dividing surfaces (§2.6), which is where the
  interface actually is.

**Complete separation** is declared when the interface opening exceeds
the potential's cutoff (6.0 Å for `se_e2_a`, §4.6) *and* NO BONDED PAIR
STILL STRADDLES THE INTERFACE PLANE — no two atoms within a bond length
of each other sit on opposite sides of it. Both the opening and the
plane are the geometric ones of §2.6 (revised 2026-08-30 (Paul), after
LEDGER T-40): found in the whole system's density profile, never by
which wafer an atom was built in, because a pull transfers material
between the faces and a label-based surface then sits on the
transferred layer and never sees the gap. The mechanical work integral
runs from the §5.3 reference state to that point and stops; prior art
integrates the entire record, noise tail included.

**The press hands over a stage ledger too (revised 2026-08-28 (Paul)).**
Alongside the curves, the bond stage records the MD step at which each
of its phases began and ended — press drive on, contact declared, hold
ended, settle began, settle ended — so any consumer of the recorded
trajectory (the analyzer, a viewer, the bootstrap harvest of §4.8) can
say which phase a frame belongs to by its step, instead of guessing
from its position in the file.

**Why bridging and not "the force has fallen to zero".** The obvious
test — keep integrating until the pulling force dies away — was tried
first, and it measures the wrong thing. Two rough surfaces do not let
go everywhere at once. In scattered places atoms stay attached to both
sides, and as the wafers move apart those places draw out into thin
STRANDS of silicon spanning the gap. A strand transmits force long
after the faces themselves are beyond each other's reach, so waiting
for zero force means waiting for the last strand to snap.

Measured on the v1 Si/Si pair, that is not a small correction. The two
faces passed out of range of one another after 10 Å of pulling; the
force did not go quiet until 25 Å; and **half of the total reported
work accrued in between**, carried by about ONE PERCENT of the atoms
(roughly 80 of 8799). Dividing that by the full nominal contact area
reports a few accidental filaments as though the whole interface had
done the work.

Three things make that unacceptable rather than merely imprecise. The
number stops being a property of the INTERFACE and becomes a property
of where a few dozen atoms happened to be standing. It is not
reproducible, since a different thermal seed draws a different web —
so a large part of the answer is a dice roll reported with the same
confidence as the rest. And it is the regime our potentials describe
WORST: a stretched, low-coordination chain is the furthest thing from
the four-coordinated bulk silicon a bulk-trained model is fitted to, and
this family of model is independently known to draw silicon out where
the real material would snap.

Bridging asks the question the measure actually means: has the
interface come apart? It is also the quantity §8 already uses to define
bonding (cross-interface bond density), so the pull stops on the same
notion of "joined" that the bond metric is built from. The bridging
count is REPORTED alongside the work, so a result that stopped with
material still spanning the gap declares itself instead of hiding.

**A NOTE ON THE FORCE, kept because it was learned the hard way.** The
force is no longer part of the separation criterion, but anyone who
reintroduces a force test needs this. The
grip reaction is a sum over every atom in the grip, and at 300 K that
sum fluctuates hard: measured on a fully separated Si/Si pair — the two
slabs 40 Å apart with nothing whatever between them — it swings across
±20 eV/Å with a standard deviation near 7 eV/Å. Testing such a quantity
against a small fixed constant asks the wrong question. The first full
end-to-end run compared it against a 0.05 eV/Å floor, roughly a
hundredth of the noise, and so reported that a pair which had visibly
come apart had never separated, at every rate in the sweep.

The right question is whether the force is DISTINGUISHABLE from zero
given its own scatter. So the test is on the mean and its uncertainty:
the averaged force counts as returned to zero when its magnitude falls
within a small number of standard errors of zero (v1: two). On the same
separated pair the windowed mean is +0.54 eV/Å against a standard error
of 0.50 — about one standard error out, comfortably zero — while the
still-bonded state earlier in the same pull sits at −1.62 eV/Å and is
not. The criterion therefore calibrates itself to the noise the system
actually has, instead of to a constant that has to be re-guessed for
every grip size, temperature, and interface area.

The configured `noise_floor` stays as a FLOOR beneath that test, for the
degenerate case of a noiseless or near-noiseless record (a quasi-static
mock, a zero-temperature run) where the standard error collapses toward
zero and would otherwise demand impossible exactness.

**The dissipation identity is a sign check.** Step 7 also records the
potential energy of the bonded relaxed state and of the fully separated,
relaxed slabs. Their difference is the thermodynamic work of adhesion at
MLIP fidelity, which §6 computes properly; the mechanical integral minus
that difference is the energy dissipated. STRUCTURAL 2 predicts the
mechanical work is the larger. If it comes out smaller, the reference
state or the integral is wrong, and the run is rejected rather than
reported.

### 5.6 The box, the boundary, and the run that has to finish

The lateral cell is the shared coincidence cell of §2, taken to its
zero-in-plane-stress size by a **one-time combined-cell relaxation** run
ONCE at the joint heal (§2.6, §3.4) — a single `fix box/relax x 0 y 0`
plus minimize on the assembled pair — whose result is **recorded** (the
relaxed cell, and the per-slab strains it implies) and then **held
fixed** for the whole press, settle, and pull. The distinction that
matters is *when*. A live lateral barostat running **during** the press
is forbidden: the cell would drift as the measurement proceeds, the
per-unit-area denominator would move mid-run, and the recorded substrate
strain would relax away — the provenance number becomes a fiction. The
one-time relaxation instead moves the box **once, before** the
measurement, writes down where it landed, and freezes it; the
measurement then runs on a fixed, recorded cell. This is also why the
assembled pair does not detonate at contact: T-17 (job 16453628) showed
the dominant frame-0 stress is the cell sitting off the potential's
preferred lattice (~7–8 GPa per material), which the combined relax
drives to ~0 with a sub-0.3% box change, the relaxed cell staying
ordered. The z-boundary is non-periodic, with vacuum sized for the full
pull distance plus margin.

Two things are then gates rather than warnings. **Atom count is
conserved**: a non-periodic boundary silently deletes any atom that
leaves the box, so a lost atom invalidates the run. And **the trajectory
must be complete**: the requested walltime must cover the whole pull — a
number the *person* sets, estimated from pull distance divided by pull
rate (§10.6), not a flat four hours — and it is this completeness gate,
not the scheduler's clock, that certifies the run finished. A run cut
short is resubmitted as a continuation (§10.6), never reported as-is.
Prior art's headline number was computed from a trajectory that stopped
at 122,500 of 150,000 steps, in a directory containing a file named
`NOTE_INCOMPLETE.txt`.

### 5.7 Provenance is part of the measurement

Every number this stage emits names the potential generation that
produced it, the seed set, the pull rate, the press mode and the load or
depth reached, and the trajectory file it was reduced from
(`VISION.md` goal 3). The analyzer **refuses a truncated trajectory**.
The stage ledger of §5.5 rides the same result manifest as the curves,
so the phase boundaries of a run are part of its permanent record.

**The analyzer is handed its input; it does not go looking for one.**
Prior art's strength analysis fetches "the newest `debond.dat` under the
job root," so it silently analyzed the *eight-layer* run while the
adhesion analysis beside it analyzed the *four-layer* run — and both
stamped the same interface area, which is identical between the two and
therefore hides the swap. That is the whole of the "15.3 versus 1.1 GPa"
disagreement: not physics, but a newest-file-wins rule. A SABSIM
analyzer takes an explicit trajectory identifier and refuses to guess.

**A detected defect must gate, not decorate.** Prior art's own bond
analyzer already prints a warning that the impact left "crushed cross
contacts <1.0 Ang (over-aggressive impact; a debond strength from this
run will read high)." The strength is then computed and reported anyway.
Every check SABSIM's protocol performs either stops the run or is not
worth performing.

Together with the truncated trajectory and the hardcoded string
declaring a 0.5 eV Morse well where the code applied 1.0 eV, the numbers
are not so much wrong as **unreconstructable**, which is worse: nothing
in the tree lets a reader determine which structure, which potential, or
which trajectory produced the headline figure.

### 5.8 A note on where prior art's design was right

The failures above are failures of *implementation*, and it is worth
saying so plainly, because prior art's own `DESIGN.md` specifies much of
what this section arrives at independently. It calls for gap closure at
0.01–0.1 Å/ps with **contact detection**, a **constant-normal-pressure
barostat** for the bonding hold, a hold measured in nanoseconds, and an
adhesion energy defined as **(E_bonded − E_separated) / area** — a
thermodynamic energy difference, not a force integral.

None of that was built. The code performs a 1.5 Å/ps velocity impact, a
50 ps constant-volume hold, no contact detection, no barostat, and
reduces a force integral instead. So the divergence is not that its
author designed the wrong protocol; it is that the design and the code
parted company and nothing detected it. The pressure-controlled press
this section freezes for v1 is, in essence, the protocol prior art
specified and never ran — and its energy-difference adhesion is the
thermodynamic entry of the §6 measure vector.

That is also the sharpest argument for our own document chain: a design
that no test binds to its code will drift, and the drift will not
announce itself. It surfaces as a number quoted to four significant
figures.

### 5.9 What we keep, what we replace, and v1

**Keep:** the three-phase arc (approach, hold at temperature, pull); the
reaction-force-on-the-grip measurement; time-averaging that force; the
non-periodic z-boundary; and the eV/Å² → J/m² conversion
(1 eV/Å² = 16.0218 J/m², 1 eV/Å³ = 160.2176 GPa).

**Replace:** the placeholder cross-interface Morse well (→ the trained
MLIP; no cross-term exists); per-slab element charges that give the same
element two identities (→ one species map, STRUCTURAL 1a); velocity
impact (→ a load- or displacement-controlled press); a thermostat that
counts directed motion as heat (→ interior-only, bias-removed); pulling
from an unequilibrated, pre-stressed state (→ the gated zero-load
reference); the averaging fix's leading zero (→ discarded); separation
as grip displacement (→ also as interface opening); the mechanical
integral labelled "work of adhesion" (→ the measure vector of §6, with
the dissipation identity as a sign check); a single seed and no error bar
(→ an ensemble with a spread); a single unvalidated pull rate (→ the rate
ladder); a discarded bottom-grip reaction force (→ the Newton check); a
flat walltime and a truncated trajectory (→ a person-set walltime sized
to the pull, §10.6, and a completeness gate); and a report string that
names a potential the run
did not use (→ provenance emitted from the run, not typed).

**Frozen for v1:** load-controlled press to a **target pressure of
~1 MPa** (ratified 2026-07-13 — Si wafers bond near 0.8 MPa and contact
loads sit below ~1.6 MPa), with one displacement-controlled cross-check
on the Si/Si reference; **press/hold temperature 300 K** (SAB is a
room-temperature process, fixed by VISION); a single depth allowance;
**hold duration ~100–200 ps** (a convergence-tested MD quantity, not a
match to the experimental ~300 s, which is inaccessible); a **pull-rate
ladder of {1, 3.2, 10} m/s** (three rungs, one decade, log-spaced —
§5.4 wants ≥3 rates over a decade, and slower is better but cost-bounded,
with M3 reporting the distance to quasi-static); bonded/not-bonded plus
contact quality always reported. Pressure, temperature, hold, and the
rate ladder are v1 defaults, not freezes — each is a `sabsim.toml` knob.
Still DESIGN follow-ons: the noise-floor thresholds for the reference
state and for "force returned to zero," and the contact-quality
definition's bond-counting cutoff.

## 6. Bond-outcome analyzer and measures

This section designs the module that turns what step 7 emits into the
numbers the gate reads. It realizes STRUCTURAL 2: the outcome of a bond
is not a number but a **measure vector**, whose entries are expected to
disagree, and whose disagreements are themselves observables.

Unlike §2, §3 and §5, this section inherits essentially nothing.
`PRIOR_ART.md` §1.8 records why: prior art's measurement layer has no
usable definition of the work of adhesion (the one its PSEUDOCODE
specifies has its sign reversed and is measured across the press), emits
only human-readable prose, carries no uncertainty and no provenance, and
contains no check that can fail. That absence is clarifying. There is no
tempting-but-broken definition to argue with, so §6 is written from
first principles on the endpoints §5 already produces.

### 6.1 Why a vector, and why its entries must not agree

A single "adhesion energy" would have to be either the energy actually
spent pulling the interface apart, or the energy stored in the bond
itself. These are not the same quantity, and forcing them into one
number destroys the information in their difference. So the analyzer
reports several measures side by side, each with its own definition,
fidelity, and uncertainty, and treats the **gaps between them as data**:
the gap between mechanical and thermodynamic work is dissipation, and
the gap between the potential's answer and an all-electron answer is the
interface-fidelity signal STRUCTURAL 3 needs.

### 6.2 Species is not provenance

Before any measure can be defined, one confusion has to be removed.
Prior art stores "oxygen that began in the silica slab" and "oxygen that
began in the lithium-niobate slab" as two different **atom types**, and
then uses that type both to assign the potential and to decide which
side of the interface an atom is on. Both uses are wrong, and they are
wrong in opposite directions.

SABSIM separates the two ideas explicitly. Every atom carries:

- a **species**, from the single global element map of §4.3 — this is
  chemistry, it is what the potential sees, and there is exactly one
  oxygen (STRUCTURAL 1a);
- a **provenance label**, a per-atom field of §2's structure contract —
  this records which slab the atom was built in, it is bookkeeping, and
  the potential never sees it.

A bond is **cross-interface** when its two atoms carry different
provenance labels. An atom that migrated across during pressing keeps
its original provenance label, which is what makes **atom transfer**
measurable at all: the transferred atoms are exactly those whose
provenance disagrees with the fragment they end up in. Prior art cannot
express this, because it has one field doing both jobs.

**The interface itself admits more than one definition.** The rule just
given — cross-interface means differing provenance — is the one SABSIM
uses by default, because it is always well defined, it costs nothing, and
it is the only definition under which atom transfer is even expressible.
It has one honest limitation: an atom that migrates into the other
material and becomes fully integrated there still carries its original
provenance, so its new, strong, bulk-like bonds are all counted as
cross-interface even though they are no longer the weld that holds the
two wafers together.

A second definition removes that limitation at the cost of uniqueness.
Take the **interface to be the surface of minimal bond strength** — the
weakest cross-section separating the two wafers, which is also the
surface along which a pull would actually break the system. A bond is
cross-interface when it lies on that surface. This routes the boundary
*around* a truly integrated transferred atom, placing it on the side it
is now bonded into, so only the genuinely weak welds are counted. Its
price is that "bond strength" can be measured several ways — a pair
energy, a force to break, an electronic bond order, or a geometric depth
in the coordination shell — and these need not put the surface in the
same place, so this is a *family* of definitions rather than one. SABSIM
does not expect a perfect definition to exist. The two families are kept
as alternatives — the analyzer is a registry (§6.7) — and where both are
computed their **disagreement is itself the observable**: it measures how
much true transfer and integration occurred, exactly the §6.1 stance that
a gap between two honest measures is data, not error. The dynamic pull of
§5 realizes the minimal-strength surface after the fact — it separates
the system at its weakest cut — so the post-fracture pieces M2 already
finds by connectivity (§6.4) are that surface as the run actually
produced it.

### 6.3 Bond cutoffs are derived, not chosen

Whether two atoms are bonded is decided by a distance cutoff, and prior
art carries five unrelated ones — 1.0, 2.5, 2.6, 3.0 and 3.2 Å — in a
single file, applied to element pairs whose real bond lengths differ by
half an ångström.

SABSIM derives the cutoff for each unordered species pair from the
**first minimum of that pair's partial radial distribution function**,
computed on the structure being analyzed. That minimum is the natural
boundary between the first coordination shell and the second; it is what
"bonded" means. The machinery already exists — §3.5 computes partial
g(r) with the density-reference normalization, and prior art even has a
first-peak finder it never applies here. Each derived cutoff is written
into the output record. Where the minimum is not resolved (too few
pairs, a liquid-like g(r)), the measure that depends on it is marked
**unresolved** rather than silently falling back to a constant.

### 6.4 The measures

**M1 — Mechanical work of separation.** The integral of the resisting
force over grip displacement, from §5.3's equilibrated zero-load
reference state to complete separation, divided by the interface area of
§2's shared cell. This is the headline, it needs no all-electron code,
and it is always available (`VISION.md` goal 4). It is **dissipative and
rate-dependent** by construction, so it is reported once per rate on the
§5.4 ladder.

**M2 — Thermodynamic work of adhesion at MLIP fidelity.** The energy
cost of ending with two separate pieces instead of one bonded system:

```
work_of_adhesion = (energy_of_piece_one + energy_of_piece_two
                    - energy_of_bonded_system) / interface_area
```

The bonded energy is unambiguous. The pieces are not, because a real
amorphous interface does not come apart along the seam it was built on.
The two pieces are identified by **bonded-cluster connectivity** — the
same kernel §2.6 uses to strip ejecta — and each is held at the shared
lateral cell. SABSIM then reports **two** named measures, because they
answer two different questions:

- `work_of_adhesion_as_fractured` — each piece relaxed only into its
  nearest energy minimum, surfaces left damaged, exactly as the pull
  left them. This is the reference **matched to M1**: the two numbers
  describe the same physical endpoint, so their difference is the
  dissipation and nothing else.
- `work_of_adhesion_relaxed` — each piece additionally annealed so its
  surface atoms rearrange and dangling bonds find partners. This is the
  reference that connects to experiment and to the surface-energy
  relation `W = γ_A + γ_B − γ_AB`, in which the surface energies are
  defined for equilibrium surfaces.

The relaxed pieces have lower energy, so `work_of_adhesion_relaxed` is
the smaller number, and the difference is reported as its own measure,
`surface_healing_energy`. Two honesties are recorded with it: an
amorphous surface is kinetically trapped, so "relaxed" means only "as
relaxed as this annealing schedule achieved," making that schedule a
recorded knob; and the two pieces need not have the composition of the
two original slabs, so `transferred_atom_count` is recorded beside them.

Each of M2's entries is reported **twice**: as a
`potential_energy_difference` at zero temperature — cheap, reproducible,
and directly comparable with the all-electron cross-check of M4, which
is also a zero-temperature quantity — and as a `free_energy_correction`
estimating the vibrational and entropic contribution at the press
temperature. The first is the headline; the second is what makes it a
free energy, and it is priced honestly: it needs a phonon calculation
per endpoint, so its ensemble may be smaller than M1's.

**M3 — The quasi-static separation curve.** M1's rate ladder needs
something to extrapolate *toward*. That target is a reversible curve,
obtained by imposing a sequence of prescribed interface openings and
minimizing at each — a rate-free ladder of constrained relaxations, not
a trajectory. Its integral is the primary quasi-static number.

Separately, and nearly for free, the frames of the §5 dynamic pull are
each minimized and their energies recorded. This second curve carries
the pull's history, so it is **not** reversible and its openings are
unevenly spaced; it is not a substitute. Its value is the comparison:
the gap between the relaxed-snapshot curve and the constrained-ladder
curve measures directly how far the chosen pull rate sits from
quasi-static, which is the assumption the whole rate ladder rests on.

**M4 — Work of adhesion at all-electron fidelity.** The same energy
difference as M2, evaluated with an all-electron method rather than the
potential: VASP on an interface subcell now, as the always-available
backstop, and Imago at scale once the cross-project deliverables
land (`ARCHITECTURE.md` §4).

The comparison has to be set up carefully, because the obvious version
of it does not work. M4 is affordable only on a subcell, while M2 is
defined on the full system. Subtracting one from the other would mix the
difference we want — how far the potential sits from all-electron
physics — with one we do not: how far a small box sits from a large one.
Two methods, two systems, one number, and nothing left to say which
difference produced it. So the analyzer forms **two** differences:

- **`interface_fidelity`** — M4 minus M2 recomputed on the **same
  subcell**. Two methods, one system. This is STRUCTURAL 3's signal, the
  one that catches a potential which is confidently wrong exactly where
  the bond number is read. Its all-electron side inherits the **recipe's
  production settings block** (§4.8), the very settings that produced the
  training labels, so what the difference reports is the potential's
  learning error and nothing else. This is the comparison the inheritance
  rule matters most for: it is a difference of two methods by
  construction, so a settings mismatch would masquerade as physics
  without ever failing visibly. Note that the subcell is much larger
  than a typical training configuration, which is exactly why §4.8
  requires the reciprocal-space entry to be a spacing rule rather than a
  fixed mesh — a fixed mesh could not serve both cell sizes honestly.
- **`subcell_truncation_error`** — M2 on the full cell minus M2 on the
  subcell. One method, two systems. This is what the truncation cost us,
  and it is **cheap**: both terms come from the potential, so no
  all-electron calculation is involved at all.

The second measure exists to gate the first. If shrinking the cell moved
the answer by as much as the fidelity difference we are trying to read,
then the fidelity question was never askable on that subcell, and
`interface_fidelity` is reported `unresolved` rather than believed.

**What an interface subcell is.** The potential is short-ranged — the
`se_e2_a` descriptor with a 6 Å cutoff (§4.6) — so an atom's energy and
force depend only on what lies within that radius of it. The physics we
are training and testing is local, and that locality is what makes a
smaller cell legitimate at all. But it cannot be exploited by cutting
atoms out: a cut surface carries dangling bonds, and the forces near it
are wrong in precisely the region we were trying to look at. Saturating
those bonds — with hydrogen, say — would introduce a species the global
type map of §4.3 does not contain, and a termination scheme we would
then have to validate on a covalent-ionic interface.

So the subcell is **not a carved cluster.** It is a legitimate physical
system in its own right, built by four rules:

- the **full lateral periodicity** of §2's shared cell is kept, untouched;
- the cell is truncated **only along the interface normal**;
- every atom whose label will be used keeps its **entire 6 Å
  environment**;
- truncation stops at the slab's **own real free surfaces**, so no
  surface is manufactured and no bond is severed.

The material that actually gets removed comes only from the **undamaged
crystalline buffer** inside each slab — never from the activated skin,
never from the interface, never from the outer free surface. That buffer
is a stack of identical repeating crystal layers, so removing a *whole
number* of them and closing the gap leaves the two faces that now meet
lined up exactly as they were in the uninterrupted crystal: no gap, no
strain, no atom short a neighbour, and a join indistinguishable from
bulk. This **quantizes the thinning** — only whole-layer steps keep the
join seamless — which is the concrete mechanism behind the promise that
no surface is manufactured and no bond is severed.

It is a thinner version of the same interface, and its energies and
forces are correct without qualification. Atoms near the outer surfaces
sit in different environments than they would in the production cell,
but those environments are physical too — so their labels are data, not
contamination. Where along the interface the subcell is centered is
decided by the per-atom committee spread (§7.3), which is the quantity
that localizes the potential's ignorance.

**Its size is a convergence test, not a constant.** Evaluate the target
quantity with the *potential* on the full cell and on the subcell, and
enlarge the subcell until the difference falls below tolerance. Because
the thinning is quantized, "enlarge" means **add back one whole crystal
layer** to the buffer: the test walks a discrete ladder of whole-layer
thicknesses, not a continuous size, and stops at the first rung whose
difference clears tolerance. That difference is
`subcell_truncation_error`; it needs no all-electron
calculation; and it means **the cheap method certifies the expensive
method's input.** This is why the truncation error is a reported measure
rather than an internal detail, and why `TODO.md`'s long-standing "VASP
interface-subcell size" item is answered by a procedure instead of by a
number.

**M5 — Bond descriptors, geometric and electronic, kept apart.** Two
families, and they must never share a name:

- **Geometric** — coordination number, cross-interface bond count per
  unit area, and contact-area fraction. These come from positions and
  the derived cutoffs of §6.3, cost nothing, and are computed along the
  whole trajectory. `contact_area_fraction` and the bond count are the
  graded contact-quality measure §5.1 requires. A further geometric
  output is the **partial radial distribution function of the
  surface-region atoms, tracked across named stages** of the pipeline —
  pristine, activated, pressed-and-bonded, separated-as-fractured, and
  separated-relaxed. It is the same partial-g(r) kernel §3.5 already
  runs, reused here not to derive a cutoff but to show how the interface
  structure evolves. It is kept as a **curve for a human to read**, not
  reduced to a scalar (see the note below and §6.6).
- **Electronic** — effective charge (Q\*) and bond order, from Imago on
  the snapshots §8 selects, with endpoints relaxed first. These are
  properties of the electron density, not of the neighbour list. To
  these we add the **total and partial density of states**, a signature
  Imago output (with VASP as the backstop, §8): the partial DOS on the
  interfacial atoms is among the sharpest bonding diagnostics there is,
  showing dangling-bond gap states in a poorly healed interface and the
  bonding states that form as two surfaces join. Like the RDF it is kept
  as a **curve for a human to read**; the only scalars extracted from it
  are the **density of states at the Fermi energy** and the **gap size**.

Prior art names a geometric neighbour count "bond order." A reader
comparing that against an electronic bond order would be comparing
unlike things with no warning. The distinction is preserved in the
names, and the schema records which family each measure belongs to.

**Defining `contact_area_fraction`.** Overlay the shared lateral cell
(§2) with an **equal-area grid in fractional coordinates** — equal-area
so a triclinic cell needs no special case — and mark a grid cell as *in
contact* when it holds the **midpoint of a cross-interface bond** (§6.2:
two atoms of differing provenance within the derived cutoff). The
fraction is the number of contacting cells over the total. This measures
**bonded** contact — the plane fraction actually welded — not mere
geometric proximity, which is the right quantity for a bond study and
keeps it consistent with the cross-interface bond definition. It
complements the cross-interface bond *count*: the count is how many
welds, the fraction is how spread out they are, so a few strong local
welds and a uniform weak contact are told apart. Its one knob is the
grid spacing, set near the mean cross-interface cutoff — about one
contact's lateral footprint per cell — and recorded; like the subcell
size it should be checked for insensitivity over a range rather than
trusted at a single value.

The RDF and the DOS are the analyzer's first **spectra** — curves over a
coordinate (a separation, or an energy) rather than single numbers. They
are handled the way §5 already handles a force curve: stored by
reference as artifacts for a human to read, with only named scalars, if
any, entering the measure vector (§6.6). At this stage that means the
RDF contributes no automated scalar at all, and the DOS contributes only
its Fermi-energy value and its gap size. Reducing them further is a
later choice, not a design commitment now.

### 6.5 The inequality chain, and the checks it buys

The measures are ordered by physics, and each ordering is a test the
analyzer runs before it reports anything:

```
M1(rate) >= work_of_adhesion_as_fractured >= work_of_adhesion_relaxed
```

- **Dissipation is non-negative.** `M1 − work_of_adhesion_as_fractured`
  is the energy dissipated in the pull. If it comes out negative, the
  reference state or the integral is wrong, and the run is rejected
  rather than reported (§5.5).
- **Healing energy is non-negative.** `work_of_adhesion_as_fractured −
  work_of_adhesion_relaxed` is the energy released as the damaged
  surfaces reorganize. A negative value means the anneal did not relax.
- **The rate ladder converges from above.** As the pull rate falls, M1
  must decrease monotonically toward the as-fractured value. Both the
  monotonicity and the limit are checked; a ladder that rises with
  falling rate indicates the pull is not yet in the dissipative regime.
- **The quasi-static ladder closes.** Because M3's ladder is a sequence
  of minimizations, the work computed by integrating its force must
  equal the difference of its endpoint energies. This tests the
  integrator independently of the physics — the single check that would
  have caught prior art's leading-zero artifact and its truncated
  trajectory at once.
- **The subcell was large enough to ask the question.**
  `subcell_truncation_error` must be small compared with the
  `interface_fidelity` difference it gates (§6.4). Where it is not, the
  fidelity measure is reported `unresolved` and never `pass`, because at
  that point a box-size artifact and a potential error are
  indistinguishable.

These are cheap, they use only quantities already computed, and none of
them exists in prior art, whose analyzer contains no check that can fail.

### 6.6 The measure-vector schema

**A gate cannot consume prose.** Every result prior art emits is a
`.txt` file with `#`-prefixed English headers; nothing downstream can
read them, which is precisely how a truncated trajectory and a
wrong-file fetch survived into a quoted result. The schema below is
therefore not bookkeeping — it is what makes §7 possible at all.

The analyzer emits one machine-readable document per pair, containing:

- **Provenance** (`VISION.md` goal 3): the potential generation and
  committee size, the seed set, the press mode with the load and depth
  reached, the pull rate, the structure and trajectory identifiers, and
  the version of every code involved.
- **Geometry:** the shared lateral cell from §2, the interface area and
  the rule used to compute it, and the derived bond cutoffs of §6.3.
- **Measures:** a list of records, each carrying `name`, `value`,
  `uncertainty`, `realization_count`, `units`, `fidelity` (geometric,
  electronic, MLIP, or all-electron), `method`, the inputs it was
  computed from, and a `status` of `ok`, `unresolved`, or `rejected`.
- **Verdicts:** the bonded / not-bonded outcome of §5.1 and the graded
  contact quality behind it.
- **Checks:** the outcome of every test in §6.5, plus §5's Newton
  residual, atom-count conservation, and trajectory completeness.

Four rules govern it. **No bare numbers**: a value without an
uncertainty and a realization count is not a measure. **The gate reads
by name and status**, never by position, so adding a measure cannot
silently shift the meaning of another. And **units are explicit and
carried**, with both the native `eV/Å²` and the SI `J/m²` recorded along
with the conversion used (1 eV/Å² = 16.0218 J/m²; 1 eV/Å³ = 160.2176
GPa), so no reader has to trust a factor typed into a report string.

The fourth rule covers **spectra**. A radial distribution function or a
density of states is a curve, not a scalar, and the record above is
built for scalars — a `value` with an `uncertainty`. So a spectrum is
stored **by reference as an artifact**, exactly as the large trajectory
frames are (§5.5), and it is meant primarily for a human to read. Only a
scalar *extracted* from a spectrum enters the measure vector as a record.
At this time SABSIM extracts none from the RDF and only two from the DOS
— the density of states at the Fermi energy and the gap size — because
automating a fuller reduction is not yet worth its cost. Adding an
extracted scalar later is a §6.7 registration, not a schema change.

### 6.7 The analyzer is a registry of measures

Each measure declares what it needs — the bonded structure, the
separated fragments, a force curve, a snapshot series — and emits
records. The analyzer resolves those needs against what the pair
produced, computes what it can, and marks the rest `unresolved`. This is
what makes the measure vector **pluggable** (`ARCHITECTURE.md` §2.3):
adding an Imago descriptor, or a second all-electron reference, is
registering a measure, not editing the gate.

It also makes the Imago-free path a first-class configuration rather
than a degraded one. If Imago is not ready, M5's electronic family and
M4's Imago variant come back `unresolved`, M1 and M2 and the VASP
backstop still report, and the gate still runs — which is exactly the
schedule insurance `VISION.md` goal 4 asks for.

### 6.8 What we keep, what we replace, and v1

**Keep:** almost nothing from prior art's analyzer — only the correct
triclinic in-plane area (for box vectors `a = (lx, 0, 0)` and
`b = (xy, ly, 0)` the area is `lx * ly` independent of tilt), its proper
minimum-image displacement routine, and the unit conversions.

**Replace:** the sign-reversed, press-spanning energy difference (→ M2
on relaxed endpoints, two references); coordination named "bond order"
(→ geometric and electronic families kept nominally apart); five
hardcoded cutoffs (→ one derived per species pair from the partial
g(r) first minimum); the bond-length distribution built from each
cation's *nearest* neighbour only (→ all bonds within the derived
cutoff); species-agnostic pair counting in a 7 Å window around the
highest atom (→ cross-interface bonds by provenance label and chemistry);
structure comparison by positional index with no minimum image (→ by
atom identity, minimum-image throughout); a bonded verdict and a crush
flag that are printed and discarded (→ first-class records the gate
reads); prose reports (→ the machine-readable schema); and numbers
without uncertainty or provenance (→ neither is optional).

**Frozen for v1:** the Imago-free set is mandatory — M1 on the rate
ladder, M2's two references with the healing energy and the transferred
atom count, M3's constrained ladder with the relaxed-snapshot
comparison, M5's geometric family, the contact-quality measure, and
every check of §6.5. M2's zero-temperature energy difference is the
headline, with the free-energy correction reported as a separate entry
on a possibly smaller ensemble. M4 uses the VASP subcell backstop, and
reports `interface_fidelity` and `subcell_truncation_error` together —
never the first without the second. The Imago variant and M5's
electronic family are registered but may report `unresolved`. Still
DESIGN follow-ons: the annealing schedule behind
`work_of_adhesion_relaxed`, the constrained-ladder opening spacing, the
free-energy estimator, the tolerance at which the interface subcell is
declared converged (its *size* is now the outcome of a convergence test,
not a constant to be chosen), and the numeric tolerances on every check
in §6.5.

## 7. Quality gates and diagnosis

This section designs the two checks that decide whether a pair is
worth believing, and the reasoning that turns a bad number into an
instruction
about what to do next. It realizes STRUCTURAL 3.

It is the first section whose inputs are entirely our own. §6 hands it a
measure vector; §5 hands it a trajectory and the records taken along it;
§4 hands it a committee of potentials that can say when it is guessing.
From prior art it inherits nothing at all, for the reason `PRIOR_ART.md`
§1.8 records plainly: **nothing in that analyzer can fail.** Its nine
warnings are bare `print` statements, its bonded verdict is computed and
discarded, and its amorphization check reports a number against no
threshold. A gate is exactly the thing that codebase does not have.

### 7.1 Two checks that differ in remedy, not in strictness

The two checks are often collapsed into one "quality gate." They must
stay apart, and the reason is not tidiness — it is that **they lead to
different actions**:

- The **potential-quality gate** asks whether the trained potential is a
  good model of these materials. A failure is a *model* problem, and the
  remedy is to generate more training data and retrain.
- The **bond-outcome gate** asks whether the work of separation is
  physically sensible. A failure may be a *protocol* problem — the
  activation, the press, the pull — which no quantity of training data
  will ever fix.

From this a second, sharper point follows, and it governs the whole
section. **A bad bond number carries no meaning on its own.** Until the
potential gate has been read, the bond number is a measurement made with
an uncalibrated instrument, and asking what it says about the protocol
is asking the wrong question. The order of the checks is therefore not a
convention; it is forced by what makes each one interpretable.

### 7.2 The potential-quality gate runs in two parts, at two times

The gate is one idea, but it cannot be one event in the pipeline, and
this falls out of decisions already made elsewhere.

Its **bulk and surface half** — equilibrium lattice constants, elastic
stiffness, surface energies, and the amorphous-structure validation of
§3.5 (partial g(r) against experiment, and the per-atom disorder score
against the environment library; ring statistics and coordination are
its v1 survivors) — must run **before the structure builder**. §2.2 makes the
builder a consumer of the potential's own relaxed lattice constants: it
matches the two surface lattices on them and records the residual strain
from them. A potential with a wrong lattice therefore builds a wrong
box, and everything downstream measures the wrong system. This half
gates the build, at the step 2/3 boundary.

**"Against VASP and experiment" is two categories, not one, and only one
of them inherits.** The references this half compares against arrive by
four different routes, and §4.8's inheritance rule binds exactly one.
The lattice constants, stiffnesses and surface energies are **computed by
us**, so they inherit the recipe's production settings block unchanged —
that is what makes each comparison a clean reading of the potential's
learning error rather than a mix of that and a settings mismatch. The
g(r) target of §3.5 (and the v1 survivors' coordination and ring
numbers) are **taken from published experiment or literature**, and
inherit nothing: they carry their own provenance and the `real` flag
recording whether the shipped value is yet the true anchor or still a
stand-in. The amorphization-depth threshold is a third thing again —
**measured by this pipeline's own sweep** (§3.6) — so it inherits
nothing either, and its provenance is one of our own runs. The
environment library (§3.5) is a fourth: **manufactured by the bootstrap
under the very model being judged** (§4.8 part 2), so it is neither an
outside truth nor a computed-accurately value, and it carries the model
name and descriptor settings it was built with instead of a `real`
flag. A rule stated as "every reference inherits" would be false of
three of the four, which is why §4.8 states it only of the computed
kind.

Its **interface half** cannot run there at all, because the interface
does not yet exist. The interface-fidelity check of §7.3 needs a
press-then-pull trajectory, so it runs after step 7.

The consequence is worth stating, because it is uncomfortable. **An
interface-coverage failure is discovered only after the entire pipeline
has been paid for.** That is what §7.3's live monitor exists to soften.

### 7.3 The interface-fidelity check, and watching it live

The bulk and surface properties above do not probe the one region the
whole project is about. A potential can reproduce every one of them and
still be wrong exactly where the bond number is read. STRUCTURAL 3 gives
the interface two complementary signals, and they catch different
failures:

- **Committee uncertainty along the press-then-pull trajectory.** The
  spread among the committee members of §4.4 is large where the
  potential is extrapolating. This is cheap, always available, and it
  catches the potential being *uncertain* — wrong in a way it knows
  about.
- **An all-electron energy-difference cross-check on an interface
  subcell** — the `interface_fidelity` measure of §6.4, which is M4
  minus M2 evaluated on **the same subcell**, against VASP now and Imago
  at scale later. This catches the potential being **confidently
  wrong**: the committee agrees with itself and is off. It is read only
  when `subcell_truncation_error` says the subcell was large enough to
  have asked the question; otherwise it is `unresolved`, not `pass`.

Neither signal subsumes the other. *Committee agreement is not
correctness*, which is precisely why the second signal is not optional.

**Watching it live, and why an abort is not a loss.** The uncertainty
signal is available at every timestep, so it need not wait for the
post-hoc check. Reasoning about whether to act on it turns on one
observation. If the uncertainty genuinely leaves the training
distribution partway through a pull, then the post-hoc check will void
that measurement anyway — the run was already lost, and finishing it
buys nothing. An abort cannot destroy work that would have survived.
**The only way a live abort wastes a run is if the threshold fires when
the potential was in fact fine.** The entire design of the monitor is
therefore false-positive control, and it has six parts:

- **Evaluate the committee on a stride**, roughly every hundred steps.
  Running four members every step multiplies inference cost about
  fourfold; running them every hundredth step costs a few percent, and
  uncertainty does not change meaningfully between adjacent
  femtoseconds. The monitor is cheap *because* it is strided, and the
  stride is a recorded setting, not an implementation detail.
- **Run the pull-rate ladder in ascending cost, and gate between its
  rungs.** §5.4 already requires at least three rates spanning a decade,
  so the fastest rung is both the cheapest and *required output
  regardless*. Run it first: it traverses the same press → bond → pull →
  separate pathway and maps the uncertainty along it for a fraction of
  the production cost. This scout is free. Its limit must be stated
  honestly, though: a slow pull is not a fast pull in slow motion. It
  permits rearrangements that visit configurations the fast rung never
  reaches, so **a clean scout is a filter, not a proof**, and the
  in-run monitor remains necessary on the slow rungs.
- **Two thresholds, not one.** A *warn* band records and harvests while
  the run continues; an *abort* band stops it. The gap between them is
  where the most valuable training data lives — configurations the
  potential finds unfamiliar but can still integrate.
- **Require persistence.** A single high-uncertainty frame is a rare
  close approach, not extrapolation. The excursion must persist over a
  window before the abort band fires — the same discipline §5.4 applies
  when it extracts a force peak above a noise floor rather than taking
  a bare maximum.
- **Resolve the uncertainty per atom, not only per cell.** DeePMD's
  energy is a sum of atomic contributions, so the committee spread can
  be resolved atom by atom. A single number for the whole cell says only
  *that* the potential is guessing; the per-atom field says **where**.
  That sharpens the diagnosis of §7.6 — spread concentrated at the
  interface is `interface_coverage`, spread out at the grips is a
  different problem entirely — and it places the interface subcell of
  §6.4, which is carved around exactly those atoms. (Whether ALF exposes
  the per-atom decomposition or only the global spread is a code-level
  question for PSEUDOCODE; the quantity exists in DeePMD.)
- **Restart from the post-cascade checkpoint, and bound the aborts.**
  STRUCTURAL 1b puts the violent Ar cascade and the heal on the universal
  foundation MLIP with ZBL, not on the committee, so **the activated
  surfaces do not depend on the committee and survive retraining
  untouched**. A retrained potential invalidates only the press, the
  settle and the pull. Finally, aborts are counted: repeated aborts at the same
  physical stage within one potential generation are not a nuisance to
  be retried, they are an `interface_coverage` diagnosis, and the gate
  escalates to a human rather than looping.

The uncertainty threshold itself is not a number typed into a settings
file. It is **calibrated against the distribution of committee spread
over held-out training configurations**, so that configurations the
potential has genuinely seen pass by construction, and the threshold
moves when the training set does. Note what this makes the threshold
mean: *this configuration is less familiar to the potential than all but
a small fraction of the things it was trained on.* Where along the
trajectory that first happens is an **output**, not a setting. Choosing
instead to abort at some fraction of the pull would be asserting
something about the physics that we do not know.

The quantile is a real choice, and a cost asymmetry settles it. Aborting
too early wastes one production run. Aborting too late wastes that same
run **and** hands us a harvest drawn from a stretch of trajectory
integrated under forces we had already stopped trusting. Err early; let
the persistence window keep "early" from becoming twitchy.

**The abort is a data-generation event.** Once the production
measurement is void, the configuration it died on is the single most
informative structure the run produced, and the machinery to exploit it
already exists. §4.4 adopts ALF's **uncertainty-driven dynamics**: a
bias potential proportional to the committee spread, whose force drives
the system *toward* configurations the potential finds unfamiliar. The
abort trigger and the UDD bias are two responses to the same signal with
opposite intent — a production run wants to avoid high uncertainty
because it is trying to make a measurement, while a data-generation run
wants to seek it because it is trying to find the potential's holes. So
at the trigger, SABSIM voids the measurement and launches a short,
bounded UDD exploration from the triggering configuration. **The
production run's death becomes a data-generation run's birth.**

This works because of a fact worth stating plainly, since it is easy to
get backwards: **a training configuration does not have to lie on a
physically correct trajectory.** The label comes from VASP, which does
not care how the configuration was generated. A configuration need only
be physically plausible and lie in a region where we need the potential
to be accurate. Configurations produced by a potential that is guessing
satisfy both — right up until they do not, which is what bounds the
exploration. The uncertainty axis therefore carries four bands, not two:

| Band | Meaning | Action |
|------|---------------------------|-----------------------------|
| below warn | familiar | run normally |
| warn → abort | unfamiliar, integrable | keep running, harvest |
| at abort | extrapolating | void; begin UDD exploration |
| ceiling | nonphysical | stop everything |

The **ceiling** is not a statistical threshold but a physical one — a
minimum interatomic distance, an energy bound, no spurious fragmentation
— because a biased run driven by a potential that no longer knows the
physics will eventually reach configurations that are *correctly
labelled and worthless*, and labelling them spends budget teaching the
model about a region it will never visit.

Finally, what is harvested is not the triggering frame. Selecting one
configuration per abort is what makes active learning converge slowly,
and training **only** on hard configurations is a distribution shift
that can degrade the potential where it used to be fine. The batch
handed to ALF's sampler is therefore drawn from four places at once: a
**stratified baseline** across the whole trajectory, the **warn band**,
the **excursion neighbourhood** on the run-up to the trigger, and the
**UDD exploration** beyond it.

### 7.4 The bond-outcome gate: a ratio, and a bracket

`VISION.md` goal 4 anchors the bond number to razor-blade crack-opening
(Maszara) measurements for silicon-to-silicon and silicon-to-silicon-
dioxide, taken in the **surface-activated** regime rather than thermal
fusion bonding, and used as **relative** anchors. v1 runs the Si/SiO₂
pair *and* a Si/Si same-material reference precisely so that a ratio can
be formed; one system alone is only a point.

**The ratio is the scientific criterion.** The simulated ratio of the
two works of separation is compared against the experimental ratio,
within the combined uncertainty of both. The reason to trust a ratio is
physical, not resignation: the systematic errors that keep a
nanosecond-scale pull from reproducing an absolute fracture energy —
the pull rate, the cell size, the thermostat, the finite activation
dose, the whole mismatch of timescales — are **largely common to the two
systems, and cancel to first order in their ratio**. What survives is
the difference between the two interfaces, which is the physics we are
actually claiming.

That cancellation is real only if the uncertainty is propagated as
such. Both numbers come from the same potential under the same protocol,
so their errors are **correlated**, and treating them as independent
would overstate the ratio's uncertainty and weaken a test that ought to
be strong. The covariance is carried, not assumed away.

Nor is the cancellation assumed to be complete, and — revised
2026-08-30 (Paul) — the ratio is no longer something the program forms.
Each pair is its own project (§1.1); the Si/SiO₂ project and the Si/Si
project each emit a work of separation with its uncertainty and its
fully resolved specification, and the scientist divides one by the
other. What the retired relation machinery would have checked — that
the two projects share a potential and a protocol — the scientist
checks by laying the two specifications side by side, sorting every
difference as contrasted, entailed or incidental (§1.1). The gate
described here therefore judges ONE pair: it reports the absolute
number, its uncertainty, and the bracket below; it does not grade the
comparison, because a criterion calibrated for one comparison has no
standing to suppress another, and it is the scientist, not the gate,
who decides what a comparison was worth.

One entry in that side-by-side is unavoidable. Si/Si has no lattice
mismatch and Si/SiO₂ does, so the residual-strain systematic that this
criterion would most like to see cancel does not — and no care in
setting up the two projects can fix it, because **you cannot contrast
two material pairs without contrasting their mismatch.** It is an
*entailed* difference, the irreducible price of the contrast rather
than a flaw in it; the ratio is only partially cancelling on its
account, and each project's provenance records the strain so a reader
cannot miss it.

**The bracket is a sanity check, and it is not science.** A ratio stays
perfectly correct when both of its numbers are wrong by the same factor
of a thousand — which is exactly what a unit-conversion error produces.
So each absolute work of separation is additionally required to fall
inside a loose order-of-magnitude bracket around its experimental value.
This criterion tests nothing about the physics and everything about the
plumbing, and it is the only thing standing between us and a confidently
reported number in the wrong units. Prior art published two mutually
inconsistent headline strengths side by side (`PRIOR_ART.md` §1.7) with
nothing in the codebase positioned to compare them.

### 7.5 Every threshold is a significance statement

§6.6 forbids bare numbers: every record carries a value, an uncertainty,
and a realization count. That rule now pays for itself. Because the gate
compares *measures* rather than numbers, nearly every comparison it
makes is a **statement about significance rather than a magic constant**.

The all-electron cross-check is the clearest case. It does not ask
whether `M4 − M2` is smaller than some tolerance in eV. It asks whether
that difference is consistent with zero given the combined uncertainty of
both measures. When the ensembles are small the test is weak — and the
gate **reports the power it had**, so that a pass on two realizations is
not silently mistaken for a pass on twenty.

Two rules follow, and both exist to close the door on warn-and-continue:

- **A measure whose status is `unresolved` can never pass a check.**
  §6.7 lets Imago descriptors come back unresolved so the Imago-free
  path stays first-class. A check that depends on them must then return
  unresolved as well — never `pass`. Absence of evidence is recorded as
  absence, and it propagates.
- **Where a bare constant is genuinely unavoidable** — the sanity
  bracket's width, the quantile that sets the uncertainty threshold, the
  persistence window — it is named, recorded in the report with its
  justification, and treated as a knob rather than a fact.

### 7.6 The precedence chain, and the diagnosis

Every check runs, and every outcome is recorded. But the *cause* the
gate reports is read off an ordered chain, because each test is only
interpretable given the ones before it — the interface check means
nothing if the bulk is wrong, and the protocol cannot be judged through
a potential we do not trust:

```
if a required check could not be evaluated  -> undiagnosed
elif the measurement is invalid             -> void
elif the bulk / surface gate fails          -> bulk_model
elif the interface-fidelity check fails     -> interface_coverage
else                                        -> protocol
```

- **`void`** — the measurement is not wrong, it is *not a measurement*.
  §6.5's internal checks failed, or the trajectory was truncated, or
  atoms were lost, or the live monitor aborted the run. A void
  measurement is **never diagnosed**, because diagnosing a number you do
  not believe is worse than reporting nothing. Remedy: rerun.
- **`bulk_model`** — the potential is wrong in general. Remedy: add
  training data.
- **`interface_coverage`** — the potential is fine in the bulk and has
  never seen the interface. Remedy: add *interface* training data. This
  is still the data remedy, now correctly targeted, and closing this
  hole is what STRUCTURAL 3 was for.
- **`protocol`** — the activation, the press, or the pull. Remedy:
  revise the protocol; more data will not help.
- **`undiagnosed`** — a test the chain depends on returned `unresolved`,
  so the chain cannot be walked at all. This is **not** the bucket for
  "nothing fired"; see §7.7. If the potential's interface check could
  not be evaluated, we may not conclude that the potential passed it.

Two design points hide in that chain. The first is that `void` sits at
the front, ahead of every question about cause, and it did not exist in
`ARCHITECTURE.md`'s original three-way routing — it falls out of §5's
refusal to accept truncated trajectories and §6.5's checks. The second
is that the chain reports the *first* actionable cause while **all**
checks still run and are recorded, so a pair with two problems does
not hide the second one; it simply names the one that must be fixed
first.

### 7.7 The conclusion and its basis are reported separately

`protocol` is the last branch, so it is reached whenever nothing before
it fires. That makes it a **conclusion by elimination**, and reasoning by
elimination is sound only when the alternatives have been exhausted. We
have enumerated exactly two ways for a potential to be at fault. Should
there be a third — a deficiency visible in neither the bulk properties
nor the two interface signals — it would fall through both tests and
land, silently and confidently, in a bucket that sends a researcher off
to adjust a press load that was never the problem.

That is the prior-art pattern of §1.8 (detect the defect, report the
number anyway) relocated from a `print` statement into the gate itself,
and the fix is neither to forbid the conclusion nor to trust it blindly.
**The gate reports the cause and, in a separate field, how it reached
it:**

```
cause : protocol            cause : protocol
basis : by_elimination      basis : direct_evidence
fired : []                  fired : [pull_rate_ladder_no_convergence]
```

Nothing is discarded. A conclusion by elimination is frequently correct
— an activation dose that is simply too low is a real protocol failure
that no protocol check need fire to make true — and a reader who sees
`by_elimination` knows at once to weigh it as inference rather than
observation.

The field also makes our own ignorance **countable**. If most protocol verdicts
across many projects are reached by elimination and few by evidence, that is a
measurable statement that the protocol checks are too sparse, and it becomes a
task rather than a silent weakness. The protocol checks available today all
come from §5 and §6 — the pull-rate ladder failing to converge, the press never
reaching the contact quality of §5.1, the dissipation identity or the
ladder-closure check of §6.5 breaking — and that set was assembled for other
purposes. **It has not been argued to span the ways a protocol can be wrong**,
and the `basis` field is how we find out.

### 7.8 The diagnostic-label schema

The gate emits one machine-readable record, alongside §6's measure
vector and obeying the same rules — read by name and status, never by
position; no bare numbers.

- **`verdict`** — `pass`, `fail`, or `void`.
- **`cause`** — null on a pass, else one of `void`, `bulk_model`,
  `interface_coverage`, `protocol`, `undiagnosed`.
- **`basis`** — `direct_evidence`, `by_elimination`, or
  `not_applicable`.
- **`fired`** — every check that failed, each with its measure name,
  value, uncertainty, threshold, and the comparison performed.
- **`unresolved`** — every check that could not be evaluated, and why.
- **`power`** — for each significance test, the combined uncertainty
  that made it pass or fail, so a weak test cannot pose as a strong one.
- **`remedy`** — `rerun`, `add_data`, `add_interface_data`,
  `revise_protocol`, or `investigate`.
- **Provenance** — the potential generation and committee size, the
  trajectory identifiers, the thresholds in force and where each came
  from (a calibrated quantile, or a named constant).

The gate takes its inputs by **explicit identifier**. It never discovers
them, and in particular it never selects the newest matching file in a
directory — the mechanism by which prior art silently compared two
different simulations to each other (`PRIOR_ART.md` §1.7).

### 7.9 A gate that has never failed is not known to be a gate

Every check here is a claim that certain inputs will be rejected, and an
untested rejection path is an assumption. The gate is therefore
exercised, as part of its test suite, on inputs that are **known to be
bad**, and each must produce its specific expected cause: a deliberately
undertrained potential (`bulk_model`); a trajectory truncated partway
(`void`); a structure with atoms lost through the boundary (`void`); a
measure vector with an energy in the wrong units (the sanity bracket);
a potential trained only on bulk configurations (`interface_coverage`);
and a pair whose interface reference is missing entirely
(`undiagnosed`, never `pass`).

This is the one requirement that most directly answers §1.8. Prior art's
analyzer contains checks; what it does not contain is any check that can
fail. Implementing a gate and testing that it *rejects* are different
pieces of work, and only the second one produces a gate.

### 7.10 What we keep, what we replace, and v1

**Keep:** nothing. There is no prior-art gate to keep — `check_amorphous`
is a reporting tool that prints a g(r) RMSD against an optional
experimental curve with **no threshold and no DFT reference**, and the
analyzer's nine warnings are bare prints.

**Replace:** report-without-threshold (→ every check compares against a
reference and can fail); warnings as `print` (→ typed records the gate
reads); the newest-file-wins input fetch (→ explicit trajectory
identifiers); a bad number attributed to the protocol by default (→ a
cause *and* the basis on which it was reached); bare tolerances (→
significance tests against propagated uncertainty, with the power
reported); and a passing verdict on missing evidence (→ `unresolved`
never passes).

**Frozen for v1:** the gate is a **reporter**. It emits the verdict, the
cause, the basis, and the remedy; a human reads them and decides whether
to add data and rerun. Wiring the remedy to `data_targeting` is the
future closed loop (`ARCHITECTURE.md` §3, `VISION.md` principle 5). The
bulk/surface half runs before the build; the interface half after step 7;
the live monitor runs with the full guard stack of §7.3, and its abort
is a run-validity decision, not a loop-closing action. The bond-outcome
gate tests the Si/SiO₂-to-Si/Si ratio against the experimental ratio,
with the absolute bracket alongside it. M4 uses the VASP interface
subcell.

**Still DESIGN follow-ons:** the numeric thresholds (the quantile that
sets the uncertainty threshold, the significance level for the fidelity
cross-check, the width of the sanity bracket); the committee stride, the
persistence window, and the abort budget of §7.3; the exploration step
budget and the plausibility ceiling that bounds the UDD run; the
composition of the harvested batch (how much stratified baseline against
how much excursion); whether ALF exposes the per-atom committee spread
or only the global one; the covariance treatment in the ratio's
uncertainty; and — the one §7.7 exists to surface — whether the
inventory of protocol checks is anywhere near complete.

## 8. Step-8 characterization (Imago + Kaleidoscope)

Every other section of this document designs something SABSIM builds and
then runs. This one designs a **seam**. The all-electron code (**Imago**)
and the thin batch manager that dispatches it (**Kaleidoscope**) are
sibling projects, not modules of this repository (`ARCHITECTURE.md` §1).
What §8 owns is everything on SABSIM's side of that boundary, and it is
four artifacts: a **selector** that decides which frames of the
press-and-pull trajectory are worth the expense, a **skeleton preparer**
that turns a structure into an input Imago will accept, a **manifest**
that is the entire conversation with Kaleidoscope, and a **harvester**
that collects what comes back and turns it into the measure records §6.6
defines.

"All-electron" is why step 8 exists at all. The potential of §4 never
sees an electron; it maps positions to energies and forces, and it was
trained to do so. It cannot say whether the bond that formed across the
interface is ionic or covalent, how much charge moved, or how strong an
individual bond is in the sense a chemist means. Imago models every
electron — no pseudopotential shortcut for the tightly bound core states
— and answers exactly those questions, on the calm, nearly-relaxed
geometries where its atom-centered basis is at its best. That last
clause is also why VASP and not Imago labels the violent step-1
configurations (`ARCHITECTURE.md` §2.3). The division of labour is
deliberate: VASP for the distorted, Imago for the bonded.

### 8.1 One seam, two consumers, wanting different things

Step 8 does not serve one measure. It serves two, and their demands are
almost opposites. Reading §8 as a single "run Imago on some snapshots"
job is the way to get it wrong.

**M4 wants two states, and they must be commensurable.** The
all-electron work of adhesion (§6.4) is an energy *difference*: the
energy of the separated state minus the energy of the bonded state, per
unit of interface area. It needs exactly two structures, both relaxed
into their local energy minima, both effectively at zero temperature. It
does not want a series, and it does not want thermal noise. What it
demands above all is that the two states hold **the same atoms in the
same cell**, because that is what makes the per-atom energy zero-points
cancel and the difference reference-free.

**M5's electronic family wants a series, and it must be consistent.**
Effective charge and bond order along the trajectory (§6.4) are read from
frames **as they were** — finite temperature, unrelaxed, taken at the
moments where something chemically interesting happened. Relaxing them
would erase the event. This family is a *trend*, so what it demands is
that every frame be measured on the same footing as every other, not that
any frame be commensurable with some external reference.

Different temperatures, different counts, different notions of
correctness. One structure convention and one dispatch path serve both,
but the two must never be collapsed into one job type — and, as §8.6
shows, they fail differently too.

### 8.2 The structure is §6.4's interface subcell, extracted once

**Decision: every Imago calculation in step 8 runs on the interface
subcell of §6.4.** Not on the production cell, which is far too large,
and not on some second, step-8-specific construction.

This is worth more than it first appears. §6.4 defines the subcell for a
different purpose — as the only affordable arena for the all-electron
cross-check — and it defines it *carefully*: the full lateral periodicity
of §2's shared cell is kept untouched, the cell is truncated only along
the interface normal, every atom whose result will be used keeps its
entire 6 Å environment, and the truncation manufactures no surface and
severs no bond. Reusing that object here means the convergence test §6.4
already runs — enlarging the subcell with the *potential* until
`subcell_truncation_error` falls below tolerance — certifies M5's frames
as well as M4's endpoints. There is no second study to run. The cheap
method certifies the expensive method's input, once, for everything.

**How the truncation actually avoids cutting a bond.** The production
cell presents two real free surfaces to vacuum, one at the outside of
each slab (§5.6). Thinning removes material only from the **undamaged
crystalline buffer** inside each slab — never from the activated skin,
never from the interface, never from the outer free surface. Because
that buffer is a stack of identical repeating crystal layers, removing a
*whole number* of them and closing the gap leaves the two faces that now
meet lined up exactly as they were in the uninterrupted crystal: no gap,
no strain, no atom short a neighbour, and a join indistinguishable from
bulk (§6.4). This **quantizes the thinning** — only whole-layer steps
keep the join seamless. §2.5 guarantees the buffer to remove exists,
because it sizes each slab as `activated_depth + minimum_bulk_thickness`.
What the subcell presents to vacuum afterwards is therefore the
production cell's *own* free surface, brought closer to the interface.
Nothing was cleaved.

**The atom set is frozen once, by identity.** It is chosen at the
zero-load reference state of §5.3 and carried through the trajectory by
atom identity, minimum-image throughout (§6.8). It is emphatically not a
spatial slice re-applied to each frame: atoms move, and a spatial slice
would let them wander in and out, so a descriptor series would jump for
reasons of bookkeeping rather than chemistry. An atom that transfers
across the interface during the pull stays in the set and is counted by
§6.4's `transferred_atom_count`, where it belongs.

**The two retained thicknesses need not be equal.** §6.4 says the subcell
is centered by the per-atom committee spread — the quantity that
localizes where the potential is least sure of itself (§7.3). With the
full lateral cell kept, there is nothing to center *laterally*; the
freedom that actually exists is how the retained thickness is **split
between the two slabs**. The spread decides it: the slab whose atoms the
committee disagrees about most keeps more substrate. The convergence test
of §6.4 accordingly runs over a thickness *pair*, and each entry of that
pair is a whole-layer count, so the search is a ladder in two discrete
directions — add a layer to one slab, or to the other — not a single
continuous number.

**An honest limit, stated rather than hidden.** The lateral cell is not
ours to shrink — it is §2's shared coincidence cell, fixed by the
crystallography of the pair. If, at the minimum retained thickness, the
subcell still exceeds the affordable envelope (prior art's 500–2000-atom
estimate, `PRIOR_ART.md` §1.2 item 5), then there is no way to make step 8
affordable for that pair without breaking one of §6.4's four rules. The
design's answer is to say so, not to break one quietly: the Imago variant
of M4 and the electronic family of M5 return `unresolved` with a recorded
reason, exactly as they do when Imago is late (§6.7). A consequence
worth noticing: **§2's coincidence tolerance prices step 8.** A looser
tolerance buys a smaller shared cell, and the shared cell is the one
dimension of the subcell that step 8 cannot negotiate.

### 8.3 Three detectors, measured where the event is

Which frames? Prior art answers this, and it is one of only two
designed-but-unbuilt ideas its evaluation rates as worth taking
(`PRIOR_ART.md` §1.8). Its `select_snapshots` specifies three detectors,
each picking out a physically meaningful moment:

- **potential-energy local minima during the hold** — bonds forming, and
  releasing energy as they do;
- **potential-energy local maxima during the pull** — a bond stretched as
  far as it will go before it lets go;
- **sharp drops in the normal stress σ_zz** — the mechanical signature of
  a bond actually breaking and shedding the load it carried;

with near-duplicate frames merged. Nothing was ever built, so what
transfers is the *shape* of the idea. Three things must be added before
it becomes an algorithm, and each of them fixes a way the naive version
fails.

**Measure the signal where the event is.** The production cell holds many
thousands of atoms in thermal motion. Its total potential energy
fluctuates by far more, frame to frame, than a single bond formation
releases. A local-minimum detector run on that series is a noise detector
with a physics name. So all three detectors run on the **frozen subcell
atom set of §8.2**: LAMMPS records per-atom potential energy and per-atom
virial, and the detectors read their sums over that set alone, with the
stress obtained from the subcell's own volume.

**A local extremum of a noisy series is not an event.** The series is
smoothed over a window of a few characteristic vibrational periods, and a
candidate must clear a **prominence** requirement — a depth or height
relative to its surroundings, measured against the same noise floor §5.4
established for the force curve. A detector without a prominence
requirement finds every thermal wiggle in the trajectory and calls each
one a bond.

**Merge by event, not by geometry.** Two frames are near-duplicates when
their **cross-interface bond sets are identical** — bonds by the derived
cutoffs of §6.3, identified by provenance label rather than species
(§6.2) — and their subcell energies differ by less than the noise floor.
A geometric root-mean-square-distance criterion, the obvious choice,
gets this backwards in both directions: it merges two frames that sit on
opposite sides of a bond-breaking event because the atoms barely moved,
and it keeps two frames that differ by nothing but a phonon.

**The endpoints are not detected; they are always included.** M4 requires
the relaxed bonded and relaxed separated states, and no detector finds
them, because they are not moments in the trajectory. They are computed
states from §5, and they enter the batch unconditionally.

**The budget is a convergence test, and its drops are logged.** Candidates
are ranked by prominence and truncated to a frame budget. What was
dropped is *reported* — a silently truncated list reads, downstream, as
complete coverage. And the budget is a numerical setting by §1.2's test:
raise it, and the descriptor trend must stop changing. Its adequacy is
demonstrated the same way the subcell's size is, by refining it once and
showing the answer stayed put, not by asserting that thirty frames feels
like enough.

Finally, selection is a **pure, deterministic function** of the
trajectory and the settings. It can be re-run, audited, and argued with
long after the molecular dynamics is gone, and its output is part of the
provenance record §1.6 requires.

### 8.4 The format transfers; the mechanics do not

Imago inherits the legacy OLCAO code's **input format**, essentially
unchanged — the differences are a few adjustments to file layout and to
the command sequence that drives a run. So `ARCHITECTURE.md` §2.3's
phrase "structure in OLCAO format" is accurate, not stale, and OLCAO
names both the method Imago implements and the input convention it
kept. This corrects an overstatement `PRIOR_ART.md` carried, which said
the two shared no input format at all.

What emphatically does **not** transfer is everything built around that
format. Prior art contributes no input generation and no skeleton prep to
inherit; every `OLCAO` string in its source is the `$OLCAO_RC`
environment variable, a convention in which a program reads its
configuration out of whichever directory it happens to be sitting in
(`PRIOR_ART.md` §1.8). That is the working-directory-as-configuration
antipattern §1 was written to invert, and importing a template that
carries it would import it. **A skeleton is a self-contained directory
whose entire content is a function of explicit arguments.** Nothing is
read from the environment. Nothing is read from the current directory.

Two physics choices are inherited outright, and one of them is inherited
with a correction.

**Full basis.** Imago builds electronic states from functions centered on
atoms, in sets of increasing size. The bond at an activated interface is
precisely a region where charge redistributes into the space *between*
atoms, so the smaller sets — tuned for near-equilibrium bulk — are the
wrong economy exactly where we are looking. Step 8 uses the full set.

**Γ-point-only sampling, re-justified.** Electronic states in a periodic
solid are labelled by wavevectors filling a reciprocal cell whose size is
inversely proportional to the real-space cell. A large real cell gives a
small reciprocal cell, and a single point — Γ, its origin — samples it
adequately. Prior art justifies Γ-only by the *disorder* of the
interface, on the reasoning that a disordered material has no dispersion
left to sample. That argument is true and it is secondary: most of the
subcell by atom count is **crystalline substrate**, which is not
disordered at all. The primary and checkable justification is cell size.
So Γ-only is v1's setting and, by §1.2's test, a numerical one: refine
the sampling and the answer must stop moving. One snapshot is run once
against a denser mesh and the comparison recorded — cheap insurance
against a justification we inherited instead of testing.

**Skeleton preparation is a pure function** of a structure and a settings
object: no clock, no working directory, no environment. That is what
makes it testable by exact comparison against a **known-good input**,
with no Imago present anywhere — which closes the last outstanding
STRUCTURAL 2 follow-on. The reference structure comes from the validated
four-structure Kaleidoscope campaign (`ARCHITECTURE.md` §2.3).

**ASE is the membrane, not the vocabulary.** ASE carries species,
positions, and the cell across the boundary. The basis choice, the
sampling, and the command sequence are Imago's own vocabulary and do not
pass through ASE's — which knows about energy, forces, and motion, and
would quietly flatten everything step 8 exists to obtain
(`VISION.md` principle 4).

### 8.5 The manifest is the whole conversation

SABSIM hands Kaleidoscope **one manifest**, listing N analysis units, and
waits. That is the entire interface. The outer sequencer treats the batch
as a single opaque step and never looks inside, because Kaleidoscope
stands up its own dispatch machinery and wrapping it in ours would nest
one inside the other (`ARCHITECTURE.md` §4.1).

Each unit is self-describing: where its skeleton lives, a stable
identifier, which consumer it serves (an M4 endpoint, or an M5 frame and
which detector found it), and provenance backpointers — the pair, the
trajectory, the frame index, the subcell, the potential generation, the
seed set.

**The identifier is a content fingerprint of the skeleton**, reusing §1.4's
rule rather than inventing a second one. Identical content yields an identical
identifier, so Kaleidoscope's cache is correct by construction; any change to
the structure or the settings yields a new one, so a stale result cannot be
served for a structure that no longer exists. An identifier built from a frame
number, a directory name, or a timestamp collides across projects — and a cache
keyed on a colliding identifier is prior art's newest-file-wins failure (§5.7)
wearing new clothes.

**What Kaleidoscope owns:** dispatch, caching, and tracking which units
succeeded and which failed. **What it must not own:** what a snapshot
means, which measure it feeds, or whether the batch was sufficient. Those
stay here. The moment we want to bolt a results database onto it is the
signal to adopt a real one instead — `VISION.md` principle 3 names this
temptation in advance because it is a natural one.

The manifest is retained as an artifact, because it *is* step 8's
provenance record. Re-running an unchanged project should be a cache hit
from end to end; if it is not, something changed, and the fingerprints
say precisely what.

### 8.6 The harvester, and the fact that failures are not random

The harvester is handed the manifest. It does not go looking for a
results directory, and it does not take the newest one (§5.7).

Two channels come back. Quantities in ASE's vocabulary — total energy,
forces — cross through ASE. Imago's own outputs — the effective charges
and bond orders that are the reason for the whole exercise, and the
total and partial density of states (§6.4) — ride the native channel and
are parsed here. The DOS and partial DOS are retained as curve artifacts
for a human to read; only their Fermi-energy value and gap size are
reduced to §6.6 records.

**M4 is all-or-nothing.** It is a difference of two endpoint energies. If
either endpoint fails, the all-electron `interface_fidelity` is
`unresolved`. It is never computed from one all-electron endpoint and one
MLIP stand-in for the other, which would silently measure the very
quantity the difference was supposed to test. And it remains gated by
`subcell_truncation_error` exactly as the VASP variant is: the cheap
method certifies the expensive method's input, whichever expensive
method it happens to be.

**M5 tolerates holes — but not every hole.** A series survives a missing
frame; the record simply carries a smaller `realization_count`, and the
missing frames are named. What it cannot survive is losing a *class* of
frame, and here is the reason this subsection exists: **all-electron
calculations do not fail at random.** They fail on the hard structures —
the maximally stretched bond, the instant of breaking, the frame with the
most distorted local geometry, which is also the frame whose atom-centered
basis suits it worst. Those are exactly the frames carrying the signal. A
harvester that averages whatever survived would report the easy physics
and call it a trend.

So the harvester reports **coverage by detector class**, not a single
success count: bond-formation minima, maximum-stretch maxima, stress-drop
spikes, each with how many were requested and how many returned. If a
class is emptied, the trend it supported is `unresolved` even though most
of the batch succeeded.

Everything harvested becomes a §6.6 record and obeys §6.6's rules: an
uncertainty across the frames it was reduced from, a `realization_count`,
explicit units, a `fidelity` of `all-electron` for energies or
`electronic` for descriptors, a `method` naming Imago and its version,
and a `status`. **No bare numbers.** The harvester computes no verdicts
of its own; §7's gate reads the records.

### 8.7 What the gate does, and does not do, with step 8

M4's Imago variant feeds `interface_fidelity`, which **gates** (§7.3): a
failure there is diagnosed as `interface_coverage`, a problem with the
potential's training data, and never as a protocol failure. That routing
is the whole point of STRUCTURAL 3.

M5's electronic descriptors **do not gate**. There is no defensible
threshold on an effective charge that means "this bond is bad." They
answer *what kind* of bond formed — how much charge moved, how covalent
it is, whether dangling-bond gap states remain in the density of states,
how the coordination changed as the bond stretched — and their audience
is the human scientist reading the report (§1.1). The two scalars taken
from the DOS, its Fermi-energy value and its gap size, are descriptive
in the same way and gate no more than the curves they came from. A number
with no defensible threshold must not acquire one merely because it is
printed beside numbers that have them.

And Imago's all-electron value does not *replace* VASP's. §6.6's `method`
field keeps them apart, and when both report, two all-electron references
disagreeing is information — one is limited by its basis, the other by
its pseudopotential — rather than a conflict to be settled by choosing a
favourite.

### 8.8 Step 8 is buildable before Imago can run it

Three Imago-side deliverables are still in flight (`ARCHITECTURE.md` §4):
a fast, lightweight analysis mode; the ASE adapter that lets a snapshot
cross the boundary; and a database of good initial-guess potentials that
makes large analyses affordable. `TODO.md` carries them as an unowned,
undated schedule risk against SABSIM's own funded deliverable.

The seam is what bounds that risk. The selector, the skeleton preparer,
and the manifest builder are pure functions of data SABSIM already
possesses; all three can be written and tested to completion with no
Imago anywhere in sight. The harvester is testable against a recorded
result from the four-structure campaign already validated on the cluster.
Only **execution** waits.

And §6.7's registry makes waiting a configuration rather than a
degradation: M4 falls back to VASP **on the same subcell** — which is the
entire reason §8.2 insisted on one structure convention — M5's electronic
family reports `unresolved`, and the gate still runs. What a late Imago
delays is a measure, not the pipeline.

### 8.9 What we keep, what we replace, and v1

**Keep:** the three detectors' shape; the full-basis choice; the
Γ-point-only choice, now re-justified by cell size and demoted to a
numerical setting with a convergence check; the 500–2000-atom cost
envelope as a planning figure; and — newly established, against what
`PRIOR_ART.md` previously claimed — the OLCAO **input format** itself,
which Imago inherits with only file-layout and command-sequence changes.

**Replace:** detectors run on the whole cell's potential energy (→ on the
frozen subcell atom set, where the event is); local extrema taken without
a prominence requirement (→ smoothed, and clearing §5.4's noise floor);
near-duplicate frames merged by geometry (→ merged by event: an identical
cross-interface bond set and an energy difference below the noise floor);
`$OLCAO_RC` working-directory-as-configuration (→ a self-contained
skeleton that is a pure function of explicit arguments — §1's inversion,
restated at the seam); a newest-file-wins results fetch (→ a manifest
whose identifiers are content fingerprints); prose output (→ §6.6
records); and a silently truncated snapshot list (→ a budget whose drops
are logged and whose adequacy is demonstrated by refinement).

**Frozen for v1:** §6.4's interface subcell is the structure for every
step-8 calculation, extracted once, frozen by atom identity at §5.3's
reference state, and thinned only through undamaged crystalline
substrate. The two relaxed endpoints are always analyzed; the descriptor
series uses as-is finite-temperature frames. The manifest is the only
interface to Kaleidoscope, and its identifiers are content fingerprints.
The harvester reports coverage by detector class. M5's electronic
descriptors are descriptive and never gate. M4's Imago variant reports
beside — never instead of — the VASP backstop, and never without
`subcell_truncation_error`.

**Still DESIGN follow-ons:** the smoothing window and the prominence
threshold behind each detector; the frame budget and the refinement that
shows it adequate; the merge tolerance; the one-time denser-mesh check
against Γ-only; the exact file-layout and command-sequence differences
between Imago and legacy OLCAO; the atom-count envelope check of §8.2,
and what §2's coincidence tolerance has to be to keep the subcell
affordable for v1's pair; and Imago's failure taxonomy — which failures
are retryable and which are structural, since §8.6's coverage rule needs
to tell them apart.

## 9. Run artifacts and reporting

This section designs the layer that turns a run into a durable, legible
result: the canonical structured output every consumer reads, the swappable
human report, and the visualization dumps. WHERE these land and how they
are organized is `ARCHITECTURE.md` §4.2; this is their algorithmic and
data-structure shape. The whole design is meant to ADAPT to practical
realities met in implementation — the schemas and the dump columns are a
starting contract, not a frozen one.

### 9.1 The canonical result — one structured summary as the contract

Every downstream consumer — the human report, a person's comparison
across projects, a future automated step — reads ONE machine-readable
summary per run (`summary.json`), never the prose report or the raw
logs (the §6.6 "a gate cannot consume prose" discipline, extended to
the whole result). It holds: the pair identity and resolved spec; the
measure vector (§6); the
activation and gate verdicts with their per-metric detail (§3.5, §7); the
run's provenance (git commit, seeds, potential and reference data with
their stand-in flags, software versions, host); and POINTERS (resolved
path + fingerprint) to the large artifacts on scratch. Because the report
and the roll-up are renderings OF this summary, the report's format can
change without touching the run, and the summary is the auditable record
of what happened.

### 9.2 The report — a swappable renderer over the summary

The human report is generated from the summary and a set of plots, and its
OUTPUT FORMAT is a swappable backend (Beamer for a presentation, or a
Markdown / HTML page) — the choice is a rendering decision, not a rerun.
v1 renders plots only — the g(r) curve, the ring-size histogram, the
disorder-vs-depth profile, and, for the bond stage, the force-vs-opening
curve and the rate ladder — with matplotlib; atomistic snapshots rendered
through Ovito are deliberately DEFERRED (a heavier dependency), while the
dumps that feed them are kept readily accessible (§9.3) so a viewer can
open them by hand. A comparison across projects — the §7.4 Si/Si vs
Si/SiO2 ratio and its combined uncertainty — is the person's own,
formed from two such summaries (§1.1, revised 2026-08-30); the summary
carries everything that comparison needs, and SABSIM renders no roll-up
of its own.

### 9.3 The visualization dumps — trajectories, well-marked

A single snapshot conveys little, so the primary visualization artifact is
the strided TRAJECTORY — a viewer watches the surface amorphize impact by
impact, or the interface press and pull. Each dynamic stage emits one, and
here the design names a build gap: today only the pull dumps a trajectory,
so the CASCADE needs a strided trajectory dump added (a frame per impact
plus the re-anneal). All stages share ONE "Ovito-ready" column set, so any
dump colors and filters the same way:

```
id  type  x y z  group  coordination  defect  provenance
```

where `group` is the LabeledGroup membership (frozen-base / border /
interior / activated-skin) as an integer to color by; `defect` is the
§3.5 per-atom verdict — 1 where the atom's second-shell environment
matches nothing in the environment library, 0 where it does (revised
2026-08-29; before that it was a coordination mismatch); `coordination`
stays as a second, human-readable column; and `provenance` is which slab
an atom was built in (the interface's two sides). The `activated-skin`
value is exactly
the per-atom set `PSEUDOCODE.md` §10.7's `label_activated_skin` records, which
is why that step — deferred in Phase 2 — becomes load-bearing here: it is the
field that lights up the amorphized layer. A single endpoint frame may also
be written into the job directory as a convenience, but it is secondary to
the trajectory.

## 10. Deployment — preparing and submitting a project to a cluster

Every section above says *what* to compute. This one says *where* it
runs — how a project becomes jobs a scheduler will accept, on whatever
machine you happen to be sitting at. The policy is already fixed one
level up in `ARCHITECTURE.md` §4.1: three execution tiers (a thin
sequencer we own, opaque Parsl sub-orchestrators we adopt, and plain
jobs we submit directly); a machine-local deployment file carrying a
`[hardware]` inventory and a `[usage.*]` map keyed by kind of job; and
three roots (`SABSIM_SCRATCH` / `SABSIM_SHARE` / `SABSIM_LOCAL`) set by a
sourced shell rc upstream of Python. The template already exists
(`share/templates/deployment_rc.toml`). What was missing — and what this
section designs — is the **consumer**: the mechanism that reads that file
and acts on it.

Two rules from §1 bound the whole design and are never bent here. The
pair specification may **never** express where it runs (§1.2), so
nothing in deployment leaks back into it. And convenience lives in
*writing* a complete file, never in a silent fallback at load time
(§1.4), so the deployment consumer is a **generator**, exactly as the
specification loader is.

### 10.1 The consumer is a writer, not a submitter

It is tempting to imagine `sabsim` itself submitting jobs and watching
them to completion. It must not, for a concrete reason recorded in
`ARCHITECTURE.md` §4.1: a long-lived submit-and-watch process cannot sit
on a login node — that is one of the six execution walls. So the consumer
**writes ready-to-submit scripts and hands them back**; the human submits
them and watches them. This is the §1.4 generator pattern lifted from the
pair specification to deployment — the same tool that emits a complete,
editable specification now also emits complete, editable submission
scripts with the site-specifics already filled in. Nothing is submitted
for you, and nothing runs on the login node except the writing itself.

The consumer is two commands:

- **`sabsim prepare`** — the writer, run inside the project folder. It
  reads *both* `sabsim.toml` (which pair, and what each surface needs)
  *and* `deployment.toml` (which hardware each kind of job wants), and
  writes the scripts. It is the single place the two inputs meet: the
  pair specification still never names the cluster, and `prepare` joins
  the two only at the moment of writing.
- **`sabsim run --prep-surf1|--prep-surf2|--bond|--analysis`** — the
  executor. It runs one job's worth of the pipeline, and this is the
  line that lives *inside* each generated script. It runs within an
  allocation (wrapped in the launcher), submits nothing itself, and
  does the actual science.

### 10.2 One pair is four jobs (revised 2026-08-30 (Paul))

A pair's eight steps neither all want the same machine nor all want to
run without a human looking, and its two surfaces are prepared ALONE
before they ever meet (§3.1). So a pair is prepared as **four jobs**,
each named like the project folder it works in (`ARCHITECTURE.md` §1):

- **prep_surf1** and **prep_surf2** (GPU, INDEPENDENT of each other):
  each prepares ONE surface of the pair. It relaxes the bulk of BOTH
  materials (§2.2 — both are needed to solve the shared cell, and the
  relaxation is cheap and deterministic), solves the shared lateral
  cell (§2.3), builds ITS half in that cell (§2.5), roughens it with
  the cascade (§3), HEALS it in the same session (§3.4), and runs the
  **activation gate** (§3.5) on the healed half — the human-inspected
  checkpoint, before any assembly. The gated, healed half is the job's
  DELIVERABLE, written into `prep_surfN_<label>/` for the bond job to
  read. Because the two jobs share no state until assembly, they may be
  submitted at once and run side by side; this is the separate-job
  fan-out `ARCHITECTURE.md` §4.3 kept available through the files,
  arriving at no cost. (From 2026-08-28 to 2026-08-30 one `activate`
  job prepared both halves serially and assembled them.)
  Each prep job needs its surface's ENVIRONMENT LIBRARY (§3.5), which
  the bootstrap builds from the recipe in the same prep folder. That
  build is a fifth kind of script `prepare` writes — one per surface,
  `prep_surfN_<label>.library.slurm` — but NOT a fifth job of the pair
  chain: it runs on the bootstrap's own clock, once per recipe, and is
  not a `sabsim run` flag (`ARCHITECTURE.md` §4, PSEUDOCODE §14.6). The
  guide lists it as step 0, and the script refuses to overwrite a
  library that is already there (the deliverable is precious, §10.8):
  a person who has changed the recipe moves the old library aside and
  resubmits. So the chained form is six jobs — two library builds,
  two preps held on them, bond, analysis — and a second submission of
  the same chain skips the two builds in seconds (added 2026-09-10,
  replacing the hand-written harness of LEDGER T-38/T-42).
- **bond** (GPU): read both halves, check that their lateral cells
  agree, bring them together at the press-start opening (§2.6), run the
  one-time lateral cell relax (§5.6), then press, settle, and pull (§5),
  with the committee of MLIP models evaluated together in one process.
  It also writes the stage ledger of §5.5.
- **analysis** (ordinary / CPU): measure (§6). Split into its *own* job —
  not folded into bond — because the all-electron characterization (§8)
  will eventually be heavy, and drawing the boundary now avoids moving it
  later.

This is **mirrored in `ARCHITECTURE.md` §4.3**, since updated from the
single-job chain it first described. §4.3 was written to *allow* the
split — every stage hands off through a file on disk, so a boundary may
fall between any two stages — and this section fixes where the
boundaries actually fall.

**The committee runs within the one bond job.** All committee models are
loaded together in the single bond process, evaluated on each
configuration, and their disagreement *is* the live uncertainty signal
(§7.3). There are no per-model submits. Committee size raises the bond
job's per-step cost — which bears on the walltime of §10.6 — but never
adds jobs.

### 10.3 One ordered job registry, read by both commands

The real safeguard against the two commands drifting apart is that the
set of jobs is defined **once** in code, as a small **ordered registry**:
prep_surf1 → prep_surf2 → bond → analysis, each entry naming the job,
the pipeline stages it runs, the folder it works in, and the abstract
resource *class* it needs (which the deployment file resolves to a real
partition). The two prep entries are marked as a **parallel group**: the
order between them is a listing order, not a dependency, and bond
depends on both. *Both* the `run` selector's flags and the `prepare`
writer read from this one registry.

The payoff is extensibility. Inserting a new kind of job later — say, a
relaxation between prep and bond — is a one-line edit to the registry,
and the flags, the written filenames, the guided index, and the run
selector all follow from it. No truth about *what the jobs are and in
what order they run* is ever written down twice, which is why the CLI
surface (flags versus a valued option) barely matters: neither form
scatters that truth.

### 10.4 The run selector

`sabsim run` accepts **at most one** of four mutually exclusive flags —
`--prep-surf1`, `--prep-surf2`, `--bond`, `--analysis` — each selecting
exactly the stages that job owns, per the registry. Giving **no** flag
runs the whole pair chain end to end, the two preps in turn; that is
what a login-node `--dry-run` exercises and what a small local test
uses. There is no selector for "which pair": a project holds exactly
one (§1.1), so the flags say only which of its jobs to run.

The flags deliberately carry no category noun — there is no
`--stage bond`. Dropping the noun lets the verbs stand alone, and it
keeps the word "stage" out of the CLI entirely, since that word is
already overloaded across the eight pipeline steps and the finer internal
stages.

### 10.5 What `prepare` writes into each script

A generated script's "get the machine ready" preamble is kept small and
boring, because most of what a run needs is already true by virtue of the
environment being installed and activated — not restated in every script.
"Getting ready" is three kinds of thing, each sorted to one home:

- **The three location roots** (scratch, shared, personal override) are
  **baked in as resolved values** — a frozen snapshot, *not* a line that
  re-reads the shell rc at run time. This is §1.4's "emit a complete
  file" applied to deployment: the script names the exact locations it
  used, so it reproduces months later and does not depend on the rc still
  existing or being unchanged at submit time. Their proper definition
  home is the sourced rc (`.sabsim/sabsimrc`), which is where `prepare`
  reads them from. The accepted cost: changing a root means regenerating.
  - **A fail-fast gate.** Before writing anything, `prepare` checks that
    the three roots actually resolve. If they do not, it **stops and
    reports on the login node** — where the message is readable — rather
    than emitting scripts that would fail on a compute node an hour into
    a job. This is the same discipline as the reference check (§1.5)
    and the activation gate (§3.5): catch the missing piece early,
    name it, and refuse.
- **The outside tools to switch on are per kind of job**, not machine-wide. A
  prep script switches on only the molecular-dynamics engine, bond only the GPU
  force-model engine, and analysis only what its measurement needs. This
  **reshapes the deployment file**: the tool list moves out of the machine-wide
  `[hardware]` inventory and into each per-kind `[usage.*]` block, so a script
  loads exactly what its job needs and nothing that could conflict with it. It
  matches the by-kind routing the file already uses for partitions. **What
  analyze needs is broader than electronic structure, and in v1 it is nothing
  extra.** Analyze owns the whole measurement tail: the mechanical
  work-of-separation (M1, §6), the structural characterization (radial
  pair-distribution, structural descriptors, §8/§12), and the report plots
  (force and stress/strain curves). All of that is the already-installed Python
  stack (numpy / matplotlib / ASE), so v1 loads NO dedicated science module —
  which is why `[usage.analysis]` carries `modules = []`. The one genuinely
  electronic-structure piece is the all-electron characterization, and it is
  Tier-B: Imago/Kaleidoscope owns its own Parsl + SLURM submission (§4.1), so
  analyze does not load it as a module. A DIRECT electronic-structure tool
  would join the analyze block only if such analysis were ever run OUTSIDE that
  Tier-B loop.
- **Everything else gets no home in the script.** The gate's reference
  files are found through the shared-data root (they are reference data,
  in §3.5's registry idiom); the Python interpreter and the launcher come
  from the activated install. None of these is hand-named in a generated
  script. A prep job's two run-time DATA inputs — the universal model's
  weights and the environment library (§3.5, 2026-08-29) — are the
  weights named by `sabsim.toml` as a root-relative path and the library
  found in that surface's preparation folder,
  `prep_surfN_<label>/environment_library.toml` (§1.2) — and
  `prepare`'s fail-fast gate resolves BOTH surfaces' inputs before
  writing, so a missing library is reported on the login node exactly as
  a missing weights file is (§1.5's third validation phase).

**Filenames are semantic and carry no ordinal number** — a script is
named for the folder its job works in (`prep_surf1_si.slurm`,
`prep_surf2_sio2.slurm`, `bond_si_sio2.slurm`, `analysis_si_sio2.slurm`;
`ARCHITECTURE.md` §1), so the name says the work AND the surface or
pair it is done to. Ordinals were rejected because inserting a job
between two existing ones would break the numbering.
Order lives in one place instead: a short, descriptively named guided
index the writer drops beside the scripts (a submission *guide*, never
`index` or `readme`), reinforced by each script printing, on success,
what to check and which job to submit next. That serves the hand-driven,
checkpoint-by-checkpoint model directly. (The command verb `run` is kept
— a common, understood word, like `git commit` — since the naming rule
governs files, not verbs.)

### 10.6 Walltime — a number the person provides, and one cheap check

Every job must declare a wall-clock limit up front, and for most jobs any
comfortable number will do. The bond job is the interesting one, because
part of its length is *physics*: §5.6's pull consumes pull-distance ÷
pull-rate of simulated time, and that cannot be shrunk without changing
the experiment.

The design deliberately does **not** have the writer predict that length.
Predicting simulation time is fragile, and it would make the thin
sequencer clever about physics it has no business modeling. Instead the
requested walltime is a value the **person provides**, in the deployment
file's per-kind `[usage.*]` block, and refines with a little experience —
after a few runs, the right number for a given pull is plain. §5.6's
pull-distance ÷ pull-rate relation stays, but as the human's **estimation
guide**, not something the software computes; this reframes §5.6, which
previously read as though the tool budgeted the number.

The **MPI rank count is person-provided the same way**, and for the same
reason. The parallelism is LAMMPS domain decomposition over one cell, so
what matters is atoms *per rank*: too few ranks and the run is slow, too
many and each rank's ghost-atom halo dwarfs the atoms it owns, so the run
is slower *again*. That atoms-per-rank sweet spot is a per-kind tuning
choice the person makes — not something the writer should derive by
filling every core on a node. So each `[usage.*]` block also names a
`tasks_per_node` (MPI ranks per node); the writer emits it verbatim and
predicts nothing, exactly as it does for walltime.

**The per-node memory request is person-provided in the same spirit**, and
it earns its own knob for a concrete reason: a job that names no `--mem`
does not get "all the node's memory" — it inherits the partition's *small
per-job default*, and that default OOM-killed the activate cascade about
44 minutes in, even though the run's true peak was a modest ~306 MB
(recorded as `T-E5-ACTIVATE`, which only went green after a `--mem` was
added by hand). So each `[usage.*]` block also names a `memory` amount (a
`{ value, unit }` size, like the walltime), and the writer emits it as
`#SBATCH --mem`. It is a *ceiling*, not a prediction — the person sets a
comfortable headroom for the kind of job, and the writer neither models
the footprint nor fills a default, exactly as with walltime and ranks.

**The accelerator request is person-provided in the same way**, and it is
stated on *every* job — `0` included — rather than left absent, so "this
job needs no GPU" is a choice on record and not a silent default (the same
reasoning as the empty `modules = []`). Each `[usage.*]` block names a
`gpus_per_node`; the writer emits `#SBATCH --gres=gpu:N` only when it is
positive, so a CPU job (activate, analyze) gets no `--gres` and is never
routed to a GPU node, while the bond job asks for its committee's GPUs
verbatim. As with ranks and walltime, the writer requests what the person
wrote and predicts nothing.

**Two cheap checks earn their place**, precisely because they predict
nothing — each only compares two numbers already written in the
deployment file. The first is walltime: each hardware partition already
names a `max_walltime` ceiling (the longest job that pool will ever
allow), and if a requested per-kind walltime exceeds it, `prepare`
**stops and says so**, instead of letting the scheduler bounce the job
after submission. The second is its GPU twin: a partition names its
`gpus_per_node`, and a job asking for more accelerators per node than the
partition has — or for any GPU from a partition that declares none — is
refused the same way. Both are symmetric with the roots gate of §10.5: a
static, login-node refusal with a readable reason.

When a run *does* exhaust its walltime, the response is neither to
silently shorten the pull — that would report a different measurement as
if it were the one asked for — nor to have the writer auto-split the job,
which is machinery we do not have. It is the human resubmitting a
**continuation**: noticing that the job stopped short and picking it up
where it left off. The completeness gate of §5.6 is what makes this safe
— an unfinished trajectory is caught and never reported as-is (prior
art's headline number came from a trajectory that stopped at 122,500 of
150,000 steps). That continuation is the within-run resume built in §11,
which restores an interrupted pull and carries it to its end; this section
relies on it, and §11 is where it is specified.

### 10.7 What we keep, what we replace, and v1

**Keep:** the throwaway field scripts under `jobs/*` as the honest
starting template — they already enumerate exactly what a real submission
needs (partition, account, task count, walltime, the potentials path, the
interpreter, the launcher, `PYTHONPATH`, the scratch root, and the
`mpirun -np N python -m sabsim run` line); the three-tier routing and the
`[hardware]` / `[usage.*]` split (`ARCHITECTURE.md` §4.1); and the
roots-via-sourced-rc mechanism.

**Replace:** the hardcoded partition / account / paths of those throwaway
scripts (→ values `prepare` fills from the deployment file); one coarse
job per pair (→ four per-kind jobs, two of them independent, revising
`ARCHITECTURE.md` §4.3);
a machine-wide tool list (→ per-kind `[usage.*]` tool lists); any notion
of the tool submitting or babysitting jobs (→ a writer plus a human); and
a tool that budgets walltime (→ a human-provided walltime with a cheap
ceiling check).

**Frozen for v1:** four jobs named prep_surf1 / prep_surf2 / bond / analysis
(revised 2026-08-30); `prepare` writes and the human submits; the ordered
registry as the single source of job identity and order; baked-in frozen roots
guarded by a resolve-or-refuse gate; per-kind tool lists; user-provided
walltime with the partition-ceiling check; and overrun handled by human
continuation. DESIGN follow-ons: the installer plus INSTALL/README that emit
the deployment rc (the packaging story); and whether a per-project walltime
override on `prepare` is worth adding once projects vary widely. (The
restart/resume mechanism the continuation relies on is now built as §11.)

### 10.8 Deliverables beside the inputs, bulk on scratch (2026-08-30)

Each job works in the scratch mirror of its own folder —
`intermediate/prep_surf1_si/`, `intermediate/bond_si_sio2/`, and so on
(`ARCHITECTURE.md` §4.1) — and that is where the bulky, regenerable
files live: LAMMPS data files and inputs, the trajectory dumps of §9.3,
the engine logs. The job's **deliverables** — the small files another
job or a person reads: the gated healed half a prep job hands to bond,
the assembled-pair and pull manifests, the stage ledger of §5.5, the
gate reports, and `measure_vector.toml` — are written into the
project's own stage folder (`prep_surf1_si/`, `bond_si_sio2/`,
`analysis_si_sio2/`). The rule is a size-and-value rule, not a file
type: a project folder copied WITHOUT following the `intermediate`
link must still hold every input needed to reproduce the pair and
every number that came out of it, and nothing that could be
regenerated from those. Each deliverable records which run of the job
produced it (the resolved scratch path and the scheduler's job id), so
a manifest always names its bytes (§1.6, `ARCHITECTURE.md` §4.2).

**A rerun never overwrites.** Submitting the same job again gives its
work a fresh subfolder of the job's intermediate folder, named by the
scheduler's job id (`run-<job id>/`; a dated name when no scheduler is
involved), and the deliverable in the project folder is replaced only
when the new run finishes — it then names the new run. The previous
run's files stay where they were. This is what let LEDGER T-40 keep a
failed pull beside the corrected one for comparison, and it is the
general case: a rerun is evidence about the earlier run, which is
destroyed if the rerun writes over it.

### 10.9 `init` — the generator §1.4 promised (2026-09-07)

§1.4 forbids a hidden default and pays for that with a promise: the
defaults exist as a **generator**, a command that writes a complete,
editable input for the person to start from. Until now that generator
was a person copying `share/templates/` by hand — and a student's first
hour with the tool was spent learning which four files go where and
what a silica recipe changes from a silicon one. `sabsim init` is that
generator made a command:

```
sabsim init [<project folder>]        # default: the current directory
```

It writes the project folder of `ARCHITECTURE.md` §1 from the tracked
templates, and it obeys three rules.

**It never overwrites.** Each file it would write is written only if
it is missing; an existing file is reported and left exactly as it
is. So `init` is safe to run again in a folder that is half made —
after a person has edited `sabsim.toml`, say — and the second run
adds only what the first could not.

**It reads the project file it wrote to learn the rest.** The four
stage folders are named from the two wafers' material labels
(`prep_surf1_si/`, `prep_surf2_sio2/`, ...), so `init` writes
`sabsim.toml` and `deployment.toml` first, then reads the two
`material` labels back out of `sabsim.toml` and makes the folders that
pair names. This is why the two-pass use works: run `init`, edit the
wafer tables to the pair you actually want, run `init` again, and the
folders follow the edited labels. Reading uses the plain TOML parser,
not the full validating loader, because a file the person is midway
through editing must still yield its labels.

**Each surface gets a recipe for ITS material.** A prep folder needs a
force-model recipe (§4.8) before its environment library can be built,
and the recipe differs per material in a known set of lines (species,
domain, gate reference, descriptor weights, crystal, melt temperature,
face, pseudopotentials). Those differences are not for a student to
rediscover: the templates hold one recipe per material we have built a
library for, under `share/templates/recipes/<label>.toml`, keyed by
the lower-cased material label (`si.toml`, `sio2.toml`). `init` copies
the matching one into each prep folder as `recipe.toml`, rewriting its
`[generation_plan] project` line to point at THIS project's file. A
material with no recipe of its own gets the silicon recipe as a
starting point and a printed notice saying so — a start, in the open,
never a silent guess.

**The pair can be named on the command line.** Which two materials
to bond is THE science decision of a project, so it is the one thing
`init` asks for rather than guesses:

```
sabsim init si_sio2 --materials Si SiO2
```

The two labels are looked up in the MATERIALS CATALOGUE,
`share/templates/recipes/materials.toml` — one entry per material the
repository ships a recipe for, holding exactly what the project file's
wafer table needs (the canonical label, the crystal file, the human
structure label, the bonding face) and which recipe template is that
material's. `init` writes the template project file and then sets the
two wafer tables from the two entries, so a person never types a
crystal path for a material we already know. The match is
case-insensitive (`sio2` finds `SiO2`) and the CANONICAL spelling is
what gets written, because the label is also the prep folder's name.
Run with no `--materials`, `init` writes the template pair and prints
the catalogue, so the person sees what is on offer before editing. A
material that is NOT in the catalogue is refused with the catalogue
printed, not written with a guessed crystal: `init` without the flag,
then editing the wafer table by hand, is the honest path for a new
material — and adding its entry and recipe to the catalogue is how it
stops being new.

What `init` does NOT do is as deliberate. It does not run the
bootstrap (a compute-node job), does not write the environment
library, and does not call `prepare` — each of those reads a file the
person is expected to look at first. It writes inputs and prints what
to edit and what to run next, and stops. The generated project is
complete in the §1.4 sense (every knob written) and wrong in the
science sense until the person has read it — exactly the relationship
a template is meant to have with its user.

### 10.10 `setup` — the install walked through, and the rc written (2026-09-10)

The one file the install could not generate was the shell rc,
`.sabsim/sabsimrc`, which must be live BEFORE Python starts because it
names the install itself (`ARCHITECTURE.md` §4.1). It was "copy an
existing one and edit the paths" — the same hand-copying `init` just
removed from the project side. `sabsim setup` is the generator for it,
and a checklist around it:

```
sabsim setup [--scratch PATH] [--share PATH] [--venv PATH]
```

It runs from the Python environment the person has just built, and it
reads its own situation rather than asking: which clone this package
is installed from (the editable install's pointer), which interpreter
prefix it is running under (the venv), which conda environment sits
beneath it, and what the three location roots currently are. It then
reports each layer of the install as PRESENT, MISSING, or WRONG, with
the exact command that fixes a missing one — the conda environment,
the venv, the engine bundle, a writable scratch root — and, crucially,
WRONG when the venv's editable install points at a clone other than
the one `setup` is run from: that is the mistake a student makes by
sourcing a lab-mate's rc, and it silently runs the wrong tree.

Then it writes `.sabsim/sabsimrc` from the template, never
overwriting, with each value taken in order from the flag, from the
variable already set in the environment, or from the template's
worked example — and it SAYS which, per value, so an example path that
was not edited is reported as such rather than trusted. It builds
nothing itself: the conda environment and the venv are hour-long steps
a person should launch knowingly (§10.1's rule that the tool writes
and the human runs). It ends by printing what to do next: source the
rc, run the tests, `sabsim init`.

## 11. Resuming an interrupted run

The clock, not the physics, is what most often cuts a run short. §10.6
made the deployment side of this a person's job — the walltime is chosen
by hand, and a run that overruns is picked up and continued rather than
silently shortened — and it named the mechanism that continuation leans
on but left it unbuilt. This section builds it: how a run the scheduler
killed partway is resumed and carried to its proper end, so that the
completeness gate of §5.6, not the wall-clock, is what certifies a run
finished.

The one run that matters here in v1 is the **pull**. Its length is partly
physics — §5.6's separation consumes pull-distance ÷ pull-rate of
simulated time, which cannot be shrunk without changing the experiment —
so it is the run most likely to meet the wall before it meets its natural
end. The press and the settle are short and rarely overrun; the mechanism
below is written so they can adopt it later, but v1 makes only the pull
resumable.

### 11.1 A run's progress lives in two places

It is tempting to think a saved simulation state is enough to continue:
restore the atoms and their velocities, press go. For the pull it is not,
and seeing why fixes the whole design. The pull advances in short bursts,
and after each burst it records, in ordinary program memory, the grip
displacement, the pulling force, the interface opening, and the count of
bonds still bridging the gap. Those running lists are not decoration — the
final force-versus-displacement curve and the separation point are built
from them at the end. Two more facts hide in the same loop: the
displacement is currently computed from the **burst counter**, which a
fresh process resets to zero; and the **starting atom count** — the
baseline the §5.6 completeness gate checks against, since atoms driven out
of the box are silently deleted — is measured once, at the top.

So a resume that restored only the simulation state would restart the
burst counter at zero, desynchronizing the reported displacement from
where the grip physically sits; it would have lost the accumulated record
the final curves are made of; and it would re-measure the atom-count
baseline against an already-depleted box. The progress lives in two places
at once — the engine and the program — and a resume that saves only one of
them silently corrupts the measurement.

### 11.2 A checkpoint is a matched pair

The design follows directly. A checkpoint is **two artifacts written
together**: the engine's complete saved state, and a small **ledger** of
the run's progress so far — the accumulated displacement / force / opening
/ bridge record, the starting atom count, and how far along the run is.
Neither is useful without the other, so they are written as a pair and
restored as a pair.

Two rules keep the pair honest. First, the run's progress is keyed to the
**engine's own step count**, which a saved state preserves, and never to
the burst counter, which it does not — so the restored displacement lines
up with the restored atoms. Second, because the engine's state is saved on
a coarser cadence than the ledger is appended, a resume may find a ledger
that runs a few bursts past the last saved state; it **reconciles** by
dropping the ledger entries beyond the saved step, so the two agree before
the run goes on. The saved state makes the physics exact across the seam;
the ledger — a few short lists of numbers — is what makes the resumed run
the *same* measurement rather than a fresh one welded onto old dynamics.

### 11.3 Fresh or resuming is decided by what is on disk

The pull needs no new flag to know which case it is in. The pull is run
as a **ladder of rungs**, one per rate (§5.4); each rung gets its OWN
directory and checkpoints there independently, so a rung's "own scratch"
is its directory and resuming one rung never touches another. At its
start a rung looks in that directory for a checkpoint pair. Finding none,
it begins normally and starts writing them. Finding one, it restores the
engine, reloads and reconciles the ledger, and continues from there to
the end. The same command that ran the pull the first time resumes it the
second; the difference is entirely in what is already on disk — the same
discipline the stage handoffs already follow (`ARCHITECTURE.md` §4.3).

### 11.4 The trust alert: warn, and stop

Resuming reuses what a previous run left in a directory, so it owes one guard
against the rare mistake of continuing the *wrong* run — a directory in which
something genuinely different ran before. The checkpoint therefore carries a
**hash of the run's inputs**, drawn from the pair's content fingerprint (§1),
the identity of the upstream artifact the pull reads, and the **pull rate**.
The rate is in the hash because the rungs of one pair share both the
specification fingerprint and the single settled reference they all restore
from, so the rate is the only input that tells them apart; folding it in means
a checkpoint carried into the wrong rung's directory is caught rather than
silently continued. On resume, if the current inputs hash differently, the run
**warns and stops**: it refuses to continue until the person confirms with an
explicit override, rather than quietly stitching new inputs onto old dynamics.

This is a guardrail, not a correctness gate, and it is mild in spirit even
though it stops. In practice it is hard to resume the wrong run by
accident, because the checkpoint sits in the run's own directory and that
is exactly where the resume looks. The warning is there for the person who
truly changed something and forgot, and the stop is what makes sure the
warning is seen rather than scrolled past. The exact fields the hash
covers ride on the same open question as the fingerprint itself (§1.8's
follow-on): what counts as a difference that ought to matter.

### 11.5 Completeness is judged on the whole, not the pieces

Resuming changes nothing about how a run is judged finished. The §5.6
completeness gate already asks whether the trajectory reached its target
and whether the atom count was conserved; it does not ask, and need not
care, how many submissions it took to get there. A pull that reaches its
end across two or three continuations is complete; one that still falls
short is caught exactly as before and never reported as-is. The one thing
resuming adds is a note in the provenance record that the run was
continued — and, if an overriding of the trust warning ever happens, that
too — so the history stays honest about how the number was produced
(`VISION.md` goal 3).

### 11.6 What we keep, what we replace, and v1

**Keep:** the durable file handoff that already lets a finished stage
survive a crash (`ARCHITECTURE.md` §4.3); the §5.6 completeness gate and
its atom-count baseline as the real arbiter of "finished"; the §1 content
fingerprint as the material the trust hash is drawn from; and the manual
`jobs/si_si_e2e/rerun_back_half.py` as the honest precedent for resuming
at a *stage* boundary — the coarse cousin of the within-run resume built
here.

**Replace:** the non-answer of raising the walltime and re-running the
pull from zero, which only meets the same wall again (→ a pull that
continues from where it stopped); and the silent assumption that a
process's in-memory progress is safe to lose (→ a progress ledger kept on
disk beside the saved state).

**Frozen for v1:** the pull is the only resumable run; a checkpoint is the
matched pair of saved engine state and progress ledger, keyed to the
engine's step count; a resume is chosen by the presence of that pair, with
no new flag; and a hash mismatch warns and stops until explicitly
overridden. DESIGN follow-ons: extending the same mechanism to the press
and the settle should they ever need it; the exact fields of the trust
hash (with §1's fingerprint definition); and the checkpoint cadence — how
often the engine state is saved — an engineering choice (it sits with the
chunking controls, not the physics knobs; the answer is invariant to it),
balancing work lost on a kill against time spent writing
state.
