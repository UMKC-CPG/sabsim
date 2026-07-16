# Design

> **Document hierarchy:** VISION → ARCHITECTURE → **DESIGN** → PSEUDOCODE
> → Code. For goals and principles, see `VISION.md`. For repository layout
> and module map, see `ARCHITECTURE.md`.

> **Prior art — read before writing the relevant sections.** Several
> algorithms this document needs already exist, and some now run, in
> Sunita's `bond_debond` pipeline: the reusable kernels are catalogued in
> `PRIOR_ART.md` §1.2, and the newer worked examples plus current status
> are in §1.5. Lift or adapt rather than re-derive:
> - **Surface amorphization (§3):** a classical + ZBL Ar-bombardment
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

## 1. Member specification and settings layer

This section designs the specification a user writes to point the
pipeline at a study, and the rules that keep it honest. It was written
last on purpose. §2 through §7 each deposited knobs, tolerances and
seeds as they went, and only with all of them on the table does the
shape of the settings layer become visible — it is not one list but
five, and the divisions between them carry meaning.

Prior art states the problem by contradiction. Its `primeinput.py` reads
a member's parameters out of the directory path it happens to be
sitting in
(`jobs/<stage>/<material>/<layer>/<energy>/`) and bakes a partition
name, a personal email address, and module versions into the scripts it
emits (`PRIOR_ART.md` §1.2 item 7). SABSIM inverts this completely:
**the configuration is an object, and the directory is an output.**

### 1.1 The object is a study, and a member still stands alone

The naive top-level object is a member: one material pair, one protocol,
one number out. But §7.4's headline criterion is a **ratio** — the work
of separation of the Si/SiO₂ pair divided by that of the Si/Si reference
— and a ratio is a property of a *pair* of members, belonging to neither
one. Give the settings layer only members and the primary measure has
nowhere to live. This is §2.1's discovery in a different costume: the
object worth modelling sits one level above where you would first put
it.

So a **study** names its members and declares the **relations** among them
— which member is the subject and which the reference. Beneath it a
**member** is one material pair under one protocol, and beneath that a
**realization** is one seed.

But a member must remain **self-contained and independently
reproducible**, executable on its own and identical whether or not a
study ever mentions it. A study is a composition over members, not an
owner of them, and it may be assembled after the fact from members that
already exist.

That freedom has a price, and paying it is the interesting part. §7.4
trusts the ratio because **the systematic errors common to both members
cancel to first order** — the pull rate, the cell size, the thermostat,
the mismatch of timescales. Cancellation requires that those systematics
actually be shared. Two members made with different potentials, or
different press loads, cancel nothing, and their ratio is worthless.

**A relation declares what it varies and what it holds fixed.** It is
tempting to write the precondition as a fixed rule — *the members must
share a potential and a protocol* — but that rule forbids one of the
studies we most want to run. Comparing two **protocols** on the same
material pair (an activation-dose sweep, a press-load sweep) is a study
in exactly the same sense, and there the protocol is the thing that must
differ. The precondition cannot be a property of the settings layer. It
is a property of **each relation**.

So a relation names two sets of fields:

- its **contrast** — the fields it deliberately varies. This is the
  independent variable, the reason the comparison is being made at all.
- its **controls** — the fields it intends to hold fixed, checked
  rather than assumed.

v1's ratio contrasts the **material pair** (Si/SiO₂ against Si/Si) while
controlling the potential and the protocol. A dose sweep would contrast
the **activation fluence** while controlling the material pair and
everything else. Same machinery, opposite fields.

**Report, never restrict.** Nothing in this section may prevent a member,
a study, or a comparison from being performed. When a relation's
controls disagree, or when it carries more than one contrast and is
therefore *confounded* — a change in the result attributable to neither
variable — the relation is still computed, still reported, and still
carries its full difference set. What changes is only whether the
**gate** is willing to issue a verdict on it.

Refusing to evaluate and refusing to certify are different acts, and
SABSIM performs only the second. §7.4's automated criterion is a narrow
instrument, competent to judge one particular ratio under one particular
set of controls; `unresolved` is a statement about **that instrument's
competence**, never about whether a number may exist or be looked at.
The scientist who runs many material pairs many different ways is the
person this project is built to serve, and they routinely learn from
comparisons no automated criterion is qualified to bless. Handing them
the number, the contrast, and the difference set is the whole job. A
machine that declines to compute what a scientist asked for, on the
grounds that it would not know how to grade the answer, has mistaken its
role.

**Every relation emits a difference set.** Controls agreeing is not the
same as the members being alike, and the gap between those two statements
is where a misleading comparison lives. Every field that differs is
therefore reported alongside the value, sorted by *why* it differs:

- **Contrasted** — it differs by design. This is the signal.
- **Entailed** — it differs *because* of the contrast, and cannot be
  removed without removing the contrast. Si/Si has no lattice mismatch
  and Si/SiO₂ does; that residual-strain systematic is precisely the
  term §7.4 would like to see cancel, and it cannot, because you cannot
  contrast two material pairs without contrasting their mismatch. An
  entailed difference is not a mistake. It is the **irreducible price of
  the contrast**, and the relation is marked as only *partially
  cancelling* on its account.
- **Incidental** — it differs for no declared reason. These are the
  dangerous ones, and naming them that way is the point: an incidental
  difference is an uncontrolled variable that nobody decided to vary.

Note which category deserves suspicion. An earlier draft of this section
called the last group "believed harmless," which is backwards — a
difference nobody intended is the least examined thing in the
comparison, not the most. **SABSIM cannot know in general which
differences break a cancellation**; that judgment rests on physics the
settings layer does not encode. What it can do is refuse to hide them.
A reader given the full difference set can decide whether a ratio, or
any other comparison, means what it appears to mean. A reader handed a
bare number cannot. The obligation belongs to *comparison* itself, so
every relation we add later inherits it.

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
  per-material code. What we are studying.
- **Protocol** — the activation species, energy, angle of incidence and
  fluence; the press mode, load, depth and duration; the hold
  temperature; the pull rates of §5.4's ladder. How the experiment is
  performed.
- **Numerical** — tolerances, cutoffs, convergence criteria, the
  committee stride and persistence window of §7.3, the significance
  levels of §7.5, slab thickness, cell size. How carefully we compute.
- **Ensemble** — the master seed and the realization count.
- **Deployment** — resource class, node counts, walltime, modules. This
  lives in a *separate document* (`ARCHITECTURE.md` §4.1) and the member
  specification cannot express it at all. That document is a single
  machine-local config with two sections — a hardware inventory (the
  per-cluster swap unit) and a per-**kind-of-job** usage map (§4.1) — and
  it is the ONLY input route outside the study spec. The strict-vs-layered
  input question is resolved in favor of strict: the CWD study
  specification carries material, protocol, numerical, and ensemble
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

### 1.5 Units are carried, and validation happens twice

Every dimensional setting **names its unit**, exactly as §6.6 requires
of every measure. Fluence is in ions·Å⁻² — cell-size-independent, so the
impact count follows from the fluence and the surface area rather than
being specified (§3.2). No reader should have to trust a conversion
factor typed into a report string.

Validation splits in two, and the split is not arbitrary — it is the
same shape as §7.2's two-phase potential gate, and for the same reason.

- **Static validation, at load.** Types, units, ranges, completeness,
  and the consistency requirements that need nothing from a running
  pipeline. The sharpest of these: **the union of the pair's species
  must equal the potential's global type map** (§4.3), which is
  STRUCTURAL 1a enforced at the earliest possible moment rather than
  discovered at an intermixed interface.
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
two members are worth comparing is a scientific judgment, made by a
person, downstream, with the difference set in hand. Whether a member
can be
performed at all is a mechanical question, answered here.

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
scripts (→ a separate deployment document, §4.1, which the member spec
cannot express); hand-typed lattice constants (→ derived from the
potential, §2.2); hidden defaults (→ the loader rejects an incomplete
specification); an unnamed, unrecorded protocol (→ inline values with a
content fingerprint); and numbers that cannot say where they came from
(→ the specification is reconstructible from any output).

**Frozen for v1:** the study is the **Si/SiO₂ facing pair plus the Si/Si
same-material reference**, sharing one potential and one protocol, with
the ratio between them as §7.4's criterion. Every protocol knob takes a
single value — written down, not hardcoded — and the design already
admits distributions (an energy or angle spread) without changing shape.
Iterating over composition, dopant, activation level, pressure,
temperature or crystal face is the outer-loop sweep deferred in
`TODO.md`; §1's contribution to it is that a sweep becomes a set of
specifications rather than an edit to the machinery.

**Serialization format — TOML** (ratified 2026-07-13), for both the
study input file and the deployment rc file. TOML was chosen for its
readable, typed key/value tables and unambiguous parse; a change would
need a concrete blocker. The **schema mechanism** built on top of it
(how required-versus-optional keys are declared and validated) is still
a follow-on.

**Still DESIGN follow-ons:** the schema
mechanism; the exact fingerprint definition (which fields are included,
and how a value declared irrelevant to comparability is excluded); the
initial classification of difference-set fields into
weakens-the-comparison and believed-harmless, which is a physics
judgment and will need revisiting as relations are added; how relations
beyond `ratio` are expressed; and the values themselves. That last one
is not a small matter — **every numeric follow-on left open by §2
through §7 lands in this file**, and §1's real service is to have given
them a single, inspectable home.

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
  the member's provenance record (`VISION.md` goal 3) and passed forward
  as
  a training-configuration dimension the MLIP must cover (STRUCTURAL 1b);
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
the current production potential** — the same committee that will run
steps 4, 6 and 7. Two consequences follow:

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

**Cold start.** At the very beginning there is no production potential to
relax under — the bootstrap (§4.5) has not yet trained one. So "the
current potential" means the **classical/seed model** that opens the
bootstrap: the first cell is relaxed under it, giving a crude but
self-consistent lattice, and §2.2's rule is re-applied under the trained
committee the moment it exists, re-deriving the cell then. The step is
identical; only the model beneath it changes. This makes "**derive the
lattice by relaxing the bulk under the current model**" a first-class,
named pipeline step in its own right, not a hidden preprocessing detail.
Its first *real* execution is deliberately the **smallest** use of the
LAMMPS execution layer (`ARCHITECTURE.md` §4.1) — a few-atom bulk relax —
and that is exactly the moment the walking skeleton's hardcoded stand-in
lattice is retired: not smuggled into the plumbing-only skeleton before a
force engine exists, and not left hardcoded once one does.

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
identity tiling, zero twist, and exactly zero strain. That makes the
same-material reference member (`ARCHITECTURE.md` §2.3) double as the
matcher's null test.

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
  stiffer, thicker slab moves less. The biaxial modulus comes from the
  same elastic constants the potential-quality gate already computes.

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

**Termination is chosen by surface energy.** Prior art takes
`sym_slabs[0]` with the comment "first candidate is sufficient" — the
first entry of a list, in list order. Where a face admits several
terminations, SABSIM enumerates them and selects by computed surface
energy, which the potential-quality gate already needs anyway.

**How the surface energy is computed.** It is the energy cost, per unit
area, of creating the face — cutting the crystal breaks bonds that were
satisfied in the interior, and that cost per area is what we compare.
For each candidate termination, build a slab, relax it under the current
model (the classical/seed model at bootstrap, the trained committee
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
between the two dividing surfaces. After placement the minimum
cross-slab atomic distance is checked; if it violates the floor, the gap
is backed off and the adjustment is recorded, rather than aborting the
member as prior art does.

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
each is a study-input knob a user may change later. Still DESIGN
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
classical MD, and both are just one setting of the projectile spec below.

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
- **Dose as fluence.** Dose is a **fluence** (ions·Å⁻²); the impact count
  follows from fluence × surface area. This makes activation comparable
  across cell sizes, which an impact *count* (prior art's knob) is not.
- **A recorded master seed** governs impact positions, velocities, and
  the LAMMPS seeds — both for reproducibility (`VISION.md` goal 3) and so
  the bond metric can be **averaged over amorphization realizations** by
  varying it (STRUCTURAL 4). Prior art's rewrite uses unseeded
  randomness, so its runs are not reproducible; we fix that.

### 3.3 The cascade engine — heat-sink and boundary design

This is the correctness core, and the part prior art gets wrong. The
classical + ZBL potential runs the cascade (STRUCTURAL 1b; §4.6): a
`hybrid/overlay` splice with ZBL for the short-range collision and the
config-selected classical generator (BKS or Vashishta for silica,
Munetoh-Tersoff a fallback; Buckingham for ionic) for the bonding.

The **heat-sink and boundary design** must be:

- a **frozen (or Langevin) bottom substrate layer** that anchors the slab
  and absorbs recoil, so the slab does not drift as a whole;
- a **`p p f` (or shrink-wrap) z-boundary** so sputtered atoms *leave*
  rather than wrap into a periodic image — a true free surface;
- a **Langevin border thermostat** on the lower/side region that drains
  cascade heat at a physical rate, while the interior evolves under
  **NVE** so the collision cascade stays ballistic, not artificially
  quenched;
- the substrate held at the target temperature between impacts.

Why this matters, concretely: prior art's whole-slab NVT over-couples to
the cascade and quenches the damage before it accumulates — its own
documented failure, worked around by detuning the thermostat to a fragile
sweet spot — and the newest tree dropped even the frozen layer and
`p p f`, so it fails to amorphize at all. The frozen-base +
border-thermostat + NVE-interior design is standard radiation-damage
practice and is robust across a *range* of energy and dose, so we design
the root cause rather than inherit a tuned single point.

**Per-impact cycle:** insert the projectile above the surface with the
spec'd velocity → NVE cascade (a few ps) → short border-thermostatted
relaxation → repeat to the target fluence. **Execution uses a persistent
LAMMPS driver** — the LAMMPS **Python binding**, held in-process across
every impact (`ARCHITECTURE.md` §4.1), *not* a fresh process plus a
full-slab disk round-trip per impact as prior art does — at the doses SAB
needs (thousands of impacts) that overhead is prohibitive.

### 3.4 The MLIP re-anneal (a SABSIM addition)

Prior art is classical throughout; SABSIM adds a stage it does not have.
After the classical cascade creates the disorder, the activated surface is
**re-equilibrated under the MLIP** (gentle, near-equilibrium) so the final
structure is MLIP/DFT-quality rather than classical-quality — the first
rung of the fidelity ladder (§4.5). This is where the classical→accurate
correction happens; validation (§3.5) runs *after* the re-anneal. Its
temperature, duration, and ensemble are design parameters; a kinetically
trapped glass will not fully rearrange, so the classical start must be a
reasonable basin (the STRUCTURAL 1b safeguards).

### 3.5 The validation gate (pass/fail, not a report)

Prior art's `check_amorphous` only *reports*: it prints a g(r) RMSD
against an optional experimental curve with **no threshold**, its
partial-g(r) pairs are hardcoded to Si/O, and its depth metric scans
top-down and stops at the first crystalline-looking layer, so it can
report 0 Å depth beneath a defective surface. SABSIM makes activation
validation a **gate** with pluggable metrics and reference data:

- **g(r) and partial g_AB(r)** with pairs *derived from the species
  present*, using the density-reference normalization prior art got right
  (the near-surface amorphous region is ~20% less dense than the crystal
  below, so the reference density must be the local slab's, not the full
  cell's — a genuinely good kernel to keep, `PRIOR_ART.md` §1.5).
- **Coordination-number distribution and per-species defect fraction**
  (generic, not Si-only).
- **Ring statistics** — absent from prior art — the network-topology check
  that separates a true amorphous network from a merely defective crystal.
- **A robust amorphization-depth profile** (disorder vs depth), replacing
  the fragile top-down scan.

Each is compared against DFT and experimental references with thresholds,
yielding a pass/fail verdict. This is the "did the surface activate, and
is its structure sane?" check that feeds the potential-quality gate
(§7; STRUCTURAL 1b).

### 3.6 What we keep, what we replace, and v1

**Keep** (re-framed, not copied): the ZBL `hybrid/overlay` splice
(channels generalized, §3.2); the density-reference g(r) normalization
(§3.5); the thermostat/timing values as a *starting range*, understood as
a symptom of the missing heat sink (§3.3); Munetoh-Tersoff as one
config-selected generator option.

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
at the cost of a bigger box); **normal incidence**; the **fluence is the
knob and the ~2–3 nm amorphized skin depth is the measured target** —
iterate fluence until §3.5's depth profile hits ~2–3 nm; **3
amorphization seeds** for the ensemble spread (the cheaper rung; more
seeds tighten the error bar at linear cost). The generator is a
config-selected classical + ZBL potential (silica per §4 and STRUCTURAL
1b); the MLIP re-anneal and the validation gate are both mandatory, not
optional. Energy, angle, and
seed count are v1 defaults, not freezes — each is a study-input knob.

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

1. **Seed.** Train an initial committee (`train_DEEPMD_ensemble_task`) on
   hand-built near-equilibrium DFT — bulk Si and cristobalite, their
   surfaces, the STRUCTURAL-4 strained substrates, and moderate-T rattled
   snapshots — enough not to explode near equilibrium.
2. **Generate the hard configs cheaply.** Run the violent Ar cascade on
   the classical + ZBL potential (CPU) to make amorphized-surface configs
   with no MLIP at all; run the interface and separation on the seed
   committee (GPU) to make pressed-interface and bond-breaking configs.
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
division of labor from §3 holds throughout: the classical potential owns
the violent cascade, the committee owns only the gentle stages, so the
species map stays {O, Si} and the model is never asked to reproduce
cascades or Ar.

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

## 5. Bond/debond MD protocol

This section designs steps 6 and 7 — pressing the two activated surfaces
together, letting them bond, and pulling them apart while recording the
force that resists. It runs on LAMMPS under the MLIP (`pair_style
deepmd`, GPU; `ARCHITECTURE.md` §4.1).

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
model — the binding runs under MPI (`srun -n N python`), so every control
decision above keys on **global, collective** quantities (a thermo `pzz`,
a summed grip force) and stays identical across ranks. The LAMMPS dump
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
  input and the approach is the response.
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
target). SABSIM thermostats **only the interior** — never the grips —
and, where any thermostatted region carries directed motion, removes the
center-of-mass bias from the temperature before applying it.

**Contact begins from a defined gap, and is confirmed by a stress.** The
starting separation is the one §2.6 established between the two
density-profile dividing surfaces, not between extremal atoms. Contact
itself is declared on a **dual criterion**, adapted from prior art's
`find_contact_step` (`PRIOR_ART.md` §1.8) — one of the few pieces of its
design worth taking: the primary test is that the gap has closed to a
threshold, and the confirmatory test is that a running average of the
normal stress has turned positive. The confirmation earns its keep,
because a gap can close on a single asperity, whereas a positive normal
stress means the two surfaces are genuinely loading each other. (Prior
art measures its gap between extremal atoms, which is exactly the
asperity failure the stress criterion guards against; we fix both.)

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

SABSIM makes the reference state a gated artifact: minimize, then
equilibrate under the thermostat, then **assert** that the net force on
each grip has fallen within the thermal noise floor and that the
potential energy has stopped drifting. If it has not, the press did not
settle, and that is reported rather than integrated over.

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
the potential's cutoff (6.0 Å for `se_e2_a`, §4.6) *and* the averaged
force has returned to zero within the noise floor. The mechanical work
integral runs from the §5.3 reference state to that point and stops;
prior art integrates the entire record, noise tail included.

**The dissipation identity is a sign check.** Step 7 also records the
potential energy of the bonded relaxed state and of the fully separated,
relaxed slabs. Their difference is the thermodynamic work of adhesion at
MLIP fidelity, which §6 computes properly; the mechanical integral minus
that difference is the energy dissipated. STRUCTURAL 2 predicts the
mechanical work is the larger. If it comes out smaller, the reference
state or the integral is wrong, and the run is rejected rather than
reported.

### 5.6 The box, the boundary, and the run that has to finish

The lateral cell is the shared coincidence cell of §2 and is **held
fixed** — no lateral barostat, or the recorded substrate strain relaxes
away mid-run and the provenance number becomes a fiction. The
z-boundary is non-periodic, with vacuum sized for the full pull distance
plus margin.

Two things are then gates rather than warnings. **Atom count is
conserved**: a non-periodic boundary silently deletes any atom that
leaves the box, so a lost atom invalidates the run. And **the trajectory
must be complete**: walltime is budgeted from pull distance divided by
pull rate, not set to a flat four hours. Prior art's headline number was
computed from a trajectory that stopped at 122,500 of 150,000 steps, in
a directory containing a file named `NOTE_INCOMPLETE.txt`.

### 5.7 Provenance is part of the measurement

Every number this stage emits names the potential generation that
produced it, the seed set, the pull rate, the press mode and the load or
depth reached, and the trajectory file it was reduced from
(`VISION.md` goal 3). The analyzer **refuses a truncated trajectory**.

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
flat walltime and a truncated trajectory (→ budgeted walltime and a
completeness gate); and a report string that names a potential the run
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
rate ladder are v1 defaults, not freezes — each is a study-input knob.
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
  the bond number is read.
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

The analyzer emits one machine-readable document per member, containing:

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
records. The analyzer resolves those needs against what the member
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

This section designs the two checks that decide whether a member is
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
§3.5 (partial g(r), ring statistics, coordination) against VASP and
experiment — must run **before the structure builder**. §2.2 makes the
builder a consumer of the potential's own relaxed lattice constants: it
matches the two surface lattices on them and records the residual strain
from them. A potential with a wrong lattice therefore builds a wrong
box, and everything downstream measures the wrong system. This half
gates the build, at the step 2/3 boundary.

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
  STRUCTURAL 1b puts the violent Ar cascade on a classical potential
  with ZBL, not on the MLIP, so **the amorphized surfaces are
  potential-independent and survive retraining untouched**. A retrained
  potential invalidates only the gentle re-anneal, the press and the
  pull. Finally, aborts are counted: repeated aborts at the same
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

Nor is the cancellation assumed to be complete. The ratio is a
**relation** in the sense of §1.1: it contrasts the material pair while
controlling the potential and the protocol. The gate checks those
controls, and reports the relation's **difference set** beside the
result.

When the controls do not hold, the gate withholds its **verdict**, not
the number. The ratio is computed and reported either way, because a
criterion calibrated for one comparison has no standing to suppress
another (§1.1). `unresolved` here means *this gate is not competent to
grade this comparison*, and it is the scientist, not the gate, who
decides what the comparison was worth.

One entry in that set is unavoidable. Si/Si has no lattice mismatch and
Si/SiO₂ does, so the residual-strain systematic that this criterion
would most like to see cancel does not — and no care in setting up the
members can fix it, because **you cannot contrast two material pairs
without contrasting their mismatch.** It is an *entailed* difference,
the irreducible price of the contrast rather than a flaw in it. The
ratio is reported as only partially cancelling on its account. The gate
does not decide what that is worth; it refuses to let a reader miss it.

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
checks still run and are recorded, so a member with two problems does
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

The field also makes our own ignorance **countable**. If most protocol
verdicts across a study are reached by elimination and few by evidence,
that is a measurable statement that the protocol checks are too sparse,
and it becomes a task rather than a silent weakness. The protocol checks
available today all come from §5 and §6 — the pull-rate ladder failing
to converge, the press never reaching the contact quality of §5.1, the
dissipation identity or the ladder-closure check of §6.5 breaking — and
that set was assembled for other purposes. **It has not been argued to
span the ways a protocol can be wrong**, and the `basis` field is how we
find out.

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
and a member whose interface reference is missing entirely
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
which detector found it), and provenance backpointers — the member, the
trajectory, the frame index, the subcell, the potential generation, the
seed set.

**The identifier is a content fingerprint of the skeleton**, reusing §1.4's
rule rather than inventing a second one. Identical content yields an
identical identifier, so Kaleidoscope's cache is correct by construction;
any change to the structure or the settings yields a new one, so a stale
result cannot be served for a structure that no longer exists. An
identifier built from a frame number, a directory name, or a timestamp
collides across members — and a cache keyed on a colliding identifier is
prior art's newest-file-wins failure (§5.7) wearing new clothes.

**What Kaleidoscope owns:** dispatch, caching, and tracking which units
succeeded and which failed. **What it must not own:** what a snapshot
means, which measure it feeds, or whether the batch was sufficient. Those
stay here. The moment we want to bolt a results database onto it is the
signal to adopt a real one instead — `VISION.md` principle 3 names this
temptation in advance because it is a natural one.

The manifest is retained as an artifact, because it *is* step 8's
provenance record. Re-running an unchanged study should be a cache hit
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
