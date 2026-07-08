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

<!-- Scope: SAB-specific slab construction (step 3) and facing-pair
assembly (step 5) on ASE — the pair-generic coincidence-supercell
lattice matcher, residual-strain application before amorphization, and a
polar-slab symmetrizer hook for future ionic/polar pairs.
Sources: ARCHITECTURE §2.3 (structure builder; STRUCTURAL 4); TODO
DESIGN (STRUCTURAL 4 follow-ons); PRIOR_ART §1.2 (polar symmetrizer) and
§1.5 (worked 16:15 coincidence cell). -->

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

<!-- Scope: the step-6/7 press-then-separate protocol on LAMMPS + the
MLIP — gap closure, pressure bonding, controlled separation — and the
force-vs-displacement reduction feeding §6. Runs on GPU (`pair_style
deepmd`).
Sources: ARCHITECTURE §2.3 (surface-dynamics engine; STRUCTURAL 2) and
§4.1; PRIOR_ART §1.5 (a built-and-run press/pull protocol template). -->

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

<!-- Scope: OLCAO skeleton preparation (structure -> OLCAO input,
full-basis, Γ-point, run settings) built independent of Imago execution,
the Kaleidoscope batch dispatch, and snapshot selection (which and how
many step-6/7 frames).
Sources: ARCHITECTURE §2.3 (bond characterization) and §4.1; TODO
(snapshot selection; OLCAO skeleton template); PRIOR_ART §1.2 item 5
(OLCAO plan). -->
