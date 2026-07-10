# Prior Art

> **Document hierarchy:** this is a **cross-cutting reference**, not a
> level of the VISION → ARCHITECTURE → DESIGN → PSEUDOCODE → Code chain.
> It records existing work — inside or outside this group — that overlaps
> SABSIM, so that ARCHITECTURE and DESIGN can point at concrete, already-
> built assets instead of re-deriving them. Each entry says plainly what
> is *usable now*, what is *design-only*, and what to *leave behind*.

---

## 1. Sunita's `bond_debond` pipeline (SiO₂ / LiNbO₃)

**Location.** `sunita/bond_debond/` inside this repository. It is a
**dropped-in copy, deliberately untracked by git** (it is not part of
the SABSIM source tree — do not treat it as a SABSIM module). Author: a
graduate student (Sunita) in the group. It was built from the same
document-chain template SABSIM uses, so it has its own
`dev/VISION.md … PSEUDOCODE.md`.

**What it is.** A five-stage, single-pass atomistic wafer-bonding
pipeline for **SiO₂ bonded to LiNbO₃** — one of the dissimilar pairs
SABSIM itself targets. Its physical arc is essentially **SABSIM steps
3–8 in miniature**:

```
build crystalline slab → relax → amorphize one surface by Ar-ion
bombardment → assemble bilayer → bond/debond MD → OLCAO analysis
```

The important difference from SABSIM: it uses **classical interatomic
potentials** (Tersoff for SiO₂, Buckingham + Coulomb for LiNbO₃) where
SABSIM will use the DeePMD MLIP, and its electronic-analysis end is
*planned* against the **legacy OLCAO code** — never built — where SABSIM
drives **Imago** through Kaleidoscope. Those are not the same code:
Imago inherits the OLCAO input format (with only file-layout and
command-sequence tweaks), but shares no rc convention or invocation with
that lineage (§1.8). There is
**no ALF, no active-learning outer loop** — it is one straight pass, not
the nested-loop design of SABSIM.

> **Update (2026-07-08) — this is now a multi-generation body of work.**
> A more recent copy adds two further generations beyond the version
> first studied: an evolved **classical** pipeline (`slab_bond_debond/`)
> that has actually *built and run* the bond/debond stages, and an
> **MLIP-targeted** restructure (`slab_bond_debond_MLIP/`). §1.1–1.4 are
> kept current; **§1.5 carries the full update**, including where the
> newer work independently confirms SABSIM's structural decisions.

### 1.1 Maturity — most of the pipeline now runs (updated 2026-07-08)

At first study the design documents ran well ahead of the code — only
slab-build, relax, and amorphize were implemented, every other stage
refused at runtime. **That is no longer true:** in the evolved classical
tree (`slab_bond_debond/`) the bilayer and bond/debond stages have been
built and executed. Current state, in the most-complete
(classical-potential) tree:

| Stage                  | SiO₂                      | LiNbO₃            |
|------------------------|---------------------------|-------------------|
| Slab build             | works                     | works             |
| Relaxation             | works                     | works (new)       |
| Amorphize (Ar bombard) | works, verified g(r)      | works (new)       |
| Bilayer assembly       | works + ran (new)         | works + ran (new) |
| Bond/debond MD         | works + ran, uncalibrated | works + ran (new) |
| OLCAO analysis         | design only (stubs)       | design only       |

The bond/debond numbers are explicitly **uncalibrated** — the
cross-interface bonds use a placeholder Morse well (§1.5). The newest,
MLIP-*targeted* tree (`slab_bond_debond_MLIP/`) is further along in
*design* but behind in *code*: its amorphization has not yet succeeded
and its bond/debond stages are still design-only. OLCAO (step 8) remains
unbuilt in every tree. The generational breakdown is in §1.5.

### 1.2 Reusable assets, ranked

**Usable now (working, validated code):**

1. **Ar-ion bombardment amorphization recipe.**
   `bin/primeinput.py` (`make_amorphize_input` and the per-impact
   blocks). This is validated LAMMPS input generation for SABSIM's
   surface-activation step (step 4): a ZBL `hybrid/overlay` splice for
   the short-range collision cascade, frozen bottom layers, a `p p f`
   boundary so sputtered atoms leave rather than wrap, seeded/
   reproducible impact positions, angle-of-incidence control, and multi-
   ion batching. Just as valuable is its `dev/CHANGES.md`, which records
   the **hard-won lesson that thermostat damping (0.1 → 1.0 ps) and
   inter-impact relaxation time (2 → 0.5 ps) were what finally made the
   surface amorphize** after many failed runs. That parameter knowledge
   is worth more than the code around it.

2. **Four-strategy polar-slab symmetrization.**
   `bin/build_slab.py` (`_make_symmetric_slab` and its helpers
   `_mirror_symmetric_slab`, `_plane_by_plane_symmetrize`). A polar
   surface such as LiNbO₃ (0001) — or GaN — carries a macroscopic dipole
   that pymatgen's built-in symmetrizers cannot remove because of the
   R3c screw-axis stacking; this code builds a mirror-symmetric slab
   directly. It depends only on pymatgen + numpy and pure geometry, so
   it lifts cleanly into SABSIM's step-3 structure builder.

3. **Amorphization-verification kernels.**
   `bin/analyze.py`: radial pair-correlation g(r) with proper shell-
   volume normalization and a density-reference trick (so sputtering
   losses do not inflate the amorphized peaks), coordination-number
   defect counting, and a surface-inward amorphous-depth estimator.
   These are exactly the "did the surface actually activate?" checks
   SABSIM's potential-quality gate will want. **Take the g(r)
   normalization, not the file.** The density-reference trick is one of
   the three sound kernels in the codebase (§1.8), but "validated"
   overstates the rest: the amorphous-depth estimator scans top-down and
   reports 0 Å (`DESIGN.md` §3.5), the whole module is SiO₂-hardcoded and
   report-only with no threshold, and §1.8 catalogues five unrelated,
   underived cutoffs elsewhere in the same file. Beyond the O(N²) scaling
   and the directory-convention glue, the *criteria* need writing — which
   is why `DESIGN.md` §3.5 makes activation a pass/fail gate rather than
   a report.

**Usable as design input (not code):**

4. **Its `DESIGN.md` §4.4 reaches the same commensurable *unit* SABSIM
   settled on** — an interface energy per area in J/m², converted from
   eV/Å² (see `ARCHITECTURE.md` §2.3, `VISION.md` goal 4). Independent
   arrival at that unit is a useful confirmation.
   **The quantity is not the same, and this entry once said it was.**
   A thermodynamic *work of adhesion* and a mechanical *work of
   separation* are different numbers; the first is rate-independent, the
   second is dissipative, and their difference is the energy dissipated
   in the pull. SABSIM reports both and treats the gap as an observable
   (`DESIGN.md` §6.1), so conflating them is precisely the error §6 is
   built to avoid. Her specification names the work of adhesion and then
   measures something that is neither — §1.8 records four faults in the
   formula. Take the unit and the intent; do not take the definition.

5. **Its `DESIGN.md` §5 is a worked-out OLCAO analysis plan** — a full-
   basis (fb) choice, Γ-point-only sampling justified by interface
   disorder, and wall-clock cost estimates for 500–2000-atom interface
   sub-cells. The *physics choices* are reusable planning for SABSIM's
   step-8 characterization. The *mechanics* are not: the plan is written
   against the **legacy OLCAO code, not against Imago**, which SABSIM
   drives through Kaleidoscope. Imago inherits the OLCAO input *format*,
   but shares no rc convention, invocation, or script lineage with the
   legacy plan (see §1.8). Take the basis/sampling/cost reasoning; take
   no templates or scripts.

6. **The two-tier potential strategy** (classical potential as
   development scaffolding, DeePMD as the production potential, selected
   by a LAMMPS `pair_style` so swapping needs no code change) mirrors
   SABSIM's own adopt-ALF/DeePMD plan. It confirms the approach and
   offers a concrete classical fallback for exercising SABSIM plumbing
   before the MLIP is ready.

**Leave behind (do not carry into SABSIM):**

7. **The working-directory-as-configuration orchestration.**
   `primeinput.py` reads the run's parameters out of the directory path
   (`jobs/<stage>/<material>/<layer>/<energy>/`) and bakes site-specific
   SLURM details (partition name, a personal email, module versions)
   into the scripts it writes. This directly contradicts `VISION.md`
   principle 1 (separate *what* from *where* from the machinery), so
   SABSIM's orchestrator should not inherit it.

### 1.3 A known inconsistency to be aware of

The LiNbO₃ Buckingham parameters hardcoded in `primeinput.py` (Li–O and
Nb–O terms) **disagree with the parameter table in its own
`DESIGN.md` §2.3.** This is a real code/doc mismatch. It is **no longer
moot** — LiNbO₃ now relaxes and amorphizes (§1.1), and the newer trees
move to a **Donnerberg Model-II core-only Buckingham** set with formal
charges (Li +1 / Nb +5 / O −2). Anyone lifting a LiNbO₃ force-field
number should check it against a primary source, not this project.

### 1.4 Open question — now answered

The stages this project had *designed but not built* — bilayer assembly
and the three-phase bond/debond MD — are exactly where **SABSIM's novel
bond-outcome metric lives.** As of 2026-07-08 that question is
**answered: Sunita built and ran them** (classical tree; see §1.1 and
§1.5). The collaboration question shifts accordingly — not *whether* the
pipeline exists, but that it is complete yet **blind at the interface**
(a placeholder pair potential), which is exactly the gap SABSIM's trained
MLIP fills.

> **Qualified (2026-07-09).** This section once ended "her pipeline +
> our potential = a working SAB simulator." The three code evaluations
> that followed (§1.6, §1.7, §1.8) do not support that. The potential is
> the *deepest* gap, not the only one: the structure builder has no
> coincidence solver and ships two slabs strained to cells 0.9% apart;
> the bilayer bonds by slamming one slab into the other at 150 m/s
> rather than pressing it; and the measurement layer emits prose with no
> uncertainty, no provenance, and no check that can fail. Dropping a
> trained MLIP into that pipeline would replace an uncalibrated number
> with a differently uncalibrated one. What transfers is the *physics*
> and the hard-won recipe knowledge — which is a great deal, and is what
> §1.2 ranks. What does not transfer is the architecture.

### 1.5 Update — three generations and the MLIP-targeted rewrite

A more recent copy contains **three generations**:

- `bond_debond/` — the original studied in §1.1–1.4 above.
- **`slab_bond_debond/`** — an evolved **classical** pipeline; the most
  *complete*. LiNbO₃ caught up (relax + amorphize), and bilayer assembly
  plus bond and debond MD are **built and have run**, yielding a first
  work of adhesion ≈ **3.746 J/m²** (plus a stress–strain curve).
- **`slab_bond_debond_MLIP/`** — a ground-up **MLIP-targeted** restructure
  (a proper `src/` package, a Stage-1.5 relaxation, a classical→DeePMD
  `pair_style` swap seam); the most forward-looking *design* but the
  least complete *code* (two competing implementations, amorphization not
  yet succeeding, Stages 3–5 design-only).

**The key relationship.** The MLIP tree is DeePMD-*targeted*, not
DeePMD-*trained*: there is **no VASP labeling, no training, no
committee / uncertainty, no active learning, no ALF** anywhere — DeePMD
is a stubbed config slot. So the two projects are **complementary**:
Sunita builds the *pipeline that consumes* the potential; SABSIM builds
*the potential* and the active-learning machinery she lacks.

**Independent confirmation of SABSIM's structural decisions.** Her newer
design reaches three of our five pre-DESIGN resolutions on its own:

- **STRUCTURAL 1a (one multi-species potential):** verbatim — *"a single
  DeePMD model … covering Si, O, Li, and Nb handles both substrates and
  the heterogeneous interface in a single, unified potential."*
- **STRUCTURAL 4 (coincidence supercell, strained before amorphization):**
  a worked example — 16×SiO₂ ≈ 15×LiNbO₃ → ≈77.9 Å cell, cutting the
  4.78% raw mismatch to ~1.8% residual strain, split ±0.88%/slab and
  applied *before* amorphization "because amorphous material has no
  lattice to strain cleanly." (`ARCHITECTURE.md` §2.3 structure-builder
  bullet points here.) **Read the cell as an example, not a method** —
  see the §1.6 caution below.
- **STRUCTURAL 2 (measure vector):** her bond/debond design defines both
  a thermodynamic adhesion energy (PE-difference / area, J/m²) and a
  mechanical σ-vs-separation curve, and the classical tree ran the
  mechanical pull end to end (`ARCHITECTURE.md` §2.3 bond-outcome
  analyzer points here). The confirmation is that *two* measures are
  needed, which is the substance of STRUCTURAL 2 — **not** the
  definitions: the thermodynamic one was never built and is wrong as
  specified (§1.8), and her design does not treat the gap between the
  two as an observable, which is the point of the vector
  (`DESIGN.md` §6.1).

**One divergence — the cascade engine (STRUCTURAL 1b).** Her MLIP design
intends **DeePMD + ZBL to run the Ar cascade** ("ZBL required even with
DeePMD"), i.e. the production MLIP does the violent amorphization. SABSIM
**considered this and reaffirms the opposite (2026-07-08): the cascade
stays classical + ZBL and the MLIP runs only the gentle stages**, so the
MLIP is never trained on cascade-level distortion or Ar. (In her *code*
the cascade is classical + ZBL anyway; the divergence is only in her
stated end-goal.)

**No interface-fidelity gate (STRUCTURAL 3).** Her `check_amorphous.py`
is a **reporting** tool, not a gate: it prints a g(r) RMSD against an
*optional experimental* neutron curve but applies **no threshold and no
DFT reference**; the only quantitative criterion is coordination-based.
SABSIM's validation gate is deliberately stricter — lift her g(r) /
partial-g(r) / coordination kernels, then add the thresholds and DFT
anchor she omits.

**The load-bearing caution.** The headline 3.746 J/m² is
**uncalibrated**: the cross-interface bonds use a placeholder generic
Morse well, and the result files say so outright. The situation is in
fact worse than "uncalibrated" — see the §1.7 evaluation: the number
comes from a trajectory its own directory marks incomplete, and the
15.3-vs-1.1 GPa discrepancy is not an internal inconsistency of one
analysis but two *different simulations* selected by a newest-file-wins
fetch, both of whose peaks are startup artifacts. This is the sharpest
statement of why SABSIM exists — the pipeline is complete but *blind
exactly at the interface*, where a trained MLIP is required.

**New reusable assets (beyond §1.2).**
- The end-to-end **bond/debond MD protocol** (press → NVT hold → minimize
  → pull → force-vs-separation → work of adhesion) — a concrete template
  for SABSIM steps 5–7, absent at first study.
- The **worked coincidence supercell** above (16:15, ≈77.9 Å).
- A likely-instructive **negative result:** the MLIP tree's amorphization
  fails to accumulate damage, and its cascade dropped the frozen
  substrate and the `p p f` sputter boundary (it uses `p p p`, no frozen
  layer, no border thermostat) that the *working* older tree had — those
  recipe details are load-bearing.
- Bulk-lattice **validation runs** of the classical potentials
  (Munetoh-2007 Tersoff for SiO₂ — a legitimate Si-O set — and Buckingham
  for LiNbO₃).

### 1.6 Evaluation of the structure-building code (2026-07-09)

Done before writing `DESIGN.md` §2, per the standing rule that prior-art
code is evaluated for narrowness before any of it is reused. The
symmetrizer is the real asset; the lattice matching is not code at all.

- **There is no coincidence-cell solver.** No `ZSLGenerator` /
  `SubstrateAnalyzer` / lattice-matching import exists anywhere. The
  16:15 cell is hand-derived in prose, and injected as literals: each
  material's job file **hardcodes the other material's lattice
  constant**. The builder is single-slab, so the shared cell is a number
  typed twice.
- **The two "matched" slabs are not commensurate.** In the MLIP tree the
  SiO₂ jobs use `cell_size = 15 * a_linbo3` (77.2245 Å) while the LiNbO₃
  jobs use `(15*a + 16*a_sio2)/2` (≈77.92 Å) — a ~0.9% disagreement,
  while the docstrings claim a shared cell. A later generation silently
  switched convention again (LiNbO₃ takes zero strain). This is the
  concrete evidence for making the *pair* the builder's object.
- **The "matcher" is a scalar length comparison.** It strains `a` and
  `b` toward one scalar via a diagonal `apply_strain([εa, εb, 0.0])` —
  no cell angle, no shear, no relative twist, no off-diagonal tiling,
  and the zero z-component freezes the Poisson response. It happens to
  work only because both surfaces are hexagonal with a = b.
- **Repeat counts are computed then overridden.** `ceil(target_size /
  a)` yields 17 instead of 16 for SiO₂ and a spurious −6.7% strain, so
  the operator must pass `--supercell 16x16` by hand. Target size and
  commensurability are the same knob; they should not be.
- **Lattice constants are literature values.** The potential's own
  equilibrium lattice differs, which is the *root cause* of the −30 to
  −40 GPa step-zero pressure that its Stage 1.5 relaxation exists to
  absorb. SABSIM matches on potential-relaxed lattices instead.
- **The bilayer assembler is `assemble_bond_slabs`** (`slab_bond_debond/
  bin/primeinput.py:2076`), not the `assemble_bilayer.py` that
  `bilayerrc.py` names — that rc file is dead config, and its `gap` of
  7.0 Å contradicts the assembler's default of 1.0 Å. The assembler
  adopts one slab's box (`box = sio2["box"]`) without checking the
  other's, applies no lateral shift, hardcodes a five-type remap with
  per-type masses and charges, strips ejecta at a 4 Å z-gap heuristic,
  and bonds by **velocity impact** rather than a static press.
- **Warn-and-continue where a gate belongs.** When all four
  symmetrization strategies fail, the code prints that the slab "will
  carry a macroscopic dipole along z" and returns it. Two of those four
  strategies symmetrize by removing atoms, breaking stoichiometry and
  net charge, while the charge-neutrality check sits downstream on the
  assembled bilayer. Terminations are selected as `sym_slabs[0]`, i.e.
  by list order.
- **Generations are not monotonic.** Two slab builders ship side by side
  (only the longer one can symmetrize LiNbO₃ (0001)); the top-level tree
  reverted LiNbO₃ to Buckingham while a nested tree carries the newer
  bond-valence Morse fix. Never assume the newest directory is the best
  physics.

**Genuinely worth keeping:** the four-strategy symmetrization ladder
(especially the direct mirror construction, which is species-generic and
succeeds where pymatgen fails on the R3c stacking); the slab-thickness
convergence study; and "strain before amorphization, because amorphous
material has no lattice to strain cleanly," which is simply correct.
`DESIGN.md` §2.7 records the full keep / replace ledger.

### 1.7 Evaluation of the bond/debond code (2026-07-09)

Done before writing `DESIGN.md` §5. This is the most complete stage in
prior art — it ran, and it produced numbers — and therefore the one that
most needed evaluating. Only the evolved classical tree
(`slab_bond_debond/`) implements it; the MLIP tree has no bond/debond
code at all. The headline figures do not mean what the surrounding
documents say they mean.

**The interface was tuned until it stuck.** With no interfacial
chemistry the surfaces would not adhere: an LJ well of 0.02 eV "let the
surfaces drift apart," so it became a Morse well of D0 = 1.0 eV (about
38 kT at 300 K) applied **identically to all six cross-interface element
pairs** — O–Li, O–Nb, O–O, Si–Li, Si–Nb, Si–O — with r0 = 1.7 Å, which
is unphysically short for, say, Si–Nb. Even then a static press "leaves
the main LiNbO₃ slab detached," so the whole upper slab was given a
−1.5 Å/ps (150 m/s) downward velocity and driven into the lower one. The
reported bond strength is a readout of that well depth and that impact
speed: mechanical interlock, not surface-activated adhesion.

**Same element, two identities.** `_BOND_CHARGES` gives oxygen from the
SiO₂ slab a charge of 0.0 and oxygen from the LiNbO₃ slab −1.178,
assigned by *which slab the atom started in*. After a 150 m/s impact
that intermixes the surfaces, that assignment is meaningless. There is
no cross-interface Coulomb at all. This is STRUCTURAL 1a — a
per-material potential cannot even be *assigned* at an intermixed
interface — demonstrated as a running program.

**Three defects in the bonding input.** Its docstring describes a
`fix move` displacement-controlled press; the code contains no `fix
move`. The thermostat is a plain `nvt` on a group containing the
drifting slab, so 150 m/s of directed motion is counted as heat and the
setpoint is never reached (the log runs ≈227 K against 300 K). And
"Stage B: stop driving" is `velocity linbo3 set 0.0 0.0 0.0 sum yes` —
with `sum yes` that *adds* zero, a no-op; the slab is never stopped.

**The measurement.** Separation is the top grip's centre-of-mass
displacement across a 51.6 Å bilayer, so the work integral contains the
elastic stretch of both slabs and is nonetheless labelled a work of
adhesion. There is no equilibration before pulling (the potential energy
jumps 481 eV in the first 0.5 ps; the first real force sample already
reads −47 eV/Å) and no baseline subtraction. The averaging fix emits a
zero before its first window closes, and that spurious zero anchors both
the first trapezoid of the work integral and the three-point line fit
behind its "Young's modulus = 181.09 GPa." The stated reason for
averaging — that otherwise "the ± thermal noise cancels and the work of
adhesion comes out ~0" — is backwards; noise cancellation is what an
integral should do. Right remedy, wrong reasoning, exactly as with the
thermostat lesson in §1.2.

**Both headline strengths are artifacts.** `strength.txt`'s 1.124 GPa is
`max(−f_z)` over a sign-flipping thermal signal (neighbouring samples
read −36, +38, +3, +21, −30 eV/Å) in the first 1.5 ps. `debond_analysis
.txt`'s 15.308 GPa is the crest of an unequilibrated loading transient.
Neither is a pull-off strength.

**The numbers are unreconstructable.** The two disagree by a factor of
thirteen not because of physics but because the strength analyzer
fetches "the newest `debond.dat` under the job root" and so silently
analyzed the *eight-layer* run, while the adhesion analyzer beside it
read the *four-layer* run; both stamp the same interface area, which is
identical between them and hides the swap. The headline **3.746 J/m² was
computed from a trajectory that stopped at step 122,500 of 150,000**, in
a directory containing `NOTE_INCOMPLETE.txt` ("data here is partial").
The analysis script prints, as a hardcoded string, that the interface
used a 0.5 eV Morse well while the code applied 1.0 eV. Its own bond
analyzer detects and *prints* that the impact left "crushed cross
contacts <1.0 Ang (over-aggressive impact; a debond strength from this
run will read high)" — and reports the strength anyway. Inputs also bake
in an absolute path to another user's home directory.

**Where its design was right.** These are failures of implementation,
not of thinking. Its own `DESIGN.md` §4 specifies gap closure at
0.01–0.1 Å/ps with **contact detection**, a **constant-normal-pressure
barostat** for a nanosecond-scale bonding hold, and adhesion energy as
**(E_bonded − E_separated) / area** — a thermodynamic energy difference.
None of it was built; the code slams, holds 50 ps at constant volume,
and integrates a force curve. SABSIM's §5 press is close to the protocol
prior art *designed and never ran*, and its energy-difference adhesion is
the thermodynamic entry of our measure vector. The lesson is about the
chain, not the student: a design nothing binds to its code will drift,
and the drift surfaces as a number quoted to four significant figures.

**Genuinely worth keeping:** the three-phase arc (approach, hold at
temperature, pull); measuring the reaction force on the pulled grip and
time-averaging it; the non-periodic z-boundary; and the unit conversions
(1 eV/Å² = 16.0218 J/m², 1 eV/Å³ = 160.2176 GPa). `DESIGN.md` §5.9
records the full keep / replace ledger.

### 1.8 Evaluation of the analyzer code (2026-07-09)

Done before writing `DESIGN.md` §6. This covers the measurement layer
(`bin/analyze.py`, 3261 lines) apart from the debond reducers already
dissected in §1.7. **The net result: §6 inherits almost nothing.** There
is no usable definition of the thermodynamic work of adhesion, no
machine-readable output, and no gate — only two sound kernels and a list
of cautions.

**"Bond order" is coordination number.** `run_bond_order_analysis`
counts cation-oxygen neighbours inside a hardcoded 2.6 Å sphere and
names the result a bond order. Bond order is an *electronic* quantity —
exactly one of the descriptors Imago computes, and one STRUCTURAL
2 lists *separately* from coordination. Collapsing them into one name
would silently invite comparing unlike things. SABSIM keeps the
geometric and electronic descriptors nominally distinct, because the
point of the two-fidelity design is that they may disagree.

**Five interface cutoffs, none shared, none derived.** Within one file:
1.0 Å (crush detection), 2.5 Å (contact counting; change analysis),
2.6 Å (bond length; bond order), 3.2 Å (a second contact count), 3.0 Å
(ejecta cleaning), plus a per-material `cn_cutoff` of 2.5 Å. Si-O sits
near 1.61 Å, Nb-O near 1.9-2.1 Å, Li-O near 2.1 Å, and one 2.6 Å sphere
serves all three. Nothing derives a cutoff from the first minimum of the
relevant partial g(r) — although `find_gr_first_peak` exists in the same
file and is used only for the amorphization report.

**The bond-length distribution is a distribution of minima.** Each
cation contributes exactly one length, its shortest (`if r.size and
r.min() < 2.6: bond_lengths.append(r.min())`), so a four-coordinate
silicon records one bond, not four. The reported mean and spread are
therefore biased short and artificially narrow — while the docstring
claims a broadened spread "signals interface strain/disorder," which is
precisely what the estimator suppresses. Cations with no oxygen in range
are dropped silently and never counted.

**Contacts are pairs, not bonds; the interface is one atom.** Both
`run_bond_analysis` and `run_change_analysis` set the interface plane to
the single highest SiO₂ atom (`zint = pos[sio2][:,2].max()`), take 7 Å
windows either side, and count *every* cross-slab pair under 2.5 Å
regardless of species — oxygen-oxygen and cation-cation included. Slab
membership is by atom *type*, i.e. by slab of origin, so an oxygen that
migrated across is still counted on its birth side: STRUCTURAL 1a again,
now in the measurement rather than the potential.

**`run_change_analysis` cannot measure what it claims.** It compares the
bonded and debonded structures with `disp = pd[:n] - pb[:n]` — positional
index alignment, not atom ID — with `n = min(len(pb), len(pd))` silently
truncating when atom counts differ, which is exactly what a lost atom
through the non-periodic boundary produces. It applies no minimum-image
convention to that difference (in a function that calls
`min_image_displacements` five lines later), so any atom crossing a
lateral boundary registers a displacement of about a box length. And it
measures each state's 7 Å window from *that state's own* extreme z, so
after separation the windows are simply far apart and the surviving
contact count is ~0 by construction. "How many bonds broke" is
guaranteed by the geometry of the estimator.

**The verdict and the defect flag both evaporate.** `run_bond_analysis`
already computes the bonded/not-bonded verdict SABSIM makes first-class —
but a single pair under 2.5 Å means "bonded," and the result is printed
to stdout, written to no file, returned to no caller. The crush detector
is the same: `crushed` is a local integer, printed, discarded. **All nine
`WARNING`s in `analyze.py` are bare `print` calls**, one of which reads
`print("WARNING (overridden):" + message)`. Nothing in the file can fail.

**There is no schema.** Every result is a human-readable `.txt` with
`#`-prefixed prose headers (`debond_analysis.txt`, `strength.txt`,
`bond_length.txt`, `bond_order.txt`, `change.txt`, `stress_strain.txt`).
No JSON, no YAML, nothing machine-readable anywhere in `bin/`. No
uncertainty on any number; no record of which potential, seed, or
trajectory produced it — which is how §1.7's truncated run and
wrong-file fetch went undetected. **A gate cannot consume prose.** The
measure-vector schema of `DESIGN.md` §6 is therefore not bookkeeping; it
is what makes the §7 gate possible at all.

**The energy-difference adhesion is specified, unbuilt, and wrong as
specified.** `dev/PSEUDOCODE.md` defines `adhesion_energy = (E_bonded -
E_separated) / interface_area`, with `E_separated` the potential energy
at step 0 of the press and `E_bonded` the mean over the last 20% of the
hold. Four faults, all in the spec: the **sign is backwards** (bonding
lowers energy, so the work of adhesion is `E_separated - E_bonded`); the
states are **not commensurable** (one instantaneous value, carrying the
thermal-initialization spike, minus one time average); it is measured
**across the press**, so it contains all the press's irreversible work
(heating, plastic deformation, the crushed contacts its own analyzer
detects), with nothing subtracted and the separated reference never
re-relaxed as two free surfaces; and it is a **potential-energy
difference, not a free energy**, at 300 K. `surface_energy` remains
unimplemented, exiting with "needs a bulk-energy reference." SABSIM's §6
writes this measurement from scratch, on the relaxed endpoints §5 emits.

**Two designed-but-unbuilt ideas worth taking.**
- `find_contact_step` specifies a **dual contact criterion**: primary,
  `gap = zmin_upper - zmax_lower <= 2.5 Å`; confirmatory, a 1 ps running
  average of `pzz` turning positive. The extremal-atom gap is the
  weakness §2.6 already fixed with a density-profile dividing surface,
  but the **pressure-sign confirmation is sound** and belongs in §5.2's
  contact detection: a gap can close on one asperity, whereas a positive
  normal stress means the surfaces are genuinely loading each other.
- `select_snapshots` specifies three detectors — potential-energy local
  *minima* during the hold (bond-formation events), potential-energy
  local *maxima* during the pull (a bond at maximum stretch), and
  **σ_zz drop spikes** (the mechanical signature of bond-breaking stress
  release) — with near-duplicate frames merged. That is a thoughtful
  answer to an open question in our own `TODO.md` (which step-6/7
  snapshots go to Imago, and how they are chosen). It belongs in §8.

**Step 8 has no code at all, and it targets the wrong code base.** Every
`OLCAO` occurrence in her source is the `$OLCAO_RC` environment
variable, a config-directory convention borrowed from the OLCAO script
template (`XYZ.py` / `recordCLP`) — not electronic-structure work. There
is no input generation and no skeleton prep. §1.1's "design only
(stubs)" is confirmed at the level of grep.

More importantly, **her step-8 plan is written against the legacy OLCAO
code, not against Imago.** SABSIM's step 8 drives *Imago* (the modern
all-electron successor) through *Kaleidoscope*. Imago inherits the OLCAO
input *format* — the two differ only in file layout and command sequence
(confirmed 2026-07-10) — but they do not share an invocation, an rc
convention, or the surrounding run-driver machinery. So the plan's
*physics* transfers — a full-basis choice, Γ-point-only sampling
justified by interface disorder, and the wall-clock cost estimates for
500-2000-atom interface subcells — and the input *format* transfers,
while the *mechanics* around it do not: no rc convention, no `$OLCAO_RC`,
and no script from that lineage should be carried across. Note that the
same legacy
template is the origin of the working-directory-as-configuration
antipattern §1.2 item 7 tells us to leave behind, so importing its
conventions would import that too. `DESIGN.md` §8's skeleton preparation
is a new build against the Imago/Kaleidoscope seam.

**Genuinely worth keeping.** `_box_xy_area` is **correct**, and its
docstring shows the reasoning rather than a guess: for a triclinic slab
box with vectors `a = (lx, 0, 0)` and `b = (xy, ly, 0)`, the in-plane
area is `lx * ly` independent of the tilt. And `min_image_displacements`
is a proper minimum-image implementation that handles the `xy` tilt — it
is simply not used in the one place it matters most. Together with the
density-reference g(r) normalization of §1.2, these are the three sound
kernels in the codebase.

---

<!-- Add further prior-art entries below as they are identified. -->
