# The SABSIM workflow as it stands — commands, potentials, gaps

**Written 2026-08-25** by reading the code, not from memory. Every claim
below cites the file that makes it true. Where the chain is silent or a
stage is a stub, this note says so rather than describing the intent as
though it were the implementation.

Two things make this note worth keeping current. The command surface is
small — two verbs — so a reader who knows those two knows the whole
front door. And the question that is genuinely hard to answer from the
code is not "what runs" but "**under which potential**", because two
different models do the work at different stages for reasons that are
deliberate and easy to get backwards.

---

## The two potentials, and why there are two

| | **DPA universal** | **Bespoke DeePMD** |
|---|---|---|
| What | DPA-3.1-3M foundation model, whole periodic table | committee trained by ALF on VASP labels |
| Role | **scaffold-grade generator** | **production model** |
| Named by | `UNIVERSAL_CASCADE_MODEL`, `SABSIM_CASCADE_MLIP_MODEL` | `potential_ref`, `SABSIM_DEEPMD_MODEL` |
| Status | `validated=False`; passes Tier-0 on Si | **does not exist yet** |

The split exists to break a circularity, STRUCTURAL 1b: the
configurations the production model must be trained on are exactly the
ones only a model can visit. `DESIGN.md` §4.5 resolves it by generating
those configurations with a *cheaper generator* than the production
model — and since the 2026-08-21 decision that generator is the
universal MLIP, which retired the separate seed committee.

The universal model is never trusted for physics. It is spliced with two
ZBL cores for the cascade (`DESIGN.md` §3.3, §4.7) because a foundation
model is out-of-distribution deep in the repulsive regime a keV impact
visits, and it is treated as scaffold-grade throughout: good enough to
land a surface in a reasonable amorphous basin, not good enough to
measure anything.

### Why DPA-3.1-3M and not DPA-2.4-7M

Adopted 2026-08-25, and the reason is physics, not performance. The
**Tier-0 inherent-structure screen** minimizes a pristine crystal and a
damaged configuration under a candidate model and requires the crystal
to come out LOWER. On silicon:

| model | lattice a | damaged − pristine | verdict |
|---|---|---|---|
| DPA-2.4-7M | 5.3473 Å (−1.54%) | −0.378 eV/atom | **FAIL** |
| DPA-3.1-3M | 5.5147 Å (+1.54%) | +0.361 eV/atom | **PASS** |

(LEDGER T-21, job 16731025.) Under a model with the ordering inverted a
silicon surface has a thermodynamic incentive to destroy itself, and an
activation run self-heats instead of amorphizing. The failure is in the
ENERGY ORDERING, so no amount of force accuracy would have caught it —
worth remembering when `TrainingSpec` balances energy against force
weight, since a configuration carries 3N forces against a single energy
and an unweighted loss is force-dominated by sheer count.

The earlier preference for DPA-2.4-7M was an engineering one: it
exported cleanly to AOTInductor `.pt2` while DPA-3.1-3M hit an
unbacked-symint export failure. That reason no longer binds — LAMMPS
loads the PyTorch `.pth` directly, energy conserved (4e-6 drift over 100
NVE steps), and a `.pth` is PORTABLE where a `.pt2` is
architecture-locked, which unpins the cascade from any one GPU type. The
~2.5x per-step speed of an AOT build is the only thing given up.

**Tier-0 is per material AND per model.** Passing on silicon licenses
nothing about the oxides, and no oxide has been screened.

---

## Before any command: three files

| File | Role | Template |
|---|---|---|
| `.sabsim/sabsimrc` | sourced UPSTREAM of Python — three roots + env | none; hand-written, gitignored |
| `sabsim.toml` | the study: materials, protocol, numerics | `dev/templates/study_spec.toml` |
| `deployment.toml` | the machine: partitions, walltimes, modules | `dev/templates/deployment_rc.toml` |

The run's home IS the current directory (`cli.py`, `os.getcwd()`). You
make a job directory, `cd` into it, and put the two TOMLs there. Nothing
is guessed from a path — `VISION.md` principle 1.

---

## Phase A — the bootstrap

**No code exists for any of this.** `potential_ref` reads
`"PENDING-BOOTSTRAP"`, `LIVE_STAGES` binds `resolve_potential` to the
skeleton stub that returns a classical stand-in regardless of what the
member asked for, and `spec/references.py` states plainly that
`potential_ref` is deliberately unchecked "because the bootstrap that
produces one is not built, so there is no store to resolve it against."

`GenerationPlan` (`PSEUDOCODE.md` §11) names the models:

```
cascade_model:  the §4.7 foundation MLIP + ZBL (classical + ZBL fallback)
protocol_model: the SAME foundation MLIP for the press and pull.
                NOT a committee: generating the hard configs with the
                model those configs are meant to train is the
                circularity STRUCTURAL 1b exists to break.
```

**Collection 1** (`DESIGN.md` §4.8 part 2) — the calm structures, six
families, all required:

| # | Family | Generated under |
|---|---|---|
| 1 | Bulk ground state | static → VASP |
| 2 | Bulk strained, past the reversible range | static → VASP |
| 3 | Bulk melt-quench amorphous | MD — **model unnamed** |
| 4 | Clean surfaces, unbombarded | static → VASP |
| 5 | Rattled snapshots | static → VASP |
| 6 | Warm runs, NVT *and* NPT | MD — **model unnamed** |

**Collection 2** (§4.8 part 5) — harvested from a bootstrap protocol
run, five families, all required:

| # | Family | Generated under |
|---|---|---|
| 7 | Amorphized surface | **DPA + ZBL** (`cascade_model`) |
| 8 | Initial joint cell, wide gap, unrelaxed | **DPA** (`protocol_model`) |
| 9 | Relaxed joint cell — contact, unloaded | **DPA** |
| 10 | Pressed cell | **DPA** |
| 11 | Pulled cell, through failure | **DPA** |

Then VASP labels a selected subset — Collection 1 as whole cells,
Collection 2 as the **§6.4 interface subcells**, because a production
cascade cell runs ~1960 atoms against a routine DFT budget of a few
hundred (LEDGER T-21). ALF folds the labels into the HDF5 store and
trains the committee; the sampler then re-runs the protocol under that
committee, flags high-σ configurations, relabels, and retrains.

Output: a generation identifier a member's `potential_ref` resolves
against.

---

## Phase B — the production run

```bash
sabsim run --dry-run
```
Runs all eight stages with `W0_STAGES` on the login node: validates the
spec, runs the phase-three reference check (every CIF and material
domain resolves), exercises the full control flow through the same
contracts a real run uses. No LAMMPS, no physics, no potential.

This is the only `run` mode allowed off an allocation.
`_refuse_live_off_allocation` requires a launcher rank variable
(`SLURM_PROCID`, `OMPI_COMM_WORLD_RANK`, `PMI_RANK`, `PMIX_RANK`) —
deliberately NOT `SLURM_JOB_ID`, which is set in an `salloc` shell that
still sits on the login node.

```bash
sabsim prepare
```
Reads BOTH inputs and writes one `.slurm` per (member × job) plus
`SUBMISSION_GUIDE.md`. **Submits nothing.** Gates first — the three
roots resolve, every walltime is under its partition ceiling, every GPU
request is under `gpus_per_node` — so a misconfiguration fails on the
login node rather than an hour into a compute job. Each script carries
`unset SLURM_MEM_PER_*` then `srun --mpi=pmix`.

### activate (GPU) — `reads = FROM_SPEC`, `writes = assembled_pair`

| Stage | Potential |
|---|---|
| `resolve_potential` | **classical stand-in** (stub) |
| `derive_lattices` (§2.2) | **DPA**, out-of-process |
| `build` | geometry only |
| `activate` (cascade) | **DPA + ZBL**, out-of-process on GPU |
| `assemble` | geometry only |

The §2.2 bulk relax runs under *the same universal MLIP the cascade then
bombards under*, so the working lattice and the amorphizing potential
agree — which is why the CIF's published lattice scale is never used.
Getting this wrong is not academic: T-18's oxide press detonated because
the pair was built on CIF lattices, ~24 GPa at frame 0, and 93% of the
atoms were ejected.

`SABSIM_CASCADE_CLASSICAL` opts into a classical+ZBL cascade in-process
on CPU instead.

### bond (GPU) — `reads = assembled_pair`, `writes = pull_results`

Heal at the wide gap, per-wafer §3.5 gate, scissor the vacuum, press to
contact, settle, pull through the rate ladder. All of it under
`_bonded_force_model`: the **bespoke DeePMD** model when
`SABSIM_DEEPMD_MODEL` names a frozen one, otherwise the **classical
stand-in**. A named-but-missing model is a loud stop, never a silent
fall-through to the stand-in — that would quietly run a different
experiment than the one requested.

Note the asymmetry: in the BOOTSTRAP the press and pull run on DPA; in
PRODUCTION they run on the bespoke committee. Same stages, different
model, by design.

### analyze (CPU) — `reads = pull_results`, `writes = measure_vector`

No force model. Reduces the pull curves to the measure vector; M1, the
mechanical work of separation, is the real measure. `characterize` is
mocked and returns `unresolved`.

### Whole chain in one allocation

```bash
srun --mpi=pmix -n 4 python -m sabsim run
```
All eight stages per member AND the declared relations — the ratio of
Si/SiO₂ to Si/Si work of separation. The per-job path never grades
relations; only the whole-chain path does.

---

## Gaps

| # | Gap | Where |
|---|---|---|
| 1 | No bootstrap code at all | nothing in `src/` |
| 2 | `resolve_potential` is the skeleton stub in `LIVE_STAGES` | `live_stages.py:1260` |
| 3 | Collection 1's dynamics families name no model | `QuenchSpec`, `WarmRunSpec` |
| 4 | `_reanneal_force_model` has no callers | `live_stages.py:677` |
| 5 | DPA-3.1-3M `validated=False`; no oxide screened | `cascade_potential.py` |
| 6 | `run_characterization` mocked | `skeleton_stages.py:267` |
| 7 | Gate references are `real = false` stand-ins | `share/activation/*.toml` |
| 8 | Press phase has no atom-conservation coverage | T-18 CORRECTION |
| 9 | No `--resume` / `--refresh` CLI flags | `cli.py` docstring |

Gaps 3 and 4 are logged in `TODO.md` under PSEUDOCODE and CODE.

Two deserve weighting above the rest. **Gap 1** means every run today is
a plumbing exercise: the physics is a classical stand-in, so the
pipeline is validated but no number it produces is the number wanted.
**Gap 8** is the one that actively lies — it reported
`atoms_conserved=True` on a cell that had lost 93% of its atoms, because
the conservation baseline is captured at PULL start rather than press
start. That is the origin of the standing rule to judge every run from
the trajectory, never from log fields or exit codes.

What is NOT a gap, and is worth saying: the eight-stage chain, the
three-job split, the file handoffs between jobs, the contract guards,
the login-node gates, and the deployment writer are all built and
exercised. The skeleton is complete; two of eight stage bodies are
stubs.
