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
function exec_full_study(study_specification):
    # Entry point. A study is members + relations (DESIGN §1.1). Each
    # member is executed independently; the relations (e.g. the Si/SiO2-
    # to-Si/Si ratio) are graded only after every member has produced
    # its measure vector.
    validated_study = load_and_validate_study(study_specification)

    member_results = empty_list
    for each member_specification in validated_study.members:
        member_results.append(exec_one_member(member_specification))

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
function exec_one_member(member_specification):
    # The eight-step pipeline for ONE member. In v1 the quality-gate loop
    # executes its body ONCE and reports (VISION principle 5); the
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
    potential = run_to_contract(
        () -> resolve_potential(member_specification),   # skeleton:
                                                          # classical
        POTENTIAL_CONTRACT)

    # Steps 3-4-5 are three SEPARATE stages, and their order is a SETTING
    # (ARCHITECTURE §2.1): the builder and the activator are order-
    # agnostic behind their contracts (§5.3), so the sequencer applies
    # whatever order the spec declares. The default (and the only
    # physically sensible order for v1) is build -> activate -> assemble;
    # a general reorder engine is [DEPTH-FIRST] for this sequencer.

    # Step 3 — build both slabs to the shared coincidence cell (§7).
    (slab_A, slab_B, shared) = run_to_contract(
        () -> build_slabs(member_specification, potential),
        SLABS_CONTRACT)

    # Step 4 — activate (amorphize) each slab's surface. A SEPARATE
    # module (DESIGN §3) with its own pass/fail gate (§3.5); in the
    # skeleton it is stubbed. It does NOT assume it ran before assembly
    # (§5.3).
    (slab_A, slab_B) = run_to_contract(
        () -> activate_surfaces(slab_A, slab_B, member_specification,
                                potential),
        ACTIVATED_SLABS_CONTRACT)

    # Step 5 — assemble the facing pair from the activated slabs (§7).
    structure = run_to_contract(
        () -> assemble_pair(slab_A, slab_B, shared, member_specification),
        STRUCTURE_CONTRACT)

    # Steps 6-7: press then pull, on the MLIP (here, the stand-in).
    trajectory = run_to_contract(
        () -> run_bond_debond_md(structure, potential, member_specification),
        TRAJECTORY_CONTRACT)

    # The analyzer turns the trajectory into a measure vector (DESIGN
    # §6). In the skeleton only the Imago-free mechanical measure is
    # real; the rest report `unresolved`.
    measures = run_to_contract(
        () -> run_analyzer(structure, trajectory, member_specification),
        MEASURE_VECTOR_CONTRACT)

    # Step 8 characterization feeds additional measures. In the skeleton
    # this is MOCKED and returns schema-valid `unresolved` records.
    characterization = run_to_contract(
        () -> run_characterization(structure, trajectory,
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
this document: `STRUCTURE_CONTRACT` and `TRAJECTORY_CONTRACT` are §3,
`MEASURE_VECTOR_CONTRACT` is §4. The structure stage's intermediate
contracts are `SLABS_CONTRACT` (two valid `Slab`s plus their shared cell,
§7.1) and `ACTIVATED_SLABS_CONTRACT` (both slabs amorphized and past the
activation gate, `DESIGN.md` §3.5). `POTENTIAL_CONTRACT` is the one
exception — not a record of ours but the external potential's loadable
`pair_style` interface (its *quality* is judged separately by the §5
gate; the guard here only checks it is a usable potential).

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
    ensemble:      EnsembleKnobs   # master seed + realization count
    potential_ref: string         # WHICH potential generation this member
                                  # uses — a content fingerprint, or the
                                  # classical stand-in marker in the
                                  # skeleton. The potential's CONTENTS are
                                  # not settings
                                  # (DESIGN §1.3); this POINTER is one,
                                  # for provenance (DESIGN §1.6, §6.6).

record MaterialKnobs:             # one per wafer; two wafers per member
    crystal_structure: string     # e.g. Si diamond, cristobalite
    surface_face:      Miller indices
    identity:          string     # the material itself
    # NEVER a lattice constant — §2.2 derives it from the potential
    # (DESIGN §1.3).

record ProtocolKnobs:
    # The skeleton touches press + separation; the activation fields are
    # declared but UNUSED there (activation is stubbed). [DEPTH-FIRST] the
    # energy/
    # angle DISTRIBUTIONS and the full field set: DESIGN §3 and §5.
    activation_species: string    # argon by default (DESIGN §1.2)
    activation_energy:  number
    activation_angle:   number
    activation_fluence: number    # ions per A^2, cell-size-independent
    initial_gap:        number    # slab separation at assembly (§2.6)
    press_control:      one of {load, displacement}   # DESIGN §5.2
    press_load:         number    # load or pressure reached
    press_depth:        number
    press_duration:     number
    separation_speed:   number    # the pull rate (DESIGN §5.4)

record NumericalKnobs:
    # Filled as modules land (DESIGN §1.8). [DEPTH-FIRST] the full
    # tolerance / cutoff / stride / window / budget set.
    pull_rate_ladder: list of number  # >= 3 rates over a decade (§5.4)
    noise_floor:      number          # peak/curve threshold (§5.4)
    frame_stride:     integer         # store 1 frame per N MD steps
                                      # (e.g. 100-1000); NOT every step
    misfit_tolerance:       number    # coincidence-match cutoff (§2.3;
                                      # it prices step 8, DESIGN §8.2)
    minimum_bulk_thickness: number    # undamaged substrate floor (§2.5)
    clash_floor:            number    # min cross-slab distance (§2.6)

record EnsembleKnobs:
    master_seed:       integer    # one master seed; per-realization
                                  # seeds are derived from it (DESIGN §1.2)
    realization_count: integer    # how many seeds to average over

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
    # Geometric regions every downstream stage needs, computed ONCE by
    # the builder rather than re-derived per LAMMPS input (DESIGN §2.6).
    frozen_base:       atom-index set
    thermostat_border: atom-index set
    nve_interior:      atom-index set
    activated_skin:    atom-index set
    grips:             atom-index set   # press/pull handles (DESIGN §5)
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
    separation_point:     frame-index or none   # complete separation
    complete:             boolean   # ran to the end (DESIGN §5.6) — GATE
    atom_count_conserved: boolean   # non-periodic box lost none — GATE
    grip_reaction:        pair of Curve   # BOTH grips -> Newton check
    provenance:           Provenance      # potential gen, seeds, rate
    frames:               FrameSetRef      # the full per-atom trajectory

record FrameSetRef:
    # A reference to the ACTUAL atomic-coordinate trajectory on shared
    # scratch. First-class: any measure, the §8 snapshot selector, or a
    # human may read it. The available per-atom CHANNELS are declared so
    # a consumer knows what is present without opening the (large) file.
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

In the walking skeleton the analyzer needs only `force_vs_grip`,
`reference_state`,
`separation_point`, and the two gate flags (`complete`,
`atom_count_conserved`) — M1's inputs. `force_vs_opening`, the σ_zz
series, and `grip_reaction` are populated but read only by deeper
measures and checks. Crucially the **`frames` reference is populated
too**: the MD stand-in writes an atomic-coordinate dump even though no
walking-skeleton
measure reads it, so the by-reference seam is real and exercised from the
start — the §8 selector and any human re-analysis inherit working
plumbing rather than a stub.

`[DEPTH-FIRST]` the reduction that produces the curves and scalar series
from the raw frames (`DESIGN.md` §5.5). The frame stride is a NUMERICAL
knob (`NumericalKnobs.frame_stride`, §2) — one stored configuration per N
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
function run_analyzer(structure, trajectory, member_specification):
    # The analyzer is a REGISTRY of measures (DESIGN §6.7). Each measure
    # declares what it needs; the analyzer resolves those needs against
    # what the member produced, computes what it can, and marks the rest
    # `unresolved`. Adding a measure is registering one, not editing the
    # gate.
    measures = empty_list
    for each measure in registered_measures():
        if measure.inputs_available(structure, trajectory):
            measures.append(measure.compute(structure, trajectory))
        else:
            measures.append(measure.as_unresolved())
    return MeasureVector{ measures: measures, ... }
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
function evaluate_member_gates(measures, member_specification, potential):
    # Potential-quality gate (DESIGN §7.2-§7.3): is the MLIP good on its
    # own terms (bulk/surface) and at the interface? This is meaningful
    # for a member on its OWN terms, independent of any comparison. A
    # failure is a POTENTIAL problem -> the remedy is more training data.
    bulk_surface = check_bulk_surface(potential, measures)
    interface    = check_interface_fidelity(measures)   # STRUCTURAL 3

    # The five-way diagnosis routes the CAUSE of a questionable bond
    # number using those per-member signals (DESIGN §7.6). The bond-outcome
    # RATIO itself is a relation, graded at the study level (§1); a
    # single member has no ratio to grade.
    return diagnose(measures, bulk_surface, interface)
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
    slabs      = build_slabs(...)               # step 3, real
    slabs      = stub_activate(slabs)           # step 4, STUB
    structure  = assemble_pair(slabs, shared)   # step 5, trivial (Si/Si)
    trajectory = press_then_pull(structure)     # steps 6-7, real
    measures   = run_analyzer(structure, trajectory)   # M1 real, the
                                                       # rest unresolved
    measures   = merge mock_characterization()  # step 8, MOCK
    gate       = evaluate_member_gates(measures)
    # -> the resulting MemberResult.trusted is FALSE (a plumbing member)
```

**What each stand-in must still honour:** `stub_activate` returns valid,
amorphization-free `Slab`s (§3); `mock_characterization` returns
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
It refines the `[DEPTH-FIRST]` structure bodies of §3 to code-readiness —
*except* the coincidence-matcher search, which recurses one level further
(§7.6). Depth here is uneven by design: the strain split bottoms out in a
single formula, the matcher needs a sub-pass of its own.

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
function build_slabs(member_specification, potential):
    # Steps up to and including step 3, for BOTH wafers. Stops before
    # activation, which the sequencer runs next.
    material_A, material_B = member_specification.material   # two wafers
    misfit_tolerance       = member_specification.numerical.misfit_tolerance

    # The shared cell is solved ONCE, on the two SUBSTRATE lattices, and
    # is an invariant of the pair (DESIGN §2.1, §2.3).
    shared = solve_shared_cell(material_A, material_B, potential,
                               misfit_tolerance)

    # Split the small residual misfit between the slabs (DESIGN §2.4).
    strain_A, strain_B = split_strain(shared, material_A, material_B,
                                      potential)

    slab_A = build_slab(material_A, shared, strain_A, potential,
                        member_specification)
    slab_B = build_slab(material_B, shared, strain_B, potential,
                        member_specification)
    return (slab_A, slab_B, shared)
```

```
record SharedCell:
    lateral_cell:    Cell                 # the shared coincidence cell
    tiling_A:        2x2 integer matrix    # whole-number tiles of A
    tiling_B:        2x2 integer matrix    # whole-number tiles of B
    twist:           angle                 # relative in-plane rotation
    residual_strain: StrainTensor          # misfit left after the match
```

A `Slab` is just a `Structure` (§3) for one material — one provenance
label, and `grips` not yet set (assembly sets them, §7.5).

### 7.2 solve_shared_cell — lattices from the potential, then the match

```
function solve_shared_cell(material_A, material_B, potential,
                           misfit_tolerance):
    # Lattices come from the POTENTIAL, not literature (DESIGN §2.2):
    # relax each bulk under the current committee, referenced to VASP.
    # The relaxed-vs-VASP disagreement is itself a potential-quality
    # measure (DESIGN §2.2, §7-of-DESIGN) — recorded, not discarded.
    lattice_A = relaxed_lattice(material_A, potential)   # vs VASP
    lattice_B = relaxed_lattice(material_B, potential)

    # The coincidence match: a Zur-McGill search over whole-number
    # tilings of BOTH surface vectors plus a relative twist, scoring
    # misfit as a strain TENSOR within the tolerance (DESIGN §2.3). This
    # is the one structure body that recurses further (§7.6).
    return coincidence_match(lattice_A, lattice_B, misfit_tolerance)
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
    # Step 5. In the real pipeline both slabs are ACTIVATED by now (the
    # sequencer ran activation between build_slab and here). Both already
    # share `shared.lateral_cell` by construction, so ASSERT
    # commensurability, never assume it (DESIGN §2.6) — prior art adopted
    # one slab's box and ignored the other's.
    assert slab_A.lateral_cell == slab_B.lateral_cell

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

    # Emit the labeled-group contract (§3) ONCE: frozen base, thermostat
    # border, NVE interior, activated skin, grips. Every downstream stage
    # reads these rather than re-deriving them per LAMMPS input (§2.6).
    pair.labeled_groups = assign_labeled_groups(pair, member_specification)
    return pair      # a Structure (§3): the facing pair, grips SET
```

### 7.6 What recurses one level further

`[DEPTH-FIRST · one level deeper]` `coincidence_match` (§7.2) is the
Zur-McGill search and is the only structure body not yet at code-
readiness. Its next sub-pass writes: the enumeration of whole-number
tiling matrices over both surface vectors up to a size bound; the
relative in-plane twist sweep; the per-candidate misfit as a strain
TENSOR (never a scalar length compare — prior art's error, `PRIOR_ART.md`
§1.6); the tolerance cut; and the selection among admissible cells
(smallest cell, least strain). Adopt pymatgen's implementation
(`DESIGN.md` §2.3) rather than re-deriving. This is where "depth is
uneven" (`ARCHITECTURE.md` §5.4) is concrete: §7.3 bottomed out in one
level; this needs two.

`[DEPTH-FIRST · one level]` the small routines that are each one step
from code and need no sub-decomposition: `relaxed_lattice` /
`relaxed_bulk` / `biaxial_stiffness` (bulk relaxations under the
potential, `DESIGN.md` §2.2); `cleave_and_tile` and `ensure_thickness`'s
convergence study (`DESIGN.md` §2.5); `select_termination_by_surface_
energy`; `symmetrize_if_polar`'s four-strategy ladder (a future hook,
`DESIGN.md` §2.5); and `density_dividing_surface`, `drop_disconnected`,
`relieve_clash`, `assign_labeled_groups` (`DESIGN.md` §2.6).
