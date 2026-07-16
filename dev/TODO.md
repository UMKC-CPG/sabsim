# Task List

> **Document hierarchy:** Tasks are organized by the level of the design
> chain they affect. Each item should cite the relevant document section.

---

## VISION

<!-- Tasks related to goals and principles. -->

- [ ] Bond-outcome metric — now defined as a work of separation per
      unit area (J/m2), commensurable with the Maszara blade test and
      calibrated on relative trends / ratios, not absolute values (see
      `VISION.md` goal 4, `ARCHITECTURE.md` §2.3). v1 runs BOTH the
      Si/SiO2 pair and a Si/Si same-material reference so the relative
      ratio can actually be formed (decided 2026-07-08). The *form* of
      the pass criterion is settled by `DESIGN.md` §7.4 (2026-07-09):
      the ratio against the experimental ratio within the combined
      uncertainty (systematic errors common to both systems cancel to
      first order, which is why the ratio is the trustworthy quantity),
      plus a loose absolute order-of-magnitude bracket that tests only
      the plumbing — a ratio stays correct when both numbers are off by
      the same factor, which is what a unit bug produces. Residual: pin
      the exact SAB-regime (not fusion-bonding) reference numbers for
      Si-Si and Si-SiO2; set the significance level and the bracket
      width; and treat the two works of separation as **correlated**
      when propagating the ratio's uncertainty, since assuming
      independence would throw away the very cancellation that makes the
      ratio worth testing (`VISION.md` goal 4 and principle 5).
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
      Largely resolved at DESIGN level by `DESIGN.md` §7 (2026-07-09):
      the properties are enumerated (§7.2), the pass thresholds became
      significance statements rather than constants (§7.5), and the
      potential gate turns out to run in **two parts at two times** —
      its bulk/surface half must precede the structure builder, which
      §2.2 makes a consumer of the potential's relaxed lattice
      constants, while its interface half cannot run until a
      press-then-pull trajectory exists. Residual: decide which module
      owns each check and **stores its reference data**, and whether the
      reference set is per-material-pair
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
- [x] Member-specification knobs — RESOLVED for v1 (2026-07-07): the knob
      set is now split in `ARCHITECTURE.md` §2.3 into material knobs
      (crystal structure + one surface face per wafer, material
      identity) and protocol knobs (activation species, activation
      energy AND dose, and press / separate load, depth, duration, and
      speed). v1 freezes every protocol knob to one value; iterating
      them is the deferred outer-loop work. Follow-on: settle the exact
      settings-file shape at DESIGN time.

<!-- Second pre-DESIGN priority cluster. Surfaced in the 2026-07-08
review of VISION + ARCHITECTURE before opening DESIGN.md. These are
STRUCTURAL: each one determines what a module IS or what data crosses a
seam, so resolving one wrong would mis-shape DESIGN itself. The three
[STRUCTURAL] items are the "could send DESIGN down a wrong path" set;
[STRUCTURAL 4] is the step-5 lattice hole that the review's linkage
table also marked close-before-DESIGN, kept here so it is not lost. The
three [RISK] items do NOT block DESIGN structure but must be on record
so they are not discovered late (two touch non-negotiable goals). -->

- [x] [STRUCTURAL 1] Bootstrap coverage (was: bootstrap + one-vs-many).
      One half now resolved, one half open.
      **1a one-vs-many — RESOLVED (2026-07-08):** the MLIP is ONE
      multi-species potential over the union of the pair's species. A
      per-material potential cannot even be assigned at an intermixed
      interface, let alone describe the cross-species bonds there, so a
      single potential trained on cross-interface configs (plus each
      bulk/surface) is forced. Per-pair bespoke (retarget = retrain);
      DeePMD is natively multi-element. v1 targets Si/SiO2 (covalent,
      Maszara anchor, short-range MLIP defensible); ionic/polar pairs
      kept as documented future work behind species-generic hooks.
      Captured in `ARCHITECTURE.md` §2.3 MLIP + material-knobs bullets.
      Foundation-model warm-start deferred to 1b below.
      **1b bootstrap coverage — RESOLVED (2026-07-08).** Break the
      circularity with a cheaper config GENERATOR than the production
      MLIP, then VASP-label + ALF-refine: (1) seed a DeePMD on hand-built
      near-equilibrium DFT (bulk Si + cristobalite, surfaces, STRUCTURAL-4
      strained substrates, rattled snapshots; optional foundation
      warm-start); (2) generate the violent Ar cascade on a
      well-validated classical silica potential (BKS / Vashishta) + ZBL —
      amorphous-surface configs made with NO MLIP; interface + separation
      on the seed MLIP; (3) VASP-label a subset, train, ALF-refine on
      committee / UDD uncertainty until below threshold; (4) converge on
      the potential-quality gate + uncertainty threshold (hands to
      STRUCTURAL 3). Engine split: classical + ZBL owns the cascade, MLIP
      only the gentle anneal + steps 6-7 (species stays {Si, O}; also
      resolves the ZBL-placement item below). Safeguards for the
      amorphous structure (glasses are kinetically trapped, so the
      classical start is only a basin): named-quality generator, a
      g(r) / ring / coordination validation added to the potential-quality
      gate vs DFT + experiment, a DFT melt-quench anchor, and a fidelity
      ladder classical -> MLIP re-anneal -> MLIP melt-quench. Captured in
      `ARCHITECTURE.md` §2.3 (MLIP + surface-dynamics + potential-gate
      bullets). DESIGN follow-ons: BKS vs Vashishta, the validation
      metrics + thresholds, seed-set composition, the bootstrap ALF
      convergence threshold, the re-anneal protocol, and the optional
      melt-quench upgrade. (`ARCHITECTURE.md` §2.1 steps 1-2, §2.3;
      `VISION.md` goal 1 and principle 5.)
- [ ] Long-range electrostatics for ionic / polar pairs — RESIDUAL from
      STRUCTURAL 1a (2026-07-08), deferred with v1's covalent Si/SiO2
      scope. A short-range MLIP (DeePMD `se_e2_a`) is defensible for
      covalent pairs but may miss charge transfer and long-range
      Madelung / polarization energetics at a strongly ionic
      ferroelectric interface (LiNbO3). Fix path if needed: a long-range
      extension such as DPLR. Shares a root with the polar-slab dipole
      problem (`PRIOR_ART.md` §1.2 and the structure-builder bullet) — a
      macroscopic dipole is a long-range object a short-range potential
      cannot represent, so slab symmetrization is also what makes a
      short-range MLIP tenable. NOT the same as STRUCTURAL 4 (lateral
      lattice matching, which stays on v1's path). Revisit when an
      ionic/polar pair enters scope; keep the builder + potential
      species-generic with hooks documented until then.
      (`ARCHITECTURE.md` §2.3 MLIP bullet.)
- [x] [STRUCTURAL 2] Where the headline J/m2 number is computed —
      RESOLVED (2026-07-08). Decision: compute BOTH as a **measure
      vector**, not either/or. (1) A MECHANICAL MD work-integral over the
      step-7 pull is the headline and schedule fallback — pure post-
      processing, no Imago needed. (2) A THERMODYNAMIC energy difference
      (work of adhesion) at two fidelities — MLIP-level from a quasi-
      static LAMMPS relax-and-energy sequence, OLCAO-level from Imago on
      relaxed endpoints — whose disagreement doubles as the interface-
      region potential check STRUCTURAL 3 wants. (3) Imago bond
      descriptors (Q*, bond order, coordination) along the snapshot
      series. Endpoints relaxed before Imago; the descriptor series uses
      as-is finite-T frames. Owned by a new bond-outcome analyzer module;
      skeleton-prep split from Imago execution. Captured in
      `ARCHITECTURE.md` §2.3 (analyzer + Imago bullets) and `VISION.md`
      goal 4; DESIGN follow-ons in the DESIGN section below.
- [x] [STRUCTURAL 3] Interface blind spot of the two-gate model —
      RESOLVED (2026-07-08). The potential-quality gate gains an
      interface-fidelity check so an interface-coverage failure is caught
      as a POTENTIAL (data) problem instead of masquerading as protocol.
      Two complementary signals, reusing tools already decided: (i)
      committee / UDD uncertainty along the whole press-then-pull
      trajectory (endpoints + bond-breaking pathway) — cheap, always on,
      catches extrapolation; (ii) an all-electron ΔE cross-check on
      interface subcells (the STRUCTURAL-2 MLIP-vs-reference
      work-of-adhesion) — catches confidently-wrong; reference = VASP on
      a small subcell now (always-on backstop), Imago at scale
      when ready. Diagnosis order for a bad bond number: bulk gate fail
      -> add data; else interface-fidelity fail -> add INTERFACE data;
      else -> genuine protocol problem. Two remedies preserved; the
      interface hole is plugged. v1 = a reported diagnostic label (gate
      is a reporter). No new machinery — reuses STRUCTURAL 2's ΔE + 1b's
      committee + VASP. Captured in `ARCHITECTURE.md` §2.3 (potential-
      quality + new diagnosis sub-bullets) and the §3 loop note. DESIGN
      follow-ons: the uncertainty + ΔE-mismatch thresholds, the VASP
      interface-subcell size, and the report's diagnostic-label schema.
      (`ARCHITECTURE.md` §2.3, §3; `VISION.md` goal 4 and principle 5.)
- [x] [STRUCTURAL 4] Lateral lattice matching for the facing pair
      (step 5) — RESOLVED for v1 (2026-07-08). Reframe: surface
      amorphization makes the interface an amorphous–amorphous contact
      with NO registry requirement (this is why dissimilar bonding works
      at all), so the matching constraint relocates from the interface to
      the crystalline SUBSTRATES, and the amorphous interlayer buffers
      residual misfit -> looser tolerance -> smaller coincidence cells.
      Step 5: coincidence supercell of the two substrate lattices within
      a relaxed tolerance, residual applied as recorded substrate strain,
      activated layers absorb the rest. v1 uses crystalline SiO2
      (β-cristobalite, closest-to-Si polymorph) + crystalline Si, so it
      DOES exercise the coincidence matcher — new build, since prior art
      gave crystalline slabs but its bilayer assembly was design-only.
      Matcher written pair-generic for reuse. Captured in
      `ARCHITECTURE.md` §2.3 structure-builder bullet. DESIGN follow-ons:
      exact faces (a material knob), coincidence indices + misfit
      tolerance, strain split by compliance, cristobalite-vs-quartz, and
      averaging the bond metric over amorphization seeds. Feeds 1b: the
      applied substrate strain is a training-config dimension the MLIP
      must cover. (`ARCHITECTURE.md` §2.1 step 5, §2.3; `VISION.md`
      goal 2.)
- [ ] [RISK] Traceability across six codes. Goal 3 (funded -> every
      guidance number traceable to its exact inputs, versions, settings)
      rests on "provenance by discipline" spanning VASP -> ALF -> LAMMPS
      -> ASE -> Imago with no central store. Discipline across
      heterogeneous tools is fragile for a non-negotiable goal; flag now,
      revisit when the provenance-owner boundary (below) is settled.
      (`ARCHITECTURE.md` §2.3 and §4; `VISION.md` goal 3, principle 6.)
- [ ] [RISK] Retarget cost reality. "Point at a new material pair and run
      mostly automatically" (goal 2) automates the WORKFLOW, not the
      COST: a new pair silently triggers a full step-1 VASP campaign plus
      step-2 ALF training from scratch. Make this explicit so turn-key is
      not oversold. (`ARCHITECTURE.md` §2.1 steps 1-2; `VISION.md`
      goal 2.)
- [ ] [RISK] Critical-path dependency on unfinished Imago deliverables.
      Step 8 is blocked until three parallel Imago efforts land: the fast
      lightweight analysis mode, the ASE -> Imago adapter, and the
      initial-guess potential database (`ARCHITECTURE.md` §4 cross-
      project dependencies). Currently unowned and undated; track as a
      schedule risk on SABSIM's own deliverable.

- [ ] Outer orchestrator — partly resolved (2026-07-08). The execution
      model is now set in `ARCHITECTURE.md` §4.1: three tiers (thin
      sequencer / opaque ALF + Kaleidoscope Parsl / direct jobs), NO
      Parsl-in-Parsl, Parsl as the common dispatch substrate with plain
      `sbatch` for v1. Still OPEN: the heavier workflow / provenance
      manager that may sit on top (Snakemake / jobflow / AiiDA) and the
      triggers for graduating to it (`ARCHITECTURE.md` §4, §4.1).
- [x] Decide which step-6/7 snapshots get sent to Imago, how many,
      and how they are chosen — RESOLVED by `DESIGN.md` §8.3
      (2026-07-10). The three detectors, run on the §8.2 subcell atom
      set, gated by prominence, merged by event; "how many" is a logged,
      refinable frame budget; endpoints always included. (See the §8
      snapshot-selection item below for the full resolution.)
- [ ] Make the step 3/4/5 ordering a flexible setting, not hardcoded
      (`ARCHITECTURE.md` §2.1).
- [x] Decide where the ZBL close-range physics is added in the LAMMPS
      simulations — RESOLVED (2026-07-08, via STRUCTURAL 1b): ZBL is
      overlaid in the classical potential that runs the violent step-4 Ar
      cascade; the MLIP stages (gentle anneal, steps 6-7) need no ZBL,
      though a safety overlay against rare close approaches during
      pressing is a DESIGN-level option (`ARCHITECTURE.md` §2.3 MLIP +
      surface-dynamics bullets).
- [ ] Carry "what to run" vs "where to run it" separation into the
      module boundaries — located (2026-07-08), STRUCTURE decided
      (2026-07-12): the "where" is a single machine-local deployment
      config with TWO sections — a hardware inventory (the per-cluster
      swap unit) and a per-KIND-OF-JOB usage map keyed by resource class
      (`cascade-md`, `bond-md`, direct `vasp`, the `sequence` footprint);
      Tier B (ALF, Kaleidoscope) is EXCLUDED — it owns its own Parsl/SLURM
      and the config points at it, never duplicates it
      (`ARCHITECTURE.md` §4.1). The input fork was also resolved: the CWD
      study spec is self-complete (material + protocol + numerical +
      ensemble); the rc-style file is deployment-ONLY, no layered defaults
      (`DESIGN.md` §1.2, §1.4). Serialization FORMAT resolved to **TOML**
      (ratified 2026-07-13, `DESIGN.md` §1.8); the schema mechanism on
      top of it stays a follow-on. Templates authored:
      `dev/templates/study_spec.toml` and `dev/templates/deployment_rc.toml`.
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
      step 2). **Promoted from convenience to load-bearing** by
      `DESIGN.md` §7.3 (2026-07-09): the bounded exploration launched at
      an uncertainty abort *is* a UDD run. The abort trigger and the UDD
      bias respond to the same committee spread with opposite intent —
      a production run avoids it to make a measurement, a data-
      generation run seeks it to find the potential's holes.
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
- [x] STRUCTURAL 2 DESIGN follow-ons — RESOLVED by `DESIGN.md` §5-§6
      (2026-07-09), except (d). (a) **Both:** a constrained-minimization
      ladder at prescribed interface openings is the primary reversible
      curve, and relaxing the dynamic-pull snapshots is a cheap second
      curve whose gap from the ladder measures how far the pull rate sits
      from quasi-static (§6.4 M3). (b) The measure-vector schema is §6.6;
      it is machine-readable, every record carries uncertainty, units,
      fidelity, method and status, and the gate reads by name and status,
      never by position. (c) Settled in §5.4-§5.5: both grip reaction
      forces (Newton check), time-averaged with the warm-up discarded,
      peak extracted above a noise floor, integrated over grip
      displacement from the gated zero-load reference to complete
      separation, with the interface-opening curve emitted alongside;
      area is the §2 shared cell's `lx*ly` (tilt-independent).
      **(d) RESOLVED by `DESIGN.md` §8.4** (2026-07-10): skeleton
      preparation is a pure function of structure + settings, testable by
      exact comparison against a known-good input with no Imago present.
      Imago inherits the OLCAO input *format* (file-layout and
      command-sequence tweaks only), not the `$OLCAO_RC` convention. See
      the §8 skeleton-prep item below.
- [ ] §6 numeric follow-ons: the annealing schedule behind
      `work_of_adhesion_relaxed` (an amorphous surface is kinetically
      trapped, so the schedule is a recorded knob); the constrained
      ladder's opening spacing; the free-energy estimator for the
      `free_energy_correction` entry; the tolerance at which the
      interface subcell is declared converged (its *size* is no longer a
      constant to choose — §6.4 makes it the outcome of a convergence
      test run with the potential itself); and the numeric tolerances on
      every check in `DESIGN.md` §6.5 (dissipation >= 0, healing >= 0,
      rate monotonicity, ladder closure, subcell truncation).
- [ ] RDF + DOS as human-read spectra (added to `DESIGN.md` §6.4, §6.6,
      §8.6, §8.7 on 2026-07-11). The surface-region partial RDF is
      tracked across named stages and the DOS/partial-DOS come from Imago
      (VASP backstop); both are stored as by-reference curve ARTIFACTS
      for human reading, NOT auto-reduced — the only reduced scalars are
      the DOS's `dos_at_fermi` and `gap_size`. Definitions still to pin:
      (a) the exact set of NAMED STAGES and the surface-region atom
      window (a depth from the §2.6 dividing surface) the RDF samples;
      (b) how `dos_at_fermi` and `gap_size` are measured (broadening,
      the E_F window, the gap criterion for a possibly gapless
      interface). (c) `contact_area_fraction` — DEFINED 2026-07-11 as a
      grid-based BONDED contact fraction (equal-area fractional grid; a
      cell counts when it holds a cross-interface bond midpoint),
      `DESIGN.md` §6.4 + `PSEUDOCODE.md` §8.8. Only its numeric knob
      `contact_grid_spacing` remains to pin, with an insensitivity check.
- [ ] Interface definition is plural (`DESIGN.md` §6.2, 2026-07-11).
      Provenance (build-time identity) is the DEFAULT cross-interface
      test; an alternative — the SURFACE OF MINIMAL BOND STRENGTH (a
      weakest-cut, i.e. the fracture surface) — better handles truly
      integrated transferred atoms but is non-unique (bond strength has
      several measures: pair energy, force-to-break, electronic bond
      order, coordination depth). To DO if useful: register the
      minimal-strength interface as a §6.7 measure and report its
      DISAGREEMENT with provenance as a true-transfer observable; the §5
      pull's post-fracture M2 pieces are its a-posteriori realization.
- [ ] Bond/debond MD §5 depth-first pass DONE (`PSEUDOCODE.md` §9,
      2026-07-11). The stage-output seam was RENAMED (2026-07-11):
      variable/parameter `bond_debond_trajectory`, type `BondDebondResult`,
      contract `BOND_DEBOND_CONTRACT`; the per-pull `Trajectory` record
      keeps its name. `run_analyzer` now reads `.press` into `Verdicts`
      and iterates `.pulls` for `per_rate` measures. Left for the
      programmer: (1) pin the numeric values of the knobs the pass
      declared — `press_temperature`, `press_approach_rate`,
      `contact_gap_threshold`, `bonded_contact_threshold`,
      `force_average_window`, `reference_pe_drift` — plus `DESIGN.md`
      §5.9's own open numbers (target bonding pressure, hold duration,
      noise floors). (2) Pin the REPRESENTATIVE-pull rule: non-`per_rate`
      measures that need a pull (M2, M4, M5-electronic) run on the slowest
      rung by current design — confirm "slowest = representative" in
      `DESIGN.md` §6.4. Also noted: `separation_speed` (ProtocolKnob) is
      the single-rate special case, superseded by
      `numerical.pull_rate_ladder`.
- [ ] Activation §3 depth-first pass DONE (`PSEUDOCODE.md` §10,
      2026-07-12). The step-4 output became a concrete seam:
      `activate_surfaces` returns ONE `ActivatedSlabs` (both activated
      slabs AND both gate verdicts), guarded by `ACTIVATED_SLABS_CONTRACT`;
      the §1 unpack, the §6 `stub_activate` honoring note, and the §3
      contract index were rippled to match. New ProtocolKnobs declared:
      `activation_mechanism`, `activation_cospecies` (+fraction),
      `cascade_duration`, `between_impact_relaxation`, `reanneal_schedule`.
      Left for the programmer: (1) pin those knobs' VALUES plus the frozen
      v1 fluence / energy / normal incidence — the validation-metric
      thresholds and the re-anneal protocol are already tracked in the
      STRUCTURAL 1b follow-on below (g(r) / ring / coordination vs DFT +
      experiment), so not duplicated here. (2) WIRING decision: `DESIGN.md`
      §3.5 says the activation gate "feeds the potential-quality gate (§7;
      STRUCTURAL 1b)", but §10 only gates the PIPELINE at the §1 seam — the
      `ActivationVerdict` is not yet threaded upward into `MemberResult` /
      the §7 gate. Decide whether the verdict surfaces in the member report
      (a sequencer concern above §10's module scope).
- [ ] Bootstrap §4 depth-first pass DONE (`PSEUDOCODE.md` §11,
      2026-07-12) — the FIFTH and last buildable-unit pass
      (`ARCHITECTURE.md` §5.2), closing the "all modules at depth" count
      from four to five (the bootstrap had been deferred as "the Wave-2
      thing behind the seam"). §11 refines `DESIGN.md` §4.5's seed ->
      generate -> label -> retrain -> refine loop as ORCHESTRATION over
      the already-written stages: config generation REUSES activation
      (§10) and bond/debond (§9) in "generate mode" (harvest trajectory
      frames, no stage fork), and training/labeling/conversion DELEGATE to
      the two ALF contracts plus the `prototypes/alf_deepmd/` converter
      (`DESIGN.md` §4.2-§4.4). The bootstrap is a TOP-LEVEL process above
      `exec_one_member` (it manufactures ONE fingerprinted potential per
      pair; §1's `resolve_potential` is a LOOKUP, not a training call). A
      §1 MARKER now records that the potential-quality gate's ACTING form
      is the bootstrap's convergence check (§11.6) — which is precisely
      why the production-side bulk/surface gate only REPORTS. Left for the
      programmer: the §4.6 numeric values are already tracked in the
      STRUCTURAL 1b follow-on (descriptor/r_cut, `n_models`, loss
      schedule, `Escut`/`Fscut`, UDD weight, committee-sigma convergence
      threshold, seed-set composition), so not duplicated here.
- [ ] STRUCTURAL 1b DESIGN follow-ons: BKS vs Vashishta as the silica
      generator, the amorphous-structure validation metrics + thresholds
      (g(r) / ring / coordination vs DFT + experiment), the seed-set
      composition, the bootstrap ALF convergence threshold, the MLIP
      re-anneal protocol, and the optional MLIP melt-quench upgrade
      (`ARCHITECTURE.md` §2.3 MLIP + potential-gate bullets).
- [x] STRUCTURAL 3 DESIGN follow-ons — RESOLVED by `DESIGN.md` §7
      (2026-07-09), except the bare numbers. The diagnostic-label schema
      is §7.8 (verdict / cause / basis / fired / unresolved / power /
      remedy / provenance). The interface-subcell *size* is no longer a
      quantity to choose: §6.4 makes it the outcome of a convergence
      test run with the potential itself (`subcell_truncation_error`),
      so the cheap method certifies the expensive method's input. The
      thresholds became *significance statements* rather than constants,
      because §6.6 forbids bare numbers and every gate comparison
      therefore carries an uncertainty (§7.5). Two additions changed
      `ARCHITECTURE.md` §2.3 in the same commit: `void` at the head of
      the chain (a measurement that is not a measurement is never
      diagnosed) and a `basis` field recording whether `protocol` was
      reached by direct evidence or by elimination (§7.7).
- [x] §6.4 defect FIXED (2026-07-09), recorded for the lesson it
      carries: the interface-fidelity check originally read `M4 - M2`
      with M4 on a subcell and M2 on the full cell, conflating the
      fidelity difference with a box-size difference. It is now M4 minus
      M2 on the *same* subcell, gated by M2(full) - M2(subcell). The
      transferable rule: **any comparison of two methods must fix the
      system, and any comparison of two systems must fix the method.**
      Worth checking for the same shape wherever else the chain compares
      quantities computed different ways.
- [ ] §7 numeric follow-ons: the quantile that calibrates the
      committee-uncertainty threshold; the significance level for the
      fidelity cross-check; the width of the absolute sanity bracket;
      the committee evaluation stride, the persistence window, and the
      abort budget (§7.3); the step budget and plausibility ceiling
      bounding the UDD exploration launched at an abort; and the
      composition of the harvested batch (stratified baseline vs
      excursion).
- [ ] §8 numeric and interface follow-ons (opened by `DESIGN.md` §8.9):
      the smoothing window and prominence threshold behind each of the
      three detectors; the frame budget and the refinement that shows it
      adequate; the merge tolerance (the sub-noise energy gap below which
      two frames with an identical cross-interface bond set are one); the
      one-time denser-mesh check that demotes Γ-only to a tested
      numerical setting; the exact file-layout and command-sequence
      differences between Imago and legacy OLCAO; the atom-count envelope
      check of §8.2 and what §2's coincidence tolerance must be to keep
      the subcell affordable for v1's pair (the coincidence tolerance
      prices step 8); and Imago's failure taxonomy — which failures are
      retryable and which are structural, since §8.6's coverage-by-class
      rule needs to tell them apart.
- [ ] §7.7's open question, deliberately surfaced rather than hidden:
      the inventory of protocol checks (rate-ladder convergence, press
      contact quality, the dissipation identity, ladder closure) was
      assembled for other purposes and has **not** been argued to span
      the ways a protocol can be wrong. The `basis: by_elimination`
      count is the instrument that measures how sparse it is.
- [ ] Confirm whether ALF exposes the **per-atom** committee spread or
      only the global `energy_stdev`. DeePMD's energy is a sum of atomic
      contributions so the quantity exists; §7.3 uses it to localize the
      potential's ignorance, and §6.4 uses that to center the interface
      subcell. A code-level question for PSEUDOCODE
      (`prototypes/alf_deepmd/`, [[alf-pluggable-mlip-backend]]).
- [x] Wording audit, deferred from the Imago rename — RESOLVED
      (2026-07-10). Ruling from the programmer: Imago inherits the OLCAO
      input *format* (only file-layout and command-sequence tweaks), so
      "structure in OLCAO format" is legitimate, not stale, and OLCAO
      names both the method Imago implements and the input convention it
      kept. The earlier `PRIOR_ART.md` claim that the two "share no input
      format" was an overstatement and has been narrowed in three places
      (§ intro, §1.2 item 5, §1.8): the *format* transfers; the rc
      convention, invocation, and `$OLCAO_RC` machinery do not.
      Captured in `DESIGN.md` §8.4 and §8.9.
- [ ] STRUCTURAL 4 DESIGN follow-ons — mostly answered by `DESIGN.md`
      §2 (2026-07-09). Settled there: the matcher is a whole-number
      tiling-matrix + in-plane-twist search (Zur-McGill, adopted from
      `pymatgen`) over a strain *tensor*, not a scalar length match; the
      strain split is weighted by each slab's biaxial stiffness times
      its thickness (an even split is the equal-weight special case);
      lattice constants come from a bulk relaxation under the current
      committee, referenced to VASP; the facing pair (not the slab) is
      the object the builder constructs. Still OPEN: the exact Si and
      SiO2 Miller faces (a material knob), the numerical misfit
      tolerance + cell-area/atom-count budget, cristobalite-vs-quartz,
      and how many amorphization seeds the bond metric is averaged over
      (`ARCHITECTURE.md` §2.3 structure-builder bullet; `DESIGN.md` §2).
- [ ] Structure-contract schema: the labeled atom groups the builder
      emits (frozen base, thermostat border, NVE interior, activated
      skin, press/pull grips, per-slab id) and consumed across the
      step-3/4/5/6/7 seam — introduced in `DESIGN.md` §2.6, needs its
      concrete field list. Prior art re-derives these regions ad hoc in
      every LAMMPS input from hardcoded layer thicknesses.
- [ ] Slab-thickness convergence: `DESIGN.md` §2.5 sets the criterion
      `slab_thickness >= activated_depth + minimum_bulk_thickness`,
      where `activated_depth` is measured by the §3.5 depth profile.
      Pin `minimum_bulk_thickness` and run the convergence study.
- [ ] STRUCTURAL 2 / §5 follow-ons opened by `DESIGN.md` §5
      (2026-07-09): the target bonding pressure and hold duration; the
      noise-floor thresholds for the zero-load reference state, for
      "force returned to zero," and for calling a force peak resolved;
      the contact-quality definition's bond-counting cutoff; and the
      ensemble size (amorphization seeds x velocity seeds). Also pin the
      pull-rate ladder's three rates (`DESIGN.md` §5.4, §5.9).
- [ ] Press-mode seam: `DESIGN.md` §5.2 freezes load-controlled press
      for v1 with a displacement-controlled cross-check on the Si/Si
      reference. Specify the seam's contract (both modes emit load AND
      depth reached) and the reversibility comparison between them.
- [x] §6 follow-ons opened by the analyzer evaluation (`PRIOR_ART.md`
      §1.8) — RESOLVED by `DESIGN.md` §6 (2026-07-09). The schema is
      machine-readable with per-record uncertainty, units, fidelity,
      method and status (§6.6); bond cutoffs are derived per species
      pair from the first minimum of that pair's partial g(r), and a
      measure whose cutoff is unresolved is marked `unresolved` rather
      than defaulted (§6.3); geometric coordination and electronic bond
      order are separate named families (§6.4 M5); and cross-interface
      bonds are identified by a per-atom **provenance label** kept
      distinct from **species** — one field per job, where prior art had
      one field doing both (§6.2).
- [x] Thermodynamic work of adhesion (§6) — RESOLVED (2026-07-09).
      Written from scratch; prior art's spec is not adopted. **Two named
      references**, because they answer different questions: pieces are
      identified by bonded-cluster connectivity, then
      `work_of_adhesion_as_fractured` relaxes each only into its nearest
      minimum (matched to the mechanical pull, so their difference is
      dissipation and nothing else) and `work_of_adhesion_relaxed`
      anneals each so its surface reorganizes (the reference that
      connects to `W = γ_A + γ_B − γ_AB`, whose surface energies are
      defined for equilibrium surfaces). Their difference is reported as
      `surface_healing_energy`, and `transferred_atom_count` beside it.
      Each is reported **twice**: a zero-temperature potential-energy
      difference (headline, comparable to the all-electron 0 K
      cross-check) and a `free_energy_correction` at the press
      temperature, whose ensemble may be smaller because it needs a
      phonon calculation per endpoint (`DESIGN.md` §6.4 M2).
- [x] §8 snapshot selection — RESOLVED by `DESIGN.md` §8.3 (2026-07-10).
      Adopted the SHAPE of prior art's unbuilt `select_snapshots` (PE
      hold-minima, PE pull-maxima, σ_zz drop spikes, near-duplicates
      merged), with three fixes it lacked: the detectors run on the §8.2
      subcell atom set (where the event is, not the noisy whole cell);
      candidates must clear a prominence threshold above §5.4's noise
      floor; and near-duplicates merge by *event* (identical
      cross-interface bond set + sub-noise energy gap), not by geometric
      RMSD. Endpoints are always included; the frame budget is a
      numerical setting whose drops are logged.
- [x] §8 skeleton prep — RESOLVED by `DESIGN.md` §8.4 (2026-07-10). A
      NEW build against the **Imago** seam, a pure function of a
      structure and a settings object (no clock, no working directory,
      no environment), testable by exact comparison against a known-good
      input with no Imago present. Correction from the earlier framing:
      Imago *does* inherit the OLCAO input format (file-layout and
      command-sequence tweaks only); what it does not inherit is the
      `$OLCAO_RC` working-directory-as-config convention (the §1.2 item 7
      antipattern) or any script from that lineage.
- [x] Settings-file shape — RESOLVED by `DESIGN.md` §1 (2026-07-09).
      The configured object is a **study** (members + relations), because
      §7.4's criterion is a ratio and a ratio belongs to a *pair* of
      members; a member still stands alone and studies may be assembled
      after the fact. Knobs split into **five** groups by a sharp test — a
      numerical setting's effect must vanish under refinement, a
      protocol knob's effect *is* the physics — with ensemble (seeds)
      separate because a seed is sampled, not tuned, and deployment in
      its own document (§4.1). No hidden defaults: the loader rejects an
      incomplete spec; defaults exist only as a generator that emits a
      fully-populated file. Protocols are identified by a **content
      fingerprint**, not a version number (versioning is too linear;
      protocols branch). Lattice constants, the shared cell, bond
      cutoffs, subcell size and activated depth are **derived, never
      settings**. `ARCHITECTURE.md` §2.3's member-spec bullet amended in
      the same commit.
- [ ] §1 follow-ons: the serialization format and schema mechanism; the
      exact fingerprint definition (which fields it covers, and how a
      field declared irrelevant to comparability is excluded); how
      relations beyond `ratio` are expressed; and the initial sorting of
      difference-set fields into *entailed* vs *incidental*, which is a
      physics judgment, not a schema one, and will need revisiting as
      relations are added (`DESIGN.md` §1.1, §1.4, §1.8).
- [ ] §1 gave every open numeric follow-on a single home. The values
      themselves — §2's tolerances, §3's gate thresholds, §5's rate
      ladder, §6.5's check tolerances, §7's quantile / stride /
      persistence window / abort budget / bracket width — must all
      appear in the specification file, since nothing may fall back to a
      hidden code default. Pinning them is still open; **housing** them
      no longer is.
- [x] Value pinning RATIFIED (2026-07-13): the literature-anchored v1
      knob values in `dev/V1_VALUES.md` are accepted. The three forks
      resolved: **Ar energy 500 eV** default (user-overridable across
      50-500 eV, optionally lower e.g. 50 eV); **3 amorphization seeds**;
      **beta-cristobalite(100) SiO2 / Si(100)**. Format = **TOML**. The
      values are distilled INTO DESIGN §2.7 (faces), §3.6 (energy /
      fluence-to-depth / seeds), §5.9 (pressure / temperature / hold /
      rate ladder); §4.6 needed no change (the forks touch no MLIP-backend
      knob). Templates authored under `dev/templates/`. Face, polymorph,
      material, energy, and seed count are v1 DEFAULTS, not freezes.
- [ ] Tier-D numeric follow-ons are NOT "pick a value" — they are
      derived or need reference DATASETS (`DESIGN.md` §1.3): lattice
      constants, shared cell / tiling / strain, bond cutoffs, the
      interface-subcell size, the activated depth, and the potential; the
      gate THRESHOLDS (g(r), ring stats, coordination, surface energies,
      the Maszara ratio) need reference data, not chosen constants. These
      are reclassified out of value-pinning; resolve them via their owning
      section's derivation or convergence study, not by typing a number.
      See `dev/V1_VALUES.md` "Tier D".
- [ ] Principle recorded by `DESIGN.md` §1.1, worth defending in review:
      **report, never restrict.** Refusing to evaluate and refusing to
      certify are different acts, and SABSIM performs only the second. A
      relation whose controls disagree, or which is confounded, is still
      computed and reported with its difference set; only the *gate's
      verdict* is withheld. `unresolved` is a statement about the gate's
      competence, never about whether a number may exist. Watch for this
      eroding as gates are implemented — the temptation to refuse the
      computation will be strong and must be resisted.

---

## PSEUDOCODE

<!-- Tasks related to algorithm specifications. -->

- [ ] First PSEUDOCODE pass follows `ARCHITECTURE.md` §5.4 — **breadth-
      first shallow, then depth-first per module.** Pass 1 covers only
      control flow and the seam schemas (Tier-A sequencer, member-spec
      load/validate, the labeled-group structure contract, the measure
      schema, the gate precedence chain) — the walking skeleton expressed
      as pseudocode. Deep per-module algorithms (coincidence matcher, UDD
      bias, detector prominence math) are deferred to when each module is
      implemented behind its already-frozen contract. Writing them all to
      full depth up front is itself a way to code into a box (§5.1). Open
      scope question for the session that starts this: confirm the Si/Si
      walking-thread membership from §5.3 Wave 0 before pseudocoding it.
- [x] `/refine` note — sequencing check RAN (2026-07-12). The standing
      ask (does the pseudocode's SHAPE — build order, skeleton-first —
      obey `ARCHITECTURE.md` §5.3's waves, not just its content?) was
      executed. Result: Wave-0 order (§6 vs §5.3), the steps-3/4/5 reorder
      freedom, and the potential/characterization seams all matched. ONE
      substantive finding — the potential-quality gate's two-times split
      (`DESIGN.md` §7.2: bulk/surface BEFORE the builder) was absent from
      §1's control flow — was resolved not by moving the production gate
      but by recognizing its ACTING form lives upstream in the bootstrap's
      convergence check: a §1 marker plus the new bootstrap pass
      (`PSEUDOCODE.md` §11; see the DESIGN-section DONE item above). The
      pre-existing per-atom-committee-spread question stays filed in the
      DESIGN section, tagged "a code-level question for PSEUDOCODE".
- [x] `/refine` leftover — FIXED (2026-07-12): the §6 walking-skeleton
      snippet had shown the PRE-ripple bare-`slabs` flow, contradicting
      §1's post-ripple `ActivatedSlabs` unpack. Now updated to
      `(slab_A, slab_B, shared) = build_slabs(...)` ->
      `activated = stub_activate(slab_A, slab_B)` -> the `slab_A`/`slab_B`
      rebind -> `assemble_pair(slab_A, slab_B, shared)`, matching §1. The
      prose honoring note below it was already correct (`PSEUDOCODE.md`
      §6).
- [x] Second whole-chain `/refine` after §11 (2026-07-12): chain
      consistent (VISION->ARCH, ARCH->DESIGN untouched; DESIGN->PSEUDOCODE
      faithful — §11 maps 1:1 onto DESIGN §4.5; PSEUDOCODE->Code still
      N/A). ONE finding, FIXED same turn: the potential-quality gate was
      asserted to be "the same gate" acting upstream (§11.6) and reporting
      downstream (§5) but was NOT a shared unit — §5 inlined its two
      checks and §11.6 named a `run_potential_quality_gate` defined
      nowhere. Factored `potential_quality_gate` into ONE §5 function that
      both `evaluate_member_gates` (reads into the five-way diagnosis) and
      §11.6 (acts on `.passes`) call, added `PotentialQualityVerdict`, and
      retyped `ConvergenceReport.quality_gate` to it. Also recorded a
      no-change observation: two top-level entry points now exist
      (`exec_full_study`, `bootstrap_potential`) with manual v1 ordering —
      consistent by design (`PSEUDOCODE.md` §5, §11.6).
- [ ] Step-8 characterization §12 pass DONE (`PSEUDOCODE.md` §12,
      2026-07-13) — the SIXTH and last module pass, on `DESIGN.md` §8,
      CLOSING the DESIGN->PSEUDOCODE boundary (all five buildable units +
      the frame now at depth). The four SABSIM-side artifacts are pure
      functions: selector (§12.2), skeleton-prep (§12.3), manifest
      (§12.4), harvester (§12.5). TWO narrow spots stay `[DEPTH-FIRST]`
      pending the in-development Imago — the exact input file-layout /
      command-sequence (§12.3) and Imago's failure taxonomy (§12.5) —
      the honest limit of "finish the pseudocode" pre-Imago (`DESIGN.md`
      §8.8: the SABSIM side needs no Imago; only execution does). CODE
      follow-on: §12 declared three new NumericalKnobs in §2
      (`detector_smoothing_window`, `detector_prominence`, `frame_budget`);
      add them to `src/sabsim/spec/records.py` + the study-spec template
      when step-8 is built (Wave 4). Their VALUES are the DESIGN §8.9
      follow-ons tracked above.

---

## CODE

<!-- Tasks related to implementation. -->

- [x] Wave-0 walking skeleton BUILT and tested (2026-07-13) — the
      `ARCHITECTURE.md` §5.3 Wave-0 target reached: the Tier-A thread runs
      end-to-end on Si/Si to an HONESTLY UNTRUSTED measure. What exists
      under `src/sabsim/`: the study-spec loader + records (`spec/`, no
      hidden defaults, `PSEUDOCODE.md` §1.4), the sequencer with the
      `run_to_contract` guard plus the measure and exec-artifact schemas
      (`pipeline/`, `PSEUDOCODE.md` §1), stub stages that pass through
      honest verdicts (`pipeline/skeleton_stages.py`), and the minimal
      Si-(100) slab / facing-pair builder (`structure/si_slabs.py`,
      `PSEUDOCODE.md` §7 minus the matcher). 25 tests pass (loader 9,
      sequencer 11, slabs 5). Commits `8537d69`, `c576c9e`, `1ca43cc`.
- [ ] NEXT — replace the skeleton stubs with the real Si/Si run, in
      slices, each landing behind its already-frozen contract. Order:
      1a. GENERAL slab builder — DONE (2026-07-14). ONE
         `structure/slab_builder` (retired the Si-only `structure/si_slabs`
         stand-in) reads a crystal from a CIF (the authoritative
         structure, `DESIGN.md` §1.2) plus a Miller face, cuts the slab
         (pymatgen `SlabGenerator`), and assembles the facing pair through
         pymatgen's Zur-McGill matcher (`DESIGN.md` §2.3 — the ADOPTED
         algorithm, NOT hand-written). No per-material or per-pair script:
         Si/Si is just the first INPUT and exercises the matcher's
         identity/null case (`DESIGN.md` §2.548). `MaterialKnobs` gained a
         CIF source (`spec/records.py`); the loader and study-spec template
         moved with it (no hidden defaults, §1.4). Ships a real Si diamond
         CIF as reference data. 7 unit tests on Si/Si (build, identity
         match, gap, box, type map, LAMMPS round-trip). Login-node geometry
         (pymatgen + ASE membrane), NO force engine. Commit `PENDING`.
      1b. Wire the builder into the pipeline — DEFERRED, coupled to the
         compound build (wave 3). `build_slabs` / `assemble_pair` cannot
         switch to the real builder yet: the live study runs the SiO2/Si
         member, whose real build needs the strained-mismatch assembly
         (`DESIGN.md` §2.4), the SiO2 CIF, and surface-energy termination
         — all wave-3 / execution-layer work. Slice 1a REFUSES a real
         mismatch rather than faking it, so wiring waits for that wave (or
         a Si/Si-only integration path). The skeleton stub stands until
         then; the pipeline stays green end-to-end.
      2. Driver command-generation — DONE (2026-07-14). New `driver/`
         package: `driver/commands.py` maps a `BuiltPair` + protocol/
         numerical knobs to the ordered LAMMPS command stream for the
         press (§9.3) and pull (§9.5). PURE `{value,unit}` -> command
         mapping (metal-units conversion + pressure->force), no LAMMPS.
         The force-model line is a PARAMETER (`ForceModel`): classical
         stand-in (`classical_si_stand_in`) now, trained MLIP
         (`deepmd_model`) later — BOTH served by one generator. BOTH
         control modes generated (load = ramped `aveforce`, displacement
         = `fix move`), one command apart (`DESIGN.md` §5.2). Region
         carving, bias-removed Langevin thermostat (§5.2), grip drives,
         and strided recording all pure functions. 15 unit tests; full
         suite 42 passed. NOTE: the mid-run STOP conditions (dual contact,
         separation) are slice 3, and the region thicknesses + load-ramp
         schedule are documented §3/§5.9 stand-ins, flagged in code.
      3. Control + analysis math — DONE (2026-07-14). `driver/analysis.py`
         is the pure numerics the live driver reads back with:
         density dividing-surfaces + interface opening (§2.6), the
         no-impact gate + DUAL contact criterion (§9.3), the two
         settle-reference gates (§9.4), and the displacement-windowed
         averaged force curve (leading warm-up dropped), its
         re-expression vs interface opening, the separation point, and
         the atom-count gate (§9.6). PURE array math, NO LAMMPS. 13 unit
         tests; full suite 55 passed. NOTE deferred: the bonded-quality
         grading (`contact_quality`, cross-interface bonds + contact
         fraction) reuses §8 geometric machinery not yet built; the
         quasistatic margins are documented §5.9 stand-ins.
      4. Bulk-relaxation execution — MOCK SIDE DONE (2026-07-14). The
         FIRST, smallest use of the force engine: relax the bulk under the
         current (classical stand-in) model to DERIVE the lattice, so the
         hardcoded 5.43 A stand-in is retired (`DESIGN.md` §2.2 cold
         start). Introduced the narrow engine seam `driver/engine.py`
         (`Engine` ABC + `MockEngine`) so the orchestration is written
         ONCE and tested with NO LAMMPS. `driver/bulk_relax.py` builds the
         `p p p` box/relax minimize stream and derives the cubic lattice
         from the relaxed box; `structure/slab_builder.write_bulk_data`
         writes the bulk block. 9 tests; full suite 64 passed. REMAINING
         (compute node): the REAL `Engine` adapter wrapping the LAMMPS
         Python binding (~100-150 lines: `commands`->`commands_list`,
         `energy`/`box`/`atom_count`->extracts) — the ONLY piece the mock
         cannot de-risk; write + debug it against live LAMMPS via
         `srun -n N python` (NOT the login node), plus confirm the emitted
         command strings parse and the `Si.sw` potential loads.
      5. Press/pull execution layer — MOCK SIDE DONE (2026-07-14).
         `driver/press_pull.py` is the three §9 control loops — press to
         the DUAL contact criterion (§9.3), settle to the gated zero-load
         reference (§9.4), pull to complete separation then reduce (§9.5,
         §9.6) — written ENTIRELY against the `Engine` seam, so each
         mid-run decision is exercised against a SCRIPTED `MockEngine`
         (opening closes, stress turns positive, force decays) with NO
         LAMMPS. Extended the seam with `positions` / `normal_stress` /
         `grip_reaction`. 6 tests; full suite 70 passed. REMAINING
         (compute node): (a) the REAL `Engine` adapter — SKELETON DRAFTED
         at `driver/lammps_engine.py` (best-effort binding calls +
         `# VERIFY` markers; API surface import-confirmed, lazy import so
         it loads with no LAMMPS; interface-completeness tested). Fill in
         + debug against live LAMMPS via `srun -n N python`, NOT the login
         node — the ONE adapter serves BOTH slice 4 and 5; (b) thin
         sequencing of
         press+settle+pulls into a `BondDebondResult` with a fresh
         restore per pull rung (persistent-engine lifecycle, real-adapter
         territory); (c) the bonded-quality grading (§8 machinery, still
         deferred).
      Slices 1-3 are login-node work; slices 4-5 are compute-node
      integration (the two that need LAMMPS). The Wave-4 knob follow-on
      (three §2 NumericalKnobs) is tracked in the PSEUDOCODE section
      above.
- [ ] Phase-sequence press + settle + pulls into a `BondDebondResult`
      (promoted 2026-07-15 from a slice-5 sub-note so it is not lost when
      slice 5 is ticked). `driver/press_pull.py` has the three §9 control
      loops as separate functions, but nothing yet drives them in order
      with a FRESH restore of the settled reference per pull rung and a
      persistent-engine lifecycle (`PSEUDOCODE.md` §9, `DESIGN.md` §5.4).
      This is real-adapter territory — the restore/lifecycle only exists
      against a live LAMMPS instance — so it lands with the compute-node
      adapter work below.
- [ ] Bonded-quality grading — `contact_quality` / cross-interface bonds
      / contact fraction (promoted 2026-07-15 from slice-3 and slice-5
      sub-notes). `driver/analysis.py` computes the geometric contact
      criteria but NOT the bonded-quality grade, which reuses the §8
      geometric machinery (bond cutoffs from partial g(r), the grid-based
      `contact_area_fraction`, `DESIGN.md` §6.4) that is not built yet.
      Ties to the §8 characterization build (Wave 4); tracked separately
      here so the grade is not forgotten inside the press/pull ledger.
- [ ] Apply the atom-count conservation gate in the pull (`/refine` #4).
      `PSEUDOCODE.md` §9.6 makes `atom_count_conserved` a GATE on the
      Trajectory — an atom escaping the open-z box voids the run (§5.6) —
      and `driver/analysis.py` has the function (tested), but
      `pull_at_rate` (`driver/press_pull.py`) never calls it and
      `PullResult` omits it. Read `engine.atom_count()` before/after the
      pull and carry the verdict. Ties to the real-adapter wiring, which
      is where a live before/after count exists.
- [x] Labeled-group ownership (`/refine` #3) — RESOLVED option C
      (2026-07-15). The DRIVER carves the four depth zones (a frozen base
      OR two grips, the thermostat border, the NVE interior) from the
      builder's per-wafer z-ranges at open time; the builder stays
      protocol-ignorant, recording only the zone GEOMETRY. The activated
      skin is the ONE exception — a MEASURED, irregular atom set
      (`PSEUDOCODE.md` §10.7), not a depth cut — so it travels as an
      explicit atom set from activation to the press. The code already
      carved by depth (`driver/commands.region_group_commands`), so this
      was a docs-catch-up: `LabeledGroups` (§3) now holds the z-ranges +
      `activated_skin`, §7.5 emits `record_zone_geometry`, §9.2 CARVES the
      zones, `DESIGN.md` §2.6/§2.7/§5.4/§6.2 were reworded, and the
      pipeline placeholder (`skeleton_stages._LABELED_GROUPS`) + the
      `BuiltPair` docs were aligned. NAMES: identity stays A/B (spec,
      atom tags, the §6 γ_A/γ_B math); the A = bottom / B = top assembly
      invariant is now stated loudly wherever the z-ranges or tags appear
      (decided 2026-07-15). 72 tests still green. Commit PENDING.
- [x] Widen the MeasureVector seam to carry VERDICTS (`/refine` #6). The
      `PSEUDOCODE.md` §4 seam is a five-field record — provenance,
      geometry, measures, verdicts, checks — but the code
      `MeasureVector` (`pipeline/measures.py`) carries only `measures`,
      so the press outcome is LOST: `run_analyzer`
      (`pipeline/skeleton_stages.py`) emits two measures and never reads
      `result.press`, dropping the `bonded` / `contact_quality` verdict
      the §4 analyzer is supposed to read once and surface. Add a
      `Verdicts` record (`bonded`, `contact_quality`), hang it on the
      vector, and have `run_analyzer` populate it from the
      `PressOutcome`. FIXED below in the same session.
- [x] Relation guards — DESCOPED (2026-07-14, was `/refine` #7).
      Comparison judgment — which systems to compare, which variables
      make a FAIR contrast, whether a difference is entailed or
      incidental — stays the USER's to make by hand. There are too many
      ways to modify a system, and not every modification degrades a
      comparison equally, for an automated confound-check to earn its
      rigidity; a strict guard would obstruct more than it protects.
      This rips nothing out: `DESIGN.md` §1.1 already keeps relations
      REPORT-ONLY, and `_evaluate_one_relation` (`pipeline/sequencer.py`)
      already computes and reports the ratio. The validator-computed
      `confounded` / `controls_disagree` flags (`spec/records.py`) stay
      as informational provenance a user MAY read. We deliberately do
      NOT build the caveat-surfacing / verdict-withholding machinery once
      planned here, so this effort never competes with core capability.

---

## ARCHIVE

<!-- Resolved items go here. Keep them for reference; use stable numbering
for cross-references. -->
