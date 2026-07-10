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
- [x] Run-specification knobs — RESOLVED for v1 (2026-07-07): the knob
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
      module boundaries — now located (2026-07-08): the "where" lives in
      the deployment / resource-class layer of `ARCHITECTURE.md` §4.1
      (per-job CPU/GPU class, nodes, walltime, env), externalized from
      code. Residual: settle the exact deployment-config shape at DESIGN
      time (`VISION.md` principle 1, `ARCHITECTURE.md` §2.3, §4.1).
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
      The configured object is a **study** (runs + relations), because
      §7.4's criterion is a ratio and a ratio belongs to a *pair* of
      runs; a run still stands alone and studies may be assembled after
      the fact. Knobs split into **five** groups by a sharp test — a
      numerical setting's effect must vanish under refinement, a
      protocol knob's effect *is* the physics — with ensemble (seeds)
      separate because a seed is sampled, not tuned, and deployment in
      its own document (§4.1). No hidden defaults: the loader rejects an
      incomplete spec; defaults exist only as a generator that emits a
      fully-populated file. Protocols are identified by a **content
      fingerprint**, not a version number (versioning is too linear;
      protocols branch). Lattice constants, the shared cell, bond
      cutoffs, subcell size and activated depth are **derived, never
      settings**. `ARCHITECTURE.md` §2.3's run-spec bullet amended in
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

---

## CODE

<!-- Tasks related to implementation. -->

---

## ARCHIVE

<!-- Resolved items go here. Keep them for reference; use stable numbering
for cross-references. -->
