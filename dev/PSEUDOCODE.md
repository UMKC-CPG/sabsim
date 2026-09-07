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
> steps 1-2 skipped behind a stand-in potential, step 4
> stubbed, step 5 trivial (no lattice mismatch), step 8 mocked. Its
> headline number is deliberately **not trusted** — the point of the
> skeleton is that the data flows and the schemas hold.

---

<!-- Sections mirror the pass-1 list in ARCHITECTURE §5.4: the Tier-A
sequencer (§1), the pair/project specification the sequencer loads (§2),
the structure AND trajectory contracts that cross the simulation steps
(§3), the measure-vector schema the analyzer emits (§4), and the
quality-gate precedence chain that reads it (§5). Section 6 assembles
them into the walking-skeleton configuration and shows where the
stand-ins sit.
Every record is CLOSED — no field references a type left undefined. -->

## 1. Tier-A sequencer — the top-level control flow

The sequencer owns the eight pipeline steps and the quality-gate loop
(`ARCHITECTURE.md` §4.1, Tier A). The configured object is a **project**
— exactly **one wafer pair** in one project folder (`DESIGN.md` §1.1,
revised 2026-08-30 (Paul)). A project holds no list of "members" and no
relations: a reference pair (Si/Si beside a Si/SiO2 question) is a
SEPARATE project folder the person makes and runs themselves, and the
comparison between the two is theirs to draw, by hand, from the two
reports. So the top entry point runs the one pair to a complete,
self-standing report and stops. The word "member" is thereby freed to
mean only a COMMITTEE member (§11, `DESIGN.md` §4.4).

The pair runs as FOUR stage folders in the project (`ARCHITECTURE.md`
§1): `prep_surf1_<a>/` and `prep_surf2_<b>/` prepare the two surfaces
INDEPENDENTLY (each builds its own half in the pair's shared cell,
bombards it, heals it and gates it), `bond_<a>_<b>/` brings the two
prepared halves together and pulls them apart, and `analysis_<a>_<b>/`
turns the pull into the measure vector. The whole-chain form below runs
those four in order in one process (a login-node dry run, a small test);
§14 cuts the same chain into four submitted jobs, the two preps side by
side.

```
function exec_full_project(project_specification):
    # Entry point. A project is ONE pair (DESIGN §1.1, 2026-08-30). The
    # project folder is where the project file sits; the loader records
    # it, and every stage folder hangs off it (ARCHITECTURE §1). The
    # stages' bulky intermediates go in the folder's scratch mirror,
    # threaded EXPLICITLY from here so every written byte stays traceable
    # to its inputs (VISION goal 3).
    validated_project = load_and_validate_project(project_specification)
    pair_result = exec_one_pair(validated_project.pair,
                                validated_project.project_directory)
    emit_project(pair_result)         # machine-readable output
    return pair_result
```

```
function exec_one_pair(pair_specification, project_directory):
    # The eight-step pipeline for ONE pair, run as its four stage folders
    # in order. Each file-writing stage receives ITS OWN stage folder
    # (deliverables) and that folder's scratch mirror (bulk), threaded in
    # explicitly (ARCHITECTURE §4.3, VISION goal 3):
    #
    #   folders = stage_folders(pair_specification)      # §2, ONE place
    #   prep_1  = stage_scratch(project_directory, folders.prep_surf1)
    #   prep_2  = stage_scratch(project_directory, folders.prep_surf2)
    #   bond    = stage_scratch(project_directory, folders.bond)
    #   analysis = stage_scratch(project_directory, folders.analysis)
    #
    # In v1 the quality-gate loop executes its body ONCE and reports
    # (VISION principle 5); the enclosing while-loop is the future
    # automated target, shown so the seam for it exists, but not
    # iterated in v1.
    #
    # while not pair_result.gate.passes:            # <- future closed loop
    #     training_data += data_targeting(pair_result.gate.weaknesses)
    #
    # EVERY stage below is routed through run_to_contract (defined after
    # this function): run the stage, then HALT unless its output
    # satisfies the contract the next stage depends on. That is what
    # makes "the pipeline always runs" safe (ARCHITECTURE §5.1) — it runs
    # until a stage produces a contract-invalid artifact, then stops
    # loudly instead of corrupting everything downstream.

    # The potential is a CONTRACT, not a fixed implementation. Today
    # the universal foundation MLIP satisfies it as a committee of one
    # (the project file's [potential] block names it); the bootstrap
    # (steps 1-2) later satisfies it with the trained committee through
    # the SAME seam (ARCHITECTURE §5.1).
    #
    # WHAT LIVES BEHIND THIS SEAM (the /refine marker). resolve_potential
    # LOOKS UP a fingerprinted, already-manufactured potential (the
    # potential_ref of DESIGN §1.6); it does NOT train one inline. The
    # manufacturing is the bootstrap loop (§11, DESIGN §4.5), a SEPARATE
    # top-level process that runs UPSTREAM of every pair. That placement
    # decides WHERE the potential-quality gate ACTS: the bootstrap's
    # convergence criterion (§11.6) IS the acting form of the §5 gate --
    # inside it the potential is still mutable, so a fail DRIVES the loop.
    # By the time a pair reaches HERE the potential is FROZEN, so the
    # same gate can only REPORT (§5, evaluate_pair_gates). The
    # production-side bulk/surface check reads as a reporter for THAT
    # reason, not by oversight -- DESIGN §7.2's "gate the build" is
    # discharged upstream, where acting is still possible.
    potential = run_to_contract(
        () -> resolve_potential(pair_specification),   # today: the
                                                          # foundation
                                                          # MLIP, alone
        POTENTIAL_CONTRACT)

    # Steps 3-4-5 are three SEPARATE stages in a FIXED order:
    # build -> activate -> assemble. The order is not a setting and no
    # reorder engine is owed (ARCHITECTURE §2.1, §5.3, retracted
    # 2026-07-23) -- activating each surface alone in vacuum, before the
    # halves meet, is what surface-activated bonding IS. What the spec
    # does choose is whether activation runs AT ALL: with it off the
    # builder emits the crystalline pair in one piece (the Si/Si null
    # path) and the activate stage is skipped entirely.

    # PREP, one surface at a time (revised 2026-08-30 (Paul)). Steps 3
    # and 4 for ONE wafer: relax both bulks and solve the pair's shared
    # cell (deterministic, so both preps reach the same cell), build
    # THIS half in it (§7.1 build_half), then cascade, heal and gate it
    # in one session (§10.1). The healed, gated half is written to the
    # prep folder as that stage's DELIVERABLE — the file the bond stage
    # reads. Nothing about the other wafer is touched, so the two calls
    # are independent and §14 submits them as two side-by-side jobs.
    # ACTIVATED_HALF_CONTRACT checks the half is amorphized AND passed
    # the §3.5 gate; a failure HALTS here, before any assembly.
    activated_A = run_to_contract(
        () -> prepare_surface(WAFER_A, pair_specification, potential,
                              prep_1),
        ACTIVATED_HALF_CONTRACT)
    activated_B = run_to_contract(
        () -> prepare_surface(WAFER_B, pair_specification, potential,
                              prep_2),
        ACTIVATED_HALF_CONTRACT)

    # BOND. Step 5 — read both deliverables back, check that the two
    # halves carry the SAME lateral cell (each prep solved it alone; a
    # disagreement means the two preps did not run from the same project
    # file and is a loud stop), then assemble the facing pair (§7.5).
    structure = run_to_contract(
        () -> assemble_pair(activated_A, activated_B, pair_specification,
                            bond),
        STRUCTURE_CONTRACT)

    # Steps 6-7: the bond flow, on the MLIP committee (here, the stand-in).
    # The pair arrives already healed and gated, so the bond flow is the
    # one-time lateral cell relax (§9.1, DESIGN §5.6), then press, settle
    # and pull. The result is a BondDebondResult (§9.1): one press
    # outcome + one reference + a per-rate list of pulls, NOT a bare
    # Trajectory (§5.4's rate ladder). Its manifests and ledgers are the
    # bond folder's deliverables; its dumps stay in the mirror.
    bond_debond_trajectory = run_to_contract(
        () -> run_bond_debond_md(structure, potential, pair_specification,
                                 bond),
        BOND_DEBOND_CONTRACT)

    # ANALYSIS. The analyzer turns that result into a measure vector
    # (DESIGN §6): it reads the press outcome into the Verdicts and
    # iterates the per-rate pulls (§4). In the skeleton only the
    # Imago-free mechanical measure is real; the rest report
    # `unresolved`. The measure vector is the analysis folder's
    # deliverable.
    measures = run_to_contract(
        () -> run_analyzer(structure, bond_debond_trajectory,
                           pair_specification, analysis),
        MEASURE_VECTOR_CONTRACT)

    # Step 8 characterization feeds additional measures. In the skeleton
    # this is MOCKED and returns schema-valid `unresolved` records.
    characterization = run_to_contract(
        () -> run_characterization(structure, bond_debond_trajectory,
                                   pair_specification),
        MEASURE_VECTOR_CONTRACT)
    measures = merge_measures(measures, characterization)

    # The gate READS the measure vector and REPORTS; it never edits a
    # measure and, in v1, never acts (DESIGN §7). It is the terminal
    # reader, not a hand-off to a further stage, so it is not itself
    # wrapped; the pair's OWN output (PairResult) is the last contract,
    # checked at the pair->project seam (§1's exec_full_project and
    # emit_pair).
    gate_report = evaluate_pair_gates(measures, pair_specification,
                                      potential)

    pair_result = record{
        specification: pair_specification,
        potential:     provenance_of(potential),
        measures:      measures,
        gate:          gate_report,
    }
    emit_pair(pair_result)
    return pair_result
```

The pair's result is itself a contract — the seam between the pair and
the project report the person reads and, by hand, compares with other
projects (its `measures` and `gate` types are defined in §4 and §5):

```
record PairResult:
    specification: PairSpecification   # what was asked for
    potential:     Provenance         # which potential generation ran
    measures:      MeasureVector      # everything the analyzer emitted
    gate:          GateReport         # the per-pair diagnostic verdict
    trusted:       boolean            # default true; FALSE for a
                                      # walking-skeleton plumbing pair
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
contracts are `ACTIVATED_HALF_CONTRACT` (one half built in the shared
cell, amorphized, healed AND passed its §3.5 gate — the prep stage's
deliverable, revised 2026-08-30 (Paul): each surface is prepared alone,
so the contract is per half, and the gate verdict rides with it).
`POTENTIAL_CONTRACT` is the one
exception — not a record of ours but the external potential's loadable
`pair_style` interface (its *quality* is judged separately by the §5
gate — as a REPORT here, and as the ACTING convergence check inside the
bootstrap, §11.6, that manufactured it; the guard here only checks it is
a usable potential the pair looks up by fingerprint).

`[DEPTH-FIRST]` the bodies of the structure stages (`build_half` /
`assemble_pair`, now in §7), `prepare_surface`, `run_bond_debond_md`,
`run_analyzer`, and `run_characterization` are the per-module algorithms;
pass 1 fixes only their signatures and the contracts they exchange
(§3, §4). `check_contract` and `halt_pipeline` are likewise
contract-level here: the actual schema-validation logic is a depth-first
concern.

## 2. The pair/project specification and its validator

The specification is the contract between the human and the pipeline
(`DESIGN.md` §1). Pass 1 captures the fields the skeleton actually
touches; the full five-group knob inventory is filled as modules land.
A project file describes exactly ONE wafer pair (revised 2026-08-30
(Paul)): there is no list of pairs and no relation between pairs; the
person who wants a reference pair makes a second project folder.

```
record Project:
    pair:              PairSpecification   # exactly ONE
    project_directory: path                # the folder the project file
                                           # sits in, set by the loader
                                           # from the file's own location
                                           # — never typed (ARCH §1)

record PairSpecification:
    # Five knob groups (DESIGN §1.2), minus deployment, which lives in
    # a separate document the pair spec cannot express (DESIGN §1.2).
    # There is NO name field: the pair is identified by its derived
    # pair_label (stage_folders, below), never by a typed label.
    material:      MaterialKnobs   # per-wafer crystal + face + identity
    protocol:      ProtocolKnobs   # activation, press, separate settings
    numerical:     NumericalKnobs  # tolerances, cutoffs, strides, budgets
    ensemble:      EnsembleKnobs   # master seed + two realization counts
    potential_ref: string         # WHICH potential generation this pair
                                  # uses — a content fingerprint, or the
                                  # foundation-MLIP stand-in's name
                                  # today. The potential's CONTENTS are
                                  # not settings
                                  # (DESIGN §1.3); this POINTER is one,
                                  # for provenance (DESIGN §1.6, §6.6).

record MaterialKnobs:             # one per wafer; two wafers per pair
    cif_source:        path        # AUTHORITATIVE crystal (a CIF):
                                   # symmetry/basis/connectivity, serves
                                   # ANY material (DESIGN §1.2)
    crystal_structure: string      # a human LABEL (e.g. "diamond"); the
                                   # CIF is authoritative, never this
    surface_face:      Miller indices
    identity:          string      # the material itself; lower-cased
                                   # it is ALSO the suffix of this
                                   # wafer's preparation folder in the
                                   # project (DESIGN §1.2, ARCHITECTURE
                                   # §1; revised 2026-08-30 (Paul))
    preparation_directory: path    # <project>/prep_surfN_<label>, N = 1
                                   # for wafer_a and 2 for wafer_b,
                                   # label = lower(identity); set by the
                                   # loader from the project file's own
                                   # location — never typed. Holds the
                                   # recipe, one subfolder per single-
                                   # material calculation, the
                                   # environment library, and the
                                   # amorphization of THIS surface
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
    required_activated_depth: number  # how deep the activated skin MUST
                                  # reach: the §10.6 depth metric's
                                  # threshold AND the depth the §7.2
                                  # thickness floor builds for (DESIGN
                                  # §3.5/§2.5, revised 2026-08-28). A
                                  # project choice, not a material fact
    # NO library path here (revised 2026-08-29, Paul, after LEDGER
    # T-39): the environment library the §10.6 gate judges against is
    # found PER WAFER at MaterialKnobs.preparation_directory /
    # environment_library.toml, never named in the project file. The
    # validator refuses a library whose recorded model is not
    # [potential] universal_model, or whose surfaces lack its wafer's
    # face.
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
    contact_gap_threshold:  number    # dividing-surface opening below
                                      # which, with the stress confirmed,
                                      # contact is declared (§9.3, §5.2)
    contact_gap_window:     integer   # chunks the opening is averaged
                                      # over before that test (§9.3);
                                      # one reading jumps when a loose
                                      # atom crosses the gap
    contact_stress_floor:   number    # |running-mean normal stress| that
                                      # confirms contact, of EITHER sign
                                      # (compression, or the tension of
                                      # an already-bonded interface)
    contact_stress_window:  integer   # chunks that running mean spans
                                      # (§9.3, §5.2; 2026-08-28)
    control_interval:       number    # TIME the driver advances between
                                      # read-backs: the resolution of the
                                      # contact test, the stage ledger and
                                      # the settle series (§5.2)
    press_time_budget:      number    # TIME the press may search for
                                      # contact before reporting "no
                                      # contact" (§9.3, §5.2)
    settle_duration:        number    # TIME the zero-load reference
                                      # equilibrates before its gates
                                      # (§9.4, §5.3)
    depth_bin_width:        number    # LENGTH of one horizontal layer
                                      # of the §10.6 disorder-versus-
                                      # depth profile (DESIGN §3.5,
                                      # 2026-08-29); refine it and the
                                      # depth must converge
    disorder_scatter_multiple: number # how many library thermal
                                      # scatters away an atom's
                                      # environment may sit and still
                                      # be "crystalline" (§10.6). Also
                                      # numerical: the §1.2 test
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

# The four stage folders of a project are named in ONE place, so the
# layout (ARCHITECTURE §1) is never written down twice. Prefix = the
# stage, suffix = the wafer material label(s), lower-cased so the names
# are shell-friendly; `surf1`/`surf2` fix which wafer is which, so a
# homo pair (Si on Si) still has two distinct surfaces.
function stage_folders(pair):
    a = lower(pair.material.wafer_a.identity)
    b = lower(pair.material.wafer_b.identity)
    return record{
        pair_label: a + "_" + b,               # "si_sio2", "si_si"
        prep_surf1: "prep_surf1_" + a,         # surface 1 (wafer A)
        prep_surf2: "prep_surf2_" + b,         # surface 2 (wafer B)
        bond:       "bond_" + a + "_" + b,     # assemble..pull
        analysis:   "analysis_" + a + "_" + b, # the measure vector
    }
```

```
function load_and_validate_project(project_specification):
    project = deserialize(project_specification)   # [DEPTH-FIRST] format
    project.project_directory = parent folder of the project file,
                                resolved                 # ARCHITECTURE §1
    pair = project.pair
    # The loader stamps each wafer's preparation folder from the folder
    # the project file sits in and the stage_folders naming (above): a
    # derived path, never a typed one.
    folders = stage_folders(pair)
    pair.material.wafer_a.preparation_directory =
        project.project_directory / folders.prep_surf1
    pair.material.wafer_b.preparation_directory =
        project.project_directory / folders.prep_surf2

    # NO HIDDEN DEFAULTS: an incomplete specification is rejected,
    # not silently completed (DESIGN §1.4). Defaults exist only as a
    # separate generator that emits a fully-populated file to edit.
    reject_if_incomplete(pair)

    # Validation rejects a spec that cannot be EXECUTED — a species
    # outside the potential's type map, a missing unit — never one
    # whose COMPARISONS would be hard to interpret (DESIGN §1.5).
    reject_if_not_executable(pair)

    # The environment library the §10.6 gate judges against is a
    # run-time input like the weights, and its checks must OPEN the
    # library file to compare model, engine, faces and temperature —
    # so they belong to phase THREE, the "do the referenced files
    # exist and make sense" phase that also opens the weights and
    # crystal files (DESIGN §1.5; revised 2026-08-29 (Paul) from an
    # earlier phase-2 placement). check_environment_libraries(pair)
    # runs there, on the login node, for EACH WAFER against that
    # wafer's own library (its prep folder, DESIGN §1.2), with the same
    # refusals and the temperature warn/refuse band as
    # load_environment_library (§10.6), so a mismatch costs no
    # node-hour. A wafer whose prep folder has no library yet is named
    # in the refusal, so the person knows which surface still needs
    # `sabsim bootstrap generate` (§11.3) or a copied prep folder.

    # No relations to validate (revised 2026-08-30 (Paul)): the project
    # holds one pair, and any comparison against a reference pair is
    # the person's, drawn by hand from two project reports.
    return project
```

`[DEPTH-FIRST]` `deserialize` (the on-disk format), the exact protocol
**content fingerprint** (`DESIGN.md` §1.4).

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
records the value a pair actually used, for provenance.

## 4. The measure-vector schema (the analyzer's output)

The analyzer emits one machine-readable document per pair — the
`measure_vector` that is the analysis folder's deliverable
(`ARCHITECTURE.md` §1) — and the gate reads it **by name and status,
never by position** (`DESIGN.md` §6.6). A gate
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
                      pair_specification, analysis_folder):
    # The analyzer is a REGISTRY of measures (DESIGN §6.7). Each measure
    # declares what it needs; the analyzer resolves those needs against
    # what the pair produced, computes what it can, and marks the rest
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
    # do with it: evaluate_pair_gates (below) READS the verdict into the
    # five-way diagnosis; the bootstrap's convergence check (§11.6) ACTS on
    # `.passes` to drive its loop. Identical gate, opposite consequence --
    # exactly the §1 marker's "acts upstream, reports downstream."
    bulk_surface = check_bulk_surface(potential, measures)   # §7.2 half
    interface    = check_interface_fidelity(measures)   # §7.3, STRUCTURAL 3
    return PotentialQualityVerdict{
        bulk_surface: bulk_surface, interface: interface,
        passes: (bulk_surface.passes and interface.passes) }

function evaluate_pair_gates(measures, pair_specification, potential):
    # The potential-quality gate is READ here, not acted on -- v1's gate
    # reports (DESIGN §7, VISION principle 5). A failure is a POTENTIAL
    # problem -> the remedy is more training data.
    quality = potential_quality_gate(potential, measures)   # DESIGN §7.2-3

    # The five-way diagnosis routes the CAUSE of a questionable bond
    # number using those per-pair signals (DESIGN §7.6). The bond-outcome
    # RATIO against a reference pair is NOT graded here or anywhere in
    # the program (revised 2026-08-30 (Paul)): the reference pair is its
    # own project, and the person forms the ratio from the two reports.
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

**No relation layer (revised 2026-08-30 (Paul)).** Earlier passes
carried an `evaluate_relations` step that graded a declared comparison
between two pairs of one study — v1's Si/SiO2-to-Si/Si work-of-
separation ratio (`DESIGN.md` §7.4) against experiment. That machinery
is retired with the study object itself: a project is one pair, the
reference pair is a second project folder, and the ratio, its
correlated uncertainty, and the honest list of everything that differs
between the two runs are the person's to assemble from the two measure
vectors. The program's whole job at this seam is to hand over a
complete, self-describing report per pair (`DESIGN.md` §1.1: report,
never restrict).

`[DEPTH-FIRST]` `check_bulk_surface` and `check_interface_fidelity`
(the committee-uncertainty and all-electron cross-check math,
`DESIGN.md` §7.3).

## 6. The walking-skeleton configuration

This is **not a separate function.** It is `exec_one_pair` (§1) in the
**walking-skeleton build phase** (`ARCHITECTURE.md` §5.3 calls it Wave 0),
showing what each stage RESOLVES to when the cheapest contract-satisfying
stand-in sits behind its contract. Same code path — the stand-ins are
injected, not branched to. Nothing below is trusted for physics; it
exists so every seam is exercised under real data flow.

```
# exec_one_pair, each stage resolved to its walking-skeleton stand-in:
    potential  = stand_in_pair_style(...)       # steps 1-2 SKIPPED
    activated_A = stub_prepare_surface(WAFER_A)  # prep_surf1: build the
    activated_B = stub_prepare_surface(WAFER_B)  # half for real (§7.1),
                                                # activation STUBBED;
                                                # each returns an
                                                # ActivatedHalf (§10.1)
    structure  = assemble_pair(activated_A,     # bond: step 5, trivial
                               activated_B)     # (Si/Si)
    bond_debond_trajectory = press_then_pull(structure)   # steps 6-7,
                                                          # real
    measures   = run_analyzer(structure,               # M1 real, the
                              bond_debond_trajectory)   # rest unresolved
    measures   = merge mock_characterization()  # step 8, MOCK
    gate       = evaluate_pair_gates(measures)
    # -> the resulting PairResult.trusted is FALSE (a plumbing pair)
```

**What each stand-in must still honour:** `stub_prepare_surface`
returns an `ActivatedHalf` (§10.1) whose slab satisfies the amorphization
contract and carries a passing verdict, written to the prep folder like
the real one, so §1's per-half handoff is exercised, not special-cased;
`mock_characterization`
returns
schema-valid `unresolved` MeasureRecords (§4); `stand_in_pair_style`
satisfies the same potential contract the trained MLIP will; and
`press_then_pull` writes the strided atomic-coordinate dump so
`Trajectory.frames` (§3) is populated even though no walking-skeleton
measure reads it — the by-reference seam is exercised, not stubbed. The
moment a stand-in's output stops satisfying its contract, the pipeline
stops — which is the signal the contract, not the module, needs
attention (`ARCHITECTURE.md` §5.1).

`[DEPTH-FIRST]` `build_half`, `assemble_pair`, and `press_then_pull` are
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

  solve_shared_cell  ->  build_half (x2)  --[activate]-->  assemble_pair

`[RESOLVED → §1]` pass-1's `exec_one_pair` collapsed steps 3-4-5 into
one `run_structure_stage` call, hiding activation. §1 now calls the
stages explicitly — `build_half` inside each surface's `prepare_surface`
(the separate activation module, `DESIGN.md` §3, follows it in the same
prep stage) -> `assemble_pair` — matching the honest form the
walking-skeleton configuration (§6) already showed. Applied at the
programmer's direction; `run_structure_stage` is retired. Revised
2026-08-30 (Paul): the two halves are built by two INDEPENDENT prep
stages, each solving the shared cell for itself, rather than by one
`build_slabs` call that made both.

### 7.1 The module's top-level shape

```
function prepare_surface(wafer, pair_specification, potential,
                         prep_folder):
    # ONE prep stage (revised 2026-08-30 (Paul)): steps up to and
    # including 3 for THIS wafer, then step 4 (§10.1), then the write of
    # the DELIVERABLE. Runs with no knowledge of the other wafer beyond
    # its crystal, which the shared cell needs; so the two calls are
    # independent and §14 submits them side by side. prep_folder is the
    # stage's folder in the project (deliverables) with its scratch
    # mirror (bulk) alongside (ARCHITECTURE §1, §4.3).
    handle    = build_half(wafer, pair_specification, potential,
                           prep_folder.scratch)                   # §7.1
    activated = activate_surface(handle, pair_specification,
                                 potential)                       # §10.1
    # The deliverable: the healed, gated half as a data file plus a
    # manifest carrying its verdict, its shared cell (so the bond stage
    # can check the two halves agree), its measured skin and the run it
    # came from. Written to the PROJECT folder, not the mirror, because
    # it is small and the bond stage reads it (§14.6 artifact form).
    write_artifact(prep_folder.project, ACTIVATED_HALF, activated)
    return activated

function build_half(wafer, pair_specification, potential,
                    scratch_directory):
    # Steps up to and including step 3, for ONE wafer. The result is a
    # STANDALONE half-cell in its OWN vacuum box (build_slab adds the
    # vacuum, §7.4) — NOT the assembled pair — WRITTEN to a data file
    # under scratch_directory and returned as a HALF-HANDLE the
    # activation stage loads on its own engine (ARCHITECTURE §4.3).
    # build_half is the FIRST stage to write real files, so the caller
    # threads it the stage's scratch directory EXPLICITLY (traceable,
    # never rebuilt from identity — VISION goal 3). assemble_pair (§7.5)
    # reads the two AMORPHIZED halves back only after both preps.
    # Building the pair crystalline in one step is the activation-OFF
    # null path (Si/Si, no cascade).
    material_A, material_B = pair_specification.material   # two wafers
    numerical              = pair_specification.numerical

    # The shared cell is solved ONCE PER PREP, on the two SUBSTRATE
    # lattices, and is an invariant of the pair (DESIGN §2.1, §2.3):
    # both preps run the same deterministic solve on the same two
    # crystals and reach the same cell, which the bond stage verifies.
    # It reads two numerical knobs: the misfit tolerance and the
    # atom-area budget.
    shared = solve_shared_cell(material_A, material_B, potential,
                               numerical.misfit_tolerance,
                               numerical.max_coincidence_area)

    # Split the small residual misfit between the slabs (DESIGN §2.4).
    strain_A, strain_B = split_strain(shared, material_A, material_B,
                                      potential)
    material, strain = (material_A, strain_A) if wafer is WAFER_A
                       else (material_B, strain_B)

    # The half DECLARES the beam species (the activation projectile plus
    # any co-deposit) in its type map though it contains none yet: the
    # cascade CREATES those atoms, and the simulator can only make an atom
    # of a type its data file already declared (§10.3). Wafer A is built as
    # the bottom half, B as the top — the assembly invariant (DESIGN §2.6).
    beam = projectile_species(pair_specification)            # §10.3
    # write_standalone_half writes the data file and stamps the HANDLE:
    # WHICH wafer a half plays (bottom A / top B) is an assembly-ROLE fact,
    # not a geometry fact, so it lives on the handle, not on the slab —
    # build_standalone_half stays wafer-agnostic.
    return write_standalone_half(
        build_standalone_half(material, shared, strain, beam,
                              potential, pair_specification),
        wafer, shared, scratch_directory)
```

```
record SharedCell:
    lateral_cell:    Cell                 # the shared coincidence cell
    tiling_A:        2x2 integer matrix    # whole-number tiles of A
    tiling_B:        2x2 integer matrix    # whole-number tiles of B
    twist:           angle                 # relative in-plane rotation
    residual_strain: StrainTensor          # misfit left after the match

record HalfHandle:
    # What build_half hands the activation stage for ONE half: everything
    # needed to amorphize it, and NOTHING about the other half, so each is
    # a self-contained fan-out unit (the # C-EXPANSION unit, §4.3). The
    # activation stage RE-READS the slab geometry from data_file, never a
    # warm in-memory object, so the unit is restartable after a crash and
    # identical whether it runs in the whole-chain process or its own
    # prep job (the normal case, §14).
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
    shared:    SharedCell # the cell this half was built in, carried so
                          # the bond stage can check both halves agree
```

A `Slab` is just a `Structure` (§3) for one material — one provenance
label, and `grips` not yet set (assembly sets them, §7.5). Across the
build→amorphize seam a half travels as a `HalfHandle` — its file plus the
few facts the cascade needs — never as a live object (`ARCHITECTURE.md`
§4.3 file handoff). Across the prep→bond seam it travels as the
ACTIVATED_HALF artifact the prep folder holds (§14.6).

### 7.2 solve_shared_cell — lattices from the potential, then the match

```
function solve_shared_cell(material_A, material_B, potential,
                           misfit_tolerance, max_coincidence_area):
    # Lattices come from the POTENTIAL, not literature (DESIGN §2.2):
    # load each crystal from its CIF (material.cif_source — symmetry and
    # basis, DESIGN §1.2) and relax the bulk under the current model,
    # referenced to VASP. At the COLD START the current model is the
    # UNIVERSAL foundation MLIP — the SAME model that runs the step-4
    # cascade — so the derived cell and the amorphizing potential agree
    # (DESIGN §2.2/§4.7: a cell equilibrated under one description and
    # bombarded under another starts stressed, the oxide-bring-up offset).
    # Because the universal model loads only in the deepmd bundle, the
    # relaxation runs OUT-OF-PROCESS (box/relax + minimize + write_data,
    # read back with read_data_box; ARCHITECTURE §4.4), mirroring the
    # cascade handoff. The relaxed-vs-VASP disagreement is itself a potential-
    # quality measure (DESIGN §2.2, §7-of-DESIGN) — recorded, not discarded.
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
                    pair_specification):
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
    #   slab_thickness >= required_activated_depth + minimum_bulk_thickness
    # The depth term is the project's REQUIREMENT on the activation (the
    # same number the §10.6 gate demands), because the build runs before
    # the gate has measured anything; v1 fixes thickness by a short
    # convergence study, applies this as a FLOOR, and records the margin.
    ensure_thickness(slab,
        pair_specification.protocol.required_activated_depth,
        pair_specification.numerical.minimum_bulk_thickness)

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
function assemble_pair(activated_A, activated_B, pair_specification,
                       bond_folder):
    # Step 5, the BARRIER stage: the first to see BOTH halves — the two
    # ACTIVATED_HALF deliverables the prep folders hold (§7.1, §14.6).
    # Before anything else it checks the two halves' recorded shared
    # cells AGREE (each prep solved the cell alone): a mismatch means the
    # preps did not come from one project file, and is a loud stop.
    #     if activated_A.shared != activated_B.shared: halt(...)
    #     shared = activated_A.shared
    #     slab_A, slab_B = activated_A.slab, activated_B.slab
    # In the real pipeline each half is AMORPHIZED by now, read back from
    # the data file
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
    # two dividing surfaces. Revised 2026-08-28 (Paul, §3.4): both halves
    # arrive HEALED and GATED from the activate stage, so this gap is the
    # opening the press starts from — near contact, the two faces within
    # range but not yet loading each other (DESIGN §2.6). Then check the
    # minimum cross-slab distance; if it violates the clash floor, back
    # the gap off and RECORD the adjustment rather than aborting the
    # pair (DESIGN §2.6).
    pair = place_facing(slab_A, slab_B, surface_A, surface_B,
                        pair_specification.protocol.initial_gap)
    pair = relieve_clash(pair,
                        pair_specification.numerical.clash_floor)

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
        # The pair's structure measures go `unresolved` with this
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
future sweep dimension), where it would wrap the enumerator in an outer
loop over grid angles. `DESIGN.md` §2.3 now carries this reconciliation
directly — its earlier "over a grid" wording was updated to the
discovered-twist reading.

**7.6.2 The Si/Si null test.** For identical lattices the identity
tiling matches exactly at zero strain and is trivially the smallest
zero-strain cell, so the search returns identity tiling, zero twist,
zero strain (`DESIGN.md` §2.3). The walking-skeleton Si/Si pair (§6)
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
        relaxed_pieces = map(anneal_then_minimize, pieces)
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
relaxed snapshots), `anneal_then_minimize` (relaxed pieces; SCHEDULE is a
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
    # BOND_DEBOND_CONTRACT). One press, one reference, many pulls. The
    # §3.5 activation verdicts ride each ActivatedHalf (§10.1) again
    # from 2026-08-28; between 2026-08-08 and then they rode this record.
    press:        PressOutcome         # step 6 (§5.1, §5.2)
    reference:    StateRef             # gated zero-load reference (§5.3)
    pulls:        list of Trajectory   # one §3 Trajectory per pull rate

record PressOutcome:
    bonded:           boolean   # verdict at the specified load (§5.1)
    contact_quality:  number    # graded; reuses §8.8 geometric machinery
    bonded_structure: StateRef  # the held, relaxed bonded state
    load_reached:     number    # BOTH load AND depth are reported (§5.2)
    depth_reached:    number
    stage_steps:      StageLedger  # the MD step each phase began/ended
                                   # at (DESIGN §5.5, §5.7, 2026-08-28)

record StageLedger:
    # The press and settle RECORD where their phases fall in the MD step
    # count, so a consumer of the recorded trajectory — the analyzer, a
    # viewer, the bootstrap harvest (§11.3) — keys a frame to its phase
    # by the step every dump frame carries, never by guessing from its
    # position in the file. Written into the bond result manifest.
    press_start:     integer   # drive installed, first press chunk begins
    contact:         integer   # the dual criterion fired (§9.3)
    hold_end:        integer   # end of the hold at temperature
    settle_start:    integer   # drive released, settle minimize begins
    settle_end:      integer   # the gated reference written (§9.4)
```

```
function run_bond_debond_md(structure, potential, pair_specification,
                            bond_folder):
    # bond_folder: the stage's project folder (manifests, ledgers) with
    # its scratch mirror (dumps, logs, data files) alongside (ARCH §1).
    driver = open_lammps_driver(structure, potential,
                                pair_specification)   # §9.2, persistent

    # The structure arrives HEALED and GATED (§10, revised 2026-08-28
    # (Paul)): each half was annealed, minimized and judged in its own
    # cascade session, and the pair is assembled at the press-start
    # opening (§7.5). The bond flow's first act is the ONE-TIME lateral
    # cell relax of DESIGN §5.6 — the shared in-plane cell to zero
    # in-plane stress, then FROZEN for the whole press, settle and pull;
    # it needs the joint cell, which is why it cannot ride activation.
    relax_lateral_cell_once(driver)                               # §5.6

    # Step 6: press the two healed surfaces together and let them bond.
    press = press_and_bond(driver, pair_specification)          # §9.3

    # The gated zero-load reference the pull integrates from (§5.3).
    reference = settle_reference(driver, press, pair_specification)  # §9.4

    # Step 7: pull ONCE PER RATE (§5.4), each from a fresh copy of the
    # reference (a pull deforms it). The press is NOT repeated.
    pulls = empty list
    for each rate in pair_specification.numerical.pull_rate_ladder:
        pulls.append(pull_at_rate(driver, reference, rate,
                                  pair_specification))     # §9.5, §9.6
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
function open_lammps_driver(structure, potential, pair_specification):
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
    # The lateral cell is taken to zero in-plane stress by a ONE-TIME
    # combined-cell relax at the joint heal (`fix box/relax x 0 y 0` +
    # minimize), recorded, then HELD FIXED for the whole press/settle/
    # pull; a live barostat DURING the press is forbidden (the cell would
    # drift and the provenance number becomes a fiction, §5.6). The
    # z-boundary is non-periodic, vacuum sized for the full pull distance
    # plus margin.
    return driver
```

### 9.3 press_and_bond — mode, no impact, honest thermostat, dual contact

```
function press_and_bond(driver, pair_specification):
    protocol  = pair_specification.protocol
    numerical = pair_specification.numerical
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
    # idea, find_contact_step; revised 2026-08-28 (Paul)): PRIMARY = the
    # opening between the two §2.6 density dividing surfaces, averaged
    # over the last contact_gap_window chunks, has closed to the
    # threshold (one reading jumps by angstroms when a loose atom crosses
    # the gap); CONFIRM = the running-average normal stress is SUSTAINED
    # above contact_stress_floor in magnitude, of EITHER sign. A gap can
    # close on ONE asperity; compression above the floor means the
    # surfaces genuinely load each other, and sustained TENSION across a
    # closed gap means they have already bonded and pull on each other —
    # the opposite of an asperity. Gap measured surface-to-surface, NOT
    # between extremal atoms (prior art's asperity failure).
    # The driver advances one control_interval at a time and reads back
    # between chunks; the stress mean spans contact_stress_window chunks;
    # the search stops at press_time_budget and REPORTS no contact (§5.2,
    # 2026-08-28 — all three are project knobs, not driver constants).
    stage_steps.press_start = current_step(driver)
    run_until(driver, step = numerical.control_interval,
        budget = numerical.press_time_budget,
        condition =
            trailing_mean(interface_geometry(driver, recorded_plane,
                                             numerical).opening,   # §9.6
                          numerical.contact_gap_window)
                <= numerical.contact_gap_threshold
            and abs(trailing_mean(normal_stress(driver),
                                  numerical.contact_stress_window))
                >= numerical.contact_stress_floor)
    if budget exhausted:
        return PressOutcome{ bonded: false, ... }     # reported, §5.1
    stage_steps.contact = current_step(driver)

    # The HOLD at temperature is where bonding actually happens (§5.2).
    hold_at_temperature(driver, protocol.press_duration)
    stage_steps.hold_end = current_step(driver)

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
        depth_reached: measured_depth(driver),
        stage_steps: stage_steps }
```

### 9.4 settle_reference — a gated zero-load state (`DESIGN.md` §5.3)

```
function settle_reference(driver, press, pair_specification):
    numerical = pair_specification.numerical
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
    release_press_drive(driver, pair_specification)
    press.stage_steps.settle_start = current_step(driver)   # ledger, §9.3
    minimize(driver)                          # to a local minimum
    # Settle at temperature for settle_duration, one control_interval at
    # a time, reading BOTH grip reactions and the potential energy back
    # after each chunk (§5.3, 2026-08-28: both are project knobs).
    series = equilibrate_under_thermostat(driver, numerical.settle_duration,
                                          numerical.control_interval)
    press.stage_steps.settle_end = current_step(driver)
    # ASSERT the press actually settled; if not, REPORT, do not integrate
    # over it (§5.3). The force test is the SAME statistical criterion
    # §9.6 uses for the pull's returned force: the net grip force (top +
    # bottom, per chunk) counts as zero when its mean lies within two
    # standard errors of zero, floored by noise_floor for a noiseless
    # record — never a fixed constant (revised 2026-08-28, Paul).
    net = series.top_reaction + series.bottom_reaction     # per chunk
    assert abs(mean(net)) <= max(2 * standard_error(net),
                                 numerical.noise_floor)
    assert potential_energy_drift(series.potential_energy)
           <= numerical.reference_pe_drift
    # The location is a WRITTEN data file, because the pull restores from a
    # file on a fresh instance (§9.6); handing it the original pair data
    # would silently discard the whole press.
    return StateRef{ location: write_reference(driver),
                     potential_energy: potential_energy(driver) }
```

### 9.5 pull_at_rate — one rung of the ladder (`DESIGN.md` §5.4)

```
function pull_at_rate(driver, reference, rate, pair_specification):
    numerical = pair_specification.numerical
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
                                rate, pair_specification)        # §9.6
```

### 9.6 reduce_to_trajectory — two curves, separation, and the gates

```
function interface_geometry(driver, recorded_plane, numerical):
    # DESIGN §2.6 (revised 2026-08-30, Paul, after LEDGER T-40): where
    # the interface IS, asked of the WHOLE system's density profile with
    # NO wafer labels — a pull transfers material between the faces, and
    # a label-based surface then lands on the transferred layer, reads
    # a ~1 A opening across a 60 A vacuum, and the pull never stops.
    z_all   = z of every atom in the box
    profile = smooth(density_profile(z_all, numerical.density_bin_width))
    low     = profile < HALF_OF_BULK * max(profile)     # the §2.6 rule
    # A run of low bins counts only when MATERIAL bounds it on BOTH
    # sides: a sputtered atom in the outer vacuum bounds nothing.
    runs    = maximal runs of `low` with an above-threshold bin on each side
    if runs is empty:                       # joined: nothing to find
        return record{ opening: 0.0, plane: recorded_plane }
    widest  = the run of greatest width
    lower_top    = threshold crossing on the low-z side of `widest`
    upper_bottom = threshold crossing on the high-z side of `widest`
    return record{ opening: upper_bottom - lower_top,
                   plane:   0.5 * (lower_top + upper_bottom) }
    # `recorded_plane` is the assembly's interface plane (§2.6, the
    # builder's per-wafer z-ranges), exact before anything moved and
    # only ever a placeholder: nothing is decided on the plane until a
    # gap has opened. The labels keep one job — reporting where
    # transferred material came from.


function reduce_to_trajectory(driver, series, frames_ref, reference,
                              rate, pair_specification):
    numerical = pair_specification.numerical
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
    # Force vs INTERFACE OPENING (the §2.6 geometric gap of
    # interface_geometry, whole-system profile, no labels) is where the
    # interface actually is — separation is NOT grip displacement, which
    # also holds the slabs' elastic stretch.
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
        provenance:           provenance_of(rate, pair_specification),
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

function anneal_then_minimize(fragment, potential, anneal_schedule):
    # A short ANNEAL on the recorded schedule — hold hot, cool to the
    # press temperature — so surface atoms reorganize and dangling bonds
    # pair, THEN minimize_local so the result is a 0 K structure (§8.5
    # relaxed reference; the §10.5 heal). Anneal first because the heat
    # is what lets loose atoms find bonds; minimize last so what the
    # gate judges is at rest (order settled 2026-08-28 (Paul)). The
    # SCHEDULE is a recorded knob: an amorphous surface is kinetically
    # trapped, so "relaxed" means "as relaxed as this schedule got it"
    # (DESIGN §6.4).
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
`activate_surface` body — the step-4 seam inside each prep stage
(§1, §7.1), guarded by `ACTIVATED_HALF_CONTRACT` — to code-readiness,
and it defines the concrete form of that contract. Like §9 it runs on
a persistent LAMMPS driver, and the cascade runs under a
`hybrid/overlay` splice of the universal foundation MLIP with two ZBL
cores, **not** the committee (DESIGN §4.7); the heal (§10.5), on the
same model, delegates back to §9.7.

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
surface-activated bonding (`DESIGN.md` §3.1). **Revised 2026-08-28 (Paul,
§3.4): activation is cascade + heal + gate again.** Each half is
bombarded, stripped of the projectile, healed (anneal then minimize,
§10.5) and judged by the §3.5 gate (§10.6) in its own session, and only
two passing halves are assembled. So `activate_surface` returns the
concrete form of `ACTIVATED_HALF_CONTRACT` — ONE healed slab with its
verdict, the deliverable of its prep stage (revised 2026-08-30 (Paul));
a failed verdict halts that prep at this seam, before any assembly.
(From 2026-08-08 to 2026-08-28 the heal and gate rode the bond flow on
the assembled pair at a wide gap; that placement
existed only because the heal then ran under a potential whose engine
lived in the bond job, and one universal model for cascade and heal
dissolved the reason.)

```
record ActivatedHalf:
    # The concrete form of §1's ACTIVATED_HALF_CONTRACT (revised
    # 2026-08-30 (Paul); from 2026-08-28 to then an ActivatedSlabs pair
    # carried both halves at once): ONE healed slab and its §3.5
    # verdict, the deliverable of one prep stage. The contract checks
    # the slab is amorphized AND the verdict passed; a failure halts the
    # prep here, before any assembly.
    slab:    Structure             # the healed half (grips still unset)
    verdict: ActivationVerdict     # its healed-surface gate (§10.6)
    wafer:   tag                   # WAFER_A (bottom) or WAFER_B (top)
    shared:  SharedCell            # the cell it was built in (§7.1)
    # The slab also records the MD step at which its heal began
    # (heal_start_step), written by the cascade session as a marker
    # beside its recording, so a consumer of the activate movie can
    # tell the cascade-hot frames from the healed ones (§11.3).

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

`[SEAM — rippled in code, 2026-07-18; re-scoped 2026-08-08; restored
2026-08-28; per half 2026-08-30]` each prep stage runs
`prepare_surface` to one `ActivatedHalf`, HALTS unless
`.verdict.passed` (the "gate, not warn" discipline at the seam where
failure is cheapest), and the bond stage reads the two halves back to
feed `assemble_pair`.

Each surface is activated INDEPENDENTLY (both are still in vacuum, not
yet facing): `activate_surface` (below) is called once per prep stage
by `prepare_surface` (§7.1), never as a co-activation — the pair does
not co-exist here. Each call takes a HalfHandle (§7.1): it opens its
own engine, RE-READS the pristine half from `handle.data_file` (never a
warm object from `build_half`), amorphizes it, and the prep stage
writes the result to its folder for `assemble_pair` (§7.5) to read —
the `ARCHITECTURE.md` §4.3 file handoff. [SERIAL I/O] The snapshot
taken out of the engine is collective (every rank holds the full atom
set), but ONE rank writes it and a barrier publishes it, so the reader
finds it on whichever rank reads it back (§7.1).

Revised 2026-08-30 (Paul): the two activations no longer share a job.
Each runs in ITS OWN prep job on the job's FULL core allocation, and
the scheduler runs the two side by side — the separate-job fan-out
`ARCHITECTURE.md` §4.3 called Approach C, arriving through the files
at no cost in stage code. Each call is a pure function of (half, seed)
handing off through files, so it must stay free of cross-call state
(# C-EXPANSION). The N realization seeds the ensemble (§10.8) loops
above multiply the prep jobs, never the bond job.

`[DISTILLATION — in code, 2026-07-19; re-scoped 2026-08-08; restored
2026-08-28]` the driver (`driver/cascade.py`) runs the cascade and the
heal, and the gate judges the healed half as it is read back, returning
an `ActivationResult` carrying the rich `ActivationVerdict`; the pipeline
distills that to the contract `Verdict` at THIS seam, so the written
`ActivatedHalf` carries its verdict and the HALT is here.

The mechanism is a SEAM, not a hard-coded procedure (`DESIGN.md` §3.1).
v1 registers one mechanism — energetic-particle bombardment — but plasma
or reactive activation slot in behind the SAME signature without touching
step 4's consumers. An ion beam and a fast-atom beam are identical in
molecular dynamics, so both are one setting of the projectile spec
(§10.3), not separate mechanisms.

```
function activate_surface(handle, pair_specification, potential):
    # RE-READ the pristine half from disk into a slab — the standalone
    # geometry plus the beam-declaring type map the handle carries (§7.1),
    # never a warm object from build_half (ARCHITECTURE §4.3). From here
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
        pair_specification.protocol.activation_mechanism]
    return mechanism(slab, pair_specification, potential)
```

```
function energetic_particle_bombardment(slab, pair_specification,
                                        potential):
    # The v1 mechanism (DESIGN §3.2–§3.5). Revised 2026-08-28 (Paul):
    # cascade, strip, HEAL and GATE, all in this one session. Derive the
    # concrete impact plan and run the cascade (universal MLIP + ZBL,
    # §4.7) to the target fluence; strip the projectile; heal (§10.5);
    # gate the healed surface (§10.6). The verdict travels with the slab.
    spec    = derive_bombardment_spec(slab, pair_specification)   # §10.3
    driver  = open_cascade_driver(slab, potential,
                                  pair_specification)             # §10.2
    damaged = run_cascade_to_fluence(driver, spec)                  # §10.4
    damaged = strip_projectile(damaged)                # DESIGN §3.4 cleanup
    healed  = heal_surface(driver, pair_specification)            # §10.5
    verdict = activation_gate(healed,
                              crystalline_reference(pair_specification),
                              pair_specification,
                              load_environment_library(
                                  pair_specification, wafer))     # §10.6
                              # ^ THIS half's wafer's own library
    # The skin label records what the cascade amorphized, at the depth the
    # gate MEASURED (§10.7).
    healed  = label_activated_skin(healed, verdict.activated_depth)  # §10.7
    return record{ slab: healed, verdict: verdict }
```

### 10.2 open_cascade_driver — the correctness core

> **Revised 2026-08-26/28 (Paul).** The cascade has exactly ONE
> generator: the universal foundation MLIP the project file names, with
> the two ZBL cores spliced in (DESIGN §4.7). The analytic forms an
> earlier draft carried were removed on 2026-08-26 and nothing falls
> back to anything.

This is the part prior art gets wrong (`DESIGN.md` §3.3). It mirrors
§9.2's persistent-driver discipline, but the potential and the boundaries
are cascade-specific.

```
function open_cascade_driver(slab, potential, pair_specification):
    # ONE persistent LAMMPS process for the WHOLE impact train, NOT a
    # fresh process + full-slab disk round-trip per impact (prior art's
    # antipattern, DESIGN §3.3 — the same one §9.2 refuses). At the doses
    # SAB needs (thousands of impacts) that overhead is prohibitive.
    #
    # POTENTIAL: hybrid/overlay of the UNIVERSAL FOUNDATION MLIP the
    # project file names (DESIGN §4.7; one row of the supported-model
    # table, never a hard-coded model) with TWO ZBL hard cores. The MLIP
    # does the bonding; ZBL #1 (longer cutoff)
    # the projectile-substrate collision; ZBL #2 (short cutoff, below the
    # bond) a hard core on every substrate-substrate pair, because a
    # near-equilibrium model has only FINITE, soft short-range repulsion
    # and would otherwise let cascade atoms fuse (PRIOR_ART §1.9).
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

function derive_bombardment_spec(slab, pair_specification):
    protocol = pair_specification.protocol
    ensemble = pair_specification.ensemble

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

### 10.5 heal_surface — anneal, then minimize (`DESIGN.md` §3.4)

A stage prior art does NOT have (DESIGN §3.4): the cascade MADE the
disorder; the heal re-equilibrates GENTLY under the same universal model
so the surface the gate judges and the press meets is settled, not
cascade-hot — the first rung of the fidelity ladder (§4.5).

**Revised 2026-08-28 (Paul): back in the activate stage, per half.** The
heal runs at the end of each half's own cascade session, in vacuum, on
the SAME driver (§10.2): after the projectile strip, the project's
`[protocol.reanneal]` schedule is applied — hold the mobile atoms hot,
cool to the press temperature — and THEN the slab is minimized. It
DELEGATES to §9.7's `anneal_then_minimize`. A kinetically trapped glass
will not fully rearrange, so the cascade start must be a reasonable
basin (STRUCTURAL 1b). (From 2026-08-08 to 2026-08-28 a single joint
heal ran on the assembled pair at a wide gap in the bond flow; that
existed only because the heal then ran under a potential whose engine
lived in the bond job.)

```
function heal_surface(driver, pair_specification):
    # Same driver, same universal model, after the last impact and the
    # projectile strip. The frozen base stays frozen; the mobile atoms
    # take the recorded schedule; the result is a 0 K healed half.
    schedule = pair_specification.protocol.reanneal_schedule
    return anneal_then_minimize(current_slab(driver), driver.potential,
                                schedule)                          # §9.7
```

### 10.6 activation_gate — pass/fail with pluggable metrics (`§3.5`)

```
function activation_gate(healed_surface, crystalline_slab,
                         pair_specification, environment_library):
    # A GATE, not a report (DESIGN §3.5). Revised 2026-08-28 (Paul): it
    # is called from the ACTIVATE stage (§10.1), once per half, on the
    # HEALED half as it is read back from its cascade session — before
    # assembly, where a failure is cheapest. Revised 2026-08-29 (Paul):
    # "crystalline" is decided per atom against the ENVIRONMENT LIBRARY
    # (below), never against a hand-set neighbour count; the depth
    # metric is re-based on it first, the coordination and ring metrics
    # keep their v1 form until a follow-on re-bases them too.
    # Judgment is PER REALIZATION: each metric judges ONE healed surface;
    # the seed-ensemble spread is taken ABOVE (§10.8). Prior art only
    # PRINTED an unthresholded g(r) RMSD (PRIOR_ART §1.8). Each metric
    # measures ONE property against a reference with a real THRESHOLD; the
    # gate is the AND.
    #
    # References + thresholds live OUTSIDE the physics spec — a threshold is
    # a criterion of the GATE, not a knob of the experiment (DESIGN §3.5) —
    # so they are looked up here, keyed by the species set.
    references = load_activation_references(
        species_of(activated_slab), pair_specification)

    # One disorder score per atom, computed ONCE and shared by every
    # metric that wants it (the depth metric today; the others as they
    # are re-based). Computed here, not inside a metric, so no two
    # metrics can disagree about which atoms are disordered.
    disordered = disordered_atoms(
        activated_slab, environment_library,
        pair_specification.numerical.disorder_scatter_multiple)

    # Everything a metric may want, in ONE record, so the survivors and
    # the re-based metrics share a signature (the code's GateContext).
    context = GateContext{
        activated: activated_slab, crystalline: crystalline_slab,
        references: references, disordered: disordered,
        library: environment_library,
        pair_specification: pair_specification }

    per_metric = empty map
    for each metric in ACTIVATION_METRICS:   # a registry, like §8 measures
        per_metric[metric.name] = metric.evaluate(context)

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
function load_activation_references(species, pair_specification):
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
function radial_distribution_metric.evaluate(context):
    activated, refs = context.activated, context.references
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
function coordination_metric.evaluate(context):
    # v1 SURVIVOR (DESIGN §3.5): still coordination-based until re-based
    # on context.disordered; it reads the same record as every metric.
    activated, crystalline, refs = (context.activated,
                                    context.crystalline,
                                    context.references)
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
function ring_statistics_metric.evaluate(context):
    # v1 SURVIVOR (DESIGN §3.5), silicon-shaped until re-based.
    activated, refs = context.activated, context.references
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
record EnvironmentLibrary:
    # DESIGN §3.5 / §4.8 part 2 (2026-08-29): what the undamaged material
    # looks like, atom by atom, as second-shell bispectrum vectors. MADE
    # by the bootstrap (§11.2), never written by hand.
    model_name:       string        # the universal model the source
                                    # structures were made under; must
                                    # equal the project's universal_model
    engine:           string        # which descriptor engine computed
                                    # every vector here (ARCHITECTURE
                                    # §2.3: LAMMPS sna/atom, a Python
                                    # library, or Imago)
    settings:         DescriptorSettings  # cutoff, expansion order, per-
                                    # species weights — the gate REUSES
                                    # these, never its own copy
    environments:     map of species -> list of vector
                                    # every catalogued environment of
                                    # that species: families 1, 4, 6
    thermal_scatter:  map of species -> number
                                    # the typical descriptor-space
                                    # distance of a warm-run atom from
                                    # its nearest cold-bulk environment;
                                    # the unit the tolerance is counted in
    warm_distances:   map of species -> list of number
                                    # every warm-run atom's nearest-cold
                                    # distance, kept so the FALSE-ALARM
                                    # RATE — the depth profile's
                                    # baseline — can be recomputed at
                                    # whatever scatter multiple a project
                                    # names, not only the recipe's
    self_check:       record{ scatter_multiple: number,
                              warm_disordered: number,
                              melt_quench_disordered: number }
                                    # DESIGN §3.5: a sound tolerance keeps
                                    # the first near zero and the second
                                    # near one; both are recorded so the
                                    # separation is auditable
    warm_run_temperature: Quantity  # the LOWEST temperature among the
                                    # warm runs catalogued: what the
                                    # thermal scatter was measured at.
                                    # The project loader's warn/refuse
                                    # band (DESIGN §3.5) is judged
                                    # against this
    provenance:       record{ families: list, frame_counts: map,
                              surfaces: list of (species, face) }
                                    # what was catalogued; the validator
                                    # checks the wafer's face is here


function load_environment_library(pair_specification, wafer):
    # DESIGN §3.5 / §4.8 part 2 / ARCHITECTURE §2.3 and §1. The library
    # is a run-time input found PER WAFER in the project folder, in
    # that wafer's prep folder `prep_surfN_<label>/` (revised 2026-08-29
    # (Paul) after LEDGER T-39, folder renamed 2026-08-30; the project
    # file names no path). Three
    # refusals and one warn/refuse band, all decidable on the login
    # node; the §2 validator runs the same rules
    # (check_environment_libraries) so no node-hour is spent on a
    # mismatch.
    path    = wafer.preparation_directory / "environment_library.toml"
    if not exists(path):
        halt("wafer '<identity>' has no environment library at <path>; "
             "run `sabsim bootstrap generate` in that folder, or copy "
             "a prepared prep_surf*_<label>/ folder there (ARCH §1)")
    library = read_environment_library(path)     # the .toml + .npz pair

    if library.model_name != pair_specification.potential.universal_model:
        halt("environment library was built under '<library model>', the "
             "project runs '<project model>' — rebuild the library")
    if library.engine != DESCRIPTOR_ENGINE.name:
        halt("environment library was computed with '<engine>', this "
             "deployment binds '<bound engine>' — both sides of the "
             "comparison must use one engine (ARCHITECTURE §2.3)")
    # Face and species only — NOT the termination (Paul, 2026-08-29):
    # every catalogued surface is bombarded to an amorphous skin before
    # it matters, so which atomic plane the clean cut ended on makes no
    # difference to the gate. Only THIS wafer's face: the other wafer
    # has a library of its own.
    face = (wafer.species, wafer.face)
    if face not in library.provenance.surfaces:
        halt("environment library catalogues no clean <face> "
             "surface; the slab's own faces would read as damage — "
             "add the face to the recipe's surfaces and rebuild")

    # The warn/refuse band (DESIGN §3.5, Paul 2026-08-29): the gate
    # judges at the heal's cool-to target, the press temperature.
    judged_at = pair_specification.protocol.press_temperature
    if judged_at > library.warm_run_temperature:
        if judged_at > 1.20 * library.warm_run_temperature:
            halt("project judges the gate at <judged_at>, more than 20 % "
                 "above the library's warm runs at <warm>; the tolerance "
                 "no longer describes the slab — rebuild the library "
                 "with a warm run at the project's temperature")
        warn("project judges the gate at <judged_at>, above the library's "
             "warm runs at <warm>: the tolerance was measured a little "
             "tight, some crystalline atoms may read as disordered")
    return library


function disordered_atoms(slab, library, scatter_multiple):
    # DESIGN §3.5: an atom is CRYSTALLINE if the library holds an
    # environment of its species within scatter_multiple thermal
    # scatters of it — "does this neighbourhood exist anywhere in the
    # undamaged material?" — and DISORDERED otherwise. Asked that way,
    # not "is it what THIS atom used to have", so a displaced atom the
    # heal re-settled onto a good site is crystalline, and both slab
    # faces are in the library through the surface family: no special
    # case for the frozen base, none for a healed-clean top.
    vectors = DESCRIPTOR_ENGINE.describe(slab, library.settings)
    #   ^ the SAME engine and settings the library was built with
    #     (ARCHITECTURE §2.3); a mismatch is a validator refusal, not a
    #     silent difference in what "crystalline" means
    flags = empty list
    for each atom in slab:
        nearest = min over library.environments[atom.species] of
                  descriptor_distance(vectors[atom], environment)
        tolerance = scatter_multiple * library.thermal_scatter[atom.species]
        flags.append(nearest > tolerance)
    return flags                      # true = disordered, one per atom


function amorphization_depth_metric.evaluate(activated, crystalline, refs,
                                            disordered, library,
                                            pair_specification):
    # DESIGN §3.5 (revised 2026-08-29). Disorder(z): the FRACTION of
    # disordered atoms in each horizontal layer of depth_bin_width, from
    # the free surface down. Every layer is judged — a layer of four
    # atoms is four verdicts, not noise — so there is NO sparse-layer
    # cut-off (the Phase-1 stand-in's fixed 10-atom cut-off skipped the
    # real skin of LEDGER T-34's half B).
    width   = pair_specification.numerical.depth_bin_width
    surface = free_surface_height(activated)
    profile = []                      # (layer_top, layer_bottom, fraction)
    for each layer of thickness width from surface DOWN to the slab base:
        atoms_in_layer = atoms of activated with layer_bottom <= z < layer_top
        fraction = count(disordered[a] for a in atoms_in_layer)
                   / count(atoms_in_layer)      # 0 for an empty layer
        profile.append((layer_top, layer_bottom, fraction))

    # The BASELINE is the library's own false-alarm rate — what the
    # tolerance calls disordered in a slab that was never bombarded —
    # never a number measured on the damaged slab being judged. (The
    # earlier "deep third of the slab" baseline included the frozen
    # bottom face, whose atoms are under-coordinated by construction,
    # and the polluted baseline swallowed the real skin: T-34.)
    multiple = pair_specification.numerical.disorder_scatter_multiple
    baseline = max over species present of
        fraction of library.warm_distances[species]
            > multiple * library.thermal_scatter[species]

    # Scan the WHOLE profile: the depth is the free surface to the LOWER
    # edge of the DEEPEST layer still above baseline — not the first
    # crystalline-looking layer from the top (prior art's 0 A bug,
    # DESIGN §3.5; the top-contiguous walk is that bug under another
    # name). A damaged layer under a healed-clean layer still counts.
    deepest = none
    for each (top, bottom, fraction) in profile:
        if fraction > baseline: deepest = bottom
    depth = 0 if deepest is none else surface - deepest

    # The THRESHOLD is the project's requirement, not a material
    # reference (DESIGN §3.5, revised 2026-08-28): how deep THIS project
    # needs the skin is the project's call.
    target = pair_specification.protocol.required_activated_depth
    return MetricVerdict{
        measured: depth, reference: "project: required_activated_depth",
        threshold: target, passed: depth >= target }
```

`DESCRIPTOR_ENGINE` is a pluggable seam (ARCHITECTURE §2.3): one binding
per deployment, with the contract `describe(atoms, settings) -> one
vector per atom`. The engine name and settings recorded in the library
are the ones the gate uses; `load_environment_library` (§10.1) refuses a
library whose engine is not the bound one, whose model is not the
project's, or whose surfaces lack the wafer's face.

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

`[DELEGATE -> §9.7]` the heal (§10.5) reuses `anneal_then_minimize` —
the same driver, a near-equilibrium schedule. Activation AUTHORED the
disorder; §9.7 relaxes it.

`[DELEGATE -> POTENTIAL, DESIGN §4]` the cascade generator — the
universal foundation MLIP the project file names, via the §4.7 generator
seam and its supported-model table — and the per-pair MLIP committee
(step 2) are §4 concerns; this module CONSUMES both, never authors
them.

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
the process that MANUFACTURES the machine-learned potential every pair
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

**It sits ABOVE `exec_one_pair`.** The bootstrap runs ONCE per
material (the species union, STRUCTURAL 1a) and emits ONE fingerprinted
potential that many projects then look up by `potential_ref` (§1,
`DESIGN.md` §1.6). So it is a top-level process alongside
`exec_full_project` (§1), NOT a stage inside the per-pair pipeline —
which is exactly why §1's `resolve_potential` is a LOOKUP, not a call
that trains.

**The circularity it resolves.** Steps 4/6/7 run MD *on* the potential,
but the configurations they visit are what the potential must be trained
on (`DESIGN.md` §4.5). The builder also consumes the potential's relaxed
lattice constants (§7.2) while the potential must be trained on the
builder's strained substrates (STRUCTURAL 4) — a TWO-WAY coupling, which
is why this is a LOOP and not a straight line.

### 11.1 The module's top-level shape

The loop is generate -> label -> train -> refine, repeated until the
potential passes BOTH convergence tests (§11.6). This is one pass of the
OUTER loop (`VISION.md` principle 5), run by hand in v1: the inner
refine-loop iterates, but re-entry for MORE pairs or project-driven
weaknesses is manual.

**The INPUT record, which every function below threads.** This object
was passed through twelve call sites under the name
`pair_specification` and defined nowhere; `DESIGN.md` §4.8 designs it and
this is its shape. The name changed with the definition, because the old
one was wrong twice: it is keyed by a species UNION and a DOMAIN rather
than by a pair, and it is a manufacturing RECIPE rather than a
description. It is the third input file, alongside the project
specification (§2) and the deployment configuration — it lives in the
prep folder of the surface it prepares (`ARCHITECTURE.md` §1) — and it
changes on a third clock: manufactured once, costing weeks, then
consumed unchanged by many projects.

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

record SelectionRule:
    # DESIGN §4.8 part 6 — which harvested configurations earn an
    # accurate calculation. The accurate method is THE cost bottleneck,
    # so every slot spent on a configuration that teaches nothing new is
    # a slot not spent on chemistry the model has never seen.
    #
    # Distinct from the §4.6 sampler cutoffs (Escut, Fscut). Those
    # decide which frames the MD CAPTURES; this decides which captured
    # frames get LABELLED. Capture is cheap, labelling is not.
    interface_preference: number  # how strongly to favour the
                                  # interface region. The bulk is
                                  # already covered cheaply by
                                  # Collection 1, so bulk-like frames
                                  # bought at labelling prices are
                                  # mostly redundant
    uncertainty_weight:   number  # how strongly to prefer the
                                  # configurations the committee least
                                  # agrees on. This is what makes the
                                  # loop ACTIVE learning rather than
                                  # bulk sampling — but it must not be
                                  # the only criterion, or the budget
                                  # chases whichever corner is noisiest
                                  # instead of whichever is most
                                  # relevant
    duplicate_cutoff:     number  # below this DESCRIPTOR-SPACE distance
                                  # to something the store already
                                  # holds, a candidate is a near-
                                  # duplicate and is skipped.
                                  # Descriptor space, NOT structural
                                  # similarity: the model sees only
                                  # within DescriptorSpec.cutoff_radius,
                                  # so two cells that look different can
                                  # present identical local
                                  # environments — and paying twice for
                                  # one environment is exactly the waste
                                  # this rule exists to stop
    frame_as_subcell:     boolean # frame interface configurations as
                                  # the §6.4 subcells rather than whole
                                  # production cells. Legitimate because
                                  # the potential is short-ranged, and
                                  # necessary because all-electron cost
                                  # grows steeply with atom count
    # The asymmetry §4.5 step 3 names: a TRAINING configuration need
    # only be physically valid and relevant, which leaves the subcell
    # choice free — whereas the §6.4 interface_fidelity cross-check
    # compares two METHODS and so demands both see the identical system.


record TrainingSpec:
    # DESIGN §4.8 part 7 — how long each committee member trains and
    # what its loss rewards.
    length:          Quantity  # training length (epochs or steps).
                               # Load-bearing for a reason that is easy
                               # to miss: committee spread is only
                               # epistemic uncertainty if the members
                               # are trained to COMPARABLE convergence.
                               # Members stopped at different degrees of
                               # fit disagree because they are unequally
                               # trained, and that disagreement is
                               # training noise wearing the uncertainty
                               # signal's clothes — which would corrupt
                               # both the §4.6 sampler and the §4.4
                               # runtime backstop
    energy_weight:   number    # how the loss balances energies against
    force_weight:    number    # forces. NOT a free 50/50: a
                               # configuration carries 3N force
                               # components against a SINGLE energy, so
                               # an unweighted loss is dominated by
                               # forces by sheer count. The balance
                               # decides what the model is good AT —
                               # forces give faithful dynamics, energies
                               # give faithful relative stability
                               # BETWEEN structures. Both are gated:
                               # §7.2 checks elastic stiffness (a
                               # curvature of the energy) and the
                               # protocol needs forces. And the Tier-0
                               # screen is purely an ENERGY-difference
                               # test — LEDGER T-21 rejected DPA-2.4-7M
                               # for ranking a damaged structure 0.421
                               # eV/atom BELOW the crystal, a failure no
                               # amount of force accuracy would have
                               # caught
    learning_schedule: string  # how the step size is annealed
    validation_split:  number  # the held-out fraction, so "trained" is
                               # a measured claim and not a hope


record DescriptorSettings:
    # The GATE'S ruler (DESIGN §3.5 / §4.8 part 2, 2026-08-29): how the
    # environment library and the §10.6 gate describe one atom's
    # neighbourhood through its SECOND shell (LEDGER T-37: the first
    # shell alone cannot see glass). Distinct from DescriptorSpec, how
    # the TRAINED MODEL sees an environment. Stated physically; the
    # engine's own parameters are DERIVED (ARCHITECTURE §2.3).
    descriptor_cutoff: Quantity   # a LENGTH: past the SECOND
                                   # neighbour shell, short of the
                                   # third (silicon: 2.35 and 3.84 A
                                   # in, 4.5 A out => 4.2 A; T-37)
    expansion_order:    int        # how finely angles are resolved
                                   # (LAMMPS's `twojmax`; 6 gives 30
                                   # components per atom, LEDGER T-35)
    species_weights:    map of species -> number
                                   # how strongly each species counts
                                   # in a neighbour's contribution, so
                                   # unlike species are told apart
    # DERIVED, never written by hand: for LAMMPS `compute sna/atom` the
    # cutoff is rcutfac x (R_i + R_j), so with rcutfac = 1 every species
    # radius is descriptor_cutoff / 2; and the engine's neighbour list
    # must be built at least descriptor_cutoff wide, or LAMMPS refuses
    # ("cutoff is longer than pairwise cutoff" — the T-35 trap).


record PhaseSpec:
    # DESIGN §4.8 part 2, family 1 — one crystal phase of the declared
    # domain, at its ground state.
    #
    # These entries ARE the domain's truth. §4.8 part 1 notes that the
    # domain label is "a handle, not the truth — the truth is the
    # enumerated starting collection", so a phase absent from this list
    # was not taught, whatever the label claims.
    name:          string     # the phase, not just the composition:
                              # alpha-quartz and cristobalite are the
                              # same SiO2 and different chemistry, and
                              # conflating them is the §4.8 hazard
    structure_ref: string     # where the symmetry, basis and
                              # connectivity come from (a CIF, §1.2)
    # NO lattice constant is stored. The CIF's published scale is a
    # STARTING geometry only: the working lattice is DERIVED by relaxing
    # under the model being manufactured (§2.2). Recording a scale here
    # would invite exactly the CIF-vs-model offset that LEDGER T-21
    # measured at -1.52% for silicon under DPA-2.4-7M.


record SurfaceSpec:
    # DESIGN §4.8 part 2, family 4 — one clean, unbombarded free
    # surface. The calm counterpart to the cascade's amorphized surface
    # (part 5 family 7): same face, no damage.
    phase:        string      # which PhaseSpec it is cut from
    miller_index: (int, int, int)   # the crystallographic face
    termination:  string      # which atomic plane the cut ends on.
                              # A polar oxide can be cut several ways
                              # from ONE Miller index, and the choices
                              # differ in energy and reactivity, so the
                              # index alone does not identify a surface
    slab_thickness: Quantity  # enough that the middle is bulk-like;
                              # the two faces must not interact
    vacuum:         Quantity  # enough that the slab does not see its
                              # own periodic image across the gap


record StrainSpec:
    # DESIGN §4.8 part 2, family 2 — one deformed bulk cell. Serves BOTH
    # the STRUCTURAL-4 shared-cell stretch (where the matcher's cell
    # dictates the strain) and the free deformation sweep.
    phase:      string        # which PhaseSpec is deformed
    strain:     3x3 tensor    # the full tensor, SHEAR KEPT. Not a
                              # scalar magnitude: a mismatched interface
                              # under load carries shear, and the press
                              # and pull are themselves compression and
                              # tension, so a model taught only
                              # volumetric scaling has not seen the
                              # deformations the protocol applies. (The
                              # same tensor-not-scalar point PSEUDOCODE
                              # §7.6 makes about residual strain.)
    origin:     string        # "structural-4" when the shared cell
                              # fixes it, "sweep" when it is chosen —
                              # recorded because one is dictated by the
                              # pair and the other is ours to pick
    # The sweep is carried PAST the reversible range, into the regime
    # where bonds begin to fail: §7.2 GATES elastic stiffness, and a
    # pull that fails through the crystal rather than along the
    # interface is an outcome §8 must tell apart from the other. A model
    # shown only small strains cannot do either.


record RattleSpec:
    # DESIGN §4.8 part 2, family 5 — static displacements about the cold
    # cell. The cheapest way to show the model the neighbourhood of
    # equilibrium.
    amplitude:   Quantity     # displacement scale per atom
    count:       int          # how many snapshots per phase
    seed:        int          # the draws are random; the seed makes
                              # them reproducible (§10.3's discipline)
    # These are UNCORRELATED kicks around a cold cell. They are NOT a
    # substitute for the warm runs of family 6: a rattled snapshot never
    # shows correlated thermal motion, nor the volume a crystal actually
    # takes when hot. Both families are required for that reason.


record GenerationPlan:
    # DESIGN §4.8 part 5 — how Collection 2 is manufactured. Which
    # protocol stages run purely to harvest frames, on WHICH force model
    # each runs, how many, and under what conditions.
    harvest_stages: list of string   # the five families of part 5:
                                     # healed activated surface, pair
                                     # at press start, settled zero-load
                                     # reference, pressed cell, pulled
                                     # cell
    cascade_model:  string           # the §4.7 foundation MLIP + ZBL,
                                     # named the way a pair's
                                     # potential_ref is (§2)
    protocol_model: string           # the SAME foundation MLIP for the
                                     # press and pull. NOT a committee:
                                     # generating the hard configs with
                                     # the model those configs are meant
                                     # to train is the circularity
                                     # STRUCTURAL 1b exists to break
    frames_per_stage: map            # stage name -> how many kept
    conditions:       map            # knob -> value: the energies,
                                     # doses, rates and temperatures
                                     # the harvest runs at
    # Collection 1 is labelled as whole cells, being small by
    # construction; Collection 2 is labelled as the §6.4 interface
    # SUBCELLS, because a production cascade cell is an order of
    # magnitude beyond what the accurate method will take (LEDGER T-21:
    # ~1960 atoms for a single-impact calibration cell, against a
    # routine budget of a few hundred).


record DescriptorSpec:
    # DESIGN §4.8 part 7 — how the model SEES a local environment.
    form:            string   # the descriptor family
    cutoff_radius:   Quantity # the locality assumption made explicit.
                              # Everything beyond it is invisible to the
                              # model, so this is the claim that the
                              # chemistry is short-ranged — and it is
                              # what makes the §6.4 subcell legitimate
                              # as a training target at all: a subcell
                              # is valid precisely when it is wider than
                              # this. It also sets the FLOOR on
                              # QuenchSpec.cell_atom_count, since a cell
                              # narrower than twice the cutoff has every
                              # atom seeing its own image.
    # A long-range electrostatic treatment is a documented future target
    # for the strongly ionic oxides (DESIGN §4); this record is where
    # that would be declared when it arrives.


record QuenchSpec:
    # DESIGN §4.8 part 2, family 3 — one bulk melt-quench amorphous
    # structure. Melt a bulk cell until it forgets its lattice, then
    # cool it back down; what is left is the amorphous network.
    #
    # This is the ONLY family that produces amorphous chemistry without
    # a cascade, which is why it is cheap enough to be worth stating
    # carefully. It has NO free surface (contrast the cascade's
    # amorphized surface, part 5 family 7) and is sized to be labelled
    # WHOLE, so it never needs the §6.4 subcell treatment.
    phase:             string     # the crystal phase melted, naming
                                  # what the network came FROM; the
                                  # same composition quenched from
                                  # different phases can land in
                                  # different networks
    cell_atom_count:   int        # target size. Bounded ABOVE by what
                                  # the accurate method will label
                                  # whole, and BELOW by the descriptor
                                  # cutoff: a cell narrower than twice
                                  # the cutoff has every atom seeing
                                  # its own periodic image, which
                                  # teaches the model an artefact
    melt_temperature:  Quantity   # held WELL above melting, so the
                                  # crystal genuinely loses order
                                  # rather than merely softening
    melt_duration:     Quantity   # long enough that the liquid has no
                                  # memory of the starting lattice —
                                  # checked, not assumed (below)
    quench_rate:       Quantity   # temperature per unit time. THE
                                  # decisive knob: a fast quench
                                  # freezes in more defects and a
                                  # higher-energy network, a slow one
                                  # relaxes toward the ideal glass, and
                                  # the two are measurably different
                                  # materials. Stated as a RATE, not a
                                  # duration, so it means the same
                                  # thing at any temperature span
    final_temperature: Quantity   # where the quench stops
    replicas:          int        # independent seeds. An amorphous
                                  # network is ONE DRAW from an
                                  # ensemble, not a structure, so a
                                  # single replica misrepresents the
                                  # phase the model must learn
    # VERIFY, do not assume: the melt must be confirmed disordered
    # (coordination and g(r) departing from the crystal) before the
    # quench is trusted. A "melt" that stayed crystalline yields a
    # rattled crystal wearing an amorphous label — training data that
    # is wrong rather than merely useless.


record WarmRunSpec:
    # DESIGN §4.8 part 2, family 6 — one short warm run of one crystal.
    # Not optional: every stage the trained model owns (the re-settle,
    # the press, the settle, the pull) runs HOT, and a committee taught
    # only cold and rattled cells reports large, meaningless spread the
    # instant a warm run begins — spending the §4.4 uncertainty signal
    # exactly where it needs to mean something.
    phase:            string      # which crystal is run warm
    ensemble:         string      # "NVT" or "NPT". BOTH are required
                                  # and they are NOT interchangeable:
                                  # NPT lets the cell breathe and so
                                  # supplies THERMAL EXPANSION, while
                                  # NVT supplies correlated motion at
                                  # FIXED volume. A model shown only
                                  # NVT never learns the volume a
                                  # crystal actually takes when hot
    temperature:      Quantity    # THE temperature the §10.6 gate
                                  # judges a slab at (the heal's
                                  # cool-to target, 300 K in
                                  # production), not "modestly
                                  # elevated": hotter runs spread the
                                  # library's thermal scatter until it
                                  # swallows the glass (LEDGER T-37);
                                  # colder measures it too tight, which
                                  # the loader's warn/refuse band
                                  # catches (DESIGN §3.5, 2026-08-29)
    duration:         Quantity    # short: this anchors the committee,
                                  # it does not measure a property
    equilibration:    Quantity    # leading interval DISCARDED before
                                  # harvesting. Frames from the initial
                                  # transient are on the way to the
                                  # ensemble, not in it
    sampling_stride:  Quantity    # spacing between harvested frames.
                                  # Consecutive MD frames are strongly
                                  # correlated, so harvesting every
                                  # step buys volume without buying
                                  # information — and pays the labeller
                                  # for the duplicates
    replicas:         int         # independent seeds per (phase,
                                  # ensemble, temperature)


record StartingCollection:
    # DESIGN §4.8 part 2 — COLLECTION 1 of the settled recipe, six
    # families, ALL REQUIRED (settled 2026-08-23). The calm structures
    # computed before anything else. Its purpose is stated out loud
    # because it is easy to over-invest: it exists so the FIRST
    # committee does not fly apart, NOT to make it accurate. (It is no
    # longer a separate seed STAGE, DESIGN §4.5 step 1, but it IS
    # required training data.)
    bulk_phases:        list of PhaseSpec   # every phase in the domain
    clean_surfaces:     list of SurfaceSpec # their cut faces
    melt_quench:        list of QuenchSpec  # the AMORPHOUS network of
                                            # each phase, melted and
                                            # quenched in BULK. Not the
                                            # cascade's amorphized
                                            # SURFACE (§11.3): no free
                                            # surface, no bombardment,
                                            # small enough to label
                                            # whole. The cheapest source
                                            # of the amorphous chemistry
                                            # the interface is made of.
    warm_runs:          list of WarmRunSpec # short NVT and NPT runs of
                                            # each crystal at modestly
                                            # elevated temperature. NOT
                                            # optional: every stage the
                                            # trained model owns runs
                                            # HOT, and a committee taught
                                            # only cold and rattled
                                            # cells reports large,
                                            # meaningless spread the
                                            # instant a warm run starts.
                                            # NPT supplies thermal
                                            # expansion, NVT the
                                            # correlated motion at fixed
                                            # volume.
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
                                    # type map every pair inherits
    domain:         string          # the structural/chemical REGIME. The
                                    # species alone cannot identify a
                                    # model: one composition spans
                                    # different chemistries (carbon as
                                    # diamond or graphite; silica from
                                    # alpha-quartz to an amorphous
                                    # network). A pair's material_domain
                                    # (§2) must lie INSIDE this one —
                                    # containment, not equality, since a
                                    # silicon-and-silica recipe covers a
                                    # silica-only pair.

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
    # COLLECTION 2 of the settled recipe, five families, ALL REQUIRED
    # (DESIGN §4.8 part 5, settled 2026-08-23, definitions revised
    # 2026-08-28): the HEALED activated surface, the assembled pair at
    # press start (before any dynamics), the SETTLED zero-load reference
    # (§9.4), the pressed cell, and the pulled cell THROUGH failure. The
    # two un-loaded cells are named because "press and pull" does not
    # imply them: they are the un-loaded contact chemistries, visited
    # once each and never again.
    generation_plan: GenerationPlan  # which stages run to harvest, on
                                     # WHICH force model each runs (the
                                     # cascade and heal on the §4.7
                                     # foundation MLIP + ZBL; the
                                     # press/settle/pull on the
                                     # SAME foundation MLIP -- not a
                                     # committee, which is what breaks
                                     # the circularity), how many, and
                                     # at what conditions

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
    descriptor_settings:   DescriptorSettings  # the bispectrum the
                                     # ENVIRONMENT LIBRARY is built with
                                     # (§11.2; DESIGN §4.8 part 2,
                                     # 2026-08-29): cutoff through the
                                     # SECOND shell, expansion order, per-
                                     # species weights. Distinct from
                                     # DescriptorSpec above, which is
                                     # how the TRAINED MODEL sees an
                                     # environment; this one is the
                                     # gate's ruler
    gate_scatter_multiple: number    # the scatter multiple the library
                                     # is self-checked and baselined at
                                     # (§11.2); a project's own
                                     # disorder_scatter_multiple may
                                     # refine it
    # The name is COMPUTED, not stated — see fingerprint_of below — so a
    # changed recipe cannot pass itself off as the model validated last
    # month.
```

**Validation, mirroring §2's three phases.** A recipe is rejected if any
field of parts 1–6 is absent (§1.4's no-hidden-defaults applies here
exactly as it does to a project; parts 7–8 are required once `train` and
`refine` are built, 2026-08-26), if `domain` is empty,
if `species_union` disagrees with the phases listed in the starting
collection, or if `production_settings.audited` is false without the
run having declared itself exploratory. The third phase — does every
REFERENCED artifact actually exist — is built on the project side
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
    # STEP 1 (generate, ONCE, on the universal foundation MLIP): build
    # Collection 1 from the recipe (§11.2) and harvest Collection 2 from
    # a pair run recorded under that same model (§11.3). No committee
    # exists yet and none is needed -- the foundation model is the
    # generator (DESIGN §4.5 step 1), which is what breaks the
    # circularity.
    configs  = build_collection1(force_model_recipe)                # §11.2
    configs += generate_hard_configs(force_model_recipe)            # §11.3
    store = new_training_store(reference_data)   # ANI-style HDF5 (§4.3)

    # STEP 2 (label, convert, train): VASP labels a selected subset, the
    # converter folds it into the store, ALF trains -> the FIRST
    # committee, which has SEEN the hard region from its first epoch
    # (§11.4).
    committee = label_convert_retrain(configs, store,
                                      force_model_recipe)            # §11.4

    # STEP 3 (refine by sampling): re-run the protocol under the committee;
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

### 11.2 build_collection1 — the calm structures, built from the recipe

> **Built 2026-08-26 (silicon), `bootstrap/collection1.py`.** This
> section once designed a `seed_committee` trained on Collection 1
> alone, whose only job was to survive config generation. The
> 2026-08-21 decision retired that stage — the universal foundation
> MLIP is the generator — so Collection 1 is now plain training data,
> built here and labelled alongside Collection 2 (§11.4).

```
function build_collection1(force_model_recipe):
    # DESIGN §4.8 part 2 -- COLLECTION 1 of the settled recipe, six
    # families, ALL REQUIRED: bulk ground state, bulk strained, bulk
    # melt-quench amorphous, clean surfaces, rattled snapshots, warm
    # NVT/NPT runs. The static families are geometry (the bulk at the
    # lattice the generator model derives, §2.2; strain tensors and
    # seeded displacements applied to it; the §7 slab builder for the
    # surfaces); the two dynamic families are short LAMMPS runs under
    # the generator model, strided into frames. Small by construction,
    # so every frame is labelled WHOLE (§11.4). The strained-substrate
    # entries are here because the builder (§7.2) will demand exactly
    # them.
    lattices   = derive_phase_lattices(force_model_recipe)      # §2.2
    structures = bulk_family(lattices) + strain_family(lattices)
               + rattle_family(lattices) + surface_family(lattices)
               + melt_quench_family(lattices)                   # dynamic
               + warm_run_family(lattices)                      # dynamic
    # DESIGN §4.8 part 2 (2026-08-29): the same six families also yield
    # the ENVIRONMENT LIBRARY the §10.6 gate judges against, written
    # beside the collection.
    library = build_environment_library(structures, force_model_recipe)
    return structures, library   # triples unlabelled; library on disk
```

```
function build_environment_library(structures, force_model_recipe):
    # DESIGN §3.5 / §4.8 part 2. Catalogue the UNDAMAGED environments:
    # family 1 (cold ideal sites), family 6 (the same sites with their
    # thermal spread) and family 4 (the clean faces, so a slab's own
    # surfaces are not mistaken for damage). Family 2 is EXCLUDED — it
    # is carried past bond failure, and a broken environment must not
    # be catalogued as crystalline. Family 3 is not catalogued; it is
    # the SELF-CHECK: the disorder every tolerance must recognise.
    settings = force_model_recipe.descriptor_settings   # recipe part 7
    catalogued = frames of structures with family in {bulk, surface,
                                                      warm_run}
    environments = map species -> []
    for each (family, source, atoms) in catalogued:
        vectors = DESCRIPTOR_ENGINE.describe(atoms, settings)
        for each atom: environments[atom.species].append(vectors[atom])

    # The TOLERANCE is measured, not guessed: the typical distance of a
    # warm-run atom from its nearest COLD-BULK environment, per species.
    cold = environments restricted to family == bulk
    thermal_scatter = map species -> typical (say, the 90th-percentile)
        nearest-cold distance over that species' warm-run vectors

    # The recipe's warm runs must be at or above the temperature the
    # gate judges at (the heal's cool-to target, §10.5), or this scatter
    # is measured too tight; the recipe validator checks that.

    # Self-check and baseline at the scatter multiple the recipe names
    # (the project may refine it; the library records what it was built
    # and checked with).
    multiple = force_model_recipe.gate_scatter_multiple
    warm_disordered = fraction of warm-run atoms whose nearest-cold
                      distance > multiple * thermal_scatter[species]
    melt_disordered = fraction of melt-quench atoms (family 3) whose
                      nearest CATALOGUED distance > the same tolerance
    # A sound tolerance keeps warm_disordered near 0 and melt_disordered
    # near 1; the library REPORTS both, and generate refuses to write a
    # library that cannot separate them (DESIGN §3.5).
    return EnvironmentLibrary{
        model_name: force_model_recipe.generator.model,
        engine: DESCRIPTOR_ENGINE.name, settings: settings,
        environments: environments, thermal_scatter: thermal_scatter,
        warm_distances: per species, the nearest-cold distances above,
        warm_run_temperature: min over catalogued warm runs of
                              spec.temperature,
        self_check: { multiple, warm_disordered, melt_disordered },
        provenance: { families, frame_counts, surfaces catalogued } }
```

### 11.3 generate_hard_configs — reuse §9/§10 in "generate" mode

> **Built 2026-08-26, first slice (silicon).** `sabsim bootstrap
> generate` does three things. (1) It BUILDS Collection 1 itself, on disk,
> from the recipe: the bulk ground state at the model-derived lattice
> (§2.2), the strain sweep (static tensors applied to that cell), the
> rattled snapshots (seeded static displacements), the clean surfaces
> (the §7 slab builder), and the melt-quench and warm-run families as
> short LAMMPS scripts run out-of-process under the universal model
> with strided dumps. (2) It HARVESTS Collection 2 from an existing
> pair run's recorded trajectories — the prep dumps (family 7,
> the healed tail), the press dump (families 8–10, keyed by the
> StageLedger of §9.3 that the bond result manifest carries) and the
> pull dumps (family 11) — cut to the §6.4 sub-cell
> with `bootstrap/subcell.py`. The pair run is an ordinary
> `sabsim run --dump-visuals` under the universal model; nothing forks.
> The committee-of-one below is that model until ALF trains one.
> (3) It WRITES the environment library (§11.2, DESIGN §3.5; built
> 2026-08-29) as a PAIR of files: `environment_library.npz` — the
> arrays, per-species environment vectors and warm-run nearest-cold
> distances — and its sidecar `environment_library.toml` — model,
> engine, settings, thermal scatter, self-check fractions, warm-run
> temperature and provenance, readable by a person. The pair lands in
> the PREP FOLDER the command is run from
> (`<project>/prep_surfN_<label>/`, ARCHITECTURE §1, revised
> 2026-08-30; the working copy under scratch is kept too), which is
> exactly where the project's loader looks for that surface's library —
> nothing is copied anywhere. A homo pair's second prep folder may
> simply receive a copy of the first's library pair, since the library
> is a fact about the material, not the surface.


The one genuinely OURS step, and the one worth stating carefully: the
bootstrap has NO cascade and NO MD of its own. It RUNS the activation
(§10) and bond/debond (§9) stages and HARVESTS the configurations they
visit. "Generate mode" is a CONSUMER difference, not a stage fork:
production reads the verdict and measures off these stages; the bootstrap
reads their trajectory FRAMES as unlabeled training candidates. The
stages themselves are unchanged — the same code, read two ways.

```
function generate_hard_configs(force_model_recipe):
    # DESIGN §4.5 step 2. Five config families from the two stages, all
    # run on the universal foundation MLIP (the cascade with the §3.3
    # ZBL cores spliced in, §4.7; the heal and the gentle stages on the
    # model alone). In BOTH the gate verdict is INFORMATIONAL, never
    # halting -- a "failed" activation is a valuable hard config to
    # LABEL, not a pipeline stop (the §1 halt is a PRODUCTION rule, not
    # a generation one).
    candidates = empty list
    run = pair_run_named_by(force_model_recipe.generation_plan)

    # (a) Healed activated surfaces (family 7) -- the tail of each
    # half's activate recording, after the heal (§10.5). The committee
    # is never asked to reproduce a cascade (§3.3): the foundation
    # model made these, and the committee meets them only at the press.
    candidates.extend(harvest_frames(run.activate_dumps,
                                     after=run.heal_start_step))

    # (b) Families 8-11, keyed on the StageLedger the bond result
    # manifest carries (§9.3, DESIGN §5.5): 8 = the pair at press start
    # (the frame AT ledger.press_start); 9 = the settled reference
    # (frames in [settle_start, settle_end]); 10 = under compression
    # (frames in [press_start, hold_end]); 11 = every pull rung's
    # record. All cut to the §6.4 interface subcell.
    ledger = run.bond_result.press.stage_steps
    candidates.extend(subcell(frames_at(run.press_dump,
                                        ledger.press_start)))
    candidates.extend(subcell(frames_between(run.press_dump,
                                             ledger.settle_start,
                                             ledger.settle_end)))
    candidates.extend(subcell(frames_between(run.press_dump,
                                             ledger.press_start,
                                             ledger.hold_end)))
    candidates.extend(subcell(harvest_frames(run.pull_dumps)))

    return candidates
```

### 11.4 label_convert_retrain — VASP truth, then ALF retrains

> **Built 2026-08-26, first slice: the DIRECT labeller.** Until ALF's
> `QM_task` is wired, `sabsim bootstrap label` writes one VASP
> directory per selected structure (POSCAR from the structure; INCAR
> and KPOINTS from the recipe's production block — Γ only off-bulk,
> `KSPACING` for the two bulk families; POTCAR concatenated from the
> recipe's PAW choices in POSCAR species order) plus ONE SLURM job
> array routed by the rc's `[usage.label]` block, and submits nothing.
> `sabsim bootstrap harvest` reads each `vasprun.xml`, drops any cell
> that did not converge, and writes the labels as an extended-XYZ set
> (energy, forces, stress per frame) — the form the prototype's
> ANI-HDF5 converter consumes, so `train` can follow without a format
> change. Selection in this slice is the budget alone (the first N of
> each family, evenly strided); the interface-preference and
> uncertainty terms of `SelectionRule` engage once a committee exists.


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
    # potential_quality_gate function evaluate_pair_gates (§5) calls, but
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
the LOOP structure (§11.1); the Collection 1 COMPOSITION (§11.2 — which
calm structures to build); the "generate mode" frame-harvesting that
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
shared `potential_quality_gate` function §5's `evaluate_pair_gates`
calls; only its CONSEQUENCE differs — act versus report.

`[ABOVE this module]` re-entry — more material pairs, or new training
targeted at a project's gate weaknesses (§1's commented outer loop) — is by
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
    provenance: Provenance     # pair, trajectory, frame index, subcell,
                               # potential generation, seed set (§8.5)

record Manifest:
    # The WHOLE interface to Kaleidoscope (`DESIGN.md` §8.5): one list,
    # handed over, waited on. Retained as step 8's provenance record.
    units: list of AnalysisUnit

function run_characterization(structure, bond_debond_trajectory,
                              pair_specification):
    # DESIGN §8. Turn a finished press/pull into the all-electron and
    # descriptor measures, or into schema-valid `unresolved` records when
    # the subcell is unaffordable (§8.2) or Imago is late (§8.8). Returns
    # a MeasureVector (the §4 contract); §1 merges it with the analyzer's.

    # ONE structure convention: §6.4's interface subcell, extracted ONCE
    # at §5.3's reference state, frozen by atom identity (§8.2). If it
    # exceeds the affordable envelope, step 8 cannot run for this pair
    # without breaking a §6.4 rule — SAY SO, do not break one quietly.
    subcell = extract_interface_subcell(
        structure, pair_specification)     # [DELEGATE -> §6.4 / §8.2]
    if not subcell.affordable:
        return all_unresolved(
            "interface subcell exceeds the step-8 envelope (§8.2)")

    # SELECT the frames worth the expense (§12.2). The two relaxed M4
    # endpoints are NOT detected — they are computed states from §5, and
    # they enter the batch unconditionally (§8.3).
    frames    = select_frames(bond_debond_trajectory, subcell,
                              pair_specification)          # §12.2
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
    return harvest(manifest, results, pair_specification)  # §12.5
```

### 12.2 select_frames — three detectors, on the subcell, merged by event

```
function select_frames(trajectory, subcell, pair_specification):
    # DESIGN §8.3. The genuinely OURS piece, and a PURE, DETERMINISTIC
    # function of the trajectory and the settings — re-runnable, auditable
    # long after the MD is gone, part of provenance (§1.6). Three
    # detectors, each a physically meaningful moment:
    #   - PE local MINIMA in the hold -> a bond forming, shedding energy
    #   - PE local MAXIMA in the pull -> a bond stretched to its limit
    #   - sharp DROPS in sigma_zz     -> a bond breaking, shedding load
    numerical = pair_specification.numerical

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
    # timestamp id COLLIDES across projects — prior art's newest-file-wins
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

function harvest(manifest, results, pair_specification):
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
function begin_or_resume_pull(driver, reference, rate, pair,
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
            input_hash          = input_hash(pair, reference, rate),
            saved_step          = driver.step }        # 0 on a fresh run

    # RESUMING. Trust FIRST (§13.4), so a wrong-run resume stops before
    # it touches the engine. Then restore the saved atoms and reconcile
    # the record to them.
    verify_inputs_or_stop(checkpoint, pair, reference, rate)
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
function input_hash(pair, reference, rate):
    # What identifies "the same run" (DESIGN §11.4): the project's CONTENT
    # fingerprint (DESIGN §1.4, the identity §12.4 builds on), the
    # identity of the settled reference the pull restores from, and the
    # pull RATE — the only input that tells one rung from another, since
    # every rung shares the fingerprint and the one settled reference
    # (DESIGN §11.4). NOT paths, NOT the wall-clock — only things whose
    # change means a genuinely different experiment. The exact fields
    # ride on the same open follow-on as the fingerprint (DESIGN §1.8).
    return content_hash(pair.fingerprint, reference.identity, rate)

function verify_inputs_or_stop(checkpoint, pair, reference, rate):
    # A guardrail, not a correctness gate (DESIGN §11.4). Resuming reuses
    # what a previous run left in a directory, so it owes one check that
    # the inputs still match the run the checkpoint came from.
    if input_hash(pair, reference, rate) == checkpoint.ledger.input_hash:
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
function pull_at_rate(driver, reference, rate, pair, control,
                      checkpoint_dir):                            # §9.5
    numerical = pair.numerical
    timestep  = numerical.md_timestep
    # chunk_steps and checkpoint_cadence are RunControl ENGINEERING
    # settings (the same home as §9's chunk controls), NOT NumericalKnobs
    # — the answer is invariant to them; they trade work-lost-on-a-kill
    # against write cost. Provisional values live in code, not the spec.
    cadence   = control.checkpoint_cadence       # engine steps per save

    ledger = begin_or_resume_pull(driver, reference, rate, pair,
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
            geometry     <- interface_geometry(driver, recorded_plane,
                                               numerical)      # §9.6
            opening      <- geometry.opening
            bridges      <- cross_interface_bridges(driver, geometry.plane)

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
                                rate, pair)                          # §9.6
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

`[DELEGATE -> fingerprint, `DESIGN.md` §1.4]` the project identity the
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
a WRITER, `prepare`, that reads the project spec AND the deployment rc
and emits ready-to-submit scripts; and an EXECUTOR, `run`, that lives
INSIDE each script and does one job's worth of the pipeline. `sabsim`
submits NOTHING and watches nothing (the login-node wall, §4.1); the
human submits the scripts and inspects each gate before sending the
next.

Nothing here trains a potential or layers in a physics default. The force
model a pair uses is a LOOKUP behind the §1 `resolve_potential` seam —
the universal foundation MLIP today, the trained committee once the
bootstrap (§11, a SEPARATE upstream Tier-B process) has produced one — so
the same four jobs run either, unchanged. Deployment is "where," never
"what" (`DESIGN.md` §1.2).

Revised 2026-08-30 (Paul): a project is ONE pair, and its jobs are the
four STAGE FOLDERS of `ARCHITECTURE.md` §1 — `prep_surf1_<a>`,
`prep_surf2_<b>`, `bond_<a>_<b>`, `analysis_<a>_<b>` — named by
`stage_folders` (§2). The script that runs a stage carries the same
name as the folder it fills, so a person reading the project folder
sees one name per stage: the script, the folder of deliverables, and
the folder of bulk under `intermediate/`.

### 14.1 The deployment records (CLOSED)

```
record DeploymentConfig:              # the parsed rc (DESIGN §10, §4.1)
    cluster_name:     text
    scheduler:        text            # e.g. "slurm"
    default_account:  text
    module_paths:     list of path    # `module use` roots (§4.4)
    partitions:       map[resource_class -> Partition]  # "cpu" / "gpu"
    usage:            map[usage_key -> UsageBlock]      # keyed by KIND:
                                      # "prep" (both prep jobs read it),
                                      # "bond", "analysis"

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
# run. Each entry names the job, the usage block the rc resolves to a
# partition, the CONTIGUOUS SUB-STAGE of the §1 pair chain it owns --
# with the on-disk artifact it READS at entry and WRITES at exit -- and
# which stage folder it fills. That handoff (ARCHITECTURE §4.3) is
# exactly what lets one job start mid-chain in its own submission.
#
# A SUB-STAGE is a run of ADJACENT pipeline stages -- a section of the
# whole §1 stage sequence, NOT a piece of any one stage. Each job owns
# one; the `stages` field lists the stages that make it up.
record JobKind:
    name:            text             # "prep_surf1" / "prep_surf2" /
                                      # "bond" / "analysis"
    usage_key:       text             # -> a UsageBlock ("prep" for both
                                      # preps, else the job's own name)
    folder:          field of stage_folders   # WHICH stage folder it
                                      # fills (deliverables in the
                                      # project, bulk in the mirror)
    stages:          ordered list of Stage   # the stages of its sub-stage
    reads:           list of (folder, artifact_name)  # entry files, by
                                      # the stage folder that holds them
    writes:          artifact_name    # exit file, in ITS OWN folder
    depends_on:      list of job names  # what must have FINISHED first;
                                      # EMPTY for both preps, which is
                                      # what lets them run side by side

JOB_REGISTRY = ordered [
    JobKind("prep_surf1", usage_key = "prep", folder = prep_surf1,
            stages = [build_half,         # §7.1, wafer A
                      activate_surface],  # §10.1 (its own §3.5 gate)
            reads  = [],                  # starts from the spec
            writes = ACTIVATED_HALF,      # the healed, gated half
            depends_on = []),
    JobKind("prep_surf2", usage_key = "prep", folder = prep_surf2,
            stages = [build_half,         # §7.1, wafer B
                      activate_surface],
            reads  = [],
            writes = ACTIVATED_HALF,
            depends_on = []),             # INDEPENDENT of prep_surf1
    JobKind("bond", usage_key = "bond", folder = bond,
            stages = [assemble_pair,      # §7.5 (checks the cells agree)
                      press_and_bond,     # §9.3
                      settle_reference,   # §9.4
                      pull_ladder],       # §9.5 (rungs, committee in-proc)
            reads  = [(prep_surf1, ACTIVATED_HALF),
                      (prep_surf2, ACTIVATED_HALF)],
            writes = PULL_RESULTS,        # per-rung curves + trajectories
            depends_on = ["prep_surf1", "prep_surf2"]),
    JobKind("analysis", usage_key = "analysis", folder = analysis,
            stages = [run_analyzer,          # §4 measure vector, PLUS
                      run_characterization], #   the mocked step-8 char
            reads  = [(bond, PULL_RESULTS)],
            writes = MEASURE_VECTOR,      # the §4 vector, GATED (§14.3)
            depends_on = ["bond"]),
]
```
Inserting a job later (§10.3, say a relax between the preps and bond)
is ONE entry here; the `run` flags, the written filenames, the guided
index and the dependency lines all follow — the truth is never written
twice. The two preps are the `ARCHITECTURE.md` §4.3 "Approach C"
fan-out: the same stage code, submitted as two jobs the scheduler may
run at once, joined at the bond job's barrier by the files.

### 14.3 The run selector — one job, or the whole chain (§10.4)

```
function run(project_spec_path, job_flag):
    # job_flag is at most ONE of {prep_surf1, prep_surf2, bond,
    # analysis}, or NONE for the whole pair chain (§10.4). There is no
    # `--only`: a project holds one pair (revised 2026-08-30 (Paul)).
    # This is the line that lives INSIDE each generated script; it runs
    # within an allocation and submits nothing itself.
    validated = load_and_validate_project(project_spec_path)   # §2
    pair      = validated.pair
    if job_flag is NONE:
        exec_one_pair(pair, validated.project_directory)      # §1 chain
    else:
        run_pair_job(pair, validated.project_directory,
                     registry_lookup(job_flag))
```

```
function run_pair_job(pair, project_directory, job):
    # ONE job's contiguous SUB-STAGE of the §1 chain. It ENTERS by
    # re-reading its `reads` artifacts from the stage folders that hold
    # them -- the same read-from-file handoff activate_surface already
    # uses (§10.1 re-reads the pristine half), so this process needs NONE
    # of the stages before it. The potential is the LOOKUP every job
    # does (§1 resolve_potential): foundation MLIP now, trained
    # committee later, SAME seam.
    folders = stage_folders(pair)                                 # §2
    home    = stage_scratch(project_directory, job.folder)       # its
                                     # project folder + scratch mirror,
                                     # this run's fresh `run-<id>/` made
    potential = run_to_contract(
        () -> resolve_potential(pair), POTENTIAL_CONTRACT)        # §1
    seeds = [ read_artifact(project_directory / folder, name)
              for (folder, name) in job.reads ]      # [] for a prep job
    # Run this job's stages exactly as §1 runs them, but only this
    # sub-stage, each guarded by run_to_contract so a bad artifact HALTS
    # here (§5.1). The final stage writes job.writes into ITS OWN stage
    # folder (the deliverable) with the bulk in the folder's mirror; the
    # NEXT job (a separate submission) reads it. Nothing crosses in
    # memory.
    run_sub_stage(job.stages, seeds, pair, potential, home)
```
`[DELEGATE -> the exact per-stage calls and signatures are §1's;
`run_pair_job` reuses them, differing only in that it starts from
`seeds` rather than the previous in-memory handle.]`

The analysis job's sub-stage is the WHOLE tail of `exec_one_pair` (§1),
not just `run_analyzer`: after it, the job MERGES the mocked step-8
characterization (`run_characterization`, §4) and READS the §5 gate, so
the MEASURE_VECTOR it writes is the GATED pair result (§1's PairResult),
not a bare measure list. The gate adds no stage -- it only reads the
vector and reports (§5, VISION principle 5) -- which is why §14.2 lists
the two producing stages while the gate rides along here.

**Where a stage's files go (`stage_scratch`).** Each stage has TWO
homes with ONE name (`ARCHITECTURE.md` §1, §4.1): `<project>/<stage
folder>/` for DELIVERABLES — the manifests, ledgers, gate reports, the
activated-half handoff, the measure vector; small, precious, kept with
the project — and `<project>/intermediate/<stage folder>/` for BULK —
dumps, LAMMPS logs, data files, generated inputs; large, regenerable,
on scratch. `intermediate` is the link into the scratch mirror of the
project's own path, so there is no study or pair key inside it: the
mirror repeats the four folder names and nothing else. A rerun NEVER
overwrites: `stage_scratch` makes a fresh `run-<scheduler job id>/`
(or a dated name off the scheduler) under the stage's bulk folder for
each run, and the deliverable manifest records which run it came from.

### 14.4 prepare — the writer (§10.5, §10.6)

```
function prepare(project_spec_path, deployment_rc_path):
    # Reads BOTH inputs and writes scripts; submits nothing (§10.1). Runs
    # on the login node, so it must FAIL THERE, readably, rather than emit
    # scripts that die on a compute node an hour in.
    roots = resolve_location_roots()      # scratch / share / local, §10.5
    if any root does not resolve:
        STOP on the login node, naming the missing root   # §10.5 gate
    deployment = load_deployment(deployment_rc_path)      # §14.1
    validated  = load_and_validate_project(project_spec_path) # §2, incl.
                                          # BOTH wafers' libraries (§10.6)
    folders    = stage_folders(validated.pair)            # §2
    make the four stage folders under validated.project_directory
    if they do not exist (never touching one that does)

    guide = new submission guide          # the ORDERED index (§10.5)
    for each job in JOB_REGISTRY:         # preps -> bond -> analysis
        usage     = deployment.usage[job.usage_key]
        partition = deployment.partitions[usage.resource_class]
        # Two cheap checks (§10.6): compare numbers already written in
        # the rc. Predict NOTHING about run length or footprint.
        if usage.walltime > partition.max_walltime:
            STOP on the login node, naming job + ceiling  # §10.6 gate
        if usage.gpus_per_node > 0 and (
                usage.gpus_per_node > partition.gpus_per_node):
            STOP on the login node, naming job + GPU ceiling  # §10.6
        script = render_job_script(validated, job, usage, partition,
                                   deployment, roots)
        path   = folders[job.folder] + ".slurm"   # SAME name as the
                                                  # folder -- NO ordinal
        write script to path
        guide.append(job, path, job.depends_on)   # ORDER lives here
    write guide beside the scripts        # a submission GUIDE, not "readme"
    return guide
```

The guide (§10.5) reads as the dependency graph, in plain words: submit
`prep_surf1_<a>.slurm` and `prep_surf2_<b>.slurm` (in either order, or
together); when BOTH have finished and their gate reports are to your
liking, submit `bond_<a>_<b>.slurm`; then `analysis_<a>_<b>.slurm`. It
also prints the one-line chained form for a person who trusts the
gates: the two preps, then bond with `--dependency=afterok:<id1>:<id2>`,
then analysis with `afterok:<bond id>`.

### 14.5 What a generated script contains (§10.5, §10.7)

```
function render_job_script(project, job, usage, partition, deployment,
                           roots):
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
        positive, so a CPU job gets no --gres (§10.6). The job NAME is
        the stage folder's name, so `squeue` reads like the project.
      - `module use <p>` for each p in deployment.module_paths, THEN
        `module load <m>` for each m in usage.modules (§4.4: the cpg tree
        is not on the default path; bond loads the ONE deepmd engine,
        whose module also LD_PRELOADs libstdc++ and exports
        DEEPMD_LMP_PLUGIN).
      - the three location roots BAKED IN as resolved values -- a frozen
        snapshot, not a re-read of the rc at run time (§10.5, §1.4).
        A prep job's two DATA inputs -- the root-relative universal
        weights and ITS wafer's environment library in that wafer's
        prep folder (§10.6, revised 2026-08-30) -- are resolved by
        prepare's fail-fast gate before anything is written, so a
        missing library stops on the login node and names the surface.
      - `cd` to the PROJECT folder (the folder holding the project file),
        so relative paths in the script mean the same thing whichever
        folder the person submits from.
      - the launcher + `python -m sabsim run <project file>
        --<job.name>` (§14.3) -- e.g. `mpirun -np <N>` INSIDE the
        allocation, never on the login node (§4.1). N = usage.nodes x
        usage.tasks_per_node, emitted as `--ntasks-per-node` so the
        scheduler's own $SLURM_NTASKS drives the launcher. Every dynamic
        run passes `--dump-visuals`, so a trajectory is always there to
        look at.
      - on success, a printed line naming what to check and which script
        to submit next (§10.5), reinforcing the guide: a prep job names
        its gate report and says "when the OTHER prep has also passed,
        submit bond"; bond names its stage ledger and says "submit
        analysis"; analysis says the measure vector is written.
```
`[DELEGATE -> the deepmd `plugin load`: the bond job's LAMMPS INPUT issues
`variable dp getenv DEEPMD_LMP_PLUGIN; plugin load ${dp}` inside the
force-model command block (`ARCHITECTURE.md` §4.4, `driver/commands` §9),
NOT here -- render_job_script only loads the module that exports the var.]`

### 14.6 The handoff artifact form (`read_artifact`/`write_artifact`)

§14.3 delegated the READ and WRITE at the mid-chain seams; this pins
what those artifacts physically ARE. A job submitted on its own re-reads
its entry artifact in a FRESH process -- it does not inherit the warm
in-memory object the whole-chain run passes stage to stage. So the
mid-chain artifacts (ACTIVATED_HALF, which each prep writes and bond
reads twice; PULL_RESULTS, which bond writes and analysis reads) must
be COMPLETE on disk: everything the downstream job needs,
reconstructible from files alone. Each takes the SAME shape the §3
trajectory already uses -- small things INLINE, large things BY
REFERENCE.

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

So ACTIVATED_HALF is the LAMMPS data file of the healed half (the atoms
-- a payload the cascade session already writes) plus a manifest
carrying what the bond job CANNOT re-derive from the atoms: which wafer
it is, the SHARED CELL it was built in (so bond can check the two
halves agree, §7.5), the gate verdict with its measured depth, the
MEASURED activated_skin atom-index set (`DESIGN.md` §2.6 -- a measured
set, not a depth cut, so it MUST travel), and the run it came from.
Bond's own assembled pair (`assembled_pair.data` + its manifest with the
per-wafer z-ranges and the interface plane) is written to the bond
folder as an internal record. PULL_RESULTS is a manifest of each rung's
reduced fields (rate, complete, separation_index, atoms_conserved, the
verdicts) plus its reduced curves (grip_displacement, force_vs_grip): a
curve small enough stays inline, a curve large enough becomes a payload
file -- the SAME small-inline / large-by-reference rule, applied field
by field. The full per-atom trajectory is ALREADY a §3 FrameSetRef
payload on scratch and is NOT duplicated here.

`write_artifact(folder, name, record)` writes the manifest (and any
small payload) into the stage's PROJECT folder and any bulky payload
into its mirror, recording the resolved path; `read_artifact(folder,
name)` reads the manifest and rehydrates the record, opening a payload
only when a consumer needs it. In v1 the ACTIVATED_HALF groups and the
PULL_RESULTS curves are both small enough to sit inline, so no payload
beyond the LAMMPS data file is written yet -- but the seam IS the
by-reference one, so a field that GROWS large is externalized later
without changing the contract.

One more re-read the analysis job makes. `run_analyzer` needs the
interface AREA (the assembled pair's lateral cell) to reduce the work
per unit area, which the PULL_RESULTS does not carry. So analysis reads
its OWN entry artifact (PULL_RESULTS) AND re-reads the bond folder's
assembled-pair manifest -- both persist there, so this is a plain
re-read, not a new hand-off. A job's `reads` field (§14.2) names its
DEFINING upstream; a job may still re-open any earlier artifact the
project's stage folders hold.

`[DELEGATE -> the manifest's on-disk syntax and the compression codec for
a bulky payload are CODE-level. The manifest is written as TOML, keeping
it consistent with the project-spec and rc files a human reads and
edits. The standard library READS TOML (`tomllib`) but cannot WRITE it,
so the code emits the few value types a manifest uses (scalars, scalar
arrays, nested tables, arrays of tables) through a small hand-rolled
writer; a null field is simply OMITTED, since TOML has no null, and the
read side maps a missing key back to "none". The CONTRACT here is only
"readable manifest + referenced payloads, small-inline /
large-by-reference."]`

### 14.7 init -- the project-folder generator (`DESIGN.md` §10.9)

The §1.4 generator as a command. It writes what is MISSING from a
project folder and touches nothing that is there; it reads the project
file it wrote to learn the pair's labels; it gives each surface the
recipe template of ITS material. It submits nothing and runs nothing.

```
constant TEMPLATE_ROOT     = <repository>/share/templates
constant RECIPE_TEMPLATES  = TEMPLATE_ROOT/recipes      # <label>.toml
constant FALLBACK_RECIPE   = RECIPE_TEMPLATES/si.toml   # a start, in
                                                        # the open

record InitReport:
    written: list[path]          # files and folders this run made
    kept:    list[path]          # already there -- left untouched
    notices: list[str]           # e.g. "no recipe template for X"

function init_project(project_folder) -> InitReport:
    make_folder_if_missing(project_folder)

    # 1. The two top-level inputs, straight from the templates.
    copy_if_missing(TEMPLATE_ROOT/project_spec.toml,
                    project_folder/sabsim.toml)
    copy_if_missing(TEMPLATE_ROOT/deployment_rc.toml,
                    project_folder/deployment.toml)

    # 2. Read the labels back with the PLAIN TOML parser -- a file the
    #    person is midway through editing must still yield them.
    raw     = parse_toml(project_folder/sabsim.toml)
    label_a = raw["wafer_a"]["material"];  label_b = raw["wafer_b"]["material"]
    folders = stage_folder_names(label_a, label_b)        # §2, one source

    # 3. The four stage folders, and a recipe in each prep folder.
    for name in folders:
        make_folder_if_missing(project_folder/name)
    for (prep_folder, label) in [(folders.prep_surf1, label_a),
                                 (folders.prep_surf2, label_b)]:
        template = RECIPE_TEMPLATES/(lower(label) + ".toml")
        if not exists(template):
            template = FALLBACK_RECIPE
            notice("no recipe template for " + label + "; wrote the "
                   "silicon recipe as a starting point -- edit it")
        target = project_folder/prep_folder/recipe.toml
        if missing(target):
            text = read(template)
            # The one line that is per-project, not per-material.
            text = set_generation_plan_project(text,
                       absolute(project_folder/sabsim.toml))
            write(target, text)

    return InitReport(written, kept, notices)
```

`stage_folder_names(label_a, label_b)` is the label-level form of §2's
`stage_folders(pair)`; the pair-level one delegates to it so the
layout is still written down once. The CLI prints the report and then
the three next steps in order -- edit the inputs, build each surface's
environment library on a compute node, run `prepare` -- because the
generated folder is complete in the §1.4 sense and unread in the
science sense until the person has looked at it (§10.9).

`[CODE level, below pseudocode]` the exact directive syntax (SLURM
`#SBATCH`), the script templating, and the guide's on-disk format.

`[ABOVE this module / OUT of scope]` the BOOTSTRAP (steps 1-2, §11) is NOT
one of these four jobs and NOT a `run` flag: it is a separate Tier-B
process (ALF's own Parsl loop plus direct VASP seed jobs, `DESIGN.md`
§4.5) that MANUFACTURES the potential upstream of every pair, run from
inside a prep folder (`sabsim bootstrap generate`, §11.3). `prepare`
writes the four STAGE jobs that CONSUME it; deploying the bootstrap
itself is ALF's concern, not this consumer's (§4.1, "no Parsl-in-Parsl").
