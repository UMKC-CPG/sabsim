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
SABSIM will use the DeePMD MLIP, and it drives **OLCAO directly** for
the electronic-analysis end where SABSIM wraps that same OLCAO lineage
inside Imago/Kaleidoscope. There is **no ALF, no active-learning outer
loop** — it is one straight pass, not the nested-loop design of SABSIM.

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
   SABSIM's potential-quality gate will want. The numerical core is well
   factored; only its O(N²) scaling and directory-convention glue would
   need replacing.

**Usable as design input (not code):**

4. **Its `DESIGN.md` §4.4 independently defines the bond metric as an
   adhesion energy in J/m²** (converted from eV/Å²) — the *same work-of-
   separation-per-area* headline number SABSIM settled on (see
   `ARCHITECTURE.md` §2.3, `VISION.md` goal 4). Independent arrival at
   the commensurable unit is a useful confirmation.

5. **Its `DESIGN.md` §5 is a worked-out OLCAO analysis plan** — a full-
   basis (fb) choice, Γ-point-only sampling justified by interface
   disorder, and wall-clock cost estimates for 500–2000-atom interface
   sub-cells. This is directly reusable planning for SABSIM's step-8
   Imago characterization.

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
MLIP fills. Her pipeline + our potential = a working SAB simulator.

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
  bullet points here.)
- **STRUCTURAL 2 (measure vector):** her bond/debond design defines both
  a thermodynamic adhesion energy (PE-difference / area, J/m²) and a
  mechanical σ-vs-separation curve, and the classical tree ran the
  mechanical pull end to end (`ARCHITECTURE.md` §2.3 bond-outcome
  analyzer points here).

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
Morse well, and the result files say so outright (her own bond-strength
outputs even disagree, 15.3 vs 1.1 GPa). This is the sharpest statement
of why SABSIM exists — the pipeline is complete but *blind exactly at the
interface*, where a trained MLIP is required.

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

---

<!-- Add further prior-art entries below as they are identified. -->
