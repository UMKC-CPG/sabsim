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
