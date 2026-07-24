# The tool landscape, the data flow, and what "converged" means

> **Status:** A session note, not part of the five-level document chain.
> Written 2026-07-24 to ground the decision on where the accurate
> reference-calculation settings should live (the choice between
> "inside the recipe", "a separate settings file", "two declared
> tiers", and "a named reference-method registry").
>
> **The decision landed the same day: two declared tiers.** `DESIGN.md`
> §4.8 is the result, and it is the authority — this note is kept only
> for the reasoning BEHIND it, which a design section states rather
> than argues. Part 5's learning-error / method-error distinction is
> why there are two settings blocks; part 6's four corrections became
> §4.8's element-set keying, its three kinds of reference, its
> `audited` flag, and its pointing at reference data rather than
> containing it. Parts 1 to 3 are orientation — the tool landscape and
> the three distinct meanings of "converged" — and stay useful on
> their own.

Everything below was checked against the documents and the code as they
actually stand, not from memory. Where the code and the design disagree,
that is called out rather than smoothed over.

It builds up in layers: first who the players are, then how they hand
work to each other, then the three genuinely different things the word
"converged" means in this project — because that distinction is what
lets the settings decision be made with confidence rather than by taste.

---

## Part 1 — The cast, and what each one eats and produces

There are seven distinct programs. Three of them we drive but did not
write and never look inside; two are our group's own prior tools; one is
a library we use as glue; and one is ours.

### The accurate quantum code (VASP)

**What it is.** The slow, trustworthy method. It solves the electronic
structure of a specific arrangement of atoms and reports how much energy
that arrangement has and what force each atom feels.

**What goes in.** A box, a list of atomic positions, and a block of
numerical settings that control how carefully the electrons are
described.

**What comes out.** One energy, one force per atom, sometimes a stress.

**How much it costs.** A lot, and the cost climbs steeply with the
number of atoms. This single fact drives an enormous amount of the
design — it is why the training configurations are cut down to thin
slices of interface, and why the expensive cross-check is only
affordable on a thin slice too.

**State in the project today.** There is no VASP code anywhere in
`src/`. Every use of it is either delegated to the active-learning
framework or is design-only.

### The active-learning framework (ALF, from Los Alamos)

**What it is.** The thing that runs the make-data / train / find-the-gaps
cycle. We adopted it whole and made a deliberate decision to treat it as
a sealed box — we configure it and read its outputs, we do not read its
internals.

**What goes in.** Two things. First, its own configuration files, which
are mostly a list of import paths naming which pieces of code to use for
training, for loading models, and for calling the quantum code. Second,
atomic configurations to work on.

**What comes out.** Two things with very different lifetimes, and
conflating them is a mistake that is easy to make:

- **An accumulating store of labeled configurations.** Every arrangement
  of atoms that has ever been sent to the quantum code, together with the
  energy and forces that came back. It is stored in a scientific data
  format organized by chemical formula. This store is the durable asset —
  it survives every retraining, and it is what makes the second model for
  a material cheaper than the first. Losing it means spending the entire
  quantum-calculation budget again.
- **The trained models themselves.** These are cheap to regenerate from
  the store. Losing one costs a retraining.

**One thing worth being precise about.** The framework does its own job
scheduling — it fans out the quantum calculations and the training runs
onto the cluster by itself. Our sequencer hands it one task and waits.
It never reaches inside.

### The model trainer (DeePMD)

**What it is.** The program that fits a fast approximate model to the
labeled data. It is selected by configuration rather than hardwired; a
different trainer would be three string changes.

**What goes in.** The labeled configurations, in the trainer's own
on-disk layout, plus one settings file per model being trained.

**What comes out.** A frozen model file that a molecular dynamics run
can load and evaluate very fast.

**Important detail.** We train four of these at once, differing only in
their random starting point and the order they see the data. They are
not a redundancy measure. Their *disagreement* is the whole point: where
four independently-fit models give the same answer, the data constrained
them; where they diverge, the model is guessing. That disagreement is the
uncertainty signal the entire active-learning loop steers on.

### The format bridge (ours, and already written)

The framework's storage format and the trainer's input format are
different. A small converter translates between them. It is unit-tested
and the translation is exact rather than approximate, because the
framework stores each value multiplied by a stated factor and the
converter divides by that same factor — a perfect round trip, not a unit
conversion that could drift.

### The molecular dynamics engine (LAMMPS)

**What it is.** The program that actually moves atoms through time. It
appears twice in the pipeline, running two different force descriptions:

- **The violent argon bombardment**, which runs on a simple classical
  force description with hard repulsive cores spliced in so atoms cannot
  pass through each other at high speed. This deliberately never uses the
  trained model.
- **The gentle stages** — the post-bombardment settling, the press, and
  the pull — which are *designed* to run on the trained model, but today
  run on a classical stand-in behind the identical interface, because no
  model has been trained yet.

**How we drive it.** Not by writing an input script and walking away.
The press-and-pull is a single stateful run whose decisions are made
mid-flight — when contact is real, when the grip force has settled, what
force resists the pull — so it runs through the engine's programming
interface as a persistent driver that reads forces back live.

### The all-electron analysis tools (Imago and Kaleidoscope, ours)

Imago examines the electronic structure of a calm, settled bonded
interface in more detail than the quantum code above provides.
Kaleidoscope dispatches many Imago runs in a batch and does nothing
heavier. These sit at the very end and are deliberately reserved for calm
structures — the violent, distorted training configurations go to VASP
instead, because that is what each tool is good at.

### The sequencer (ours)

A thin program that runs the steps in order, checks each one produced
what it promised, and starts the next. It is deliberately lightweight.

---

## Part 2 — How the work actually flows

Two loops, meeting at one seam.

**The outer loop manufactures a model.** It runs once per set of
chemical elements, costs weeks, and produces one artifact.

1. A small collection of calm, ordinary structures is computed
   accurately: perfect crystals of both materials, their clean surfaces,
   mildly shaken versions, and lightly stretched versions. Four models
   are fit to this. The bar is deliberately low — the only requirement is
   that they do not fly apart when asked to run.
2. Hard configurations are generated cheaply. The argon bombardment runs
   on the *classical* force description, on ordinary processors, and its
   frames are harvested. Separately, the pressing and pulling run on the
   *current four models*, and those frames are harvested too. Two
   families, two sources — and this is the part an obvious sketch gets
   wrong. Only the first family comes from the classical force
   description. The second comes from the models' own trajectory, because
   the interface region is exactly where the answer is read, so the
   models' own path through it is where the training signal is richest.
3. A subset of those harvested frames is chosen and sent to the quantum
   code. The results go into the store. The models are refit.
4. The whole protocol is re-run under the refit models, which now report
   where they are *still* uncertain. Those places get sent to the quantum
   code. Refit again. Repeat.

**The inner loop consumes the model.** Once per study member: build the
two slabs, bombard each surface, assemble them facing each other, press,
pull, analyze.

**Where they meet.** A study member does not name a force description.
It names a *generation identifier* — a label pointing at one specific
manufactured model. In the current template all three members carry
`potential_ref = "PENDING-BOOTSTRAP"`, and the lookup that resolves it is
a stub returning a classical stand-in.

**One coupling worth flagging, because it makes this a loop rather than
a line.** The structure builder needs each crystal's lattice spacing, and
the design deliberately takes that spacing from *relaxing the crystal
under the current model* rather than from a published crystallographic
file. The reason is sound: the box is subsequently evolved by that model,
so building the box on an experimental lattice leaves the model instantly
compressed or stretched — prior art hit exactly this and reported tens of
gigapascals of internal pressure at the very first step. But it means the
builder is downstream of the model, while the model must be trained on
the builder's stretched structures. Two-way coupling. That is why step
two comes before step three in the ordering.

---

## Part 3 — Three different things "converged" means here

This is where the confusion lives, and it is worth separating carefully,
because the design currently handles two of these three explicitly and
the third not at all.

### Convergence type one — is a single quantum calculation resolved?

Every accurate calculation carries a set of numerical controls: how
finely the electron wavefunctions are represented, how densely
reciprocal space is sampled, how partial occupancies near the Fermi level
are smeared, and how tightly the iterations must settle before the answer
is accepted. Loosen them and the answer is cheap and wrong; tighten them
and it is expensive and right. The way you find the boundary is to
tighten each control until the energies and forces stop moving.

**Who owns this in the project today: nobody.** This is the gap. Not one
line in the four design documents states an energy cutoff, a sampling
density, or a convergence tolerance. The pseudocode has a step that says
"the quantum code labels a selected subset" and hands off. That hand-off
currently goes to the active-learning framework's quantum task, which
means its own configuration files would become the source of truth for
the most consequential numbers in the project — sitting inside a box we
have declared we do not look into.

**One subtlety that matters more than it looks.** The sampling density
has to be expressed as a *spacing* rather than a fixed grid. A small
perfect crystal and a large amorphous slab need very different grids to
be equally well resolved. State it as a grid and it is wasteful on one
and wrong on the other. This is what makes a single settings block able
to serve calculations on wildly different cell sizes at all — and it is
directly relevant to the decision, because it is what makes the
inheritance options even possible.

### Convergence type two — has the model learned enough?

Two tests together, and both are already specified:

- The four models' spread across a complete protocol run falls below a
  threshold. Meaning: the model is confident everywhere the protocol
  actually goes.
- The model reproduces agreed reference properties within tolerance —
  lattice spacings, elastic stiffness, surface energies, and the
  structural signature of the disordered surface.

The design is explicit that the second test is the same check that later
runs in the production pipeline, but with a different power. During
manufacturing it can *act*: a failure sends the loop back for more data.
Downstream, once the model is frozen, the identical check can only
*report*.

**The numbers are not pinned.** The design deliberately leaves the
uncertainty thresholds and the biasing weight as tunable knobs, recorded
as a follow-on.

### Convergence type three — is a physical answer converged with
respect to how we set the problem up?

Three separate ladders, all specified:

- **Cell-size convergence for the cross-check.** The expensive method is
  only affordable on a thin slice of interface, so the design asks: does
  that slice give the same answer as the full cell? The elegant part is
  that this is tested entirely with the *cheap* method — evaluate the
  target quantity on the full cell and on the slice, both with the fast
  model, and enlarge until the difference is small. The cheap method
  certifies the expensive method's input. And "enlarge" means adding back
  one whole crystal layer at a time, because only whole-layer steps leave
  the rejoined faces seamless.
- **Pull-rate convergence.** Simulated pulls are far faster than real
  ones, so the resisting force is inflated by the rate. The design
  reports the answer once per rate on a ladder and extrapolates toward a
  rate-free reference obtained by a sequence of held-open relaxations.
- **Disorder-realization convergence.** Bombardment is stochastic, so
  several independent realizations are run and the spread is taken across
  them.

**These three types are independent.** A calculation can be perfectly
resolved numerically and still be run on too small a cell. A model can be
beautifully converged in the learning sense and yet be faithfully
reproducing badly-resolved training data. That last sentence is the crux
of the decision.

---

## Part 4 — Every place an accurate quantum answer is consumed

Five places, and it is worth stressing that these are not five instances
of the same calculation. They differ in size, in count, in cost, and in
what the answer is *used for*.

1. **Energy and forces on distorted configurations.** Thousands of them,
   each on a small slice. These *train* the model.
2. **The relaxed lattice spacing of each perfect crystal.** A few, tiny,
   cheap. Compared against the model's own relaxed lattice.
3. **Elastic stiffness and surface energies.** A handful, small cells,
   deliberately well-resolved. Compared against the model's predictions.
4. **The structural signature of the disordered surface.** Currently
   **taken from literature and experiment, not computed by us at all.**
5. **The energy difference across the interface.** One per study, on one
   thick slice. Subtracted from the model's answer for the same slice.

Rows 2, 3 and 5 are all *comparisons*: a number from the model set
against a number from the accurate method. Row 1 is what *made* the
model. Row 4 is different in kind, and it is the first place the design
needs a correction (Part 6, item two).

---

## Part 5 — Why this decides the settings question

Take row 5, the interface cross-check, since it is the sharpest case. It
is defined as the accurate answer minus the model's answer, on the very
same slice of atoms. Its entire job is to catch a model that is
*confidently wrong* — one where all four models agree with each other
and are all off together, which the disagreement signal by construction
cannot detect.

Now: that difference is really two differences stacked on top of each
other.

**Learning error.** The model was fit to data produced by one particular
set of numerical settings. It learned *that* energy surface, including
whatever error those settings carry. If you now compare the model against
an accurate calculation run with the *same* settings, the gap you see is
purely "how faithfully did the fitting absorb its training data."

**Method error.** Separately, those settings have their own error against
physical reality. Loose settings misrepresent the true energy surface. No
amount of additional training data fixes this — the model would only
learn the wrong surface more faithfully.

Here is the consequence, and it is the thing to see clearly before
choosing:

- **If the comparisons inherit the training settings**, every comparison
  measures learning error cleanly and is *completely blind* to method
  error. A model trained on under-resolved data would sail through every
  gate, because it is being graded against the same under-resolved
  standard it was taught from.
- **If the comparisons use tighter settings than the training did**, then
  every comparison measures the two errors mixed together, with no way to
  separate them — and it will blame the model for a discrepancy that was
  baked into its training data before it ever saw a single configuration.

Neither is wrong. They answer different questions. The genuine mistake
would be to pick one and believe it had answered both.

That is the entire argument for option 3: declare a **production
settings block** used for the training labels and for every comparison
that gets differenced against the model — which gives the clean
learning-error reading and the structural guarantee that no comparison
can accidentally use settings the training never saw — and
*additionally* run one small **accuracy audit** at recipe-creation time,
on a handful of tiny cells, tightening the controls until the numbers
stop moving, recording how much error the production settings themselves
carry.

The audit is a few small calculations, once per element set. Against a
budget of thousands of labels it is a rounding error. What it buys is
that the gate reports learning error, the recipe reports method error,
and a reader can add them together rather than being silently blind to
one.

---

## Part 6 — Four things that should change

Grounded in what the documents and code actually say, not preferences.

### One — the recipe is keyed by the element set, not the material pair

"One recipe per material pair" is imprecise in a way that matters. The
design's own decision is that there is **one model covering the union of
the elements involved**. For silicon and silicon dioxide the element set
is oxygen and silicon. The current study template makes this concrete:
the silicon-to-silica member, the silicon-to-silicon null test, and the
silica-to-silica null test all carry the *same* generation identifier.
One model serves all three.

So the recipe is keyed by the element set, exactly as the classical
force-description registry already is. This is not a cosmetic wording
fix — it changes what the file is named after, what "one settings block
per recipe" scopes over, and how adding a third material behaves. Adding
gallium nitride to a silicon-and-oxygen study extends the element set and
demands a new model; it does not add a parallel one.

### Two — some references are measured in a lab and inherit nothing

The design describes the structural references for the disordered
surface as being checked "against VASP and experiment," as though those
were one category. They are not, and the file that actually holds them
proves it. Every number in it is a literature-guided placeholder carrying
an explicit `real = false` flag, with one exception — the required
disorder depth, which is not literature at all but a value *measured by
this pipeline's own sweep*.

So there are three kinds of reference in this project, not one: values we
compute accurately, values taken from published experiment, and values
measured by our own simulations. The inheritance rule can only bind the
first kind. Stating it universally would be false, and the design should
say so plainly rather than paper over it.

### Three — the settings block needs an honesty flag

The classical force-description registry marks each entry as validated or
not, and refuses to run an unvalidated one unless a deliberate,
externally-visible opt-in is set. The reference-data file marks itself
`real = false`. Both say the same thing: *this exists, and nobody has yet
earned the right to trust it.*

The settings block should carry the identical flag — has a convergence
study actually been run against these values, or are they a plausible
guess someone wrote down? Anything manufactured under unaudited settings
is exploratory, and should say so in its own record. This costs one field
and reuses a pattern that is already built and working, rather than
introducing a new concept.

### Four — the pseudocode already separates recipe from reference data

The manufacturing procedure's top-level function already takes *two*
inputs: the specification, and the reference data, as separate objects.
Folding everything into one file would undo that. The existing signature
is better, and it lines up exactly with item two — the reference values
include laboratory measurements that no recipe should pretend to own. The
recipe should *point at* the reference data, not contain it.

Which means the option-3 recommendation refines to: the recipe holds the
two settings blocks and the manufacturing plan; the reference values keep
their own home; and the recipe records which reference set it was judged
against, so the pairing is recoverable afterward.

---

## Where this leaves the decision

Option 3, with those four corrections folded in, comes out as: one file
per element set, holding a production settings block used for both the
labels and every model-versus-accurate comparison, plus a one-time
accuracy audit whose result is recorded as a reported quantity, plus an
honesty flag saying whether that audit has actually been run, and a
pointer to — not a copy of — the reference values it is judged against.

That gives the structural guarantee that no comparison can be run under
settings the training never saw, without the blind spot about whether
those settings were good enough in the first place.

If that lands right, the next step is a new design section with every
number as a placeholder pointing at the values file, the beyond-elastic
stretched, compressed and sheared structures added to the starting
collection, and small companion edits where the comparisons are described
so they state where their reference settings come from.
