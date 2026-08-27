# Environment / Engine Validation Ledger

Append-only record of every environment and engine test we run, so that
a later reflection reads **exact commands and exact output lines**, not
prose recollection.  This file exists because prose reports of "this
works / that was wrong" swung confusingly; a committed script plus a job
ID plus a quoted output line cannot be re-narrated.

## Rules (do not break these)

1. **One committed script per test.** The script IS the exact command.
   No claim rests on an ad-hoc shell line typed once and lost.  The
   as-run script lives beside this file (copied verbatim after it ran).
2. **Every new script self-logs its environment** as its first output:
   `module list`, the relevant `env` vars, `command -v python mpirun`,
   `ldd` of the `liblammps` that loaded, and `lammps.__file__`.  The log
   alone must reconstruct what ran.
3. **Every entry below cites**: job ID, as-run script path, the exact
   launch line(s), the specific evidence line(s) quoted verbatim, the
   verdict, and — mandatory — **Scope NOT covered** (what the test did
   *not* prove, so no one over-reads it).
4. **Append-only.** A superseded entry is marked `SUPERSEDED by <job>`,
   never edited or deleted.  The record of a wrong turn stays visible.
5. **No "decisive/proven" in any report** without a job ID + quoted
   evidence line from this ledger.

---

## T-FABRIC — job 15551674 — 2026-07-31

**Question.** Does the conda OpenMPI 5.0.10 in `sabsim_dev` reach this
cluster's InfiniBand fabric across two nodes, or does it fall back to
TCP ("slow and fragile")?

- **As-run script:** `install/tests/launch_fix.slurm` + `fabric_test.py`
  (mpi4py ping-pong; NO LAMMPS).
- **Environment:** conda env `sabsim_dev`; both launches preceded by
  `unset SLURM_MEM_PER_NODE SLURM_MEM_PER_CPU SLURM_MEM_PER_GPU`.
- **Exact launch lines:**
  - `srun --mpi=pmix -n 2 <python> fabric_test.py`
  - `mpirun -np 2 <python> fabric_test.py`
- **Evidence (verbatim):**
  - nodes: `rank 0 -> c039`, `rank 1 -> c043` (2 distinct hosts)
  - UCX: `ucp_context_0 inter-node cfg#1 tag(rc_mlx5/mlx5_0:1)`
  - ping-pong: `4194304    346.9    12.090` (GB/s), 1.9 us lat @ 8 B
  - `=== M1b exit: 0 ===`, `=== M2b exit: 0 ===`
- **Verdict: PASS.** conda 5.0.10 + UCX 1.20.1 selects the Mellanox
  `rc_mlx5` transport and hits ~12 GB/s / 1.9 us — native IB, not TCP.
- **Scope NOT covered:** LAMMPS not involved; this is a bare mpi4py
  ping-pong.  Says nothing about any LAMMPS engine or deepmd.

---

## T-BUILD-C — job 15554787 — 2026-07-31

**Question.** Can both LAMMPS engines be source-built against conda
OpenMPI 5.0.10 and pass the static safety checks?

- **As-run script:** `install/build_lammps.sh`.
- **Result prefixes:**
  `…/programs/lammps/22Jul2025-conda-ompi5.0.10` and
  `…/programs/lammps/2024.08.29-deepmd-conda-ompi5.0.10`.
- **Evidence (verbatim, VERIFY block):**
  - glibc floor: `GLIBC_2.14`
  - libmpi: `libmpi.so.40 => …/sabsim_dev/lib/libmpi.so.40`,
    `libopen-pal.so.80 => …/sabsim_dev/lib/libopen-pal.so.80`
  - libpython: `none: Python-agnostic`
  - deepmd symbol: the no-trailing-int `utils::bounds<int>(…Error*)`
  - `15554787|COMPLETED|0:0`
- **Verdict: PASS (build-time / static only).** Binaries exist and are
  statically correct (glibc-safe, conda libmpi, deepmd ABI symbol).
- **Scope NOT covered:** never imported, never run, never launched on
  2 nodes, deepmd never registered or run.  No RUNTIME evidence at all.

---

## T-SITE-ENGINE — job 15580445 — 2026-08-01

**Question.** Does Imago's SITE-toolchain engine
(`cpg_lammps/2024.08.29-deepmd`, OpenMPI 4.1.5) load and run 2-node
IN-PROCESS under the `sabsim_dev` venv Python — with deepmd registering
— now that no competing conda `liblammps` exists?  (Directly tests the
ARCHITECTURE §4.1 claim that "the site modules do NOT fit here".)

- **As-run scripts:** `install/tests/site_engine_probe.slurm` +
  `site_engine_probe.py`.
- **Environment:** `module use …/cpg/modulefiles;
  module load cpg_lammps/2024.08.29-deepmd` (auto-loads
  `openmpi/4.1.5_gcc_12.3.0`); venv Python
  `…/virtual_envs/sabsim_dev/bin/python`; `unset SLURM_MEM_PER_*`.
  MODEL = LAMMPS-owns-MPI: `lammps()` built with **no `comm=`** and
  **no mpi4py imported**.
- **Exact launch lines:**
  - A1: `mpirun -np 2 <venv python> site_engine_probe.py`
  - A2: `srun --mpi=pmix -n 2 -N 2 <venv python> site_engine_probe.py`
- **Evidence (verbatim, both A1 and A2):**
  - wrapper: `…/2024.08.29-deepmd/lib64/python/lammps/__init__.py`
  - `1 by 1 by 2 MPI processor grid`
  - `RANKINFO world_rank=0/2 host=c014…`,
    `RANKINFO world_rank=1/2 host=c024…`
  - `pair_style deepmd registered: True`
  - `SITE ENGINE OK`; `=== A1 mpirun exit: 0 ===`,
    `=== A2 srun exit: 0 ===`
- **Verdict: PASS.** The site engine loads under the venv (conda)
  Python, MPI_Init spans both nodes, a real SW step runs, deepmd
  registers.  Refutes §4.1's "site modules do NOT fit".
- **Scope NOT covered (important):**
  1. **LAMMPS-owns-MPI model only** — NOT the `mpi4py` comm-sharing
     model that SABSIM's DESIGN currently uses (no `comm=` was passed).
  2. deepmd was **registered, not run** — no trained model, no deepmd
     force step.
  3. **No fabric-bandwidth measurement** — 2-node functional only; did
     not re-measure GB/s the way T-FABRIC did.

---

## T-CONDA-ENGINE — job 15582291 — 2026-08-01

**Question.** Does our conda-built deepmd engine (OpenMPI 5.0.10) run
2-node in-process under the venv Python using the **mpi4py
comm-sharing** model SABSIM's code actually uses (comm=MPI.COMM_WORLD +
comm.bcast)?  Symmetric counterpart to T-SITE-ENGINE (15580445).

- **As-run scripts:** `install/tests/conda_engine_probe.slurm` +
  `conda_engine_probe.py`.
- **Environment (self-logged in the .out):** conda engine prefix
  `…/2024.08.29-deepmd-conda-ompi5.0.10` via PYTHONPATH/LD_LIBRARY_PATH
  (NOT a Lmod module); venv Python; `unset SLURM_MEM_PER_*`.
  MODEL = comm-sharing: mpi4py imported first, then
  `lammps(comm=MPI.COMM_WORLD)`, plus a real `comm.bcast`.
- **Exact launch lines:**
  - C1: `srun --mpi=pmix -n 2 -N 2 <venv python> conda_engine_probe.py`
  - C2: `<sabsim_dev>/bin/mpirun -np 2 <venv python>
    conda_engine_probe.py`
- **Evidence (verbatim, both C1 and C2):**
  - `libmpi.so.40 => …/sabsim_dev/lib/libmpi.so.40`,
    `libopen-pal.so.80 => …/sabsim_dev/lib/libopen-pal.so.80`
  - `mpi4py module  : …/sabsim_dev/…/mpi4py/__init__.py`
  - `RANKINFO rank=0/2 lammps_world=2 host=c009… bcast_ok=True`,
    `RANKINFO rank=1/2 lammps_world=2 host=c010… bcast_ok=True`
  - `1 by 1 by 2 MPI processor grid`; `Loop time … on 2 procs`
  - `pair_style deepmd registered: True`; `CONDA ENGINE OK`
  - `=== C1 srun exit: 0 ===`, `=== C2 mpirun exit: 0 ===`
- **Verdict: PASS.** Fills Stack C cells **E1 + E2 + E4**.  mpi4py and
  liblammps share one conda libmpi 5.0.10; LAMMPS sees world_size=2
  across 2 hosts; the Python-side comm.bcast returns on every rank;
  deepmd registers.  Stack C supports SABSIM's current code unchanged.
- **Scope NOT covered:**
  1. deepmd **registered, not run** (no trained model) — E3 still open.
  2. Not a full `sabsim prepare` -> activate run — E5 still open.
  3. **Confound noted:** the log shows `Loaded 1 plugins from
     …/envs/sabsim/lib/deepmd_lmp` at startup — a stray
     `LAMMPS_PLUGIN_PATH` (pointing at the OLD sabsim env) is leaking in
     from the inherited environment and auto-loading a plugin before our
     explicit `plugin load`.  Harmless to the verdict (it loaded cleanly
     into the conda 2024.08.29 engine, which itself proves ABI match),
     but it must be cleaned up when the old sabsim env is retired.  Same
     leak was present in 15580445.

---

## T-FEATURES — job 15683172 — 2026-08-04

**Question.** The build recipe REQUESTS 25 packages, but a requested
CMake flag is not proof of a compiled-in package.  Do BOTH Stack-C
engines actually contain every LAMMPS package the styles SABSIM emits
depend on — and exactly what do they trade away vs Imago's 26-pkg site
engine?  (Closes the gap left by T-BUILD-C, whose "Scope NOT covered"
noted it had NO runtime evidence of the package set.)

- **As-run scripts:** `install/tests/features_probe.slurm` +
  `features_probe.py`.  The probe reads the live
  `lammps.installed_packages` from each installed binary and diffs it
  against REQUIRED_BY_SABSIM (packages the emitted styles need, derived
  by grepping src/ for pair_style/fix/compute literals) and the site
  26-set.  REQUIRED_BY_SABSIM = {MANYBODY, EXTRA-FIX, PLUGIN, ML-SNAP,
  ML-IAP}; core styles (nve/nvt/langevin/setforce/aveforce/move/
  box-relax/minimize/dump-custom/compute-reduce/temp-com/region) need
  no package.
- **Environment (self-logged):** conda engines selected via
  PYTHONPATH/LD_LIBRARY_PATH (NOT Lmod); venv Python; `unset
  SLURM_MEM_PER_*`; one serial rank per engine
  (`srun --mpi=pmix -n 1`) — package registration is identical on
  every rank, so no multi-node launch needed.
- **Evidence (verbatim, IDENTICAL for BOTH engines):**
  - deepmd `LAMMPS version : 20240829`;
    classical `LAMMPS version : 20250722`
  - `package count  : 25`
  - `MISSING_REQUIRED  : (none)`
  - `dropped_vs_site   : ML-HDNNP VORONOI`
  - `extra_vs_site     : (none)`
  - `has_pair_style sw/zbl/tersoff/vashishta : True` (all four)
  - `has_fix halt       : True`
  - `FEATURES OK`; `=== … exit: 0 ===` for both
- **Verdict: PASS.** Every package SABSIM's emitted styles require is
  present in BOTH Stack-C engines, and every named pair_style + `fix
  halt` registers.  The conda build trades away EXACTLY two packages
  vs the site engine — `ML-HDNNP` and `VORONOI` — neither of which any
  code path invokes (their only repo mentions are TODO.md /
  build_lammps.sh, flagged as deliberately deferred).
- **Scope NOT covered:**
  1. Package **presence**, not a physics run — a style registering is
     not the same as it producing correct forces (that is E3 for
     deepmd; SW/ZBL already ran in T-SITE/T-CONDA-ENGINE).
  2. ML-HDNNP / VORONOI are absent by design; if a FUTURE study needs
     HDNNP potentials or Voronoi analysis, restore per the
     build_lammps.sh note (add dep to environment.yml + re-enable the
     flag + DOWNLOAD_N2P2 / DOWNLOAD_VORO) and re-run this probe.

---

## T-DEEPMD-RUN — job 15686597 — 2026-08-04

**Question.** Does a REAL trained deepmd model compute forces through the
Stack C engine (E3) — and can our deepmd **3.1.3** plugin load a model
frozen by the group's deepmd **2.2.10 / TensorFlow** training stack (the
training->inference SEAM)?  Uses Prakash's PRODUCTION Si model.

- **As-run scripts:** `install/tests/e3_deepmd/deepmd_run.slurm` +
  `deepmd_run_probe.py` (model retargeted from an in-house .pth to the
  real .pb after Prakash's model appeared 2026-08-04 10:24).
- **Model:** `/cluster/VAST/rulisp-lab/cpg/share/train_deepmd_si/graph.pb`
  — a fully-trained (checkpoint `model.ckpt-400000`) deepmd-kit 2.2.10 /
  TensorFlow Si potential, type_map ["Si"], se_e2_a, rcut 6.
- **Environment (self-logged):** FULL `conda activate sabsim_dev` (so the
  deepmd TF backend + libtensorflow_cc are wired) via the system mamba
  hook, THEN the Stack C deepmd engine prepended on PYTHONPATH/
  LD_LIBRARY_PATH; `unset LAMMPS_PLUGIN_PATH` + `SLURM_MEM_PER_*`;
  explicit `plugin load $DEEPMD_LMP_PLUGIN`.  1 node, 1 rank, 1 A100.
- **Exact launch line:** `srun --mpi=pmix -n 1 <venv python>
  deepmd_run_probe.py`.
- **Evidence (verbatim):**
  - plugin: `Loading plugin: deepmd pair style`; `build variant: cuda`;
    `build with tf lib: …/libtensorflow_cc.so.2`; `support model ver.:
    1.1`
  - model: `using   1 model(s): …/graph.pb`, `rcut in model: 6`,
    `ntypes in model: 1`
  - GPU bound: `Created device …/device:GPU:0 … NVIDIA A100 80GB`
  - `pair_style deepmd registered: True`
  - real MD: step 0->10 `E_pair -1169.4621 -> -1166.511`;
    `potential_energy (eV): -1166.510969`
  - `global_max_force (eV/Angstrom): 1.051713` (finite, non-zero)
  - `DEEPMD RUN OK`; `=== E3 run exit: 0 ===`
- **Verdict: PASS.** Fills Stack C cell **E3**.  A trained model computes
  real, finite forces through the Stack C engine.  DECISIVELY: our deepmd
  **3.1.3** plugin loads and runs a deepmd **2.2.10 / TensorFlow** `.pb`
  DIRECTLY — no `dp convert-from`, no rebuild — so the group's existing TF
  training stack feeds SABSIM's Stack C bond engine unchanged.  The
  earlier "training(2.2.10/TF) vs inference(3.1.3) seam" is RESOLVED, not
  merely bridgeable.
- **Scope NOT covered:**
  1. Single rank on ONE GPU — multi-rank deepmd across ranks/GPUs not
     re-proven here (MPI decomposition itself is E4-proven with the
     classical engine, job 15582291).
  2. Physics NOT validated — a force step executing is not a check that
     the potential is accurate; that is the MLIP bootstrap's job (§11),
     not an install test.
  3. The TF/cuDNN "already registered" + oneDNN lines on stderr are
     benign TF+torch coexistence warnings (exit 0); not investigated
     further.

---

## T-E5-ACTIVATE — job 15703266 — 2026-08-04

**Question.** Does a full `sabsim prepare` -> activate run go green
end-to-end on the conda-derived engine, through the WIRED deployment
path (generated script -> module load -> srun -> venv interpreter ->
sabsim -> build -> cascade)?  This is E5, the last open cell.

- **As-run scripts:** `sabsim prepare <jobs/si_si_e2e/sabsim.toml> --rc
  <machine-local deployment.toml>` generated
  `si-si-reference_activate.slurm` (in the E5 scratch dir); it does
  `module use …/cpg/modulefiles; module load cpg_lammps_conda/22Jul2025`
  then `srun --mpi=pmix -n $SLURM_NTASKS python -m sabsim run … --activate
  --only si-si-reference`.  Submitted from a shell with `sabsim_dev`
  active (SLURM --export=ALL carries it).
- **Environment (self-evident in the run):** conda-derived classical
  engine via the module; venv Python on every node (proven by the srun
  fix); 2 nodes x 2 ranks; `--mem=96G` (see scope note 3).
- **Evidence (verbatim):**
  - `sabsim run: job 'activate' complete`
  - `member 'si-si-reference': wrote assembled_pair`
  - `15703266  COMPLETED  0:0  …  00:42:49`; step `MaxRSS 313588K`
    (~306 MB peak — modest, not a leak)
  - remote-node ranks ran the venv Python
    (`…/virtual_envs/sabsim_dev/…`), NOT the conda-env Python
- **Verdict: PASS.** Fills the conda-engine cell **E5**.  The full
  deployment consumer works on the conda-derived stack: prepare writes a
  correct script, the module selects the engine, srun carries the venv
  interpreter to every node, and the real Si/Si cascade runs to a written
  `assembled_pair`.  With E5 green, the conda engine now PASSES F1/E1/E2/
  E3/E4/E5/build/feat — the complete matrix.
- **Two prepare.py bugs this surfaced, both fixed + tested (287 pass):**
  1. Launcher was `mpirun`, which does NOT preserve the venv on REMOTE
     nodes (remote rank fell back to the conda-env Python lacking
     `sabsim`) — DIAGNOSED job 15697153; switched to `srun --mpi=pmix`
     (§4.1's stated primary launcher).
  2. The generated script did not emit `unset SLURM_MEM_PER_*` that §4.1
     promises; added.
- **Scope NOT covered:**
  1. `si-si-reference` member only (not `si-sio2`); `activate` job only
     (`bond`/`analyze` not run in this smoke).
  2. Physics not validated — a written `assembled_pair` proves the
     plumbing, not that the amorphization is correct (§3.5 gate's job).
  3. **`--mem=96G` was HAND-ADDED to the generated script.** The default
     allocation OOM-killed the cascade at ~44 min (job 15697360), and the
     deployment rc / prepare have NO memory knob.  FOLLOW-UP: add a memory
     field to the `[usage.*]` schema so prepare emits `#SBATCH --mem`
     (peak was only ~306 MB, so a small default suffices).
     [RESOLVED 2026-08-05: the memory knob landed (#5); prepare now emits
     `#SBATCH --mem` from a required `memory` field.]

---

## T-6A-BOND — job 15724578 — 2026-08-05

**Question.** Does the `bond` job kind run end-to-end on the GPU partition
through the WIRED deployment path — the generated script allocating a GPU
node, loading the conda-derived deepmd engine module, `srun` carrying the
venv, RE-READING the activate job's `assembled_pair` across a SEPARATE
submission, running press->settle->pull, and writing `pull_results`?  This
is 6a: the deployment PLUMBING, on the classical stand-in — NOT the deepmd
force model (that is 6b).

- **As-run scripts:** `si-si-reference_bond.slurm` + `deployment_6a.toml`
  (both in the E5 dir `…/install-tests/e5_prepare_activate/`), spec
  `jobs/deploy_smoke/sabsim.toml` (trimmed: 20 ps press, single 10 m/s
  rung).  The script is `sabsim prepare`'s OWN output regenerated with the
  #5 `--mem` fix, then two HAND-ADDS (see scope 2).
- **Reuse:** re-read the EXISTING E5 `assembled_pair` (job 15703266) from
  the member scratch keyed by the E5 job dir — activate NOT re-run.
- **Environment (self-evident in the run):** conda-derived deepmd engine
  via `module load cpg_lammps_conda/2024.08.29-deepmd`; venv Python; GPU
  node g027; 1 node x 2 ranks; `--mem=32G` (from #5); `--gres=gpu:
  V100-PCIE-32GB:1` + `unset LAMMPS_PLUGIN_PATH` HAND-ADDED; `unset
  SLURM_MEM_PER_*`.
- **Exact launch line:** `srun --mpi=pmix -n "${SLURM_NTASKS}" python -m
  sabsim run …/deploy_smoke/sabsim.toml --bond --only si-si-reference`.
- **Evidence (verbatim):**
  - `sabsim run: job 'bond' complete`
  - `member 'si-si-reference': wrote pull_results`
  - `15724578|…|COMPLETED|0:0|01:03:40`; `15724578.0|python|COMPLETED|0:0|
    01:03:38|316052K` (~309 MB peak, well under the 32 GB ceiling)
  - artifacts written: `pull_results.manifest.toml` (10527 B),
    `pull_10mps/log.pull`, `log.press`, `settled_reference.data`
- **Verdict: PASS (6a).**  The bond deployment plumbing works on the
  conda-derived stack: the generated script allocates a GPU node, the
  module selects the engine, `srun` carries the venv, the bond job
  RE-READS the activate job's `assembled_pair` across a separate
  submission, and press->settle->pull writes `pull_results`.  The
  activate->bond file handoff (ARCHITECTURE §4.3) is proven on the GPU
  partition, as separate submissions.
- **Scope NOT covered (important):**
  1. **CLASSICAL stand-in only.** `resolve_potential` returned the SW
     stand-in; the deepmd FORCE MODEL was NOT exercised through the
     pipeline (`LAMMPS_PLUGIN_PATH` was unset so no plugin loaded).  That
     is 6b.  E3 (15686597) proved the deepmd engine computes real forces
     STANDALONE; this does not re-prove it and does not connect it to the
     pipeline.
  2. **Two HAND-ADDS.**  `--gres` — prepare emitted none at run time; the
     GPU knob has SINCE landed (`gpus_per_node`, this same day) so a fresh
     bond script now carries `--gres=gpu:4`.  `unset LAMMPS_PLUGIN_PATH` —
     a 6a-only isolation, a 6b question.  (deployment_6a.toml predates the
     `gpus_per_node` field, so it would need that key added to re-prepare.)
  3. **Trimmed protocol** (20 ps press, single 10 m/s rung, pull capped at
     `RunControl.max_chunks=500`) — NOT the full 3-rung ladder; M1/M3 are
     not converged.  Plumbing, not physics.
  4. `si-si-reference` only; 2 ranks on 1 GPU (SW does not use the GPU);
     no multi-GPU deepmd decomposition.
  5. Benign stderr on g027: PMIx `psec/munge` "component not found"
     probe warnings + pymatgen CIF rounding — exit 0, run completed.

---

## T-6B-DEEPMD — job 15725126 — 2026-08-05

**Question.** Does a REAL trained DeePMD model drive the pipeline's own
press/pull — `sabsim run --bond` -> `_bonded_force_model` -> plugin load ->
`pair_style deepmd` -> GPU force eval — as opposed to only running deepmd
STANDALONE (which E3, job 15686597, already proved)?  This is 6b: the
trained-MLIP force path THROUGH the pipeline, via the new
`SABSIM_DEEPMD_MODEL` override.

- **As-run scripts:** `si-si-reference_bond.slurm` + `deployment_6b.toml`
  (E5 dir).  The script is `sabsim prepare`'s output (now auto-emitting
  `--gres=gpu:1` from the new `gpus_per_node` knob), with the gres TYPE
  refined to the free V100 + two hand-adds: `export
  SABSIM_DEEPMD_MODEL=…/train_deepmd_si/graph.pb` and `unset
  LAMMPS_PLUGIN_PATH`.
- **Model / structure:** Prakash's Si `graph.pb` (type_map ["Si"], ntypes
  1); reused the E5 `assembled_pair` (1 atom type Si — matches).  1 node x
  1 rank x 1 V100 (g027).
- **Evidence — WIRING PROVEN (verbatim, from log.press / .out):**
  - `variable dp getenv DEEPMD_LMP_PLUGIN`
  - `plugin load …/envs/sabsim_dev/lib/libdeepmd_lmp.so`
  - `Loading plugin: deepmd pair style  by Han Wang`
  - `pair_style deepmd …/train_deepmd_si/graph.pb`
  - `using   1 model(s): …/graph.pb`; `rcut in model: 6`; `ntypes … 1`
  - `Created device …/device:GPU:0 … Tesla V100-PCIE-32GB`
  - deepmd+TF footprint `MaxRSS 862248K` (~842 MB, vs classical ~309 MB
    in 6a — still far under the 32 GB ceiling)
- **Evidence — RUN FAILED (verbatim):**
  - `sabsim: run halted — ERROR: Lost atoms: original 8800 current 8781
    (src/thermo.cpp:494)`
  - `15725126|…|FAILED|1:0|00:02:44`; died IN THE PRESS (the pull was
    never reached — no new `pull_results`; the `pull_10mps/` on disk is
    6a's, timestamp 07:05, this job ran ~07:46).
- **Verdict: PARTIAL — wiring PROVEN, run INCOMPLETE.**  The deepmd force
  model DID drive the pipeline's press on the GPU through the new seam
  (`_bonded_force_model` -> `deepmd_model` -> `force_model_commands` emits
  `plugin load` before `pair_style deepmd`), which is 6b's code goal and
  is now proven on real hardware.  The run then lost 19 atoms in the press
  and LAMMPS aborted (lost atoms are fatal by default outside the cascade).
- **Cause: potential MISMATCH, not a code defect.**  The reused
  `assembled_pair` was activated AND re-annealed under the CLASSICAL
  potential (E5 activate, job 15703266), then pressed under DeePMD.  The
  Si deepmd model sees that classically-amorphized surface as
  out-of-distribution and ejects surface atoms almost immediately (the
  fatal error hits ~seconds into the press MD).  The `_bonded_force_model`
  contract is literally "press under the SAME potential the surfaces were
  annealed under"; the override broke that on purpose (it changed only the
  bond force model, not `_reanneal_force_model`, and reused a classical
  pair), so this failure is EXPECTED physics of the shortcut.
- **Scope NOT covered / caveats:**
  1. **No deepmd press/pull to completion**; the pull was never reached,
     so there is NO deepmd `pull_results` and NO deepmd M1/M3.
  2. **The mismatch is inherent to the REUSE shortcut.**  A faithful
     deepmd bond must ALSO activate/re-anneal under deepmd (so the pressed
     structure is deepmd-equilibrated), OR minimize/re-equilibrate the
     pair under deepmd before pressing.  Both are more than a quick reuse
     — deferred to the §11 bootstrap wiring or a dedicated longer run.
  3. **Provenance decoupling** (as forecast): `resolve_potential` is
     unchanged, so the run's `potential` record still says
     "classical-stand-in" while the forces were deepmd.  The real fix is
     wiring `resolve_potential` to the committee so both agree.
  4. Single rank, 1 V100, Si-only model on a 1-type Si pair; no multi-GPU
     deepmd decomposition.
  5. Benign stderr: TF cuFFT/cuDNN/cuBLAS "already registered" +
     DP/OMP parallelism-thread WARNINGs (TF+torch coexistence).  The
     fatal line is the lost-atoms; exit 1.

---

## T-RENAME — job 15726178 — 2026-08-05

**Question.** After renaming the deployment env `sabsim_dev` -> `sabsim`
(removed the old dead `sabsim`, cloned `sabsim_dev` -> `sabsim`, rebuilt
the venv, `patchelf`-ed the engine RPATHs, repointed the modulefiles), do
BOTH conda-derived engines still LOAD and RUN a real MD step under the new
`sabsim` env — so `sabsim_dev` can be removed safely?

- **As-run scripts:** `install/tests/rename_validate.slurm` +
  `rename_validate.py`.  GPU node (L40S); self-activates `sabsim` (the
  two-step conda+venv activation), `module load`s each engine in turn,
  builds a tiny diamond-Si box from a lattice (no data file), runs.
- **Evidence (verbatim):**
  - classical (`cpg_lammps_conda/22Jul2025`):
    `potential_energy (eV): -933.1183568608094`; `RENAME VALIDATE
    classical: OK`
  - deepmd (`cpg_lammps_conda/2024.08.29-deepmd`, plugin from
    `envs/sabsim`, Prakash `graph.pb`):
    `potential_energy (eV): -1169.289125433037`; `RENAME VALIDATE
    deepmd: OK`
  - `classical exit: 0 ; deepmd exit: 0`; `RENAME VALIDATE: PASS (both
    engines run under env sabsim)`; `15726178 COMPLETED 0:0 00:00:20`
- **Verdict: PASS.**  Both engines `import lammps` (so `liblammps.so`
  loads — which after the patchelf resolves `libmpi` from `envs/sabsim`,
  not `sabsim_dev`; a broken RPATH would fail the load) and run real MD;
  the deepmd plugin loads from the module's repointed `envs/sabsim` path
  and computes forces.  The rename is safe; `sabsim_dev` env + venv were
  removed after this passed.
- **What the rename did (for the record):** (1) removed the old dead
  `sabsim` env + venv; (2) `conda create -n sabsim --clone sabsim_dev`;
  (3) rebuilt `virtual_envs/sabsim` via `build_venv.sh`; (4) `patchelf
  --set-rpath` on the 4 engine ELF files (`bin/lmp` +
  `lib64/liblammps.so.0` per engine), `envs/sabsim_dev/lib` ->
  `envs/sabsim/lib`; (5) repointed the modulefiles (tracked + published;
  deepmd's `deepmd_env` -> `envs/sabsim`), the recipe
  (`environment.yml` / `build_venv.sh` / `build_lammps.sh`),
  `.sabsim/sabsimrc` (already named `sabsim`), `~/.bashrc` (dropped the
  `ssabsim_dev` alias), and the docs; (6) removed `sabsim_dev` env + venv
  + `.sabsim/sabsimrc_dev`.
- **Scope NOT covered:**
  1. Engines were `patchelf`-ed, NOT rebuilt from source — valid because
     `sabsim` is an EXACT clone of `sabsim_dev` (identical libs), so the
     RPATH swap points at byte-identical `libmpi`/`libstdc++`.  A
     from-source rebuild (`build_lammps.sh`, now `CONDA_ENV=sabsim`) would
     reproduce them if ever needed.
  2. Single rank, one GPU, a tiny lattice box — a functional load+run,
     not a multi-node or physics check (those are the E-series / 6a).
  3. The `current` symlink is unchanged (it is version-named, carries no
     env name).

---

## T-8 — jobs 15876062 (activate) + 15876145/243/342/690 (bond) — 2026-08-06

**Question.** Does a real trained DeePMD model drive a GREEN bond THROUGH
the SABSIM pipeline — activate (classical) -> assemble -> relax -> scissors
-> press -> settle -> pull — end to end, on a deepmd-consistent pair (not
6b's reused classically-activated pair)?

- **As-run:** `jobs/si_si_deepmd/` (gitignored) — `sabsim prepare` output,
  hand-edited bond (partition `gpu,requeue`, account `general`, typed V100
  gres, `SABSIM_DEEPMD_MODEL=.../train_deepmd_si/graph.pb`, `unset
  LAMMPS_PLUGIN_PATH`). Study spec `initial_gap=15 A`. Model: Prakash Si
  `graph.pb` (type_map ["Si"], rcut 6). The pipeline code under test is
  COMMITTED: 41aad23 (relax+scissors), e51be05 (OOD-safe relax),
  22d44f6 (dividing-surface gap), bbd9f31 (overlap clamp).
- **Activate (job 15876062): PASS.** Classical cascade -> re-anneal ->
  §3.5 gate -> assemble wrote a Si-only `assembled_pair` at a closest-atom
  gap of 11.04 A (`wafer_b[0]-wafer_a[1] = 81.63-70.60`) — free surfaces
  for the relax. Gate passed (the blocking gate only writes the pair on
  success).
- **Bond — four runs, each a distinct finding (all verbatim from
  `log.press`), all ultimately the SAME out-of-distribution cause:**
  1. **15876145** — relax was a plain minimize: `ERROR: Lost atoms:
     original 8799 current 8782` (17) IN THE RELAX MINIMIZE. The bulk-Si
     model sees the classically-amorphized surface OOD; an unconstrained
     minimize ejects loose atoms. -> e51be05: capped/damped/wall relax.
  2. **15876243** — capped relax SURVIVED (`run 5000`, 8799 intact), but
     scissors was SKIPPED (min/max closest-atom measure fooled by an atom
     that wandered into the gap during the ~500 K self-heated relax);
     press faced the vacuum: `Lost atoms ... current 8798` (1).
     -> 22d44f6: measure the gap by the dividing surface.
  3. **15876342** — scissors FIRED: `displace_atoms scissors_upper move
     0.0 0.0 -38.03 units box` — but 38 A into an ~11 A gap
     (`interface_opening` read ~45 A: the OOD relax depleted the interface
     density), driving the wafers together: `Lost atoms ... 8798`.
     -> bbd9f31: clamp the cut by the actual nearest atoms.
  4. **15876690** — the clamp PREVENTED the overshoot, but scissors was
     SKIPPED again (atom-ceiling -> 0: a stray atom within 2.5 A of the
     other wafer); press faced the vacuum: `Lost atoms ... current 8797`
     (2).
- **Verdict: PLUMBING PROVEN; a clean end-to-end GREEN is DEFERRED.** What
  is proven: the deepmd plugin loads and DRIVES both the relax AND the
  press on the GPU through the wired pipeline (`plugin load` ->
  `pair_style deepmd` -> `Tesla V100`), and the relax->scissors->press
  sequence executes. The SCISSORS mechanism is verified — it fires, cuts,
  and clamps (301 unit tests incl. `test_scissors_delta_is_clamped_
  against_wafer_overlap`, and it fired live in 15876342). What is NOT
  achieved: no `settled_reference.data`, no `pull_results`.
- **Scope NOT covered / why deferred.** Every failure is an artifact of an
  INADEQUATE model — a bulk-crystal Si potential run on amorphous surfaces
  is OOD, so the relax self-heats (~500 K) and sprays interface atoms,
  CORRUPTING the surface geometry that any gap measure must read (the
  density metric over-reads on depletion; the atom metric under-reads on a
  stray). No amount of measure-robustification fixes a corrupted
  structure. The real fix is a model that knows these surfaces — the
  trained COMMITTEE / per-slab re-anneal under DeePMD (DESIGN §3.4) — after
  which the TEMPORARY OOD relax scaffold (capped/damped/wall) is removed
  (see the TODO). Also: single rank / 1 V100 / Si-only; provenance still
  labels `classical-stand-in` (resolve_potential unwired).

---

## T-9 — jobs 16306379 (activate) + 16306381 (bond) — 2026-08-09

**Question.** Does the RE-ARCHITECTED activate->bond split (DESIGN §3.4/
§3.5/§4.7) run end-to-end on the GPU: a cascade-ONLY universal-MLIP
activate (no re-anneal, no gate — substrate-only), assemble at the WIDE
gap, then the bond flow's HEAL -> per-wafer §3.5 GATE -> halt/scissor/press
in-process under a single frozen bespoke DeePMD model (a "committee of
one")?  This is the split's plumbing on real hardware — distinct from T-8
(pre-re-arch: classical activate, gate at the activate seam).

- **As-run scripts (committed):**
  `install/tests/t9_universal_split/` —
  `t9a_activate_assemble.{py,slurm}` (Job A),
  `t9b_bond_press.{py,slurm}` (Job B), `submit.sh`, `README.md`.
  Both drivers self-log their environment as their first output.
- **Structure / models:** a small 2x2x4 diamond-Si slab per half, ONE Ar
  impact each, `cascade_step_cap=300`. Cascade = universal **DPA-2.4-7M**
  `.pt2` (`v320fix/dpa24.pt2`) + ZBL, out-of-process in the deepmd bundle.
  Bond = **committee of one**: the group's Si `graph.pb` (type_map ["Si"],
  rcut 6), in-process via `cpg_lammps_conda/2024.08.29-deepmd`.
- **Environment (self-logged in each .out):** Job A — sabsim venv +
  `SABSIM_CASCADE_ENGINE_PREFIX`/`_MLIP_MODEL`/
  `_ALLOW_UNVALIDATED_POTENTIAL=1`, NO engine module (the bundle is
  spawned isolated); Job B — sabsim venv + the deepmd module,
  `SABSIM_DEEPMD_MODEL=.../train_deepmd_si/graph.pb`, `unset
  LAMMPS_PLUGIN_PATH` + `SLURM_MEM_PER_*`. Both 1 node / 1 rank / 1 V100.
- **Exact launch lines:** `bash install/tests/t9_universal_split/
  submit.sh` -> `sbatch t9a_activate_assemble.slurm`;
  `sbatch --dependency=afterok:16306379 t9b_bond_press.slurm`; Job B runs
  `srun --mpi=pmix -n 1 <venv python> t9b_bond_press.py`.
- **Evidence — Job A (verbatim, `t9-activate-16306379.out`):**
  - cascade force model: `hybrid/overlay deepmd .../v320fix/dpa24.pt2
    zbl 0.5 2 zbl 0.5 1.2`
  - `[half a] readback atoms: 128  surviving types: [1]` (and half b) —
    Si only, the Ar projectile stripped as cascade cleanup
  - `assembled pair atoms: 255  closest-atom gap: 7.606 A` (clears the
    6 A separation cutoff -> free-surface heal)
  - `T9A ACTIVATE+ASSEMBLE OK`; `16306379  COMPLETED  0:0  00:03:08`
- **Evidence — Job B (verbatim, `t9-bond-16306381.out`):**
  - `using   1 model(s): .../train_deepmd_si/graph.pb`; `rcut in model: 6`;
    `Tesla V100-PCIE-32GB`
  - `loaded pair atoms: 255 | type_map: {'Si': 1}`;
    `bond pair_style: deepmd .../graph.pb`
  - `note: activation gate failed (§3.5): radial_distribution: measured
    0.475 vs 0.3 (.../share/activation/Si.toml)`
  - `activation_a : passed=False  reason=radial_distribution: 0.475 vs
    0.3`; `activation_b : passed=False  reason=... 0.725 vs 0.3`
  - `GATE RAN PER WAFER TAG (a and b) — new bond-flow seam engaged`;
    `contact_reached : False`
  - `T9B BOND HEAL+GATE+PRESS OK`; `16306381  COMPLETED  0:0  00:00:14`
- **Verdict: PASS (plumbing).** The re-architected split runs end-to-end
  on the GPU: cascade-ONLY universal activate hands back a substrate-only
  amorphized half (projectile stripped), two halves assemble at a
  7.6 A wide gap, and the bond flow HEALS the combined cell under the
  committee-of-one, GATES each healed surface PER WAFER TAG, and HALTS on
  the failed gate before any scissor/press — carrying both verdicts out.
  The `.pt2` universal cascade (subprocess) and the `graph.pb` committee
  (in-process) each ran on the V100 in their own job, handing off through
  the on-disk pair. Every new re-arch seam engaged as designed.
- **Scope NOT covered (important):**
  1. **The gate did NOT pass**, so there is NO scissor, NO press-to-
     contact, NO bond, NO pull. A 128-atom slab with ONE impact and a
     short capped heal is under-activated; the `radial_distribution`
     reference (0.3, `share/activation/Si.toml`) is a documented stand-in
     threshold. Whether that is under-activation or a threshold artifact
     is (h)'s question (first gate-PASSING activation -> `validated=True`),
     NOT this plumbing test's.
  2. **Committee of ONE**, not an N-member committee; a single frozen
     model behind the seam.
  3. **NOT the full `sabsim prepare` deployment path** — this is a
     driver-level harness that calls the same seams directly. E5
     (15703266) proved prepare->activate for CLASSICAL activate; the
     prepare path for the GPU-universal activate is a separate follow-on.
  4. Single rank / 1 V100 per job; one impact, `cascade_step_cap=300`,
     capped `RunControl`, 5 ps trimmed hold — plumbing, not physics.
  5. Provenance unchanged (`resolve_potential` still classical stand-in),
     as in 6b/T-8.

---

## T-17 — box-relax 16453628 + lattice/stiffness probes — 2026-08-21

**Question.** For the geometrically-matched SiO2/LiNbO3 oxide pair that
DETONATED under the fixed-box DPA press (t14/t15), WHERE does the frame-0
stress come from, and does a one-time in-plane `box/relax` find a
zero-stress cell the crystal can hold? (The A.2/§5.6 + A.3 question.)

- **As-run scripts (diagnostic probes, ARCHIVED not distributed — a
  deliberate rule-1 exception, see Scope 1):** `install/tests/archive/
  t17_dpa_lattice/` — `relax_lattice.py`
  (per-material bulk box-relax under DPA), `build_stiffness_probe.py` +
  `stepwise_measure.py` (+/-1% strain -> stress slope -> biaxial
  modulus), `box_relax_probe.py` + `box_relax.slurm` (the assembled-pair
  in-plane box/relax + NVT stability probe).
- **Structure / model:** SiO2(100)/LiNbO3(001) matched halves; force
  model = universal DPA-2.4-7M `.pt2`, out-of-process in the deepmd
  bundle on a V100. Bulk cells 576 (SiO2) / 540 (LiNbO3); stiffness slabs
  54 / 60 atoms; assembled pair 5724 atoms.

- **Evidence 1 — the CIF lattice is far off the DPA lattice
  (`t17_val/lattice_results.json`, verbatim):**
  - SiO2  `"initial_pressure_bar": 73862.6 -> "final_pressure_bar":
    4592.4`; `"percent_change_abc": [-0.53, -1.25, +2.08]`
  - LiNbO3 `"initial_pressure_bar": 84347.2 -> "final_pressure_bar":
    2793.3`; `"percent_change_abc": [-0.68, -0.43, +0.69]`
  So each bulk crystal built from CIF numbers sits ~7-8 GPa off the
  model's own equilibrium — a per-material, MISFIT-INDEPENDENT stress.

- **Evidence 2 — biaxial moduli are close
  (`t17_stiffness/stepwise_results.json`, verbatim mean-in-plane stress
  vs strain, linear):** SiO2 (pxx+pyy)/2 falls 62617 -> 15458 bar across
  the +/-1% sweep -> M ~= 234 GPa; LiNbO3 falls from 80571 bar similarly
  -> M ~= 276 GPa (ratio ~1.18). So the even split sits NEAR the
  stiffness-weighted split; re-weighting is a modest refinement.

- **Evidence 3 — one-time in-plane box/relax finds a zero-stress cell the
  crystal holds (job 16453628, `t17-boxrelax-16453628.out`, verbatim):**
  - BEFORE (even-split cell): `atoms=5724 box a=22.019 b=38.504`;
    `[whole] press=57681 pxx=97829 pyy=57648 pzz=17566 bar`
  - AFTER `box/relax x 0 y 0` + minimize: `box a=21.961 (-0.27%)
    b=38.491 (-0.03%)`; `[whole] press=-7815 pxx=-37 pyy=-25 ... bar`;
    `pe/atom -8.9327 -> -9.3588`
  - after 2.0 ps NVT 300 K on the relaxed cell: `atoms=5724 (lost 0)
    temp=293.8 K`; `VERDICT (relaxed cell): HELD and STAYED ORDERED
    (box-relax cell survives!)`; `=== T-17 box-relax exit 0 ===`

- **Verdict: FINDINGS captured (diagnostic).** The oxide-pair frame-0
  stress is dominated by the CIF-vs-DPA lattice offset (~7-8 GPa per
  material, Evidence 1), NOT by the coincidence-misfit or the even split
  (moduli within 18%, Evidence 2). A single in-plane `box/relax x 0 y 0`
  + minimize drives the assembled pair's in-plane stress to ~0
  (pxx 97829 -> -37, pyy 57648 -> -25 bar) with a -0.27% box change, and
  the relaxed cell STAYS ORDERED under 2 ps of 300 K NVT with no atom
  loss (Evidence 3). This is the demonstrated A.2 one-time combined-cell
  relax, and the reason mainline must build on the §2.2 derived lattice.

- **Scope NOT covered:**
  1. **Diagnostic probes, ARCHIVED not distributed** — the scripts above
     live under gitignored `install/tests/archive/` and self-select cells
     via env vars. DELIBERATE rule-1 exception: the raw probes hold
     dead-ends that would mislead if shipped, so their LESSONS are
     reproduced by the promoted mainline routines + committed tests (the
     combined-cell box-relax, the biaxial-stiffness routine, the
     worst-axis strain metric), not by the probes.
  2. **`box/relax` relaxed only x,y** — pzz was left compressive
     (-23382 bar); z is the free-surface/grip axis, handled separately.
  3. **No per-slab stress split** — the `.pt2` exposes only the GLOBAL
     virial, so box-relax finds ONE combined-cell minimum, not each
     slab's share.
  4. **Provenance-record + freeze are UNBUILT** — the probe measures the
     relaxed cell but does not write it to provenance or freeze x,y for a
     subsequent press; that wiring is the promotion work (§5.6/§2.6).
  5. **Universal model, not the bespoke committee**; single V100; the
     stiffness slope->modulus FIT was done by hand off the JSON, not
     coded in any script.

---

## T-18 — job 16701588 (combined-cell-relax oxide press) — 2026-08-22

**Question.** Does the mainline combined-cell relax (Phase-3 item 3,
commit `cd4c46e`) stop the SiO2/LiNbO3 press detonation on real hardware?
The pair used to blow apart between press frames 9-10 under the fixed-box
press; item 3 replaced the forbidden live `lateral_relax` barostat with a
one-time recorded `fix box/relax x 0 y 0` at the joint heal.

- **As-run scripts (committed):** `install/tests/t15_driver_dpa/` —
  `assemble_pair.py` (part 1, sabsim env) + `driver_press_pull.py`
  (part 2, deepmd bundle python) + `t15_driver_dpa.slurm`. The harness is
  DEMO-gated (gate bypassed) so the press RUNS TO CONTACT and the outcome
  is visible; the combined-cell relax under test is now automatic inside
  mainline `press_and_bond`, so re-running t15 exercises it unchanged.
- **Structure / model:** the matched SiO2/LiNbO3 amorphized pair (small,
  193 atoms after the demo assembly), force model = universal DPA-2.4-7M
  `.pt2`, in-process in the deepmd 3.2.0b0 bundle on one V100. Launch:
  `sbatch --export=ALL,VALWORK=.../v_item3_press t15_driver_dpa.slurm`.
- **Evidence (verbatim, `t15-driver-dpa-16701588.out` / `.err`):**
  - `=== press ===`; `contact_reached : True`; `chunks_to_contact: 6`;
    `note : contact on the dual criterion, held at temperature (§9.3)`
  - press movie written: `v_item3_press/press_movie.dump` (1.25 MB) —
    opens in OVITO as a LAMMPS dump.
  - `settled reference: False` — the settle did not converge (short demo
    settle).
  - pull crashed: `Exception: ERROR: Lost atoms: original 193 current 192
    (src/thermo.cpp:494)` at `pull_at_rate` -> `run` (press_pull.py:717).
  - `16701588  FAILED`, `Total wall time: 0:23:14`.
- **Verdict: PARTIAL PASS — the detonation is FIXED.** The press reached
  contact on the dual criterion and HELD at temperature (chunk 6), with
  no blow-up: the combined-cell relax lets the strained oxide pair press
  stably where the fixed-box press detonated. Two downstream issues, both
  NOT physics failures of item 3: the settle did not converge (a demo
  tuning matter), and the pull hard-crashed on ONE lost atom because the
  press/pull `preamble_commands` lacks `thermo_modify lost warn` (the
  cascade has it, commands.py:1095) — so LAMMPS aborts on a sputtered atom
  BEFORE the driver's §5.6 atom-conservation gate can report it. That is a
  mainline gap (tracked in TODO), not a t15 defect.
- **Scope NOT covered:**
  1. **Gate DEMO-bypassed** — this proves the PRESS (item 3), not the
     §3.5 per-wafer gate (item 6); that is a separate validation.
  2. **Small demo pair (193 atoms), short capped RunControl, one fast
     pull rung** — plumbing + behaviour, not a converged measurement.
  3. **Settle + pull did NOT complete** — no work-of-separation number;
     the pull needs the lost-atom fix above before it can run to the end.
  4. Single V100, in-process bundle lammps; provenance is the demo
     harness, not the `sabsim prepare` deployment path.

---

## T-18 re-run — job 16701673 (lost-atom fix) — 2026-08-22

**Question.** With the lost-atom fix (`3e6b2aa`, `thermo_modify lost warn`
in the press/pull preamble), does the oxide press+settle+pull run to
completion instead of crashing as T-18 did on one lost atom?

- **As-run script:** `install/tests/t15_driver_dpa/` (unchanged from
  T-18; the fix is in mainline `commands.py`). Launch:
  `sbatch --export=ALL,VALWORK=.../v_item3_press_v2 t15_driver_dpa.slurm`.
- **Evidence (verbatim, `t15-driver-dpa-16701673.out`):**
  - `contact_reached : True` (press held to contact — item 3 again)
  - `settled reference: False` (the short demo settle did not converge)
  - `=== pull @ 10.0 m/s ===`; `complete : False`;
    `separation_index: None`; `atoms_conserved : True`
  - `T15 DRIVER-UNDER-DPA COMPLETE`; `=== T-15 exit 0 ===`
  - movies: `v_item3_press_v2/press_movie.dump` (1.16 MB) +
    `pull_movie.dump` (75 KB), both OVITO-readable.
- **Verdict: PASS — the fix resolves T-18's pull crash.** The full
  press -> settle -> pull now runs to a clean exit 0 (was `FAILED` on
  `ERROR: Lost atoms` at the pull); the driver's §5.6 atom-conservation
  gate is now reachable and reports `atoms_conserved=True`. Supersedes
  T-18's "pull crashed on one lost atom" finding.
- **Scope NOT covered:** the pull did NOT reach full separation
  (`complete=False`) within the 40-chunk cap at the fast 10 m/s rung, so
  there is still no converged work-of-separation number — a chunk-budget /
  pull-rate tuning matter, not a crash. Settle still did not converge
  (demo). Gate still DEMO-bypassed (that is T-19). Small demo pair.

## T-19 — job 16701674 (real per-wafer §3.5 gate) — 2026-08-22

**Question.** Does the per-wafer activation gate (Phase-3 item 6, commit
`ef7a07d`) run on real hardware — keying each oxide wafer by its OWN
declared species and judging it against its OWN reference?

- **As-run scripts (committed):** `install/tests/t19_oxide_gate/`
  (`assemble_pair.py` sets per-wafer species; `driver_press_pull.py` runs
  the REAL gate, no demo bypass) + `t19_oxide_gate.slurm`. Launch:
  `sbatch --export=ALL,VALWORK=.../t19_val t19_oxide_gate.slurm`.
- **Evidence (verbatim, `t19-oxide-gate-16701674.out`):**
  - `wafer A species ['O', 'Si'] | wafer B species ['Li', 'Nb', 'O']`
  - wafer A judged against `.../share/activation/O_Si.toml`: rdf PASS,
    coordination 0.284 PASS (band 0.05-0.60), ring 0.591 PASS, depth 0.0
    FAIL (target 7.0) -> `passed=False`.
  - wafer B judged against `.../share/activation/Li_Nb_O.toml`: rdf PASS,
    coordination 0.952 FAIL (band 0.05-0.60), ring 0.602 PASS, depth 34.0
    PASS -> `passed=False`.
  - `contact_reached : False`; `note: activation gate failed (§3.5)`;
    `T19 REAL-GATE DRIVER COMPLETE`; `=== T-19 exit 0 ===`
  - `t19_val/press_movie.dump` (561 KB) = the heal + combined-cell relax
    (item 3 runs BEFORE the gate).
- **Verdict: PASS (plumbing).** The gate keyed each wafer by its OWN
  species set (O_Si for SiO2, Li_Nb_O for LiNbO3), loaded the correct
  per-material reference for each, ran all four metrics per wafer, and
  HALTED before the press on failure -- exactly item 6's design. The
  global-type-map bug is gone.
- **Scope NOT covered (the CALIBRATION question, open):** both surfaces
  FAILED the stand-in thresholds, informatively -- wafer A (SiO2) on depth
  = 0.0 (the metric found no amorphized skin), wafer B (LiNbO3) on
  coordination = 0.952 (OVER-coordinated, the SAME signature as the T-10
  Si coordination wall). Whether the universal cascade over-amorphizes /
  over-coordinates the oxides or the `real=false` stand-in bands + depth
  targets are mis-set is the open per-material calibration question
  (shared with T-10). This validates the gate PLUMBING, not the oxide
  amorphization quality or the reference numbers.

---

## T-18 / T-18-rerun CORRECTION — 2026-08-22 (supersedes their PASS)

The T-18 and T-18-rerun verdicts above are WRONG and are retracted. I read
the driver's log fields, not the trajectory. Inspecting the actual dump
(`v_item3_press_v2/press_movie.dump`) shows the pair DISINTEGRATED under
the press: atom count 2631 -> 2167 (step 5000) -> 540 -> 318 -> ... -> 191
(step 20500), ~93% of atoms ejected. The system EXPLODED; it did not press
to contact.

Three corrections:
1. **The combined-cell relax (item 3) did NOT fix this detonation.** It
   cannot: the pair is a THIN RIBBON (`t12_val/match.pkl`: substrate/film
   aspect 5.2:1 / 6.35:1, tilings 1x6 / 1x5, x-extent 9.4 A = ONE unit
   cell) built on CIF lattices, i.e. the ~24 GPa configuration the
   archived T-17 README explicitly gates ("nothing downstream runs until
   re-matched at DPA lattices"). The validation ran on a known-bad cell.
2. **"193 atoms" was the post-explosion remnant, not the pair (2631).**
3. **`atoms_conserved=True` is a FALSE pass:** the driver captures the
   conservation baseline at PULL start, which here was the already-blown
   ~193-atom remnant, so the entire press-phase loss (2440 atoms) is
   invisible to the §5.6 gate. That is a mainline bug (tracked in TODO):
   the conservation gate has no coverage over the press phase.
4. `contact_reached=True` fired on flying-atom stress spikes, not a real
   press. T-19's gate-halt is unaffected (it never pressed).

CORRECT NEXT STEP (the archive's decision gate, not yet done): rebuild the
oxide pair at the DPA-preferred lattices (§2.2) AND on a LOW-ASPECT 2-D
cell (item-4 worst-axis-ranked match, `build_dpa_matched_halves.py` /
`square_cell_search.py` in the archive), verify near-zero frame-0 stress,
THEN press -- and judge every run from the TRAJECTORY, not the log.

---

## T-20 — job 16701820 (corrected 2-D DPA-lattice cell) — 2026-08-22

**Question.** After T-18's ribbon exploded, does a cell built the RIGHT way
-- each crystal rescaled to its DPA-preferred lattice (§2.2), matched on a
LOW-ASPECT 2-D coincidence ranked by the item-4 worst-axis strain -- start
near-enough zero stress under DPA and STAY ordered? (The archive's
decision gate.)

- **As-run scripts (committed):** `install/tests/t20_2dcell/`
  (`prepare_pair.py` builds it, `frame0_check.py` measures it) +
  `t20_2dcell.slurm`. Launch:
  `sbatch --export=ALL,VALWORK=.../v_2dcell_v2 t20_2dcell.slurm`.
- **Structure:** SiO2(100)/LiNbO3(001), rescaled to the DPA lattices,
  matched on the 644 A^2 / aspect-1.13 / worst-axis-1.77% / twist-5.4 cell
  (SiO2 tiling [[1,14],[0,24]], LiNbO3 [[4,5],[0,7]]); pristine pair 2976
  atoms (SiO2 1296 + LiNbO3 1680), both halves on the 23.70x26.80 A cell.
  Force model = universal DPA-2.4-7M `.pt2`, in-process bundle, one V100.
- **Evidence (verbatim, `t20-2dcell-16701820.out`):**
  - `[frame-0 (as built)] atoms=2976 pxx+pyy(mean)=5.09 GPa pzz=0.39 GPa`
  - `[after box-relax] atoms=2976 pxx+pyy(mean)=0.12 GPa pzz=-2.64 GPa`
  - `[after 2 ps NVT 300 K] atoms=2976 pxx+pyy(mean)=0.43 GPa pzz=-0.05
    GPa`
  - trajectory (`v_2dcell_v2/frame0_relax.dump`): 25 frames, atoms
    2976..2976 (NO loss), OVITO-readable.
  - `T20 FRAME0 CHECK COMPLETE`; `=== T-20 exit 0 ===`.
- **Verdict: PASS -- the corrected cell is sound, judged from the
  trajectory.** The 2-D DPA-lattice cell starts at 5.1 GPa in-plane (vs
  the T-18 ribbon-on-CIF's ~24 GPa), the item-3 combined-cell box-relax
  drives it to 0.12 GPa, and it STAYS ordered at 300 K (0.43 GPa, all
  2976 atoms held). This is the genuine validation of item 3 (the ribbon
  T-18 faked and retracted), the item-4 worst-axis 2-D cell, and the §2.2
  DPA-lattice rescale -- together. Contrast T-18: 24 GPa -> 191 atoms.
- **Scope NOT covered:** PRISTINE crystals (not yet activated); box-relax
  left pzz compressive (-2.64 GPa, z not barostatted) which the NVT then
  relieved (-0.05 GPa) via the free surfaces; no press/pull, no
  work-of-separation. NEXT: activate THIS cell's surfaces, then press.

## T-21 — jobs 16707838 + 16729651 + 16731025 + 16731354 — 2026-08-23

*(Si activate; null test; Tier-0 model screen; A100 export/portability.)*

**Question.** Does the universal-first cascade produce a THIN amorphized
skin under DPA-2.4-7M, and if not, why -- cascade parameters, thermostat,
or the model itself?

- **As-run scripts:** `$CPG_SHARE/share/models/dpa_gpu_bench/`
  (`v_si_fastcheck/`, `v_null_test/{energy_*,null_*}.in + null_test.slurm`),
  `share/models/tier0_screen/{tier0_screen.py,tier0_screen.slurm}`,
  `share/models/a100fix/a100_export.slurm`. NOT yet copied under
  `install/tests/` -- see "Scope NOT covered".
- **16707838 (Si/Si activate, reduced fluence 0.003, V100).** Half A ran
  4/4 impacts, 200 frames; job hit its 6 h wall during half B (TIMEOUT).
  Judged FROM THE TRAJECTORY:
  - atoms 4400 -> 4402 (4399 Si + 3 Ar); ONE Si sputtered. No explosion.
  - temperature RATCHETS every impact and never recovers:
    `132 -> 399 -> 727 -> 1024 -> 1377 -> 1598 -> 1729 K peak -> 1537 K`
    (Si melts at 1687 K). Half B, independent seed, reproduced it:
    `132 -> 374 -> 716 -> 848 K`.
  - energy bookkeeping: projectiles supplied 4 x 75 eV = 300 eV, but
    kinetic energy rose +799.5 eV while potential energy fell -875.9 eV
    and TOTAL energy fell -76.4 eV (Langevin was net REMOVING). The slab
    heated ITSELF: 0.199 eV/atom released.
  - structure: interior coordination 3.80 -> **5.75**, number density
    +11.5%, thickness 57.49 -> 51.54 A. NOT amorphous silicon (a-Si stays
    ~4-coordinated) -- a DENSE high-coordination phase.
  - §2.2 derive ran universal and out-of-process as designed:
    a = 5.3475 A vs the CIF's 5.4300 (**-1.52%**), zero strain in the
    built slab (measured NN distance 2.3155 A -> a = 5.3475 exactly).
- **16729651 (null test, V100).** Inherent-structure energies, deepmd
  ALONE (no ZBL), same box/surfaces:
  - `RESULT pristine   minimized_pe_per_atom -6.461513`
  - `RESULT amorphized minimized_pe_per_atom -6.882385`
  - the DAMAGED slab is **0.421 eV/atom LOWER** = 1852 eV over the slab.
    Surface cannot explain it (would need 20.7 J/m^2 vs ~1.5 real).
    Half A got 876 eV = 47% of the way through the transformation.
  - null DYNAMICS, no projectile: `withzbl` PE -28420.81 -> -28590.25,
    `nozbl` -28420.87 -> -28603.22 -- **ZBL is NOT implicated**. The
    pristine slab stays tetrahedral (coordination 3.80 -> 4.14) and
    EXPANDS (57.49 -> 58.53 A): it is METASTABLE; the dense phase needs
    an impact to nucleate.
- **16731025 (Tier-0 screen, H100 g034).** Minimize pristine vs damaged
  under each model; crystal MUST be lower:
  - `SUMMARY DPA-2.4-7M a=5.3473 a_error_pct=-1.54
    gap_eV_per_atom=-0.377817 verdict=FAIL`
  - `SUMMARY DPA-3.1-3M a=5.5147 a_error_pct=+1.54
    gap_eV_per_atom=+0.360604 verdict=PASS`
  - ASE/FIRE reproduced LAMMPS `box/relax` (5.3473 vs 5.3475) -- harness
    cross-validated by an independent route.
- **16731354 (A100 export + portability, g002).** 
  - **lmp loads `.pth` DIRECTLY** for BOTH models, energy conserved:
    dpa24 TotEng -26521.413 -> -26521.428 (6e-7 drift); dpa3
    -21959.485 -> -21959.393 (4e-6). `.pth` is NOT arch-locked.
  - `dpa24.dp -> dpa24_a100.pt2` export **OK on A100** (184 MB), NVE
    check exit 0, step-0 energy matching eager to 8e-8 relative.
  - `dpa3.dp -> .pt2` **FAILED with the same `u0` guard on A100** --
    confirming the bug is SOURCE-LEVEL, not architecture-related.
  - speed (4096 atoms): `.pt2` AOT A100 **0.1879 s/step**; `.pth` eager
    A100 0.4636; dpa3 `.pth` eager A100 0.8842; `.pt2` AOT V100 0.2890.
    **AOT is 2.47x faster than eager on the same hardware.**
- **Verdict: the universal cascade PLUMBING passes; DPA-2.4-7M FAILS the
  physics.** The model does not hold diamond silicon as the stable phase,
  so amorphization depth is set by a propagating transformation front
  rather than by the ion range -- no thermostat or fluence tuning can fix
  that. DPA-3.1-3M passes the same gate and runs today via `.pth`.
- **Scope NOT covered:** cascade depth under DPA-3.1 (that is Tier 1, not
  yet run); no oxide screened (Tier-0 is per material AND per model);
  the `.pth` runs are 100-step NVE benchmarks, not cascades; harnesses
  still live under `$CPG_SHARE`, not `install/tests/`; DPA-3.1 has no
  `.pt2`, so it runs 2.47x slower than it could until the `network.py`
  patch in `dev/notes/mlip-cascade-integration.md` is applied.

## T-22 — jobs 16733423 (crashed) + 16795220 (stands) — 2026-08-25

*(Tier-1 energy scan: bombardment energy -> reachable damage depth,
under DPA-3.1-3M.)*

**Question.** How deep does a single Ar impact reach into DPA-3.1
silicon as a function of energy, and which energy brackets the 7 Å
`expected_activated_depth` the build sizes slabs against?

- **As-run scripts:** `install/tests/t22_energy_scan/`
  (`energy_scan.slurm`, `run_energy_scan.py`, `analyze_energy_scan.py`).
- **16733423 (first attempt, 12 tasks, RETRACTED as a result).** All
  twelve cascades RAN; every task then died in reporting on
  `AttributeError: 'CascadeOutcome' object has no attribute 'verdict'`.
  Activation became cascade-only in the 2026-08-08 re-arch and the §3.5
  gate moved to the bond flow, so `activate_one_half` returns a bare
  `CascadeOutcome`; the harness still reached for a gate verdict. The
  physics was fine and nothing was reported. Structures preserved under
  `$SCRATCH/jobs/bulk_si/t22_attempt1_16733423/`.
- **16795220 (13 tasks, ALL COMPLETED, 31-54 min each).** 12 energies
  x 1 impact x 1 seed, plus a zero-impact NULL CONTROL. Si(001),
  1960 atoms, 745 Å², cut on DPA-3.1's own working lattice
  (a = 5.5147 Å, DESIGN §2.2). Judged FROM THE STRUCTURES:

  | E (eV) | vacated | above null | reach (Å) |
  |---|---|---|---|
  | null |  28 |  0 |  0.00 |
  |   20 |  30 |  2 |  0.00 |
  |   30 |  30 |  2 |  2.76 |
  |   40 |  36 |  8 |  4.14 |
  |   50 |  35 |  7 |  2.76 |
  |   60 |  45 | 17 |  4.14 |
  |   70 |  44 | 16 |  5.51 |
  |   85 |  42 | 14 |  2.76 |
  |  100 |  53 | 25 |  6.89 |
  |  120 |  49 | 21 |  6.89 |
  |  140 |  51 | 23 |  6.89 |
  |  170 |  72 | 44 | 19.30 |
  |  200 | 104 | 76 | 13.79 |

  - **Zero sputtering at every energy** — survivors 1960/1960
    throughout, so up to 200 eV the upper bracket is NOT set by atom
    loss.
  - **The null earns its place.** 28 of the ~30 sites "vacated" at
    20 eV are the pre-relax's own surface settling, so the low-energy
    vacancy COUNT is almost entirely floor. Its subsurface reach is
    exactly 0.00 Å, so REACH is uncontaminated: relaxation empties
    surface sites only, and any nonzero reach is genuine damage.
  - Reach quantizes onto multiples of 1.379 Å = a/4, the Si(001)
    plane spacing, as vacated lattice sites must.
- **Run-to-run scatter, from the two runs as an unintended replicate**
  (same seed 12345, same energies; they differ only by `caf7208`'s
  relax timestep and GPU nondeterminism):

  | E (eV) | attempt 1 reach | 16795220 reach |
  |---|---|---|
  |  20 |  1.38 |  0.00 |
  |  30 |  2.76 |  2.76 |
  |  40 |  2.76 |  4.14 |
  |  50 |  4.14 |  2.76 |
  |  60 |  2.76 |  4.14 |
  |  70 |  4.14 |  5.51 |
  |  85 |  4.14 |  2.76 |
  | 100 |  6.89 |  6.89 |
  | 120 |  6.89 |  6.89 |
  | 140 |  6.89 |  6.89 |
  | 170 | 11.03 | 19.30 |
  | 200 | 11.03 | 13.79 |

  Below 100 eV the two agree to ±1 lattice plane (±1.4 Å). At
  100/120/140 eV BOTH runs give 6.89 Å — the only stable plateau in
  the scan. At 170/200 eV they diverge by up to 8 Å, which is what
  single-seed sampling of a CRYSTALLINE target looks like when an ion
  finds a channel.
- **Verdict: the bracket is 100-140 eV.** Reach there is reproducibly
  6.89 Å against the spec's `expected_activated_depth = 7.0 Å`
  (`dev/templates/study_spec.toml:295`), and 100 eV is the cheapest
  point on that plateau. Below 100 eV reach falls short and is
  seed-noisy; above 170 eV it is deep, erratic, and would drive damage
  past the skin the build sizes for.
- **Scope NOT covered:** SKIN DEPTH — this is REACH from ONE impact,
  which bounds the skin but is not it; amorphization is cumulative
  (the classical sweep used 15-44 impacts) and a dosed run at 100 eV
  is the next measurement. The disorder-profile half of the analyzer
  reports NO result: its zero-impact null runs no MD (the relaxation
  is inside the impact loop) so it sits near 0 K against ~1 ps of warm
  MD, and differencing the two measures temperature — it reported a
  30-39 Å "skin" at 20 eV before that was caught. Single seed
  throughout; no oxide; DPA-3.1 still `validated=False`, and this scan
  does not change that (the §3.5 gate is a bond-flow measurement).

## T-23 — job 16816216 — 2026-08-26

- **What ran:** three of T-22's scanned points re-run in MOVIE MODE —
  the cascade recording frames — so the bombardment can be watched.
  `install/tests/t22_energy_scan/energy_scan_movie.slurm`, array tasks
  2/7/11 = 40/100/200 eV, `run_energy_scan.py <task> --movie`. Same
  model (DPA-3.1-3M `.pth`, out-of-process), same 1960-atom cell, same
  seed 12345, same durations as job 16795220. Only the recording
  differs. This is NOT a new measurement.
- **Result: three trajectories, 56 frames each, 3.2 MB each.**

  | E (eV) | frames | atoms @ f0 | reach (Å) | node |
  |-------:|-------:|-----------:|----------:|:-----|
  |     40 |     56 |       1961 |      4.14 | g029 |
  |    100 |     56 |       1961 |      5.51 | g018 |
  |    200 |     56 |       1961 |     13.79 | g020 |

  1961 at frame 0 is 1960 Si plus the argon, so both species are
  present in the first frame and a species-coloured render works. The
  count drops to 1960 at the cleanup, which strips the projectile.
- **56 frames, not ~200, and that is the halt doing its job.** The
  cascade is capped by `fix cascade_halt` at 0.5 ps, which fired on
  step 5130 (value 0.5008); with the 500-step relax that is 5630 steps
  and, at `MOVIE_FRAME_STRIDE = 100`, 56 frames. At 20 fps that is
  under three seconds of video. Lowering the stride is the knob.
- **Frames are evenly spaced in STEPS, not in time.** `fix dt/reset`
  floats the step between 1e-5 and 0.1 ps, so the frames sample the
  violent opening densely and the cooling tail sparsely. Legible as
  slow-motion; useless for reading velocity.
- **Reproducibility note: 100 eV came back 5.51 Å, not the 6.89 Å both
  earlier runs gave.** 40 eV (4.14) and 200 eV (13.79) match job
  16795220 exactly. This run landed on H100s where both earlier ones
  used other hardware, and recording frames does not perturb the
  dynamics — so this is the same single-seed scatter T-22 already
  documented, now visible at a point that had looked stable across two
  runs. It does not overturn the 100-140 eV bracket, which rests on a
  plateau of three energies, but it does weaken "6.89 Å reproducibly"
  to "6.89 Å in two runs of three". Seeds at the chosen point are the
  measurement that would settle it.
- **A reporting bug recurred and cost nothing this time.** Every task
  exited 1 on the `SCANMOVIE` line: it spelled the dump's name out by
  hand as `..._activation_a.dump` when the subprocess activate names
  the stage `activate_a`. The cascades, the frames and every
  `SCANRESULT` line were already written. Fixed by asking
  `stage_dump_file` for the path instead of guessing it, and by
  reporting a missing movie as `frames=0` rather than raising — a
  report must not be able to kill a run that already has its result.
  This is trap 5 of the T-22 README, committed a second time.
- **Scope NOT covered:** no physics. Nothing here is evidence about
  reach, skin, dose, or the gate beyond what T-22 already recorded,
  except the 100 eV scatter noted above. No render was produced — the
  dumps are for rendering elsewhere.

## T-25 — jobs 16822060 (failed, diagnostic) + 16822116 (stands) — 2026-08-26

*(Option (a) of the A′ decision: the deepmd-kit 3.2 bundle as SABSIM's
IN-PROCESS engine, so `pair_style deepmd` can load a DPA `.pth` — and
later the ALF-trained committee — inside the interactive press/pull.)*

**Question.** Can SABSIM's own `LammpsEngine` (the Python binding, one
persistent instance per rank) run the universal DPA-3.1-3M model, on the
GPU, under the bundle's OpenMPI, with no LAMMPS compiled?

- **What was built.** No compile: the bundle is a complete conda
  environment (Python 3.12, OpenMPI 5.0.10 + mpi4py, a LAMMPS 2024.08.29
  Python binding, the deepmd pair style as the plugin
  `lib/deepmd_lmp/dpplugin.so` with a PyTorch/CUDA backend). A venv
  `virtual_envs/sabsim-dp3` layered on the bundle's python
  (`--system-site-packages`; pymatgen + pytest + sabsim editable on top)
  and a module `cpg_lammps_conda/deepmd-kit-3.2.0b0` (bundle bin/lib on
  the path, `DEEPMD_LMP_PLUGIN` set, `LAMMPS_PLUGIN_PATH` unset — the
  explicit-`plugin load` discipline). Load the module FIRST, then
  activate the venv.
- **As-run scripts:** `install/tests/t25_inprocess_dp3/`
  (`t25_inprocess_dp3.slurm`, `probe_inprocess_dp3.py`). The probe uses
  the real pieces: `bulk_type_map`/`write_bulk_data` for a 216-atom Si
  block, `deepmd_model`, `bulk_relax_commands`, `LammpsEngine`; then
  200 steps of NVE at 300 K, judged on total-energy drift.
- **16822060 (FAILED — a real bug, fixed).** The 1-rank and 2-rank
  probes both died in the NVE run with `Lost atoms: original 216
  current 198`. The log showed why: the box/relax minimize had collapsed
  the cell from 4323 to 628 Å³ at −1.21 → −2.48 eV/atom. Cause:
  `deepmd_model` emitted `pair_coeff * *` with NO element list, which
  maps LAMMPS type 1 to the model's FIRST element — hydrogen, for a
  118-element universal model. Silicon was simulated as hydrogen.
  Harmless for the one-element `graph.pb` this helper was written for;
  fatal here. Fix: `deepmd_model(model_path, type_map)` now writes the
  elements in type order on the `pair_coeff` line (commit with this
  entry). An earlier 16822052 failed on a PATH-order slip (module loaded
  after the venv, so `python` lacked sabsim) — fixed in the slurm.
- **16822116 (PASS, g040 L40S, 1 rank then 2 ranks under
  `srun --mpi=pmix`).** Verbatim:

  ```
  T25RESULT rank=0 ranks=1 atoms=216 a=5.5164 etot0=-1159.8996 etot1=-1159.8968 drift_eV_per_atom=1.30e-05
  T25RESULT rank=1 ranks=2 atoms=216 a=5.5164 etot0=-1159.8996 etot1=-1159.8968 drift_eV_per_atom=1.30e-05
  T25RESULT rank=0 ranks=2 atoms=216 a=5.5164 etot0=-1159.8996 etot1=-1159.8968 drift_eV_per_atom=1.30e-05
  === T-25 exit 1rank=0 2ranks=0 ===
  ```
  Plugin registered in-process, model on GPU 0, box relaxed to
  a = 5.5164 Å (the out-of-process derivation gave 5.5147 — same
  physics, a different minimizer stopping point), −5.37 eV/atom, and
  1.3e-5 eV/atom drift over 200 NVE steps. The two ranks agree to every
  printed digit, so the domain decomposition under the bundle's MPI is
  sound.
- **Verdict.** Option (a) is DONE as an environment, not a build: the
  bond stage can run a DPA `.pth` in-process by switching the install to
  the `sabsim-dp3` venv + this module. **Scope NOT covered:** the real
  bond stage (heal → gate → press → pull) has not yet run under it —
  that is the C bond job, next; `graph.pb` (TF backend) under the
  3.2 plugin is untested; larger cells / multi-GPU untested.

## T-26 — job 16823583 — 2026-08-26

*(The bootstrap's first slice: `sabsim bootstrap generate
--skip-collection2` builds Collection 1 of the silicon recipe for real.)*

**Question.** Does the recipe → Collection-1 path run end to end on a
GPU node under DPA-3.1-3M out-of-process, and do the two dynamic
families produce what they claim (a real amorphous network; warm
crystals)?

- **As-run:** `install/tests/t26_bootstrap_generate/t26_generate.slurm`
  from `jobs/bootstrap_si/` (recipe.toml = the template with absolute
  study/job/reference paths; deployment.toml with `[usage.label]`).
  H100 g032, 28 min 31 s, exit 0.
- **Result, judged from `structures.extxyz`:**

  ```
  T26RESULT family=bulk count=1 atoms=64
  T26RESULT family=melt_quench count=10 atoms=64
  T26RESULT family=rattle count=10 atoms=64
  T26RESULT family=strain count=18 atoms=64
  T26RESULT family=surface count=1 atoms=8
  T26RESULT family=warm_npt count=10 atoms=64
  T26RESULT family=warm_nvt count=10 atoms=64
  ```
  Lattice derived at a = 5.5164 Å (T-25's in-process value; the study
  pipeline's derivation gave 5.5147). The melt-quench frames were
  checked for disorder as PSEUDOCODE §11.1 demands: first quench frame
  mean coordination 4.31 with 56 % of atoms off four-fold, last frame
  4.22 / 20 % — an amorphous network, not a rattled crystal.
- **One defect, fixed in the same commit:** the clean surface came out
  as a single 8-atom column (the primitive Si(100) slab cell, 3.9 Å
  wide) — every atom inside its own periodic image at a 6 Å cutoff. The
  surface family now carries a required `lateral_repeat` (template: 3,
  → 72 atoms, 11.6 Å wide). The 8-atom surface stays in T-27's label
  set as one plumbing task; the next generate replaces it.
- **Scope NOT covered:** Collection 2 (needs a member run with
  `--dump-visuals`; C ran without), labels (T-27), any oxide phase.

## T-27 — jobs 16823627 (cancelled) + 16823654 (array 0-51, stands) — 2026-08-26

*(The bootstrap's direct VASP labeller on the T-26 structures: the first
real labels, and the first real cost numbers, of the lean recipe.)*

- **As-run:** `sabsim bootstrap label recipe.toml --rc deployment.toml`
  from `jobs/bootstrap_si/`, which wrote 52 label directories and ONE
  job array under the scratch mirror
  (`.../bootstrap/si-lean-v0/labels/`); `sbatch` of that array;
  `sabsim bootstrap harvest recipe.toml` afterwards. 52 tasks = bulk 1 +
  strain 10 (real k-spacing, `vasp_std`) + melt_quench 10 + rattle 10 +
  surface 1 + warm_nvt 10 + warm_npt 10 (Γ only, `vasp_gam`), module
  `vasp/6.4.2_gcc_12.3.0_openmpi_4.1.5`, 32 ranks, one node each.
- **16823627 — CANCELLED after 11 min, a real bug.** VASP reported
  "32 mpi-ranks, with 32 threads/rank": the site build spawns an OpenMP
  thread per core in every rank, 1024 threads on 64 cores, and no SCF
  step had finished. The array writer now pins `OMP_NUM_THREADS=1`
  (commit 28d8085).
- **16823654 — 52/52 COMPLETED, 52/52 converged, 0 dropped.** Per-task
  VASP wall time 12–21 s (bulk 21.4, melt-quench 15–20, strain 12.6,
  warm 18.0). Judged from `labels.extxyz`:

  ```
  T27RESULT family=bulk         n= 1 atoms= 64 E/atom=[-5.319,-5.319] eV max|F|=0.00 eV/A
  T27RESULT family=melt_quench  n=10 atoms= 64 E/atom=[-5.005,-4.599] eV max|F|=4.55 eV/A
  T27RESULT family=rattle       n=10 atoms= 64 E/atom=[-4.978,-4.818] eV max|F|=17.08 eV/A
  T27RESULT family=strain       n=10 atoms= 64 E/atom=[-5.319,-4.685] eV max|F|=0.85 eV/A
  T27RESULT family=surface      n= 1 atoms=  8 E/atom=[-2.706,-2.706] eV max|F|=0.64 eV/A
  T27RESULT family=warm_npt     n=10 atoms= 64 E/atom=[-5.234,-5.213] eV max|F|=3.52 eV/A
  T27RESULT family=warm_nvt     n=10 atoms= 64 E/atom=[-5.238,-5.203] eV max|F|=2.81 eV/A
  ```
  Sanity: the relaxed bulk sits lowest with zero force; the amorphous
  quench frames are 0.3–0.7 eV/atom above it and cool toward it along
  the quench; the ±10 % strains reach +0.63 eV/atom; the 0.15 Å rattle
  produces forces up to 17 eV/Å (large — a smaller amplitude is worth
  considering for the next recipe); the 8-atom surface column is the
  T-26 defect (two faces per eight atoms) and is dropped from the next
  set by the lateral_repeat fix.
- **Cost:** the whole lean Collection-1 label set is ~15 node-minutes
  of VASP. The budget question is therefore entirely the interface
  sub-cells (~150–250 atoms, Γ only), not these.
- **Note for the reader of `labels.extxyz`:** ASE stores the energy and
  forces as calculator results, so read them with
  `get_potential_energy()` / `get_forces()`, not from `info`.
- **Scope NOT covered:** Collection 2 (needs the dumped member run);
  the audit block; any oxide.
