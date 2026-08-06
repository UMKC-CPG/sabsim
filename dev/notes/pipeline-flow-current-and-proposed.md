# SABSIM run flow: current (grounded) and proposed

Working note, 2026-08-05. NOT canonical yet — a reviewable synthesis to
decide what lands in VISION / ARCHITECTURE / DESIGN and at which level.

## SESSION STATUS (2026-08-05, resume here)

**Decisions reached with Paul this session:**
- **Argon:** strip it (atoms AND declared species) at the END of the
  cascade, before the re-settle. AGREED. → applied to DESIGN §3.4.
- **B/C (no classical potential):** "universal" = an off-the-shelf,
  already-trained foundation model (MACE-MP / CHGNet kind), rough but
  no per-material fitting. So we do NOT need a third bespoke amorphization
  model: rough model (classical where it exists, universal where it does
  not) for the violent cascade; ONE bespoke committee for the gentle
  stages. B collapses into the existing §4.7 ladder.
- **Relaxation sequence:** one fixed in-plane footprint (set under the
  committee, since the final measurement is under it); at each force-model
  handoff re-relax internals + out-of-plane only; cold-start falls back to
  the rough/seed model. AGREED (in-plane framing + cold-start caveat). →
  applied to DESIGN §2.2.
- **E:** production runs drive dynamics with one representative model and
  check the full committee's disagreement on a stride (abort if it wanders
  untrusted); "all members every step" is reserved for data-generation.
  Transition data-generation → production = convergence (uncertainty below
  threshold + quality gate). AGREED; only the threshold numbers are soft.
- **D (ALF):** ALF manages the committee internally; SABSIM sets the size
  and provides two plugin functions (train, load). Already documented
  (ARCH §2.2, DESIGN §4.4) — no edit needed.

**Applied this session (DESIGN.md, uncommitted — Paul pushes):**
- §3.4 — the projectile-strip paragraph (argon type gone before re-anneal).
- §2.2 — "one in-plane footprint, several potentials" + the one-line
  "cascade in step 4 is the exception" correction.
- §4.8 (part 2) — **A applied**: warm NVT/NPT crystal samples added to the
  starting collection, with the rationale that a committee taught only
  cold + rattled structures reports meaningless disagreement the instant
  a warm stage (re-settle/press/settle/pull) begins.
- §4.7 (ladder) — **B/C applied**: Tier 2 now pins "universal" = off-the-
  shelf foundation model (MACE-MP / CHGNet, no per-material fitting), and
  a new "Why not a bespoke amorphization model per material?" paragraph
  records that B (a third MLIP) was weighed and rejected (scaffold-grade
  bar + STRUCTURAL 1b).

**CPU/GPU contradiction — RESOLVED 2026-08-06 (universal-first pivot).**
Paul chose to make the universal foundation model the DEFAULT cascade
potential (Si-only is insufficient for his materials), which dissolves
the contradiction: a universal cascade is GPU work, so the whole activate
job is GPU and the re-anneal riding along is GPU too — no CPU/GPU tension.
General rule now in the docs: **the activate job's class FOLLOWS the
cascade potential's tier** (universal→GPU default; opt-in classical→CPU),
set per-member via the `gpus_per_node` knob. Applied as a 9-edit pass:
DESIGN §4.7 reframed "universal-first, classical optional" (heading,
intro, ladder, registry trim, version-pinning line, frozen-v1) + ARCH
§4.1 (intro sentence, table rows, URGENT→Settled block). All UNCOMMITTED
(this pass is AFTER commit 2389403; a new commit will cover it).

**Still OPEN (next time):**
- **E** threshold numbers.
- Housekeeping: TODO.md still lists the CPU/GPU item as URGENT — mark it
  resolved. Consider whether to build Tier-2 (MACE-in-LAMMPS + ZBL
  overlay) as the next implementation step (task, not yet scoped).
- The **re-settle CPU-vs-GPU** contradiction (ARCH §4.1 table vs DESIGN
  §10.2), which ARCHITECTURE itself marks "OPEN — URGENT".

**Task #8 — REFRAMED AGAIN 2026-08-06 (vacuum-gap relax, code DONE).**
Two findings changed the plan. (a) "Re-anneal under deepmd" cannot be a
one-liner: the re-anneal runs in the cascade's LAMMPS session where argon
is a declared TYPE, and deepmd's `pair_coeff * *` maps types 1:1 onto the
model's type_map, so a Si-only model errors with 2 declared types — LAMMPS
cannot drop a type in-session. (b) Paul's insight: assembly ALREADY strips
the argon type (Si-only pair), and the slabs are placed a *configurable*
`initial_gap` apart (currently 3 Å, WITHIN the 6 Å model cutoff). Open the
gap beyond the cutoff and a single joint relax heals each surface as an
effectively-FREE surface — no separate re-anneal session needed.
So #8 became **relax–press–settle–pull**: assemble at initial_gap ≈ 10 Å;
a new pre-press RELAX (minimize + short room-T hold, both grips pinned)
under deepmd, gated to run ONLY when the assembled closest-atom gap clears
`RunControl.separation_cutoff` (so the classical 3 Å path is untouched).
CODE DONE + 299 tests: `commands.contact_relax_commands`, `_press_setup`
split (drive issued separately), `press_and_bond` runs the relax then the
drive, `RunControl.relax_chunks=5`, `_assembled_gap` guard. Model cutoff
read from Prakash Si `input.json`: rcut 6.0, type_map ['Si']. NEXT: the
GPU proof run (activate classical @gap10 → bond deepmd) + ledger T-8.
DEFERRED DESIGN (§3.4/§2.6): whether this joint relax should REPLACE the
per-slab re-anneal, and where the gate then runs — kept BOTH for now.

**RUN IN FLIGHT (resume monitoring here).** #8 proof in
`jobs/si_si_deepmd/` (spec @ initial_gap 15 A; prepared + hand-edited
scripts; `jobs/` is gitignored so this lives on disk only).
- ACTIVATE re-run **job 15876062** COMPLETED (gate passed, Si-only,
  closest-atom gap 11.04 A — free for the relax). Good pair on scratch.
- BOND **job 15876145** FAILED (6:08): `Lost atoms 8799->8782` in the
  RELAX minimize. Diagnosis: the surfaces are CLASSICALLY amorphized, so
  the first bulk Si `.pb` sees them OUT OF DISTRIBUTION and a plain
  minimize ejects ~17 loose surface atoms. Same root cause as 6b
  (classical->trained OOD), caught earlier (before scissors/press).
- FIX (committed after this note): `contact_relax_commands` is now
  damped + displacement-CAPPED dynamics + reflecting wall instead of a
  minimize. **THIS IS A TEMPORARY SCAFFOLD** to exercise the plumbing on
  an inadequate model — flagged in the docstring, `_RELAX_DISPLACE_CAP`,
  the call site, and a TODO ("REMOVE the TEMPORARY OOD relax scaffold").
  The real fix is activation under the trained COMMITTEE (DESIGN §3.4,
  deferred per-slab re-anneal under DeePMD); then the scaffold is deleted.
NEXT: re-submit `si-si-reference_bond.slurm` (code auto-picks up via the
editable venv). GREEN = `plugin load` -> `pair_style deepmd` ->
`relax_cap_i ... nve/limit` + `relax_wall` (capped settle, no ejection)
-> `displace_atoms scissors_upper` -> press -> NO `Lost atoms` ->
`settled_reference.data` -> `pull_results`. Then ledger T-8.

**Older follow-up still open:** wire the multi-step handoff relaxation +
the currently-unwired `bulk_relax` (DESIGN §2.2).

**How this was built.** Three careful reading passes, kept separate:
one over the design chain (VISION, ARCHITECTURE, DESIGN, PSEUDOCODE)
only; one over the source under `src/sabsim/` only; one over the ALF
clone plus the DeePMD prototype for the committee question. No memory,
no secondary sources (the `prototypes/` critique and diagram were
deliberately excluded). Every claim below traces to a document section
or a `file:line`. Where the design says one thing and the running code
does another, both are stated.

Vocabulary (kept plain on purpose):
- **classical force field** — a simple, hand-built potential
  (Stillinger-Weber for silicon) plus a **short-range repulsion** (ZBL)
  so fast atoms cannot pass through each other.
- **trained model** — the machine-learned potential (DeePMD). The
  design runs it as a **committee**: several independently-trained
  models (four, by default) whose disagreement is the uncertainty
  signal.
- **the handoff** — the point where the run stops using the classical
  force field and starts using the trained model.

---

## PART I — How a run works TODAY

The single most important fact: **no trained model has been built, so
everything the design assigns to the trained model actually runs on a
classical stand-in** — except one validation hook (`SABSIM_DEEPMD_MODEL`)
that swaps a real trained model into the squeeze/pull step only. The
table separates the *designed owner* from *what runs today*.

| # | Stage | What happens | Designed owner | Runs today |
|---|-------|--------------|----------------|------------|
| 0 | Resolve potential | Look up the frozen potential for this pair | trained committee, by fingerprint | **stub** string `classical-stand-in`, and the live stages **ignore it** — each stage picks its own force field (`sequencer.py:142`, `skeleton_stages.py:59`, code discrepancy #1) |
| 1 | Build the two slabs | Cut each wafer to its surface, in vacuum | after **relaxing the bulk under the model** to get the true lattice (DESIGN §2.2) | real, BUT the bulk-relax is **never called** — slabs are cut on the textbook lattice the design forbids (`bulk_relax.py` unused; `slab_builder.py:198`). Only silicon-to-silicon runs; a real mismatched pair is refused (coincidence matcher unused) |
| 2a | Bombard the surface | Fire argon atoms to disorder the surface | **classical + short-range repulsion** (DESIGN §3.3) | same — classical SW + two repulsion cores (`cascade_potential.py`). Consistent. |
| 2b | **Re-settle** (the handoff) | Gently relax the disordered surface | **trained model** (DESIGN §3.4) | **classical stand-in.** The trained-model switch does **not** reach here, and the argon *type* is still declared (see the argon thread), so a silicon-only trained model cannot run here today |
| 2c | Activation checkpoint | Pass/fail structural tests on the roughened layer | — | **real and blocking** — the one enforced physics gate (`activation_gate.py`, halts on fail) |
| 3 | Join the two slabs | Assemble the facing pair, drop stray atoms | — (geometry) | real (silicon case). **This is where the element list drops from two to one** (`amorphized_assembly.py:386`) |
| 4 | Squeeze / settle / pull | Press into contact, settle to zero load, pull apart at several rates | **trained model** (DESIGN §5) | classical stand-in **unless** `SABSIM_DEEPMD_MODEL` is set → real trained model. **The only stage the switch touches** (`live_stages.py:630`) |
| 5 | Measure | Work of separation from the pull curves | model-fidelity | real for the one mechanical measure; the others are placeholder `unresolved` |
| 6 | Characterize interface | All-electron bond analysis | VASP / Imago | **mock** — returns `unresolved` (`skeleton_stages.py:243`) |
| 7 | Grade | Member gate + the two-pair ratio | reports (v1) | report-only; every result stamped `trusted=False` |

**Upstream, once per pair (steps 1–2 of the eight): build the trained
model.** Designed as VASP labels + ALF active learning. **Not built at
all** — no committee is ever trained.

### The classical → trained boundary, as designed

Inside the activation step: the classical force field owns the violent
bombardment; the trained model takes over at the gentle re-settle and
owns everything after (re-settle, squeeze, settle, pull, and the
model-fidelity measures). All-electron codes own only the training
labels and the final interface characterization.

### The argon thread (the sharpest current gap)

- Every slab **declares argon as a second element** from the start, even
  before any argon atom exists (`live_stages.py:239`).
- Argon atoms are created during bombardment, then **deleted by type
  during the re-settle** (`cascade.py:388`).
- BUT the argon **type stays declared** through the re-settle (mapped to
  "nothing" for the classical field). The element list only drops to
  silicon-only at the **join** step (`amorphized_assembly.py:386`).
- Therefore a silicon-only trained model **cannot run at the re-settle**
  today — the design is silent on stripping argon before the re-settle
  (it strips stray atoms only at the join, DESIGN §2.6), and the code
  confirms the type lingers. This is exactly where task #8 crashed.

### Inconsistencies and unsettled points (consolidated)

1. **Argon vs the re-settle** (above). Design silence + code fact. The
   one that blocks a trained-model re-settle. *(sharpest)*
2. **Re-settle: ordinary vs graphics processors.** ARCHITECTURE §4.1's
   table says GPU; DESIGN §10.2 folds it into the CPU activate job. The
   architecture document marks this "OPEN — URGENT" itself.
3. **Designed vs. reality.** The design attributes the gentle stages to
   the trained model; today they run classical, `resolve_potential` is
   ignored, and provenance **mislabels** a real trained-model pull as
   `classical-stand-in` (code discrepancy #1).
4. **Bulk-relax written but unwired** — the run builds on the forbidden
   textbook lattice (code discrepancy #4).
5. **Coincidence matcher unused** — only silicon-to-silicon executes; a
   real mismatched pair (silicon-to-silica) is refused at the join. So
   "choose materials A & B" is the design; silicon-to-silicon is what
   runs (code discrepancy #5).
6. **The average-over-random-seeds loop** is asserted to live in the
   sequencer but is absent from the sequencer's own control flow (design
   inconsistency #3).
7. **Missing gates in code:** the potential-quality gate and the live
   interface-fidelity check **do not exist**; the member gate reports
   only; characterization is mocked.
8. **Placeholder numbers throughout** — activation references flagged
   `real=false`, uncertainty thresholds, interface-subcell size,
   force-model recipe cutoffs — the flow depends on numbers that do not
   yet exist.
9. **The no-classical-potential fallback ladder** (DESIGN §4.7) is
   designed (three tiers) but only the first (silicon) is built.
10. Minor: a dangling `§12` cross-reference; the two "settle/anneal"
    steps share vocabulary; the amorphization-depth target was re-pinned
    to 7 Å and carries three historical values.

---

## PART II — The proposed flow (your A–E woven in)

The spine is unchanged: **classical bombardment → trained re-settle →
trained squeeze/pull → measure → characterize → ratio.** The changes:

**Seed set (A).** Enrich the trained model's starting data. Most of A is
**already in the design** (DESIGN §4.8): perfect crystals (ground
states), clean surfaces, strained substrates, AND uniformly
stretched/compressed/sheared cells past the reversible range. The **one
genuinely new part of A** is finite-temperature *sampled* configurations
— the design has only "rattled" (thermally-displaced) snapshots, not
warm MD ensembles. → add warm NVT/NPT sampling of the crystals to §4.8.

**Three trained models (B), motivated by no-classical-potential (C).**
Today's design uses a classical force field for the bombardment and one
trained committee ({Si, O}) for the gentle stages. Your proposal: for
materials with **no usable classical force field** (lithium niobate,
gallium nitride), train **one extra model per material, fused with the
short-range repulsion, purpose-built for the bombardment** — giving
three models total (two amorphization models + one production
committee). This **extends the design's existing fallback ladder** (§4.7
already anticipates C): its middle rung is a *universal/foundation* model
+ repulsion for the bombardment. Your B differs by proposing a
**per-material trained** model there instead of a universal one — a real
choice to weigh (per-material accuracy vs. the cost of training two more
models per pair).
- A clean by-product: an amorphization-specific model **would** include
  argon in its vocabulary (it owns the cascade), while the production
  committee stays {Si, O}. That actually **sharpens the handoff**: the
  argon is stripped *between* the two models — which is exactly the fix
  the current argon gap needs.

**Committee production (D).** ALF manages the committee **internally**.
The caller (SABSIM) supplies only the committee **size** and two plugin
functions (train, and load-as-calculators); ALF runs the sampling,
computes the disagreement (spread across members), selects frames to
label, and decides when to retrain. So on the chart, training is an
**opaque box we configure, not orchestrate**.

**Committee at the pull (E).** Grounded reading: the design's live
abort-on-disagreement (§7.3) and ALF's own committee calculator both
evaluate **all members together in one running simulation** — you cannot
abort a run live on disagreement if you ran the members one-after-
another. So the answer leans **parallel / in one process**, not N
separate serial runs. The genuinely **open** sub-question (worth pinning
in DESIGN): during a *production measurement* — as opposed to
data-generation — do we (i) drive the dynamics with a single
representative model and evaluate the full committee's spread only **on a
stride** (cheaper, coarser abort), or (ii) evaluate all members every
step (costlier, immediate abort)? Recommendation: (i) for production,
(ii) reserved for the data-generation runs where you *want* the
uncertainty to steer the dynamics.

---

## PART III — Where each piece should be documented

| Item | Level | Home |
|------|-------|------|
| Name the "two force fields, one handoff" as *the* organizing idea | ARCHITECTURE | §2.2 |
| Strip argon **before** the re-settle; pin where | DESIGN (+ code) | §3.4, §2.6 |
| Resolve re-settle CPU vs GPU | ARCHITECTURE / DESIGN | §4.1 ↔ §10.2 |
| Add warm MD sampling to the seed set (A) | DESIGN | §4.8 |
| Per-material amorphization model + repulsion (B/C) | ARCHITECTURE + DESIGN | §2.3, §4.7 |
| ALF owns committee production (D) | ARCHITECTURE + DESIGN | §4, §4.4 |
| Production pull: one model + strided committee check (E) | DESIGN | §5, §7.3 |
| Show "built vs not-built" honestly (the v1 gap) | all / the chart | — |
| Wire bulk-relax; wire the coincidence matcher | (code follow-ups) | — |

---

## Open questions for you (before we edit any canonical doc)

1. **Argon/handoff:** strip argon at the end of bombardment (so the
   re-settle can run under the trained model, as designed) — agreed?
2. **B vs. the existing §4.7 ladder:** per-material amorphization models
   (your B) or the universal-model rung already designed — or both, as
   ladder tiers?
3. **E:** adopt "one model drives, committee checked on a stride" for
   production runs?
4. Which of these do you want written into the documents **first**?
