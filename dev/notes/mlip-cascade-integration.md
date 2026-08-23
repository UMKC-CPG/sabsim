# MLIP integration — universal cascade + bespoke bond-debond (working note)

Working note, 2026-08-07. Tracks the effort to close the "runs on real
physics" gap (TODO L1788): wire a universal foundation MLIP for the
CASCADE and the bespoke DeePMD for the BOND-DEBOND. NOT canonical yet.

## RESUME HERE (2026-08-23) — DPA-2.4-7M FAILS THE PHYSICS; USE DPA-3.1

**Read this before the 2026-08-09 block below, which it supersedes on the
model choice.** Full evidence: `install/tests/LEDGER.md` T-21.

**DPA-2.4-7M does NOT hold diamond silicon as the stable phase.** Minimize
the pristine slab and a bombardment-damaged slab under deepmd alone, same
box and surfaces: pristine `-6.461513` eV/atom, damaged `-6.882385` — the
DAMAGED structure is **0.421 eV/atom LOWER**. So a cascade nucleates a
transformation that then runs downhill on its own: the slab converts to a
dense ~5.75-coordinated phase (from 3.80), densifies 11.5%, contracts 10%,
and releases 0.199 eV/atom as heat — which is what drove the observed
`132 -> 1729 K` temperature ratchet, NOT the 4 x 75 eV of projectile
energy. Consequence: **amorphization depth is set by a propagating phase
front, not by the ion range, so it cannot be tuned by energy, dose, or
thermostat.** The old "PRODUCTION MODEL = DPA-2.4-7M" line further down
is WRONG for silicon cascades.

Ruled out along the way: pre-strain (the slab was built exactly on the
§2.2 DPA lattice, measured NN 2.3155 Å → a = 5.3475 Å, zero strain); the
ZBL overlay (null runs with and without it behave identically); and
spontaneous instability (the unbombarded slab stays tetrahedral and
EXPANDS — it is metastable, the impact is what nucleates).

**TIER-0 SCREEN — run this before trusting ANY model.** Minimize a
pristine crystal and a damaged configuration under the candidate; require
`E(crystal) < E(damaged)`. Minutes per model, and it is a hard gate.
Script: `$CPG_SHARE/share/models/tier0_screen/tier0_screen.py`.

| model | lattice a | damaged − pristine | verdict |
|---|---|---|---|
| DPA-2.4-7M | 5.3473 Å (−1.54%) | −0.378 eV/atom | **FAIL** |
| DPA-3.1-3M | 5.5147 Å (+1.54%) | +0.361 eV/atom | **PASS** |

**DPA-3.1-3M IS USABLE TODAY — no `.pt2`, no patch.** `lmp` loads the
PyTorch `.pth` DIRECTLY (`pair_style deepmd .../dpa3.pth`), energy
conserved (4e-6 drift over 100 NVE steps), and `.pth` is NOT
architecture-locked, so it runs on V100/A100/H100 alike. Only the
AOT-compiled `.pt2` is arch-specific.

### The `network.py` `u0` bug — DIAGNOSED, patch NOT applied

Applying it is DEFERRED (2026-08-23, Paul): `.pth` already works, so this
buys SPEED only — but a lot of it. Measured on 4096 atoms: `.pt2` AOT on
A100 **0.1879 s/step** vs `.pth` eager on A100 0.4636 — **AOT is 2.47x
faster on the same hardware**. For DPA-3.1 that is ~0.88 → ~0.36 s/step.

The `dpa3.dp -> .pt2` export fails identically on V100 and A100, so the
bug is SOURCE-LEVEL, not architectural. THREE copies of one pattern:

| file | line | expression |
|---|---|---|
| `deepmd/dpmodel/utils/network.py` | 1343 | `int(xp.sum(...))` |
| `deepmd/pt/model/network/utils.py` | 92 | `n_edge = nlist_mask.sum().item()` |
| `deepmd/pd/model/network/utils.py` | 92 | same (paddle — ignore) |

`int(...)` / `.item()` force a DATA-DEPENDENT value (the edge count
depends on mask VALUES, not shapes) to a Python int, so `torch.export`
carries it as unbacked symint `u0` and refuses to specialize
(`GuardOnDataDependentSymNode`). Dynamo capture flags do NOT help.

`n_edge` has exactly ONE consumer in each file (`network.py:1375`,
`utils.py:120`):

```python
edge_id    = arange(0, n_edge)
edge_index = zeros([nf, nloc, nnei])
edge_index[nlist_mask] = edge_id
```

**FIX — mask rank by cumulative sum, which is shape-static.** Delete the
`n_edge` line and replace those three lines:

```python
# dpmodel/utils/network.py
flat_mask = xp.reshape(xp.astype(nlist_mask, nlist.dtype), (-1,))
edge_index = xp.reshape(
    (xp.cumulative_sum(flat_mask, axis=0) - 1) * flat_mask,
    (nf, nloc, nnei))

# pt/model/network/utils.py
flat_mask = nlist_mask.to(nlist.dtype).reshape(-1)
edge_index = ((torch.cumsum(flat_mask, 0) - 1)
              * flat_mask).reshape(nf, nloc, nnei)
```

EQUIVALENT because at the k-th `True` in row-major order the cumulative
sum is k+1, so minus 1 gives k — exactly what a boolean scatter of
`arange(n_edge)` assigns; multiplying by the mask restores 0 at `False`
positions, matching the `zeros` init. Same tensor, no symint forced.

**ATTEMPTED 2026-08-23 — three sites patched and PROVEN equivalent,
then blocked INSIDE PYTORCH.** Work kept at
`$CPG_SHARE/share/models/dpa3_patch/` (`patched/deepmd` = the shadow
package, `tools/` = the probes, `patch_test.slurm` = the gated job).
The shared bundle was NEVER written to: `BUNDLE_BASELINE.md5` records
its checksums and the job re-verifies them on entry and exit (still
`OK`). Undo = `rm -rf .../dpa3_patch/patched`, or restore the `.orig`
files kept beside each patched file.

The blocker is NOT one line. It is the same anti-pattern in a chain,
and each fix exposed the next:

1. `dpmodel/utils/network.py:1343` -- `int(xp.sum(...))`.
   FIX: rank by cumulative sum (shape-static).
2. `pt/model/network/utils.py:92` -- `.sum().item()`.
   FIX: the same rewrite, torch-native.
3. `dpmodel/descriptor/repflows.py:1481` -- `int(xp.sum(...))`, run
   only when `use_dynamic_sel` (its own comment says "int cannot jit").
   FIX: `h2.shape[0]` -- same number, but a SHAPE, so the symbol
   becomes size-like.
4. `dpmodel/utils/network.py:1280` in `aggregate()` -- the branch
   `bin_count.shape[0] != num_owner`, which pads to length.
   FIX: `xp_bincount(..., minlength=num_owner)`, removing the branch;
   the tail zeros it adds are turned into ones by the existing
   `where`, which is exactly what the old padding wrote.

Each round moved the error forward, which is how we know the fixes
land: `u0` (not size-like) -> `u5` **size-like** -> `Ne(u5, 14)` branch
guard -> and finally:

```
Eq(u4, 1)  (Size-like symbols: u4)
Caused by: (autograd/graph.py:869 in _engine_run_backward)
```

**That last one is inside PyTorch's autograd engine, not deepmd** -- a
broadcast guard on an unbacked symbolic size while building the
BACKWARD graph. Fixing it means patching torch itself or restructuring
deepmd so no unbacked size reaches a backward pass. That is a different
and much larger job, so the attempt STOPS here (Paul, 2026-08-23).

**The physics was verified at every round, and the verification itself
had to be fixed first.** The first equivalence run was INVALID: both
runs loaded the patched package, because `python $W/eval_model.py` puts
`$W` on `sys.path[0]` and `$W` held `deepmd/`. The agreement it showed
was GPU run-to-run noise. Now the package lives in `patched/`, the
probes in `tools/`, and the job asserts the two runs loaded DIFFERENT
`deepmd.__file__` paths before the gate can even be reached. With that
in place: stock `-344.3080332279` vs patched `-344.3080327511` eV, max
force difference `5.5e-07` eV/A (3.7e-07 relative) -- **EQUIVALENCE
PASS**, i.e. the rewrite is physics-neutral, and the residual matches
the patched-vs-patched noise floor.

**If this is ever resumed:** the three deepmd fixes are done and
verified -- start from site 4. Worth trying first, cheapest to
hardest: a newer deepmd/torch (this is a 3.2.0b0 BETA on torch 2.11);
the `guard_or_false` / `statically_known_true` APIs the error message
itself recommends; or exporting with the backward graph disabled if
inference-only export is possible.

**Steps when it is done:** (1) shadow-copy ONLY the 25 MB `deepmd`
package (`cp -a $PREFIX/lib/python3.12/site-packages/deepmd
$WORK/patched/`) — NOT the 17 GB prefix; the 6 `.so` files under
`deepmd/lib/` come along verbatim. (2) Edit both files, keep `.orig`.
(3) `PYTHONPATH=$WORK/patched` on the EXPORT process ONLY — the
isolation wrapper deliberately unsets PYTHONPATH, and the lmp runtime
must never see it. (4) Assert `deepmd.__file__` is under `$WORK/patched`
or you silently export the unpatched bundle. (5) **EQUIVALENCE GATE:**
patched vs unpatched energy AND forces on one structure, agree to ~1e-6
relative, or stop — the patch must not change physics. (6) Export with
the `-lcuda` symlink + `LIBRARY_PATH` from
`share/models/a100fix/a100_export.slurm`. (7) Validate: NVE in LAMMPS,
TF32 OFF, step-0 energy matching the `.pth` run to ~1e-4 eV. (8) LEDGER
entry noting the patch is **EXPORT-TIME ONLY** — the `.pt2` is
self-contained, so production LAMMPS never loads patched Python.

**Risks:** `xp.cumulative_sum` on torch tensors via `array_api_compat` is
used elsewhere in deepmd (`dpmodel/loss/dos.py`) but unverified on this
path — fallback is patching only the `pt` copy. Patch BOTH, since which
copy the exporter touches is not guaranteed. int32 cumsum over
`nf*nloc*nnei` (~4e5) is safe; use int64 for a much larger cell. This is
a local patch to a BETA (3.2.0b0) — record it or a bundle refresh
silently reverts it.

### Hardware

`gpu` + `requeue` carry A100 (16 nodes x 4), H100 (up to 8/node), L40S,
H200 — and 49 of 64 A100s were FREE with an EMPTY pending queue while we
queued behind 3 V100s. Pin V100 ONLY when using the V100 `.pt2`. A fresh
A100 `.pt2` for DPA-2.4 exists at
`$CPG_SHARE/share/models/a100fix/dpa24_a100.pt2` (physics FAILS Tier-0,
kept only as the export-path control). PHYSICS CAVEAT on newer hardware:
Ampere+ defaults to TF32 matmul (10 mantissa bits vs 23), so set
`torch.backends.cuda.matmul.allow_tf32 = False` for anything numerical
and re-run the NVE conservation check before trusting a new GPU type.

## RESUME HERE (2026-08-09 EVENING — OVERNIGHT FLEET, read FIRST)

Four V100 activations launched Sun 2026-08-09 ~21:30; all finish before the
Tue 08:00 maintenance window (reservation `Aug_Maint`, all nodes). Branch
`universal-mlip-cascade` is **9 commits ahead of main, NOT pushed** (Paul
pushes own). Every harness is committed under `install/tests/`. Logs +
artifacts in `$CPG_SHARE/share/models/dpa_gpu_bench/`.

**THE JOBS** (check `sacct -j <id> --format=State,Elapsed`; `.out` files):
- **T-10  16324481** (gpu g027) — Si 6x6x10 full-fluence activation, gate
  DIRECTLY. Out: `t10-activate-gate-16324481.out` → look for
  `T10 GATE PASSED|FAILED`. Surface: `t10_val/activated.extxyz`.
- **T-10b 16345032** (requeue g021) — 2nd Si realization, seed 20260810 →
  `t10b_val/`. A genuine A!=B pair with T-10 (preemptible; may restart).
- **T-12 SiO2   16344824** (gpu) — amorphous SiO2 surface + movie →
  `t12_val/sio2_activated.extxyz` + `sio2_movie.dump`.
- **T-12 LiNbO3 16344825** (gpu) — amorphous LiNbO3 surface + movie →
  `t12_val/linbo3_activated.extxyz` + `linbo3_movie.dump`.

**T-11 ALREADY QUEUED:** `16345420` submitted `--dependency=afterok:
16324481` — it fires CLUSTER-SIDE when T-10 finishes (no session needed),
on the `t10_val` surface MIRRORED. It fires REGARDLESS of the gate result
(SLURM only sees T-10 exit 0): if T-10 activated well → a real Si
work-of-separation + press/pull movie in `t11_val/`; if under-activated →
T-11's own heal+gate halts harmlessly. Check `t11-bond-debond-16345420.out`.

**NEXT WHEN THEY FINISH:**
1. **Si (h):** read `t10-activate-gate-16324481.out` gate verdict. If
   PASSED → (a) flip `UNIVERSAL_CASCADE_MODEL.validated` False→True in
   `cascade_potential.py`; (b) append ledger T-10 + T-11 (from
   16345420's out). If FAILED → read the failing metric; more
   fluence/impacts and/or tune `share/activation/Si.toml`; re-run T-10.
   For a TRUE A!=B pair, edit t11 to load `t10_val` (A) + `t10b_val` (B)
   and re-run.
2. **Oxides — assemble + bond (the real target):** the two amorphized
   halves are COMMENSURATE (2.03% strain, shared cell, global
   `{Ar,Li,Nb,O,Si}` map; SiO2=wafer A, LiNbO3=wafer B). Assemble with
   `assemble_amorphized_pair` (both already tagged) → bond-debond under
   **Prakash's SiO2+LiNbO3 model**: `SABSIM_DEEPMD_MODEL=$CPG_SHARE/share/
   training_deepmd_sio2_linbo3/model.pb` (type_map [Si,Li,Nb,O], rcut 6),
   in-process deepmd — a T-11-style harness on the oxide surfaces (T-13,
   to build).
   **BLOCKER TO RESOLVE FIRST (§3.5 gate):** `press_and_bond` gates each
   healed surface post-heal and HALTS on fail; there is NO oxide reference
   (Si-only), and the gate keys on `frozenset(built.type_map)` = the GLOBAL
   `{Ar,Li,Nb,O,Si}` set (same for BOTH wafers — it can't tell SiO2 from
   LiNbO3). So the oxide bond needs EITHER (a) per-material references +
   a per-wafer species key (a gate design change for heterogeneous
   interfaces), OR (b) a gate-optional bond path for oxides. Decide with
   Paul before T-13.
3. **Movies:** `t12_val/{sio2,linbo3}_movie.dump`, `t10_val/
   cascade_movie.dump`, `t10b_val/cascade_movie.dump` — OVITO/VMD.

**WATCHERS:** two session background pollers were set (T-10 → auto-flip +
ledger + auto-fire T-11 on PASS; T-12 both → report). If the session
persisted they act/report automatically; if it ended, do the above by hand.
The build tool for the oxide pair is `install/tests/t12_oxide_pair/
build_matched_halves.py` (re-run to rebuild the matched halves).

## FINDING 2026-08-10 — universal cascade makes QUENCHED-MELT Si, not a-Si

The universal DPA-2.4-7M cascade, run CASCADE-ONLY, produces a dense
LIQUID-LIKE Si, not tetrahedral a-Si — so every Si activation FAILS the
§3.5 coordination gate and the bond crashes. **The anneal fix below is a
CANDIDATE to DISCUSS with Paul, NOT a decision.**

EVIDENCE (all COMPLETED, all gate-FAILED on coordination ~0.92 vs the
[0.05, 0.60] band): T-10 `16324481` (6x6x10, 75 eV), Si bracket
`16365791` (4x4x8, 25 eV) + `16365792` (40 eV).
- The region that should be crystalline BULK (the gate's deep-third
  self-reference) has a SMEARED neighbour distribution — continuous
  density 2.3–3.4 Å, NO tetrahedral first shell + gap. Coordination
  reaches 4 only at a 2.7 Å cutoff and climbs to 6.7 @2.9, 8.8 @3.2
  (crystalline/tetrahedral Si = 4 out to ~2.6 Å, then nothing to 3.84).
- nn distances are NORMAL (median ~2.36 Å) and density ~crystalline, so it
  is NOT crushed/overlapping — it is a dense, ~6-coordinated LIQUID-Si-like
  network (liquid Si is denser AND higher-coordinated than crystalline).
- ENERGY DOES NOT FIX IT: 25 eV is as bad as 75 eV. So it was never an
  over-DOSE problem; it is the melt QUENCH.
- The surface is far out-of-distribution for graph.pb: the Si bond T-11
  `16345420` collapsed (111 neighbours/atom) + shed atoms; the demo bond
  `16365808` (gate bypassed, lost-atoms tolerated) same — no usable movie.

DIAGNOSIS: the cascade MELTS the Si; cascade-only (no anneal) freezes the
melt disordered instead of relaxing it into the 4-coordinated tetrahedral
network. The re-arch (§3.4) moved annealing into the bond-flow HEAL, and
that heal is far too short to anneal a quenched melt.

CANDIDATE FIX — DISCUSS FIRST: a proper post-melt ANNEAL under the
universal model (hold at moderate T so the liquid relaxes to tetrahedral
a-Si, then cool) BEFORE gating/bonding. This REOPENS the re-arch decision
that removed the per-slab re-anneal — the heal may need to BE a real
anneal, or the cascade may need its own. Open questions for Paul: anneal
T / duration / cool-rate; where it lives (activate vs bond flow); and
whether the gate's `bond_cutoff` (2.9 Å, `share/activation/Si.toml`) also
needs revisiting, since a dense-melt g(r) first-minimum sits past 2.9 Å.
NOTE: SiO2 amorphized CLEANLY (1:2, 6 atoms lost) — the melt-quench issue
may be Si-specific (Si's anomalous dense liquid); LiNbO3 over-sputtered
instead. Check each oxide's g(r)/coordination when an oxide gate exists.

## RESUME HERE (2026-08-08, LATEST — read this first)

**★ (g) DONE — T-9 NODE-VALIDATED 2026-08-09 (jobs 16306379 + 16306381).**
The re-architected split runs end-to-end on a V100: cascade-ONLY universal
activate (DPA-2.4-7M `.pt2` subprocess) hands back a SUBSTRATE-ONLY half
(128 Si, Ar stripped) ×2 → assemble at a 7.606 Å WIDE gap → bond flow
HEALS under a COMMITTEE OF ONE (Prakash Si `graph.pb`, in-process
`cpg_lammps_conda/2024.08.29-deepmd`) → GATES each surface PER WAFER TAG →
HALTS on the failed gate before scissor/press (halt-on-fail seam works).
Committed reproducible harness: `install/tests/t9_universal_split/`
(2 py + 2 slurm + submit.sh + README, self-logging); LEDGER entry **T-9**.
PLUMBING PASS; the gate did NOT pass (radial_distribution 0.475/0.725 vs
0.3 — a 128-atom/1-impact/short-heal surface is under-activated; the 0.3
`share/activation/Si.toml` ref is a stand-in). **NEXT = (h):** get a first
gate-PASSING activation (more impacts/fluence and/or tune the RDF ref) →
flip DPA-2.4-7M `validated=True` and drop `SABSIM_ALLOW_UNVALIDATED_
POTENTIAL`. Follow-on: the `sabsim prepare` deployment path for the
GPU-universal activate (E5 only covered classical). All UNCOMMITTED before
this session's T-9 commit (Paul pushes own).

**★ SESSION HANDOFF 2026-08-09 — CODE phase steps (a)+(b) DONE + GREEN
(333 tests); NEXT = bond-flow heal+gate (d) + wide gap (c).**
DONE this session: DESIGN+PSEUDOCODE re-arch + /refine (all consistent), then
CODE (a) CASCADE-ONLY: `build_activate_script`/`activate_surface` drop the
re-anneal+gate; new `cascade_cleanup_commands` (teardown+strip-projectile+
reset ids) — the strip STAYS as cascade cleanup so the handoff is
substrate-only (DESIGN §3.4 corrected: only the ANNEAL moved, not the
strip); `activate_surface` now returns `CascadeOutcome`. (b) DROPPED
VERDICTS from the activate seam: `ActivatedSlabs` (2 slabs, no verdicts),
`_validate_activated` (checks slabs present), `activation_adapter.
activated_slabs_from_results(slab_a,slab_b)`, skeleton stub, `activate_
surfaces`, live_stages (`activate_one_half`/`_activate_one_half_subprocess`/
`activate_surfaces_live` all cascade-only, return CascadeOutcome), sequencer
comments. KEPT for step (d): `reanneal_commands`, `mlip_reanneal`,
`gate_activated_structure`, `verdict_from_activation`, `_reanneal_force_model`
(all currently unused, awaiting the bond-flow heal+gate). Tests updated
(adapter, cascade_driver, member_jobs). (c) DONE: template `initial_gap`
3→10 Å (> the bond flow's 6 Å `separation_cutoff`), so assembly places the
pair WIDE and the existing `contact_relax_commands` heal (gated on
`_assembled_gap > separation_cutoff`, press_pull.py:325) now engages as a
free-surface heal (§2.6/§3.4; 64 tests green). **(d) BOND-FLOW GATE — DONE +
GREEN.** (d1) `press_pull.gate_healed_surfaces(engine, built)`: splits the
assembled pair by wafer tag, gates each surface with `activation_gate`,
MIRRORS wafer B's z first (it was flipped face-down at assembly; the depth
metric reads the top bin as the free surface) — READ-ONLY, tested. (d2)
`activation_a/b` (ActivationVerdict|None) added to `PressResult` +
`BondDebondResult`. (d3) `press_and_bond` calls `gate_healed_surfaces` AFTER
the heal, BEFORE the scissor; a FAILED gate returns early (no scissor/press)
carrying the verdicts. (d4) `run_bond_debond_md_live` puts them on
`BondDebondResult` (both branches). (d5) `_validate_bond_debond` checks
`activation_a/b.passed` FIRST → halt-on-fail. (d6) test reconciliation:
wide-gap press tests get a `passing_gate` fixture (stubs the gate to pass —
they test scissors/relax, not the gate); narrow-gap tests don't hit it. Also
FIXED a (c) fallout (`test_press_script` approach run 300000→1000000 for the
10 Å gap). REMOVED dead `gate_activated_structure` + its imports; kept
`verdict_from_activation` as the report distiller.
NARROW-GAP `else` in press_and_bond LEFT as-is (production always wide after
(c), so it's a dead path; no raise). **REPORT FOLLOW-ON DONE:**
`run_analyzer_live` surfaces each surface's §3.5 verdict as a per-surface
`activated_depth_{a,b}` Measure (value = measured skin depth, method = gate
summary, OK/UNRESOLVED); `verdict_from_activation` REFACTORED to take an
`ActivationVerdict` directly, so dead `ActivationResult` REMOVED entirely
(cascade.py). Tests: test_activation_adapter (distiller) +
test_live_stages (2 analyzer tests: surfaced / omitted-when-absent). 334+
green. **(f) DONE:** template `[usage.activate]` FLIPPED to the GPU universal
shape — partition=gpu, nodes/tasks=1, gpus_per_node=1, mem=48G, modules=[],
`[usage.activate.environment]` = SABSIM_CASCADE_ENGINE_PREFIX + _MLIP_MODEL +
_ALLOW_UNVALIDATED (NO LAMMPS_POTENTIALS, cascade-only). Classical CPU is the
`SABSIM_CASCADE_CLASSICAL` opt-in (documented in the block). Reconciled 5
deploy tests (test_prepare + test_deploy_config) to the GPU shape. REMAINING
for the thread (deployment/validation, NOT the re-arch): (g) node-validate
the full split on GPU; (h) first gate-pass→`validated=True`.
All UNCOMMITTED (Paul pushes own).

**★ (superseded) SESSION HANDOFF — NEXT = the re-anneal/gate CODE phase.**
Where we are: (1) universal cascade ForceModel WIRED + node-validated; (2)
out-of-process activate engine (subprocess+file handoff) BUILT + node-
validated (job 16014788); (3) prepare.py per-kind `environment` env-wiring
DONE (27 tests); (4) RE-ANNEAL DECISION made (Paul): the #8 combined-cell
relax REPLACES the per-slab re-anneal, and the §3.5 gate MOVES POST-ASSEMBLY
into the bond flow; (5) **DESIGN + PSEUDOCODE fully updated for that
decision** (DESIGN §3.4/§3.5/§4.7/§10.2, ARCH §4.1, PSEUDOCODE §10.1/§10.5/
§10.6/§9.1/§7.5 + sequencer comments — chain is consistent, all ≤80). NOT
STARTED: the CODE re-architecture. Concrete code steps (TODO §4.7 item, and
the "RESOLVED 2026-08-08" block in pipeline-flow note): (a)
`cascade.build_activate_script`/`activate_surface` → CASCADE-ONLY (drop
`reanneal_commands` + `gate_activated_structure` from BOTH the universal
subprocess and classical in-process paths); (b) `ActivatedSlabs` +
`ACTIVATED_SLABS_CONTRACT` + `activation_adapter` → drop the gate verdicts;
sequencer stops gating at the activate seam; (c) `assemble_pair` → assemble
at the WIDE gap (> MLIP cutoff); (d) bond flow (`live_stages`/`press_pull`/
`run_bond_debond_md`) → add heal (the existing `contact_relax_commands`) →
`activation_gate` per wafer tag → halt-on-fail → scissor → press; move the
verdict onto the bond output; (e) update tests across both flows; (f) flip
`[usage.activate]` to GPU (now drops LAMMPS_POTENTIALS since cascade-only);
(g) node-validate the new split; (h) first gate-passing activation →
`validated=True`. Minor: `label_activated_skin` §10.7 (a-priori depth on
cascade-only, gate re-labels post-heal). All work UNCOMMITTED (Paul pushes
own). Detail of everything below.


**ACTIVATE-STAGE GPU ENGINE — DONE + NODE-VALIDATED + DOCUMENTED (job
16014788).** Full out-of-process activate path PROVEN on a V100: sabsim
built a Si slab + emitted the 58-line script, spawned the bundle `lmp` as an
isolated subprocess (universal deepmd+ZBL cascade + classical `sw` re-anneal
via LAMMPS_POTENTIALS), read the dump back (128 Si, Ar projectile deleted),
gated (4 metrics), snapshotted — exit 0. ARCH §4.4 (out-of-process cascade
engine subsection) + DESIGN §4.7 (built-state) updated; 331 tests green.
env knobs: SABSIM_CASCADE_ENGINE_PREFIX + SABSIM_CASCADE_MLIP_MODEL +
LAMMPS_POTENTIALS + SABSIM_ALLOW_UNVALIDATED_POTENTIAL. Job scripts:
`dpa_gpu_bench/subprocess_activate_{check.slurm,val.py}`.

**prepare.py ENV WIRING DONE 2026-08-08:** optional per-kind
`[usage.<kind>.environment]` map (config.py `_optional_str_map` +
UsageBlock.environment) → prepare emits sorted `export` lines; tested (27
green). Template documents the GPU-universal activate shape (not flipped —
see below). **RE-ANNEAL DECISION 2026-08-08 (Paul): the #8 combined-cell
relax REPLACES the per-slab re-anneal; the §3.5 GATE MOVES POST-ASSEMBLY**
(flow note "RESOLVED 2026-08-08"). CONSEQUENCE: the ACTIVATE stage becomes
CASCADE-ONLY (both the universal subprocess AND the classical in-process
paths) → my subprocess's classical `sw` re-anneal + LAMMPS_POTENTIALS
DISSOLVE; the current cascade+re-anneal+gate build is the working
INTERMEDIATE. That re-architecture (build_activate_script/activate_surface
drop re-anneal+gate; gate runs per-wafer-tag after the #8 relax, before the
scissor+press; ActivatedSlabs/sequencer checkpoint move; DESIGN §3.4/§3.5/
§4.1 + PSEUDOCODE) is NOT YET DONE — cross-cutting, DESIGN-first. REMAINING:
that re-architecture; then flip `[usage.activate]` to GPU (drops
LAMMPS_POTENTIALS once cascade-only); first gate-passing activation →
`validated=True`. Detail below (SUBPROCESS PATH BUILT).

New `driver/cascade_subprocess.py`
(`resolve_cascade_engine_prefix` via `SABSIM_CASCADE_ENGINE_PREFIX` in-repo
env; `run_activate_subprocess` = isolated bundle-`lmp -in`; `read_dump_
structure`). `build_activate_script` + `reanneal_commands` +
`gate_activated_structure` (cascade.py) + `amorphized_half_from_arrays`
(amorphized_assembly.py) extracted/added. `activate_one_half` now DISPATCHES:
universal→`_activate_one_half_subprocess` (out-of-process, reads the dump
back for gate+snapshot), classical→in-process (unchanged). Unit tests:
`test_cascade_subprocess.py` (dump reader + prefix resolver),
`build_activate_script` matches the live stream. LOOSE END (solved, no code):
the subprocess classical RE-ANNEAL (`sw`) needs `Si.sw` — the bundle has
none, but `LAMMPS_POTENTIALS` survives the wrapper's env reset, so the
activate job points it at a sabsim lammps potentials dir (has Si.sw). OPEN
(non-blocking) DESIGN NOTE: under the universal cascade the re-anneal is
still classical `sw` (needs LAMMPS_POTENTIALS); running it under the
universal MLIP instead (already loaded, no external file, arguably more
faithful) is a future option — kept classical for now (§4.5). REMAINING:
node-validate the full subprocess activate on GPU (small spec; set
SABSIM_CASCADE_ENGINE_PREFIX + SABSIM_CASCADE_MLIP_MODEL +
SABSIM_ALLOW_UNVALIDATED_POTENTIAL=1 + LAMMPS_POTENTIALS); ARCH §4.1/§4.4 +
DESIGN docs for the out-of-process cascade engine; deployment `[usage.
activate]` GPU + the env. Original in-progress detail below.

**ACTIVATE-STAGE GPU ENGINE — IN PROGRESS (subprocess + file handoff).**
Decision (Paul): the universal cascade engine (deepmd-official bundle, its
OWN torch/MPI) CANNOT use the in-process `LammpsEngine` model ARCH §4.1/§4.4
assume (shared `libmpi` with mpi4py) — it must run OUT-OF-PROCESS as the
bundle's `lmp -in <script>`, handing back a structure FILE (ARCH §4.3).
BOUNDARY: the subprocess runs the WHOLE LAMMPS half (cascade + re-anneal,
one `lmp` invocation) and writes the activated structure; the sabsim process
builds the slab before and runs the §3.5 gate after, reading that file.
Classical cascade stays fully in-process on CPU, unchanged. DONE so far
(pure + tested, 11 green): `reanneal_commands` extracted from `mlip_reanneal`
(behavior-preserving) and `build_activate_script(...)` — the full
out-of-process script (setup+prerelax+precomputed impacts+reanneal+
`write_dump id type x y z` handoff), proven to match the live command stream
exactly. STILL TO BUILD: (1) subprocess runner (bundle `lmp`, isolated env,
GPU) keyed off `SABSIM_CASCADE_MLIP_MODEL` + a bundle-prefix ref; (2) read
the dump back → gate + amorphized-half snapshot from FILE (today they read
the live engine); (3) branch in `activate_one_half` (universal→subprocess,
classical→in-process); (4) deployment: `[usage.activate]` GPU + how the
bundle is made available — OPEN SUB-DECISION: a cpg modulefile for the
bundle vs an env-prefix var (partly outside the repo, may need $CPG_SHARE
work); (5) document the out-of-process cascade engine in ARCH §4.1/§4.4
(currently in-process-only) + DESIGN; (6) node-validate the full activate
subprocess on GPU.


**Decision (Paul): a universal foundation MLIP drives the CASCADE only;
bespoke DeePMD drives the BOND-DEBOND.** Genuinely universal (no bespoke
training); do NOT fall back to classical.

**CASCADE ForceModel WIRED + NODE-VALIDATED (2026-08-08, job 16012217).**
`resolve_cascade_generator` is now UNIVERSAL-FIRST for every material:
`pair_style hybrid/overlay deepmd <DPA-2.4-7M.pt2> zbl zbl` with the
species-derived cores. Classical is the explicit `SABSIM_CASCADE_CLASSICAL`
opt-in; the universal entry is `validated=False` so a default cascade needs
`SABSIM_ALLOW_UNVALIDATED_POTENTIAL` until it clears the §3.5 gate. The
EXACT emitted block ran a real Si-slab+Ar mini-cascade on the V100: 100
steps, energy conserved (drift ~0.01 eV/1729 atoms), no NaN — proving
`pair_style deepmd (.pt2 GNN)` COMPOSES in `hybrid/overlay` with ZBL (the one
risk). Decisions locked: projectile mapped to its real element (no NULL);
empty preload (bundle lmp has deepmd built in); `atom_modify map yes` rides
on `ForceModel.needs_atom_map` and the preamble injects it before read_data;
`.pt2` path via `SABSIM_CASCADE_MLIP_MODEL` (deploy-time, GPU-arch-specific).
Full suite green (323). Code: `cascade_potential.py` (universal model +
generalized ZBL assembly + resolver), `commands.py` (needs_atom_map +
preamble), `cascade.py`/`live_stages.py` (use_classical threading), tests,
`DESIGN.md` §4.7 + `TODO.md`. Job scripts: `dpa_gpu_bench/
universal_cascade_check.slurm`. NEXT (TODO §4.7): (a) select the deepmd GPU
engine for the activate stage + deploy-time `.pt2` build; (b) first
gate-passing activation → flip `validated=True`; (c) native DP-ZBL as a
later close-range refinement.

**GPU IS NOW WORKING (2026-08-08, job 16010337). Option C SOLVED for the
production model — DPA-2.4-7M runs on the V100 via the AOTInductor `.pt2`
path.** 4096-atom Si NVE, 100 steps: energy conserved (TotEng −26521.42 eV,
drift ~0.01 eV), E_pair −6.51 eV/atom, no NaN, **0.289 s/step**, 14.2
katom-step/s — ~28x the CPU throughput (CPU was 0.5 katom-step/s). This is
now the adopted GPU cascade engine (`deepmd-kit-3.2.0b0-cuda129`).

**CORRECTION to the old "both models fail `.dp→.pt2` on `u0`" claim below:
they fail DIFFERENTLY.**
- **DPA-2.4-7M:** `torch.export` SUCCEEDS; the only blocker was the
  AOTInductor C++ LINK (`ld: cannot find -lcuda`) — the CUDA driver stub
  not on the link path. FIX: symlink the node's `libcuda.so.1` as a bare
  `libcuda.so` on `LIBRARY_PATH` (link-time; keep runtime `LD_LIBRARY_PATH`
  clean for isolation). Then `dp convert-backend .dp .pt2` completes and
  LAMMPS runs `pair_style deepmd .pt2`. Worked first try.
- **DPA-3.1-3M:** the ACTUAL `u0` case, and it is SOURCE-LEVEL, not a
  config knob. `deepmd/dpmodel/utils/network.py::get_graph_index`
  (called from `descriptor/repflows.py:635`) does
  `n_edge = int(xp.sum(xp.astype(nlist_mask, xp.int32)))` — casting the
  data-dependent edge count to a Python `int`, which `torch.export` cannot
  specialize (`GuardOnDataDependentSymNode`, `u0`). The two
  `torch._dynamo` capture flags do NOT help (the code demands a concrete
  value; it is not a graph-break). A deepmd source patch would fix it
  (mark `n_edge` size-like via `torch._check_is_size`, or bound it by
  `nloc*nnei`). DEFERRED — DPA-2.4-7M is faster AND compiles, so it wins.

**PRODUCTION MODEL = DPA-2.4-7M** (GPU `.pt2`). DPA-3.1-3M stays a
research/accuracy option pending the upstream (or our) `network.py` patch.

Artifacts (job 16010337): `$CPG_SHARE/share/models/dpa_gpu_bench/v320fix/`
(`dpa24.pt2` 184M works; `dpa24.dp`, `dpa3.dp`), job
`v320_gpu_fix.slurm` + Python export shim `dp_export_pt2.py`, install recipe
§7 updated. CPU adoption below stays valid as the no-GPU fallback.

**DECISION 2026-08-08 (superseded on GPU): ADOPT the deepmd-official bundle
as the cascade engine.** CPU works everywhere; GPU works for DPA-2.4-7M
(above). Route E (ASE-on-GPU) is now UNNEEDED for DPA-2.4. Route C for
DPA-3.1 remains a source patch if that model is ever wanted on GPU.

**WHAT WORKS (proven):** DPA-2.4-7M and DPA-3.1-3M (both FULL periodic
table, H->Og, via the `MP_traj_v024_alldata_mixu` branch) run in **LAMMPS
on CPU** (DPA-2.4 completed a run; DPA-3.1 computed forces E_pair=-1166 eV
then only OOM'd on a 16GB cap) AND in **Python eager on CPU+GPU**
(DeepPot.eval: DPA-3 -43.2 eV, DPA-2.4 -52.1 eV on the V100). The models,
coverage, and concept are validated.

**THE ENGINE:** deepmd's OFFICIAL self-contained offline-installer bundle
(NOT our conda-forge/torch-2.11/custom-LAMMPS stack). Two installed:
- CPU: `/home/rulisp/data/scratch/deepmd_official/dp313cpu` (deepmd 3.1.3 +
  torch 2.10; SCRATCH/disposable — the proven CPU engine).
- GPU: `/cluster/VAST/rulisp-lab/cpg/programs/deepmd-kit-3.1.3-cuda129`
  (deepmd 3.1.3 + torch 2.10, cuda129, py312) and
  `.../deepmd-kit-3.2.0b0-cuda129` (v3.2.0b0 beta, torch 2.11, has the
  AOTInductor path). Both are self-contained conda envs.
ACTIVATE (per-stage, ISOLATED from sabsim): fully reset the env first
(`unset` all `CONDA_*`, `CONDA_SHLVL=0`, `PATH=/usr/bin:/bin`) THEN
`source $PREFIX/etc/profile.d/conda.sh; conda activate $PREFIX`. Hard-verify
`python` is the bundle's. GOTCHA: if the sabsim env (torch 2.11) leaks in,
LAMMPS loads 2.11 and crashes the same way — isolation is mandatory.

**GPU-LAMMPS IS BLOCKED (why we run CPU):** two SEPARATE beta/upstream
issues, neither CLI-fixable:
- deepmd 3.1.3 (torch 2.10): the C++ **TorchScript** force path crashes on
  the V100 — DPA-3 at `custom_silu`, DPA-2 after load. (Works on CPU +
  Python-eager; V100 arch IS supported: sm_70 in torch arch_list.)
- deepmd 3.2.0b0 (torch 2.11): the new **AOTInductor `.pt2`** path (the
  intended fix, native compiled C++ inference, NOT TorchScript) can't
  EXPORT these models: `dp --pt freeze -o .pth --model-branch` works (must
  pass `--pt` else it defaults to TF), `dp convert-backend .pth .dp` works
  (17-26 MB `.dp`), but `.dp -> .pt2` fails in `torch.export` on an
  UNBACKED-SYMINT / data-dependent-shape guard (`u0` symbol — common in
  GNN neighbor handling). Not fixable from `convert-backend` (no dynamo
  knobs). `dp --pt-expt freeze` also can't prune the multitask branch.

**DEFERRED GPU routes (return here if CPU too slow):**
- **C — Python-level AOTInductor export.** Bypass `convert-backend`: in
  Python, set `torch._dynamo.config.capture_scalar_outputs=True` +
  `capture_dynamic_output_shape_ops=True` (the standard cures for the `u0`
  unbacked-symint error), then drive deepmd's `.pt2` export. Needs digging
  into deepmd's export internals; a code investigation, not a quick job.
- **E — ASE-on-GPU MD (LAMMPS-independent).** The models run in eager
  PyTorch on GPU (proven), so ASE's MD integrators + deepmd's ASE
  calculator can run the cascade ON GPU, bypassing LAMMPS/TorchScript
  entirely. BUT SABSIM's whole cascade+bond-debond driver is LAMMPS-based
  (ZBL cores, frozen base + border thermostat, adaptive dt, projectile
  spawn, §3.5 gate) — using ASE means REIMPLEMENTING that. Big change.
- Also worth a later re-check: a NEWER GPU (A100/H100) on the 3.1.3
  TorchScript path, and a stable deepmd >3.2.0 once released.

**NEXT (adopt-and-wire, CPU):**
1. Formalize the cascade engine: a `cpg` modulefile for the deepmd-official
   CPU/GPU bundle + wire it as the activate-stage engine (deployment
   per-stage env, isolated as above); a `mace_model`-style `ForceModel`
   emitting `pair_style deepmd <frozen.pth>` behind
   `_assemble_hybrid_overlay`/`resolve_cascade_generator`.
2. Freeze the chosen model's MP-traj branch (`dp --pt freeze -c <ckpt> -o
   <out.pth> --model-branch MP_traj_v024_alldata_mixu`) as the production
   cascade model (pick DPA-2.4-7M — fully proven; DPA-3.1-3M if preferred).
3. DP-ZBL (native, `dp_zbl_model`) for cascade close-range still to wire;
   DESIGN §4.7 "universal + native ZBL" update.
4. Benchmark actual CPU cascade throughput on a real box to judge whether C
   or E is needed.
Bench/test scripts live in `$CPG_SHARE/share/models/dpa_gpu_bench/`
(cputest.slurm proved CPU; v320_gpu_test.slurm has the .pt2 workflow).

### The debugging saga (why deepmd-official-bundle, ruled-out paths)

Our stack = conda-forge deepmd-kit 3.1.3 (pins **torch 2.11**, bleeding
edge) + our custom-built LAMMPS + runtime plugin. Both universal DPA
models freeze fine + run in EAGER Python, but crash in the LAMMPS C++
TorchScript path: DPA-3 at `custom_silu` (SiLUT), DPA-2 at
`task_deriv_one -> torch.autograd.grad` (the force derivative in
`forward_lower`). RULED OUT (with evidence): `atom_modify map yes` (no
help); `dp freeze` activation/precision flags (none exist, only
`--model-branch`); the `pytorch-exportable`/`.pte` export (C++
`libdeepmd_cc` only loads `.pth` TorchScript — "Unsupported model file
format"); conda-forge older-torch (cuda torch floor is 2.11; deepmd 3.1.3
pins 2.11); conda-forge `lammps` package (downgrades to deepmd 2.2.7 — NO
conda-forge lammps for deepmd 3.x; the plugin IS the only 3.x mechanism, so
our setup was standard). An "other LLM" suggested fixes 1&3 were fabricated
(nonexistent flags); fix 2 accidentally pointed at the real (dead-for-
LAMMPS) pt-expt backend. The offline installer was the pivot: deepmd ships
`.sh` bundles for every release (`deepmd-kit-3.1.3-{cpu,cuda129}`), self-
contained with THEIR tested torch (2.10) + LAMMPS — and it works.

GOTCHA: system `/usr/bin/curl` has NO https (use `wget`). GPU installer =
3 split parts, `cat` them together. Staging: installer + CPU test bundle in
`/home/rulisp/data/scratch/deepmd_official/` (scratch, purgeable — the CPU
bundle `dp313cpu` is disposable; the 5GB installer `.sh` can be deleted).

## What is already CONFIRMED for DPA (all positive)

- **deepmd-kit 3.1.3 (our installed version) supports DPA-1/2/3** — the
  `descriptor/dpa{1,2,3}.py` modules are present — AND ships a **native
  DP-ZBL model** (`deepmd/.../model/dp_zbl_model.py`, `pairtab_atomic_
  model.py`, `linear_atomic_model.py`). So the cascade close-range
  repulsion is composed INSIDE the model (radiation-damage use case), with
  NO fragile LAMMPS `hybrid/overlay` and NO domain-decomposition limit.
- **NO new environment / NO new build needed.** The EXISTING deepmd plugin
  `.../mamba/envs/sabsim/lib/libdeepmd_lmp.so` already links libtorch
  (`ldd` shows `libtorch*.so`, `libc10*.so`) — so it can run PyTorch-backend
  models, which DPA is. This is the whole reason we chose DPA over MACE.
- **DPA-3.1-3M downloaded** to `$CPG_SHARE/share/models/dpa3.1-3m/`
  (`DPA-3.1-3M.pt`, 47 MB; `README.md`; `input_pretrain.json`). License
  **CC-BY-4.0** (commercial OK). Requires deepmd-kit **v3.1.0** (we have
  3.1.3 ✓). Repo: HuggingFace `deepmodelingcommunity/DPA-3.1-3M` (not
  gated). NOTE: system `/usr/bin/curl` has NO https (build-time); use
  `wget` for HF downloads.
- **`dp --pt show ... model-branch` works** — it's a MULTITASK model
  (branches: `MP_traj_v024_alldata_mixu`, `Omat24`, `Domains_SemiCond`,
  `Others_HfO2`, ... `RANDOM`). Use a branch by FREEZING it.
- **Froze the broad Materials-Project branch** `MP_traj_v024_alldata_mixu`
  → `bench/frozen_mptraj.pth` (18 MB, "singletask model"). **Element
  coverage = FULL PERIODIC TABLE, H→Og (118 elements)** incl Si/O/Ga/N/
  Li/Nb — genuinely universal, meets Paul's hard requirement. 3.27M params
  (3.11M descriptor + 155k fitting).
- Benchmark job `15960072` FAILED only because the cell-build used
  `python -c "import ase"` and **`ase` is in the VENV layer
  (`.../virtual_envs/sabsim`), NOT the conda `python`**. Fixed the slurm to
  build the Si cell in PURE PYTHON (no ase). Resubmitted → `15960373`.

## Benchmark job — how it works / how to rerun

`$CPG_SHARE/share/models/dpa3.1-3m/bench/dpa3_bench.slurm`:
freeze MP-traj branch → `dp show type-map size` → build ~4096-atom Si cell
(pure python) → `lmp -in bench.in` (100 steps, `pair_style deepmd
frozen_mptraj.pth`, `pair_coeff * * Si`) → grep Performance. Env: `dp` +
`python` from the conda env (`$ENV/bin` on PATH), `lmp` from module
`cpg_lammps_conda/2024.08.29-deepmd`, `DEEPMD_LMP_PLUGIN` set explicitly to
`$ENV/lib/libdeepmd_lmp.so`, `unset LAMMPS_PLUGIN_PATH` + the SLURM_MEM
triplet. GPU: `gpu,requeue` / `--account=general` / V100. Rerun:
`sbatch dpa3_bench.slurm`.

## The three-track plan (from the four-agent inventory)

**Track 1 — universal cascade MLIP (DPA-3.1-3M + native DP-ZBL).** After
the benchmark passes: wire it behind the existing seam. The cascade force
model is built by `_assemble_hybrid_overlay` (`driver/cascade_potential.py`)
via `resolve_cascade_generator`; the universal path needs a registry entry
+ a ForceModel that emits `pair_style deepmd <frozen.pth>` (deepmd already
has `deepmd_model()` in `driver/commands.py:160`). DESIGN §4.7 already says
universal-first is the default. DESIGN UPDATE to capture: "universal + ZBL
*overlay*" → "universal with *built-in/native* ZBL" (MACE-MP has built-in
ZBL; deepmd has native DP-ZBL) — simplifies the recipe.

**Track 2 — bespoke DeePMD bond-debond.** re-anneal (§3.4) + press/pull run
the trained committee. `deepmd_model` + the `SABSIM_DEEPMD_MODEL` override
already work for press/pull (`live_stages.py:849`); generalize that seam to
the re-anneal (`_reanneal_force_model`, today classical). The committee/σ
+ interface gate + OOD-scaffold removal need a trained committee (bootstrap,
unbuilt) — deferred.

**Track 3 — realization ensemble loop (model-independent, wire ANYTIME).**
STRUCTURAL-4: loop `exec_one_member` over `amorphization_count`×
`velocity_count` seeds in the sequencer (§10.8), aggregate the bond metric
→ `Measure.value`=mean, `uncertainty`=realization spread. Today one
realization runs; `amorphization_count` is only a metadata stamp. Cleanest
standalone first win; needs no MLIP.

## Key seam facts (from the inventory — file:line)

- Real seam is ONE `ForceModel` (`driver/commands.py:122`: pair_style /
  pair_coeff / preload); `force_model_commands` (`:260`) has NO branching.
- `deepmd_model(path)` (`commands.py:160`) emits `pair_style deepmd <path>`
  + `pair_coeff * *` + preload plugin-load lines. Proven via
  `SABSIM_DEEPMD_MODEL` override.
- `resolve_potential` (`skeleton_stages.py:60`) is DECORATIVE — returns a
  classical stand-in, IGNORED by the live stages (they resolve their own
  ForceModel). Wiring a committee there has no effect unless the live
  stages are changed to consume it.
- `resolve_cascade_generator` / `_assemble_hybrid_overlay`
  (`cascade_potential.py:361/472`) build the cascade `hybrid/overlay
  <classical> zbl zbl`; `entry.classical_style` is registry-driven (NOT
  hardcoded sw). Registry `CASCADE_GENERATOR_REGISTRY` (`:120`).
- CASCADE + RE-ANNEAL run in ONE process (`activate_surface`,
  `driver/cascade.py:461`: cascade → mlip_reanneal). WRINKLE: universal
  MLIP (cascade) + bespoke DeePMD (re-anneal) want different torch
  versions → can't coexist in one process. Resolve when wiring: split into
  two engine invocations (file handoff) OR run re-anneal under the
  universal model. Deferred.

## MACE — PARKED (not abandoned)

Paul first preferred MACE. Parked because:
- **No torch 2.2 (MACE-validated) on conda-forge** — only 2.11/2.12/2.13
  CUDA libtorch. Must stay on conda-forge (cxx11 ABI=1) to match
  `liblammps.so`; the pytorch-channel torch 2.2 is pre-cxx11 ABI=0 → would
  rerun the DeePMD CXXABI fight.
- So MACE would run on torch 2.11 (UNVALIDATED for MACE); risk shifts to
  `mace-torch 0.3.16` + pinned `e3nn 0.4.4` on torch 2.11 (untested).
- Plugin path IS viable without a new engine: `XJTU-ICP/mace_lammps_plugin`
  builds against our existing `liblammps.so` (29Aug2024, has
  `BUILD_SHARED_LIBS`+`PKG_PLUGIN`). Configure got 95% — the ONLY blocker
  was the CUDA-libtorch cmake demanding CUDA **dev headers**
  (`cuda_runtime.h`) that the conda env lacks (has nvcc + cudart runtime,
  not the `-dev` headers). Would need a fresh isolated MACE env (torch
  2.2 unavailable) or adding cuda `-dev` to a clone.
- MACE `pair_style mace` needs `no_domain_decomposition` (bypasses LAMMPS
  neighbor list) — an MPI limit DPA does not have. MACE-MP DOES have
  built-in ZBL though.
Parked artifacts (leave; revisit only if DPA fails):
`/home/rulisp/programs/lammps/mace_lammps_plugin` (clone),
`.../build-mace-plugin` (failed configure). The `mace_probe` venv was in
node-local `/tmp` (ephemeral).

## NEXT (in order)

1. Read `dpa3-bench-15960373.out` — runnable? ms/step? Decide DPA-3.1-3M vs
   fall back to DPA-2 (faster) / DPA-1 (fastest, if elements fit).
2. If DPA-3 works: wire Track 1 (universal cascade ForceModel behind
   `_assemble_hybrid_overlay` / a registry entry; native DP-ZBL for
   close-range) + the DESIGN §4.7 "built-in ZBL" update.
3. Track 3 (ensemble loop) can proceed in parallel anytime — model-free.
4. Track 2 re-anneal seam generalization; committee/bootstrap deferred.
5. Resolve the cascade↔re-anneal one-process/two-torch wrinkle when wiring.
