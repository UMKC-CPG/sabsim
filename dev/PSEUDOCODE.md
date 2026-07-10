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
> The skeleton runs the **Si/Si Wave-0 thread** (`ARCHITECTURE.md` §5.3):
> steps 1-2 skipped behind a classical potential stand-in, step 4
> stubbed, step 5 trivial (no lattice mismatch), step 8 mocked. Its
> headline number is deliberately **not trusted** — the point of the
> skeleton is that the data flows and the schemas hold.

---

<!-- Sections mirror the pass-1 list in ARCHITECTURE §5.4: the Tier-A
sequencer (§1), the run/study specification the sequencer loads (§2),
the structure AND trajectory contracts that cross the simulation steps
(§3), the measure-vector schema the analyzer emits (§4), and the
quality-gate precedence chain that reads it (§5). Section 6 assembles
them into the Wave-0 thread and shows exactly where the stand-ins sit.
Every record is CLOSED — no field references a type left undefined. -->

## 1. Tier-A sequencer — the top-level control flow

The sequencer owns the eight pipeline steps and the quality-gate loop
(`ARCHITECTURE.md` §4.1, Tier A). The configured object is a **study** —
**one or more** runs plus **optional** relations among them (`DESIGN.md`
§1.1). A study may hold a single system or several, run under different
conditions, and a relation may compare them across **any** of the
registered measures, not one privileged number. So the top entry point
runs each member run to a complete, self-standing report, then grades
whatever relations were declared — of which there may be none. **A study
of one run is fully valid:** it produces its report and no internal
comparison, and the human who runs it is free to compare that report
against anything else, outside the program.

```
function run_study(study_specification):
    # Entry point. A study is runs + relations (DESIGN §1.1). Each run
    # is executed independently; the relations (e.g. the Si/SiO2-to-
    # Si/Si ratio) are graded only after every run has produced its
    # measure vector.
    validated_study = load_and_validate_study(study_specification)

    run_results = empty_list
    for each run_specification in validated_study.runs:
        run_results.append(run_single(run_specification))

    # Relations are an OPTIONAL comparison layer, graded at the study
    # level (there may be none). A relation compares a subset of the
    # runs across one or more registered measures; v1's bond-outcome
    # ratio (DESIGN §7.4) is one such relation, not the only kind. With
    # no relations the study report is simply the per-run reports.
    study_report = evaluate_relations(validated_study.relations,
                                      run_results)

    emit_study(study_report, run_results)   # machine-readable output
    return study_report
```

```
function run_single(run_specification):
    # The eight-step pipeline for ONE run. In v1 the quality-gate loop
    # executes its body ONCE and reports (VISION principle 5); the
    # enclosing while-loop is the future automated target, shown so the
    # seam for it exists, but not iterated in v1.
    #
    # while not run_result.gate.passes:          # <- future closed loop
    #     training_data += data_targeting(run_result.gate.weaknesses)

    # The potential is a CONTRACT, not a fixed implementation. The
    # walking skeleton satisfies it with a classical pair_style
    # stand-in; the bootstrap wave (steps 1-2) later satisfies it with
    # the trained MLIP through the SAME seam (ARCHITECTURE §5.1).
    potential = resolve_potential(run_specification)   # W0: classical

    # Steps 3/4/5 order is a SETTING (ARCHITECTURE §2.1), so the
    # sequencer reads it rather than hardcoding build->amorphize->
    # assemble. The builder and activator are order-agnostic behind the
    # structure contract (ARCHITECTURE §5.3).
    structure = run_structure_stage(run_specification, potential)

    # Steps 6-7: press then pull, on the MLIP (here, the stand-in).
    trajectory = run_bond_debond_md(structure, potential,
                                    run_specification)

    # The analyzer turns the trajectory into a measure vector (DESIGN
    # §6). In W0 only the Imago-free mechanical measure is real; the
    # rest report `unresolved`.
    measures = run_analyzer(structure, trajectory, run_specification)

    # Step 8 characterization feeds additional measures. In W0 this is
    # MOCKED and returns schema-valid `unresolved` records.
    measures = merge_measures(
        measures,
        run_characterization(structure, trajectory, run_specification))

    # The gate READS the measure vector and REPORTS; it never edits a
    # measure and, in v1, never acts (DESIGN §7).
    gate_report = evaluate_run_gates(measures, run_specification,
                                     potential)

    run_result = record{
        specification: run_specification,
        potential:     provenance_of(potential),
        measures:      measures,
        gate:          gate_report,
    }
    emit_run(run_result)
    return run_result
```

The run's result is itself a contract — the seam between a run and the
study that may relate it to others (its `measures` and `gate` types are
defined in §4 and §5):

```
record RunResult:
    specification: RunSpecification   # what was asked for
    potential:     Provenance         # which potential generation ran
    measures:      MeasureVector      # everything the analyzer emitted
    gate:          GateReport         # the per-run diagnostic verdict
    trusted:       boolean            # default true; FALSE for a Wave-0
                                      # plumbing run whose number is not
                                      # to be believed (ARCHITECTURE §5.3)
```

**Each step is a contract-checked hand-off.** The sequencer launches a
step, waits, and validates the step's output against its contract before
launching the next (`ARCHITECTURE.md` §4.1); a step whose output fails
its contract stops the pipeline rather than propagating a bad artifact.
Linking is by file contracts on the shared filesystem, so "hand-off"
means "write a contract-valid artifact, then read it."

```
function run_step(step_callable, inputs, output_contract):
    artifact = step_callable(inputs)          # Tier-B/C work happens here
    validation = check_contract(artifact, output_contract)
    if not validation.ok:
        halt_pipeline(reason = validation.failure)   # gate, don't warn
    return artifact
```

`[DEPTH-FIRST]` the bodies of `run_structure_stage`,
`run_bond_debond_md`, `run_analyzer`, and `run_characterization` are the
per-module algorithms; pass 1 fixes only their signatures and the
contracts they exchange (§3, §4 below).

## 2. The run/study specification and its validator

The specification is the contract between the human and the pipeline
(`DESIGN.md` §1). Pass 1 captures the fields the skeleton actually
touches; the full five-group knob inventory is filled as modules land.

```
record Study:
    runs:      list of RunSpecification    # ONE or more
    relations: list of Relation            # zero or more (optional)

record RunSpecification:
    # Five knob groups (DESIGN §1.2), minus deployment, which lives in
    # a separate document the run spec cannot express (DESIGN §1.2).
    material:      MaterialKnobs   # per-wafer crystal + face + identity
    protocol:      ProtocolKnobs   # activation, press, separate settings
    numerical:     NumericalKnobs  # tolerances, cutoffs, strides, budgets
    ensemble:      EnsembleKnobs   # master seed + realization count
    potential_ref: string         # WHICH potential generation this run
                                  # uses — a content fingerprint, or the
                                  # classical stand-in marker in W0. The
                                  # potential's CONTENTS are not settings
                                  # (DESIGN §1.3); this POINTER is one,
                                  # for provenance (DESIGN §1.6, §6.6).

record MaterialKnobs:             # one per wafer; two wafers per run
    crystal_structure: string     # e.g. Si diamond, cristobalite
    surface_face:      Miller indices
    identity:          string     # the material itself
    # NEVER a lattice constant — §2.2 derives it from the potential
    # (DESIGN §1.3).

record ProtocolKnobs:
    # W0 touches press + separation; the activation fields are declared
    # but UNUSED in W0 (activation is stubbed). [DEPTH-FIRST] the energy/
    # angle DISTRIBUTIONS and the full field set: DESIGN §3 and §5.
    activation_species: string    # argon by default (DESIGN §1.2)
    activation_energy:  number
    activation_angle:   number
    activation_fluence: number    # ions per A^2, cell-size-independent
    press_control:      one of {load, displacement}   # DESIGN §5.2
    press_load:         number    # load or pressure reached
    press_depth:        number
    press_duration:     number
    separation_speed:   number    # the pull rate (DESIGN §5.4)

record NumericalKnobs:
    # W0 touches the pull-rate ladder, the analyzer noise floor, and the
    # trajectory frame stride. [DEPTH-FIRST] the full tolerance / cutoff
    # / stride / window / budget set.
    pull_rate_ladder: list of number  # >= 3 rates over a decade (§5.4)
    noise_floor:      number          # peak/curve threshold (§5.4)
    frame_stride:     integer         # store 1 frame per N MD steps
                                      # (e.g. 100-1000); NOT every step

record EnsembleKnobs:
    master_seed:       integer    # one master seed; per-realization
                                  # seeds are derived from it (DESIGN §1.2)
    realization_count: integer    # how many seeds to average over

record Relation:
    # A relation compares a subset of the study's runs across one or
    # more MEASURES (by name, DESIGN §6.6) — not one privileged number.
    # It is optional; the walking skeleton declares none.
    kind:     one of {ratio, sweep, ...}   # v1's bond gate is `ratio`
    members:  list of run-ids              # which runs it relates
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

    for each run in study.runs:
        # NO HIDDEN DEFAULTS: an incomplete specification is rejected,
        # not silently completed (DESIGN §1.4). Defaults exist only as a
        # separate generator that emits a fully-populated file to edit.
        reject_if_incomplete(run)

        # Validation rejects a spec that cannot be EXECUTED — a species
        # outside the potential's type map, a missing unit — never one
        # whose COMPARISONS would be hard to interpret (DESIGN §1.5).
        reject_if_not_executable(run)

    for each relation in study.relations:
        # REPORT, NEVER RESTRICT (DESIGN §1.1). A relation whose controls
        # disagree, or which is confounded by more than one contrast, is
        # still computed and still reported; only the gate's VERDICT is
        # withheld. So validation here computes the difference set and
        # flags confounds — it does not delete the relation.
        relation.difference_set = sort_differences(
            relation, study.runs)          # contrasted/entailed/incidental
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
Wave 0 the coincidence match is the identity (no lattice mismatch), so
the matcher is exercised for real only at the Si/SiO2 transition
(`ARCHITECTURE.md` §5.3, Wave 3).

`[DEPTH-FIRST]` the coincidence matcher (Zur-McGill search, `DESIGN.md`
§2.3), the strain split (`DESIGN.md` §2.4), slab cutting and termination
selection (`DESIGN.md` §2.5), and the density-profile dividing surface
(`DESIGN.md` §2.6).

**The trajectory contract (steps 6-7 → analyzer).** The press/pull hands
the analyzer a `Trajectory` (`DESIGN.md` §5.5). The reduced curves are
small and kept inline; the per-atom frames are large and kept **by
reference** on scratch (`ARCHITECTURE.md` §4.1, "large trajectory I/O").
**We never store every timestep.** Even the raw frame set is a *strided
subsample* — one stored configuration every, say, 100, 200, 500, or 1000
MD steps — so the number of stored frames is a small fraction of the
run's step count. That strided atomic-coordinate frame set is
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

In Wave 0 the analyzer needs only `force_vs_grip`, `reference_state`,
`separation_point`, and the two gate flags (`complete`,
`atom_count_conserved`) — M1's inputs. `force_vs_opening`, the σ_zz
series, and `grip_reaction` are populated but read only by deeper
measures and checks. Crucially the **`frames` reference is populated
too**: the MD stand-in writes an atomic-coordinate dump even though no W0
measure reads it, so the by-reference seam is real and exercised from the
start — the §8 selector and any human re-analysis inherit working
plumbing rather than a stub.

`[DEPTH-FIRST]` the reduction that produces the curves and scalar series
from the raw frames (`DESIGN.md` §5.5). The frame stride is a NUMERICAL
knob (`NumericalKnobs.frame_stride`, §2) — one stored configuration per N
steps, typically 100-1000, never every step — and `FrameSetRef.stride`
records the value a run actually used, for provenance.

## 4. The measure-vector schema (the analyzer's output)

The analyzer emits one machine-readable document per run; the gate reads
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
function run_analyzer(structure, trajectory, run_specification):
    # The analyzer is a REGISTRY of measures (DESIGN §6.7). Each measure
    # declares what it needs; the analyzer resolves those needs against
    # what the run produced, computes what it can, and marks the rest
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

In Wave 0 only **M1**, the mechanical work-integral, is a real computed
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
function evaluate_run_gates(measures, run_specification, potential):
    # Potential-quality gate (DESIGN §7.2-§7.3): is the MLIP good on its
    # own terms (bulk/surface) and at the interface? This is meaningful
    # for a run on its OWN terms, independent of any comparison. A
    # failure is a POTENTIAL problem -> the remedy is more training data.
    bulk_surface = check_bulk_surface(potential, measures)
    interface    = check_interface_fidelity(measures)   # STRUCTURAL 3

    # The five-way diagnosis routes the CAUSE of a questionable bond
    # number using those per-run signals (DESIGN §7.6). The bond-outcome
    # RATIO itself is a relation, graded at the study level (§1); a
    # single run has no ratio to grade.
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
function evaluate_relations(relations, run_results):
    # Study-level grading of the OPTIONAL comparison layer. With no
    # relations this returns nothing, and the study report is simply the
    # per-run reports. A relation grades its members across its declared
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
            reports.append(grade_relation(relation, run_results))
    return reports
```

In Wave 0 the study holds a single Si/Si run and declares **no**
relations, so there is nothing to grade and the study report is simply
that run's report — a study of one is fully valid (`DESIGN.md` §1.1).
The bond-outcome ratio first becomes gradable at the Si/SiO2 transition,
when a second run exists to relate; and even then, comparison remains an
optional layer the human may also perform outside the program.

`[DEPTH-FIRST]` `check_bulk_surface`, `check_interface_fidelity` (the
committee-uncertainty and all-electron cross-check math, `DESIGN.md`
§7.3), and `grade_relation` — dispatched by `kind`, of which the `ratio`
case carries the correlated-uncertainty propagation of `DESIGN.md` §7.4.

## 6. The Wave-0 thread, assembled

The skeleton is `run_single` with every deep call replaced by the
cheapest contract-satisfying stand-in (`ARCHITECTURE.md` §5.3). Nothing
below is trusted for physics; it exists so every seam is exercised under
real data flow.

```
function run_single_wave0(run_specification):
    potential = classical_pair_style(run_specification)    # steps 1-2
                                                           # SKIPPED
    slab      = cut_slab(run_specification, potential)     # step 3, real
    activated = stub_activation(slab)                      # step 4, STUB
    structure = assemble_pair(activated, activated,        # step 5,
                              run_specification)           # trivial Si/Si
    trajectory = press_then_pull(structure, potential,     # steps 6-7,
                                 run_specification)         # real
    measures  = run_analyzer(structure, trajectory,        # M1 real,
                             run_specification)             # M2-M5 unres.
    measures  = merge_measures(measures,
                               mock_characterization())    # step 8 MOCK
    gate      = evaluate_run_gates(measures, run_specification,
                                   potential)
    return record{ measures: measures, gate: gate,
                   trusted: false }        # W0 number is a plumbing test
```

**What each stand-in must still honour:** `stub_activation` returns a
valid `Structure` (§3) even though it does not amorphize;
`mock_characterization` returns schema-valid `unresolved` MeasureRecords
(§4); `classical_pair_style` satisfies the same potential contract the
trained MLIP will; and `press_then_pull` writes the strided atomic-
coordinate dump so `Trajectory.frames` (§3) is populated even though no
W0 measure reads it — the by-reference seam is exercised, not stubbed.
The moment a stand-in's output stops satisfying its contract, the
skeleton stops running — which is the signal the contract, not the
module, needs attention (`ARCHITECTURE.md` §5.1).

`[DEPTH-FIRST]` `cut_slab`, `assemble_pair`, and `press_then_pull` are
real in Wave 0 but their algorithm bodies are written in the structure
and MD depth-first passes; here they are contract signatures only.
