# Pseudocode

> **Document hierarchy:** VISION → ARCHITECTURE → DESIGN → **PSEUDOCODE**
> → Code. For the design rationale behind these algorithms, see
> `DESIGN.md`; for the build strategy that sets this document's shape,
> see `ARCHITECTURE.md` §5.

> **PASS 1 — the walking skeleton (`ARCHITECTURE.md` §5.4).** This first
> pass writes **control flow and the seam schemas only** — the frozen
> contracts between steps and the thin thread that carries data through
> all of them. The deep per-module algorithms (the coincidence matcher,
> the amorphization cascade, the UDD bias, the snapshot detectors, the
> work integrals) are **deferred to depth-first passes**, written when
> each module is implemented behind its already-frozen contract. Every
> such deferral is marked `[DEPTH-FIRST]` below.
>
> The skeleton runs the **Si/Si walking-skeleton thread**
> (`ARCHITECTURE.md` §5.3, "Wave 0"):
> steps 1-2 skipped behind a classical potential stand-in, step 4
> stubbed, step 5 trivial (no lattice mismatch), step 8 mocked. Its
> headline number is deliberately **not trusted** — the point of the
> skeleton is that the data flows and the schemas hold.

---

<!-- Sections mirror the pass-1 list in ARCHITECTURE §5.4: the Tier-A
sequencer (§1), the member/study specification the sequencer loads (§2),
the structure AND trajectory contracts that cross the simulation steps
(§3), the measure-vector schema the analyzer emits (§4), and the
quality-gate precedence chain that reads it (§5). Section 6 assembles
them into the walking-skeleton configuration and shows where the
stand-ins sit.
Every record is CLOSED — no field references a type left undefined. -->

## 1. Tier-A sequencer — the top-level control flow

The sequencer owns the eight pipeline steps and the quality-gate loop
(`ARCHITECTURE.md` §4.1, Tier A). The configured object is a **study** —
**one or more** members plus **optional** relations among them
(`DESIGN.md` §1.1). A study may hold a single system or several, run
under different conditions, and a relation may compare them across
**any** of the registered measures, not one privileged number. So the
top entry point runs each member to a complete, self-standing report,
then grades whatever relations were declared — of which there may be
none. **A study of one member is fully valid:** it produces its report
and no internal comparison, and the human who runs it is free to compare
that report against anything else, outside the program.

```
function exec_full_study(study_specification, job_directory):
    # Entry point. A study is members + relations (DESIGN §1.1). Each
    # member is executed independently; the relations (e.g. the Si/SiO2-
    # to-Si/Si ratio) are graded only after every member has produced its
    # measure vector. job_directory is the run's home on the shared
    # filesystem (ARCHITECTURE §4.1); the stages' bulky intermediates go in
    # its scratch mirror, threaded EXPLICITLY from here so every written
    # byte stays traceable to its inputs (VISION goal 3).
    validated_study = load_and_validate_study(study_specification)

    member_results = empty_list
    for each member_specification in validated_study.members:
        # Each member owns a scratch subtree keyed by study + member
        # identity (the ARCHITECTURE §4.2 mirror); the file-writing stages
        # RECEIVE it, never rebuild it from identity themselves.
        member_scratch_dir = member_scratch(
            job_directory, validated_study.name,
            member_specification.name)
        member_results.append(
            exec_one_member(member_specification, member_scratch_dir))

    # Relations are an OPTIONAL comparison layer, graded at the study
    # level (there may be none). A relation compares a subset of the
    # members across one or more registered measures; v1's bond-outcome
    # ratio (DESIGN §7.4) is one such relation, not the only kind. With
    # no relations the study report is simply the per-member reports.
    study_report = evaluate_relations(validated_study.relations,
                                      member_results)

    emit_study(study_report, member_results)   # machine-readable output
    return study_report
```

```
function exec_one_member(member_specification, scratch_directory):
    # The eight-step pipeline for ONE member; its file-writing stages
    # (build_slabs first, §7.1) get scratch_directory threaded in
    # explicitly (ARCHITECTURE §4.3, VISION goal 3). In v1 the quality-gate
    # loop executes its body ONCE and reports (VISION principle 5); the
    # enclosing while-loop is the future automated target, shown so the
    # seam for it exists, but not iterated in v1.
    #
    # while not member_result.gate.passes:          # <- future closed loop
    #     training_data += data_targeting(member_result.gate.weaknesses)
    #
    # EVERY stage below is routed through run_to_contract (defined after
    # this function): run the stage, then HALT unless its output
    # satisfies the contract the next stage depends on. That is what
    # makes "the pipeline always runs" safe (ARCHITECTURE §5.1) — it runs
    # until a stage produces a contract-invalid artifact, then stops
    # loudly instead of corrupting everything downstream.

    # The potential is a CONTRACT, not a fixed implementation. The
    # walking skeleton satisfies it with a classical pair_style
    # stand-in; the bootstrap wave (steps 1-2) later satisfies it with
    # the trained MLIP through the SAME seam (ARCHITECTURE §5.1).
    #
    # WHAT LIVES BEHIND THIS SEAM (the /refine marker). resolve_potential
    # LOOKS UP a fingerprinted, already-manufactured potential (the
    # potential_ref of DESIGN §1.6); it does NOT train one inline. The
    # manufacturing is the bootstrap loop (§11, DESIGN §4.5), a SEPARATE
    # top-level process that runs UPSTREAM of every member. That placement
    # decides WHERE the potential-quality gate ACTS: the bootstrap's
    # convergence criterion (§11.6) IS the acting form of the §5 gate --
    # inside it the potential is still mutable, so a fail DRIVES the loop.
    # By the time a member reaches HERE the potential is FROZEN, so the
    # same gate can only REPORT (§5, evaluate_member_gates). The
    # production-side bulk/surface check reads as a reporter for THAT
    # reason, not by oversight -- DESIGN §7.2's "gate the build" is
    # discharged upstream, where acting is still possible.
    potential = run_to_contract(
        () -> resolve_potential(member_specification),   # skeleton:
                                                          # classical
        POTENTIAL_CONTRACT)

    # Steps 3-4-5 are three SEPARATE stages in a FIXED order:
    # build -> activate -> assemble. The order is not a setting and no
    # reorder engine is owed (ARCHITECTURE §2.1, §5.3, retracted
    # 2026-07-23) -- activating each surface alone in vacuum, before the
    # halves meet, is what surface-activated bonding IS. What the spec
    # does choose is whether activation runs AT ALL: with it off the
    # builder emits the crystalline pair in one piece (the Si/Si null
    # path) and the activate stage is skipped entirely.

    # Step 3 — build both slabs to the shared coincidence cell (§7). Each
    # is written to a data file under scratch_directory and returned as a
    # HALF-HANDLE (§7.1); build_slabs is the first stage to write files.
    (handle_A, handle_B, shared) = run_to_contract(
        () -> build_slabs(member_specification, potential,
                          scratch_directory),
        SLABS_CONTRACT)

    # Step 4 — activate (amorphize) each slab's surface. A SEPARATE
    # module (DESIGN §3) with its own pass/fail gate (§3.5); in the
    # skeleton it is stubbed. It does NOT assume it ran before assembly
    # (§5.3). Each call takes a HalfHandle, RE-READS the pristine half from
    # its data file, amorphizes it, and writes the amorphized half back
    # (§10.1). The stage returns ONE ActivatedSlabs (§10.1): both activated
    # slabs AND both gate verdicts. The contract checks verdict_A.passed
    # and verdict_B.passed, so a FAILED activation gate is contract-invalid
    # and halts HERE (§10.1) — the gate is enforced at this seam, not
    # buried in the module.
    activated = run_to_contract(
        () -> activate_surfaces(handle_A, handle_B, member_specification,
                                potential),
        ACTIVATED_SLABS_CONTRACT)
    slab_A = activated.slab_A   # rebind to the activated slabs; the
    slab_B = activated.slab_B   # verdicts rode the contract check above

    # Step 5 — assemble the facing pair from the activated slabs (§7).
    structure = run_to_contract(
        () -> assemble_pair(slab_A, slab_B, shared, member_specification),
        STRUCTURE_CONTRACT)

    # Steps 6-7: press then pull, on the MLIP (here, the stand-in). The
    # result is a BondDebondResult (§9.1): one press outcome + one
    # reference + a per-rate list of pulls, NOT a bare Trajectory (§5.4's
    # rate ladder). Named for what it is at this seam.
    bond_debond_trajectory = run_to_contract(
        () -> run_bond_debond_md(structure, potential, member_specification),
        BOND_DEBOND_CONTRACT)

    # The analyzer turns that result into a measure vector (DESIGN §6):
    # it reads the press outcome into the Verdicts and iterates the
    # per-rate pulls (§4). In the skeleton only the Imago-free mechanical
    # measure is real; the rest report `unresolved`.
    measures = run_to_contract(
        () -> run_analyzer(structure, bond_debond_trajectory,
                           member_specification),
        MEASURE_VECTOR_CONTRACT)

    # Step 8 characterization feeds additional measures. In the skeleton
    # this is MOCKED and returns schema-valid `unresolved` records.
    characterization = run_to_contract(
        () -> run_characterization(structure, bond_debond_trajectory,
                                   member_specification),
        MEASURE_VECTOR_CONTRACT)
    measures = merge_measures(measures, characterization)

    # The gate READS the measure vector and REPORTS; it never edits a
    # measure and, in v1, never acts (DESIGN §7). It is the terminal
    # reader, not a hand-off to a further stage, so it is not itself
    # wrapped; the member's OWN output (MemberResult) is the last
    # contract, checked at the member->study seam (§1's exec_full_study
    # and emit_member).
    gate_report = evaluate_member_gates(measures, member_specification,
                                     potential)

    member_result = record{
        specification: member_specification,
        potential:     provenance_of(potential),
        measures:      measures,
        gate:          gate_report,
    }
    emit_member(member_result)
    return member_result
```

The member's result is itself a contract — the seam between a member and
the study that may relate it to others (its `measures` and `gate` types
are defined in §4 and §5):

```
record MemberResult:
    specification: MemberSpecification   # what was asked for
    potential:     Provenance         # which potential generation ran
    measures:      MeasureVector      # everything the analyzer emitted
    gate:          GateReport         # the per-member diagnostic verdict
    trusted:       boolean            # default true; FALSE for a
                                      # walking-skeleton plumbing member
                                      # whose number is not
                                      # to be believed (ARCHITECTURE §5.3)
```

**Every stage is routed through one guard: `run_to_contract`.** The
sequencer never calls a stage and hopes. It runs the stage through a
guard that validates the stage's output against the contract the *next*
stage depends on, and **halts** the pipeline if that contract is not met
(`ARCHITECTURE.md` §4.1). Linking is by file contracts on the shared
filesystem, so a "hand-off" is "write a contract-valid artifact, then
read it," and `run_to_contract` is what stands over that write.

```
function run_to_contract(work, contract):
    # A GUARD placed at the seam between two stages — NOT a stage itself.
    # It runs the given work, then refuses to let the pipeline advance
    # unless the result satisfies `contract`, the shape the NEXT stage
    # depends on. This is where ARCHITECTURE §4.1's "launch, check the
    # output contract, then launch the next" is enforced, and where the
    # "gate, don't warn" rule lives: a contract-invalid artifact HALTS
    # the pipeline and is never passed downstream (the prior-art
    # NOTE_INCOMPLETE-quoted-as-a-result failure, DESIGN §5.7).
    #
    # WHY THIS NAME. It is not `run_step`, because it does NOT do a
    # step's work — `work` does. Naming it `run_step` would advertise the
    # one thing it delegates and hide the thing it exists for. Its job is
    # to hold that work's output TO its CONTRACT — and "the contract is
    # the unit of stability" is the load-bearing idea of ARCHITECTURE
    # §5.1, so the name is built on the vocabulary we already committed
    # to. It deliberately avoids "gate" (the §7 quality gate) and
    # "checkpoint" (the §5.5 git baseline), both already taken. Every
    # stage is routed THROUGH it, so the discipline reads uniformly:
    # run_to_contract(work_A, ...); run_to_contract(work_B, ...).
    #
    # `work` is a ZERO-ARGUMENT callable — the stage with its inputs
    # already supplied, written `() -> stage(args)` at the call sites, so
    # a stage of any arity fits one guard signature.
    artifact = work()
    validation = check_contract(artifact, contract)
    if not validation.ok:
        halt_pipeline(reason = validation.failure)   # halt, never warn
    return artifact
```

The contracts named at the call sites are exactly the seam schemas of
this document: `STRUCTURE_CONTRACT` and `BOND_DEBOND_CONTRACT` are §3,
`MEASURE_VECTOR_CONTRACT` is §4. The structure stage's intermediate
contracts are `SLABS_CONTRACT` (two valid `Slab`s plus their shared cell,
§7.1) and `ACTIVATED_SLABS_CONTRACT` (both slabs amorphized and past the
activation gate, `DESIGN.md` §3.5; its concrete form is §10.1's
`ActivatedSlabs`, which carries both slabs AND both gate verdicts).
`POTENTIAL_CONTRACT` is the one
exception — not a record of ours but the external potential's loadable
`pair_style` interface (its *quality* is judged separately by the §5
gate — as a REPORT here, and as the ACTING convergence check inside the
bootstrap, §11.6, that manufactured it; the guard here only checks it is
a usable potential the member looks up by fingerprint).

`[DEPTH-FIRST]` the bodies of the structure stages (`build_slabs` /
`assemble_pair`, now in §7), `activate_surfaces`, `run_bond_debond_md`,
`run_analyzer`, and `run_characterization` are the per-module algorithms;
pass 1 fixes only their signatures and the contracts they exchange
(§3, §4). `check_contract` and `halt_pipeline` are likewise
contract-level here: the actual schema-validation logic is a depth-first
concern.

## 2. The member/study specification and its validator

The specification is the contract between the human and the pipeline
(`DESIGN.md` §1). Pass 1 captures the fields the skeleton actually
touches; the full five-group knob inventory is filled as modules land.

```
record Study:
    members:   list of MemberSpecification    # ONE or more
    relations: list of Relation            # zero or more (optional)

record MemberSpecification:
    # Five knob groups (DESIGN §1.2), minus deployment, which lives in
    # a separate document the member spec cannot express (DESIGN §1.2).
    material:      MaterialKnobs   # per-wafer crystal + face + identity
    protocol:      ProtocolKnobs   # activation, press, separate settings
    numerical:     NumericalKnobs  # tolerances, cutoffs, strides, budgets
    ensemble:      EnsembleKnobs   # master seed + two realization counts
    potential_ref: string         # WHICH potential generation this member
                                  # uses — a content fingerprint, or the
                                  # classical stand-in marker in the
                                  # skeleton. The potential's CONTENTS are
                                  # not settings
                                  # (DESIGN §1.3); this POINTER is one,
                                  # for provenance (DESIGN §1.6, §6.6).

record MaterialKnobs:             # one per wafer; two wafers per member
    cif_source:        path        # AUTHORITATIVE crystal (a CIF):
                                   # symmetry/basis/connectivity, serves
                                   # ANY material (DESIGN §1.2)
    crystal_structure: string      # a human LABEL (e.g. "diamond"); the
                                   # CIF is authoritative, never this
    surface_face:      Miller indices
    identity:          string      # the material itself
    # NEVER a lattice constant — the CIF fixes symmetry/basis but its
    # SCALE is a starting geometry only; §2.2 derives the working lattice
    # from the potential (DESIGN §1.3).

record ProtocolKnobs:
    # Press + separation are exercised by the skeleton; the activation
    # fields are declared here and REFINED by §10 (activation's depth-
    # first pass), no longer a stub. What stays [DEPTH-FIRST] is only the
    # energy/angle DISTRIBUTIONS at code level — v1 freezes each field to a
    # single value (§10.3), but a real beam is neither monoenergetic nor
    # unidirectional (DESIGN §3.2).
    activation_mechanism: string  # WHICH activation method (DESIGN §3.1);
                                  # v1 registers only bombardment (§10.1)
    activation_species:   string  # projectile; argon by default (§1.2)
    activation_cospecies: string or none   # optional co-deposit (iron the
                                  # first accommodated), else none (§3.2)
    activation_cospecies_fraction: number  # co-deposit fraction, if used
    activation_energy:    number  # impact energy (single value in v1)
    activation_angle:     number  # angle of incidence (normal in v1)
    activation_fluence:   number  # ions per A^2, cell-size-independent
    cascade_duration:     number  # NVE cascade time per impact (~ps, §3.3)
    between_impact_relaxation: number  # border-thermostat settle between
                                  # impacts, so the next starts cool (§3.3)
    reanneal_schedule:    AnnealSchedule   # the MLIP re-anneal (§3.4,
                                  # §10.5): temperature, duration, ensemble.
                                  # A trapped glass bounds how far it goes
    initial_gap:        number    # slab separation at assembly (§2.6)
    press_control:      one of {load, displacement}   # DESIGN §5.2
    press_load:         number    # load or pressure reached
    press_depth:        number
    press_duration:     number    # the hold; where bonding happens (§5.2)
    press_temperature:  number    # thermostat setpoint for the hold (§5.2)
    press_approach_rate: number   # grip ramp/approach speed; bounded by
                                  # the no-impact guard (§9.3, DESIGN §5.2)
    separation_speed:   number    # single-rate special case; the real
                                  # pull uses numerical.pull_rate_ladder
                                  # (DESIGN §5.4)

record NumericalKnobs:
    # Filled as modules land (DESIGN §1.8). [DEPTH-FIRST] the full
    # tolerance / cutoff / stride / window / budget set.
    pull_rate_ladder: list of number  # >= 3 rates over a decade (§5.4)
    noise_floor:      number          # peak/curve threshold (§5.4)
    frame_stride:     integer         # store 1 frame per N MD steps
                                      # (e.g. 100-1000); NOT every step
    misfit_tolerance:       number    # coincidence-match strain cutoff
                                      # (§2.3; largest strain component)
    max_coincidence_area:   number    # atom-area budget for the match
                                      # (§7.6): bounds atoms per layer,
                                      # the lateral half of §8.2's total
                                      # step-8 atom envelope
    minimum_bulk_thickness: number    # undamaged substrate floor (§2.5)
    clash_floor:            number    # min cross-slab distance (§2.6)
    contact_grid_spacing:   number    # grid cell size for the bonded
                                      # contact-area fraction (§8.8,
                                      # DESIGN §6.4); ~one cutoff/cell
    contact_gap_threshold:  number    # dividing-surface gap that, with a
                                      # positive mean normal stress, marks
                                      # contact (§9.3, DESIGN §5.2)
    bonded_contact_threshold: number  # contact quality above which the
                                      # verdict is "bonded" (§9.3, §5.1)
    force_average_window:   number    # pull force-average window, in grip
                                      # DISPLACEMENT units (§9.5, §5.4)
    reference_pe_drift:     number    # max PE drift for the reference to
                                      # count as settled (§9.4, DESIGN §5.3)
    detector_smoothing_window: number  # smooths each §12.2 detector series
    detector_prominence:    number    # min event prominence vs §5.4 floor
    frame_budget:           integer   # max frames to step 8; §1.2 knob

record EnsembleKnobs:
    # TWO sampling axes, not one (V1_VALUES; DESIGN §6.6). The amorphized
    # skin and the thermal state are independent sources of run-to-run
    # spread, so each gets its own realization count; the §6.6 error bar
    # is taken over their product.
    master_seed:         integer  # one master seed; every per-realization
                                  # seed is derived from it (DESIGN §1.2)
    amorphization_count: integer  # independent cascade realizations, i.e.
                                  # how many amorphized skins to average
                                  # over (the dominant axis; v1 uses 3)
    velocity_count:      integer  # thermal-velocity reseeds PER amorph
                                  # realization (the second axis; v1 = 1)

record Relation:
    # A relation compares a subset of the study's members across one or
    # more MEASURES (by name, DESIGN §6.6) — not one privileged number.
    # It is optional; the walking skeleton declares none.
    kind:     one of {ratio, sweep, ...}   # v1's bond gate is `ratio`
    members:  list of member-ids              # which members it relates
    measures: list of measure-names        # which metrics it compares on
    contrast: list of field-paths          # what it deliberately varies
    controls: list of field-paths          # what it holds fixed
    # Attached by the validator (below) and read by evaluate_relations:
    difference_set:    DifferenceSet   # contrasted/entailed/incidental
    confounded:        boolean         # more than one contrast
    controls_disagree: boolean         # a declared control actually differs

record DifferenceSet:
    # Each field that differs between the members, classified (§1.1).
    contrasted: list of field-paths   # the signal
    entailed:   list of field-paths   # differs BECAUSE of the contrast
    incidental: list of field-paths   # nobody decided to vary it
```

```
function load_and_validate_study(study_specification):
    study = deserialize(study_specification)   # [DEPTH-FIRST] format

    for each member in study.members:
        # NO HIDDEN DEFAULTS: an incomplete specification is rejected,
        # not silently completed (DESIGN §1.4). Defaults exist only as a
        # separate generator that emits a fully-populated file to edit.
        reject_if_incomplete(member)

        # Validation rejects a spec that cannot be EXECUTED — a species
        # outside the potential's type map, a missing unit — never one
        # whose COMPARISONS would be hard to interpret (DESIGN §1.5).
        reject_if_not_executable(member)

    for each relation in study.relations:
        # REPORT, NEVER RESTRICT (DESIGN §1.1). A relation whose controls
        # disagree, or which is confounded by more than one contrast, is
        # still computed and still reported; only the gate's VERDICT is
        # withheld. So validation here computes the difference set and
        # flags confounds — it does not delete the relation.
        relation.difference_set = sort_differences(
            relation, study.members)          # contrasted/entailed/incidental
        relation.confounded = (count(relation.contrast) > 1)
        # A declared control that actually differs between members means
        # the comparison is not the controlled one the relation claims.
        relation.controls_disagree = any(
            control appears in relation.difference_set
            for control in relation.controls)

    return study
```

`[DEPTH-FIRST]` `deserialize` (the on-disk format), the exact protocol
**content fingerprint** (`DESIGN.md` §1.4), and `sort_differences`'
entailed-vs-incidental logic (`DESIGN.md` §1.1).

## 3. The structure and trajectory contracts (steps 3-7)

Two physical-state seams cross the simulation stages: the **structure**
(builder → amorphization → assembly → press/pull) and the **trajectory**
(the press/pull output → analyzer and characterization). Both are here
because both are shapes downstream stages depend on and nothing deeper,
which is what lets the stages be built and swapped independently.

One data structure carries the model from the builder through
amorphization, assembly, press, and pull (`DESIGN.md` §2.6).

```
record Structure:
    atoms:          list of Atom
    lateral_cell:   Cell        # the shared coincidence cell (DESIGN §2)
    substrate_strain: StrainTensor   # recorded provenance (DESIGN §2.4)
    labeled_groups: LabeledGroups
    # Cell (box vectors) and StrainTensor (a 3x3 tensor) are primitive
    # geometric value types, like `vector` and `number` — not stubs.

record Atom:
    # Species is what the POTENTIAL sees (one global type map, ONE
    # oxygen); provenance is bookkeeping the potential never sees. They
    # are SEPARATE fields — conflating them is the STRUCTURAL-1a error
    # (DESIGN §6.2). A bond is cross-interface iff its endpoints'
    # provenance labels differ.
    species:    element in the global type map
    provenance: which slab this atom was built in
    position:   vector

record LabeledGroups:
    # The structure's contribution to region definition (DESIGN §2.6).
    # Option C (labeled-group ownership, resolved 2026-07-15): the four
    # DEPTH zones — a frozen base OR two grips, the thermostat border, the
    # NVE interior — are NOT stored here as atom-index sets. The builder
    # records only the per-wafer z-RANGES below; each stage's DRIVER
    # carves the zones IT needs from them, by depth, at open time. This
    # keeps the builder ignorant of the MD protocol: the cascade wants a
    # frozen base, the press/pull wants two grips, and that stage-specific
    # choice does not belong to the geometry.
    wafer_a_z_range:   (low, high)    # bottom slab's z-extent
    wafer_b_z_range:   (low, high)    # top slab's z-extent
    interface_z:       scalar         # the dividing plane between slabs
    # The activated skin is the ONE exception: a MEASURED, irregular atom
    # set (§10.7 — the atoms the cascade actually amorphized), NOT a depth
    # cut. It cannot be re-carved from z-ranges, so it travels as an
    # atom-index set from activation to the press that tracks it (§9.3).
    activated_skin:    atom-index set
```

The builder ASSERTS commensurability rather than assuming it: both slabs
share `lateral_cell` by construction (`DESIGN.md` §2.6). For Si/Si in
the walking skeleton the coincidence match is the identity (no lattice
mismatch), so
the matcher is exercised for real only at the Si/SiO2 transition
(`ARCHITECTURE.md` §5.3, Wave 3).

`[DEPTH-FIRST → §7]` the coincidence matcher (Zur-McGill search,
`DESIGN.md` §2.3), the strain split (`DESIGN.md` §2.4), slab cutting and
termination selection (`DESIGN.md` §2.5), and the density-profile
dividing surface (`DESIGN.md` §2.6) — all written in §7, the structure
builder's depth-first pass.

**The trajectory contract (steps 6-7 → analyzer).** The press/pull hands
the analyzer a `Trajectory` (`DESIGN.md` §5.5). The reduced curves are
small and kept inline; the per-atom frames are large and kept **by
reference** on scratch (`ARCHITECTURE.md` §4.1, "large trajectory I/O").
**We never store every timestep.** Even the raw frame set is a *strided
subsample* — one stored configuration every, say, 100, 200, 500, or 1000
MD steps — so the number of stored frames is a small fraction of the
trajectory's total step count. That strided atomic-coordinate frame set
is
nonetheless a **first-class channel** of the contract, not an
afterthought the heavy measures happen to reach.

```
record Trajectory:
    identifier:           string   # explicit id; the analyzer never
                                  # guesses "newest file" (DESIGN §5.7)
    force_vs_grip:        Curve    # testing-machine force; the M1
                                  # integrand (DESIGN §5.5)
    force_vs_opening:     Curve    # force vs interface opening (§5.5)
    scalar_series:        map from name to list of number
                                  # per-frame PE, sigma_zz, ... (small)
    reference_state:      StateRef  # gated zero-load reference (§5.3);
                                  # the M1 integral's start
    separation_point:     curve-index or none   # into the reduced curves,
                                  # not a frame index (§9.6)
    complete:             boolean   # ran to the end (DESIGN §5.6) — GATE
    atom_count_conserved: boolean   # non-periodic box lost none — GATE
    grip_reaction:        pair of Curve   # BOTH grips -> Newton check
    provenance:           Provenance      # potential gen, seeds, rate
    frames:               FrameSetRef      # the full per-atom trajectory

record FrameSetRef:
    # A reference to the ACTUAL atomic-coordinate trajectory on shared
    # scratch — the coordinate ARCHIVE. Its consumers are the ones that
    # need atomic POSITIONS: §8/§12 characterization (Imago, RDF,
    # structural descriptors), the §8 snapshot selector, and human
    # inspection. The pull's OWN reduction never reads it (§9.6). It is
    # written only when such a consumer is in play, so the reference is
    # `none` for a bare bond-strength run. CONVERSELY, the frame-reading
    # §8 measures (§8.6, §8.8) presume the archive EXISTS; the §9.5
    # write-trigger is what guarantees it whenever such a measure is in
    # the run, so those measures never meet a `none`. The per-atom
    # CHANNELS are declared so a consumer knows what is present without
    # opening the (large) file.
    # We NEVER store every timestep — the frame set is a STRIDED
    # subsample, so frame_count is a small fraction of the step count.
    location:    path on scratch
    frame_count: integer   # << the MD step count (strided subsample)
    stride:      integer   # MD steps between stored frames, e.g.
                          # 100 / 200 / 500 / 1000 — never every step
    channels:    subset of {positions, velocities, per_atom_energy,
                            per_atom_virial}   # positions ALWAYS present

record Curve:
    x:     list of number     # e.g. grip displacement (A)
    y:     list of number     # e.g. force (eV/A)
    units: Units

record StateRef:
    location:         path on scratch   # one stored configuration
    potential_energy: number
```

The press/pull STAGE does not emit a bare `Trajectory`: because bonding
happens once but the pull repeats per rate (`DESIGN.md` §5.4), it emits a
`BondDebondResult` (§9.1) that wraps a press outcome, one reference state,
and a LIST of per-rate `Trajectory` records. `Trajectory` here is the
shape of ONE pull; the wrapper is the concrete form of this seam.

In the walking skeleton the analyzer needs only `force_vs_grip`,
`reference_state`,
`separation_point`, and the two gate flags (`complete`,
`atom_count_conserved`) — M1's inputs. `force_vs_opening`, the σ_zz
series, and `grip_reaction` are populated but read only by deeper
measures and checks. The **`frames` reference** is the coordinate
archive (§3): the MD stand-in can write the strided dump when recording
is turned on, so the by-reference seam is real and exercised — the
§8/§12 consumers and any human re-analysis inherit working plumbing
rather than a stub. It is written only when a coordinate consumer is in
play (§9.5), so a bare walking-skeleton run that asks for none leaves the
reference empty by design, not by omission.

`[DEPTH-FIRST]` the reduction that produces the curves and scalar series
from the live per-chunk SERIES, not from stored frames (`DESIGN.md`
§5.5; §9.6). The frame stride is a NUMERICAL knob
(`NumericalKnobs.frame_stride`, §2) — one stored configuration per N
steps, typically 100-1000, never every step — and `FrameSetRef.stride`
records the value a member actually used, for provenance.

## 4. The measure-vector schema (the analyzer's output)

The analyzer emits one machine-readable document per member; the gate
reads
it **by name and status, never by position** (`DESIGN.md` §6.6). A gate
cannot consume prose, so this schema is what makes §5 (the gate) possible
at all.

```
record MeasureVector:
    provenance: Provenance      # potential gen, seeds, press mode, codes
    geometry:   Geometry        # shared cell, interface area + its rule
    measures:   list of MeasureRecord
    verdicts:   Verdicts        # bonded / not-bonded, contact quality
    checks:     list of CheckResult   # §6.5 tests + Newton, atom count

record MeasureRecord:
    name:             string             # gate reads by THIS, not position
    value:            number or none
    uncertainty:      number             # NO BARE NUMBERS (DESIGN §6.6)
    realization_count: integer           # how many seeds it averaged
    units:            Units              # native AND SI + the conversion
    fidelity:         one of {geometric, electronic, MLIP, all-electron}
    method:           string             # e.g. "LAMMPS work-integral"
    inputs:           list of artifact-ids
    status:           one of {ok, unresolved, rejected}

record Units:
    native:     string        # e.g. "eV/A^2"
    si:         string        # e.g. "J/m^2"
    conversion: number        # 1 eV/A^2 = 16.0218 J/m^2 (DESIGN §6.6)

record Provenance:
    # Everything needed to reconstruct the number (DESIGN §6.6, goal 3).
    potential_generation: string   # the content fingerprint that ran
    committee_size:       integer
    seed_set:             list of integer
    press_mode:           string   # with the load / depth reached
    pull_rate:            number
    structure_id:         string
    trajectory_id:        string
    code_versions:        map from tool-name to version

record Geometry:
    lateral_cell:   Cell
    interface_area: number   # lx*ly, tilt-independent (DESIGN §6.6)
    area_rule:      string   # how the area was computed
    bond_cutoffs:   map from species-pair to number   # DERIVED (§6.3)

record Verdicts:
    bonded:          boolean  # the bonded / not-bonded outcome (§5.1)
    contact_quality: number   # graded, continuous (DESIGN §5.1)

record CheckResult:
    name:   string   # e.g. "newton_residual", "complete", "atom_count"
    passed: boolean
    detail: string   # what was measured against what tolerance
```

```
function run_analyzer(structure, bond_debond_trajectory,
                      member_specification):
    # The analyzer is a REGISTRY of measures (DESIGN §6.7). Each measure
    # declares what it needs; the analyzer resolves those needs against
    # what the member produced, computes what it can, and marks the rest
    # `unresolved`. Adding a measure is registering one, not editing the
    # gate.
    #
    # The input is a BondDebondResult (§9.1): one press outcome + one
    # reference + a LIST of per-rate pulls. Two things follow. (1) The
    # press outcome IS the Verdicts (bonded / contact quality, §5.1) —
    # read once, not through a measure. (2) A `per_rate` measure (M1 and
    # the geometric series, §8.4/§8.8) is computed ONCE PER PULL, on that
    # pull's single `Trajectory`, and each record carries its rate in
    # provenance so §8.9's rate-ladder check can compare across them; a
    # non-`per_rate` measure (M2, M3, M4, the electronic M5) reads the
    # whole result and picks the pull(s) it needs itself.
    verdicts = verdicts_from_press(bond_debond_trajectory.press)
    pulls    = bond_debond_trajectory.pulls

    measures = empty_list
    for each measure in registered_measures():
        if not measure.inputs_available(structure, bond_debond_trajectory):
            measures.append(measure.as_unresolved())
        else if measure.per_rate:
            for each pull in pulls:            # one record per rate
                measures.append(measure.compute(structure, pull))
        else:
            measures.append(
                measure.compute(structure, bond_debond_trajectory))
    return MeasureVector{ measures: measures, verdicts: verdicts, ... }
```

In the walking skeleton only **M1**, the mechanical work-integral, is a
real computed
record (it needs no all-electron code, `DESIGN.md` §6.4); M2-M5 register
but return `unresolved`, and the pipeline still runs — the first-class
Imago-free path (`DESIGN.md` §6.7).

`[DEPTH-FIRST]` every measure's `compute` (the work integrals, the
constrained ladder, the derived cutoffs, the descriptors) and the check
math of `DESIGN.md` §6.5.

## 5. The quality gates and the precedence chain

Two gates, kept apart because they lead to different remedies, and read
in a fixed order because each is interpretable only given the ones before
it (`DESIGN.md` §7.1). In v1 the gate is a **reporter**: it evaluates and
reports, and does not act (`DESIGN.md` §7, VISION principle 5).

```
record PotentialQualityVerdict:
    # THE potential-quality gate's output (DESIGN §7.2-§7.3), returned as
    # ONE object so its two consumers share it (see below). bulk_surface
    # and interface are the depth-first outputs of the two check_*
    # functions; each carries at least `.passes`.
    bulk_surface: CheckResult   # §7.2 bulk/surface half (folds in §3.5)
    interface:    CheckResult   # §7.3 interface-fidelity (STRUCTURAL 3)
    passes:       boolean       # both halves pass

function potential_quality_gate(potential, measures):
    # THE potential-quality gate, as ONE named unit (DESIGN §7.2-§7.3), so
    # its two callers invoke the SAME object and only DIFFER in what they
    # do with it: evaluate_member_gates (below) READS the verdict into the
    # five-way diagnosis; the bootstrap's convergence check (§11.6) ACTS on
    # `.passes` to drive its loop. Identical gate, opposite consequence --
    # exactly the §1 marker's "acts upstream, reports downstream."
    bulk_surface = check_bulk_surface(potential, measures)   # §7.2 half
    interface    = check_interface_fidelity(measures)   # §7.3, STRUCTURAL 3
    return PotentialQualityVerdict{
        bulk_surface: bulk_surface, interface: interface,
        passes: (bulk_surface.passes and interface.passes) }

function evaluate_member_gates(measures, member_specification, potential):
    # The potential-quality gate is READ here, not acted on -- v1's gate
    # reports (DESIGN §7, VISION principle 5). A failure is a POTENTIAL
    # problem -> the remedy is more training data.
    quality = potential_quality_gate(potential, measures)   # DESIGN §7.2-3

    # The five-way diagnosis routes the CAUSE of a questionable bond
    # number using those per-member signals (DESIGN §7.6). The bond-outcome
    # RATIO itself is a relation, graded at the study level (§1); a
    # single member has no ratio to grade.
    return diagnose(measures, quality.bulk_surface, quality.interface)
```

```
function diagnose(measures, bulk_surface, interface):
    # The five-way precedence chain (DESIGN §7.6). Order matters: a bad
    # bond number is meaningless until the potential gate has been read.
    if any_required_check_unresolved(measures, bulk_surface, interface):
        cause = undiagnosed        # a test that did not run is not a pass
    else if measurement_invalid(measures):
        cause = void               # truncated traj, lost atoms, failed
                                   # check, uncertainty abort — NEVER
                                   # diagnosed (DESIGN §7.6)
    else if not bulk_surface.passes:
        cause = bulk_model         # add training data
    else if not interface.passes:
        cause = interface_coverage # add INTERFACE training data
    else:
        cause = protocol           # more data will not fix it

    # `protocol` is reached BY ELIMINATION, sound only if the protocol
    # checks are exhaustive — which is not yet argued (DESIGN §7.7). So
    # report the cause AND, separately, the basis it was reached on.
    basis = direct_evidence if a_named_protocol_check_fired(measures)
            else by_elimination

    return GateReport{ cause: cause, basis: basis,
                       fired: fired_checks(measures) }
```

The gate's output is the diagnostic-label schema of `DESIGN.md` §7.8:

```
record GateReport:
    cause: one of {undiagnosed, void, bulk_model,
                   interface_coverage, protocol}    # DESIGN §7.6
    basis: one of {direct_evidence, by_elimination}  # DESIGN §7.7
    fired: list of check-names   # which protocol checks actually fired
    # In v1 this is REPORTED, never acted on (DESIGN §7; VISION prin. 5).
```

```
function evaluate_relations(relations, member_results):
    # Study-level grading of the OPTIONAL comparison layer. With no
    # relations this returns nothing, and the study report is simply the
    # per-member reports. A relation grades its members across its declared
    # measures; v1's bond-outcome `ratio` (DESIGN §7.4) is one kind — the
    # Si/SiO2-to-Si/Si work-of-separation ratio against the experimental
    # ratio within combined (correlated) uncertainty, plus a loose
    # absolute bracket that tests plumbing, not physics.
    reports = empty_list
    for each relation in relations:
        if relation.confounded or relation.controls_disagree:
            # REPORT, NEVER RESTRICT: still reported, verdict withheld
            # (DESIGN §1.1). `unresolved` means "this gate is not
            # competent to grade this comparison," never "no number."
            reports.append(relation.as_unresolved_with_differences())
        else:
            reports.append(grade_relation(relation, member_results))
    return reports
```

In the walking skeleton the study holds a single Si/Si member and
declares **no**
relations, so there is nothing to grade and the study report is simply
that member's report — a study of one is fully valid (`DESIGN.md` §1.1).
The bond-outcome ratio first becomes gradable at the Si/SiO2 transition,
when a second member exists to relate; and even then, comparison remains
an optional layer the human may also perform outside the program.

`[DEPTH-FIRST]` `check_bulk_surface`, `check_interface_fidelity` (the
committee-uncertainty and all-electron cross-check math, `DESIGN.md`
§7.3), and `grade_relation` — dispatched by `kind`, of which the `ratio`
case carries the correlated-uncertainty propagation of `DESIGN.md` §7.4.

## 6. The walking-skeleton configuration

This is **not a separate function.** It is `exec_one_member` (§1) in the
**walking-skeleton build phase** (`ARCHITECTURE.md` §5.3 calls it Wave 0),
showing what each stage RESOLVES to when the cheapest contract-satisfying
stand-in sits behind its contract. Same code path — the stand-ins are
injected, not branched to. Nothing below is trusted for physics; it
exists so every seam is exercised under real data flow.

```
# exec_one_member, each stage resolved to its walking-skeleton stand-in:
    potential  = classical_pair_style(...)      # steps 1-2 SKIPPED
    (handle_A, handle_B, shared) = build_slabs(...)  # step 3, real
    activated  = stub_activate(handle_A, handle_B)   # step 4, STUB:
    slab_A     = activated.slab_A               # returns an ActivatedSlabs
    slab_B     = activated.slab_B               # (§10.1), verdicts PASS
    structure  = assemble_pair(slab_A, slab_B,   # step 5, trivial (Si/Si)
                               shared)
    bond_debond_trajectory = press_then_pull(structure)   # steps 6-7,
                                                          # real
    measures   = run_analyzer(structure,               # M1 real, the
                              bond_debond_trajectory)   # rest unresolved
    measures   = merge mock_characterization()  # step 8, MOCK
    gate       = evaluate_member_gates(measures)
    # -> the resulting MemberResult.trusted is FALSE (a plumbing member)
```

**What each stand-in must still honour:** `stub_activate` returns an
`ActivatedSlabs` (§10.1) whose two slabs are valid but amorphization-free
and whose two gate verdicts trivially PASS — it satisfies the same
contract the real activation does, so §1's unpack and gate check are
exercised, not special-cased; `mock_characterization` returns
schema-valid `unresolved` MeasureRecords (§4); `classical_pair_style`
satisfies the same potential contract the trained MLIP will; and
`press_then_pull` writes the strided atomic-coordinate dump so
`Trajectory.frames` (§3) is populated even though no walking-skeleton
measure reads it — the by-reference seam is exercised, not stubbed. The
moment a stand-in's output stops satisfying its contract, the pipeline
stops — which is the signal the contract, not the module, needs
attention (`ARCHITECTURE.md` §5.1).

`[DEPTH-FIRST]` `build_slabs`, `assemble_pair`, and `press_then_pull` are
real even in the walking skeleton, but their algorithm bodies are written
in the structure (§7) and MD (later) depth-first passes; here they are
contract signatures only.

---

## 7. Structure builder — algorithms (steps 3, 5)

This is the **first depth-first module pass** (`ARCHITECTURE.md` §5.4).
It refines the `[DEPTH-FIRST]` structure bodies of §3 to code-readiness,
including the coincidence-matcher search, which took one further sub-pass
of its own (§7.6). Depth here is uneven by design: the strain split
bottomed out in a single formula, the matcher needed a sub-pass more.

**The builder is not one call.** Pass 1's sequencer wrote
`run_structure_stage(...)` as a single stage; decomposing it shows why
that was too coarse. The facing PAIR is the primary object and the shared
lateral cell is an invariant of the pair (`DESIGN.md` §2.1), so the cell
must be solved BEFORE any slab is cut — no per-slab step can precede it.
And activation (step 4) is a SEPARATE module (`DESIGN.md` §3) that runs
BETWEEN slab-building (step 3) and assembly (step 5). So the builder
exposes entry points the sequencer calls in order, with activation
injected between the second and third:

  solve_shared_cell  ->  build_slab (x2)  --[activate]-->  assemble_pair

`[RESOLVED → §1]` pass-1's `exec_one_member` collapsed steps 3-4-5 into
one `run_structure_stage` call, hiding activation. §1 now calls the three
stages explicitly — `build_slabs` -> `activate_surfaces` (the separate
activation module, `DESIGN.md` §3) -> `assemble_pair` — matching the
honest form the walking-skeleton configuration (§6) already showed.
Applied at the
programmer's direction; `run_structure_stage` is retired.

### 7.1 The module's top-level shape

```
function build_slabs(member_specification, potential, scratch_directory):
    # Steps up to and including step 3, for BOTH wafers. Stops before
    # activation, which the sequencer runs next. The two results are
    # STANDALONE half-cells, each in its OWN vacuum box (build_slab adds
    # the vacuum, §7.4) — NOT the assembled pair. Each is WRITTEN to a data
    # file under scratch_directory and returned as a HALF-HANDLE the
    # activation stage loads on its own engine (ARCHITECTURE §4.3).
    # build_slabs is the FIRST stage to write real files, so the sequencer
    # threads it the run's scratch directory EXPLICITLY (traceable, never
    # rebuilt from identity — VISION goal 3). assemble_pair (§7.5) reads
    # the two AMORPHIZED halves back only after activation. Building the
    # pair crystalline in one step is the activation-OFF null path (Si/Si,
    # no cascade).
    material_A, material_B = member_specification.material   # two wafers
    numerical              = member_specification.numerical

    # The shared cell is solved ONCE, on the two SUBSTRATE lattices, and
    # is an invariant of the pair (DESIGN §2.1, §2.3). It reads two
    # numerical knobs: the misfit tolerance and the atom-area budget.
    shared = solve_shared_cell(material_A, material_B, potential,
                               numerical.misfit_tolerance,
                               numerical.max_coincidence_area)

    # Split the small residual misfit between the slabs (DESIGN §2.4).
    strain_A, strain_B = split_strain(shared, material_A, material_B,
                                      potential)

    # Each half DECLARES the beam species (the activation projectile plus
    # any co-deposit) in its type map though it contains none yet: the
    # cascade CREATES those atoms, and the simulator can only make an atom
    # of a type its data file already declared (§10.3). Wafer A is built as
    # the bottom half, B as the top — the assembly invariant (DESIGN §2.6).
    beam = projectile_species(member_specification)          # §10.3
    # write_standalone_half writes the data file and stamps the HANDLE:
    # WHICH wafer a half plays (bottom A / top B) is an assembly-ROLE fact,
    # not a geometry fact, so it lives on the handle, not on the slab —
    # build_standalone_half stays wafer-agnostic.
    handle_A = write_standalone_half(
        build_standalone_half(material_A, shared, strain_A, beam,
                              potential, member_specification),
        WAFER_A, scratch_directory)
    handle_B = write_standalone_half(
        build_standalone_half(material_B, shared, strain_B, beam,
                              potential, member_specification),
        WAFER_B, scratch_directory)
    return (handle_A, handle_B, shared)
```

```
record SharedCell:
    lateral_cell:    Cell                 # the shared coincidence cell
    tiling_A:        2x2 integer matrix    # whole-number tiles of A
    tiling_B:        2x2 integer matrix    # whole-number tiles of B
    twist:           angle                 # relative in-plane rotation
    residual_strain: StrainTensor          # misfit left after the match

record HalfHandle:
    # What build_slabs hands the activation stage for ONE half: everything
    # needed to amorphize it, and NOTHING about the other half, so each is
    # a self-contained fan-out unit (the # C-EXPANSION unit, §4.3). The
    # activation stage RE-READS the slab geometry from data_file, never a
    # warm in-memory object, so the unit is restartable after a crash and
    # identical whether it runs in the member's own job or a separate one.
    #
    # [SERIAL I/O] Under MPI the write above happens on ONE rank, then a
    # barrier, and each reader below re-reads the file for ITSELF. Every
    # library file call is pinned to serial mode so the library cannot
    # turn a read into a collective behind the guard (DESIGN §2.6,
    # ARCHITECTURE §4.1 second discipline).
    data_file: path       # the pristine standalone half on disk
    type_map:  map        # species -> type id, WITH the beam declared
    identity:  string     # the material (report + reference lookup)
    wafer:     tag        # WAFER_A (bottom) or WAFER_B (top)
```

A `Slab` is just a `Structure` (§3) for one material — one provenance
label, and `grips` not yet set (assembly sets them, §7.5). Across the
build→amorphize seam a half travels as a `HalfHandle` — its file plus the
few facts the cascade needs — never as a live object (`ARCHITECTURE.md`
§4.3 file handoff).

### 7.2 solve_shared_cell — lattices from the potential, then the match

```
function solve_shared_cell(material_A, material_B, potential,
                           misfit_tolerance, max_coincidence_area):
    # Lattices come from the POTENTIAL, not literature (DESIGN §2.2):
    # load each crystal from its CIF (material.cif_source — symmetry and
    # basis, DESIGN §1.2) and relax the bulk under the current model,
    # referenced to VASP. At the COLD START the current model is the
    # classical/seed model, not yet a trained committee (DESIGN §2.2);
    # the relaxation itself is a driver minimization (§9.7). The
    # relaxed-vs-VASP disagreement is itself a potential-quality measure
    # (DESIGN §2.2, §7-of-DESIGN) — recorded, not discarded.
    lattice_A = relaxed_lattice(material_A, potential)   # vs VASP
    lattice_B = relaxed_lattice(material_B, potential)

    # The coincidence match: a Zur-McGill search over whole-number
    # tilings of BOTH surface vectors, scoring misfit as a strain TENSOR
    # within the tolerance (DESIGN §2.3). Its algorithm is written in
    # §7.6, adopting pymatgen rather than re-deriving the search.
    return coincidence_match(lattice_A, lattice_B, misfit_tolerance,
                             max_coincidence_area)
```

### 7.3 split_strain — a weighted formula (this one bottoms out)

```
function split_strain(shared, material_A, material_B, potential):
    # Distribute the residual misfit between the slabs weighted by each
    # slab's biaxial STIFFNESS times its THICKNESS (DESIGN §2.4): a
    # stiffer or thicker slab resists straining, so it takes LESS. An
    # even split is the equal-weight special case; "one slab takes all"
    # is the thickness -> infinity limit.
    weight_A = biaxial_stiffness(material_A, potential) *
               thickness(material_A)
    weight_B = biaxial_stiffness(material_B, potential) *
               thickness(material_B)
    fraction_A = weight_B / (weight_A + weight_B)   # stiffer A -> less
    fraction_B = weight_A / (weight_A + weight_B)
    strain_A = fraction_A * shared.residual_strain  # scale the tensor
    strain_B = fraction_B * shared.residual_strain
    return (strain_A, strain_B)
```

No `[DEPTH-FIRST]` marker: this is code-ready. It is the concrete case of
"depth is uneven" (`ARCHITECTURE.md` §5.4) — one level from the skeleton
to done, where the matcher (§7.6) needs two.

### 7.4 build_slab — cut, tile, thickness, termination, polar hook

```
function build_slab(material, shared, applied_strain, potential,
                    member_specification):
    # Step 3 for one wafer. Adopted ASE machinery cleaves and tiles;
    # three decisions sit on top (DESIGN §2.5).
    # The crystal comes from material.cif_source (a CIF — DESIGN §1.2):
    # relaxed_bulk loads it, then relaxes to the model's own lattice.
    bulk = relaxed_bulk(material, potential)             # DESIGN §2.2

    # Cleave along the requested Miller face, tile to the shared cell,
    # add vacuum, and apply the recorded substrate strain (provenance).
    slab = cleave_and_tile(bulk, material.surface_face, shared,
                           applied_strain)

    # Thickness is a CRITERION, not a constant (DESIGN §2.5):
    #   slab_thickness >= activated_depth + minimum_bulk_thickness
    # activated_depth is measured by the activation gate (DESIGN §3.5);
    # v1 fixes thickness by a short convergence study and records the
    # margin achieved.
    ensure_thickness(slab, activated_depth_of(material),
        member_specification.numerical.minimum_bulk_thickness)

    # Where a face admits several terminations, ENUMERATE and select by
    # computed surface energy (DESIGN §2.5) — which the potential-quality
    # gate needs anyway. NOT "first candidate in list order" (prior art).
    slab = select_termination_by_surface_energy(slab, potential)

    # Polar-slab symmetrizer: a HOOK and a GATE (DESIGN §2.5). v1 faces
    # are non-polar, so it is a documented hook; when switched on, an
    # uncancelled macroscopic dipole is a HARD failure (a short-range
    # MLIP cannot represent it), and any strategy that removes atoms must
    # report what it removed and re-run charge neutrality here.
    slab = symmetrize_if_polar(slab)

    return slab      # a Structure (§3): one provenance, grips unset
```

### 7.5 assemble_pair — dividing surface, ejecta, clash, labeled groups

```
function assemble_pair(slab_A, slab_B, shared, member_specification):
    # Step 5, the BARRIER stage: the first to see BOTH halves. In the real
    # pipeline each half is AMORPHIZED by now, read back from the data file
    # its activation stage wrote (ARCHITECTURE §4.3) — assembly receives
    # two read-back states, not live crystalline slabs. Both already share
    # `shared.lateral_cell` by construction, so ASSERT commensurability,
    # never assume it (DESIGN §2.6) — prior art adopted one slab's box and
    # ignored the other's.
    assert slab_A.lateral_cell == slab_B.lateral_cell

    # FLIP the top half in z so its ACTIVATED face meets the interface.
    # Both halves were bombarded on their +z top (the open cascade box,
    # §10.4): stacked as built, A's activated face points UP toward the
    # interface, but B's would point up and AWAY, facing its pristine back
    # to the bond plane. Mirroring B turns its activated face down (DESIGN
    # §2.6). Skipping this bonds an activated face to an unactivated one —
    # a silent error that passes every downstream gate.
    slab_B = flip_in_z(slab_B)

    # The surface plane is where the number-density profile falls to half
    # its interior value — NOT the highest atom, which a single asperity
    # or adatom would set (DESIGN §2.6).
    surface_A = density_dividing_surface(slab_A)
    surface_B = density_dividing_surface(slab_B)

    # Remove sputtered ejecta by BONDED-CLUSTER connectivity: an atom not
    # in the slab's largest connected cluster is not in the slab
    # (DESIGN §2.6). NOT "cut at the first 4 A z-gap" (prior art).
    slab_A = drop_disconnected(slab_A)
    slab_B = drop_disconnected(slab_B)

    # Place B facing A at the configured initial gap, measured between the
    # two dividing surfaces. Then check the minimum cross-slab distance;
    # if it violates the clash floor, back the gap off and RECORD the
    # adjustment rather than aborting the member (DESIGN §2.6).
    pair = place_facing(slab_A, slab_B, surface_A, surface_B,
                        member_specification.protocol.initial_gap)
    pair = relieve_clash(pair,
                        member_specification.numerical.clash_floor)

    # NO registry search: an amorphous-amorphous contact has no registry
    # (STRUCTURAL 4, DESIGN §2.6). The lateral offset survives only as an
    # ensemble realization variable, never a tuned knob.

    # Record the labeled-group GEOMETRY (§3), NOT four atom-index sets:
    # the per-wafer z-ranges and the interface plane the driver carves its
    # depth zones from (option C, §2.6). The measured activated_skin is
    # already attached by activation (§10.7) and is carried through here.
    pair.labeled_groups = record_zone_geometry(pair)
    return pair      # a Structure (§3): the facing pair, z-ranges SET
```

### 7.6 coincidence_match — the Zur-McGill search (we adopt pymatgen)

`[RESOLVED · was one level deeper]` This is the sub-pass §7.2 deferred,
now brought to code-readiness. Depth here is TWO where §7.3 was one
(`ARCHITECTURE.md` §5.4): the strain split bottomed out in a formula,
but the match needs its own algorithm. The algorithm itself we do NOT
write — we ADOPT pymatgen's Zur-McGill enumerator (`DESIGN.md` §2.3,
`VISION.md` principle 2). What SABSIM writes AROUND it is the four
things prior art got wrong or skipped (`PRIOR_ART.md` §1.6): scoring the
misfit as a strain TENSOR, the single physical tolerance, the atom-area
budget, and treating "no admissible cell" as a reported outcome.

```
function coincidence_match(lattice_A, lattice_B, misfit_tolerance,
                           max_coincidence_area):
    # The two in-plane surface vectors of each relaxed lattice (§7.2
    # supplied the lattices; the requested Miller face fixes the plane).
    surface_A = surface_vectors(lattice_A)      # a_1, a_2 in the plane
    surface_B = surface_vectors(lattice_B)      # b_1, b_2 in the plane

    # Adopt pymatgen's enumerator. Its length/angle tolerances are only
    # a PREFILTER — the authoritative cut below is on our own strain
    # tensor — so mapping the one physical knob onto both is safe: a
    # diagonal strain IS a length change, an off-diagonal shear IS an
    # angle change. Its area cap is the atom-area budget (below).
    enumerator = zsl_generator(
        max_length_tol = misfit_tolerance,      # fractional length
        max_angle_tol  = misfit_tolerance,      # small-angle shear
        max_area       = max_coincidence_area)

    admissible = empty list
    # Iterate EVERY match: pass pymatgen's `lowest = false`. Its `lowest`
    # would pre-collapse to the smallest-AREA match, but our selection
    # applies the strain-tensor tolerance cut FIRST and only then takes
    # the smallest cell (below) — so we must see the whole stream, not
    # pymatgen's area-only winner.
    for each match in enumerator(surface_A, surface_B, lowest = false):
        # A match carries whole-number 2x2 tilings for BOTH surfaces and
        # the two aligned supercell vector sets. The clean names below
        # map onto pymatgen's ZSLMatch fields (A = film, B = substrate,
        # the call order above):
        #   supercell_A  <-  match.film_sl_vectors
        #   supercell_B  <-  match.substrate_sl_vectors
        #   tiling_A     <-  match.film_transformation
        #   tiling_B     <-  match.substrate_transformation
        # `alignment_twist` is DERIVED, not a field: the rotation that
        # carries B's supercell onto A's (§7.6.1).
        strain = misfit_strain_tensor(match.supercell_A,
                                      match.supercell_B)   # 2x2, shear
        # The AUTHORITATIVE tolerance cut is the largest strain
        # COMPONENT — not a scalar length ratio, which cannot even see
        # the shear (DESIGN §2.3; prior art's two-number error, §1.6).
        if max_component(strain) <= misfit_tolerance:
            admissible.append(SharedCell(
                lateral_cell    = match.supercell_A,
                tiling_A        = match.tiling_A,
                tiling_B        = match.tiling_B,
                twist           = alignment_twist(match),   # §7.6.1
                residual_strain = strain))

    if admissible is empty:
        # A FIRST-CLASS reported outcome, never a crash: within this
        # tolerance and this area budget the two lattices share no cell.
        # The member's structure measures go `unresolved` with this
        # reason — the very envelope §8.2 prices step 8 against
        # (DESIGN §2.3, §8.2). Loosening either knob is the human's
        # call, never a silent widening (DESIGN §1.4).
        return no_admissible_cell(surface_A, surface_B,
                                  misfit_tolerance, max_coincidence_area)

    # Among the survivors take the SMALLEST cell (fewest atoms per
    # layer); break ties by least misfit (DESIGN §2.3). No stiffness is
    # needed here — the stiffness-weighted split is the SEPARATE §7.3.
    return smallest_then_least_misfit(admissible)
```

```
function misfit_strain_tensor(supercell_A, supercell_B):
    # Each supercell is a 2x2 matrix whose rows are its two in-plane
    # vectors. The deformation carrying B's supercell onto A's is
    # F = supercell_A * inverse(supercell_B); the misfit strain is
    # F - I (DESIGN §2.3). The OFF-DIAGONAL entries are shear and are
    # KEPT — discarding them is precisely prior art's diagonal rescale,
    # which cannot match two surfaces whose cell angles differ.
    deformation = matrix_multiply(supercell_A, inverse(supercell_B))
    return deformation - identity_2x2
```

**7.6.1 A note on the twist (`DESIGN.md` §2.3).** The adopted enumerator
takes no twist grid: it searches whole-number tilings at the lattices'
GIVEN orientations, and the rigid rotation that aligns each matched pair
IS that candidate's twist — read out by `alignment_twist`, not imposed.
For v1's goal (the smallest cell for a nominally untwisted Si/SiO2 bond)
this discovered rotation is sufficient. An EXPLICIT grid becomes the
mechanism only when twist is promoted to a CONTROLLED physical knob (a
future study dimension), where it would wrap the enumerator in an outer
loop over grid angles. `DESIGN.md` §2.3 now carries this reconciliation
directly — its earlier "over a grid" wording was updated to the
discovered-twist reading.

**7.6.2 The Si/Si null test.** For identical lattices the identity
tiling matches exactly at zero strain and is trivially the smallest
zero-strain cell, so the search returns identity tiling, zero twist,
zero strain (`DESIGN.md` §2.3). The walking-skeleton Si/Si member (§6)
is therefore ALSO the matcher's null test — a real exercise of this code
path whose correct answer is the trivial one. Prior art's continued-
fraction reasoning is the ONE-DIMENSIONAL shadow of this search
(`DESIGN.md` §2.3) and is not wrong; the adopted enumerator subsumes it,
so SABSIM seeds no candidates by hand.

### 7.7 Routines that bottom out at this level

`[DEPTH-FIRST · one level]` the small routines that are each one step
from code and need no sub-decomposition: `relaxed_lattice` /
`relaxed_bulk` / `biaxial_stiffness` (bulk relaxations under the
potential, `DESIGN.md` §2.2); `cleave_and_tile` and `ensure_thickness`'s
convergence study (`DESIGN.md` §2.5); `select_termination_by_surface_
energy`; `symmetrize_if_polar`'s four-strategy ladder (a future hook,
`DESIGN.md` §2.5); `flip_in_z` (mirror the top half so its activated face
meets the interface, `DESIGN.md` §2.6); and `density_dividing_surface`,
`drop_disconnected`, `relieve_clash`, `record_zone_geometry` (the
z-ranges the driver carves zones from — option C, `DESIGN.md` §2.6).

---

## 8. Bond-outcome analyzer — algorithms (the measures and checks)

This is the **second depth-first module pass** (`ARCHITECTURE.md` §5.4).
It refines the `[DEPTH-FIRST]` measure bodies of §4 and the check math of
`DESIGN.md` §6.5 to code-readiness. Depth is uneven again, but along a new
axis: several measures bottom out entirely in the analyzer (the M1 work
integral, the derived cutoffs, the bond graph, the geometric descriptors,
every check), while others are code-ready in the analyzer's OWN part —
forming a difference, splitting into pieces — yet DELEGATE a step to a
module not written yet. Two such modules exist: a MINIMIZER/anneal step
shared with the MD pass (§5-of-DESIGN), and the CHARACTERIZATION module
(§8-of-DESIGN) that returns all-electron values and electronic
descriptors. The analyzer never performs those; it consumes their
results. §8.10 lists every delegation in one place.

The organizing idea is `DESIGN.md` §6.1: the outcome is a VECTOR whose
entries are meant to DISAGREE, and the gaps are observables. So the
measures are written to make the gaps computable (§8.9's checks), never
to reconcile them.

### 8.1 The registry, made concrete

§4 gave `run_analyzer` as a registry loop. The depth-first refinement is
only to name the registered measures and what each declares it needs, so
the resolve-what-you-can behaviour (`DESIGN.md` §6.7) is concrete:

```
function registered_measures():
    # Each entry declares its input needs; run_analyzer (§4) computes the
    # ones whose needs are met and marks the rest `unresolved`. The
    # Imago-free walking skeleton resolves ONLY M1 + the geometric M5;
    # everything all-electron or relaxation-based comes back unresolved,
    # and the pipeline still runs (DESIGN §6.7, VISION goal 4).
    return [
        measure("mechanical_work_of_separation",       # M1  §8.4
                needs = {force_vs_grip, reference_state,
                         separation_point, interface_area},
                per_rate = true),                       # once per pull
        measure("work_of_adhesion_as_fractured",        # M2  §8.5
                needs = {separated_endpoint, minimizer}),
        measure("work_of_adhesion_relaxed",             # M2  §8.5
                needs = {separated_endpoint, minimizer, anneal}),
        measure("surface_healing_energy",               # M2  §8.5
                needs = {work_of_adhesion_as_fractured,
                         work_of_adhesion_relaxed}),
        measure("transferred_atom_count",               # M2  §8.5
                needs = {separated_endpoint, provenance}),
        measure("quasi_static_curve",                   # M3  §8.6
                needs = {minimizer, opening_ladder}),
        measure("rate_gap",                             # M3  §8.6
                needs = {quasi_static_curve, frames, minimizer},
                per_rate = true),
        measure("interface_fidelity",                   # M4  §8.7
                needs = {all_electron_value, m2_on_subcell}),
        measure("subcell_truncation_error",             # M4  §8.7
                needs = {m2_on_full, m2_on_subcell}),
        measure("coordination_number",                  # M5g §8.8
                needs = {frames, bond_cutoffs},
                per_rate = true),
        measure("cross_interface_bond_density",         # M5g §8.8
                needs = {frames, bond_cutoffs, provenance,
                         interface_area}, per_rate = true),
        measure("contact_area_fraction",                # M5g §8.8
                needs = {frames, bond_cutoffs, provenance},
                per_rate = true),
        measure("effective_charge",                     # M5e §8.8
                needs = {electronic_descriptors}),
        measure("bond_order_electronic",                # M5e §8.8
                needs = {electronic_descriptors}),
        measure("dos_at_fermi",                         # M5e §8.8
                needs = {electronic_descriptors}),
        measure("gap_size",                             # M5e §8.8
                needs = {electronic_descriptors})]
    # The full RDF, DOS, and partial DOS are SPECTRA, not scalars: they
    # are emitted as by-reference curve ARTIFACTS for human reading, not
    # as records above (DESIGN §6.4, §6.6). Only the two DOS scalars
    # (dos_at_fermi, gap_size) are reduced into the measure vector.
    #
    # `per_rate = true` marks a measure computed ONCE PER PULL, on that
    # pull's single Trajectory (§4's loop iterates .pulls for these). The
    # rest default to whole-result and take the entire BondDebondResult.
    # Of those, the ones that still need a pull (M2, M4, and M5's
    # electronic family) run on the REPRESENTATIVE pull — the slowest
    # rung, closest to quasi-static — which each measure's compute selects
    # from the result before calling its kernel; that is why the
    # `trajectory` parameter of m2_on / m4_differences / etc. is a single
    # pull. quasi_static_curve needs no pull at all. Which rung counts as
    # "representative" is a DESIGN §6.4 detail (TODO), not the loop's.
```

### 8.2 Derived bond cutoffs (`DESIGN.md` §6.3)

```
function derived_cutoffs(structure):
    # ONE cutoff per unordered species pair, from the FIRST MINIMUM of
    # that pair's partial g(r) — the boundary between first and second
    # coordination shells, which is what "bonded" means. NOT the five
    # hardcoded constants of prior art (PRIOR_ART.md §1.8).
    cutoffs = empty map
    for each unordered species pair (s, t) in structure:
        # Adopt §3.5's partial-g(r) kernel WITH the density-reference
        # normalization (a sound prior-art kernel, PRIOR_ART.md §1.8).
        radial = partial_gr(structure, s, t)
        minimum = first_minimum(radial)      # prior art's own unused
                                             # first-peak/min finder
        if minimum is resolved:
            cutoffs[(s, t)] = minimum
        else:
            # Too few pairs, or a liquid-like g(r) with no clear shell.
            # The DEPENDENT measure is marked unresolved downstream — we
            # NEVER fall back to a constant (DESIGN §6.3).
            cutoffs[(s, t)] = unresolved
    return cutoffs      # written into Geometry.bond_cutoffs (§4)
```

Bottoms out: it composes two adopted kernels and a resolved/unresolved
branch, no decision left to make.

### 8.3 Provenance is not species: the bond graph and the fragments

The one confusion §6.2 removes, made operational. Species is chemistry
(what the potential sees, one global oxygen); provenance is which slab an
atom was built in (bookkeeping the potential never sees). Both live on
`Atom` (§3) as separate fields, so a cutoff lookup uses SPECIES and a
cross-interface test uses PROVENANCE — prior art has one field doing both
and is wrong in both directions at once (`DESIGN.md` §6.2).

```
function build_bond_graph(structure, cutoffs):
    # An edge joins two atoms iff their MINIMUM-IMAGE distance is within
    # the cutoff for their SPECIES pair (§8.2). Minimum image throughout
    # (adopt §5's routine) — prior art omits it in the very function that
    # defines a neighbour (PRIOR_ART.md §1.8).
    graph = empty graph over structure.atoms
    for each near pair (i, j) from a cell list:
        pair_cutoff = cutoffs[species_pair(i, j)]
        if pair_cutoff is resolved and
           min_image_distance(i, j) <= pair_cutoff:
            graph.add_edge(i, j)
    return graph

function is_cross_interface(edge):
    # A bond is cross-interface iff its endpoints' PROVENANCE differs.
    # This is the DEFAULT interface definition (DESIGN §6.2): always well
    # defined, cheap, and the one under which atom transfer is
    # expressible. An alternative — the surface of MINIMAL BOND STRENGTH,
    # a weakest-cut that routes around truly integrated transferred atoms
    # — is a documented registry alternative (DESIGN §6.2, §6.7); where
    # both are computed, their disagreement measures true transfer.
    return edge.i.provenance != edge.j.provenance

function fragments_and_transfer(structure, cutoffs):
    # The pieces of a separated state are the connected components of the
    # bond graph (union-find) — the SAME connectivity kernel §2.6/§7.5
    # use to strip ejecta, now used to split a fractured interface.
    graph     = build_bond_graph(structure, cutoffs)
    fragments = connected_components(graph)

    # An atom TRANSFERRED iff its own provenance disagrees with the
    # majority provenance of the fragment it ends in (DESIGN §6.2). This
    # is measurable ONLY because provenance survives the migration.
    transferred = 0
    for each fragment in fragments:
        home = majority_provenance(fragment)
        transferred += count(atom in fragment
                             where atom.provenance != home)
    return (fragments, transferred)
```

Bottoms out: cell list + union-find + a majority count.

### 8.4 M1 — the mechanical work integral (`DESIGN.md` §6.4, §5.5)

```
function mechanical_work_of_separation(trajectory, interface_area):
    # The integral of resisting force over grip displacement, from the
    # EQUILIBRATED zero-load reference (§5.3) to complete separation,
    # per unit interface area. The headline, always available, needs no
    # all-electron code (DESIGN §6.4, VISION goal 4).
    curve = trajectory.force_vs_grip
    # DISCARD the averaging fix's leading zero before integrating — it
    # anchored both of prior art's headline artifacts (PRIOR_ART.md
    # §1.8, DESIGN §5.5). Start at the reference grip position, not step 0.
    curve = drop_leading_average_zero(curve)
    start = trajectory.reference_state.grip_position
    stop  = grip_position_at(trajectory.separation_point)
    work  = trapezoid(curve, from = start, to = stop)   # eV
    return work / interface_area                        # eV/A^2 -> J/m^2
```

M1 is **dissipative and rate-dependent** by construction, so the analyzer
computes ONE M1 per rate on the §5.4 ladder, each averaged over the
ensemble with its uncertainty (`DESIGN.md` §6.4). Bottoms out — a
trapezoid over a curve the trajectory already carries.

### 8.5 M2 — thermodynamic work of adhesion (`DESIGN.md` §6.4)

The analyzer's OWN part is code-ready: split into pieces (§8.3), apply the
energy formula, form the healing difference. The relaxations it needs are
DELEGATED to the shared minimizer/anneal (§8.10).

```
function work_of_adhesion(bonded_energy, piece_one_energy,
                          piece_two_energy, interface_area):
    # Separated MINUS bonded, divided by area (DESIGN §6.4). The SIGN is
    # the one prior art reversed (PRIOR_ART.md §1.8). Positive means the
    # bonded system is lower in energy — adhesion costs energy to undo.
    return (piece_one_energy + piece_two_energy
            - bonded_energy) / interface_area

function m2_on(cell_structure, trajectory, kind):
    # Parameterized by WHICH cell (full system, or the §8.7 subcell) so
    # M4 can reuse it on the subcell without a second definition. `kind`
    # selects the reference: as_fractured or relaxed.
    bonded = potential_energy(cell_structure)          # unambiguous
    (pieces, _) = fragments_and_transfer(
        separated_endpoint(cell_structure, trajectory),
        derived_cutoffs(cell_structure))
    # Each piece held at the SHARED lateral cell (DESIGN §6.4).
    if kind == as_fractured:
        # Relax each piece only into its NEAREST minimum — surfaces left
        # damaged, matched to M1's endpoint (DELEGATE: local minimizer).
        relaxed_pieces = map(minimize_local, pieces)
    else:  # kind == relaxed
        # Additionally ANNEAL so surfaces reorganize and dangling bonds
        # pair — the reference that connects to W = gA + gB - gAB
        # (DELEGATE: anneal; its SCHEDULE is a recorded knob, DESIGN §6.4).
        relaxed_pieces = map(minimize_then_anneal, pieces)
    e1, e2 = potential_energy(relaxed_pieces[0]),
             potential_energy(relaxed_pieces[1])
    return work_of_adhesion(bonded, e1, e2, interface_area(cell_structure))
```

`surface_healing_energy` = `as_fractured − relaxed` (>= 0, checked in
§8.9); `transferred_atom_count` comes straight from §8.3. Each M2 entry is
reported **twice** (`DESIGN.md` §6.4): a `potential_energy_difference` at
0 K (the headline, comparable with M4's 0 K all-electron value) and a
`free_energy_correction` at press temperature — the latter DELEGATES a
per-endpoint phonon calc, so its ensemble may be smaller than M1's.

### 8.6 M3 — the quasi-static curve and the rate gap (`DESIGN.md` §6.4)

```
function quasi_static_curve(structure, opening_ladder):
    # A rate-FREE reversible curve: impose each prescribed interface
    # opening and MINIMIZE at it (DELEGATE: constrained minimizer). Its
    # integral is the primary quasi-static number M1's ladder aims at.
    energies = empty list
    for each opening in opening_ladder:
        constrained = impose_opening(structure, opening)
        energies.append(minimize_at_fixed_opening(constrained))
    return curve_of(opening_ladder, energies)

function rate_gap(quasi_static, trajectory):
    # Minimize each §5 dynamic-pull FRAME and record its energy (DELEGATE:
    # minimizer). This curve carries the pull's HISTORY, so it is NOT
    # reversible and its openings are uneven — not a substitute. Its value
    # is the GAP from the reversible ladder: how far the chosen pull rate
    # sits from quasi-static, the assumption the whole ladder rests on.
    relaxed_snapshots = map(minimize_local, trajectory.frames)
    return gap_between(relaxed_snapshots, quasi_static)
```

Structure code-ready; every minimization is delegated (§8.10).

### 8.7 M4 — forming the two differences (`DESIGN.md` §6.4)

M4 is the same energy difference as M2 but at ALL-ELECTRON fidelity, and
it is affordable only on a subcell. The trap §6.4 warns of: subtracting an
all-electron subcell number from an MLIP FULL-cell number mixes the
fidelity difference we want with a box-size difference we do not. So the
analyzer forms TWO differences, each holding one thing fixed.

```
function m4_differences(structure, trajectory):
    # The all-electron value on the SUBCELL comes from the
    # CHARACTERIZATION module (VASP now, Imago at scale) — DELEGATE. The
    # subcell itself is the whole-layer-quantized truncation of §6.4 /
    # DESIGN §8.2, also owned there. The analyzer only FORMS the
    # differences and gates one by the other.
    subcell        = interface_subcell(structure)          # DELEGATE
    m4_value       = all_electron_work_of_adhesion(subcell) # DELEGATE
    m2_subcell     = m2_on(subcell,   trajectory, as_fractured)
    m2_full        = m2_on(structure, trajectory, as_fractured)

    # Two methods, ONE system: the STRUCTURAL-3 signal — a potential
    # confidently wrong exactly where the bond number is read.
    interface_fidelity = m4_value - m2_subcell
    # One method, TWO systems: what truncation cost, and it is CHEAP
    # (both terms from the potential, no all-electron calc).
    subcell_truncation_error = m2_full - m2_subcell

    # The cheap difference GATES the expensive one: if shrinking the cell
    # moved the answer by as much as the fidelity gap we mean to read,
    # the question was never askable on this subcell (DESIGN §6.4, §6.5).
    if not small_compared_to(subcell_truncation_error,
                             interface_fidelity):
        interface_fidelity = unresolved
    return (interface_fidelity, subcell_truncation_error)
```

The difference-forming and the gate bottom out here; the all-electron
value and the subcell extraction delegate to characterization (§8.10).

### 8.8 M5 — descriptors, two families kept nominally apart (§6.4)

```
function geometric_descriptors(trajectory, cutoffs, interface_area):
    # From POSITIONS and the derived cutoffs only — no electrons. Computed
    # along the whole trajectory. These are the graded contact-quality
    # measure §5.1 needs.
    series = empty list
    for each frame in trajectory.frames:
        graph = build_bond_graph(frame, cutoffs)          # §8.3
        coordination = mean_degree(graph)
        cross_bonds  = count(edge in graph
                            where is_cross_interface(edge))
        series.append({
            coordination_number          : coordination,
            cross_interface_bond_density : cross_bonds / interface_area,
            contact_area_fraction        : contact_fraction(frame, graph)})
    return series
```

Alongside the scalar series, the geometric family also emits the
**partial RDF of the surface-region atoms across named stages** (pristine
-> activated -> pressed -> as-fractured -> relaxed), reusing §8.2's
partial-g(r) kernel not to derive a cutoff but as a structural diagnostic
(`DESIGN.md` §6.4). It is a SPECTRUM, so it is stored as a by-reference
curve ARTIFACT for human reading (§6.6), NOT reduced to a scalar record.

The **electronic** family — `effective_charge` (Q\*) and
`bond_order_electronic` — are properties of the electron density, not the
neighbour list, and come from the CHARACTERIZATION module on §8-selected
snapshots with endpoints relaxed first (DELEGATE). To these it adds the
**total and partial density of states** (a signature Imago output, VASP
backstop): the full DOS and partial DOS ride the native channel as
by-reference curve ARTIFACTS (§8.6-of-DESIGN), and only two scalars are
reduced from them — `dos_at_fermi` and `gap_size` (`DESIGN.md` §6.4).
None of the electronic family may share a name with the geometric one:
prior art calls a geometric neighbour count "bond order," so a reader
would compare unlike things (`DESIGN.md` §6.4). The schema's `fidelity`
field (`geometric` vs `electronic`, §4) keeps them apart for the gate too.

`contact_fraction` is now defined (`DESIGN.md` §6.4 pins the geometry;
the §7.6.1-style flag this pass raised is resolved):

```
function contact_fraction(frame, graph):
    # Overlay the shared lateral cell with an EQUAL-AREA grid in
    # FRACTIONAL coordinates (equal-area so a triclinic cell needs no
    # special case), Nx x Ny cells sized near one cross-interface cutoff
    # (contact_grid_spacing, a recorded NumericalKnob). A cell is IN
    # CONTACT when it holds the MIDPOINT of a cross-interface bond (§8.3).
    # This measures BONDED contact, not mere proximity (DESIGN §6.4).
    occupied = empty set
    for each edge in graph where is_cross_interface(edge):
        midpoint = min_image_midpoint(edge)     # wrapped into the cell
        (u, v)   = fractional_xy(midpoint, frame.lateral_cell)
        occupied.add(grid_cell_of(u, v, contact_grid_spacing))
    return size(occupied) / grid_cell_count(frame, contact_grid_spacing)
```

Bottoms out: a grid bin over the cross-interface bond midpoints §8.3
already yields. Its one knob, `contact_grid_spacing`, is recorded and —
like the subcell size (§6.4) — should be checked for insensitivity over
a range rather than trusted at a single value.

### 8.9 The check math (`DESIGN.md` §6.5)

Each ordering in the inequality chain is a test on numbers already
computed, emitted as a `CheckResult` (§4). None exists in prior art, whose
analyzer contains no check that can fail (`PRIOR_ART.md` §1.8).

```
function analyzer_checks(measures):
    checks = empty list
    # Dissipation >= 0. A negative value means the reference state or the
    # integral is wrong -> the run is REJECTED (void, §5.5), not reported.
    checks.append(nonneg("dissipation",
        measures.M1_slowest - measures.work_of_adhesion_as_fractured))
    # Healing energy >= 0, else the anneal did not relax (DESIGN §6.5).
    checks.append(nonneg("surface_healing_energy",
        measures.work_of_adhesion_as_fractured
        - measures.work_of_adhesion_relaxed))
    # The rate ladder converges FROM ABOVE: M1 decreases monotonically
    # toward as_fractured as the rate falls (DESIGN §5.4, §6.5).
    checks.append(monotone_decreasing_toward(
        "rate_ladder_from_above",
        measures.M1_by_rate, measures.work_of_adhesion_as_fractured))
    # Ladder closure: M3's force-integral must equal its endpoint energy
    # difference — tests the INTEGRATOR independent of physics; the single
    # check that catches a leading-zero or truncated-trajectory artifact.
    checks.append(equal_within_tol("quasi_static_ladder_closure",
        integral_of(measures.quasi_static_curve),
        endpoint_energy_difference(measures.quasi_static_curve)))
    # The subcell was big enough to ask the question (gates M4, §8.7).
    checks.append(small_compared_to("subcell_adequate",
        measures.subcell_truncation_error,
        measures.interface_fidelity))
    return checks
```

Bottoms out. These join §5's Newton residual, atom-count conservation,
and trajectory completeness in the `checks` list of the MeasureVector (§4);
the gate (§5) reads them by name.

### 8.10 What bottoms out, what delegates

`[BOTTOMS OUT here]` `derived_cutoffs` (§8.2); the bond graph, fragments,
and transfer count (§8.3); the M1 work integral (§8.4); the
work-of-adhesion formula and healing difference (§8.5); the M4
difference-forming and its gate (§8.7); the geometric descriptors and the
surface-region RDF-across-stages curve artifact (§8.8); and every check
(§8.9). Each composes adopted kernels (partial g(r), minimum image,
union-find, trapezoid) with a resolved/unresolved branch.

`[DELEGATE -> MINIMIZER / anneal, shared with the MD pass §5-of-DESIGN,
not yet written]` `minimize_local` (as_fractured pieces and the M3
relaxed snapshots), `minimize_then_anneal` (relaxed pieces; SCHEDULE is a
recorded knob), and `minimize_at_fixed_opening` (M3's constrained ladder).

`[DELEGATE -> CHARACTERIZATION module, DESIGN §8, not yet written]` the
all-electron value on the subcell and the subcell extraction itself
(whole-layer quantized, §6.4/§8.2-of-DESIGN); and M5's electronic family
(`effective_charge`, `bond_order_electronic`, and the DOS/partial-DOS
curves with their two reduced scalars `dos_at_fermi` / `gap_size`) on
§8-selected snapshots.

`[DELEGATE -> PHONON calc]` M2's `free_energy_correction` per endpoint.

`[DEFINED]` `contact_area_fraction`'s geometry is now pinned (§8.8,
`DESIGN.md` §6.4); only its knob `contact_grid_spacing` remains a numeric
follow-on.

The pattern mirrors §7: the module's own algorithms reach code-readiness
this pass, and what remains is either one adopted call away or owned by a
module whose contract §3/§4 already froze — so none of it can force this
one to change (`ARCHITECTURE.md` §5.1).

---

## 9. Bond/debond MD — algorithms (steps 6, 7)

This is the **third depth-first module pass** (`ARCHITECTURE.md` §5.4),
on `DESIGN.md` §5. It refines the `run_bond_debond_md` body (the §6
walking-skeleton stub) to code-readiness, and it also supplies the
minimizer/anneal routines the analyzer §8 delegated back here (§8.5,
§8.6) — they live here because they run on the SAME LAMMPS driver under
the SAME MLIP. It runs on LAMMPS under `pair_style deepmd` on GPU
(`ARCHITECTURE.md` §4.1). Almost everything bottoms out into LAMMPS
fixes with a few real decisions on top; §9.8 lists the two things that
delegate outward.

Prior art built and RAN this stage, so its failures are concrete
(`PRIOR_ART.md` §1.7): a chemistry-free interface escalated to a 150 m/s
velocity impact, a thermostat that counted the drive as heat, a pull
integrated from a stressed state, a kept leading-zero, a `max()` peak,
and a truncated trajectory quoted as a result. Every routine below is
built to refuse one of those.

### 9.1 The module's top-level shape, and the press/pull seam

**The press happens once; the pull repeats per rate.** Bonding is a
single event, but the §5.4 rate ladder pulls the SAME bonded state at
several rates. So the stage emits one press outcome, one gated reference
state, and a LIST of per-rate pulls — not a single trajectory.

```
record BondDebondResult:
    # The concrete form of the §3 press/pull stage output (what §1 calls
    # BOND_DEBOND_CONTRACT). One press, one reference, many pulls.
    press:     PressOutcome         # step 6 (§5.1, §5.2)
    reference: StateRef             # gated zero-load reference (§5.3)
    pulls:     list of Trajectory   # one §3 Trajectory per pull rate

record PressOutcome:
    bonded:           boolean   # verdict at the specified load (§5.1)
    contact_quality:  number    # graded; reuses §8.8 geometric machinery
    bonded_structure: StateRef  # the held, relaxed bonded state
    load_reached:     number    # BOTH load AND depth are reported (§5.2)
    depth_reached:    number
```

```
function run_bond_debond_md(structure, potential, member_specification):
    driver = open_lammps_driver(structure, potential,
                                member_specification)   # §9.2, persistent

    # Step 6: press the two activated surfaces together and let them bond.
    press = press_and_bond(driver, member_specification)          # §9.3

    # The gated zero-load reference the pull integrates from (§5.3).
    reference = settle_reference(driver, press, member_specification)  # §9.4

    # Step 7: pull ONCE PER RATE (§5.4), each from a fresh copy of the
    # reference (a pull deforms it). The press is NOT repeated.
    pulls = empty list
    for each rate in member_specification.numerical.pull_rate_ladder:
        pulls.append(pull_at_rate(driver, reference, rate,
                                  member_specification))     # §9.5, §9.6
    return BondDebondResult{ press: press, reference: reference,
                            pulls: pulls }
```

`[SEAM — resolved]` this refines the §3 trajectory seam. `Trajectory`
(§3) stays the shape of ONE pull; `BondDebondResult` wraps the press
outcome and the per-rate list around it. Its consumers: `run_analyzer`
(§4, §8) reads `press.bonded` / `press.contact_quality` into the
`Verdicts` (§4) and iterates `pulls` for the per-rate measures (§8.4's
"one M1 per rate"). The walking skeleton (§6) runs a single-rate ladder,
so `pulls` has one element — the seam is exercised, not special-cased.
RENAMED (the programmer's call): the stage-output object is the variable
`bond_debond_trajectory` of type `BondDebondResult`, guarded by
`BOND_DEBOND_CONTRACT`; the per-pull `Trajectory` record and the
`trajectory` parameters inside the §8 measures keep their names, because
those genuinely are one pull. `run_analyzer` now iterates `.pulls` for
per-rate measures and reads `.press` into `Verdicts` (§4).

### 9.2 The persistent LAMMPS driver

```
function open_lammps_driver(structure, potential, member_specification):
    # ONE persistent LAMMPS process for the whole press+pull, NOT a fresh
    # LAMMPS per impact with a full-slab disk round-trip (prior art's
    # antipattern, PRIOR_ART.md §1.7). Load the potential once, then CARVE
    # press/pull depth zones from §2's z-ranges (§3 LabeledGroups, option
    # C) — the builder does NOT hand these over as atom-index sets; the
    # driver cuts them by depth at open time:
    #   bottom_grip       -> held handle, the press/pull anchor (§9.5)
    #   top_grip          -> driven handle, ramped or moved (§9.3, §9.5)
    #   border            -> just inside each grip, INTEGRATED (nve) AND
    #                        Langevin-thermostatted, BIAS-REMOVED. The nve
    #                        is not optional: a Langevin fix adds forces
    #                        but does not advance, so a border without its
    #                        own nve is a reflecting wall, not the §5.2
    #                        heat sink (found on a compute node, stage 5).
    #   interior          -> plain NVE, everything left over. "Interior"
    #                        here names ONLY this free group, never the
    #                        border; see §9.3's thermostat note.
    # The activated_skin is NOT carved here: it is the MEASURED set
    # (§10.7) carried from activation, integrated as interior but TRACKED
    # for §5.1. (The cascade driver, §10.2, carves a frozen_base instead
    # of grips from the same z-ranges — the zones are stage-appropriate.)
    # The lateral cell is HELD FIXED — no lateral barostat, or the
    # recorded substrate strain relaxes away and the provenance number
    # becomes a fiction (§5.6). The z-boundary is non-periodic, vacuum
    # sized for the full pull distance plus margin.
    return driver
```

### 9.3 press_and_bond — mode, no impact, honest thermostat, dual contact

```
function press_and_bond(driver, member_specification):
    protocol  = member_specification.protocol
    numerical = member_specification.numerical
    # Pluggable control mode at ONE seam (§5.2). v1 freezes load-control;
    # displacement-control is the SAME seam, run once on Si/Si as a
    # cross-check (their disagreement measures press irreversibility).
    # HANDLES ARE RIGID by default, with ONE exception: applying a load is
    # setting a FORCE, and a force moves nothing unless something
    # integrates it, so under load-control the driven grip is given its
    # OWN integrator (mass) and the pressure pushes it down. Under
    # displacement-control the grip is driven kinematically, so it needs
    # no integrator. Either way the settle later re-freezes it (§9.4).
    if protocol.press_control == load:
        drive = ramp_normal_stress(driver.grips.top, protocol.press_load,
                                   protocol.press_approach_rate)
    else:  # displacement
        drive = drive_grip_down(driver.grips.top, protocol.press_depth,
                                protocol.press_approach_rate)

    # NO VELOCITY IMPACT (§5.2): approach speed far below the sound speed,
    # acquired kinetic energy far below the bond scale — else the press is
    # a collision and the interface is interlock, not adhesion. A GATE.
    assert approach_is_quasistatic(drive)

    # THE THERMOSTAT MUST NOT SEE THE DRIVE (§5.2): thermostat the BORDER
    # ONLY — the layer just inside each grip — never the grips and never
    # the interface. Integrate BOTH the border and the interior (each
    # nve), because the Langevin thermostat on the border adds forces but
    # does not advance; a border that is thermostatted but never moved is
    # a reflecting wall, not a heat sink (§9.2). Remove the center-of-mass
    # bias from the border before thermostatting it, so directed drift is
    # never read as heat (prior art's nvt-on-the-drifting-slab error).
    integrate_interior_and_border(driver)
    thermostat_border_bias_removed(driver, protocol.press_temperature)

    # CONTACT ON A DUAL CRITERION (§5.2, adapted from prior art's one good
    # idea, find_contact_step): PRIMARY = the gap between the two §2.6
    # density dividing surfaces has closed to a threshold; CONFIRM = a
    # running average of the normal stress has turned positive. A gap can
    # close on ONE asperity; positive normal stress means the surfaces
    # genuinely load each other. Gap measured surface-to-surface, NOT
    # between extremal atoms (prior art's asperity failure).
    run_until(driver,
        gap_between_dividing_surfaces(driver) <= numerical.contact_gap_threshold
        and mean_normal_stress_positive(driver))

    # The HOLD at temperature is where bonding actually happens (§5.2).
    hold_at_temperature(driver, protocol.press_duration)

    # The bonded/not-bonded VERDICT and graded contact quality (§5.1),
    # reusing the §8.3/§8.8 geometric machinery rather than a second
    # copy. A no-bond is a RESULT with its own diagnostic label (§7),
    # NEVER a reason to escalate the drive.
    quality   = contact_quality(current_frame(driver))
    threshold = numerical.bonded_contact_threshold
    return PressOutcome{
        bonded: quality >= threshold, contact_quality: quality,
        bonded_structure: snapshot(driver),
        load_reached: measured_load(driver),
        depth_reached: measured_depth(driver) }
```

### 9.4 settle_reference — a gated zero-load state (`DESIGN.md` §5.3)

```
function settle_reference(driver, press, member_specification):
    numerical = member_specification.numerical
    # The pull's curve must start at rest under NO applied load. Prior art
    # minimizes, re-heats, and pulls at once, integrating from a stressed
    # state (its PE jumps 481 eV in 0.5 ps). SABSIM GATES the reference.
    #
    # RUNS ON THE PRESS'S OWN LAMMPS INSTANCE (no re-read of a data file),
    # so the box, the carved groups, and the grip force GAUGES all persist
    # from the press — the settle reads the gauges, it does not recreate
    # them. FIRST release the press drive so nothing is still loading the
    # interface: remove the drive fix, and under LOAD control also remove
    # the driven grip's own integrator, which re-freezes it into a rigid
    # handle at the depth it reached. Without this the reference would
    # equilibrate WHILE STILL BEING PRESSED and the zero-load gate would
    # be a lie.
    release_press_drive(driver, member_specification)
    minimize(driver)                          # to a local minimum
    equilibrate_under_thermostat(driver)      # settle at temperature
    # ASSERT the press actually settled; if not, REPORT, do not integrate
    # over it (§5.3). Force floor reuses the pull's noise floor.
    assert net_grip_force(driver) <= numerical.noise_floor
    assert potential_energy_drift(driver) <= numerical.reference_pe_drift
    # The location is a WRITTEN data file, because the pull restores from a
    # file on a fresh instance (§9.6); handing it the original pair data
    # would silently discard the whole press.
    return StateRef{ location: write_reference(driver),
                     potential_energy: potential_energy(driver) }
```

### 9.5 pull_at_rate — one rung of the ladder (`DESIGN.md` §5.4)

```
function pull_at_rate(driver, reference, rate, member_specification):
    numerical = member_specification.numerical
    restore(driver, reference)           # a FRESH copy; the pull deforms it
    hold(driver.grips.bottom)            # bottom grip held
    drive_grip(driver.grips.top, rate)   # top grip at constant rate

    # BOTH reaction forces are recorded; their sum is a FREE Newton check
    # (§5.4). LAMMPS exposes the summed force on a held group BEFORE it is
    # zeroed, so the check costs nothing. Prior art holds with setforce,
    # never queries it, and throws the check away.
    record_both_grip_reactions(driver)

    # THE COORDINATE ARCHIVE is opened up front, and ONLY when a consumer
    # will actually read it — anything that needs atomic POSITIONS: the §8
    # measures that read frames (contact area, bond graphs, relaxed
    # snapshots), step-8 characterization (Imago, RDF, structural
    # descriptors), or a person keeping the movie. A strided atomic-
    # coordinate dump -> FrameSetRef (§3); NEVER every step (frame_stride,
    # §2). It is a SEPARATE artifact, NOT read by the reduction. The bare
    # bond-strength run opens nothing — its 1.3 GB/rung is why the default
    # omits it.
    if a coordinate consumer is in play:
        frames_ref = open_strided_frame_dump(driver,
                                             numerical.frame_stride)
    else:
        frames_ref = none

    # The pull advances in CHUNKS; after each, the per-chunk SERIES are
    # read back and appended (§13.5 shows the loop in full, re-keyed for
    # resume): grip displacement, force, interface opening, and the
    # cross-interface bond count. These live scalar lists — NOT stored
    # frames — are the ONLY thing the reduction is built from.
    series = run_pull_gathering_series(driver, rate, numerical)

    return reduce_to_trajectory(driver, series, frames_ref, reference,
                                rate, member_specification)        # §9.6
```

### 9.6 reduce_to_trajectory — two curves, separation, and the gates

```
function reduce_to_trajectory(driver, series, frames_ref, reference,
                              rate, member_specification):
    numerical = member_specification.numerical
    # The reduction is built ENTIRELY from the per-chunk SERIES gathered
    # live in the loop (§9.5) — displacement, force, opening, bridges.
    # `frames_ref` is the SEPARATE coordinate archive (§3): carried
    # through to Trajectory.frames for real analysis and human eyes, and
    # NOT read here. It is `none` when no consumer needed it (§9.5).

    # Force is TIME-AVERAGED and the average's WARM-UP is DISCARDED
    # (§5.4). The window is in units of GRIP DISPLACEMENT (small vs a
    # bond length), not timesteps. An averaging fix emits a leading ZERO
    # before its first window closes — DROP it (prior art kept it as
    # debond.dat's first point, anchoring a trapezoid and a modulus fit).
    force_vs_grip = averaged_force_curve(series.displacement, series.force,
                        numerical.force_average_window,
                        drop_leading_zero = true)

    # TWO curves (§5.5). Force vs GRIP DISPLACEMENT is the M1 integrand.
    # Force vs INTERFACE OPENING (distance between the two §2.6 dividing
    # surfaces) is where the interface actually is — separation is NOT
    # grip displacement, which also holds the slabs' elastic stretch.
    # Both re-expressions run off the SERIES, never off stored frames.
    force_vs_opening = reexpress_versus_opening(force_vs_grip,
                           series.displacement, series.opening)
    bridge_curve     = reexpress_versus_opening(force_vs_grip,
                           series.displacement, series.bridges)

    # COMPLETE SEPARATION (§5.5): the FIRST sample of the REDUCED curves
    # where the interface opening exceeds the potential cutoff (6 A, §4.6)
    # and NO bonds still bridge the gap. This is an index into the curves,
    # NOT a frame index. The M1 integral (§8.4) stops HERE, not at the
    # record's end (prior art integrated the whole noise tail).
    separation = separation_point(force_vs_opening, bridge_curve,
                                  potential_cutoff)

    # The PEAK is EXTRACTED above the noise floor by a stated margin, not
    # max() over noise (§5.4); a below-margin peak is marked unresolved by
    # the analyzer (§8), not here. This routine only carries the curves.

    # GATES, not warnings (§5.6). A non-periodic box silently deletes an
    # escaped atom, so atom-count conservation is a gate; and the run must
    # be COMPLETE (walltime budgeted from distance/rate, not a flat
    # clock) — prior art's headline came from a 122500/150000-step run in
    # a dir named NOTE_INCOMPLETE.txt.
    return Trajectory{
        identifier:           new_trajectory_id(),
        force_vs_grip:        force_vs_grip,
        force_vs_opening:     force_vs_opening,
        scalar_series:        series_of(driver),   # sigma_zz, PE, ...
        reference_state:      reference,
        separation_point:     separation,  # index into the reduced curves
        complete:             ran_to_completion(driver),
        atom_count_conserved: atom_count_unchanged(driver),
        grip_reaction:        both_grip_curves(driver),
        provenance:           provenance_of(rate, member_specification),
        frames:               frames_ref }
```

The **dissipation sign check** (§5.5) — mechanical work >= thermodynamic
work of adhesion — is NOT run here: it needs the relaxed-endpoint W_adh
that the analyzer computes (§8.5), so it lives in §8.9's check list. This
module's part is to record the inputs it needs — the averaged curve and
the bonded/separated relaxed endpoints (via §9.7) — honestly.

### 9.7 The minimizer/anneal routines the analyzer delegates here

The analyzer (§8.5, §8.6) delegates its relaxations to this module: they
run on the same LAMMPS driver under the same MLIP, and they are
minimizations, not dynamics, so they are cheap and deterministic given
the potential.

```
function minimize_local(fragment_or_frame, potential):
    # Relax into the NEAREST local minimum at FIXED lateral cell — no
    # thermostat, no anneal (§8.5 as_fractured pieces; §8.6 relaxed
    # snapshots). Surfaces are left as the pull/press left them.
    return minimized_state

function minimize_then_anneal(fragment, potential, anneal_schedule):
    # minimize_local, then a short ANNEAL so surface atoms reorganize and
    # dangling bonds pair (§8.5 relaxed reference). The SCHEDULE is a
    # recorded knob: an amorphous surface is kinetically trapped, so
    # "relaxed" means "as relaxed as this schedule got it" (DESIGN §6.4).
    return annealed_state

function minimize_at_fixed_opening(structure, opening, potential):
    # Impose a prescribed interface opening and minimize with that opening
    # CONSTRAINED (§8.6 M3's rate-free quasi-static ladder).
    return constrained_minimum
```

### 9.8 What bottoms out, what delegates

`[BOTTOMS OUT here]` the persistent driver and its depth-zone carve +
group -> fix map (§9.2); `press_and_bond`'s mode switch, no-impact gate,
bias-removed thermostat, dual contact criterion, and hold (§9.3);
`settle_reference`'s
gated minimize+equilibrate (§9.4); `pull_at_rate`'s both-grip recording,
its live per-chunk series, and the conditional coordinate archive (§9.5);
`reduce_to_trajectory`'s warm-up-discarded averaged force, two curves,
separation point, and gates, all off the series (§9.6);
and the three minimizer/anneal routines (§9.7). Each is a LAMMPS-driver
operation plus a clear gate or extraction.

`[DELEGATE -> POTENTIAL, DESIGN §4]` the MLIP the whole stage runs under
is step 2's committee; this module is a CONSUMER of it (`pair_style
deepmd`), never its author.

`[ABOVE this module]` the ensemble (STRUCTURAL 4 amorphization seeds and
thermal-velocity seeds, `DESIGN.md` §5.4) is looped by the sequencer via
`realization_count` (§2); this module runs ONE realization, and the
averaging over seeds is §6.6's uncertainty, not this module's job.

`[CODE level, below pseudocode]` the exact LAMMPS fix syntax.

`[DESIGN §5.9 numeric follow-ons]` the VALUES of the knobs added for this
module — `press_temperature`, `press_approach_rate`, `contact_gap_
threshold`, `bonded_contact_threshold`, `force_average_window`,
`reference_pe_drift` — plus the target bonding pressure and hold duration.
Their existence is pinned here; their numbers are a §5.9 DESIGN task.

## 10. Surface activation — algorithms (step 4)

This is the **fourth (and final) depth-first module pass**
(`ARCHITECTURE.md` §5.4), on `DESIGN.md` §3. It refines the
`activate_surfaces` body — §1's step-4 seam, guarded by
`ACTIVATED_SLABS_CONTRACT` — to code-readiness, and it defines the
concrete form of that contract. Like §9 it runs on a persistent LAMMPS
driver, but the cascade runs under a `hybrid/overlay` ZBL + classical
splice, **not** the MLIP; the MLIP enters only at the re-anneal (§10.5),
which delegates back to §9.7.

Prior art built and RAN this stage, so its failures are concrete
(`PRIOR_ART.md` §1.2, §1.5): argon-only ZBL channels, SiO₂-hardcoded
metrics, a whole-slab NVT that over-couples and QUENCHES the cascade
before damage accumulates, a newest tree that dropped the frozen layer
and `p p f` so it fails to amorphize AT ALL, a fresh LAMMPS process plus
a full-slab disk round-trip PER IMPACT, an impact-COUNT dose, unseeded
randomness, and a report-only "verification" with no threshold. Every
routine below refuses one of those.

### 10.1 Top-level shape, the pluggable mechanism, and the contract

Activation is **per-wafer**: each surface is amorphized independently in
vacuum, BEFORE the two ever face each other — that is the whole point of
surface-activated bonding (`DESIGN.md` §3.1). So `activate_surfaces`
activates the two slabs independently and returns the concrete form of
`ACTIVATED_SLABS_CONTRACT`.

```
record ActivatedSlabs:
    # The concrete form of §1's ACTIVATED_SLABS_CONTRACT: both slabs
    # amorphized AND past the gate (DESIGN §3.5). The verdict is CARRIED,
    # not merely logged, so run_to_contract (§1) can check verdict.passed
    # — a failed gate is a contract-invalid artifact and the pipeline
    # HALTS (gate, not warn). Prior art only PRINTED an unthresholded g(r)
    # RMSD, so a defective surface passed silently.
    slab_A:    Structure           # activated slab A (grips still unset)
    slab_B:    Structure           # activated slab B
    verdict_A: ActivationVerdict   # A's pass/fail gate result
    verdict_B: ActivationVerdict   # B's pass/fail gate result

record ActivationVerdict:
    passed:          boolean    # AND over every registered metric (§10.6)
    per_metric:      map from metric-name to MetricVerdict
    activated_depth: number     # MEASURED amorphization depth, A (§10.6)
    reason:          string     # names the failing metric when not passed

record MetricVerdict:
    measured:  number or Curve    # scalar OR a human-read curve (g(r), …)
    reference: string             # which DFT/experimental reference used
    threshold: number
    passed:    boolean
```

`[SEAM — rippled in code, 2026-07-18]` this refines §1's step-4 seam the
way §9.1 refined the press/pull seam, and the ripple is now APPLIED: the
sequencer runs `activate_surfaces` to one `ActivatedSlabs`, rebinds
`slab_A` / `slab_B` from it to feed `assemble_pair`, and the
`ACTIVATED_SLABS_CONTRACT` gates on `.verdict_A.passed` /
`.verdict_B.passed` (a failed gate halts the pipeline HERE). So the
verdict is carried, not merely logged — exactly as the
`bond_debond_trajectory` ripple was.

```
function activate_surfaces(handle_A, handle_B, member_specification,
                           potential):
    # Each surface is activated INDEPENDENTLY (both are still in vacuum,
    # not yet facing). Two calls, never one co-activation; the pair does
    # not co-exist here. Each call takes a HalfHandle (§7.1): it opens its
    # own engine, RE-READS the pristine half from handle.data_file (never a
    # warm object from build_slabs), amorphizes it, and writes the
    # amorphized half back to disk for assemble_pair (§7.5) to read — the
    # ARCHITECTURE §4.3 file handoff. [SERIAL I/O] The snapshot taken out
    # of the engine is collective (every rank holds the full atom set),
    # but ONE rank writes it and a barrier publishes it, so assemble_pair
    # finds it on whichever rank reads it back (§7.1).
    #
    # v1 runs the two as this SERIAL pair inside one job (Approach A), each
    # bombardment on the job's FULL core allocation (ARCHITECTURE §4.3 —
    # serial slabs, not two-at-once in one job). These two calls, times the
    # N realization seeds the ensemble (§10.8) loops above, are the 2 x N
    # independent units; the separate-job fan-out (Approach C) stays
    # AVAILABLE through the files but is not the plan. Because each call is
    # a pure function of (half, seed) handing off through files, that
    # fan-out is a change of submission wrapper, not of stage code — so keep
    # it free of cross-call state (# C-EXPANSION, ARCHITECTURE §4.3).
    activated_A = activate_surface(handle_A, member_specification,
                                   potential)
    activated_B = activate_surface(handle_B, member_specification,
                                   potential)
    return ActivatedSlabs{
        slab_A:    activated_A.slab,    slab_B:    activated_B.slab,
        verdict_A: activated_A.verdict, verdict_B: activated_B.verdict }
```

`[DISTILLATION — in code, 2026-07-19]` the code splits `activate_surfaces`
across two layers, and the `ActivatedSlabs` shown here is the CONCEPTUAL
result. The DRIVER (`driver/cascade.py`) returns two `ActivationResult`s
carrying the RICH `ActivationVerdict` above — every metric, the measured
depth, the named failure. The PIPELINE stage then maps each rich verdict
DOWN to the small contract `Verdict` (passed, reason) that
`ACTIVATED_SLABS_CONTRACT` reads, through the adapter
(`pipeline/activation_adapter.py`), keeping the measured skin depth and —
on a failure — the failing metric in the reason string. So the code
`exec_artifacts.ActivatedSlabs` carries the DISTILLED `Verdict`, not the
rich one; the gate still HALTS at this seam, because a distilled failure
is still a failure. The rich per-metric detail survives on the driver
side for the report (`DESIGN.md` §9), not on the contract.

The mechanism is a SEAM, not a hard-coded procedure (`DESIGN.md` §3.1).
v1 registers one mechanism — energetic-particle bombardment — but plasma
or reactive activation slot in behind the SAME signature without touching
step 4's consumers. An ion beam and a fast-atom beam are identical in
classical MD, so both are just one setting of the projectile spec (§10.3),
not separate mechanisms.

```
function activate_surface(handle, member_specification, potential):
    # RE-READ the pristine half from disk into a slab — the standalone
    # geometry plus the beam-declaring type map the handle carries (§7.1),
    # never a warm object from build_slabs (ARCHITECTURE §4.3). From here
    # DOWN the slab is in-memory WITHIN this one engine/stage, which is
    # exactly what the file discipline allows; it forbids only carrying a
    # live object ACROSS the seam between two stages.
    # [SERIAL I/O] Every rank performs this read for itself (§7.1); it is
    # a local act, NOT a collective, and must never become one.
    slab = read_standalone_half(handle)          # geometry + type_map
    # Dispatch on the configured mechanism (DESIGN §3.1) — the same
    # registry idiom as the §8 measures and the §9 press-control switch.
    # v1 registers exactly one; the seam is what makes a plasma or
    # reactive method a NON-invasive addition later.
    mechanism = ACTIVATION_MECHANISMS[
        member_specification.protocol.activation_mechanism]
    return mechanism(slab, member_specification, potential)
```

```
function energetic_particle_bombardment(slab, member_specification,
                                        potential):
    # The v1 mechanism (DESIGN §3.2–§3.5). Four stages: derive the
    # concrete impact plan, run the classical + ZBL cascade to the target
    # fluence, re-anneal under the MLIP, then GATE — validation runs on
    # the ACCURATE (re-annealed) structure, not the classical one (§3.4).
    spec    = derive_bombardment_spec(slab, member_specification)   # §10.3
    driver  = open_cascade_driver(slab, potential,
                                  member_specification)             # §10.2
    damaged = run_cascade_to_fluence(driver, spec)                  # §10.4
    relaxed = mlip_reanneal(damaged, potential,
                            member_specification)                   # §10.5
    verdict = activation_gate(relaxed, slab, member_specification)  # §10.6
    relaxed = label_activated_skin(relaxed, verdict.activated_depth)  # §10.7
    return record{ slab: relaxed, verdict: verdict }
```

### 10.2 open_cascade_driver — the correctness core

This is the part prior art gets wrong (`DESIGN.md` §3.3). It mirrors
§9.2's persistent-driver discipline, but the potential and the boundaries
are cascade-specific.

```
function open_cascade_driver(slab, potential, member_specification):
    # ONE persistent LAMMPS process for the WHOLE impact train, NOT a
    # fresh process + full-slab disk round-trip per impact (prior art's
    # antipattern, DESIGN §3.3 — the same one §9.2 refuses). At the doses
    # SAB needs (thousands of impacts) that overhead is prohibitive.
    #
    # POTENTIAL: hybrid/overlay of the config-selected CLASSICAL generator
    # (Stillinger-Weber for SILICON — one model across the whole pipeline,
    # decided 2026-07-17; BKS or Vashishta for silica, Munetoh-Tersoff a
    # fallback; Buckingham for ionic — DESIGN §3.3, §4.7) with TWO ZBL hard
    # cores, NOT the MLIP. The classical part does the bonding; ZBL #1
    # (longer cutoff) the projectile-substrate collision; ZBL #2 (short
    # cutoff, below the bond) a hard core on every substrate-substrate
    # pair, because the classical generators have only FINITE short-range
    # repulsion and would otherwise let cascade atoms fuse (PRIOR_ART §1.9).
    # The ZBL Z-pair channels are DERIVED from the species set (§10.3),
    # never hand-enumerated (prior art's argon-only failure).
    #
    # HEAT SINK AND BOUNDARIES — the root cause prior art tuned around:
    #   frozen_base       -> immobile bottom layer; anchors the slab so it
    #                        does not drift, and absorbs recoil (§3.3)
    #   thermostat_border -> Langevin on the lower/side region; drains
    #                        cascade heat at a PHYSICAL rate
    #   nve_interior      -> plain NVE, so the cascade stays BALLISTIC and
    #                        is never artificially quenched (prior art's
    #                        whole-slab NVT quenches the damage away)
    # These are the SLAB's OWN geometric regions (a standalone slab in
    # vacuum), DISTINCT from the pair-level LabeledGroups geometry (§3)
    # assembly emits later — activation runs before there IS a pair.
    #
    # Z-BOUNDARY is `p p f` (or shrink-wrap): sputtered atoms LEAVE rather
    # than wrap into a periodic image (§3.3) — a true free surface. The
    # newest prior-art tree dropped this AND the frozen layer, so it fails
    # to amorphize at all. The LATERAL cell is HELD FIXED, so the recorded
    # substrate strain does not relax away (same reason as §9.2). The
    # substrate is held at the target temperature between impacts (§3.3).
    return driver
```

### 10.3 derive_bombardment_spec — species-generic, dose as fluence

```
record BombardmentSpec:
    projectile_mass:  number         # from the projectile species (§3.2)
    zbl_channels:     list of Z-pair # DERIVED from the species set
    energy:           Distribution   # one frozen value in v1 (§3.2)
    angle:            Distribution   # normal incidence in v1
    impact_count:     integer        # from fluence x area, NOT a count
    impact_seeds:     list of integer  # derived from ONE master seed
    cascade_duration: number         # NVE time per impact (§10.4)
    between_impact_relaxation: number  # settle between impacts (§10.4)

function derive_bombardment_spec(slab, member_specification):
    protocol = member_specification.protocol
    ensemble = member_specification.ensemble

    # PROJECTILE is species-generic (DESIGN §3.2): argon by default, an
    # OPTIONAL co-species (iron first) co-deposited at a set fraction.
    # Mass follows from the species — nothing is hand-set per material.
    projectile_species = species_set_with_cospecies(protocol)
    species_present    = species_of(slab)

    # ZBL channels are DERIVED from substrate ∪ projectile (DESIGN §3.2),
    # so a new material or co-species needs NO code change — prior art
    # hand-enumerated Si/O/Ar and broke on anything else.
    zbl_channels = zbl_pairs_from_species(
        union(species_present, projectile_species))
    projectile_mass = mass_of(protocol.activation_species)

    # DOSE AS FLUENCE (DESIGN §3.2): the impact COUNT follows from
    # fluence x surface area, so activation is comparable across cell
    # sizes — an impact COUNT (prior art's knob) is not.
    surface_area = lateral_area(slab)
    impact_count = round(protocol.activation_fluence * surface_area)

    # A RECORDED master seed governs impact positions, velocities, and the
    # LAMMPS seeds (DESIGN §3.2) — for reproducibility (VISION goal 3) AND
    # so the bond metric can be averaged over amorphization realizations
    # by varying it (§10.8). Per-impact seeds are DERIVED from the one
    # master seed; prior art's rewrite is unseeded, so it does not
    # reproduce.
    impact_seeds = derive_seeds(ensemble.master_seed, impact_count)

    # v1 FREEZES energy/angle/pattern to single values (the protocol-knob
    # freeze), but the spec ADMITS distributions since a real beam is
    # neither monoenergetic nor unidirectional (DESIGN §3.2). Here each is
    # the degenerate one-value distribution.
    return BombardmentSpec{
        projectile_mass: projectile_mass, zbl_channels: zbl_channels,
        energy: single_value(protocol.activation_energy),
        angle:  single_value(protocol.activation_angle),
        impact_count: impact_count, impact_seeds: impact_seeds,
        cascade_duration: protocol.cascade_duration,
        between_impact_relaxation: protocol.between_impact_relaxation }
```

### 10.4 run_cascade_to_fluence — the per-impact loop

```
function run_cascade_to_fluence(driver, spec):
    # The per-impact cycle (DESIGN §3.3), run on the PERSISTENT driver so
    # there is no per-impact relaunch or disk round-trip.
    for each seed in spec.impact_seeds:
        # Insert the projectile above the surface with the spec'd velocity
        # (sampled from the energy/angle distributions; v1 = one value).
        position = sample_impact_position(driver, seed)
        velocity = sample_impact_velocity(spec.energy, spec.angle, seed)
        insert_projectile(driver, spec.projectile_mass, position, velocity)

        # NVE cascade: the collision stays ballistic in the interior while
        # the Langevin border drains the heat (§10.2). Run with an ADAPTIVE
        # timestep — it shrinks so no atom leaps THROUGH the steep ZBL wall
        # in one step — restored to the fixed step for the relaxation below
        # (an adaptive step destabilizes Nose-Hoover). `cascade_duration`
        # is SIZED FOR THE IMPACT ENERGY (a 500 eV cascade needs longer
        # than a 50 eV one), NOT a constant across energies; v1's single
        # energy fixes one value (PRIOR_ART §1.9).
        run_nve_cascade(driver, spec.cascade_duration)

        # Short border-thermostatted relaxation back toward the target
        # temperature BETWEEN impacts (DESIGN §3.3), so the next impact
        # starts from an equilibrated substrate, not a hot one.
        relax_border_thermostat(driver, spec.between_impact_relaxation)

        # Atoms sputtered THROUGH the `p p f` boundary have left; a non-
        # periodic box drops them, and here that loss is EXPECTED (a free
        # surface) — the OPPOSITE of the pull's atom-count GATE (§9.6),
        # where the box is closed and a lost atom is a failure.
    return damaged_slab_snapshot(driver)
```

### 10.5 mlip_reanneal — the SABSIM addition (`DESIGN.md` §3.4)

```
function mlip_reanneal(damaged_slab, potential, member_specification):
    # A stage prior art does NOT have (DESIGN §3.4). The classical cascade
    # MADE the disorder; now re-equilibrate GENTLY under the MLIP so the
    # final structure is MLIP/DFT-quality, not classical-quality — the
    # first rung of the fidelity ladder (DESIGN §4.5). This is where the
    # classical->accurate correction happens, and it runs BEFORE the gate
    # (§10.6), so the gate judges the accurate structure.
    #
    # It DELEGATES to §9.7's minimize_then_anneal: the SAME MLIP driver, a
    # near-equilibrium schedule. A kinetically trapped glass will not fully
    # rearrange, so "re-annealed" means "as relaxed as this schedule got
    # it" — the classical start must be a reasonable basin (STRUCTURAL 1b).
    schedule = member_specification.protocol.reanneal_schedule
    return minimize_then_anneal(damaged_slab, potential, schedule)  # §9.7
```

### 10.6 activation_gate — pass/fail with pluggable metrics (`§3.5`)

```
function activation_gate(activated_slab, crystalline_slab,
                         member_specification):
    # A GATE, not a report (DESIGN §3.5). Judgment is PER REALIZATION: each
    # metric judges ONE re-annealed slab; the seed-ensemble spread is taken
    # ABOVE this module (§10.8). Prior art only PRINTED an unthresholded
    # g(r) RMSD (PRIOR_ART §1.8). Each metric measures ONE property and
    # compares it to a reference with a real THRESHOLD; the gate is the AND.
    #
    # References + thresholds live OUTSIDE the physics spec — a threshold is
    # a criterion of the GATE, not a knob of the experiment (DESIGN §3.5) —
    # so they are looked up here, keyed by the species set.
    references = load_activation_references(
        species_of(activated_slab), member_specification)

    per_metric = empty map
    for each metric in ACTIVATION_METRICS:   # a registry, like §8 measures
        per_metric[metric.name] = metric.evaluate(
            activated_slab, crystalline_slab, references)

    # The depth metric supplies the MEASURED activated_depth that build_slab
    # only ESTIMATED a-priori (§7.4) and that §10.7 uses to label the skin.
    activated_depth = per_metric["amorphization_depth"].measured

    # PASS iff EVERY metric passes; one failure fails the gate, and the
    # reason names WHICH, so the §1 halt is diagnosable.
    passed = all(v.passed for v in per_metric.values)
    reason = "" if passed else first_failing_metric(per_metric)
    return ActivationVerdict{
        passed: passed, per_metric: per_metric,
        activated_depth: activated_depth, reason: reason }
```

```
function load_activation_references(species, member_specification):
    # References + thresholds are NOT physics-spec knobs (DESIGN §3.5). Read
    # them keyed by the species set — so a new material adds a reference
    # FILE, not code — searching an easily-locatable, version-controlled
    # `share/` directory FIRST (the small v1 STAND-INS travel with the
    # code), then the deployment SABSIM_SHARE root (large real references: a
    # DFT/exp g(r), the group's a-Si continuous-random-network model). A
    # reference a required metric needs but cannot find leaves that metric
    # UNRESOLVED, which never passes — a stand-in is explicit, never
    # silently defaulted (DESIGN §1.4 no-defaults). Each entry is tagged
    # real | stand-in so a report can say which criteria are provisional.
    return activation_reference_set   # curves + thresholds, per metric
```

The registered metrics (`ACTIVATION_METRICS`, DESIGN §3.5). Each returns
the `MetricVerdict` of §10.1 (`measured` — a scalar or a curve — plus the
`reference`, `threshold`, and `passed`). Bonds, where a metric needs them,
are taken to the first minimum of the relevant partial g(r).

```
function radial_distribution_metric.evaluate(activated, crystalline, refs):
    # One partial per species pair DERIVED from the slab (Si-only => Si-Si).
    # DENSITY-REFERENCE normalization: the reference density is the LOCAL
    # near-surface slab's, not the whole cell's, or sputtering loss inflates
    # the peaks (the sound prior-art kernel, PRIOR_ART §1.5).
    curve = { (A, B): pair_correlation(
                  activated, A, B, density=local_slab_density(activated))
              for (A, B) in species_pairs(activated) }
    # The DISCRIMINATOR is the SECOND-neighbour structure and the first
    # minimum, NOT the shared first peak. The curve is RECORDED for human
    # inspection (report-leaning, by-hand comparison); the automated pass is
    # a COARSE second-shell RMSD, so a wildly-off curve still fails.
    score = second_shell_rmsd(curve, refs.gr)
    return MetricVerdict{
        measured: curve, reference: refs.gr_name,
        threshold: refs.gr_threshold,
        passed: refs.has_gr and score <= refs.gr_threshold }
```

```
function coordination_metric.evaluate(activated, crystalline, refs):
    # The MEAN is the wrong number: amorphous silicon stays ~4-fold. Measure
    # the DISTRIBUTION and the fraction of 3- and 5-coordinated defects, PER
    # species. The reference coordination is the crystalline slab's (a
    # self-reference); the target is an amorphous defect-fraction band.
    defect_fraction = fraction_off_reference_coordination(
        activated, crystalline)
    return MetricVerdict{
        measured: defect_fraction,
        reference: "crystalline self-reference + a-Si band",
        threshold: refs.coordination_defect_band,
        passed: defect_fraction within refs.coordination_defect_band }
```

```
function ring_statistics_metric.evaluate(activated, crystalline, refs):
    # The network-topology discriminator: crystalline silicon is all
    # SIX-membered rings; the amorphous network carries FIVE- and
    # SEVEN-membered rings. Build the bond graph and enumerate rings through
    # a PLUGGABLE BACKEND (DESIGN §3.5): v1 = networkx King / shortest-path
    # rings; a purpose-built tool (Imago bond_analysis.py) may replace it
    # behind RING_BACKEND after a narrowness evaluation (standing rule).
    graph = bond_graph(activated)
    ring_histogram = RING_BACKEND.ring_size_histogram(graph)
    non_six_fraction = fraction_of_non_six_rings(ring_histogram)
    return MetricVerdict{
        measured: ring_histogram, reference: refs.ring_name,
        threshold: refs.ring_target,
        passed: non_six_fraction >= refs.ring_target }
```

```
function amorphization_depth_metric.evaluate(activated, crystalline, refs):
    # Disorder(z): bin a per-atom disorder score (the coordination defect,
    # or any registered per-atom metric) by depth. The activated depth is
    # where the profile RETURNS to the bulk baseline — measured deep in the
    # slab — scanning from the free surface DOWN over the WHOLE profile, NOT
    # stopping at the first crystalline-looking layer (prior art's 0 A bug,
    # DESIGN §3.5) nor by the Phase-1 top-contiguous scan.
    profile  = disorder_versus_depth(activated, crystalline)
    baseline = bulk_baseline(profile)             # deep, still crystalline
    depth    = depth_to_return_to_baseline(profile, baseline)
    return MetricVerdict{
        measured: depth, reference: refs.depth_name,
        threshold: refs.depth_target, passed: depth >= refs.depth_target }
```

`RING_BACKEND` is a pluggable seam (DESIGN §3.5): v1 binds it to a
`networkx` implementation of `ring_size_histogram(graph) -> {size: count}`;
the Imago `bond_analysis.py` ring tool is the candidate replacement,
evaluated for narrowness before adoption. Swapping it changes no metric.

### 10.7 label_activated_skin — record what the cascade amorphized

```
function label_activated_skin(slab, activated_depth):
    # The cascade CHANGED which atoms are amorphous; record it. The
    # activated_skin (LabeledGroups, §3) is the set of atoms shallower than
    # the MEASURED amorphization depth (§10.6), NOT an a-priori guess.
    # Assembly (§7.5) records the pair-level zone GEOMETRY (z-ranges), but
    # the activated_skin is the ONE labeled group that is a measured atom
    # set — step 6's press carries and tracks THIS set (§9.3), never
    # re-carving it from depth. Written here so it is not recomputed later.
    slab.labeled_groups.activated_skin =
        atoms_shallower_than(slab, activated_depth)
    return slab
```

### 10.8 What bottoms out, what delegates

`[BOTTOMS OUT here]` the persistent cascade driver — hybrid/overlay ZBL
splice, frozen-base / Langevin-border / NVE-interior heat sink, and the
`p p f` boundary (§10.2); the species-generic spec derivation — fluence
-> count, ZBL channels from the species set, seed derivation (§10.3); the
per-impact insert/cascade/relax loop (§10.4); the gate's pluggable
species-derived metrics and their AND (§10.6); and the activated-skin
labeling (§10.7). Each is a LAMMPS-driver operation or a metric plus a
threshold.

`[DELEGATE -> §9.7]` the MLIP re-anneal (§10.5) reuses
`minimize_then_anneal` — the same MLIP driver, a near-equilibrium
schedule. Activation AUTHORED the disorder; §9.7 relaxes it.

`[DELEGATE -> POTENTIAL, DESIGN §4]` the classical generator
(BKS/Vashishta/Munetoh-Tersoff/Buckingham, config-selected via the §4.7
generator seam — selection, acceptance, and fallback) and the MLIP
committee (step 2) are §4 concerns; this module CONSUMES both, never
authors them.

`[ABOVE this module]` the ensemble (STRUCTURAL 4: averaging the bond
metric over amorphization realizations, `DESIGN.md` §3.2) is looped by the
sequencer via `realization_count` (§2), varying the master seed; this
module runs ONE realization. Same division of labor as §9.8.

`[CODE level, below pseudocode]` the exact LAMMPS fix syntax, the ring-
statistics algorithm (likely an adopted library, `VISION.md` principle 2),
and the g(r)/coordination kernels — some of which are the good prior-art
kernels to KEEP (the density-reference normalization, DESIGN §3.6).

`[DESIGN §3.6 / numeric follow-ons]` the FROZEN v1 values — the single
fluence, energy, and normal incidence; the cascade duration and between-
impact relaxation; the re-anneal schedule; and every gate THRESHOLD with
its DFT/experimental reference DATA. Their existence is pinned here; the
numbers and the reference curves are a DESIGN task.

---

## 11. Bootstrap — manufacturing the potential (steps 1, 2)

This is the **fifth and last depth-first module pass**
(`ARCHITECTURE.md` §5.4), on `DESIGN.md` §4 (especially §4.5). It is the
one buildable unit (`ARCHITECTURE.md` §5.2) that had no pass until now:
the process that MANUFACTURES the machine-learned potential every member
consumes. The earlier "all modules at depth" was really FOUR — this
closes the count to five.

**It is orchestration, not new physics.** Almost every DOING step here
is adopted (`VISION.md` principle 2): the training task and the ensemble
loader are the two ALF contracts (`DESIGN.md` §4.2), the HDF5<->DeePMD
bridge is the unit-tested converter (§4.3), the committee-uncertainty
and UDD math live in ALF's `MLMD_calculator` (§4.4), and the labels come
from VASP. What is OURS is the LOOP that wires them and, above all, the
config GENERATION (§11.3), which REUSES the activation (§10) and
bond/debond (§9) stages already written — run to HARVEST the
configurations they visit, not to produce a measurement. So this pass is
short and mostly delegates; §11.7 is a long ledger for that reason.

**It sits ABOVE `exec_one_member`.** The bootstrap runs ONCE per
material pair (the species union, STRUCTURAL 1a) and emits ONE
fingerprinted potential that many members then look up by `potential_ref`
(§1, `DESIGN.md` §1.6). So it is a top-level process alongside
`exec_full_study` (§1), NOT a stage inside the per-member pipeline —
which is exactly why §1's `resolve_potential` is a LOOKUP, not a call
that trains.

**The circularity it resolves.** Steps 4/6/7 run MD *on* the potential,
but the configurations they visit are what the potential must be trained
on (`DESIGN.md` §4.5). The builder also consumes the potential's relaxed
lattice constants (§7.2) while the potential must be trained on the
builder's strained substrates (STRUCTURAL 4) — a TWO-WAY coupling, which
is why this is a LOOP and not a straight line.

### 11.1 The module's top-level shape

The loop is seed -> generate -> label -> retrain -> refine, repeated
until the potential passes BOTH convergence tests (§11.6). This is one
pass of the OUTER loop (`VISION.md` principle 5), run by hand in v1: the
inner refine-loop iterates, but re-entry for MORE pairs or study-driven
weaknesses is manual.

**The INPUT record, which every function below threads.** This object
was passed through twelve call sites under the name
`pair_specification` and defined nowhere; `DESIGN.md` §4.8 designs it and
this is its shape. The name changed with the definition, because the old
one was wrong twice: it is keyed by a species UNION and a DOMAIN rather
than by a pair, and it is a manufacturing RECIPE rather than a
description. It is the third input file of the project, alongside the
study specification (§2) and the deployment configuration, and it
changes on a third clock: manufactured once, costing weeks, then
consumed unchanged by many members.

```
record ReferenceSettings:
    # DESIGN §4.8 parts 3-4. The numerical controls of ONE accurate
    # calculation. TWO instances live in a recipe and they are not
    # interchangeable — see the two fields on ForceModelRecipe below.
    basis_cutoff:          Quantity   # how finely wavefunctions resolve
    reciprocal_spacing:    Quantity   # a SPACING, never a fixed mesh:
                                      # one block must serve a few-atom
                                      # bulk cell AND a §6.4 subcell, and
                                      # only a spacing scales to both
    exchange_correlation:  string     # the approximation used
    occupancy_smearing:    Quantity   # partial-occupancy broadening
    electronic_tolerance:  Quantity   # electronic convergence limit
    geometric_tolerance:   Quantity   # force/geometry convergence limit
    audited:               boolean    # has the part-4 audit actually been
                                      # run against these values, or are
                                      # they a plausible guess? Same idiom
                                      # as the registry's `validated` and
                                      # the reference file's `real` — a
                                      # recipe may be unaudited, but what
                                      # it makes is then EXPLORATORY
    # [DEPTH-FIRST] every value above is a placeholder until the first
    # audit runs (DESIGN §4.8 "Frozen for v1"); the FIELDS are fixed here
    # because a value the manufacture uses must be visible (§1.4).

record StartingCollection:
    # DESIGN §4.8 part 2. The calm structures computed before anything
    # else. Its purpose is stated out loud because it is easy to
    # over-invest: it exists so the seed committee does not fly apart,
    # NOT to make it accurate.
    bulk_phases:        list of PhaseSpec   # every phase in the domain
    clean_surfaces:     list of SurfaceSpec # their cut faces
    strained_substrates: list of StrainSpec # STRUCTURAL 4's shared-cell
                                            # stretch (a special case of
                                            # the deformations below)
    rattled_snapshots:  RattleSpec          # moderate-temperature shake
    deformations:       list of StrainSpec  # uniform tension, compression
                                            # and shear on each bulk
                                            # phase, carried PAST the
                                            # reversible range. Two
                                            # reasons this is not
                                            # optional: the §7.2 gate
                                            # already checks elastic
                                            # stiffness, so a model never
                                            # shown a deformed cell would
                                            # be gated on a property it
                                            # was not taught; and the
                                            # protocol IS a deformation
                                            # experiment whose pull can
                                            # fail through the CRYSTAL
                                            # rather than the interface,
                                            # an outcome §8 must tell
                                            # apart from the other

record ForceModelRecipe:
    # DESIGN §4.8, all eight parts. What to manufacture, and how the
    # result is judged.

    # --- Part 1: the key. What this model covers. ---
    species_union:  set of string   # STRUCTURAL 1a; fixes the §4.3 global
                                    # type map every member inherits
    domain:         string          # the structural/chemical REGIME. The
                                    # species alone cannot identify a
                                    # model: one composition spans
                                    # different chemistries (carbon as
                                    # diamond or graphite; silica from
                                    # alpha-quartz to an amorphous
                                    # network). A member's material_domain
                                    # (§2) must lie INSIDE this one —
                                    # containment, not equality, since a
                                    # silicon-and-silica recipe covers a
                                    # silica-only member.

    # --- Part 2: what is computed first. ---
    starting_collection: StartingCollection

    # --- Parts 3-4: the two settings blocks, and why there are two. ---
    # Three consumers of an accurate number are DIFFERENCES against the
    # model (§2.2's lattice, §7.2's stiffness and surface energies,
    # §6.4's interface_fidelity), and each stacks two errors. LEARNING
    # error is how faithfully the fit absorbed the method it was trained
    # on; METHOD error is how far that method sits from reality, which no
    # extra training data removes. Inherit everywhere and the gate reads
    # learning error cleanly but is BLIND to method error; tighten the
    # references alone and the two mix with no way to separate them. So
    # both are declared, and a reader can add them.
    production_settings: ReferenceSettings   # the labels AND every
                                             # reference differenced
                                             # against the model
    audit_settings:      ReferenceSettings   # tightened, run ONCE on a
                                             # handful of small cells at
                                             # recipe-creation time
    audit_offset:        MeasureVector       # how far production sits
                                             # from audit — a REPORTED
                                             # quantity, not a footnote

    # --- Part 5: how the hard configurations are made (§11.3). ---
    generation_plan: GenerationPlan  # which stages run to harvest, on
                                     # WHICH force model each runs (the
                                     # cascade on the §4.7 classical form,
                                     # the press/pull on the current
                                     # committee), how many, and at what
                                     # conditions

    # --- Part 6: what gets the expensive labels (§11.4). ---
    labeling_budget: int             # accurate calls per round; VASP is
                                     # the cost bottleneck
    labeling_rule:   SelectionRule   # favour the interface, prefer high
                                     # committee spread, skip near-
                                     # duplicates, frame interface configs
                                     # as §6.4 subcells

    # --- Part 7: the learning loop (§4.4, §4.6). ---
    committee_size:    int           # independently-trained members
    descriptor:        DescriptorSpec  # form and cutoff radius
    training_schedule: TrainingSpec  # length; energy-vs-force loss balance
    capture_cutoffs:   (Quantity, Quantity)   # Escut, Fscut
    bias_weight:       Quantity      # the UDD push up the uncertainty
                                     # gradient

    # --- Part 8: when to stop, and what the result is called. ---
    uncertainty_threshold: Quantity  # test 1 of §11.6, WITH a number: a
                                     # stopping rule phrased as "below
                                     # threshold" with no threshold is not
                                     # a stopping rule
    quality_tolerances:    map of string -> Quantity  # test 2's limits
    reference_data_ref:    string    # POINTS AT the reference set (§3.5),
                                     # never contains it: those values
                                     # include laboratory measurements no
                                     # recipe should own, and one set may
                                     # serve several recipes. Recorded so
                                     # the pairing is recoverable later.
    # The name is COMPUTED, not stated — see fingerprint_of below — so a
    # changed recipe cannot pass itself off as the model validated last
    # month.
```

**Validation, mirroring §2's three phases.** A recipe is rejected if any
field is absent (§1.4's no-hidden-defaults applies here exactly as it
does to a study), if `domain` names a regime no registry entry covers,
if `species_union` disagrees with the phases listed in the starting
collection, or if `production_settings.audited` is false without the
run having declared itself exploratory. The third phase — does every
REFERENCED artifact actually exist — is built on the study side
(`spec/references.py`) and this recipe's version reuses it: the
`reference_data_ref` must resolve, and every phase named in the starting
collection must have a crystal file that opens.

```
record BootstrapResult:
    # What the bootstrap emits and §1's resolve_potential later looks up.
    potential:   PotentialHandle    # loadable pair_style deepmd committee
    fingerprint: string             # content id (§1.6) = a potential_ref
    convergence: ConvergenceReport  # the two tests of §11.6, for provenance
    provenance:  Provenance         # seed set, VASP subset, ALF rounds, seeds
    recipe:      ForceModelRecipe   # the recipe that produced it, carried
                                    # so the product records what made it
```

```
function bootstrap_potential(force_model_recipe, reference_data):
    # STEP 1 (seed): a committee that just does not explode near
    # equilibrium; its only job is to survive step-2 generation (§11.2).
    committee = seed_committee(force_model_recipe, reference_data)   # §11.2
    store = new_training_store(reference_data)   # ANI-style HDF5 (§4.3),
                                                 # primed with the seed labels

    # STEP 2 (generate the hard configs cheaply, ONCE): the violent cascade
    # on the classical+ZBL potential (no MLIP), the interface/separation on
    # the seed committee — the configurations the potential must cover but a
    # near-equilibrium seed has never seen (§11.3).
    configs = generate_hard_configs(committee, force_model_recipe)   # §11.3

    # STEP 3 (label, convert, retrain): VASP labels a selected subset, the
    # converter folds it into the store, ALF retrains -> the first committee
    # that has actually SEEN the hard region (§11.4).
    committee = label_convert_retrain(configs, store,
                                      force_model_recipe)            # §11.4

    # STEP 4 (refine by sampling): re-run the protocol under the committee;
    # the sampler flags where it is STILL uncertain; VASP labels those;
    # retrain; repeat until BOTH convergence tests pass (§11.6). v1 iterates
    # THIS loop; the outer re-entry stays by hand (VISION principle 5).
    converged = false
    while not converged:
        (committee, converged, report) = refine_by_sampling(
            committee, store, force_model_recipe)          # §11.5, §11.6

    return BootstrapResult{
        potential:   freeze(committee),
        fingerprint: fingerprint_of(committee, store),
        convergence: report,
        provenance:  provenance_of(store) }
```

### 11.2 seed_committee — enough not to explode near equilibrium

```
function seed_committee(force_model_recipe, reference_data):
    # DESIGN §4.5 step 1. Train an INITIAL committee on hand-built near-
    # equilibrium DFT: bulk Si and cristobalite, their surfaces, the
    # STRUCTURAL-4 strained substrates, and moderate-T rattled snapshots.
    # The bar is LOW on purpose — "does not fly apart near equilibrium",
    # not "accurate" — because its only job is to run step-2 generation
    # long enough to REACH the hard configs (§11.3). The strained-substrate
    # entries are here because the builder (§7.2) will demand exactly them.
    #
    # DELEGATES to ALF contract 1 (train_DEEPMD_ensemble_task, §4.2):
    # n_models potentials from different seeds (§4.4). We supply the seed
    # SET; ALF does the training.
    seed_set = assemble_seed_set(force_model_recipe, reference_data)
    return train_committee(seed_set)      # [DELEGATE -> ALF, §4.2]
```

### 11.3 generate_hard_configs — reuse §9/§10 in "generate" mode

The one genuinely OURS step, and the one worth stating carefully: the
bootstrap has NO cascade and NO MD of its own. It RUNS the activation
(§10) and bond/debond (§9) stages and HARVESTS the configurations they
visit. "Generate mode" is a CONSUMER difference, not a stage fork:
production reads the verdict and measures off these stages; the bootstrap
reads their trajectory FRAMES as unlabeled training candidates. The
stages themselves are unchanged — the same code, read two ways.

```
function generate_hard_configs(committee, force_model_recipe):
    # DESIGN §4.5 step 2. Two config families, from the two stages; in
    # BOTH the gate verdict is INFORMATIONAL, never halting — a "failed"
    # activation is a valuable hard config to LABEL, not a pipeline stop
    # (the §1 halt is a PRODUCTION rule, not a generation one).
    candidates = empty list

    # (a) Amorphized-surface configs. Inside activation the cascade ITSELF
    # always runs on the classical+ZBL potential (§10.2), in production and
    # here alike; the committee enters only via the gentle re-anneal
    # (§10.5). So the MLIP is never asked to reproduce a cascade (§3.3).
    (handle_A, handle_B, shared) = build_slabs(force_model_recipe,
                                               committee,
                                               scratch_directory)
    activated = activate_surfaces(handle_A, handle_B, force_model_recipe,
                                  committee)                        # §10
    candidates.extend(harvest_frames(activated))

    # (b) Pressed-interface and bond-breaking configs. These run on the
    # COMMITTEE (§9) — the very region the potential must get right, so its
    # own trajectory is where the training signal is richest.
    structure = assemble_pair(activated.slab_A, activated.slab_B,
                              shared, force_model_recipe)           # §7.5
    bond_debond = run_bond_debond_md(structure, committee,
                                     force_model_recipe)            # §9
    candidates.extend(harvest_frames(bond_debond))

    return candidates
```

### 11.4 label_convert_retrain — VASP truth, then ALF retrains

```
function label_convert_retrain(candidates, store, force_model_recipe):
    # DESIGN §4.5 step 3. The DOING is all adopted; ours is only the
    # SELECTION of what to label and the interface-subcell framing.
    #
    # Pick a SUBSET to label — VASP is the cost bottleneck. Interface
    # configs are labeled as INTERFACE SUBCELLS (§6.4), not whole
    # production cells: the potential is short-ranged so the signal is
    # local, and all-electron cost climbs steeply with atom count. A
    # TRAINING config need only be valid and relevant, which frees the
    # subcell choice — unlike the §7.3 cross-check, which must fix the
    # system across two methods (DESIGN §4.5's stated asymmetry).
    subset = select_for_labeling(candidates, force_model_recipe)

    labels = vasp_label(subset)        # [DELEGATE -> VASP, ALF QM_task]
    absorb_converted(store, labels)    # [DELEGATE -> converter, §4.3]
    return train_committee(store)      # [DELEGATE -> ALF contract 1, §4.2]
```

### 11.5 refine_by_sampling — chase the potential's own uncertainty

```
function refine_by_sampling(committee, store, force_model_recipe):
    # DESIGN §4.5 step 4. Re-run the protocol under the CURRENT committee
    # and let it TELL us where it is still ignorant, instead of guessing.
    # Two sampler modes, both from ALF's MLMD_calculator (§4.4), both
    # potential-agnostic:
    #   - uncertainty-triggered capture: grab a frame when sigma_E or
    #     sigma_F exceeds Escut/Fscut (what it is ALREADY unsure about);
    #   - UDD bias: add E_bias = w * sigma_E so the dynamics climb the
    #     uncertainty gradient INTO weak regions (Kulichenko 2023).
    # A run the §7.3 live monitor ABORTS is not wasted: it feeds exactly
    # here, and the bounded UDD excursion from its triggering config is the
    # most targeted sampler we have (DESIGN §4.5, §7.3).
    flagged = resample_high_uncertainty(committee,
                                        force_model_recipe)     # §4.4
    committee = label_convert_retrain(flagged, store,
                                      force_model_recipe)       # §11.4 again
    (converged, report) = test_convergence(committee, store,
                                           force_model_recipe)  # §11.6
    return (committee, converged, report)
```

### 11.6 test_convergence — the ACTING form of the §5 gate

This is the section the §1 marker points at. Convergence is TWO tests
together (`DESIGN.md` §4.5), and the second IS the potential-quality gate
of §5 — but here it ACTS, because the potential is still mutable: a fail
does not report, it sends the loop back to §11.5 for more data. The SAME
gate, downstream in §5, can only report, because by then the potential is
frozen. That is the whole resolution of the `/refine` sequencing finding:
DESIGN §7.2's "gate the build, before the builder" is discharged HERE,
upstream, where acting is possible.

```
record ConvergenceReport:
    committee_uncertainty: MetricVerdict            # sigma over run vs cut
    quality_gate:          PotentialQualityVerdict  # the §5 gate, run to ACT
    passed:                boolean

function test_convergence(committee, store, force_model_recipe):
    # Both tests read ONE full protocol run under the current committee
    # (activation §10 + press/pull §9), so run it once, measure two ways.
    run = run_protocol_under(committee, force_model_recipe)   # §9, §10

    # Test 1 — committee SPREAD across that run is below threshold: the
    # potential is confident everywhere the protocol goes (§4.4).
    uncertainty = committee_spread(run)
    below = uncertainty.measured <= uncertainty.threshold

    # Test 2 — THE §5 potential-quality gate: call the SAME shared
    # potential_quality_gate function evaluate_member_gates (§5) calls, but
    # ACT on its `.passes` to drive the loop, where §5 only reads it. That
    # one shared object is what makes the §1 marker's "acts here, reports
    # there" literally true. The bulk/surface half folds in §3.5's
    # amorphous-structure validation (STRUCTURAL 3, DESIGN §4.5's hand-off).
    measures = analyze_run(run, force_model_recipe)          # §8
    quality  = potential_quality_gate(committee, measures)   # [-> §5]

    passed = below and quality.passes
    return (passed, ConvergenceReport{
        committee_uncertainty: uncertainty,
        quality_gate: quality, passed: passed })
```

### 11.7 What bottoms out, what delegates

`[OURS, bottoms out here]` the RECIPE record and its validation (§11.1 —
what a force model must state before anyone spends weeks making one);
the LOOP structure (§11.1); the seed-set COMPOSITION (§11.2 — which
structures to hand ALF); the "generate mode" frame-harvesting that
reuses §9/§10 (§11.3); the label-SUBSET selection and the
interface-subcell framing (§11.4); and the TWO-test convergence with the
gate run to ACT (§11.6). These are our orchestration decisions.

The recipe deserves a word about WHY it is ours rather than adopted.
Every DOING step it configures is someone else's — ALF trains, VASP
labels, DeePMD fits. But nothing in those tools records what a model was
supposed to cover, which settings its comparisons must inherit, or when
it is finished. Those are the judgments that make a number traceable
(`VISION.md` goal 3), and they have no home inside a black box we have
committed to not looking into (§4.1).

`[DELEGATE -> §9, §10, §7]` all config GENERATION runs the already-
written activation (§10), bond/debond (§9), and structure (§7) stages
UNCHANGED; the bootstrap only harvests their frames. No stage forks for
this — the "generate" reading is a consumer choice (§11.3).

`[DELEGATE -> ALF/DeePMD/VASP, DESIGN §4.2-§4.4]` training
(`train_DEEPMD_ensemble_task`), the ensemble loader, the HDF5<->DeePMD
converter, the committee sigma and the UDD bias, and VASP labeling are
ADOPTED (`VISION.md` principle 2) — driven by config, never authored
here. The prototype at `prototypes/alf_deepmd/` already implements and
unit-tests the two ALF contracts and the converter round-trip.

`[DELEGATE -> §5]` the acting convergence gate (§11.6) calls the SAME
shared `potential_quality_gate` function §5's `evaluate_member_gates`
calls; only its CONSEQUENCE differs — act versus report.

`[ABOVE this module]` re-entry — more material pairs, or new training
targeted at a study's gate weaknesses (§1's commented outer loop) — is by
hand in v1 (`VISION.md` principle 5). This module manufactures ONE
potential per invocation.

`[DESIGN §4.6 / numeric follow-ons]` the FROZEN v1 values — descriptor
`se_e2_a` and r_cut 6.0 A, `n_models` 4, the loss schedule, `Escut` /
`Fscut`, the UDD weight `E_en_bias_weight`, the committee-sigma
convergence threshold, and the seed-set composition — are pinned as
EXISTING here; the numbers themselves are a DESIGN task (the STRUCTURAL
1b/3 follow-ons).

## 12. Step-8 characterization — algorithms (step 8)

This is the SIXTH module pass, on `DESIGN.md` §8. It closes the
DESIGN->PSEUDOCODE boundary: the one buildable unit
(`ARCHITECTURE.md` §5.2) whose depth pass was left for last — marked
`[DEPTH-FIRST]` in §1 and mocked in §6. It is written now because the
design is settled, so this is transcription, not speculation.

**It designs a SEAM, not a module SABSIM runs.** Imago (the all-electron
code) and Kaleidoscope (its batch manager) are sibling projects, not
ours (`DESIGN.md` §8). SABSIM owns FOUR artifacts on its side: a
SELECTOR (which frames earn the expense, §12.2), a SKELETON PREPARER (a
structure -> an input Imago accepts, §12.3), a MANIFEST (the whole
conversation with Kaleidoscope, §12.4), and a HARVESTER (results -> §6.6
records, §12.5). `DESIGN.md` §8.8 is emphatic that all four are PURE
FUNCTIONS testable to completion with no Imago present. Only EXECUTION
waits.

**Two consumers, opposite demands (`DESIGN.md` §8.1).** M4 (all-electron
work of adhesion) wants exactly TWO relaxed, 0 K, commensurable
endpoints; M5's electronic family wants a consistent finite-T UNRELAXED
frame SERIES at the chemically-eventful moments. One structure
convention and one dispatch path serve both — but never as one job.

**What genuinely waits on Imago** is narrow, and `[DEPTH-FIRST]` where it
lands: the EXACT input file-layout / command-sequence (§12.3 — the
FORMAT is inherited from OLCAO, but the tweaks are still being finalized
in the in-development Imago) and Imago's FAILURE TAXONOMY (§12.5).
Everything else is OURS and bottoms out here.

### 12.1 The module's top-level shape

```
record AnalysisUnit:
    # One Imago calculation, self-describing (`DESIGN.md` §8.5).
    skeleton:   SkeletonDir    # a self-contained input dir (§12.3)
    identifier: string         # CONTENT fingerprint of the skeleton (§1.4)
    consumer:   one of {m4_endpoint, m5_frame}    # which measure it feeds
    detector:   DetectorClass or none   # for an m5_frame, which detector
                                        # found it; none for an m4 endpoint
    provenance: Provenance     # member, trajectory, frame index, subcell,
                               # potential generation, seed set (§8.5)

record Manifest:
    # The WHOLE interface to Kaleidoscope (`DESIGN.md` §8.5): one list,
    # handed over, waited on. Retained as step 8's provenance record.
    units: list of AnalysisUnit

function run_characterization(structure, bond_debond_trajectory,
                              member_specification):
    # DESIGN §8. Turn a finished press/pull into the all-electron and
    # descriptor measures, or into schema-valid `unresolved` records when
    # the subcell is unaffordable (§8.2) or Imago is late (§8.8). Returns
    # a MeasureVector (the §4 contract); §1 merges it with the analyzer's.

    # ONE structure convention: §6.4's interface subcell, extracted ONCE
    # at §5.3's reference state, frozen by atom identity (§8.2). If it
    # exceeds the affordable envelope, step 8 cannot run for this pair
    # without breaking a §6.4 rule — SAY SO, do not break one quietly.
    subcell = extract_interface_subcell(
        structure, member_specification)     # [DELEGATE -> §6.4 / §8.2]
    if not subcell.affordable:
        return all_unresolved(
            "interface subcell exceeds the step-8 envelope (§8.2)")

    # SELECT the frames worth the expense (§12.2). The two relaxed M4
    # endpoints are NOT detected — they are computed states from §5, and
    # they enter the batch unconditionally (§8.3).
    frames    = select_frames(bond_debond_trajectory, subcell,
                              member_specification)          # §12.2
    endpoints = relaxed_endpoints(bond_debond_trajectory,
                              subcell)   # [DELEGATE -> §5 / §8 M2 relax]

    # PREPARE a skeleton per unit (§12.3), BUILD the manifest (§12.4),
    # DISPATCH the batch and wait (§12.5).
    units = ([make_unit(e, m4_endpoint, none) for e in endpoints]
           + [make_unit(f.structure, m5_frame, f.detector)
              for f in frames])
    manifest = build_manifest(units)                         # §12.4
    results  = dispatch_batch(manifest)  # [DELEGATE -> Kaleidoscope, §8.5;
                                         # EXECUTION waits on Imago, §8.8]

    # HARVEST into §6.6 records, reporting coverage BY DETECTOR CLASS
    # because all-electron runs fail on the hard frames, not at random.
    return harvest(manifest, results, member_specification)  # §12.5
```

### 12.2 select_frames — three detectors, on the subcell, merged by event

```
function select_frames(trajectory, subcell, member_specification):
    # DESIGN §8.3. The genuinely OURS piece, and a PURE, DETERMINISTIC
    # function of the trajectory and the settings — re-runnable, auditable
    # long after the MD is gone, part of provenance (§1.6). Three
    # detectors, each a physically meaningful moment:
    #   - PE local MINIMA in the hold -> a bond forming, shedding energy
    #   - PE local MAXIMA in the pull -> a bond stretched to its limit
    #   - sharp DROPS in sigma_zz     -> a bond breaking, shedding load
    numerical = member_specification.numerical

    # FIX 1 — measure where the event IS. Read per-atom PE and virial
    # summed over the FROZEN SUBCELL SET alone, stress from the subcell's
    # own volume; the whole cell's thermal noise dwarfs one bond (§8.3).
    signal = subcell_series(trajectory, subcell)

    candidates = empty list
    for detector in {hold_minima, pull_maxima, stress_drops}:
        # FIX 2 — a local extremum of a noisy series is not an event.
        # Smooth over a few vibrational periods, then require PROMINENCE
        # above the §5.4 noise floor; without it every thermal wiggle
        # reads as a bond (§8.3).
        extrema = detect_extrema(
            signal, detector,
            window = numerical.detector_smoothing_window)
        for candidate in extrema:
            if prominence(candidate, signal) >= (
                    numerical.detector_prominence):
                candidates.append(tag(candidate, detector))

    # FIX 3 — merge by EVENT, not geometry. Two frames are one when their
    # CROSS-INTERFACE BOND SETS are identical (cutoffs §6.3, bonds by
    # PROVENANCE not species §6.2) and their subcell energies differ by
    # less than the noise floor. An RMSD criterion merges across a break
    # and keeps phonon-only pairs — backwards both ways (§8.3).
    merged = merge_by_event(candidates, subcell,
                            tolerance = numerical.noise_floor)

    # RANK by prominence, TRUNCATE to the budget, LOG the drops — a silent
    # truncation reads downstream as full coverage (§8.3). The budget is a
    # §1.2 numerical knob: raise it and the trend must stop moving.
    kept = rank_and_truncate(merged, budget = numerical.frame_budget)
    log_dropped(dropped = merged - kept)
    return kept
```

### 12.3 prepare_skeleton — a self-contained input, pure by construction

```
function prepare_skeleton(structure, settings):
    # DESIGN §8.4. A SKELETON is a self-contained directory whose ENTIRE
    # content is a function of explicit arguments: no clock, no working
    # directory, no environment. That is §1's inversion restated at the
    # seam, and what makes this testable by EXACT comparison against a
    # known-good input with NO Imago present (closing the last STRUCTURAL
    # 2 follow-on). It must NOT read the `$OLCAO_RC` working-dir-as-config
    # convention prior art carried (§8.4).
    #
    # ASE is the MEMBRANE, not the vocabulary (VISION principle 4): ASE
    # carries species / positions / cell across the boundary; the basis,
    # sampling, and command sequence are Imago's OWN vocabulary and do not
    # pass through ASE's (which would flatten them, §8.4).
    atoms = ase_atoms_of(structure)          # [DELEGATE -> ASE membrane]

    # Two inherited physics choices, frozen for v1 (§8.4):
    basis      = FULL         # the bond redistributes charge BETWEEN
                              # atoms, so small near-eq sets misfit here
    k_sampling = GAMMA_ONLY   # primary reason is CELL SIZE (large real
                              # cell -> small reciprocal cell); a §1.2
                              # numerical setting, checked once vs a
                              # denser mesh (§8.4)

    # [DEPTH-FIRST] the EXACT file layout and command sequence. The FORMAT
    # is inherited from legacy OLCAO with only layout / command tweaks
    # (§8.4). The known-good reference input EXISTS NOW — from the
    # validated four-structure campaign (§8.4, §8.8) — so this preparer is
    # testable to COMPLETION against it today; what stays open is only the
    # residual Imago-vs-OLCAO tweaks (§8.9), pinned when the in-development
    # Imago finalizes them. Everything ABOVE this line is fixed now.
    return emit_imago_skeleton(atoms, basis, k_sampling, settings)
```

### 12.4 build_manifest — content-fingerprint identifiers

```
function build_manifest(units):
    # DESIGN §8.5. Each unit's IDENTIFIER is a CONTENT FINGERPRINT of its
    # skeleton, reusing §1.4's rule, not a second one: identical content
    # -> identical id, so Kaleidoscope's cache is correct by construction;
    # any change -> a new id, so a stale result is never served for a
    # structure that no longer exists. A frame-number / directory /
    # timestamp id COLLIDES across members — prior art's newest-file-wins
    # failure (§5.7) in new clothes.
    for unit in units:
        unit.identifier = content_fingerprint(unit.skeleton)   # [-> §1.4]
    return Manifest{ units: units }       # kept as step 8's provenance
```

### 12.5 dispatch and harvest — coverage by class, failures not random

```
function dispatch_batch(manifest):
    # DESIGN §8.5. Hand Kaleidoscope ONE manifest and wait; the outer
    # sequencer treats the batch as a single opaque step (no Parsl in
    # Parsl, §4.1). Kaleidoscope owns DISPATCH, CACHING, and success /
    # failure TRACKING — NOT what a snapshot means, which measure it
    # feeds, or whether the batch sufficed (those stay here, §8.5).
    #
    # [DELEGATE -> Kaleidoscope]; EXECUTION waits on Imago (§8.8). Until
    # it lands, M4 falls back to VASP ON THE SAME SUBCELL (§6.4) and M5's
    # electronic family is `unresolved`; the gate still runs. Waiting is a
    # CONFIGURATION, not a degradation (§6.7).
    return kaleidoscope_run(manifest)

function harvest(manifest, results, member_specification):
    # DESIGN §8.6. Read results BY the manifest — never a results-dir
    # scan, never newest-file-wins (§5.7). Two channels: ASE-vocabulary
    # quantities (energy, forces) cross through ASE; Imago's own outputs
    # (effective charge, bond order, total / partial DOS §6.4) ride the
    # native channel, parsed here. DOS / pDOS are kept as human-read CURVE
    # artifacts; only `dos_at_fermi` and `gap_size` reduce to §6.6.

    # M4 is ALL-OR-NOTHING: a difference of two endpoint energies, so if
    # EITHER endpoint failed, `interface_fidelity` is `unresolved` — never
    # one all-electron endpoint against one MLIP stand-in, which would
    # measure the very thing the difference tests. Still gated by
    # `subcell_truncation_error` (§6.4): the cheap method certifies the
    # expensive method's input, whichever it is.
    m4 = form_m4_difference(results, manifest)   # [-> §8.7 (analyzer M4)]

    # M5 survives a missing FRAME (smaller realization_count, frames
    # named) but NOT a missing CLASS: all-electron runs fail on the HARD,
    # signal-carrying frames (max stretch, the break), so averaging the
    # survivors reports the easy physics as a trend. Report COVERAGE BY
    # DETECTOR CLASS; empty a class and its trend is `unresolved` even if
    # most of the batch succeeded (§8.6).
    m5 = form_m5_by_class(results, manifest)     # [-> §8.8 (descriptors)]

    # [DEPTH-FIRST] Imago's FAILURE TAXONOMY — which failures are RETRYABLE
    # (dispatch, non-convergence) vs STRUCTURAL (the basis cannot fit this
    # geometry). §8.6's coverage-by-class needs the distinction to know if
    # an emptied class is recoverable; the taxonomy comes from the
    # in-development Imago. Until pinned, treat every failure as terminal
    # for its unit — the safe reading never over-reports coverage.

    # Every harvested value is a §6.6 record: uncertainty over its frames,
    # realization_count, units, fidelity (all-electron | electronic),
    # method (Imago + version), status. NO bare numbers, NO verdicts here
    # — §7's gate reads the records (§8.6, §8.7).
    return assemble_measures(m4, m5)      # a MeasureVector (§4 contract)
```

### 12.6 What bottoms out, what delegates

`[OURS, bottoms out here]` the four-artifact SEAM shape (§12.1); the
three-detector SELECTION with subcell scope, prominence bar, and
merge-by-event (§12.2); the SELF-CONTAINED skeleton discipline, pure of
clock / cwd / env (§12.3); the CONTENT-FINGERPRINT manifest (§12.4); and
the COVERAGE-BY-CLASS harvest with M4 all-or-nothing, M5
holes-not-classes (§12.5). All buildable and testable with no Imago
(`DESIGN.md` §8.8), against the validated four-structure campaign.

`[DELEGATE -> §6.4 / §5 / §8]` the interface SUBCELL is §6.4's (§8.2);
the relaxed M4 ENDPOINTS come from §5 / the §8 M2 relax; the M4
DIFFERENCE and M5 DESCRIPTOR reductions are the analyzer's §8.7-§8.8.
Characterization SELECTS, PREPARES, and HARVESTS; it does not redefine a
measure.

`[DELEGATE -> Kaleidoscope, DESIGN §8.5]` dispatch, caching, and
success / failure tracking; meaning, measure-routing, and sufficiency
stay here. The batch is one opaque step (§4.1).

`[DEPTH-FIRST]` two narrow spots wait on the in-development Imago: the
EXACT input file-layout / command-sequence (§12.3) and Imago's FAILURE
TAXONOMY (§12.5). Everything else is fixed — the honest boundary of
"finish the pseudocode" before Imago exists.

`[ABOVE this module]` step-8 EXECUTION is Wave 4 (`ARCHITECTURE.md`
§5.3): the four artifacts are fixture-tested now; they connect to real
Imago when it lands, with the VASP subcell backstop carrying M4 until
then.

`[DESIGN §8.9 / numeric follow-ons]` the detector smoothing window and
prominence, the frame budget and its adequacy refinement, the merge
tolerance, and the one-time denser-mesh Γ check are DECLARED here (the
three new NumericalKnobs in §2) with their VALUES left as DESIGN tasks.

## 13. Resuming an interrupted run — algorithms (`DESIGN.md` §11)

This is the resume mechanism DESIGN §11 designed and §10.6 leans on: how
a pull the scheduler killed partway is carried to its proper end, so the
§5.6 completeness gate — not the wall-clock — is what certifies a run
finished. It is a small, self-contained module of checkpoint routines
that the pull calls into; nothing above it changes shape (`DESIGN.md`
§11.3 adds no new flag), and only the pull uses it in v1.

The one fact that drives every routine below (`DESIGN.md` §11.1): a
pull's progress lives in TWO places at once. The engine holds the atoms
and their velocities; ordinary program memory holds the accumulated
record the final curves are built from — the displacement, force,
opening, and bridge-count series of §9.5 — plus the starting atom count
the §5.6 gate checks against. A resume that restored only the engine
would keep the atoms but lose the record, restart the burst counter that
the displacement is (today) computed from, and re-measure the atom-count
baseline against an already-depleted box. So the checkpoint must save
BOTH places, as a matched pair.

### 13.1 The module's top-level shape

The module offers the pull four routines over a checkpoint that lives in
the RUNG's own checkpoint directory — `pull_<rate>/checkpoints/`, since
each rate is a separate pull with its own self-contained directory
(`DESIGN.md` §11.3): `write_checkpoint` (save the pair on a cadence),
`load_checkpoint` (read it back, or report none), `reconcile` (trim the
ledger to the saved engine step), and `verify_inputs_or_stop` (the trust
alert). The pull's loop (§9.5) gains exactly three touch points — decide
fresh-or-resume on entry, key each burst's displacement to the engine
step and append it to the ledger, and write the pair every so many steps
— and nothing else in the stage moves.

```
# The matched pair (DESIGN §11.2): two artifacts written TOGETHER and
# restored together. Neither is useful without the other.
structure Checkpoint:
    engine_state         # the engine's complete saved state (write_restart)
    ledger               # the Ledger below, saved beside it

# The progress that lives in program memory (DESIGN §11.1), keyed so a
# resume lines the record back up with the restored atoms. These four
# series ARE the raw record §9.6 reduces into the two curves — the
# ledger is not a new structure, it is §9.5's in-memory lists made
# durable, plus the two scalars a fresh process would otherwise lose.
structure Ledger:
    sample_steps          # engine step each sample below was taken at
    displacement          # grip displacement series (§9.5)
    force                 # top-grip reaction series (§9.5)
    opening               # interface-opening series (§9.5)
    bridges               # cross-interface bond-count series (§9.5)
    starting_atom_count   # the §5.6 conservation baseline, measured once
    saved_step            # engine step the paired state was written at
    input_hash            # the §13.4 trust field
```

### 13.2 The checkpoint pair — written together, keyed to the step

```
function write_checkpoint(driver, ledger, checkpoint_dir):
    # Written as a PAIR (DESIGN §11.2). A kill DURING the write must never
    # leave a half-pair that a later resume would trust, so each artifact
    # is written to a temporary name and then RENAMED into place; the
    # rename is the atomic step, and the pair becomes visible only once
    # both parts are fully on disk.
    ledger.saved_step = driver.step         # the engine's ABSOLUTE step
    # The engine state is written COLLECTIVELY — under MPI every rank
    # contributes to the one restart file (§9.2) — so this runs on all
    # ranks.
    write_restart(driver, checkpoint_dir / "engine.restart.tmp")
    # ...but the LEDGER and the atomic renames touch shared files a single
    # path can hold once, so ONLY the primary rank does them, or the ranks
    # would race on one path. Nothing rank-specific is lost: the ledger's
    # series come from collective read-backs, identical on every rank.
    if not driver.is_primary:
        return
    write_ledger(ledger,  checkpoint_dir / "ledger.json.tmp")
    # Rename the LEDGER first, then the engine state, so a kill between the
    # two leaves the ledger AHEAD of the engine (reconcile can trim that;
    # it could not fill a gap the other way — §13.2, §13.5).
    atomic_rename(checkpoint_dir / "ledger.json.tmp",
                  checkpoint_dir / "ledger.json")
    atomic_rename(checkpoint_dir / "engine.restart.tmp",
                  checkpoint_dir / "engine.restart")

function load_checkpoint(checkpoint_dir):
    # A checkpoint EXISTS only when BOTH parts are present. A lone restart
    # or a lone ledger is treated as no checkpoint at all — the pair
    # discipline of §11.2 refuses to restore from half a pair.
    if not (exists(checkpoint_dir / "engine.restart")
            and exists(checkpoint_dir / "ledger.json")):
        return None
    return Checkpoint{
        engine_state = checkpoint_dir / "engine.restart",
        ledger       = read_ledger(checkpoint_dir / "ledger.json") }
```

### 13.3 Fresh or resuming, decided by what is on disk

```
function begin_or_resume_pull(driver, reference, rate, member,
                              checkpoint_dir):
    # No new flag (DESIGN §11.3): the presence of the pair decides.
    checkpoint = load_checkpoint(checkpoint_dir)

    if checkpoint is None:
        # FRESH. The ordinary §9.5 setup: restore the settled reference
        # into the driver, hold the bottom grip, drive the top grip at
        # rate. Seed a ledger with the baseline the §5.6 gate needs and
        # the trust hash this run will be resumed against.
        restore(driver, reference)
        hold(driver.grips.bottom)
        drive_grip(driver.grips.top, rate)
        return new Ledger{
            starting_atom_count = atom_count(driver),
            input_hash          = input_hash(member, reference, rate),
            saved_step          = driver.step }        # 0 on a fresh run

    # RESUMING. Trust FIRST (§13.4), so a wrong-run resume stops before
    # it touches the engine. Then restore the saved atoms and reconcile
    # the record to them.
    verify_inputs_or_stop(checkpoint, member, reference, rate)
    read_restart(driver, checkpoint.engine_state)
    drive_grip(driver.grips.top, rate)         # re-arm the constant pull
    return reconcile(checkpoint.ledger, driver.step)

function reconcile(ledger, restored_step):
    # The ledger is appended every burst but the engine is saved on a
    # COARSER cadence (§13.5), so a ledger may run a few bursts PAST the
    # last saved state. Drop every sample taken beyond the restored step
    # so the record and the atoms agree before the run goes on (DESIGN
    # §11.2). Keying each sample to its engine step is exactly what makes
    # this trim well-defined.
    keep = indices i where ledger.sample_steps[i] <= restored_step
    return ledger with every series (sample_steps, displacement, force,
                                     opening, bridges) trimmed to `keep`
```

### 13.4 The trust alert: warn, and stop

```
function input_hash(member, reference, rate):
    # What identifies "the same run" (DESIGN §11.4): the study's CONTENT
    # fingerprint (DESIGN §1.4, the identity §12.4 builds on), the
    # identity of the settled reference the pull restores from, and the
    # pull RATE — the only input that tells one rung from another, since
    # every rung shares the fingerprint and the one settled reference
    # (DESIGN §11.4). NOT paths, NOT the wall-clock — only things whose
    # change means a genuinely different experiment. The exact fields
    # ride on the same open follow-on as the fingerprint (DESIGN §1.8).
    return content_hash(member.fingerprint, reference.identity, rate)

function verify_inputs_or_stop(checkpoint, member, reference, rate):
    # A guardrail, not a correctness gate (DESIGN §11.4). Resuming reuses
    # what a previous run left in a directory, so it owes one check that
    # the inputs still match the run the checkpoint came from.
    if input_hash(member, reference, rate) == checkpoint.ledger.input_hash:
        return                                  # the common case: proceed
    warn("this run's inputs differ from the run this checkpoint was "
         "written for; refusing to stitch new inputs onto old dynamics")
    # WARN AND STOP. The stop is what makes the warning seen rather than
    # scrolled past; it lifts ONLY on an explicit, deliberate override —
    # the one switch the person must set by hand to say "yes, continue
    # anyway", recorded in provenance when they do (§13.6).
    if not resume_override_is_set():
        stop
```

### 13.5 The pull loop, re-keyed and check-pointed (`§9.5`)

This is the delta to §9.5: the same loop, with the displacement re-keyed
to the engine step and the two new touch points folded in. After the
loop, §9.6 reduces the ledger's raw series — the very series a fresh run
gathers in memory — into the two curves, the separation point, and the
gates, unchanged; the only difference is that the series comes from the
ledger. The coordinate archive is handled exactly as in §9.5.

```
function pull_at_rate(driver, reference, rate, member, control,
                      checkpoint_dir):                            # §9.5
    numerical = member.numerical
    timestep  = numerical.md_timestep
    # chunk_steps and checkpoint_cadence are RunControl ENGINEERING
    # settings (the same home as §9's chunk controls), NOT NumericalKnobs
    # — the answer is invariant to them; they trade work-lost-on-a-kill
    # against write cost. Provisional values live in code, not the spec.
    cadence   = control.checkpoint_cadence       # engine steps per save

    ledger = begin_or_resume_pull(driver, reference, rate, member,
                                  checkpoint_dir)   # §13.3

    # The loop of §9.5, now step-keyed. On a fresh run the ledger is
    # empty and this fills it; on a resume it is pre-loaded and this
    # extends it — the SAME code either way (DESIGN §11.3).
    #
    # Stop on the §9.6 separation test (opening past cutoff, force back
    # to the floor, no bridges left), extended by the code's one-more-
    # averaging-window confirmation tail — a press_pull.py refinement,
    # not itself in §9.5/§9.6.
    while not separated_with_confirmation_tail(ledger):
        run(driver, control.chunk_steps)
        step = driver.step               # the engine's ABSOLUTE step

        # THE HINGE (DESIGN §11.1). Displacement is the grip's travel,
        # which is rate x elapsed-simulated-time; elapsed time is the
        # ENGINE STEP x timestep, NOT (burst_index x chunk_steps), so a
        # resumed run whose burst index restarts at zero still reports
        # where the grip physically sits. On a fresh run the two agree
        # exactly; they diverge only across a resume, which is the bug.
        append to ledger:
            sample_steps <- step
            displacement <- rate * (step * timestep)
            force        <- grip_reaction(driver.grips.top)
            opening      <- interface_opening(driver)
            bridges      <- cross_interface_bridges(driver)

        # Save the pair on a cadence. Cheap relative to the MD between
        # saves; the cadence trades work-lost-on-a-kill against
        # write cost (a §5.9-style number, §13.7).
        if step - ledger.saved_step >= cadence:
            write_checkpoint(driver, ledger, checkpoint_dir)   # §13.2

    # §9.6's reduction, fed straight from the ledger — the ledger IS the
    # series it reduces (displacement/force/opening/bridges). The
    # coordinate archive is the on-disk strided dump: a SEPARATE artifact
    # that survives a kill, so it is not in the ledger, and it exists only
    # when a consumer is in play (§9.5); else the reference is none.
    frames_ref = the strided dump on disk if a consumer is in play,
                 else none
    return reduce_to_trajectory(driver, ledger, frames_ref, reference,
                                rate, member)                        # §9.6
```

### 13.6 Completeness and provenance are unchanged

Resuming changes nothing about how a run is judged finished (`DESIGN.md`
§11.5). The §5.6 gate in §9.6 asks whether the trajectory reached its
target and whether the atom count was conserved against the ledger's
`starting_atom_count`; it does not ask, and need not care, how many
submissions it took. A pull that reaches its end across two or three
continuations is complete; one still short is caught exactly as before.
The only addition is honesty in the record: `reduce_to_trajectory`'s
provenance (§9.6) gains a note that the run was CONTINUED, and — if the
§13.4 trust warning was ever overridden — that too, so the history stays
truthful about how the number was produced (`VISION.md` goal 3).

### 13.7 What bottoms out, what delegates

`[OURS, bottoms out here]` the MATCHED-PAIR write with temp-then-rename
atomicity and the both-parts-present load (§13.2); the step-keyed ledger
and its RECONCILE-to-saved-step trim (§13.3); the on-disk presence test
that decides fresh-vs-resume with no new flag (§13.3); the displacement
re-key to the engine step, the correctness hinge (§13.5); and the
input-hash WARN-AND-STOP with a deliberate override (§13.4). Each is a
small, testable operation over the driver seam and two files.

`[DELEGATE -> ENGINE, §9.2]` `write_restart` / `read_restart`, the
engine's `step`, and `is_primary` (which rank writes the shared files
under MPI) are the persistent LAMMPS driver's operations; this module
CALLS them and never reimplements the saved-state format or the rank map.

`[DELEGATE -> §9.5 / §9.6]` the pull's setup, its stop rule, the
averaging, the two curves, the separation point, and the §5.6 gates are
all §9's; §13 only re-keys the displacement and threads the ledger
through them. The MEASUREMENT is unchanged.

`[DELEGATE -> fingerprint, `DESIGN.md` §1.4]` the study identity the
trust hash draws on is the content fingerprint of `DESIGN.md` §1.4 (the
same machinery `PSEUDOCODE.md` §12.4 uses); this module composes it with
the settled-reference identity and the pull rate, then compares, but does
not define what a "difference that matters" is — that is `DESIGN.md`
§1.8's open follow-on.

`[ABOVE this module]` only the PULL is resumable in v1 (`DESIGN.md`
§11.6); `press_and_bond` (§9.3) and `settle_reference` (§9.4) are short
and adopt the same four routines later, unchanged, should they ever need
to. The sequencer (§1) decides nothing new — it reruns the same command
(`DESIGN.md` §10.6).

`[CODE level, below pseudocode]` the exact `write_restart` /
`read_restart` syntax, the atomic-rename call, and the ledger's on-disk
serialization (the four series plus the two scalars).

`[DESIGN §5.9 / §11.6 numeric follow-on]` the checkpoint CADENCE — how
many engine steps between saves — is a RunControl ENGINEERING setting
(`checkpoint_cadence`, beside `chunk_steps` and `max_chunks`), NOT a
NumericalKnob: the answer is invariant to it, so it takes a provisional
value in code rather than a spec-visible one, balancing work lost on a
kill against time spent writing state.

## 14. Deployment — preparing and running (`DESIGN.md` §10)

The CONSUMER of the machine-local deployment file (`ARCHITECTURE.md`
§4.1, §4.4; `DESIGN.md` §10). It is two commands that share one registry:
a WRITER, `prepare`, that reads the study spec AND the deployment rc and
emits ready-to-submit scripts; and an EXECUTOR, `run`, that lives INSIDE
each script and does one job's worth of the pipeline. `sabsim` submits
NOTHING and watches nothing (the login-node wall, §4.1); the human
submits the scripts and inspects each gate before sending the next.

Nothing here trains a potential or layers in a physics default. The force
model a member uses is a LOOKUP behind the §1 `resolve_potential` seam —
the classical stand-in today, the trained committee once the bootstrap
(§11, a SEPARATE upstream Tier-B process) has produced one — so the same
three jobs run either, unchanged. Deployment is "where," never "what"
(`DESIGN.md` §1.2).

### 14.1 The deployment records (CLOSED)

```
record DeploymentConfig:              # the parsed rc (DESIGN §10, §4.1)
    cluster_name:     text
    scheduler:        text            # e.g. "slurm"
    default_account:  text
    module_paths:     list of path    # `module use` roots (§4.4)
    partitions:       map[resource_class -> Partition]  # "cpu" / "gpu"
    usage:            map[job_kind -> UsageBlock]        # keyed by KIND

record Partition:                     # one [hardware.partitions.*]
    name:          text               # the REAL scheduler partition
    capacity:      map[text -> number]  # cores_per_node / gpus_per_node
    max_walltime:  duration           # the ceiling §14.4 checks against

record UsageBlock:                    # one [usage.*], keyed by job kind
    resource_class: text              # names a Partition ("cpu" / "gpu")
    nodes:          integer
    tasks_per_node: integer           # MPI ranks per node; HUMAN-provided
                                      # (§10.6), NOT filled from the
                                      # partition -- the atoms-per-rank
                                      # sweet spot is a per-kind tuning
                                      # choice, like walltime
    gpus_per_node:  integer           # accelerators per node; 0 for a
                                      # CPU-only job, stated on EVERY block
                                      # (like modules=[]). Writer emits
                                      # `--gres=gpu:N` only when positive
    walltime:       duration          # HUMAN-provided (§10.6), not computed
    memory:         memory_amount     # per-node request, HUMAN-provided
                                      # (§10.6): a { value, unit } size the
                                      # writer emits as `--mem`. A job with
                                      # none inherits the partition's small
                                      # per-job default, which OOM-killed
                                      # the activate cascade (T-E5-ACTIVATE)
    modules:        list of text      # module(s) to `module load` (§4.4)
```
`load_deployment` reads the rc into this as a COMPLETE object with no
silent physics default (§1.4): a missing required field is a loud stop,
never a fallback. `[DELEGATE -> the TOML PARSING, and the three location
roots read from the sourced `.sabsim/sabsimrc`, `DESIGN.md` §10.5]`.

### 14.2 One ordered job registry, read by both commands (§10.3)

```
# The SINGLE source of truth for what the jobs are and in what order they
# run. Each entry names the job, the abstract resource class the rc
# resolves to a partition, and the CONTIGUOUS SUB-STAGE of the §1 member
# chain it owns -- with the on-disk artifact it READS at entry and WRITES
# at exit. That handoff (ARCHITECTURE §4.3) is exactly what lets one job
# start mid-chain in its own submission.
#
# A SUB-STAGE is a run of ADJACENT pipeline stages -- a section of the
# whole §1 stage sequence, NOT a piece of any one stage. Each job owns
# one; the `stages` field lists the stages that make it up.
record JobKind:
    name:            text             # "activate" / "bond" / "analyze"
    resource_class:  text             # -> a UsageBlock + a Partition
    stages:          ordered list of Stage   # the stages of its sub-stage
    reads:           artifact_name or NONE    # entry file in member scratch
    writes:          artifact_name            # exit file in member scratch

JOB_REGISTRY = ordered [
    JobKind("activate", "cpu",
            stages = [build_slabs,        # §7
                      activate_surfaces,  # §10 (its own §3.5 gate)
                      assemble_pair],     # §7
            reads  = NONE,                # starts from the spec
            writes = ASSEMBLED_PAIR),     # the assembled-pair data file
    JobKind("bond", "gpu",
            stages = [press_and_bond,     # §9.3
                      settle_reference,   # §9.4
                      pull_ladder],       # §9.5 (rungs, committee in-proc)
            reads  = ASSEMBLED_PAIR,
            writes = PULL_RESULTS),       # per-rung curves + trajectories
    JobKind("analyze", "cpu",
            stages = [run_analyzer,          # §4 measure vector, PLUS
                      run_characterization], #   the mocked step-8 char
            reads  = PULL_RESULTS,
            writes = MEASURE_VECTOR),     # the §4 vector, GATED (§14.3)
]
```
Inserting a job later (§10.3, say a relax between activate and bond) is
ONE entry here; the `run` flags, the written filenames, and the guided
index all follow — the truth is never written twice.

### 14.3 The run selector — one job, or the whole chain (§10.4)

```
function run(study_spec_path, job_flag, only_member):
    # job_flag is at most ONE of {activate, bond, analyze}, or NONE for
    # the whole member chain (§10.4). only_member narrows a multi-member
    # study to one. This is the line that lives INSIDE each generated
    # script; it runs within an allocation and submits nothing itself.
    validated = load_and_validate_study(study_spec_path)     # §2
    members   = validated.members
    if only_member is given:
        members = [ the member named only_member ]           # or STOP
    for each member in members:
        scratch = member_scratch(job_directory, validated.name,
                                 member.name)                # §1
        if job_flag is NONE:
            exec_one_member(member, scratch)                 # §1 whole chain
        else:
            run_member_job(member, scratch,
                           registry_lookup(job_flag))
```

```
function run_member_job(member, scratch, job):
    # ONE job's contiguous SUB-STAGE of the §1 chain. It ENTERS by re-reading
    # its `reads` artifact from the member scratch -- the same
    # read-from-file handoff activate_surfaces already uses (§1 re-reads the
    # pristine half), so this process needs NONE of the stages before it.
    # The potential is the LOOKUP every job does (§1 resolve_potential):
    # classical stand-in now, trained committee later, SAME seam.
    potential = run_to_contract(
        () -> resolve_potential(member), POTENTIAL_CONTRACT)  # §1
    seed = (job.reads is NONE)
           ? member                            # activate: from the spec
           : read_artifact(scratch, job.reads) # bond/analyze: from disk
    # Run this job's stages exactly as §1 runs them, but only this
    # sub-stage, each guarded by run_to_contract so a bad artifact HALTS
    # here (§5.1). The final stage writes job.writes into scratch; the NEXT
    # job (a separate submission) reads it. Nothing crosses in memory.
    run_sub_stage(job.stages, seed, member, potential, scratch)
```
`[DELEGATE -> the exact per-stage calls and signatures are §1's; `run_
member_job` reuses them, differing only in that it starts from `seed`
rather than the previous in-memory handle.]`

The analyze job's sub-stage is the WHOLE tail of `exec_one_member` (§1),
not just `run_analyzer`: after it, the job MERGES the mocked step-8
characterization (`run_characterization`, §4) and READS the §5 gate, so
the MEASURE_VECTOR it writes is the GATED member result (§1's
MemberResult), not a bare measure list. The gate adds no stage -- it only
reads the vector and reports (§5, VISION principle 5) -- which is why
§14.2 lists the two producing stages while the gate rides along here.

### 14.4 prepare — the writer (§10.5, §10.6)

```
function prepare(study_spec_path, deployment_rc_path):
    # Reads BOTH inputs and writes scripts; submits nothing (§10.1). Runs
    # on the login node, so it must FAIL THERE, readably, rather than emit
    # scripts that die on a compute node an hour in.
    roots = resolve_location_roots()      # scratch / share / local, §10.5
    if any root does not resolve:
        STOP on the login node, naming the missing root   # §10.5 gate
    deployment = load_deployment(deployment_rc_path)      # §14.1
    validated  = load_and_validate_study(study_spec_path) # §2

    guide = new submission guide          # the ORDERED index (§10.5)
    for each member in validated.members:
        for each job in JOB_REGISTRY:     # activate -> bond -> analyze
            usage     = deployment.usage[job.name]
            partition = deployment.partitions[usage.resource_class]
            # Two cheap checks (§10.6): compare numbers already written in
            # the rc. Predict NOTHING about run length or footprint.
            if usage.walltime > partition.max_walltime:
                STOP on the login node, naming job + ceiling  # §10.6 gate
            if usage.gpus_per_node > 0 and (
                    usage.gpus_per_node > partition.gpus_per_node):
                STOP on the login node, naming job + GPU ceiling  # §10.6
            script = render_job_script(validated, member, job,
                                       usage, partition, deployment, roots)
            path   = semantic_name(member, job)   # "activate" / "bond" /
                                                  # "analyze" -- NO ordinal
            write script to path
            guide.append(member, job, path)       # ORDER lives here, §10.5
    write guide beside the scripts        # a submission GUIDE, not "readme"
    return guide
```

### 14.5 What a generated script contains (§10.5, §10.7)

```
function render_job_script(study, member, job, usage, partition,
                           deployment, roots):
    # A small, boring preamble plus the run line. Anything already true of
    # the activated install is NOT restated (§10.5).
    return a script with, in order:
      - SCHEDULER DIRECTIVES from (partition.name, usage.nodes,
        usage.tasks_per_node, usage.gpus_per_node, usage.memory,
        usage.walltime, deployment.default_account) -- the §10.7 field set
        the throwaway jobs/* scripts already enumerate. usage.memory is
        emitted as `--mem`; without it the job takes the partition's small
        per-job default and can be OOM-killed (§10.6, T-E5-ACTIVATE).
        usage.gpus_per_node is emitted as `--gres=gpu:N` ONLY when
        positive, so a CPU job gets no --gres (§10.6).
      - `module use <p>` for each p in deployment.module_paths, THEN
        `module load <m>` for each m in usage.modules (§4.4: the cpg tree
        is not on the default path; bond loads the ONE deepmd engine,
        whose module also LD_PRELOADs libstdc++ and exports
        DEEPMD_LMP_PLUGIN).
      - the three location roots BAKED IN as resolved values -- a frozen
        snapshot, not a re-read of the rc at run time (§10.5, §1.4).
      - the launcher + `python -m sabsim run <study> --<job.name>
        --only <member.name>` (§14.3) -- e.g. `mpirun -np <N>` INSIDE the
        allocation, never on the login node (§4.1). N = usage.nodes x
        usage.tasks_per_node, emitted as `--ntasks-per-node` so the
        scheduler's own $SLURM_NTASKS drives the launcher.
      - on success, a printed line naming what to check and which script
        to submit next (§10.5), reinforcing the guide.
```
`[DELEGATE -> the deepmd `plugin load`: the bond job's LAMMPS INPUT issues
`variable dp getenv DEEPMD_LMP_PLUGIN; plugin load ${dp}` inside the
force-model command block (`ARCHITECTURE.md` §4.4, `driver/commands` §9),
NOT here -- render_job_script only loads the module that exports the var.]`

### 14.6 The handoff artifact form (`read_artifact`/`write_artifact`)

§14.3 delegated the READ and WRITE at the two mid-chain seams; this pins
what those artifacts physically ARE. A job submitted on its own re-reads
its entry artifact in a FRESH process -- it does not inherit the warm
in-memory object the whole-chain run passes stage to stage. So the two
mid-chain artifacts (ASSEMBLED_PAIR, which activate writes and bond
reads; PULL_RESULTS, which bond writes and analyze reads) must be
COMPLETE on disk: everything the downstream job needs, reconstructible
from files alone. Each takes the SAME shape the §3 trajectory already
uses -- small things INLINE, large things BY REFERENCE.

```
record HandoffArtifact:              # one written mid-chain artifact
    manifest: path       # a READABLE index (the small, self-describing
                         # half): scalars, geometry, per-rate fields,
                         # verdicts, provenance -- and the NAMES of any
                         # bulky payloads below. Human-inspectable and
                         # durable across a code change (VISION goal 3),
                         # NOT an opaque pickle of the whole record.
    payloads: map[name -> path]   # the LARGE half, each its OWN file: an
                         # engine data file (LAMMPS), or a numeric array
                         # stored as its own (optionally COMPRESSED)
                         # binary. NEVER a large array inlined into the
                         # manifest; the manifest references these by name.
```

So ASSEMBLED_PAIR is the LAMMPS `assembled_pair.data` (the atoms -- a
payload the assemble stage already writes) plus a manifest carrying the
labeled-group geometry the bond job CANNOT re-derive from the atoms: the
per-wafer z-ranges, the interface plane, and the MEASURED activated_skin
atom-index set (`DESIGN.md` §2.6 -- a measured set, not a depth cut, so
it MUST travel). PULL_RESULTS is a manifest of each rung's reduced fields
(rate, complete, separation_index, atoms_conserved, the verdicts) plus
its reduced curves (grip_displacement, force_vs_grip): a curve small
enough stays inline, a curve large enough becomes a payload file -- the
SAME small-inline / large-by-reference rule, applied field by field. The
full per-atom trajectory is ALREADY a §3 FrameSetRef payload on scratch
and is NOT duplicated here.

`write_artifact(scratch, name, record)` writes the manifest and any
payloads under the member scratch; `read_artifact(scratch, name)` reads
the manifest and rehydrates the record, opening a payload only when a
consumer needs it. In v1 the ASSEMBLED_PAIR groups and the PULL_RESULTS
curves are both small enough to sit inline, so no payload beyond the
existing LAMMPS data file is written yet -- but the seam IS the
by-reference one, so a field that GROWS large is externalized later
without changing the contract.

One more re-read the analyze job makes. `run_analyzer` needs the interface
AREA (the assembled pair's lateral cell) to reduce the work per unit area,
which the PULL_RESULTS does not carry. So analyze reads its OWN entry
artifact (PULL_RESULTS) AND re-reads the earlier ASSEMBLED_PAIR from the
SAME member scratch -- both artifacts persist there, so this is a plain
re-read, not a new hand-off. A job's `reads` field (§14.2) names its
DEFINING upstream; a job may still re-open any earlier artifact its member
scratch holds.

`[DELEGATE -> the manifest's on-disk syntax and the compression codec for
a bulky payload are CODE-level. The manifest is written as TOML, keeping
it consistent with the study-spec and rc files a human reads and edits.
The standard library READS TOML (`tomllib`) but cannot WRITE it, so the
code emits the few value types a manifest uses (scalars, scalar arrays,
nested tables, arrays of tables) through a small hand-rolled writer; a
null field is simply OMITTED, since TOML has no null, and the read side
maps a missing key back to "none". The CONTRACT here is only "readable
manifest + referenced payloads, small-inline / large-by-reference."]`

`[CODE level, below pseudocode]` the exact directive syntax (SLURM
`#SBATCH`), the script templating, and the guide's on-disk format.

`[ABOVE this module / OUT of scope]` the BOOTSTRAP (steps 1-2, §11) is NOT
one of these three jobs and NOT a `run` flag: it is a separate Tier-B
process (ALF's own Parsl loop plus direct VASP seed jobs, `DESIGN.md`
§4.5) that MANUFACTURES the potential upstream of every member. `prepare`
writes the three MEMBER jobs that CONSUME it; deploying the bootstrap
itself is ALF's concern, not this consumer's (§4.1, "no Parsl-in-Parsl").
