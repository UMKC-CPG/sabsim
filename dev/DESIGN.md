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

## 1. Run specification and settings layer

<!-- Scope: the editable config a user changes to point the pipeline at
a study — material knobs (crystal, one Miller face, identity) and
protocol knobs (activation species / energy / dose; press and separate
load, depth, duration, speed) — kept apart from the deployment/resource
layer and the fixed machinery, and exposed programmatically. v1 fixes
Si/SiO2 (plus a Si/Si reference) with every protocol knob frozen.
Sources: ARCHITECTURE §2.3 (run specification; settings/deployment
separation; programmatic entry) and §4.1; TODO DESIGN (settings-file
shape). -->

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
  the run's provenance record (`VISION.md` goal 3) and passed forward as
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

**The twist.** Before tiling, the second slab may be **rotated in the
surface plane** by an angle `twist_angle`. This is a real physical
degree of freedom — nothing requires two bonded wafers to share a
crystallographic orientation — and it is the single largest lever on how
big the matched cell has to be, because rotating one lattice changes
*which* whole-number combinations happen to line up with the other's.
Prior art holds the twist at zero without saying so.

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

**The search.** Enumerate whole-number matrices up to an area limit and
twist angles over a grid, keep every candidate whose largest strain
component is within the misfit tolerance and whose atom count is within
budget, and among the survivors take the smallest cell. Two properties
are worth stating because they are exactly what prior art lacks:

- Nothing in this ever assumes the two surface vectors have equal
  length, or meet at 90° or 120°, or that the same whole number is used
  in both directions. It is correct for any pair of surfaces.
- Allowing off-diagonal whole numbers and a twist routinely finds a far
  smaller cell at the same tolerance than the diagonal, twist-free
  search does. Prior art's restriction is what forces its 7.9 nm,
  ~72,500-atom bilayer — and cell size lands directly on the execution
  walls of `ARCHITECTURE.md` §4.1, so this is a cost decision, not a
  stylistic one.

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
same-material reference run (`ARCHITECTURE.md` §2.3) double as the
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
run as prior art does.

**There is no registry search.** Prior art exposes a `lateral_shift`
knob "to explore different bonding registries." Registry is a
crystalline-epitaxy concept, and STRUCTURAL 4 is precisely the
observation that an amorphous–amorphous contact has none — that is *why*
dissimilar bonding works. The lateral offset survives only as one more
realization variable, alongside the amorphization seed, for the
ensemble the bond metric is averaged over.

**The builder emits labeled groups.** The frozen base, the thermostatted
border, the NVE interior (§3.3), the activated skin, and the press/pull
grips (§5) are all geometric facts the builder knows and every
downstream stage needs. Prior art re-derives each region ad hoc inside
every LAMMPS input, from hardcoded per-material layer thicknesses.
SABSIM makes the labeled group set part of the structure contract that
crosses the step-3/4/5/6/7 seam, so the cascade and the pull agree on
what "the substrate" means without either of them measuring it again.

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
selection in every input file (→ the labeled-group contract); and
adopting one slab's box for the pair (→ assert commensurability).

**Frozen for v1:** crystalline β-cristobalite SiO₂ against crystalline
Si, plus the Si/Si same-material reference that null-tests the matcher;
lattices from the current committee, checked against VASP; the misfit
tolerance and cell-area budget set to admit the amorphous interlayer's
buffering (STRUCTURAL 4). Still DESIGN follow-ons: the exact Miller
faces (a material knob), the tolerance and budget values themselves, and
cristobalite versus quartz.

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
LAMMPS driver** (an in-LAMMPS impact loop, or the LAMMPS Python library),
*not* a fresh process plus a full-slab disk round-trip per impact as prior
art does — at the doses SAB needs (thousands of impacts) that overhead is
prohibitive.

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
first accommodated co-species); a single frozen fluence, energy, and
normal incidence; the generator is a config-selected classical + ZBL
potential (silica per §4 and STRUCTURAL 1b); the MLIP re-anneal and the
validation gate are both mandatory, not optional.

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
4. **Refine by sampling.** Re-run the protocol under the committee; the
   sampler (uncertainty-triggered and/or UDD-biased, §4.4) flags the
   configurations where σ is high; VASP labels those; retrain. Repeat
   until committee σ across a full protocol run falls below threshold.

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
and the reaction force is recorded. Grip thicknesses come from §2's
labeled-group contract, not from a hardcoded per-material layer
thickness.

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

**Frozen for v1:** load-controlled press to a single target pressure,
with one displacement-controlled cross-check on the Si/Si reference; a
single press temperature, depth allowance, and hold duration; at least
three pull rates spanning a decade; bonded/not-bonded plus contact
quality always reported. Still DESIGN follow-ons: the target bonding
pressure and hold duration, the noise-floor thresholds for the reference
state and for "force returned to zero," the contact-quality definition's
bond-counting cutoff, and the ensemble size in seeds.

## 6. Bond-outcome analyzer and measures

<!-- Scope: the pluggable measure vector — mechanical MD work-integral
(headline, Imago-free), thermodynamic work-of-adhesion at MLIP and
all-electron fidelity (including the quasi-static separation-energy
protocol), and Imago bond descriptors — plus the measure-vector schema
the gate consumes.
Sources: ARCHITECTURE §2.3 (bond-outcome analyzer; STRUCTURAL 2); TODO
DESIGN (STRUCTURAL 2 follow-ons); PRIOR_ART §1.5 (dual measure
definition; uncalibrated-interface caution). -->

## 7. Quality gates and diagnosis

<!-- Scope: the two checks and their routing — the potential-quality
gate (bulk stiffness / surface energies plus the interface-fidelity
check: committee uncertainty along the pull and an MLIP-vs-all-electron
ΔE cross-check) and the bond-outcome gate — with the three-way diagnosis
(bulk-model / interface-coverage / protocol) and its reported
diagnostic-label schema. v1 reports; it does not close the loop.
Sources: ARCHITECTURE §2.3 (two separate checks + diagnosis) and §3;
TODO DESIGN (STRUCTURAL 3 follow-ons). -->

## 8. Step-8 characterization (Imago + Kaleidoscope)

<!-- Scope: skeleton preparation (structure -> Imago input, full-basis,
Γ-point, run settings) built independent of Imago execution, the
Kaleidoscope batch dispatch, and snapshot selection (which and how many
step-6/7 frames).
Caution (PRIOR_ART §1.8): prior art's step-8 plan is written against the
LEGACY OLCAO code, not against Imago — the two share no input format,
rc convention, or invocation. Take its physics (full basis, Γ-point-only
given interface disorder, the 500-2000-atom cost estimates); take none
of its templates, scripts, or the $OLCAO_RC working-directory-as-config
convention it carries. Skeleton prep is a new build on the Imago seam.
Prior art's `select_snapshots` detectors ARE worth adopting in shape:
PE local minima during the hold (bond formation), PE local maxima during
the pull (bond at maximum stretch), and sigma_zz drop spikes
(bond-breaking stress release), with near-duplicate frames merged.
Sources: ARCHITECTURE §2.3 (bond characterization) and §4.1; TODO
(snapshot selection; skeleton template); PRIOR_ART §1.2 item 5 and
§1.8. -->
