# The state of SABSIM, stage by stage — 2026-08-26

Written by re-reading the program source under `src/`, the settings
files (`dev/templates/*.toml`, `share/activation/*.toml`), and the
design chain (`VISION`, `ARCHITECTURE`, `DESIGN`, `PSEUDOCODE`, `TODO`).
It is meant to be read cold, without the project's internal shorthand,
so that a reader can decide what to build next and why. The earlier
note `workflow-current.md` (2026-08-25) covers the same ground in
shorthand; this one supersedes it as the planning reference.

Status words used throughout:

- **Built and node-validated** — ran on a compute node and was judged
  from the trajectory, not from an exit code.
- **Built, unvalidated** — the code exists but has not been proven on a
  node for this case.
- **Placeholder** — a function that returns a shape-correct dummy so the
  control flow can run.
- **Missing** — nothing exists under `src/`.

---

## 1. What the program is for

SABSIM simulates surface-activated bonding. Two wafers (for example
silicon and silica) each have their surface roughened and disordered by
an argon-ion beam; the two disordered surfaces are pressed together at
room temperature so they bond; then they are pulled apart so the
strength of the bond can be measured. The headline number is the work
of separation — the energy per unit area needed to pull the bonded pair
apart. The scientific claim is a ratio: the work for a silicon/silica
pair divided by the work for a silicon/silicon pair, compared against
experiment. Every simulation step is molecular dynamics in LAMMPS, and
the quality of the result depends entirely on the interatomic potential
(the force model) used at each step.

## 2. How a run is launched

There are two commands.

- `sabsim run` executes every stage for every member of a study in one
  process. With `--dry-run` it runs on the login node with placeholder
  stage bodies (no LAMMPS, no physics) to check the study file and the
  control flow. Without `--dry-run` it must be inside a SLURM
  allocation and uses the real stage bodies.
- `sabsim prepare` writes three SLURM scripts per member — `activate`,
  `bond`, `analyze` — plus a submission guide, and submits nothing. A
  person submits each job in order; each job re-reads the file the
  previous job wrote (`assembled_pair`, then `pull_results`, then
  `measure_vector`).

Both routes call the same stage functions in
`src/sabsim/pipeline/live_stages.py`. Each stage is wrapped in a check
that the object it produced has the right shape before the next stage
runs; a wrong shape stops the run loudly instead of passing bad data
downstream.

One fact that is easy to miss (and is now being fixed): the
"potential" object the sequencer passed from stage to stage was never
used by any real stage. Each stage decided its own force model from
environment variables and a lookup table.

## 3. The force models in play

The design calls for two different models, for a deliberate reason. A
cheap, general-purpose model does the violent ion-beam step (and, in
the design, generates training data), while a purpose-trained,
high-accuracy model does the gentle bonding and pulling steps and
reports its own uncertainty. On 2026-08-26 the code held three things,
none of them the second one.

**Universal foundation model (DPA-3.1-3M).** A pre-trained neural
network potential covering the whole periodic table; needs no
per-material work. It runs only inside its own deepmd-kit software
bundle, so SABSIM launches it as a separate LAMMPS process and
exchanges files with it. Used for the bulk lattice relaxation and for
the ion-beam cascade (spliced with two ZBL repulsive cores so close
collisions are physical). Passed a one-time sanity screen on silicon (a
perfect crystal has lower energy than a damaged one) but has never
passed the surface-structure gate on any material, so it is marked
`validated=False` and every run must opt in to an unvalidated model.

**Classical potentials** (Stillinger-Weber for Si, Tersoff for Si-O,
three more registered). Traditional analytic potentials shipped as
parameter files, looked up by (element set, material domain). Used by
the bond stage by default whenever no DeePMD model is named, and as an
optional CPU cascade. Silicon Stillinger-Weber is the only entry
anywhere marked validated; GaN and LiNbO3 have no parameter file
shipped. DECISION 2026-08-26 (Paul): classical potentials are removed
from SABSIM. They were never going to be the production model and
their presence made the potential story hard to follow.

**A single frozen DeePMD model** (from a colleague's training). One
trained model file loaded in-process through the DeePMD LAMMPS plugin.
Used by the bond stage as an opt-in override. A stand-in for the
committee: no uncertainty estimate.

**The trained committee** — the design's production model: four DeePMD
models trained together by ALF so that their disagreement measures
uncertainty. Would be named by each member's `potential_ref`. Today
every member says `"PENDING-BOOTSTRAP"`. It does not exist.

The lookup mechanism and the "assemble a `pair_style` line" functions
are solid, well-documented code. The problem is not the mechanism; it
is that the model the design calls the production model has never been
manufactured, and the model that IS used has not passed its own
acceptance test.

## 4. The workflow, stage by stage

### Steps 1-2 — make the training data and train the production model

What should happen: run the universal model through a whole bonding
protocol to generate configurations; label a subset with VASP; train
the four-model DeePMD committee with ALF; repeat wherever the committee
is uncertain. Specified in DESIGN §4.5 and §4.8 and PSEUDOCODE §11.

What exists: nothing under `src/`. `prototypes/alf_deepmd/` holds a
data converter and two ALF hook functions that `src/` does not import.

Status: **Missing.**

### Step 2a — look up the potential for this member

What should happen: resolve `potential_ref` to a manufactured model.

What exists: `skeleton_stages.resolve_potential` returned a dummy
object; the live stage set reused the placeholder. (Being removed on
2026-08-26 in favour of the study file's `[potential]` block.)

Status: **Placeholder.**

### Step 2b — find the lattice constant the model prefers

What happens: build a small periodic block of the crystal, relax box
and atoms to zero pressure under the universal model, read back the
cell. Cutting slabs at the model's own lattice constant avoids a
stressed starting box (the oxide pair built at the published lattice
exploded at ~24 GPa in test T-18).

Code: `derive_lattices_live` → `bulk_relax_subprocess_script`,
`run_activate_subprocess`, `read_data_box` (`driver/bulk_relax.py`).

Design also says (§7.2): this is where the potential's bulk properties
(lattice, stiffness, surface energy) should be compared against DFT
before the build is allowed to proceed.

Status: **Built and node-validated** (Si a = 5.5147 Å under DPA-3.1).
The DFT comparison gate is **Missing**; `biaxial_stiffness.py` measures
one stiffness but nothing calls it.

### Step 3 — cut the two wafer slabs

What happens: read each crystal from its CIF, rescale to the derived
lattice, cut the requested face, find a common in-plane cell for the
two materials (pymatgen's coincidence-lattice search), strain each half
by half the mismatch, tile the cell up to the chosen beam footprint
(~1475 Å²), add vacuum, write each half to its own file.

Code: `build_halves` in `live_stages.py`; `match_surfaces`,
`even_split_shared_cell`, `build_standalone_half`,
`write_standalone_half` in `structure/slab_builder.py`.

Status: **Built and node-validated for Si/Si.** For a genuinely
mismatched pair (Si/SiO2) the code path passes unit tests but has not
been run through the mainline on a node; the only oxide pairs tried
were built by side scripts. The study template still uses alpha-quartz
because no beta-cristobalite CIF exists. Known drifts: strain is stored
as a scalar, not the tensor the pseudocode specifies; two pymatgen
knobs are not mapped; the worst-axis strain metric exists but is not
what ranks the candidate cells.

### Step 4 — roughen each surface with the ion beam

What happens: for each half separately, a short relaxation, then a
sequence of argon impacts at the chosen energy aimed at random surface
points up to the chosen dose; each impact runs with an adaptive tiny
timestep until 0.5 ps has elapsed, then the border layer cools the slab
for 0.5 ps; finally all argon atoms are deleted. The stage is
"cascade only": the gentle heal and the quality check moved to the
bond stage on 2026-08-08.

Code: `activate_surfaces_live` → `activate_one_half` →
`_activate_one_half_subprocess` → `build_activate_script` (one
self-contained LAMMPS script) → `run_activate_subprocess` →
`read_dump_structure`. Force model: universal model plus two ZBL cores
(`resolve_cascade_generator`).

Status: **Built and node-validated as plumbing** (runs end to end on
V100/H100, energy conserved, argon stripped). **Not validated as
physics:** no full-dose activation under the universal model has
passed the surface-structure gate. Under the earlier DPA-2.4 model the
silicon came out far too over-coordinated (defect fraction ~0.9 against
an allowed 0.05-0.60). Under DPA-3.1 only single-impact reach scans
have run (T-22/T-23: 100-140 eV reaches the 7 Å target). The dosed run
has not been done. The ensemble count in the study file
(`amorphization_count = 3`) is read but only one realization ever runs.

### Step 5 — stack the two roughened halves into a facing pair

What happens: flip the top half so its roughened face points down,
remove any fragments knocked loose, place the halves 10 Å apart (wider
than the potential's reach, so the next step can heal each surface as
if alone), lift if any atoms clash, write one LAMMPS data file.

Code: `assemble_pair_live` → `assemble_amorphized_pair`,
`write_lammps_data`.

Status: **Built and node-validated for Si/Si.** One hard-coded number
remains: the bond length used to decide "loose fragment" is fixed at
2.8 Å in `live_stages.py`, whereas the design says bond cutoffs are
derived from the pair-correlation function, and the gate reference
files already carry that number.

### Step 6a — heal both surfaces and check they are properly amorphous

What happens: with the pair 10 Å apart, run a short relaxation of atoms
and cell so both surfaces settle; then judge each surface separately
against its material's reference file (`share/activation/Si.toml`,
`O_Si.toml`, `Li_Nb_O.toml`) on four metrics: pair-correlation first
peak, coordination-defect fraction, ring statistics, damaged-layer
depth. A failure stops the run before the expensive press.

Code: `press_and_bond` → `contact_relax_commands`,
`combined_cell_relax_commands`, `gate_healed_surfaces` →
`activation_gate` (`driver/activation_gate.py`).

Status: **Built and node-validated as machinery** (T-9 silicon, T-19
oxides). **Has never passed on a real activation.** All three
reference files are explicitly marked `real = false` (literature
guesses); only the 7 Å depth was measured, and it was measured under
Stillinger-Weber, not under the current model.

### Step 6b — cut out the vacuum, press to contact, hold

What happens: slide the top half down to the press start gap; apply a
constant downward pressure (1 MPa) on the top grip; advance in chunks
until the gap has closed AND the normal stress has turned positive;
hold at 300 K for 150 ps so bonding can occur.

Code: `_scissors_delta`, `scissors_commands`, `press_drive_commands`,
`contact_reached`.

Status: **Built and node-validated on Si/Si.** The design's
displacement-controlled cross-check has not been run. There is no
graded "how much of the interface bonded" measure — `contact_quality`
is always `None`.

### Step 6c — settle a zero-load reference

What happens: remove the load, minimise, equilibrate, confirm grip
forces and energy have stopped drifting; write the settled state to a
file. Code: `settle_reference`.

Status: **Built and validated.**

### Step 7 — pull apart at each rate on the ladder

What happens: for each rate (1, 3.2, 10 m/s in the template), start
from the settled file, pull the top grip up in chunks, record grip
displacement, reaction force, interface opening and the number of atoms
still bridging; stop when the opening exceeds the cutoff and nothing
bridges. Checkpoint pairs allow resume.

Code: `pull_at_rate`, `begin_or_resume_pull`, `driver/resume.py`,
`driver/analysis.py`.

Status: **Built and node-validated on Si/Si**, including resume. Two
known defects: the atom-count conservation check starts counting at
the pull, so atoms lost during the press go unnoticed (T-18 reported
"atoms conserved" on a pair that had lost 93 % of its atoms); and the
loader accepts a ladder of one rate although the design requires at
least three.

### Step 8a — reduce to measures

What happens: integrate force over displacement up to separation,
divide by interface area → work of separation.

Code: `run_analyzer_live` → `work_of_separation`.

Design (§6.4) lists five measure families: M1 mechanical work (per
rate); M2 thermodynamic work of adhesion (two variants, via energies of
the separated pieces); M3 a quasi-static reference curve; M4 the
all-electron cross-check; M5 geometric and electronic bond descriptors
including a contact-area fraction. Plus a registry so a gate can ask
for measures by name, and consistency checks between them.

Status: **Only M1 is built**, and it reports one number (the slowest
rate that separated) rather than one per rate. Uncertainty is
hard-coded to zero because only one seed ever runs. Everything else is
emitted as `unresolved`. The bonded-cluster kernel M2 needs already
exists in `amorphized_assembly.py`.

### Step 8b — characterise the bonds electronically

What should happen: select frames, cut an interface sub-cell, send to
the all-electron code (Imago) via its batch manager, harvest charges,
bond orders, density of states. Design §8, four components.

Code: `skeleton_stages.run_characterization`, a mock reused by the
live set.

Status: **Placeholder.**

### Grade the member; grade the study

What should happen: walk a fixed chain of questions (was the
measurement valid? is the bulk model right? has the potential seen the
interface? otherwise the protocol) and produce a verdict with its
cause; compare the Si/SiO2 : Si/Si ratio against experiment with
correlated uncertainty, plus an order-of-magnitude sanity bracket on
each absolute number. Design §7.

Code: `evaluate_member_gates` (placeholder text "not graded");
`evaluate_relations` (computes the ratio).

Status: **The ratio arithmetic works; the gate is a placeholder.**
Every result is stamped `trusted = False`.

### Write the results out

What should happen: one machine-readable summary per run, a human
report with plots, trajectory dumps with columns a viewer can colour
by. Design §9.

Code: `emit_study` returns a Python dict; the per-job route writes
`measure_vector.toml`.

Status: **Missing** apart from the TOML handoff files. Trajectory
recording is off by default and records only `id type x y z`.

## 5. What is missing, in the order it matters

**Gap 1 — the production potential does not exist, and nothing
consumes one.** This is the root. Because there is no trained
committee: the bond stage runs on a stand-in; no stage reports an
uncertainty; the "has the potential seen the interface" check and the
live abort monitor have no signal; and `potential_ref` in the study
file is decorative. Building the bootstrap is a separate project (VASP,
ALF, GPU time). Until it exists, every number the pipeline produces is
a plumbing result, which the code honestly labels `trusted = False`.

**Gap 2 — the universal model cannot run the bond stage even though
the design says it should.** The 2026-08-21 decision was that the
universal model also does the heal, press and pull until the committee
exists. But the universal model only loads in its separate deepmd-kit
bundle, which SABSIM reaches by writing a complete LAMMPS script and
reading a file back afterwards. The press and pull are interactive
loops — advance a chunk, read positions and stress, decide, advance
again — so they cannot be handed off as a single script. Closing this
needs an architecture decision: rewrite the press/pull as
script-with-checkpoints, or obtain an in-process LAMMPS build that can
load DPA-3 weights (a `cpg_lammps` module for deepmd-kit 3.x).

**Gap 3 — the ion-beam stage has never been shown to produce a
correct amorphous surface under the universal model.** The
single-impact scan says 100-140 eV reaches the depth target; the dosed
activation at that energy has not been run. Until one dosed activation
passes the gate, `validated=False` stays. There is also an open
question whether the gate's coordination band is itself mis-set — all
three reference files are guesses.

**Gap 4 — the analyzer measures one thing out of five, once.** M2,
M3, M5-geometric and the measure registry are pure-Python work on data
the pull already records. Per-rate M1 and the ensemble loop over seeds
also belong here. This is the cheapest part of the design to build and
the one that most changes what a result looks like.

**Gap 5 — the two gates that decide whether a result is believable
are placeholders.** The potential-quality gate at the build boundary
(lattice/stiffness against DFT) and the per-member diagnosis chain
with the ratio bracket. Both are specified in detail (DESIGN §7) and
both are pure Python.

**Gap 6 — a run can silently lie about atom loss.** Move the
conservation baseline to the assembled pair and check it at every
stage boundary. Small, and it closes the one known way a void run
passes.

**Gap 7 — no report layer.** No summary file, no plots, no
viewer-ready dump columns, no activated-skin label.

**Gap 8 — materials beyond silicon are not runnable end to end.** The
mismatched build has not been node-validated through the mainline; no
oxide has passed even the one-time sanity screen under the universal
model; beta-cristobalite has no CIF.

## 6. Cruft: what is in the repository that distracts

**Dead code in `src/`** (leftovers from before the 2026-08-08
"cascade only" change or from the hard-coded-silicon era):
`driver/cascade.py` `mlip_reanneal`, `reanneal_commands`, the
two-engine `activate_surfaces`; `live_stages._reanneal_force_model`;
`commands.classical_si_stand_in`; `slab_builder.build_facing_pair`;
`biaxial_stiffness.measure_biaxial_modulus` (wired to nothing); and
docstrings that still describe the heal and gate as living in the
activate stage.

**Placeholders inside the "real" stage set:** `resolve_potential` and
`run_characterization` are imported from `skeleton_stages` into
`LIVE_STAGES`; a reader cannot tell they are dummies without following
the import.

**Environment-variable switches that encode decisions the study file
should own:** `SABSIM_CASCADE_MLIP_MODEL`, `SABSIM_CASCADE_CLASSICAL`,
`SABSIM_DEEPMD_MODEL`, `SABSIM_ALLOW_UNVALIDATED_POTENTIAL` decided
which physics ran and none was recorded in the study file. (Being
moved into a `[potential]` block on 2026-08-26.)

**Validation-harness sprawl:** `install/tests/` holds eleven
`t9...t22` directories plus eight loose probe scripts (59 tracked
files) and an `archive/`. Together they are a second, parallel way to
run the pipeline, and several build their own slabs by side scripts
rather than through `build_halves` — which is how the T-18
thin-ribbon oxide cell happened. The LEDGER is the valuable part.

**Untracked but present at the repository root:** `sunita/`,
`sunita2/`, `log.lammps`, `jobs/` (eight run directories). All
gitignored. `src/scripts/XYZ.py` (a small XYZ file tool, tracked) does
not belong to any stage.

**Design-document tails:** `dev/TODO.md` has 88 open items, many of
them long historical narratives now resolved or superseded.
`dev/old_docs/` (seven files) and five notes in `dev/notes/` overlap
with each other. PSEUDOCODE §1 still omits the lattice-derivation
stage the sequencer runs.

## 7. What is genuinely solid

The study-specification loader with its no-hidden-defaults validation;
the sequencer with its contract guards; the three-job split with file
handoffs; the deployment writer with its login-node checks; the slab
builder with the real coincidence-lattice matcher and even strain
split; the lattice derivation; the out-of-process cascade with ZBL
splicing; the assembly; the heal → gate → scissor → press → settle →
pull → resume chain; and 361 unit tests, all green. The framework is
finished. What remains is (a) the physics acceptance of the universal
cascade, (b) the analyzer, (c) the gates and report, and (d) — the
large one — the production potential and a way to run the bond stage
under a modern DeePMD model.

## 8. Decisions taken on 2026-08-26 (Paul)

1. Move the four force-model environment variables into a study-file
   `[potential]` block, so the study file is again the provenance
   record.
2. Remove the passed-along `potential` object and the placeholder
   `resolve_potential` stage; each stage reads the study file's
   `[potential]` block.
3. Remove classical potentials from the code and mark them deprecated
   in the design documents; they would almost never be used and only
   create confusion.
4. Next large piece of work: establish the ALF DeePMD committee.

## 9. Decisions taken later on 2026-08-26 (Paul) — the road to ALF

Order of work: **C** (one dosed 120 eV activation through the real gate,
job 16820522, the first run through the `prepare` route since the
re-architecture) and **E** (atom conservation baselined at the assembled
pair; commit `b33d246`) first; then the two A′ decisions below; then the
bootstrap.

**Decision 1 — option (a):** build an in-process LAMMPS engine linked
against deepmd-kit 3.x (a `cpg_lammps` module), so `pair_style deepmd`
can load a DPA `.pth` and, later, the ALF-trained committee `.pth`
inside SABSIM's own process. No rewrite of the press/pull loops. Claude
attempts the build.

**Decision 2 — a LEAN VASP labelling recipe, cheap first, dial up
later.** Get the whole process to run end to end before spending on
accuracy; the budget is learned by spending.
- k-points: Γ only (a single k-point) for every system that is not a
  bulk single crystal; a real k-spacing only for the bulk ground-state
  and bulk strain families.
- plane-wave cutoff on the low side (see the recipe note for numbers).
- smearing and convergence criteria not demanding.
- interface sub-cells for labelling: remove the deeper crystalline /
  near-crystalline layers and keep only a couple of layers of ordered
  material under each activated surface — the surface atoms are what the
  training is for.
- `material_domain` stays as it is (recorded, unread) for now.
- the bootstrap lives in `src/sabsim/bootstrap/` behind a
  `sabsim bootstrap` command, run as its own job(s), separate from the
  three per-member jobs.
