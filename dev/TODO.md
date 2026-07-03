# Task List

> **Document hierarchy:** Tasks are organized by the level of the design
> chain they affect. Each item should cite the relevant document section.

---

## VISION

<!-- Tasks related to goals and principles. -->

- [ ] Pin down exactly which real-world measurements the quality gate
      checks, and what each is compared against (stiffness, surface
      energies, reference bond strength). Cite `VISION.md` principle 5
      and goal 4.
- [ ] Define what "characterize the bond" (step 8) actually outputs,
      and how those numbers turn into experimental advice
      (`VISION.md` goal 4).

---

## ARCHITECTURE

<!-- Tasks related to layout, modules, build. -->

<!-- Pre-DESIGN priority cluster. These four holes are load-bearing for
the DESIGN level and should be resolved before DESIGN.md is filled in.
Raised in the 2026-07-03 refine of VISION + ARCHITECTURE; the first two
were not previously tracked anywhere. -->

- [ ] Specify the quality-gate architecture (complements the VISION
      "which measurements" item): where each reference / target value
      comes from (experiment, higher-fidelity calc, literature), whether
      the reference set is per-material-pair, and which module owns the
      gate and stores its reference data. Right now
      `passes_our_SAB_quality_tests` is a black box (`ARCHITECTURE.md`
      §2.3, §3; `VISION.md` goal 4 and principle 5).
- [ ] Define the inner/outer loop coupling: how our SAB-weakness
      sampling (outer, ours) composes with ALF's own uncertainty-driven
      sampling (inner, adopted). Does the outer loop hand ALF new seed
      structures, new labeled data, or re-trigger a fresh campaign? This
      seam is the literal adopt-inner / build-outer boundary and is
      currently undefined (`ARCHITECTURE.md` §2.3 step 2, §3;
      `VISION.md` principle 5).
- [ ] Specify the outer-loop convergence mechanism: how a failed SAB
      quality test maps back to which new VASP configs to add (the
      `data_targeting(report.weaknesses)` arrow in §3 is one hand-waved
      line), plus an iteration budget / non-convergence exit so the loop
      is bounded (`ARCHITECTURE.md` §3; `VISION.md` principle 5).
- [ ] Write the material-pair genericity paragraph: name what is
      material-specific (VASP pseudopotentials, ASE slab recipes and
      surface orientation, ZBL parameters, quality-gate reference
      quantities) versus generic machinery, so the retargeting seam is
      explicit before DESIGN (`ARCHITECTURE.md` §2.3; `VISION.md` goal 2
      and principle 1).

- [ ] Decide the outer orchestrator and the triggers for graduating
      from the lean controller to a heavier one
      (`ARCHITECTURE.md` §4).
- [ ] Decide which step-6/7 snapshots get sent to Imago, how many,
      and how they are chosen (`ARCHITECTURE.md` §2.3, step 8).
- [ ] Make the step 3/4/5 ordering a flexible setting, not hardcoded
      (`ARCHITECTURE.md` §2.1).
- [ ] Decide where the ZBL close-range physics is added in the LAMMPS
      simulations (`ARCHITECTURE.md` §2.3 note).
- [ ] Carry "what to run" vs "where to run it" separation into the
      module boundaries (`VISION.md` principle 1, `ARCHITECTURE.md`
      §2.3).
- [ ] Decide which module owns provenance-by-discipline record-keeping
      (each step recording its inputs, exact tool version, and
      settings) (`ARCHITECTURE.md` §2.3 / §4, `VISION.md` goal 3 and
      principle 6).
- [ ] Validate the DeePMD backend end-to-end once real step-1 data and
      a GPU node exist: train + freeze an ensemble (`.pth`, deepmd-kit
      v3 PyTorch backend) and confirm committee `energy_stdev` in ALF's
      sampler (`ARCHITECTURE.md` §2.3, step 2). Converter round-trip is
      already unit-tested.
- [ ] Decide whether the SNAP "how cheap can we go" benchmark backend
      is in scope for v1 or deferred (`ARCHITECTURE.md` §2.3, step 2).
- [ ] Wire UDD as a first-class knob: expose ALF's `use_bias` /
      `E_en_bias_weight` on the committee calculator — a small,
      backend-independent ALF-side change (`ARCHITECTURE.md` §2.3,
      step 2).
- [ ] Add a `LICENSE` file (deferred 2026-07-03). Leaning Apache-2.0
      (explicit patent grant — the SAB process has a patent landscape)
      or BSD-3-Clause (simpler, matches scientific-Python and LANL ALF).
      Before committing one, confirm the grant terms and clear it with
      UMKC tech-transfer / sponsored-programs; copyright holder is
      likely "The Curators of the University of Missouri", not the PI.

---

## DESIGN

<!-- Tasks related to algorithms and data structures, mathematical
foundations, interaction rules. -->

- [ ] Document the MLIP backend-plugin mechanism when DESIGN work
      begins: the ANI-HDF5 ↔ DeePMD unit-factor conversion (round-trip
      already prototyped and unit-tested) and the potential-agnostic
      UDD bias math. `ARCHITECTURE.md` §2.3 forward-references both as
      "DESIGN-level detail" but no DESIGN section covers them yet
      (`ARCHITECTURE.md` §2.3, step 2).

---

## PSEUDOCODE

<!-- Tasks related to algorithm specifications. -->

---

## CODE

<!-- Tasks related to implementation. -->

---

## ARCHIVE

<!-- Resolved items go here. Keep them for reference; use stable numbering
for cross-references. -->
