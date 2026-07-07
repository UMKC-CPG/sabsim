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

### 1.1 Maturity — the docs run well ahead of the code

The single most important thing to know before reusing anything: the
project's **design documents describe far more than its code implements.**

- Its `dev/DESIGN.md` and `PSEUDOCODE.md` lay out a clean, modular
  pipeline (`build_slab.py`, `ar_bombardment.py`, `assemble_bilayer.py`,
  a three-phase `run_bonding_md.py`, `carve_subcell.py`, `run_olcao.py`).
  This is genuinely well-written design.
- The **actual working code** is one self-contained script,
  `bin/primeinput.py` (≈1500 lines, emits LAMMPS input as Python
  strings), plus `bin/build_slab.py` and `bin/analyze.py`. It implements
  **only the relaxation and amorphization stages** — every other stage is
  explicitly refused at runtime.

What has actually run end to end:

| Stage                     | SiO₂                       | LiNbO₃          |
|---------------------------|----------------------------|-----------------|
| Slab build                | works                      | slab only       |
| Relaxation                | works                      | no output       |
| Amorphize (Ar bombard)    | works, **verified** by g(r)| not run         |
| Bilayer assembly          | design only                | design only     |
| Bond/debond MD            | design only                | design only     |
| OLCAO analysis            | design only (empty stubs)  | design only     |

In short: **SiO₂ runs all the way through surface activation and is
validated; LiNbO₃ only gets a slab; and the bond/debond and electronic-
analysis stages — the parts closest to SABSIM's novel bond-outcome
metric — exist here only as design text.**

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
`DESIGN.md` §2.3.** This is a real code/doc mismatch, though moot in
practice because LiNbO₃ amorphization never successfully ran. Flagged
here only so that anyone lifting a force-field number checks it against
a primary source, not this project.

### 1.4 Open question for a future decision

The stages this project *designed but never built* — bilayer assembly
and the three-phase bond/debond MD — are exactly where **SABSIM's novel
outer-loop bond-outcome metric will live.** A live option (not yet
decided) is whether Sunita finishes those stages inside SABSIM's
structure, since she has already reasoned them through on paper. This is
recorded as a possibility, not a plan.

---

<!-- Add further prior-art entries below as they are identified. -->
