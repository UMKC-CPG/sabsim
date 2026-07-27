# Deployment DESIGN section — discussion in progress

> **Status (2026-07-26) — DISCUSSION COMPLETE, SECTION WRITTEN.** All
> questions (Q1-Q5) are resolved and the DESIGN section is now written as
> **`DESIGN.md` §10** ("Deployment — preparing and submitting a study to
> a cluster"), with §5.6 and §5.9 reframed for the Q5 walltime decision.
> Nothing is coded yet. PROPAGATION status (2026-07-26): (1) DONE —
> `ARCHITECTURE.md` §4.3 revised to three per-kind jobs, preserving its
> Approach-A (serial halves) argument as a SEPARATE axis living inside
> the activate job; (2) DONE — `dev/templates/deployment_rc.toml`
> reshaped: `modules` moved out of `[hardware]` into per-kind `[usage.*]`
> (cascade-md=lammps; bond-md=lammps+deepmd; vasp=vasp; sequence=[]);
> (4) DONE — the `/refine` resolved the §10/§11 question (see the revised
> "Placement finding" below): the bare `§10.x` refs were `PSEUDOCODE.md`
> §10 cross-refs missing the prefix, so no DESIGN §10 was ever reserved;
> the refs were prefixed, the stub removed, deployment renumbered to §10.
> (3) DONE at DESIGN level — restart/resume is now its own section,
> `DESIGN.md` §11 ("Resuming an interrupted run"): within-run continuation
> of the PULL only (v1), checkpoint = matched pair (saved engine state +
> progress ledger) keyed to the engine step, resume chosen by the pair's
> presence, input-hash mismatch WARNS AND STOPS unless overridden, §5.6
> gate unchanged; §10.6/§10.7 repointed at §11. PSEUDOCODE DONE
> (2026-07-27) as `PSEUDOCODE.md` §13 — a dedicated section mirroring
> DESIGN §11 1:1, with the pull's §9.5 its only v1 caller; CODE is the
> remaining follow-on, tracked in `dev/TODO.md`. Nothing is coded yet.

This is gap **G3** (deployment). It is a *clean build*, not a cleanup:
the deliverable package `src/sabsim/` is free of baked-in site details
(a source-wide check found only comments and launcher-detection env
vars). The only place partition/account/paths are hardcoded is the
acknowledged **throwaway** scripts under `jobs/*` — those are field
notes, not the product, and they already enumerate exactly what a real
submission needs (partition, account, task count, walltime,
`LAMMPS_POTENTIALS`, the venv python, the mpirun path, `PYTHONPATH`,
`SABSIM_SCRATCH`, and the `mpirun -np N python -m sabsim run` line).

## What is already settled ABOVE this (do not relitigate)

- **ARCHITECTURE §4.1** fixes the policy: three tiers (thin sequencer /
  opaque ALF+Kaleidoscope Parsl / direct jobs); the deployment config is
  one machine-local TOML with a `[hardware]` inventory (per-cluster swap
  unit) and a `[usage.*]` map keyed by KIND OF JOB, joined by the word
  **class**; Tier B is excluded (the config POINTS AT ALF/Kaleidoscope's
  own Parsl+SLURM, never duplicates it); the three roots
  (`SABSIM_SCRATCH`/`SABSIM_SHARE`/`SABSIM_LOCAL`) are set by a sourced
  shell rc UPSTREAM of Python and the TOML is found THROUGH them.
- **The template exists:** `dev/templates/deployment_rc.toml` (complete).
- **DESIGN §1.2 / §1.4** constrain us: the study spec is forbidden to
  express deployment at all; the deployment file is deployment-ONLY (no
  scientific/numerical default may hide in it); "defaults exist only as a
  GENERATOR that emits a complete file," never a silent load-time
  fallback.
- **The one real gap:** the designed, templated config has NO consumer.
  `src/sabsim/deploy/` holds only `scratch.py` (the mirror tree); nothing
  reads `deployment_rc.toml`.

## Decisions LOCKED this session

1. **The consumer is a WRITER** (Q1). `sabsim` reads the study + the
   deployment config and WRITES ready-to-submit scripts; a human does the
   final submit. Not a submitter (a long-lived submit-and-watch process
   can't sit on a login node — ARCH §4.1 wall 4) and not schema-only.
   Rationale: the throwaway scripts already ARE the hand-written
   template, so teaching `sabsim` to emit that template with the
   site-specifics filled in is the natural next step, and it stays
   hand-run. This is the §1.4 "generator" pattern lifted to deployment.

2. **One member becomes THREE submitted jobs** (Q2), split by kind of
   work, which the user submits IN ORDER, watching each to completion and
   checking correctness before the next:
   - **activate** (ordinary/CPU): build both wafers, roughen both
     surfaces (the classical + ZBL cascade), bring them together. Named
     for its heavy, gating work; the cheap build+assemble glue rides
     along. The checkpoint the human inspects before continuing is the
     ACTIVATION GATE — a hardware-kind boundary that is ALSO a decision
     boundary. (The throwaway `jobs/si_si_e2e/slurm_back` already cut at
     roughly this seam and validated it.)
   - **bond** (GPU): press, settle, pull.
   - **analyze** (ordinary/CPU): measure. Split off as its OWN job (user's
     call) because the all-electron analysis will eventually be heavy;
     splitting now avoids a later boundary rewrite. A three-script shape,
     not two-with-analysis-folded.

3. **CLI shape** (Q3):
   - `sabsim prepare <spec>` — the WRITER. It is the "joining object":
     the one command that reads BOTH the study spec (which members, what
     each needs) AND the deployment config (hardware per kind), and writes
     N members x 3 jobs of scripts. The study spec still never mentions
     the cluster; `prepare` joins them at write time.
   - `sabsim run <spec> --activate | --bond | --analyze` — runs ONE job;
     this line lives inside each generated script. Add `--only <member>`
     to narrow to one member. The three are MUTUALLY EXCLUSIVE flags
     ("at most one"); NO flag given = run the whole chain (keeps the
     login-node `--dry-run` whole-chain check). Chosen over a valued
     option because dropping the noun "stage" means the flags need no
     category word at all.
   - **Names: activate / bond / analyze.** Self-documenting; match the
     pipeline's own vocabulary (§3 activation, §5 bond/debond, §6
     analyzer). The word "stage" is DROPPED (overloaded: the eight steps,
     the fine internal stages). If a coarse-unit noun is ever needed,
     "leg" or "segment" was floated — deferred, not chosen.
   - **Filenames are semantic, NO ordinals** (`activate.slurm`,
     `bond.slurm`, `analyze.slurm`). User reconsidered ordinals because
     inserting a new job BETWEEN existing ones would break the numbering.
     Order lives in ONE place — a guided index the writer drops alongside
     (a short README + each script printing "done; check X, then submit
     the next"), which serves the hand-driven checkpoint model.
   - **THE REAL SAFEGUARD:** define the set of jobs ONCE in code as a
     small ORDERED REGISTRY (`activate -> bond -> analyze`) that BOTH the
     `run` flags and the `prepare` writer read from. Then inserting a new
     job later is a one-line edit and the flags, writer, filenames, and
     index all follow. The CLI surface (flags vs option) barely matters
     because neither scatters the truth.

4. **Committee runs within ONE submit** (clarified). All committee models
   run inside the single `bond` job's MD run — the engine loads all model
   files together in one process, evaluates them on each configuration,
   and their disagreement IS the live uncertainty signal (§7.3). NO
   per-member submits. Training's committee is the adopted tool's own
   business (Tier B), also not per-member from our side. Consequence for
   Q5: committee SIZE multiplies the bond job's per-step cost, so it
   pushes on that job's walltime demand — a size matter inside one job,
   never a reason to add jobs. NOTE: not wired yet — today's pipeline uses
   a classical stand-in and reports committee spread as hardcoded 0.0, so
   this is the design target, not current behaviour.

5. **Q4 — environment setup in each generated script** (RESOLVED
   2026-07-26). "Getting ready" is three kinds of thing, sorted into
   three homes:
   - (a) **Scripts are SELF-CONTAINED.** Each generated script carries
     its own environment setup so it can be submitted into a fresh
     compute-node shell without the interactive session having been
     prepared first.
   - **The generator BAKES THE RESOLVED LOCATION VALUES inline as a
     FROZEN SNAPSHOT** — not a "source the rc" line. Chosen because it
     matches the §1.4 "emit a COMPLETE file" pattern; it is fully
     reproducible (a script names the exact locations it used); and it
     does not depend on the sabsimrc still existing/unchanged at submit
     time. Cost accepted: a changed root needs a REGENERATE to take
     effect.
   - **FAIL-FAST GATE at generation time.** The three roots are DEFINED
     in the sabsimrc (their proper home). Before writing anything, the
     generator checks they resolve; if not, it STOPS AND REPORTS on the
     login node rather than emitting scripts that would fail on a compute
     node — same spirit as the study-reference check (catch it where the
     message is readable).
   - (b) **TOOL LISTS GO PER-KIND.** The programs-to-switch-on move OUT
     of the machine-wide `[hardware]` inventory and INTO each `[usage.*]`
     block, so activate loads only the classical-dynamics engine, bond
     only the GPU force-model engine, analyze only the electronic-
     structure package. This RESHAPES `dev/templates/deployment_rc.toml`.
   - **Leftover plumbing** (potential-file path, python interpreter,
     launcher) gets NO home in the script: potentials are found through
     the shared-data root; interpreter and launcher come from the
     activated install. The script's getting-ready section stays small
     and boring.
   - **Naming.** Generated scripts (activate/bond/analyze), sabsimrc, and
     the config file all pass "clear, not generic." The CLI verb `run`
     STAYS (a common, understood command word, like `git commit`). The
     guided index the writer drops still needs a descriptive name (NOT
     `index`/`readme`) — pick it when the writer is built.

## RESOLVED — Q5 (walltime)

6. **Q5 — walltime** (RESOLVED 2026-07-26). The writer does NOT predict
   simulation time. The requested walltime is a PERSON-PROVIDED value in
   the per-kind `[usage.*]` block, refined with experience; §5.6's
   pull-distance / pull-rate formula stays as the human's ESTIMATION
   GUIDE, not something the code computes (this REFRAMED §5.6 and the
   §5.9 "Replace" clause). ONE cheap check added: `prepare` compares the
   requested walltime to the partition's `max_walltime` ceiling (both
   already in the file — predicts nothing) and STOPS+reports if it
   exceeds, symmetric with the roots gate. Overrun is handled by HUMAN
   CONTINUATION (not auto-shorten, not writer auto-split); the §5.6
   completeness gate makes that safe. The continuation mechanism itself
   is the restart/resume follow-on (G5) — §11.6 relies on it, does not
   define it. Written as `DESIGN.md` §11.6.

## Placement finding — RESOLVED by /refine (2026-07-26): deployment is §10

The section first landed at §11 on the belief that DESIGN §10 was
RESERVED — bare intra-doc refs from §3.5/§4.7/§9.3 (§10.2, §10.7, §10.8)
seemed to point at an unwritten surface-activation cascade driver, and a
placeholder stub was parked at §10 to hold the numbering.

The `/refine` overturned that belief. Every one of those bare refs
resolves cleanly into `PSEUDOCODE.md` §10 (activation ALGORITHMS), and
one is decisive: `DESIGN.md` §9.3 says "§10.7's `label_activated_skin`",
a function DEFINED in `PSEUDOCODE.md` §10.7. Likewise §10.2 =
`open_cascade_driver` and §10.8 = the STRUCTURAL-4 ensemble note. So they
were CROSS-refs missing the filename prefix, never a reservation —
`PSEUDOCODE.md` §10 is the counterpart to DESIGN **§3**, not to a DESIGN
§10, whose cascade-driver material already lives in §3.3 + §4.7.

Resolution: the six refs were prefixed with `PSEUDOCODE.md`; the §10 stub
was deleted; deployment was renumbered §11 -> §10 (headers §10.1-§10.7,
internal §10.5/§10.6 refs, the §5.6/§5.9 forward refs, `ARCHITECTURE.md`
§4.3's `DESIGN.md` §10.2 ref, and the template's §10.5 ref all updated).
No numbering gap remains; §9 -> §10 flows.

## Level flags (do not leave inconsistent)

- The "one member = three submitted jobs" decision REVISES the execution
  model, which lives in **ARCHITECTURE §4.3** ("file-handoff stages,
  serial slabs" — today it describes ONE job running the whole member
  chain). §4.3 was written to ALLOW the split (every stage hands off
  through a file), but it must be updated to say a member executes as
  three per-kind jobs. Land this when the section is written.
- The **DESIGN deployment section does not exist yet.** ARCHITECTURE §4.1
  has the policy; DESIGN must add the CONSUMER mechanism (the `prepare`
  writer, the `run --activate/--bond/--analyze` selector, the ordered job
  registry, how the config is read, how Q4/Q5 resolve). Write it once Q4
  and Q5 are settled.
- Decision (b) in Q4 RESHAPES `dev/templates/deployment_rc.toml` (tool
  list migrates from `[hardware]` to `[usage.*]`).

## Related open TODO items this connects to

- ARCH-level "what to run vs where to run" deployment item (TODO, the
  `[hardware]`+`[usage.*]` structure + the rc mechanism). Its FOLLOW-ON
  (the installer + INSTALL/README that emit the rc) is still unwritten.
- "Run ONE Si/Si member end to end" step (3): the real-vs-stub stage
  selector. The `run --activate/--bond/--analyze` selector is the clean
  form of the one-off `rerun_back_half.py`.
