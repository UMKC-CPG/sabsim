# MLIP integration — universal cascade + bespoke bond-debond (working note)

Working note, 2026-08-07. Tracks the effort to close the "runs on real
physics" gap (TODO L1788): wire a universal foundation MLIP for the
CASCADE and the bespoke DeePMD for the BOND-DEBOND. NOT canonical yet.

## RESUME HERE (2026-08-07)

**Decision (Paul): a universal foundation MLIP drives the CASCADE /
amorphization ONLY; the bespoke DeePMD (a trained committee later) drives
the BOND-DEBOND (re-anneal + press/pull).** No allegiance to a specific
universal MLIP — the only requirement is that it is genuinely universal so
cascades run with NO bespoke additional training.

**Where we landed: DPA-3.1-3M (deepmd) is the universal cascade model,
pending a speed check.** We PIVOTED here from MACE (see "MACE — parked").

**IN FLIGHT: GPU benchmark job `15960373`** (resubmitted; earlier
`15960072` failed only on a trivial `ase` import — see below). Results
land in:
`/cluster/VAST/rulisp-lab/cpg/share/models/dpa3.1-3m/bench/dpa3-bench-15960373.out`
Check on return: `sacct -j 15960373 --format=JobID,State,Elapsed,ExitCode`
then read that `.out`. It answers the two open questions:
1. **Runnability** — does our conda `libdeepmd_lmp.so` actually RUN a DPA-3
   (message-passing) model in LAMMPS (`pair_style deepmd frozen_mptraj.pth`)?
   This is the last real unknown (the DPA custom-op question).
2. **Speed** — `ms/step` on ~4096 Si atoms (≈ cascade box) on a V100. Is a
   3.27M-param message-passing model fast enough to drive a full-dose
   cascade? If too slow → fallback ladder: DPA-2, then DPA-1.

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
