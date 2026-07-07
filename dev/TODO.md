# Task List

> **Document hierarchy:** Tasks are organized by the level of the design
> chain they affect. Each item should cite the relevant document section.

---

## VISION

<!-- Tasks related to goals and principles. -->

- [ ] Bond-outcome metric — now defined as a work of separation per
      unit area (J/m2), commensurable with the Maszara blade test and
      calibrated on relative trends / ratios, not absolute values (see
      `VISION.md` goal 4, `ARCHITECTURE.md` §2.3). Residual: pin the
      exact SAB-regime (not fusion-bonding) reference numbers for Si-Si
      and Si-SiO2, and set the trend / ratio pass criteria the gate
      uses (`VISION.md` goal 4 and principle 5).
- [ ] Define what "characterize the bond" (step 8) actually outputs,
      and how those numbers turn into experimental advice
      (`VISION.md` goal 4). Headline output now decided — a work of
      separation per area; still open is the fuller set of measures and
      how they convert into a concrete recommendation.

---

## ARCHITECTURE

<!-- Tasks related to layout, modules, build. -->

<!-- Pre-DESIGN priority cluster. These four holes are load-bearing for
the DESIGN level and should be resolved before DESIGN.md is filled in.
Raised in the 2026-07-03 refine of VISION + ARCHITECTURE; the first two
were not previously tracked anywhere. -->

- [ ] Quality-gate architecture — partly resolved (2026-07-07). Now
      split into two checks in `ARCHITECTURE.md` §2.3: a potential-
      quality gate (stiffness, surface energies vs VASP / experiment)
      and a separate bond-debond outcome metric (work of separation per
      area, Maszara-anchored, relative). In v1 both only report.
      Residual: decide which module owns each check and stores its
      reference data, whether the reference set is per-material-pair,
      and the exact properties + pass thresholds for the potential gate
      (`ARCHITECTURE.md` §2.3, §3; `VISION.md` goal 4 and principle 5).
- [ ] Inner/outer loop coupling — DEFERRED by decision (2026-07-07).
      ALF is centered on MLIP generation, agnostic to the application,
      so the coupling is NOT about application knobs: the outer loop
      steers ALF by supplying training systems that populate the
      bond-debond application region where the potential is weak. Still
      open — which physical parameters are worth iterating, decided with
      collaborators under finite resources (candidates: composition,
      dopant, activation level, pressure, temperature, Miller faces).
      Revisit then (`ARCHITECTURE.md` §2.3 step 2, §3; `VISION.md`
      principle 5).
- [ ] Outer-loop convergence — DEFERRED by decision (2026-07-07), tied
      to the loop-coupling item above. Near-term goal is narrower: get a
      SINGLE pass of the outer loop working end to end first; only then
      design the repeat logic (weakness-to-new-data mapping, iteration
      budget, non-convergence exit) (`ARCHITECTURE.md` §3; `VISION.md`
      principle 5).
- [ ] Run-specification knobs — RESOLVED for v1 (2026-07-07): the knob
      set is now split in `ARCHITECTURE.md` §2.3 into material knobs
      (crystal structure + one surface face per wafer, material
      identity) and protocol knobs (activation species, activation
      energy AND dose, and press / separate load, depth, duration, and
      speed). v1 freezes every protocol knob to one value; iterating
      them is the deferred outer-loop work. Follow-on: settle the exact
      settings-file shape at DESIGN time.

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
