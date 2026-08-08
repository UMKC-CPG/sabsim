# MLIP integration — universal cascade + bespoke bond-debond (working note)

Working note, 2026-08-07. Tracks the effort to close the "runs on real
physics" gap (TODO L1788): wire a universal foundation MLIP for the
CASCADE and the bespoke DeePMD for the BOND-DEBOND. NOT canonical yet.

## RESUME HERE (2026-08-08, LATEST — read this first)

**Decision (Paul): a universal foundation MLIP drives the CASCADE only;
bespoke DeePMD drives the BOND-DEBOND.** Genuinely universal (no bespoke
training); do NOT fall back to classical.

**DECISION 2026-08-08: ADOPT the deepmd-official bundle as the cascade
engine, run it on CPU for now.** GPU-LAMMPS is blocked (see below) but that
is a performance gap, not a correctness one — the universal model is PROVEN
to run in LAMMPS. Deeper GPU routes (C, E below) are DEFERRED; revisit if
CPU throughput is insufficient.

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
