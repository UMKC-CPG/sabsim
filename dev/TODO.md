# Task List

> **Document hierarchy:** Tasks are organized by the level of the design
> chain they affect. Each item should cite the relevant document section.

---

## VISION

<!-- Tasks related to goals and principles. -->

- [ ] Bond-outcome metric — now defined as a work of separation per
      unit area (J/m2), commensurable with the Maszara blade test and
      calibrated on relative trends / ratios, not absolute values (see
      `VISION.md` goal 4, `ARCHITECTURE.md` §2.3). v1 runs BOTH the
      Si/SiO2 pair and a Si/Si same-material reference so the relative
      ratio can actually be formed (decided 2026-07-08). The *form* of
      the pass criterion is settled by `DESIGN.md` §7.4 (2026-07-09):
      the ratio against the experimental ratio within the combined
      uncertainty (systematic errors common to both systems cancel to
      first order, which is why the ratio is the trustworthy quantity),
      plus a loose absolute order-of-magnitude bracket that tests only
      the plumbing — a ratio stays correct when both numbers are off by
      the same factor, which is what a unit bug produces. Residual: pin
      the exact SAB-regime (not fusion-bonding) reference numbers for
      Si-Si and Si-SiO2; set the significance level and the bracket
      width; and treat the two works of separation as **correlated**
      when propagating the ratio's uncertainty, since assuming
      independence would throw away the very cancellation that makes the
      ratio worth testing (`VISION.md` goal 4 and principle 5).
- [ ] Define what "characterize the bond" (step 8) actually outputs,
      and how those numbers turn into experimental advice
      (`VISION.md` goal 4). Headline output now decided — a work of
      separation per area; still open is the fuller set of measures and
      how they convert into a concrete recommendation.

---

## ARCHITECTURE

<!-- Tasks related to layout, modules, build. -->

- [ ] **Clean deployment-environment rebuild (`sabsim_dev`) — the ROOT fix
      for the engine failures** (opened 2026-07-31). The hand-built env had
      NO recorded recipe AND a fatal flaw: sabsim loads LAMMPS in-process
      (`import lammps`), and a competing conda `liblammps.so` (glibc 2.34)
      was loaded via the Python's `DT_RPATH=$ORIGIN/../lib` (searched BEFORE
      `LD_LIBRARY_PATH`), dying on the glibc-2.28 nodes (probe 15520412).
      RECIPE in `install/` (DRAFT): `environment.yml` (conda base, NO
      lammps package; mpi4py FROM conda) + `build_venv.sh` (venv — pinned
      ase/pymatgen/parsl, editable ALF + sabsim). Both BUILT + verified
      2026-07-31 (GPU builds land with `CONDA_OVERRIDE_CUDA=12.9`; venv +
      editable installs OK). MPI RESOLVED: the stack runs on CONDA OpenMPI
      5.0.10 (deepmd forces it, the python RPATH loads it), and it DRIVES
      THE INFINIBAND FABRIC via UCX at ~12 GB/s (job 15551674) — no site
      OpenMPI needed. Launcher = `srun --mpi=pmix` / `mpirun` after
      `unset SLURM_MEM_PER_NODE SLURM_MEM_PER_CPU SLURM_MEM_PER_GPU` (the
      allocation exports those mutually-exclusive — that was the whole
      multi-node blocker). REMAINING: (a) build LAMMPS from SOURCE on the
      cluster (el8-native) against conda OpenMPI 5.0.10 -> venv, BOTH the
      classical engine and the deepmd-2024.08.29 engine (the site
      `cpg_lammps` 4.1.5 modules DON'T fit — they mismatch conda 5.0.10);
      (b) a `sabsimrc.dev` (activate sabsim_dev + venv); (c) validate
      engine + activate + bond, THEN retire the old env + repoint the rc.
      SUBSUMES the multi-node and engine-acquisition items below. Recorded
      in `ARCHITECTURE.md` §4.1.
- [ ] **Restore the trimmed LAMMPS packages when a study needs them**
      (2026-07-31, Paul flagged). The first conda-toolchain build
      (`install/build_lammps.sh`) cut `ML-HDNNP`/`DOWNLOAD_N2P2`,
      `VORONOI`/`DOWNLOAD_VORO`, and `WITH_PNG`/`WITH_CURL` to isolate a
      clean core build. None are on the v1 SW/ZBL + deepmd path, but
      re-add them (dep -> `environment.yml`, flag -> `build_lammps.sh`;
      `libpng`/`libcurl` for PNG/CURL, n2p2/voro self-download) if a later
      study needs HDNNP potentials, Voronoi analysis, or image/curl
      output. Also noted at the package list in `build_lammps.sh`.
- [x] **RESOLVED — the OpenMPI-5 sysadmin request is NOT needed**
      (2026-07-31). Paul's contingency idea. The fabric test (job 15551674)
      showed conda OpenMPI 5.0.10 + UCX ALREADY drives this cluster's
      InfiniBand fabric at ~12 GB/s (UCX picks `rc_mlx5`) — a site-compiled
      OpenMPI 5 would buy nothing. And the op_pt collision fear is moot: the
      whole stack is ONE MPI (conda 5.0.10), so there is nothing for it to
      collide with. Do not file the request.
- [x] **RESOLVED — multi-node launch works; the blocker was a SLURM env
      conflict, not the interconnect** (2026-07-31). Not conda-vs-site MPI
      either: the allocation exports `SLURM_MEM_PER_NODE` and
      `SLURM_MEM_PER_CPU` together, and the nested `srun` that OpenMPI 5's
      PRRTE uses to launch its per-node daemon aborts on "mutually
      exclusive" (job 15551533). FIX: `unset SLURM_MEM_PER_NODE
      SLURM_MEM_PER_CPU SLURM_MEM_PER_GPU` before launch — then BOTH
      `srun --mpi=pmix` and `mpirun` span nodes cleanly (job 15551674, 2
      nodes, ~12 GB/s over the fabric). Also disproves the old
      "srun --mpi=pmix fails / munge" memory: pmix (pmix_v2) is offered and
      works. Bake the unset into the generated run scripts
      (`src/sabsim/deploy/prepare.py`).
- [ ] **Engine acquisition — adopt the CPG LAMMPS module scheme; DeePMD
      needs a dedicated site build (de-risked 2026-07-28).**
      SUPERSEDED for the `sabsim_dev` env (see the rebuild item above): the
      site `cpg_lammps` modules are OpenMPI 4.1.5 and MISMATCH the conda
      OpenMPI 5.0.10 that env forces in-process, so LAMMPS is instead
      source-built against conda 5.0.10. The DeePMD build de-risking below
      still applies to whatever LAMMPS build hosts the plugin. Today sabsim
      imports a conda-vendored LAMMPS (`virtual_envs/sabsim`), which on a
      real compute node links a CONDA OpenMPI (not the site interconnect)
      and whose sibling `mamba/envs/sabsim/lib/liblammps.so` won't even
      load on the nodes (needs GLIBC_2.29; nodes are 2.28). Imago already
      solved this: a CPG-owned modulefile tree at `/cluster/VAST/
      rulisp-lab/cpg/modulefiles/cpg_lammps/22Jul2025.lua` builds LAMMPS
      with the SITE toolchain (gcc 12.3.0 / OpenMPI 4.1.5, RPATH-baked,
      glibc <= 2.14, no libpython) so it runs on the real interconnect
      from any/no conda env and sets LAMMPS_POTENTIALS / PATH / PYTHONPATH
      / LD_LIBRARY_PATH itself. A consumer selects it by TWO `md.init`
      lines (`module use ... && module load cpg_lammps`), zero code — the
      scheme is built for MULTIPLE versions (`family("lammps")` makes them
      exclusive). ADOPT it for sabsim's compute jobs: fixes the conda-MPI
      mismatch and the stale `LAMMPS_POTENTIALS` (see the resume-smoke
      CODE item) in one move; the classical SW-Si stand-in — all we run
      today — works on it. LANDED in `ARCHITECTURE.md` §4.4 (engine
      acquisition, beside the §4.1 Engine seam); the deployment
      `deployment_rc.toml` `[usage.bond-md]` wiring is the code half, still
      open. DeePMD DE-RISKING VERDICT:
      the prebuilt conda deepmd plugin CANNOT be loaded into the site
      build — three layers, last one fatal: (1) glibc fine; (2) CXXABI
      fixable (conda TF needs gcc >= 13 libstdc++, site pins 12.3 —
      LD_PRELOAD clears it, LD_LIBRARY_PATH does not: site lmp pins
      libstdc++ via DT_RPATH); (3) HARD LAMMPS-ABI mismatch — deepmd-kit
      3.1.3 is built against `lammps 2024.08.29`, the site build is
      22Jul2025, and `utils::bounds` gained a trailing `int` between them,
      so the plugin's symbol is undefined. To run DeePMD we need a MATCHED
      site build: LAMMPS 29Aug2024 + the deepmd interface compiled as a
      pair, site toolchain (and gcc >= 13 for the TF/torch backend),
      published as a second `cpg_lammps/2024.08.29-deepmd` module — one
      `md.init` line for sabsim, no code change. DeePMD BUILD DONE
      2026-07-29: `cpg_lammps/2024.08.29-deepmd` built + installed +
      verified on a compute node (`module load` -> `plugin load ${dp}` ->
      `pair_style deepmd` registers). The LIGHT path worked — build LAMMPS
      29Aug2024 (proven `build-lammps.sbatch` recipe, only the version
      changed) to ABI-match the prebuilt conda deepmd plugin; NO deepmd
      rebuild. ABI proven by symbol: `utils::bounds<int>(...,Error*)` no
      trailing int (29Aug2024) vs `...,Error*,int` (22Jul2025). Runtime:
      LD_PRELOAD conda libstdc++ (CXXABI_1.3.15) + `variable dp getenv
      DEEPMD_LMP_PLUGIN; plugin load ${dp}`. Consuming it from sabsim
      (emit the two `plugin load` lines in the deepmd force-model block,
      select the module in `deployment_rc.toml`) is the remaining wiring,
      still gated on the trained MLIP.
      ENV NOTE (2026-07-29, running the resume smoke): the `cpg_lammps`
      modulefile is CORRECT — its `prefix` IS versioned (Lua concatenates
      `".../programs/lammps/"` with `"22Jul2025-gcc12.3.0-ompi4.1.5"`
      across two lines), and it sets `LAMMPS_POTENTIALS` to the real
      versioned `share/lammps/potentials` (where `Si.sw` lives). The bug
      is only in the JOB scripts: `jobs/*/slurm` hardcode
      `LAMMPS_POTENTIALS=.../programs/lammps/share/lammps/potentials` — a
      versionless path with nothing under it, so a hand-run fails "cannot
      open Si.sw". FIX when adopting the module scheme: drop the hardcoded
      export and `module load cpg_lammps`, which sets it right. (Ran the
      smoke by pointing the env at `.../lammps/current/share/lammps/
      potentials` directly.)
      LANDED 2026-08-04 — PIVOTED to the CONDA-DERIVED engine as primary:
      the code needs mpi4py comm-sharing, which the site OpenMPI-4.1.5
      build cannot provide (adopting it would need a site-4.1.5 mpi4py, so
      "adopt" doesn't avoid a build). Both engines source-built against
      conda OpenMPI 5.0.10 and published as `cpg_lammps_conda/{22Jul2025,
      2024.08.29-deepmd}` modules (NO LD_PRELOAD — conda libstdc++
      suffices); `deployment_rc` + `prepare.py` wired; `programs/lammps/
      current` repointed; `ARCHITECTURE.md` §4.1/§4.4 reconciled. Validated
      F1/E1/E2/E3/E4/E5/build/feat ALL PASS
      (`install/tests/{MATRIX,LEDGER}.md`), incl. a real deepmd 2.2.10/TF
      `graph.pb` running on the 3.1.3 plugin (job 15686597) and a full
      `prepare`->activate green run (job 15703266). Site `cpg_lammps` stays
      a documented fallback.
      BOND 6a DONE 2026-08-05 (job 15724578, T-6A-BOND): the `bond` job kind
      ran end-to-end on the GPU partition through the wired deployment path
      — generated script -> GPU alloc -> deepmd engine module -> srun venv
      -> RE-READ the activate job's `assembled_pair` (reused E5's, activate
      not re-run) -> press/settle/pull -> wrote `pull_results`. On the
      CLASSICAL stand-in (6a = plumbing); the deepmd force model through the
      pipeline is 6b (still open — needs the bootstrap or a resolve_potential
      override onto a real .pb). Surfaced + FIXED a writer gap: prepare
      emitted no `--gres`, so added a `gpus_per_node` field to `[usage.*]`
      (sibling of #5's memory knob) — `deploy/config.py` + `prepare.py`
      (`--gres=gpu:N` only when >0, plus a login-node GPU-ceiling check),
      template (0/4/0), and the chain (PSEUDOCODE §14.1/§14.4/§14.5, DESIGN
      §10.6). 293 tests.
      ENV RENAMED 2026-08-05 (#7 DONE, T-RENAME job 15726178): the whole
      deployment env was renamed `sabsim_dev` -> `sabsim` (shorter everyday
      name; `ssabsim` now launches it, `ssabsim_dev` retired). Removed the
      old dead `sabsim` env, cloned `sabsim_dev` -> `sabsim`, rebuilt the
      venv, `patchelf`-ed the 4 engine binaries' RPATH (`envs/sabsim_dev/
      lib` -> `envs/sabsim/lib` — valid: exact clone, byte-identical libs),
      repointed the modulefiles (tracked + published) + recipe + docs.
      Validated: BOTH engines load + run a real MD step under `sabsim`
      (classical -933.1 eV, deepmd -1169.3 eV).
      6b/#8 PLUMBING DONE 2026-08-06 (LEDGER T-8, jobs 15876062 activate +
      15876145/243/342/690 bond): the DeePMD force model DRIVES the
      pipeline's relax + press on the GPU end-to-end (relax -> scissors ->
      press wired via `contact_relax_commands`/`scissors_commands`), and
      scissors is verified (fires/cuts/clamps). A clean GREEN
      (settled_reference + pull_results) is DEFERRED: all four bond runs
      failed on OOD artifacts — the bulk Si model corrupts the amorphized
      surfaces (relax self-heats ~500 K), which no gap measure survives.
      Real fix = the trained COMMITTEE / per-slab re-anneal under DeePMD
      (DESIGN §3.4), after which the TEMPORARY OOD relax scaffold is
      removed (its own TODO above). Provenance still says
      `classical-stand-in` (resolve_potential unwired).

- [ ] **REMOVE the TEMPORARY OOD relax scaffold once the seam is green
      (CODE).** `commands.contact_relax_commands` currently does damped,
      displacement-CAPPED dynamics + a reflecting wall INSTEAD OF a
      minimize, purely so a not-yet-in-distribution model (the first bulk
      Si `.pb` run on classically-amorphized surfaces) does not eject
      atoms ("Lost atoms" in the relax, bond job 15876145). This is
      SCAFFOLDING to exercise the classical->trained PLUMBING, NOT the
      intended physics. The real fix is activation under the trained
      COMMITTEE (DESIGN §3.4, the deferred per-slab re-anneal under
      DeePMD): once surfaces are in-distribution, the cap/damp/wall come
      out and a normal relax suffices. Delete `_RELAX_DISPLACE_CAP`, the
      nve/limit + wall/reflect dance, and revert to a plain minimize (or
      drop the joint relax entirely if the per-slab re-anneal replaces it)
      when task #8's seam test is proven. Do NOT build on this.

- [x] **Deployment: add a MEMORY knob to `[usage.*]` (CODE) — DONE
      2026-08-05.** E5 (job 15697360) OOM-killed the activate cascade on
      the partition default; `deployment_rc`/`prepare.py` emitted no
      `#SBATCH --mem`, so E5 only passed with a hand-added `--mem=96G`
      (actual peak was ~306 MB, T-E5-ACTIVATE). LANDED as a full
      design-chain change, not just code: a `Memory { value, unit }` record
      + `_require_memory` loader in `deploy/config.py` (units reduce to MB,
      SLURM's `--mem` unit; unknown unit is a loud stop), a `memory` field
      on `UsageBlock`, `_slurm_memory` in `prepare.py` emitting
      `#SBATCH --mem` (whole GB/TB kept verbatim as `16G`, else MB), the
      three `[usage.*]` blocks in `dev/templates/deployment_rc.toml`
      (activate 16 GB / bond 32 GB / analyze 8 GB — comfortable ceilings,
      NOT tuned), and the propagation up the chain (`PSEUDOCODE.md` §14.1
      UsageBlock + §14.5 directives, `DESIGN.md` §10.6 sibling paragraph to
      walltime/ranks). 291 tests pass (4 new: missing/bare-memory rejection,
      unit reduction, unknown-unit stop). Verified a generated bond script
      carries `#SBATCH --mem=32G`. NOTE: a machine-local rc now REQUIRES a
      `memory` field per usage block (no silent default) — regenerate or
      hand-add it to any existing `deployment.toml` before `prepare`.

- [ ] **General-triclinic support — lift the orthogonal-cell boundary
      (documented 2026-07-29 in `ARCHITECTURE.md`).** The facing-pair
      builder reduces any REMOVABLE in-plane tilt to zero
      (`slab_builder.orthogonalize_in_plane`), which lands every v1 Si and
      SiO2 face on an orthogonal cell — but a genuinely oblique face (a
      hexagonal surface, a non-reducible triclinic cell) stays oblique,
      and the activation gate's minimum-image assumes an ORTHOGONAL cell
      (scalar per-axis wrapping, `driver/activation_gate.py`), so it would
      mis-measure such a face. To admit general lattices, replace that
      scalar min-image with a full triclinic one (wrap in fractional
      coordinates against the cell matrix, or the LAMMPS reduced-tilt
      convention). NOT needed for v1's material pairs; this is the single
      known blocker to running an arbitrary crystal face. See the
      `orthogonalize_in_plane` note further down and the restart round-trip
      that motivated the reduction (resume-smoke item).

<!-- Pre-DESIGN priority cluster. These four holes are load-bearing for
the DESIGN level and should be resolved before DESIGN.md is filled in.
Raised in the 2026-07-03 refine of VISION + ARCHITECTURE; the first two
were not previously tracked anywhere. -->

- [ ] Quality-gate architecture — partly resolved (2026-07-07). Now
      split into two checks in `ARCHITECTURE.md` §2.3: a potential-
      quality gate (stiffness, surface energies vs VASP / experiment)
      and a separate bond-debond outcome metric (work of separation per
      area, Maszara-anchored, relative). In v1 both only report.
      Largely resolved at DESIGN level by `DESIGN.md` §7 (2026-07-09):
      the properties are enumerated (§7.2), the pass thresholds became
      significance statements rather than constants (§7.5), and the
      potential gate turns out to run in **two parts at two times** —
      its bulk/surface half must precede the structure builder, which
      §2.2 makes a consumer of the potential's relaxed lattice
      constants, while its interface half cannot run until a
      press-then-pull trajectory exists. Residual: decide which module
      owns each check and **stores its reference data**, and whether the
      reference set is per-material-pair
      (`ARCHITECTURE.md` §2.3, §3; `VISION.md` goal 4 and principle 5).
- [ ] Inner/outer loop coupling — DEFERRED by decision (2026-07-07).
      ALF is centered on MLIP generation, agnostic to the application,
      so the coupling is NOT about application knobs: the outer loop
      steers ALF by supplying training systems that populate the
      bond-debond application region where the potential is weak. Still
      open — which physical parameters are worth iterating, decided with
      collaborators under finite resources (candidates: composition,
      dopant, activation level, pressure, temperature, Miller faces).
      Revisit then (`ARCHITECTURE.md` §2.3 step 2, §3; `VISION.md`
      principle 5).
- [ ] Outer-loop convergence — DEFERRED by decision (2026-07-07), tied
      to the loop-coupling item above. Near-term goal is narrower: get a
      SINGLE pass of the outer loop working end to end first; only then
      design the repeat logic (weakness-to-new-data mapping, iteration
      budget, non-convergence exit) (`ARCHITECTURE.md` §3; `VISION.md`
      principle 5).
- [x] Member-specification knobs — RESOLVED for v1 (2026-07-07): the knob
      set is now split in `ARCHITECTURE.md` §2.3 into material knobs
      (crystal structure + one surface face per wafer, material
      identity) and protocol knobs (activation species, activation
      energy AND dose, and press / separate load, depth, duration, and
      speed). v1 freezes every protocol knob to one value; iterating
      them is the deferred outer-loop work. Follow-on: settle the exact
      settings-file shape at DESIGN time.

<!-- Second pre-DESIGN priority cluster. Surfaced in the 2026-07-08
review of VISION + ARCHITECTURE before opening DESIGN.md. These are
STRUCTURAL: each one determines what a module IS or what data crosses a
seam, so resolving one wrong would mis-shape DESIGN itself. The three
[STRUCTURAL] items are the "could send DESIGN down a wrong path" set;
[STRUCTURAL 4] is the step-5 lattice hole that the review's linkage
table also marked close-before-DESIGN, kept here so it is not lost. The
three [RISK] items do NOT block DESIGN structure but must be on record
so they are not discovered late (two touch non-negotiable goals). -->

- [x] [STRUCTURAL 1] Bootstrap coverage (was: bootstrap + one-vs-many).
      One half now resolved, one half open.
      **1a one-vs-many — RESOLVED (2026-07-08):** the MLIP is ONE
      multi-species potential over the union of the pair's species. A
      per-material potential cannot even be assigned at an intermixed
      interface, let alone describe the cross-species bonds there, so a
      single potential trained on cross-interface configs (plus each
      bulk/surface) is forced. Per-pair bespoke (retarget = retrain);
      DeePMD is natively multi-element. v1 targets Si/SiO2 (covalent,
      Maszara anchor, short-range MLIP defensible); ionic/polar pairs
      kept as documented future work behind species-generic hooks.
      Captured in `ARCHITECTURE.md` §2.3 MLIP + material-knobs bullets.
      Foundation-model warm-start deferred to 1b below.
      **1b bootstrap coverage — RESOLVED (2026-07-08).** Break the
      circularity with a cheaper config GENERATOR than the production
      MLIP, then VASP-label + ALF-refine: (1) seed a DeePMD on hand-built
      near-equilibrium DFT (bulk Si + cristobalite, surfaces, STRUCTURAL-4
      strained substrates, rattled snapshots; optional foundation
      warm-start); (2) generate the violent Ar cascade on a
      well-validated classical silica potential (BKS / Vashishta) + ZBL —
      amorphous-surface configs made with NO MLIP; interface + separation
      on the seed MLIP; (3) VASP-label a subset, train, ALF-refine on
      committee / UDD uncertainty until below threshold; (4) converge on
      the potential-quality gate + uncertainty threshold (hands to
      STRUCTURAL 3). Engine split: classical + ZBL owns the cascade, MLIP
      only the gentle anneal + steps 6-7 (species stays {Si, O}; also
      resolves the ZBL-placement item below). Safeguards for the
      amorphous structure (glasses are kinetically trapped, so the
      classical start is only a basin): named-quality generator, a
      g(r) / ring / coordination validation added to the potential-quality
      gate vs DFT + experiment, a DFT melt-quench anchor, and a fidelity
      ladder classical -> MLIP re-anneal -> MLIP melt-quench. Captured in
      `ARCHITECTURE.md` §2.3 (MLIP + surface-dynamics + potential-gate
      bullets). DESIGN follow-ons: BKS vs Vashishta, the validation
      metrics + thresholds, seed-set composition, the bootstrap ALF
      convergence threshold, the re-anneal protocol, and the optional
      melt-quench upgrade. (`ARCHITECTURE.md` §2.1 steps 1-2, §2.3;
      `VISION.md` goal 1 and principle 5.)
      **STATUS (2026-08-28): design RESOLVED; generate / label / harvest
      BUILT; train / refine NOT STARTED.** The decision above stands
      with two amendments. (2026-08-21) The config GENERATOR is the
      universal foundation MLIP (+ ZBL for the cascade): no analytic
      potential and no seed committee appear anywhere in the loop, and
      the BKS / Vashishta / Stillinger-Weber language in the paragraph
      above is history. (2026-08-28, Paul) There is NO fallback
      generator of any kind — the DFT melt-quench "last resort" is
      struck too; a material the named universal model cannot describe
      is one SABSIM does not yet cover, and the answer is a new row in
      the supported-model table (DESIGN §4.7), never a second code
      path. Built: `sabsim bootstrap generate` (Collection 1 from the
      recipe, Collection 2 harvested from a dumped member run), `label`
      (direct VASP job array) and `harvest` (`labels.extxyz`) — LEDGER
      T-26 / T-27 on silicon. NOT built: `train` (the ALF bridge; the
      `prototypes/alf_deepmd/` converter is unit-tested but not imported
      by `src/`), the committee `pair_style` on the consumer side, the
      uncertainty readout, `refine`, and `test_convergence`. Until
      `train` lands the production slot holds the universal foundation
      MLIP as a committee of one (`[potential] production_weights`). The
      consumer-side wiring is tracked in the MLIP-integration checklist
      + status table below.
- [ ] Long-range electrostatics for ionic / polar pairs — RESIDUAL from
      STRUCTURAL 1a (2026-07-08), deferred with v1's covalent Si/SiO2
      scope. A short-range MLIP (DeePMD `se_e2_a`) is defensible for
      covalent pairs but may miss charge transfer and long-range
      Madelung / polarization energetics at a strongly ionic
      ferroelectric interface (LiNbO3). Fix path if needed: a long-range
      extension such as DPLR. Shares a root with the polar-slab dipole
      problem (`PRIOR_ART.md` §1.2 and the structure-builder bullet) — a
      macroscopic dipole is a long-range object a short-range potential
      cannot represent, so slab symmetrization is also what makes a
      short-range MLIP tenable. NOT the same as STRUCTURAL 4 (lateral
      lattice matching, which stays on v1's path). Revisit when an
      ionic/polar pair enters scope; keep the builder + potential
      species-generic with hooks documented until then.
      (`ARCHITECTURE.md` §2.3 MLIP bullet.)
- [x] [STRUCTURAL 2] Where the headline J/m2 number is computed —
      RESOLVED (2026-07-08). Decision: compute BOTH as a **measure
      vector**, not either/or. (1) A MECHANICAL MD work-integral over the
      step-7 pull is the headline and schedule fallback — pure post-
      processing, no Imago needed. (2) A THERMODYNAMIC energy difference
      (work of adhesion) at two fidelities — MLIP-level from a quasi-
      static LAMMPS relax-and-energy sequence, OLCAO-level from Imago on
      relaxed endpoints — whose disagreement doubles as the interface-
      region potential check STRUCTURAL 3 wants. (3) Imago bond
      descriptors (Q*, bond order, coordination) along the snapshot
      series. Endpoints relaxed before Imago; the descriptor series uses
      as-is finite-T frames. Owned by a new bond-outcome analyzer module;
      skeleton-prep split from Imago execution. Captured in
      `ARCHITECTURE.md` §2.3 (analyzer + Imago bullets) and `VISION.md`
      goal 4; DESIGN follow-ons in the DESIGN section below.
- [x] [STRUCTURAL 3] Interface blind spot of the two-gate model —
      RESOLVED (2026-07-08). The potential-quality gate gains an
      interface-fidelity check so an interface-coverage failure is caught
      as a POTENTIAL (data) problem instead of masquerading as protocol.
      Two complementary signals, reusing tools already decided: (i)
      committee / UDD uncertainty along the whole press-then-pull
      trajectory (endpoints + bond-breaking pathway) — cheap, always on,
      catches extrapolation; (ii) an all-electron ΔE cross-check on
      interface subcells (the STRUCTURAL-2 MLIP-vs-reference
      work-of-adhesion) — catches confidently-wrong; reference = VASP on
      a small subcell now (always-on backstop), Imago at scale
      when ready. Diagnosis order for a bad bond number: bulk gate fail
      -> add data; else interface-fidelity fail -> add INTERFACE data;
      else -> genuine protocol problem. Two remedies preserved; the
      interface hole is plugged. v1 = a reported diagnostic label (gate
      is a reporter). No new machinery — reuses STRUCTURAL 2's ΔE + 1b's
      committee + VASP. Captured in `ARCHITECTURE.md` §2.3 (potential-
      quality + new diagnosis sub-bullets) and the §3 loop note. DESIGN
      follow-ons: the uncertainty + ΔE-mismatch thresholds, the VASP
      interface-subcell size, and the report's diagnostic-label schema.
      (`ARCHITECTURE.md` §2.3, §3; `VISION.md` goal 4 and principle 5.)
- [x] [STRUCTURAL 4] Lateral lattice matching for the facing pair
      (step 5) — RESOLVED for v1 (2026-07-08). Reframe: surface
      amorphization makes the interface an amorphous–amorphous contact
      with NO registry requirement (this is why dissimilar bonding works
      at all), so the matching constraint relocates from the interface to
      the crystalline SUBSTRATES, and the amorphous interlayer buffers
      residual misfit -> looser tolerance -> smaller coincidence cells.
      Step 5: coincidence supercell of the two substrate lattices within
      a relaxed tolerance, residual applied as recorded substrate strain,
      activated layers absorb the rest. v1 uses crystalline SiO2
      (β-cristobalite, closest-to-Si polymorph) + crystalline Si, so it
      DOES exercise the coincidence matcher — new build, since prior art
      gave crystalline slabs but its bilayer assembly was design-only.
      Matcher written pair-generic for reuse. Captured in
      `ARCHITECTURE.md` §2.3 structure-builder bullet. DESIGN follow-ons:
      exact faces (a material knob), coincidence indices + misfit
      tolerance, strain split by compliance, cristobalite-vs-quartz, and
      averaging the bond metric over amorphization seeds. Feeds 1b: the
      applied substrate strain is a training-config dimension the MLIP
      must cover. (`ARCHITECTURE.md` §2.1 step 5, §2.3; `VISION.md`
      goal 2.)
- [ ] [RISK] Traceability across six codes. Goal 3 (funded -> every
      guidance number traceable to its exact inputs, versions, settings)
      rests on "provenance by discipline" spanning VASP -> ALF -> LAMMPS
      -> ASE -> Imago with no central store. Discipline across
      heterogeneous tools is fragile for a non-negotiable goal; flag now,
      revisit when the provenance-owner boundary (below) is settled.
      (`ARCHITECTURE.md` §2.3 and §4; `VISION.md` goal 3, principle 6.)
- [ ] [RISK] Retarget cost reality. "Point at a new material pair and run
      mostly automatically" (goal 2) automates the WORKFLOW, not the
      COST: a new pair silently triggers a full step-1 VASP campaign plus
      step-2 ALF training from scratch. Make this explicit so turn-key is
      not oversold. (`ARCHITECTURE.md` §2.1 steps 1-2; `VISION.md`
      goal 2.)
- [ ] [RISK] Critical-path dependency on unfinished Imago deliverables.
      Step 8 is blocked until three parallel Imago efforts land: the fast
      lightweight analysis mode, the ASE -> Imago adapter, and the
      initial-guess potential database (`ARCHITECTURE.md` §4 cross-
      project dependencies). Currently unowned and undated; track as a
      schedule risk on SABSIM's own deliverable.

- [ ] Outer orchestrator — partly resolved (2026-07-08). The execution
      model is now set in `ARCHITECTURE.md` §4.1: three tiers (thin
      sequencer / opaque ALF + Kaleidoscope Parsl / direct jobs), NO
      Parsl-in-Parsl, Parsl as the common dispatch substrate with plain
      `sbatch` for v1. Still OPEN: the heavier workflow / provenance
      manager that may sit on top (Snakemake / jobflow / AiiDA) and the
      triggers for graduating to it (`ARCHITECTURE.md` §4, §4.1).
- [x] Decide which step-6/7 snapshots get sent to Imago, how many,
      and how they are chosen — RESOLVED by `DESIGN.md` §8.3
      (2026-07-10). The three detectors, run on the §8.2 subcell atom
      set, gated by prominence, merged by event; "how many" is a logged,
      refinable frame budget; endpoints always included. (See the §8
      snapshot-selection item below for the full resolution.)
- [ ] Make the step 3/4/5 ordering a flexible setting, not hardcoded
      (`ARCHITECTURE.md` §2.1).
- [x] Decide where the ZBL close-range physics is added in the LAMMPS
      simulations — RESOLVED (2026-07-08, via STRUCTURAL 1b): ZBL is
      overlaid in the classical potential that runs the violent step-4 Ar
      cascade; the MLIP stages (gentle anneal, steps 6-7) need no ZBL,
      though a safety overlay against rare close approaches during
      pressing is a DESIGN-level option (`ARCHITECTURE.md` §2.3 MLIP +
      surface-dynamics bullets).
- [ ] Carry "what to run" vs "where to run it" separation into the
      module boundaries — located (2026-07-08), STRUCTURE decided
      (2026-07-12): the "where" is a single machine-local deployment
      config with TWO sections — a hardware inventory (the per-cluster
      swap unit) and a per-KIND-OF-JOB usage map keyed by resource class
      (`cascade-md`, `bond-md`, direct `vasp`, the `sequence` footprint);
      Tier B (ALF, Kaleidoscope) is EXCLUDED — it owns its own Parsl/SLURM
      and the config points at it, never duplicates it
      (`ARCHITECTURE.md` §4.1). The input fork was also resolved: the CWD
      study spec is self-complete (material + protocol + numerical +
      ensemble); the rc-style file is deployment-ONLY, no layered defaults
      (`DESIGN.md` §1.2, §1.4). Serialization FORMAT resolved to **TOML**
      (ratified 2026-07-13, `DESIGN.md` §1.8); the schema mechanism on
      top of it stays a follow-on. Templates authored:
      `dev/templates/study_spec.toml` and `dev/templates/deployment_rc.toml`.
      ROOT-ESTABLISHING mechanism DECIDED (2026-07-17): the three roots
      (`SABSIM_SCRATCH` / `SABSIM_SHARE` / `SABSIM_LOCAL`) are NOT in the
      deployment TOML — they must exist before Python starts (one names
      the install) and the TOML is found THROUGH them, so they are set by
      a sourced shell rc upstream of Python, the imago `imagorc` pattern:
      a machine-local `.sabsim/sabsimrc` of `export` lines inside the
      user's clone, sourced by the activation alias, generated by the
      installer and user-edited. Single-user and group-leader installs
      share it (system-wide admin install deferred). Written into
      `ARCHITECTURE.md` §4.1; `.sabsim/` gitignored. FOLLOW-ON: the
      installer + `INSTALL`/README that actually emit the rc are unwritten
      (the packaging story, not yet started); the derive-`SABSIM_SHARE`
      alternative was considered and DROPPED as unnecessary.
      **DESIGN CONSUMER — SECTION WRITTEN (2026-07-26) as `DESIGN.md`
      §10.** All questions Q1-Q5 resolved; §5.6/§5.9 reframed for the
      walltime decision. PROPAGATION (2026-07-26): (1) DONE — revised
      `ARCHITECTURE.md` §4.3 to three per-kind jobs, keeping its
      Approach-A serial-halves argument as a SEPARATE axis inside the
      activate job; (2) DONE — reshaped
      `dev/templates/deployment_rc.toml` (tool list machine-wide ->
      per-kind `[usage.*]`: cascade=lammps, bond=lammps+deepmd,
      vasp=vasp, sequence=[]); (4) DONE — `/refine`: the bare `§10.x`
      refs were `PSEUDOCODE.md` §10 cross-refs missing the prefix (now
      prefixed), so no DESIGN §10 was ever reserved; the stub was removed
      and deployment renumbered §11 -> §10. (3) DONE at DESIGN level —
      restart/resume is now its OWN section, `DESIGN.md` §11 ("Resuming
      an interrupted run"): within-run continuation of the PULL only in
      v1; a checkpoint is a MATCHED PAIR (saved engine state + a small
      progress ledger), keyed to the engine's step count not the burst
      counter; resume is chosen by the pair's presence (no new flag); an
      input-hash mismatch WARNS AND STOPS until explicitly overridden;
      §5.6 completeness gate unchanged (judges the whole, not the
      pieces). §10.6/§10.7 repointed at §11. No code yet — see the CODE
      follow-on below. Full capture:
      `dev/notes/deployment-design-discussion.md`. The
      settled decisions: the consumer is a WRITER
      (`sabsim prepare <spec>` emits ready-to-submit scripts, human
      submits — not a submitter, not schema-only); one member = THREE
      per-kind jobs run in order with human checkpoints — **activate**
      (CPU cascade+build+assemble), **bond** (GPU press/pull), **analyze**
      (CPU, split off for future heavy all-electron work); each job runs
      `sabsim run <spec> --activate|--bond|--analyze [--only <member>]`
      (mutually exclusive flags, none = whole chain); semantic filenames,
      NO ordinals, order in a guided index; the real safeguard is ONE
      ordered job registry in code that both `run` and `prepare` read;
      committee runs within the one `bond` submit. Q4 RESOLVED: scripts
      are SELF-CONTAINED — the generator BAKES resolved location values
      inline as a FROZEN SNAPSHOT (matches §1.4 "emit a complete file"),
      with a FAIL-FAST GATE that stops+reports on the login node if the
      roots (defined in the sabsimrc) don't resolve; TOOL LISTS GO
      PER-KIND (out of `[hardware]`, into each `[usage.*]` —
      RESHAPES the template); plumbing (potentials/interpreter/launcher)
      stays out of scripts; CLI verb `run` kept. Q5 RESOLVED: walltime is
      PERSON-PROVIDED per-kind (writer does NOT predict it); §5.6's
      formula becomes the human's estimation guide (reframed §5.6/§5.9);
      `prepare` refuses if requested walltime > partition `max_walltime`
      (cheap ceiling check); overrun -> HUMAN CONTINUATION (restart/resume
      is the G5 follow-on). All captured in `DESIGN.md` §10 (renumbered
      from §11 by the 2026-07-26 `/refine`: the bare §10.x refs turned
      out to be `PSEUDOCODE.md` §10 cross-refs, so no DESIGN §10 was
      reserved and the placeholder stub was dropped).
      REFINE 2026-07-29 (before starting the wiring): the §10 consumer
      gets a PSEUDOCODE pass FIRST — as `PSEUDOCODE.md §14`, "Deployment:
      prepare and run" — before any code. (A `/refine` had tentatively
      leaned DESIGN -> Code directly for §10; the user OVERRODE it into the
      standing rule: ALWAYS pseudocode from design before code, no
      shortcut, for any section. DESIGN §10 judged complete enough to
      pseudocode: the three jobs map to crisp §4.3 file-handoff boundaries
      — activate ends at the assembled-pair file, bond reads it and ends at
      the pull output, analyze reads that.) Also reconciled the template
      to `ARCHITECTURE.md` §4.4: `deployment_rc.toml` `bond-md` loads ONE
      engine module (`cpg_lammps/2024.08.29-deepmd`), NOT a separate
      deepmd-kit module (DeePMD is a runtime `plugin load`), `cascade-md`
      loads `cpg_lammps/22Jul2025`, and a machine-wide `module_paths` adds
      the `module use` for the CPG modulefile tree.
      PSEUDOCODE §14 DONE (2026-07-29, commit 4c90f7d) — "Deployment:
      preparing and running": 14.1 closed records (DeploymentConfig /
      Partition / UsageBlock), 14.2 the ordered JOB_REGISTRY (activate /
      bond / analyze), 14.3 the `run` selector + `run_member_job`, 14.4
      the `prepare` writer, 14.5 the generated-script shape.
      USAGE-KEY RECONCILIATION (2026-07-30): §14.1/§14.4 key `usage` by
      MEMBER JOB (activate/bond/analyze), but `ARCHITECTURE.md` §4.1 and
      the template still keyed it by TOOL (cascade-md/bond-md/vasp/
      sequence) — the §10.2 axis change had only reached §4.3. Fixed BOTH
      together (user chose "§4.1 + template"): §4.1's usage paragraphs
      rewritten to member-job keys (resource_class is the inner class
      seam; `sequence` dropped — the writer+human model has no
      orchestrator allocation, §10.1; direct-VASP-seed out, §14.5), and
      `deployment_rc.toml` rewritten to `[usage.activate|bond|analyze]`
      (activate = classical engine / CPU, bond = deepmd / GPU, analyze =
      CPU with NO science module in v1 — M1 is pure Python, and the §8
      characterization is Tier-B Kaleidoscope). Template parses; keys =
      activate/bond/analyze. CODE SLICE 1 now STARTING (in `deploy/`):
      §14.1 loader+records + §14.2 registry + §14.3 `run` selector + unit
      tests; `prepare` (§14.4-14.5) deferred to slice 2.
      SLICE 1a DONE (2026-07-30, commit 4732eba): `deploy/config.py`
      (§14.1 load_deployment + DeploymentConfig/Partition/UsageBlock/
      Duration) and `deploy/registry.py` (§14.2 ordered JOB_REGISTRY,
      artifact names, registry_lookup); 18 tests.
      SLICE 1b DONE (2026-07-30): the `run` selector + artifact I/O.
      (a) PSEUDOCODE §14.6 pinned the handoff artifact form — a readable
      manifest + large payloads by reference (§3 small-inline/large-by-ref
      rule) — resolving §14.3's delegated read_artifact/write_artifact;
      manifest is TOML (user pref), hand-rolled writer since `tomllib`
      only reads, null fields omitted. (b) `pipeline/handoff.py`:
      write/read_artifact for ASSEMBLED_PAIR (LAMMPS .data + an extended-
      XYZ atoms payload that round-trips the per-wafer TAGS the driver
      needs + a TOML groups manifest) and PULL_RESULTS (TOML manifest of
      the reduced curves); the ASSEMBLED_PAIR re-read is the Approach-C
      the `Structure.built` comment forecast. (c) `pipeline/member_jobs.py`:
      `run` selector + `run_member_job` — activate builds from the spec
      and writes ASSEMBLED_PAIR; bond re-reads it, presses/pulls, writes
      PULL_RESULTS; analyze reads PULL_RESULTS AND re-reads ASSEMBLED_PAIR
      for the interface cell, writes MEASURE_VECTOR; no-flag delegates to
      exec_full_study. (d) CLI: mutually-exclusive --activate/--bond/
      --analyze on `run`, --dry-run rejected with a job flag (dry-run is
      the whole-chain login check, §10.4), per-job summary with the
      next-job hint. 19 new tests (handoff round-trip incl. tags, three-
      separate-jobs chain, CLI); full suite 271 passed.
      LIVE SMOKE DONE (2026-07-30, job 15454930, "DEPLOY SMOKE: PASS" in
      24 min): the three-job chain ran end-to-end on real LAMMPS for the
      si-si-reference member as three SEPARATE `sabsim run --activate/
      --bond/--analyze` processes sharing one scratch — ASSEMBLED_PAIR
      (data + tagged atoms + manifest) and PULL_RESULTS round-tripped
      across the boundary, so the run selector §14.3 + handoff §14.6 are
      validated on the LIVE stages, not just the fake-stage-set units. Two
      bugs the smoke surfaced, both committed: (a) an MPI race in the
      scratch intermediate-link creation that DEADLOCKED a fresh job dir —
      all ranks race to make the link, losers halt, winner hangs at the
      next collective (commit 2289e3d, + deterministic regression test;
      the e2e never hit it because its link already existed); (b) the CLI
      summary printed on all 16 ranks, now rank-0 only (commit d144a99).
      NOTE the smoke trimmed the PROTOCOL (single 10 m/s pull rung, 20 ps
      press hold) on the SAME full-size ~8800-atom pair — the cell is
      PINNED in live_stages, not a spec knob, so there is no "small
      system." M1 came back UNRESOLVED by design (a single fast,
      non-quasi-static pull that did not fully separate); a real converged
      M1 needs the slow rate ladder = the full-run's job, nothing
      small-system-specific to transfer. Smoke files: jobs/deploy_smoke/
      (gitignored).
      PREPARE (§14.4-14.5) DONE (2026-07-30): `deploy/roots.py`
      (resolve_location_roots — SCRATCH+SHARE required, LOCAL optional,
      the §10.5 login-node gate) + `deploy/prepare.py` (prepare +
      render_job_script + the guide) + the `sabsim prepare` CLI verb.
      Scripts are the (A) FAITHFUL lean §10.5 form (directives + modules +
      frozen roots + run line; NO PYTHONPATH/LAMMPS_POTENTIALS — those
      come from the activated install). Also added a `tasks_per_node`
      field to UsageBlock (DESIGN §10.6 + PSEUDO §14.1 first, then code +
      template): MPI ranks/node is HUMAN-provided per-kind (atoms-per-rank
      sweet spot), not filled from the partition — template = 32/4/1 for
      activate/bond/analyze. 287 tests. The deployment consumer's design
      chain is now complete THROUGH CODE (run + prepare both built +
      tested; run validated live by the smoke).
      REMAINING (deployment): the "install" so the lean scripts run — a
      `.sabsim/sabsimrc` (the three roots + LAMMPS_POTENTIALS + conda
      activation) and `pip install -e .` (registers `sabsim`, puts the
      venv on PATH). This is the packaging follow-on §10.7 named; it is
      what makes the (A) scripts self-sufficient. Optional later: a
      tasks_per_node<=capacity ceiling check (like the walltime one);
      per-study walltime override on prepare (§10.7 follow-on).
- [x] **RESOLVED 2026-08-06 (ARCHITECTURE ↔ DESIGN): the MLIP re-anneal's
      resource class.** Settled by the universal-first cascade pivot: the
      activate job's resource class FOLLOWS the cascade potential's tier —
      the default universal MLIP makes activate GPU (so the re-anneal
      riding along is GPU too, no tension), and an opt-in classical form
      makes it CPU, chosen per-member via the `gpus_per_node` knob. The
      §3.5 activation gate still forces the re-anneal onto the activate
      side (not the bond job). `ARCHITECTURE.md` §4.1 rewritten (table +
      "Settled" block replacing "OPEN — URGENT"); `DESIGN.md` §4.7
      reframed "universal-first, classical optional." Was: §4.1 marked the
      re-anneal GPU while §10.2 folded it into the CPU activate job.
- [x] **PSEUDOCODE for `DESIGN.md` §11 (resume) — DONE 2026-07-27 as
      `PSEUDOCODE.md` §13** ("Resuming an interrupted run"). A dedicated
      top-level section (chosen over folding into §9) so resume stays
      coherent in one place at every level, mirroring DESIGN §11 1:1; the
      pull's §9.5 is its only v1 caller. Seven subsections: 13.1 the
      Checkpoint/Ledger structures; 13.2 the matched-pair write (temp-
      then-rename atomicity, both-parts-present load); 13.3 fresh-vs-
      resume by disk presence + `reconcile` to the saved step; 13.4 the
      `input_hash` warn-and-stop with deliberate override; 13.5 the
      re-keyed, check-pointed `pull_at_rate` loop (the hinge); 13.6
      completeness+provenance unchanged; 13.7 bottoms-out/delegates.
      `checkpoint_cadence` is a `RunControl` engineering setting (beside
      `chunk_steps`), value a §5.9 task.
- [x] **CODE follow-on for `DESIGN.md` §11 / `PSEUDOCODE.md` §13
      (resume) — DONE (2026-07-29).** Design, pseudocode, AND code are all
      done; the compute-node smoke passed (`RESUME SMOKE: PASS`, the SMOKE
      RUN note below in this item). Kept in place for its detailed record;
      checkbox reconciled 2026-08-07.
      Concrete pieces §13 pins: (a) in `driver/press_pull.py`, key the
      pull's `displacement` to the engine's ABSOLUTE step count, not the
      `chunk` counter (today `elapsed = (chunk+1)*chunk_steps*timestep`
      resets on a fresh process — the correctness hinge, §13.5); (b)
      write the checkpoint PAIR on a cadence — the engine's saved state
      (LAMMPS `write_restart`, none in the code today) plus a small
      on-disk ledger of the accumulated displacement/force/opening/bridge
      record AND the starting atom count (the §5.6 conservation baseline,
      also lost on a kill today), temp-then-rename so a kill mid-write
      leaves no half-pair (§13.2); (c) at pull start, detect the pair in
      scratch, `read_restart` + reload/RECONCILE the ledger (drop entries
      past the saved step), else begin fresh (§13.3); (d) an input hash
      (from the `DESIGN.md` §1.4 fingerprint + the settled-reference
      identity + the pull RATE — the only per-rung distinguisher, §13.4)
      recorded in the checkpoint, compared on resume — mismatch WARNS AND
      STOPS unless an explicit override (§13.4); (e) provenance notes a
      run was resumed (and any override) (§13.6). `checkpoint_cadence`
      lives on `RunControl` beside `chunk_steps` / `max_chunks` (an
      ENGINEERING setting, NOT a spec-visible NumericalKnob — the code
      revealed its siblings live there; DESIGN/PSEUDOCODE updated to
      match), so no `records.py` / template change is needed; its VALUE
      is a provisional-in-code `DESIGN.md` §5.9 / §11.6 task. Pull ONLY
      in v1; press/settle adopt §13's routines later.
      GROUNDING (2026-07-27, from reading the seams): (f) `pipeline/
      live_stages.py` runs the ladder's rungs in ONE shared
      `scratch_directory`, filename-distinguished (`log.pull_<i>`,
      `pull_<slug>` trajectory) — §13/DESIGN §11.3 now want each rung
      SELF-CONTAINED in `pull_<rate>/` with its log, trajectory, and a
      `checkpoints/` subdir; this restructures per-rung scratch layout
      and gives `pull_at_rate` a `checkpoint_dir` arg (threaded like
      `trajectory_file`). (g) `MockEngine` steps NOTHING today — it must
      gain a step counter that advances on `run N` plus a write/read_
      restart round-trip, or §13 cannot stay MockEngine-tested (the whole
      seam point). (h) `_pull_setup`'s `preamble_commands` does a
      `read_data` of the reference; on resume it branches to
      `read_restart` of the checkpoint instead. (i) the §13.4 override is
      an env var mirroring `SABSIM_ALLOW_UNVALIDATED_POTENTIAL`.
      PROGRESS (2026-07-27): DONE — the `Engine` seam
      (`step`/`write_restart`/`read_restart` + `MockEngine` step model,
      commit fbb9eb3); the ledger/hinge/checkpoint pair/reconcile
      (`driver/resume.py` + `press_pull.py`, commit 018a079, covering
      (a)(b)(c)(g)(h)); and the trust hash + warn-and-stop + override
      (`input_hash`/`verify_inputs_or_stop`, covering (d)(i)); and (f) the
      `live_stages.py` per-rung `pull_<rate>/` restructure that threads
      `checkpoint_dir` — resume is now ON for real runs (`_pull_rung_paths`,
      each rung self-contained with its own `checkpoints/`); and (e)
      provenance — `resumed`/`override_used` threaded `PullResult` ->
      `PullOutcome`, and a `[resumed]` / `[resumed; trust override]` marker
      on the rung note (`_pull_note`), so a continued run declares itself
      (VISION goal 3). ALL §13 CODE DONE. The compute-node smoke test is
      WRITTEN and ready to submit: `jobs/resume_smoke/` (slurm + README +
      `run_resume_smoke.py`) — CHECK A exact `write_restart`/`read_restart`
      round-trip, CHECK B full kill-and-resume pull; run once at `-n 1`,
      look for `RESUME SMOKE: PASS`.
      SMOKE RUN — RESOLVED 2026-07-29, `RESUME SMOKE: PASS` (interactive
      node, `-n 1`). CHECK A first FAILED with `read_restart` err0016
      "Did not assign all restart atoms correctly". The parked "`boundary
      p p f` before the read" hypothesis was DISPROVEN — all three preamble
      variants (units+style+boundary, units+style, units-only) failed
      identically. REAL cause: `build_facing_pair` emitted a triclinic box
      whose in-plane tilt sat at TWICE LAMMPS's skew limit (xy = -lx); a
      pymatgen coincidence cell can lean that far, `read_data` tolerates
      it, but `write_restart` / `read_restart` mis-bin atoms at the limit
      and silently drop them (55 of 640). FIX: orthogonalize the assembled
      pair in `slab_builder.build_facing_pair` — the same
      `orthogonalize_in_plane` lattice reduction `build_standalone_half`
      already applies — a no-op on an already-square face, so Si(100) is
      unchanged. CHECK A now round-trips to 7e-16. CHECK B was RESCOPED to
      what resume actually owns: `resumed` + `advanced` past the checkpoint
      step + `atoms_conserved`; `complete` is printed but NOT asserted —
      the coherent crystalline Si/Si smoke fixture necks and holds bridges
      instead of cleanly separating (a fresh un-killed pull of it does not
      complete either; that is FIXTURE physics, covered mock-side, not
      resume). Run 2026-07-29: CHECK A ok; CHECK B resumed=True
      advanced=True (step 800 -> 100000) atoms_conserved=True. Resume is
      DONE-DONE — its restart physics is now proven on live LAMMPS. Env
      note: the run needs `LAMMPS_POTENTIALS` at the VERSIONED build
      (`.../programs/lammps/current/share/lammps/potentials`, or let
      `module load cpg_lammps` set it); only the `jobs/*/slurm` scripts
      hardcode a versionless path — the modulefile itself is correct (see
      the engine-acquisition item).
- [x] **MPI: rank-0-guard `resume.write_checkpoint`'s ledger write —
      DONE 2026-07-27.** Surfaced writing the smoke test. `write_restart`
      is collective (all ranks, one file) and stays on all ranks; the
      `ledger.json` write and the two `os.replace` renames now run only on
      the primary rank, so the N ranks of an MPI pipeline run no longer
      race on one path (the data was identical across ranks — the
      read-backs are collective — so it was a filesystem race, not wrong
      content). The rank reaches the driver seam through the engine, which
      already holds the communicator: `Engine.is_primary()` is a concrete
      default-True (so the mock and serial runs are their own primary) and
      `LammpsEngine` overrides it to `comm is None or comm.rank == 0`.
      `load_checkpoint` is read-only, so it stays all-ranks. The rename
      order (ledger before engine) is now in `PSEUDOCODE.md` §13.2 too.
      NOTE: the pipeline passes an explicit comm, so this is correct
      there; `jobs/resume_smoke/` opens engines with `comm=None` (LAMMPS
      default world), under which rank 0 cannot be singled out, so THAT
      script stays `-n 1` — a script limitation, not the pipeline's.
- [ ] Decide which module owns provenance-by-discipline record-keeping
      (each step recording its inputs, exact tool version, and
      settings) (`ARCHITECTURE.md` §2.3 / §4, `VISION.md` goal 3 and
      principle 6).
- [ ] Validate the DeePMD backend end-to-end once real step-1 data and
      a GPU node exist: train + freeze an ensemble (`.pth`, deepmd-kit
      v3 PyTorch backend) and confirm committee `energy_stdev` in ALF's
      sampler (`ARCHITECTURE.md` §2.3, step 2). Converter round-trip is
      already unit-tested.
- [ ] Decide whether the SNAP "how cheap can we go" benchmark backend
      is in scope for v1 or deferred (`ARCHITECTURE.md` §2.3, step 2).
- [ ] Wire UDD as a first-class knob: expose ALF's `use_bias` /
      `E_en_bias_weight` on the committee calculator — a small,
      backend-independent ALF-side change (`ARCHITECTURE.md` §2.3,
      step 2). **Promoted from convenience to load-bearing** by
      `DESIGN.md` §7.3 (2026-07-09): the bounded exploration launched at
      an uncertainty abort *is* a UDD run. The abort trigger and the UDD
      bias respond to the same committee spread with opposite intent —
      a production run avoids it to make a measurement, a data-
      generation run seeks it to find the potential's holes.
- [ ] Add a `LICENSE` file (deferred 2026-07-03). Leaning Apache-2.0
      (explicit patent grant — the SAB process has a patent landscape)
      or BSD-3-Clause (simpler, matches scientific-Python and LANL ALF).
      Before committing one, confirm the grant terms and clear it with
      UMKC tech-transfer / sponsored-programs; copyright holder is
      likely "The Curators of the University of Missouri", not the PI.

---

## DESIGN

<!-- Tasks related to algorithms and data structures, mathematical
foundations, interaction rules. -->

- [ ] **Retire the walking-skeleton residue (Paul, 2026-08-28).** The
      walking skeleton has become a walking person, and some one-off
      scaffolding from the skeleton period is still on the path every
      run takes. Each item names its level; the first two are the
      2026-08-28 decisions, the rest are open.
      (1) [CODE] The capped / damped / reflecting-wall "contact relax"
      that preceded the heal (`commands.contact_relax_commands`,
      `press_pull.press_and_bond`) — a restraint written for a
      two-potential mismatch (surfaces amorphized under one model,
      pressed under another) that no longer exists. REMOVED
      2026-08-28; no document ever described it.
      (2) [DESIGN → CODE] The heal + §3.5 gate return to the activation
      stage, and the wide assembly gap + vacuum scissors are removed
      (DESIGN §3.4/§2.6, revised 2026-08-28) — DONE in the documents
      and in the code 2026-08-28 (`driver/cascade.build_activate_script`
      appends `commands.heal_surface_commands`; `live_stages.
      activate_one_half` gates the healed half; `press_and_bond` is
      cell relax -> press -> hold; the scissors, the wide-gap branch and
      the bond-side heal are deleted).
      (3) [DESIGN → CODE] `RunControl` in `driver/press_pull.py` holds
      numbers that live only in code: `equilibrate_chunks` 20 (the
      settle span), `stress_window` 5, `chunk_steps` 1000, `max_chunks`
      500. DESIGN §1.4 says nothing defaults silently and every knob
      carries its unit in the study file. The two contact knobs
      (`contact_gap_window`, `contact_stress_floor`) were lifted into
      the study file by the §5.2 revision of 2026-08-28 and the scissors
      pair died with the scissors; the settle span, the stress window
      and the chunking need a DESIGN §5.3 sentence each and then a
      study-file home.
      (4) [CODE] RESOLVED 2026-08-28 with (2): the "surfaces already
      close" branch in `press_and_bond` (the skeleton's direct-contact
      path, reused by accident to restart a bond from a saved press
      frame, LEDGER T-30) no longer exists — there is ONE path, cell
      relax -> press, and a pair restored from a saved press frame
      simply enters it at whatever opening it was saved at.
      (5) [CODE] `pipeline/skeleton_stages.py` still narrates Wave 0 in
      its header; its live use is the placeholder for the unbuilt step-8
      characterization and the placeholder measure records. Reword the
      header to say exactly that.

- [ ] **Rename the study-level "member" to "material pair"** (deferred,
      opened 2026-07-31). The word is overloaded: §1.1/§2.1 and
      `spec/records.py` use "member" for a study-level MATERIAL PAIR,
      while §4.4 uses it for a COMMITTEE member (one of the `n_models`
      MLIPs). Preference (Paul, 2026-07-31): RESERVE "member" for
      committee members — matching §4.4's existing usage — and rename the
      material-pair sense to "material pair" (or similar) across
      DESIGN / PSEUDOCODE / `records.py` / the spec schema / tests. A
      disambiguation note in §1.1 covers readers for now (added the same
      day); the full rename is NOT urgent — do not scour the code until
      this is scheduled deliberately.
- [ ] Document the MLIP backend-plugin mechanism when DESIGN work
      begins: the ANI-HDF5 ↔ DeePMD unit-factor conversion (round-trip
      already prototyped and unit-tested) and the potential-agnostic
      UDD bias math. `ARCHITECTURE.md` §2.3 forward-references both as
      "DESIGN-level detail" but no DESIGN section covers them yet
      (`ARCHITECTURE.md` §2.3, step 2).
- [ ] **§4.8 follow-ons — the force-model recipe** (opened 2026-07-24,
      when §4.8 was written). The section defines what a recipe must
      state; these four discharge it. (a) **Pin the numbers.** Every
      value in §4.8 is a placeholder resolved by the values file:
      production basis cutoff, reciprocal-space spacing,
      exchange-correlation treatment, smearing, electronic and geometric
      tolerances; the tightened audit block; strain magnitudes and how
      far past the reversible range they run; the labelling budget; and
      the two stopping thresholds. Several cannot honestly be chosen
      until the part-4 audit has been run once. (b) **Run the accuracy
      audit for {Si, O}** and record how far the production block sits
      from it — until then the block is unaudited and anything built on
      it is EXPLORATORY, the same discipline as
      `SABSIM_ALLOW_UNVALIDATED_POTENTIAL` (§4.7). (c) **Define the
      record** that `PSEUDOCODE.md` §11's twelve `pair_specification`
      call sites already assume, plus the load-time domain check that
      refuses a member whose structures fall outside the declared domain
      — DONE 2026-07-24 for the member side: `material_domain` is a
      required field on `MemberSpecification`, threaded to both force-model
      resolvers, and phase-three validation checks (species union, domain)
      against the registry before any engine opens. What REMAINS is the
      recipe side: once `ForceModelRecipe` exists, a member's domain must
      be checked to lie INSIDE the recipe's — containment, not equality,
      since a silicon-and-silica recipe legitimately covers a silica-only
      member. (d) **Lift §4.7's registry key to (species, domain)** —
      DONE 2026-07-24, see the item below.
- [x] **Define the recipe record `PSEUDOCODE.md` §11 threaded but never
      declared** — DONE 2026-07-24. `ForceModelRecipe` and its two
      sub-records (`ReferenceSettings`, `StartingCollection`) are written
      into §11.1, covering all eight parts of DESIGN §4.8 plus the
      validation rules. The twelve call sites were renamed from
      `pair_specification`, which was wrong twice: the key is a species
      UNION and a DOMAIN rather than a pair, and the object is a
      manufacturing recipe rather than a description. Not yet code — the
      record is a pseudocode declaration, and the Python dataclass lands
      when the bootstrap is built.
- [x] **Phase-three validation: do the referenced artifacts exist?** —
      DONE 2026-07-24 (this was gap G4 from the 2026-07-23 audit). New
      `spec/references.py` holds the crystal-path resolver (moved out of
      `live_stages` so the checker and the stages search the SAME places
      — one that looked elsewhere would either pass runs that then fail
      or fail runs that would work) and `check_study_references`, called
      by `exec_full_study` before any engine opens. It checks every
      wafer's CIF resolves and that (species union, material_domain) is
      a real registry key, reports EVERY problem in one pass rather than
      the first, and NAMES what it cannot yet check (`potential_ref` has
      no store to resolve against until the bootstrap exists). DESIGN
      §1.5 is now three phases, split by what each check needs: the file,
      the environment, or a measurement the pipeline must first produce.
      It immediately found a real defect — see the cristobalite item.
- [ ] **Restore beta-cristobalite as the Si/SiO₂ counterface** (surfaced
      2026-07-24 by phase-three validation, which refused the shipped
      template). The `si-sio2` member named
      `sio2_beta_cristobalite.cif`, a file that has never existed —
      cubic, and so the closest lattice match to Si(100), which is why it
      was chosen. The template and the e2e job now point at the
      alpha-quartz CIF that does ship, with the intent recorded in a
      comment, so the spec loads. Create the cristobalite CIF with the
      compound build and swap it back. Nothing is lost meanwhile: the
      assembly cannot run a genuine lattice mismatch until the wave-3
      coincidence matcher lands either (§2.3).
      **Why cristobalite and not quartz, recorded so the swap-back is not
      re-litigated.** Real fab silica is AMORPHOUS — thermal or deposited
      oxide — so neither crystal is what sits on a wafer, and the choice
      is about which starting crystal survives contact with this
      pipeline. Two criteria pick cristobalite for the DISSIMILAR member.
      It is cubic, so it can share a cell with Si(100); alpha-quartz is
      trigonal and would fight the coincidence matcher. And its density
      (~2.2 g/cm³) is essentially that of amorphous silica, where quartz
      sits at ~2.65 — which matters because §3.5's gate normalizes g(r)
      to the LOCAL density and already contends with the amorphized skin
      running ~20% lighter than the crystal beneath; starting from quartz
      widens that gap rather than narrowing it. Alpha-quartz stays right
      for the SILICA NULL test, where there is no silicon to match and
      the best-characterized crystal is the better reference — which is
      what the template already does. TWO CAVEATS for whoever makes the
      CIF: beta-cristobalite is only stable above ~1470 °C (the RT
      cristobalite polymorph is alpha, tetragonal), so the cubic
      structure is a modelling idealization; and the idealized Fd-3m form
      carries 180° Si-O-Si bridges against a real ~144°, which a
      classical form may react badly to. Decide between the idealized
      cell and a distorted lower-symmetry variant, and expect the §2.2
      bulk relax to move it.
- [x] **Retire the `_silica_only` marker in the cascade registry** —
      DONE 2026-07-24 (surfaced the same day by §4.8's domain analysis).
      The registry keyed on a frozen set of SPECIES, but two entries
      legitimately cover {Si, O} — the Munetoh Tersoff that spans the
      Si/SiO₂ interface, and the Vashishta form better for amorphous
      silica but unable to describe elemental silicon at all. They had
      been disambiguated by smuggling a non-element marker string into
      the key, which no real cell could produce, so the silica form was
      unreachable — a safety property by accident rather than design.
      The key is now `(species, domain)`: `CascadeGeneratorEntry` carries
      a `domain` field, the five rows declare `diamond-cubic`,
      `silicon-and-silica`, `silica-only`, `wurtzite` and
      `trigonal-ferroelectric`, and both resolvers take an optional
      `domain`. A species set with several registered domains and no
      domain named REFUSES, listing the candidates; a set with exactly
      one resolves without naming it, since there is nothing to choose
      between. The duplicated refusal blocks in the two resolvers were
      factored into one `_resolve_registry_entry`, and
      `registered_substrate_sets` became `registered_material_domains`
      (species AND domain in every message). Six new tests, 199 green.
      What is NOT done and stays with the §4.8 item above: the member
      specification cannot yet CARRY a domain, so a Si/SiO₂ run reaches
      the ambiguity refusal rather than passing a choice through.
- [x] STRUCTURAL 2 DESIGN follow-ons — RESOLVED by `DESIGN.md` §5-§6
      (2026-07-09), except (d). (a) **Both:** a constrained-minimization
      ladder at prescribed interface openings is the primary reversible
      curve, and relaxing the dynamic-pull snapshots is a cheap second
      curve whose gap from the ladder measures how far the pull rate sits
      from quasi-static (§6.4 M3). (b) The measure-vector schema is §6.6;
      it is machine-readable, every record carries uncertainty, units,
      fidelity, method and status, and the gate reads by name and status,
      never by position. (c) Settled in §5.4-§5.5: both grip reaction
      forces (Newton check), time-averaged with the warm-up discarded,
      peak extracted above a noise floor, integrated over grip
      displacement from the gated zero-load reference to complete
      separation, with the interface-opening curve emitted alongside;
      area is the §2 shared cell's `lx*ly` (tilt-independent).
      **(d) RESOLVED by `DESIGN.md` §8.4** (2026-07-10): skeleton
      preparation is a pure function of structure + settings, testable by
      exact comparison against a known-good input with no Imago present.
      Imago inherits the OLCAO input *format* (file-layout and
      command-sequence tweaks only), not the `$OLCAO_RC` convention. See
      the §8 skeleton-prep item below.
- [ ] §6 numeric follow-ons: the annealing schedule behind
      `work_of_adhesion_relaxed` (an amorphous surface is kinetically
      trapped, so the schedule is a recorded knob); the constrained
      ladder's opening spacing; the free-energy estimator for the
      `free_energy_correction` entry; the tolerance at which the
      interface subcell is declared converged (its *size* is no longer a
      constant to choose — §6.4 makes it the outcome of a convergence
      test run with the potential itself); and the numeric tolerances on
      every check in `DESIGN.md` §6.5 (dissipation >= 0, healing >= 0,
      rate monotonicity, ladder closure, subcell truncation).
- [ ] RDF + DOS as human-read spectra (added to `DESIGN.md` §6.4, §6.6,
      §8.6, §8.7 on 2026-07-11). The surface-region partial RDF is
      tracked across named stages and the DOS/partial-DOS come from Imago
      (VASP backstop); both are stored as by-reference curve ARTIFACTS
      for human reading, NOT auto-reduced — the only reduced scalars are
      the DOS's `dos_at_fermi` and `gap_size`. Definitions still to pin:
      (a) the exact set of NAMED STAGES and the surface-region atom
      window (a depth from the §2.6 dividing surface) the RDF samples;
      (b) how `dos_at_fermi` and `gap_size` are measured (broadening,
      the E_F window, the gap criterion for a possibly gapless
      interface). (c) `contact_area_fraction` — DEFINED 2026-07-11 as a
      grid-based BONDED contact fraction (equal-area fractional grid; a
      cell counts when it holds a cross-interface bond midpoint),
      `DESIGN.md` §6.4 + `PSEUDOCODE.md` §8.8. Only its numeric knob
      `contact_grid_spacing` remains to pin, with an insensitivity check.
- [ ] Interface definition is plural (`DESIGN.md` §6.2, 2026-07-11).
      Provenance (build-time identity) is the DEFAULT cross-interface
      test; an alternative — the SURFACE OF MINIMAL BOND STRENGTH (a
      weakest-cut, i.e. the fracture surface) — better handles truly
      integrated transferred atoms but is non-unique (bond strength has
      several measures: pair energy, force-to-break, electronic bond
      order, coordination depth). To DO if useful: register the
      minimal-strength interface as a §6.7 measure and report its
      DISAGREEMENT with provenance as a true-transfer observable; the §5
      pull's post-fracture M2 pieces are its a-posteriori realization.
- [ ] Bond/debond MD §5 depth-first pass DONE (`PSEUDOCODE.md` §9,
      2026-07-11). The stage-output seam was RENAMED (2026-07-11):
      variable/parameter `bond_debond_trajectory`, type `BondDebondResult`,
      contract `BOND_DEBOND_CONTRACT`; the per-pull `Trajectory` record
      keeps its name. `run_analyzer` now reads `.press` into `Verdicts`
      and iterates `.pulls` for `per_rate` measures. Left for the
      programmer: (1) pin the numeric values of the knobs the pass
      declared — `press_temperature`, `press_approach_rate`,
      `contact_gap_threshold`, `bonded_contact_threshold`,
      `force_average_window`, `reference_pe_drift` — plus `DESIGN.md`
      §5.9's own open numbers (target bonding pressure, hold duration,
      noise floors). (2) Pin the REPRESENTATIVE-pull rule: non-`per_rate`
      measures that need a pull (M2, M4, M5-electronic) run on the slowest
      rung by current design — confirm "slowest = representative" in
      `DESIGN.md` §6.4. Also noted: `separation_speed` (ProtocolKnob) is
      the single-rate special case, superseded by
      `numerical.pull_rate_ladder`.
- [ ] Activation §3 depth-first pass DONE (`PSEUDOCODE.md` §10,
      2026-07-12). The step-4 output became a concrete seam:
      `activate_surfaces` returns ONE `ActivatedSlabs` (both activated
      slabs AND both gate verdicts), guarded by `ACTIVATED_SLABS_CONTRACT`;
      the §1 unpack, the §6 `stub_activate` honoring note, and the §3
      contract index were rippled to match. New ProtocolKnobs declared:
      `activation_mechanism`, `activation_cospecies` (+fraction),
      `cascade_duration`, `between_impact_relaxation`, `reanneal_schedule`.
      Left for the programmer: (1) pin those knobs' VALUES plus the frozen
      v1 fluence / energy / normal incidence — the validation-metric
      thresholds and the re-anneal protocol are already tracked in the
      STRUCTURAL 1b follow-on below (g(r) / ring / coordination vs DFT +
      experiment), so not duplicated here. (2) WIRING decision: `DESIGN.md`
      §3.5 says the activation gate "feeds the potential-quality gate (§7;
      STRUCTURAL 1b)", but §10 only gates the PIPELINE at the §1 seam — the
      `ActivationVerdict` is not yet threaded upward into `MemberResult` /
      the §7 gate. Decide whether the verdict surfaces in the member report
      (a sequencer concern above §10's module scope).
- [ ] Bootstrap §4 depth-first pass DONE (`PSEUDOCODE.md` §11,
      2026-07-12) — the FIFTH and last buildable-unit pass
      (`ARCHITECTURE.md` §5.2), closing the "all modules at depth" count
      from four to five (the bootstrap had been deferred as "the Wave-2
      thing behind the seam"). §11 refines `DESIGN.md` §4.5's seed ->
      generate -> label -> retrain -> refine loop as ORCHESTRATION over
      the already-written stages: config generation REUSES activation
      (§10) and bond/debond (§9) in "generate mode" (harvest trajectory
      frames, no stage fork), and training/labeling/conversion DELEGATE to
      the two ALF contracts plus the `prototypes/alf_deepmd/` converter
      (`DESIGN.md` §4.2-§4.4). The bootstrap is a TOP-LEVEL process above
      `exec_one_member` (it manufactures ONE fingerprinted potential per
      pair; §1's `resolve_potential` is a LOOKUP, not a training call). A
      §1 MARKER now records that the potential-quality gate's ACTING form
      is the bootstrap's convergence check (§11.6) — which is precisely
      why the production-side bulk/surface gate only REPORTS. Left for the
      programmer: the §4.6 numeric values are already tracked in the
      STRUCTURAL 1b follow-on (descriptor/r_cut, `n_models`, loss
      schedule, `Escut`/`Fscut`, UDD weight, committee-sigma convergence
      threshold, seed-set composition), so not duplicated here.
      Amended 2026-08-28 (Paul): `seed_committee` (§11.2) is retired —
      the section is now `build_collection1`, §11.1 runs generate ->
      label -> train -> refine on the universal foundation MLIP, and the
      Collection 2 families are keyed on the press stage ledger (§9.3
      StageLedger, DESIGN §4.8 part 5 / §5.5).
- [ ] STRUCTURAL 1b DESIGN follow-ons: the amorphous-structure validation
      metrics + thresholds (g(r) / ring / coordination vs DFT +
      experiment), the Collection 1 composition, the bootstrap ALF
      convergence threshold, the heal protocol, and the optional MLIP
      melt-quench upgrade (`ARCHITECTURE.md` §2.3 MLIP + potential-gate
      bullets). The "BKS vs Vashishta silica generator" question is
      moot: the generator is the universal foundation MLIP (2026-08-21).
- [ ] Cascade generator DESIGN follow-ons (`DESIGN.md` §4.7, written
      2026-07-18, scope (a)). **UNIVERSAL PATH BUILT 2026-08-08**: the
      universal foundation MLIP + ZBL is now the DEFAULT for every material
      behind `resolve_cascade_generator` — `pair_style hybrid/overlay deepmd
      <model.pt2> zbl zbl`, v1 model **DPA-2.4-7M** (`validated=False`,
      proven to run on a V100 via the deepmd 3.2.0b0 `.pt2` path). Classical
      forms (silicon SW validated; silica / GaN / LiNbO3 documented +
      untested) are the explicit `SABSIM_CASCADE_CLASSICAL` opt-in. Still
      open: (1) run DPA-2.4-7M through a FULL activation to clear the §3.5
      gate (§4.7 rung 4, the arbiter), then flip `validated=True` — until
      then a default cascade needs `SABSIM_ALLOW_UNVALIDATED_POTENTIAL`;
      (2) the deepmd GPU engine for the activate stage is WIRED + node-
      validated (2026-08-08, job 16014788) as an OUT-OF-PROCESS
      subprocess+file-handoff (ARCH §4.4 — the bundle has its own torch/MPI,
      cannot share sabsim's in-process LAMMPS): `driver/cascade_subprocess`
      + `activate_one_half` dispatch, keyed off `SABSIM_CASCADE_ENGINE_
      PREFIX`. The per-kind `environment` EMISSION mechanism is now DONE
      (config.py `UsageBlock.environment` + prepare.py, 27 tests); STILL
      OPEN under (2): flip `[usage.activate]` to the GPU universal shape
      (partition/gres + the engine-prefix and model env — NO
      LAMMPS_POTENTIALS, since the re-arch below makes activate cascade-only)
      and the deploy-time, GPU-arch-specific `.pt2` build; (3) pin the
      acceptance-check
      tolerances — the crystal lattice/density band and the probe
      single-impact stability criterion (§4.7 rungs 2-3); (4) native DP-ZBL
      as a later close-range refinement of the `hybrid/overlay` splice
      (deepmd `dp_zbl_model`). Items (5) "validate a non-silicon classical
      candidate" and (6) "the DFT melt-quench last resort" are MOOT
      (Paul, 2026-08-28): there are no fallbacks. DESIGN §4.7 was
      rewritten 2026-08-28 as ONE universal generator, named by the
      study file and checked against a supported-model TABLE in code
      (one row today, DPA-3.1-3M). CODE DONE 2026-08-28: `cascade_
      potential.SUPPORTED_UNIVERSAL_MODELS` + `supported_universal_
      model(name)`; the validator (`spec/references.py`) and both
      resolvers look the study file's / recipe's model name up in that
      table, so a second universal model is a new row, not a resolver
      edit.
- [ ] **Re-anneal + gate re-architecture (DECIDED 2026-08-08, Paul; flow
      note "RESOLVED 2026-08-08"). REVERSED 2026-08-28 (Paul): the heal
      and the §3.5 gate move BACK into the activation stage, per half,
      at the end of each cascade session (anneal then minimize under the
      same universal model), and the gate halts BEFORE assembly. The
      2026-08-08 placement existed only because the heal then ran under
      a production potential whose engine lived in the bond job; one
      universal model for cascade and heal dissolved that reason. The
      wide assembly gap, the vacuum scissors, and the damped/capped
      pre-relax scaffold go with it; `initial_gap` becomes the
      press-start opening. The one-time LATERAL cell relax (§5.6) stays
      in the bond flow (it needs the joint cell). Docs propagated
      2026-08-28 (ARCH §2.1/§2.3/§4.1/§4.4, DESIGN §2.6/§3.4/§3.5/§5/
      §10.2, PSEUDOCODE §1/§7.5/§9.1/§10.1/§10.5/§10.6); CODE DONE
      2026-08-28 (`commands.heal_surface_commands` + heal-start marker,
      `cascade.build_activate_script`, `live_stages.activate_one_half`
      gating the healed half, `ActivatedSlabs`/`Structure` carrying the
      verdicts, `press_and_bond` = cell relax -> press -> hold with the
      `StageLedger`, `handoff` manifests, `bootstrap/harvest` keyed on
      the ledger; node validation = the dpa3f demo, LEDGER entry to
      follow). The text below is the 2026-08-08 record.** The #8
      combined-cell relax REPLACES the
      per-slab re-anneal, and the §3.5 gate MOVES POST-ASSEMBLY. Cross-
      cutting, DESIGN-first: (1) `cascade.build_activate_script` +
      `activate_surface` drop the re-anneal AND the gate — BOTH the universal
      out-of-process subprocess and the classical in-process paths, so the
      ACTIVATE stage becomes cascade-only and just yields the amorphized
      half; (2) the §3.5 gate runs after the #8 joint relax, per-surface by
      wafer tag, BEFORE the scissor + press (keeps §4.1's gate-before-press-
      GPU); (3) the return contract shifts — the verdict comes from the
      post-#8 gate, so `ActivatedSlabs` + the sequencer's gate checkpoint
      move accordingly; (4) DESIGN + PSEUDOCODE are now UPDATED to match
      (DESIGN §2.2/§2.6/§3.4/§3.5/§4.7/§10.2, ARCH §4.1/§4.4, PSEUDOCODE
      §7.5/§9.1/§10.1/§10.5/§10.6 + sequencer; refined 2026-08-08) — the CODE
      remains. This also drops the activate job's LAMMPS_POTENTIALS need (no
      classical re-anneal in the bundle) and lets `[usage.activate]` flip
      cleanly to the GPU universal shape. The current cascade+re-anneal+gate
      activate (node-validated, job 16014788) is the working INTERMEDIATE
      this simplifies.
      SCOPE ADD (2026-08-21): the #8 combined-cell relax also owns the
      RECORDED one-time LATERAL re-equilibration (x,y), not only the
      out-of-plane heal — see the §5.6 lateral-stress item. That is
      what lets the press hold a FIXED, recorded cell without the
      `lateral_relax` band-aid, so this relax and the §5.6 rewrite land
      together.
- [ ] **`coordination_numbers` MISCOUNTS on non-orthogonal cells — the
      gate coordination failures are a MEASUREMENT ARTIFACT, not
      over-amorphization (diagnostic 2026-08-22).** The gate kernel uses
      `box_x=cell[0][0]`, `box_y=cell[1][1]` with per-axis minimum-image,
      valid ONLY for an orthogonal in-plane cell (the stand-in caveat the
      module already states). But the activated slabs are sheared: a
      PRISTINE diamond-Si slab (cell[1]=[-3.84,3.84,0], NN 2.351 A) reads
      coordination MODE 2 from `coordination_numbers` vs MODE 4 from ASE
      `neighbor_list` (the truth) at cutoff 2.9 A. So the 0.76-1.0 defect
      fractions that FAILED Si (T-10) and LiNbO3 (T-19) are wrong before
      any physics -- NO cascade dose/energy sweep could fix them (this
      diagnostic SAVED that V100 series). FIX: count neighbors with a
      general-cell routine (ASE `neighbor_list`, already a dependency) in
      `coordination_numbers`; likely also affects the ring metric + the
      `_reference_coordination` self-reference (its deep-third "crystal"
      also read over-coordinated). Then RE-RUN the gate on the existing
      activated surfaces (`t10_val`, `t12_val_*`) to get the TRUE
      coordination, and only THEN judge it against the (still stand-in)
      thresholds. This also subsumes the separate "coordination not
      per-species" review item -- do both in the kernel rewrite.
- [ ] Activation gate (Phase 2) DESIGN follow-ons (`DESIGN.md` §3.5,
      `PSEUDOCODE.md` §10.6, written 2026-07-18). The gate design is a
      metric registry (g(r)/partial g_AB, coordination DISTRIBUTION +
      defect fraction, ring statistics, robust return-to-baseline depth),
      each returning a `MetricVerdict`; references/thresholds live OUTSIDE
      the physics spec in an easily-locatable `share/` dir (real ones later
      from `SABSIM_SHARE`). Still open: (1) PIN the v1 stand-in reference
      numbers/curves — a-Si first g(r) peak ~2.35 A, ~4-fold with a few %
      3/5-coordinated, 5/6/7-ring populations, ~2-3 nm depth target — then
      the REAL DFT/exp g(r) + the group's a-Si CRN model as drop-in
      replacements; (2) EVALUATE the Imago `bond_analysis.py` ring tool for
      narrowness (standing rule) before adopting it behind the `RING_
      BACKEND` seam — networkx King/shortest-path rings is the v1 backend;
      (3) build the `share/` reference dir + the `load_activation_
      references` resolver (repo share first, then SABSIM_SHARE). The Phase-1
      stand-in `activation_disorder_check` is what this gate replaces.
- [ ] /refine follow-ons (2026-07-18): (a) §10.7 `label_activated_skin` —
      record the activated-skin atom SET from the gate's measured depth —
      is not yet coded (the Phase-1 stand-in returns a verdict only); it
      lands with the Phase-2 gate / live wiring. (b) A dedicated
      `activation_temperature` spec knob: the cascade border thermostat
      currently reuses `press_temperature` as the shared room-temperature
      setpoint (`DESIGN.md` §3.3), which v1 keeps; a separate knob is a
      possible future need, not now. (c) DONE (2026-07-18): the `share/`
      reference-data directory is built and in the `ARCHITECTURE.md` §1
      layout; `share/activation/Si.toml` holds the v1 stand-in references.
- [ ] Slab size <-> bombardment energy <-> DFT cost: a THREE-WAY
      accommodation (`DESIGN.md` §2.5 / §3.2 / §3.6 / §6.4; found live
      2026-07-18). The slab must be large enough to ABSORB the cascade
      energy — energy-per-atom sets a thermal spike, and above the
      vaporization threshold the slab BOILS OFF instead of amorphizing
      (measured on real LAMMPS: 500 eV into a 288-atom slab -> ~165,000 K,
      77% sputtered; 100 eV into ~2000 atoms -> ~700 K, clean). So §2.5's
      thickness criterion (activated_depth + minimum_bulk_thickness) needs
      a THIRD consideration: enough atoms (thick AND wide) that the impact
      energy spreads into a survivable spike. BUT the cell must also stay
      DFT-TRACTABLE — the bootstrap VASP labeling (§4.5) and the
      all-electron interface subcells (§6.4) scale steeply with atom count
      — so we CANNOT simply enlarge the slab to absorb a high energy. The
      resolution (user steer, 2026-07-18): jointly choose the bombardment
      ENERGY, the slab SIZE, and the amorphized DEPTH to keep the cell
      DFT-tractable, ACCEPTING A LOWER ENERGY (enough to create SOME
      amorphous layer) over strict fidelity to the physically-realized
      ~1 keV fast-atom-beam energies and ~2-3 nm depths. This is consistent
      with v1's relative-trends / ratio calibration (`DESIGN.md` §7), which
      already does not demand absolute physical agreement. CONSEQUENCE: the
      §3.6 frozen 500 eV default and the ~2-3 nm skin-depth target become
      NEGOTIABLE under the DFT budget — re-pin energy, slab size, and depth
      TOGETHER, not independently, once the DFT cell-size budget is known.
- [ ] Run-artifact + reporting layer — BUILD items (`ARCHITECTURE.md`
      §4.2, `DESIGN.md` §9, designed 2026-07-18; adapt as implementation
      demands). (1) The run bundle: results land in the SUBMISSION dir
      `jobs/<study>/<member>/`, per-run subdirs `run-<id>/` + a `latest`
      symlink, small keepables (report, `summary.json`, manifest) in the
      job dir and large data on SABSIM_SCRATCH via the `intermediate`
      symlink with human-readable names; a study roll-up at `jobs/<study>/`.
      (2) The canonical `summary.json` (§9.1) as the single structured
      contract (measures, verdicts, provenance: git commit / seeds /
      potential + reference-data flags / versions / host; pointers +
      fingerprints to scratch). (3) The swappable report renderer (§9.2):
      Beamer / Markdown / HTML over the summary + matplotlib plots (g(r),
      rings, depth profile, force-vs-opening, rate ladder); NO Ovito
      snapshots in v1; the study roll-up renders the §7 ratio. (4) The
      visualization dumps (§9.3): add a STRIDED CASCADE TRAJECTORY (only
      the pull dumps today) and a shared Ovito-ready column set
      `id type x y z group coordination defect provenance` across cascade
      and pull; the endpoint frame in the job dir is a secondary
      convenience. NOTE: §10.7 `label_activated_skin` (deferred in Phase 2)
      is now LOAD-BEARING — it is the per-atom `activated-skin` group value
      the dump colours by.
- [x] Activation pipeline wiring — the build->amorphize->assemble chain
      runs inside the pipeline, node-validated (2026-07-20, `4f6f689`;
      `ARCHITECTURE.md` §4.3, `PSEUDOCODE.md` §1/§7.1/§10.1). The member
      chain is file-handoff stages — build-standalone-halves ->
      [amorphize A | amorphize B] -> assemble — each opening its OWN engine
      from a data file (never a live handle across the seam), the two
      amorphizations serial in one job (Approach A; the four `# C-EXPANSION`
      points flagged for the later fan-out). Built: `HalfHandle` (file +
      beam-declaring type map + identity + wafer role) as the
      build->amorphize handoff; `SLABS_CONTRACT` checks the handles; the
      sequencer threads the run's scratch dir explicitly
      (`exec_full_study(study, job_directory)` -> `member_scratch` ->
      `exec_one_member`); `slab_builder` gained `orthogonalize_in_plane` +
      `read_standalone_half`; NEW `pipeline/live_stages.py` holds the REAL
      stages `build_halves` / `activate_surfaces_live` / `assemble_pair_live`
      speaking the SAME contracts as the W0 stubs (which now also speak the
      handle seam, so W0 stays login-node-runnable — `test_sequencer` gains
      a `job_home` fixture). Sub-slices (a) verdict adapter, (b) standalone
      half builder+writer, (c) amorphized assemble, (d) engine-provider —
      all DONE. Node run (jobid 15021434): chain ran build -> activate BOTH
      halves -> gate; the gate CORRECTLY HALTED at `ACTIVATED_SLABS_CONTRACT`
      (gate-not-warn) on the gentle smoke dose (216-atom slab over-sputters
      at 100 eV); `assemble_pair_live` then exercised on the real amorphized
      halves (63+109 survivors -> facing pair, 1.49 Å clash relief). 150
      unit tests green.
- [ ] Run ONE Si/Si member end to end FOR REAL — the four steps left after
      the wiring landed (verified against code 2026-07-20):
      (1) PIN the slab-size/dose so a real amorphized layer forms and the
      gate PASSES — the one genuine physics item (the open §3.6 three-way
      slab<->energy<->DFT-cost accommodation; the node run's 216-atom slab
      over-sputters at 100 eV; `_LATERAL_REPEAT` / `_MIN_SLAB_THICKNESS` in
      `live_stages` are stand-in constants — bigger slab or gentler energy).
      MEASURED (2026-07-21, sweep v3, jobid 15124543 — 20 points, 1h39m,
      every point clean): on a 4400-atom slab 38.4 Å wide x 55 Å thick,
      energy {40,50,62,75} eV x dose {0.010...0.030}/Å², **ZERO SPUTTERING
      AT ALL 20 POINTS** (4400 survivors everywhere) — the drop to 40-75 eV
      fully solved the over-sputtering. Skin depth spans only 3.95-10.26 Å
      and SATURATES in both knobs: 75 eV runs 5.97/8.27/8.56/10.25/10.26
      across the dose row (flat past 0.025), while down the dose-0.030
      column energy gives 6.57/8.34/8.53/10.26. So ENERGY sets the
      REACHABLE DEPTH (it is the ion range) and DOSE fills in DISORDER
      (coordination 0.086->0.219, rings 0.199->0.465, both rising with
      either knob). CONSEQUENCE — the blocker is no longer the dose but the
      THRESHOLD: nothing in the clean zero-sputter regime reaches the 20 Å
      `share/activation/Si.toml` depth stand-in (max 10.26 Å), and the
      energies that would reach it reintroduce the sputtering just escaped.
      All 20 points PASS coordination, rings, and RDF and fail ONLY on
      depth. So step (1) now resolves by LOWERING the threshold to measured
      physics (the skin-thickness item in the DESIGN section above), NOT by
      pushing the dose — and the accessible 4-10 Å window BRACKETS the
      5-10 Å floor that item predicted for Si/Si on registry-decoupling
      grounds. Candidates: e075_f025 (10.25 Å, coord 0.198, rings 0.455)
      for the deepest clean skin, e050_f020 (5.95 Å) for a thin one. USER
      STEERS the number. CAVEATS: ONE seed per point and the noise is real
      (the 40 eV row ran 3.95->4.36->3.98->8.31->6.57), so treat any
      single-cell difference as noise and trust only row/column trends; and
      `radial_distribution` reads exactly 2.375 at ALL 20 points — it is the
      g(r) first-peak POSITION (Si-Si ~2.35 Å), not a disorder measure, so
      its >=0.3 threshold passes trivially and contributes nothing to the
      gate. Worth revisiting when the thresholds are retuned.
      (2) CONNECT the press/pull + analyzer PIPELINE STAGES to their real
      code: the press/pull DRIVER (`driver/press_pull.py`) already EXISTS
      and was validated on real LAMMPS (stage 5) — only the pipeline stages
      `run_bond_debond_md` + `run_analyzer` (`skeleton_stages`) are still
      placeholders; each needs a thin connector, NOT new physics.
      (3) SELECT real-vs-stub stages in the sequencer: it is hardwired to
      the `skeleton_stages` stubs (so it runs login-node with no LAMMPS); it
      needs a way to pick the `live_stages` set for a real run while keeping
      the stubs for quick login-node checks.
      (4) BUILD the reporting layer (`ARCHITECTURE.md` §4.2 / `DESIGN.md` §9:
      summary.json, swappable report, cascade trajectory dump + column set,
      §10.7 skin-label) — designed, NOT yet coded.
      Independent follow-ons (none block the four above): Si/SiO2 dissimilar
      — the surface-lattice matcher (`match_surfaces`, ZSL) EXISTS and is
      used by `build_facing_pair`; missing is wiring it INTO `build_halves`
      (today each half is cut on its own lattice, so the si-sio2 halves are
      not commensurate and assembly refuses) AND the strained assembly of a
      real mismatch (`assemble_facing_pair` raises `NotImplementedError` for
      non-identity); the SiO2 cascade potential is REGISTERED
      (`SiO2.vashishta`) but `validated=False`. Real refs: the
      `share/activation/Si.toml` thresholds are literature stand-ins
      (real=false) — replace with DFT/exp + the a-Si CRN model (user HAS
      one). Reuse the STORED bond cutoff: the gate already reads a
      `bond_cutoff` from the reference; the assembly's `_BOND_CUTOFF=2.8 Å`
      (`live_stages`) could read that instead of hardcoding (§6.3). Triclinic
      min-image: the gate's g(r)/coordination kernels assume an ORTHOGONAL
      in-plane cell, and `orthogonalize_in_plane` only removes a REMOVABLE
      tilt — it lands Si(100) on an orthogonal cell (that cell is orthogonal
      under a pymatgen tilt artifact) but does NOT orthogonalize a genuinely
      oblique cell (a hexagonal or triclinic face stays oblique), so the
      triclinic kernel is still needed for those materials, just not for the
      current Si(100) path. `activation_temperature` spec knob — noted, not
      built. Evaluate the Imago ring tool (door-open swap).
- [x] STRUCTURAL 3 DESIGN follow-ons — RESOLVED by `DESIGN.md` §7
      (2026-07-09), except the bare numbers. The diagnostic-label schema
      is §7.8 (verdict / cause / basis / fired / unresolved / power /
      remedy / provenance). The interface-subcell *size* is no longer a
      quantity to choose: §6.4 makes it the outcome of a convergence
      test run with the potential itself (`subcell_truncation_error`),
      so the cheap method certifies the expensive method's input. The
      thresholds became *significance statements* rather than constants,
      because §6.6 forbids bare numbers and every gate comparison
      therefore carries an uncertainty (§7.5). Two additions changed
      `ARCHITECTURE.md` §2.3 in the same commit: `void` at the head of
      the chain (a measurement that is not a measurement is never
      diagnosed) and a `basis` field recording whether `protocol` was
      reached by direct evidence or by elimination (§7.7).
- [x] §6.4 defect FIXED (2026-07-09), recorded for the lesson it
      carries: the interface-fidelity check originally read `M4 - M2`
      with M4 on a subcell and M2 on the full cell, conflating the
      fidelity difference with a box-size difference. It is now M4 minus
      M2 on the *same* subcell, gated by M2(full) - M2(subcell). The
      transferable rule: **any comparison of two methods must fix the
      system, and any comparison of two systems must fix the method.**
      Worth checking for the same shape wherever else the chain compares
      quantities computed different ways.
- [ ] §7 numeric follow-ons: the quantile that calibrates the
      committee-uncertainty threshold; the significance level for the
      fidelity cross-check; the width of the absolute sanity bracket;
      the committee evaluation stride, the persistence window, and the
      abort budget (§7.3); the step budget and plausibility ceiling
      bounding the UDD exploration launched at an abort; and the
      composition of the harvested batch (stratified baseline vs
      excursion).
- [ ] §8 numeric and interface follow-ons (opened by `DESIGN.md` §8.9):
      the smoothing window and prominence threshold behind each of the
      three detectors; the frame budget and the refinement that shows it
      adequate; the merge tolerance (the sub-noise energy gap below which
      two frames with an identical cross-interface bond set are one); the
      one-time denser-mesh check that demotes Γ-only to a tested
      numerical setting; the exact file-layout and command-sequence
      differences between Imago and legacy OLCAO; the atom-count envelope
      check of §8.2 and what §2's coincidence tolerance must be to keep
      the subcell affordable for v1's pair (the coincidence tolerance
      prices step 8); and Imago's failure taxonomy — which failures are
      retryable and which are structural, since §8.6's coverage-by-class
      rule needs to tell them apart.
- [ ] §7.7's open question, deliberately surfaced rather than hidden:
      the inventory of protocol checks (rate-ladder convergence, press
      contact quality, the dissipation identity, ladder closure) was
      assembled for other purposes and has **not** been argued to span
      the ways a protocol can be wrong. The `basis: by_elimination`
      count is the instrument that measures how sparse it is.
- [ ] Confirm whether ALF exposes the **per-atom** committee spread or
      only the global `energy_stdev`. DeePMD's energy is a sum of atomic
      contributions so the quantity exists; §7.3 uses it to localize the
      potential's ignorance, and §6.4 uses that to center the interface
      subcell. A code-level question for PSEUDOCODE
      (`prototypes/alf_deepmd/`, [[alf-pluggable-mlip-backend]]).
- [x] Wording audit, deferred from the Imago rename — RESOLVED
      (2026-07-10). Ruling from the programmer: Imago inherits the OLCAO
      input *format* (only file-layout and command-sequence tweaks), so
      "structure in OLCAO format" is legitimate, not stale, and OLCAO
      names both the method Imago implements and the input convention it
      kept. The earlier `PRIOR_ART.md` claim that the two "share no input
      format" was an overstatement and has been narrowed in three places
      (§ intro, §1.2 item 5, §1.8): the *format* transfers; the rc
      convention, invocation, and `$OLCAO_RC` machinery do not.
      Captured in `DESIGN.md` §8.4 and §8.9.
- [ ] STRUCTURAL 4 DESIGN follow-ons — mostly answered by `DESIGN.md`
      §2 (2026-07-09). Settled there: the matcher is a whole-number
      tiling-matrix + in-plane-twist search (Zur-McGill, adopted from
      `pymatgen`) over a strain *tensor*, not a scalar length match; the
      strain split is weighted by each slab's biaxial stiffness times
      its thickness (an even split is the equal-weight special case);
      lattice constants come from a bulk relaxation under the current
      committee, referenced to VASP; the facing pair (not the slab) is
      the object the builder constructs. Still OPEN: the exact Si and
      SiO2 Miller faces (a material knob), the numerical misfit
      tolerance + cell-area/atom-count budget, cristobalite-vs-quartz,
      and how many amorphization seeds the bond metric is averaged over
      (`ARCHITECTURE.md` §2.3 structure-builder bullet; `DESIGN.md` §2).
      CODE STATUS 2026-08-06: the §2.2 BULK RELAX is now WIRED (commit
      cf92d30) — a first-class `derive_lattices` stage relaxes each
      material's cell under the current model (classical seed at cold
      start; the same seam takes the committee later) and the build
      rescales onto it, any symmetry (`derive_lattice`,
      `rescale_crystal_to_cell`, `_coupling_for`), retiring the CIF-lattice
      cut. CODE STATUS 2026-08-22 (universal-first reaches §2.2, branch
      `universal-mlip-cascade`): `derive_lattices_live` now derives the
      working lattice under the UNIVERSAL MLIP by default — the SAME model
      the step-4 cascade runs under — so the cell and the amorphizing
      potential AGREE. This closes the specific gap the A.3 note below
      flags: the dominant oxide residual stress is the §2.2 CIF-vs-DPA
      offset, which relaxing under classical SW then bombarding under DPA
      does NOT remove; deriving under DPA does. Because the `.pt2` loads
      only in the deepmd bundle, the default derivation runs OUT-OF-PROCESS
      (`bulk_relax_subprocess_script` -> `run_activate_subprocess`, read
      back by `read_data_box`), mirroring the cascade handoff; an explicit
      `SABSIM_CASCADE_CLASSICAL` keeps the small in-process path. Also
      fixed en route: `bulk_relax_commands` now inserts `atom_modify map
      yes` before `read_data` for a message-passing MLIP (it was classical-
      only and silently deepmd-incompatible). Docs propagated (DESIGN
      §2.2, ARCH §4.4, PSEUDOCODE §7.2); 10 unit tests added; 61 green. CODE STATUS 2026-08-21 (supersedes the 2026-08-06 line above):
      the matcher (`match_surfaces`, pymatgen ZSLGenerator) is now
      WIRED through `build_standalone_half`, and the strained
      real-mismatch assembly is BUILT (Phase B, branch
      `universal-mlip-cascade`, commits `40b9e6a` + `563eb80`):
      `even_split_shared_cell` + `tile_slab_to_shared_cell` place both
      slabs on one commensurate cell. Only `assemble_facing_pair` (the
      crystalline all-in-one null path) still raises
      `NotImplementedError`, and the real mismatch path no longer
      needs it. DRIFT that remains (A.3, review 2026-08-21): the split
      is EVEN (`even_split_shared_cell`, `slab_builder.py:546`), NOT
      the §2.4 stiffness-weighted split the docs describe. The
      `biaxial_stiffness * thickness` weighting needs each material's
      elastic constants under the potential — the SAME constants the
      potential-quality gate computes (§2.4:677) — which are not yet
      measured. CORRECTED by the T-17 evidence (2026-08-21): the
      MEASURED biaxial moduli are close (SiO2 ~234, LiNbO3 ~276 GPa,
      ratio ~1.18, `build_stiffness_probe.py`), so the even split sits
      NEAR the stiffness-weighted split — the weighting is a MODEST
      refinement for this pair, NOT the detonation cause. The dominant
      residual stress is the §2.2 CIF-vs-DPA-lattice offset (~7-8 GPa
      per material, `relax_lattice.py`), which mainline `build_halves`
      already removes via `derive_lattices` but the t12/t14/t15
      harnesses skipped; the one-time box-relax is the demonstrated fix
      (see the §5.6 lateral-stress item below). THICKNESS
      AS A STRESS LEVER (Paul, 2026-08-21, capture-not-act): thickness
      enters the stiffness weight, so thickening the STIFFER slab moves
      strain onto the softer one and lowers PEAK stress — but that
      optimizes a DIFFERENT objective (min-peak or equal stress) than
      §2.4's current total-energy minimum, and couples §2.4 to the §2.5
      depth floor (thickness can only grow above the floor). DECIDE the
      objective function before acting.
- [ ] **Cell geometry is defined by the universal MLIP, never
      re-derived under the trained committee — self-consistency loop
      left open (noted 2026-08-21, Paul; fine for now).** With the
      universal foundation model as the bootstrap generator, the whole
      cell construction runs on ITS energetics: the derived lattices
      (§2.2 bulk relax), the elastic constants behind the strain split
      (§2.4), and the amorphized half-cells themselves. The bespoke
      committee is then trained on configs the universal model visited
      — but the cell is NOT rebuilt under the committee once it exists.
      DESIGN §2.2 / ARCH §2.3 already say "the shared cell is
      re-derived whenever an ALF round changes the committee", so the
      design anticipates closing this loop; the universal-generator
      flow simply does not close it yet. Accepted for v1. FUTURE:
      re-derive the cell under the trained committee and check whether
      the geometry (and thus the training configs) shifts enough to
      warrant an outer iteration.
- [ ] **Lateral stress accommodation during the press — §5.6 needs a
      recorded exception (review 2026-08-21; Paul approved the
      direction).** Pressing the SiO2/LiNbO3 pair detonates: the
      assembled cell carries large residual stress (frame-0 probes, up to
      ~24 GPa for a CIF-built cell), the fixed-box press (§5.6) traps
      it, and the interface rebounds and disintegrates between press
      frames 9-10. ROOT CAUSE, CORRECTED by the T-17 evidence
      (2026-08-21): the dominant term is the §2.2 CIF-vs-DPA-lattice
      offset (~7-8 GPa per material, `relax_lattice.py`) — a MISFIT-
      INDEPENDENT stress that mainline `build_halves` already removes
      via the `derive_lattices` rescale (commit `cf92d30`) but the
      detonating t12/t14/t15 harnesses SKIPPED (they built from CIF).
      The measured biaxial moduli are close (SiO2 ~234, LiNbO3 ~276
      GPa), so the even split is NOT the cause — A.3 is a modest
      refinement. §5.6 forbids a live lateral barostat ("the recorded
      substrate strain relaxes away and the provenance number becomes
      a fiction") — correctly — and the uncommitted `lateral_relax`
      band-aid (`lateral_relax_commands`, `commands.py`; `press_pull.
      py`; `fix nph x 0 y 0`) is exactly the zero-stress,
      runs-during-the-measurement barostat §5.6 rules out. The
      DEMONSTRATED fix is the one-time box-relax (`box_relax_probe.py`,
      job 16453628: pxx/pyy ~98k/58k -> ~0 bar, box moved -0.27%,
      stayed ordered). SANCTIONED DIRECTION: (1) apply the mainline
      §2.2 `derive_lattices` rescale (removes the dominant offset — the
      harness bug was skipping it); (2) fold a ONE-TIME, RECORDED
      combined-cell lateral relaxation into the #8 combined-cell relax
      (see the re-arch item) — x,y find the post-amorphization
      equilibrium ONCE at assembly, the relaxed cell + new per-slab
      strains are written to provenance (§2.6), then x,y are FROZEN for
      the whole press/settle/pull; (3) keep a stiffness-set barostat
      (holds toward the RECORDED cell with the material's biaxial
      modulus as the resistance, not toward zero) only as a documented
      fallback. DESIGN EDIT REQUIRED, COORDINATED (refine catch, 2026-08-21):
      the fixed-lateral rule is echoed beyond §5.6 — PSEUDOCODE §9
      (~line 1848) and §10 (~2070/2311) both say "LATERAL cell HELD
      FIXED — no barostat", and §2.6 records no combined lateral relax
      yet. The revision (permit a recorded, one-time, pre-measurement
      re-equilibration; still forbid drift DURING the pull) touches
      §5.6 + §2.6 + PSEUDOCODE §9/§10 together, not §5.6 alone. Retire
      the unconditional `lateral_relax`.
      The distinction from `lateral_relax`, in three axes: WHEN (once,
      before vs continuously during), RECORDED (yes vs silent drift),
      and FIXED-during-measurement (yes vs no). Couples to A.3 (shares
      the elastic constants) and the thickness lever above.
      CODE DONE 2026-08-21 (Phase-3 item 3): DESIGN §5.6 revised +
      PSEUDOCODE §9 synced; `combined_cell_relax_commands` added
      (`commands.py`, `fix box/relax x 0 y 0` + minimize + unfix),
      WIRED at the joint heal before the gate (`press_pull.py`), and the
      `lateral_relax` band-aid fully retired (field, builder, wiring,
      t15). Full suite green. REMAINING: (a) write the relaxed cell +
      per-slab strains to provenance (the "recorded" half of §5.6 — the
      FREEZE is done via `unfix`, the record is not yet captured to the
      artifact); (b) node-validate the mainline combined-cell-relax
      press on the oxide pair (batched).
- [ ] Structure-contract schema: the labeled atom groups the builder
      emits (frozen base, thermostat border, NVE interior, activated
      skin, press/pull grips, per-slab id) and consumed across the
      step-3/4/5/6/7 seam — introduced in `DESIGN.md` §2.6, needs its
      concrete field list. Prior art re-derives these regions ad hoc in
      every LAMMPS input from hardcoded layer thicknesses.
- [ ] Slab-thickness convergence: `DESIGN.md` §2.5 sets the criterion
      `slab_thickness >= activated_depth + minimum_bulk_thickness`,
      where `activated_depth` is measured by the §3.5 depth profile.
      WIRED 2026-08-07 (commit `b823133`) as a FLOOR in the build —
      `_effective_slab_thickness = max(slab_thickness,
      expected_activated_depth + minimum_bulk_thickness)`, all three now
      spec knobs and the achieved margin recorded on the shared cell — so
      the criterion is now ENFORCED. What REMAINS is the physics: pin the
      provisional values (`minimum_bulk_thickness` = 30 A,
      `expected_activated_depth` = 7 A, `slab_thickness` = 55 A) by running
      the convergence study, and close the loop that feeds §3.5's MEASURED
      depth back to re-check the build-time estimate (today a manual step).
- [ ] Minimum amorphous-skin thickness — a work-of-separation convergence
      (design discussion 2026-07-20; the user wants the skin as THIN as the
      physics allows, for a cheaper DFT cell). The bond is an INTERFACE
      property — the cross-interface bond density at the contact plane — so
      the skin's DEPTH matters only through its two other jobs, both a
      BUFFER role, not a strength role: (a) decoupling the two crystal
      REGISTRIES (the reason activated bonding joins dissimilar materials),
      and (b) absorbing the lattice MISFIT. So thinner should not weaken the
      bond down to a floor: ~5-10 Å for Si/Si (no misfit; it just needs a
      genuine registry-free amorphous contact), a bit more for Si/SiO2 (to
      buffer the misfit); below ~5 Å it degrades into a rough crystalline
      surface — mechanical INTERLOCK, a DIFFERENT regime, not the SAB one we
      model. VERIFY empirically, do not argue it: assemble pairs at several
      skin thicknesses (thinned by LOWERING THE DOSE, more than the energy),
      run the full press/pull, and plot W_sep vs skin thickness; the
      plateau's THINNEST skin is the operating point. This lands the §3.5
      gate depth threshold on PHYSICS — replacing the study file's
      `[protocol.activation] required_activated_depth` (7 Å in the
      production template; moved there from the `share/activation/`
      reference on 2026-08-28, Paul: a study's depth requirement is a
      study choice, not a material fact — LEDGER T-33 halted a 50 eV
      demo on the production value) — and is the cheapest cell that
      still gives the converged bond (the §3.6 three-way slab<->energy<->DFT
      accommodation). Enabled by the end-to-end press/pull; the natural
      companion to the energy sweep is a DOSE sweep measuring W_sep. Ties
      `DESIGN.md` §2.5 (thickness criterion), §3.5/§3.6 (depth/dose), §8
      (bond metric).
- [ ] §3.6 depth-anchor RE-CHECK after the pre-cascade minimize (opened
      2026-08-07, from the §2.4 out-of-plane relax landing, commit
      `b92418f`). The §2.4/§2.7 pre-cascade relaxation now runs
      UNCONDITIONALLY (`cascade_prerelax_commands`), so the Si/Si run
      bombards a surface-RELAXED start, whereas the 20-point sweep that
      pinned the 7 A operating depth used an un-relaxed start. On the next
      sweep, confirm the measured depth / gate metrics are unchanged (the
      frozen base is anchored, so the change is a small near-surface
      settle) or re-pin the threshold. Cheap; the threshold was always
      flagged measurement-anchored, not physics-derived. Ties `DESIGN.md`
      §2.4 / §3.6.
- [ ] **RESUME HERE (2026-07-21). ONE DECISION IS OPEN AND IT IS THE
      USER'S: where the work-of-separation integral STOPS.** The whole
      chain now runs end to end and produces a number, so this is the
      question standing between us and a defensible one.
      WHAT WE FOUND. Ovito showed a WEB OF STRINGS bridging the two
      wafers during separation (user's observation, frames 60-80 of
      `ovito_pull_10mps.dump`). Quantified: the two faces pass out of
      each other's reach after 10 Å of pulling, but bonds still cross
      the interface until ~44 Å, and HALF the reported work accrues in
      between — carried by about ONE PERCENT of the atoms (~80 of
      8799), then divided by the full contact area. Bonds crossing the
      plane decay 149 -> 118 -> 45 -> 23 -> 11 -> 5 -> 1 -> 0; the last
      strand FLICKERS in and out from 32 Å to 42 Å.
      THE CHOICE, and it spans a factor of two:
      (a) AS COMMITTED (`653204c`): stop when NOTHING crosses the plane.
          The rigorous reading of "the interface has parted" — and it
          INCLUDES all the strand-drawing work. Gives ~10.0 J/m².
          Note this is BIGGER than the old force rule's 9.4, not
          smaller: waiting for the last strand integrates FURTHER than
          waiting for the force to go quiet. (I had predicted the
          opposite; the data corrected it.)
      (b) Stop when the faces pass out of range (~10 Å of pulling).
          Excludes the strand work. Gives ~5.0 J/m².
      (c) Stop when bridging falls below a fraction of its start value.
          Intermediate; needs the fraction chosen.
      MY READING: (a) is the right DEFINITION, and its answer being
      strand-dominated is a real finding about the POTENTIAL rather
      than something to define away — a stretched low-coordination
      silicon chain is the regime a classical Si model describes worst,
      and this family is known to draw silicon out where the real
      material snaps. The fix for that is the trained potential, not
      the stopping rule. But the call is the user's.
      TO RESUME: pick a rule, then `sbatch jobs/si_si_e2e/slurm_back`
      (reuses the amorphized halves, ~21 min, no re-bombardment). The
      criterion in code today is (a) and has NOT yet been run.
- [ ] Pull-rate sweep is mis-scaled against the chunk budget: separation
      needs ~25-44 Å of grip travel, but `max_chunks=500` allows only
      5 Å at 1.0 m/s and 16 Å at 3.2 m/s, so ONLY the fastest rate can
      reach separation — the opposite of what the sweep exists for (it
      should report the SLOWEST rate that separates). Raise `max_chunks`
      (~800-1000 lets 3.2 m/s finish; 1.0 m/s needs ~3000) and compare
      the work across rates. Costs disk: each rate already writes a
      1.3 GB trajectory.
- [ ] Trajectory dumps are 1.3 GB per rate, ~3.9 GB per member per run,
      and will multiply by the 3 amorphization seeds once the ensemble
      loop lands. Revisit `frame_stride` (currently 100) with the
      reporting layer.
- [ ] DEFERRED (raised 2026-07-21, no action for now) — MODEST BOMBARDMENT
      PARALLELISM: fire n Ar SIMULTANEOUSLY per round instead of strictly
      one at a time (`DESIGN.md` §3.2/§3.3; would add a §10.3 knob and
      change the §10.4 loop). Today `run_cascade_to_fluence`
      (`driver/cascade.py:290`) is a strict serial loop — insert ONE
      projectile, run the halted NVE cascade, relax, repeat — and the
      16-way parallelism is LAMMPS spatial decomposition WITHIN a single
      impact. Cost is linear in impact count at ~10.0 s/impact with a
      ~zero intercept (measured across sweep 15124543), so n-at-a-time
      would cut a dose point's wall clock by roughly n.
      THIS IS A MODEL CHANGE, NOT A SCHEDULING CHANGE — it must be
      VALIDATED, never assumed. Two conditions must both hold:
      (a) SPATIAL — the cascades must not overlap. Best min-image
          separation for n sites on the 38.4 Å square torus is 27.2 Å
          (n=2, L/sqrt(2)), 23.8 Å (n=3, 0.620 L), 19.2 Å (n=4, L/2). At
          40-75 eV the measured skin is only 4-8 Å deep and the lateral
          damage radius is comparable (~10 Å, ~15 Å counting elastic
          disturbance), so n=2-3 has real margin while n=4 is the first
          that is genuinely tight.
      (b) THERMAL — with no sputtering essentially the WHOLE ion energy
          thermalizes into the slab: one 50 eV impact raises all 4400
          atoms by ~88 K, four at once by ~350 K in one pulse. Since
          amorphization here IS a thermal-spike-and-quench process, a 4x
          larger global pulse may over-anneal the damage the quench is
          meant to freeze in. Langevin cooling is exponential, so
          draining 4x the energy costs an extra ~tau*ln(4) (a few tenths
          of a ps), which trims the speedup to ~3x rather than defeating
          it — the relax duration must grow with n, not stay fixed.
      FIRST STEP, BEFORE ANYTHING ELSE — MEASURE THE CASCADE FOOTPRINT:
      run a SINGLE impact and record the lateral radius of atoms
      displaced past a threshold. That replaces the ~10 Å estimate above
      with a measured number, and the separation rule then follows from
      DATA rather than from argument. Costs ~10 s of compute.
      THEN validate equivalence: the same (energy, dose) at n = 1 / 2 / 4,
      comparing skin depth, coordination, and ring statistics. Needs >= 3
      SEEDS per condition — the sweep's 40 eV row ran 3.95 -> 4.36 ->
      3.98 -> 8.31 -> 6.57 Å, so a single-seed comparison would "confirm"
      whatever it happened to draw.
      DESIGN RULE if it is ever built: n must SCALE WITH AREA, never be a
      fixed count. Expose an area-per-simultaneous-impact knob (about
      (2 x footprint radius)^2) and DERIVE n from it, or the physics
      changes silently the moment someone widens the cell (`VISION.md`
      principle 1). At ~625 Å²/ion today's cell supports n=2; a 76.8 Å
      cell would support ~9.
      IMPLEMENTATION (modest, all local to `driver/cascade.py`): group
      `impact_seeds` into rounds of n; sample the n sites per round under
      a min-image minimum-separation rejection test (deterministic from
      the seeds that already exist); insert all n projectiles before the
      single `run`. The physical-time halt and the fire-and-forget
      structure work unchanged, since the halt keys on elapsed time and
      not on a projectile count. RECORD n IN THE MANIFEST — a run at n=4
      is NOT trajectory-comparable to one at n=1 even given identical
      seeds.
      NOT NEEDED FOR SWEEPS, which is why this is deferred: fanning grid
      points out as separate jobs buys the same wall clock at ZERO physics
      risk (`ARCHITECTURE.md` §4.3, the C-EXPANSION fan-out). The payoff
      case is the single large PRODUCTION run at a realistic 2-3 nm skin,
      where one member carries hundreds of impacts and cannot be split
      across jobs — and where the wider cell makes the separation
      comfortable anyway. Ties the skin-thickness item above (both are
      dose-physics questions on the same cascade).
- [ ] STRUCTURAL 2 / §5 follow-ons opened by `DESIGN.md` §5
      (2026-07-09): the target bonding pressure and hold duration; the
      noise-floor thresholds for the zero-load reference state, for
      "force returned to zero," and for calling a force peak resolved;
      the contact-quality definition's bond-counting cutoff; and the
      ensemble size (amorphization seeds x velocity seeds). Also pin the
      pull-rate ladder's three rates (`DESIGN.md` §5.4, §5.9).
- [ ] Press-mode seam: `DESIGN.md` §5.2 freezes load-controlled press
      for v1 with a displacement-controlled cross-check on the Si/Si
      reference. Specify the seam's contract (both modes emit load AND
      depth reached) and the reversibility comparison between them.
- [x] §6 follow-ons opened by the analyzer evaluation (`PRIOR_ART.md`
      §1.8) — RESOLVED by `DESIGN.md` §6 (2026-07-09). The schema is
      machine-readable with per-record uncertainty, units, fidelity,
      method and status (§6.6); bond cutoffs are derived per species
      pair from the first minimum of that pair's partial g(r), and a
      measure whose cutoff is unresolved is marked `unresolved` rather
      than defaulted (§6.3); geometric coordination and electronic bond
      order are separate named families (§6.4 M5); and cross-interface
      bonds are identified by a per-atom **provenance label** kept
      distinct from **species** — one field per job, where prior art had
      one field doing both (§6.2).
- [x] Thermodynamic work of adhesion (§6) — RESOLVED (2026-07-09).
      Written from scratch; prior art's spec is not adopted. **Two named
      references**, because they answer different questions: pieces are
      identified by bonded-cluster connectivity, then
      `work_of_adhesion_as_fractured` relaxes each only into its nearest
      minimum (matched to the mechanical pull, so their difference is
      dissipation and nothing else) and `work_of_adhesion_relaxed`
      anneals each so its surface reorganizes (the reference that
      connects to `W = γ_A + γ_B − γ_AB`, whose surface energies are
      defined for equilibrium surfaces). Their difference is reported as
      `surface_healing_energy`, and `transferred_atom_count` beside it.
      Each is reported **twice**: a zero-temperature potential-energy
      difference (headline, comparable to the all-electron 0 K
      cross-check) and a `free_energy_correction` at the press
      temperature, whose ensemble may be smaller because it needs a
      phonon calculation per endpoint (`DESIGN.md` §6.4 M2).
- [x] §8 snapshot selection — RESOLVED by `DESIGN.md` §8.3 (2026-07-10).
      Adopted the SHAPE of prior art's unbuilt `select_snapshots` (PE
      hold-minima, PE pull-maxima, σ_zz drop spikes, near-duplicates
      merged), with three fixes it lacked: the detectors run on the §8.2
      subcell atom set (where the event is, not the noisy whole cell);
      candidates must clear a prominence threshold above §5.4's noise
      floor; and near-duplicates merge by *event* (identical
      cross-interface bond set + sub-noise energy gap), not by geometric
      RMSD. Endpoints are always included; the frame budget is a
      numerical setting whose drops are logged.
- [x] §8 skeleton prep — RESOLVED by `DESIGN.md` §8.4 (2026-07-10). A
      NEW build against the **Imago** seam, a pure function of a
      structure and a settings object (no clock, no working directory,
      no environment), testable by exact comparison against a known-good
      input with no Imago present. Correction from the earlier framing:
      Imago *does* inherit the OLCAO input format (file-layout and
      command-sequence tweaks only); what it does not inherit is the
      `$OLCAO_RC` working-directory-as-config convention (the §1.2 item 7
      antipattern) or any script from that lineage.
- [x] Settings-file shape — RESOLVED by `DESIGN.md` §1 (2026-07-09).
      The configured object is a **study** (members + relations), because
      §7.4's criterion is a ratio and a ratio belongs to a *pair* of
      members; a member still stands alone and studies may be assembled
      after the fact. Knobs split into **five** groups by a sharp test — a
      numerical setting's effect must vanish under refinement, a
      protocol knob's effect *is* the physics — with ensemble (seeds)
      separate because a seed is sampled, not tuned, and deployment in
      its own document (§4.1). No hidden defaults: the loader rejects an
      incomplete spec; defaults exist only as a generator that emits a
      fully-populated file. Protocols are identified by a **content
      fingerprint**, not a version number (versioning is too linear;
      protocols branch). Lattice constants, the shared cell, bond
      cutoffs, subcell size and activated depth are **derived, never
      settings**. `ARCHITECTURE.md` §2.3's member-spec bullet amended in
      the same commit.
- [ ] §1 follow-ons: the serialization format and schema mechanism; the
      exact fingerprint definition (which fields it covers, and how a
      field declared irrelevant to comparability is excluded); how
      relations beyond `ratio` are expressed; and the initial sorting of
      difference-set fields into *entailed* vs *incidental*, which is a
      physics judgment, not a schema one, and will need revisiting as
      relations are added (`DESIGN.md` §1.1, §1.4, §1.8).
- [ ] §1 gave every open numeric follow-on a single home. The values
      themselves — §2's tolerances, §3's gate thresholds, §5's rate
      ladder, §6.5's check tolerances, §7's quantile / stride /
      persistence window / abort budget / bracket width — must all
      appear in the specification file, since nothing may fall back to a
      hidden code default. Pinning them is still open; **housing** them
      no longer is.
- [x] Value pinning RATIFIED (2026-07-13): the literature-anchored v1
      knob values in `dev/V1_VALUES.md` are accepted. The three forks
      resolved: **Ar energy 500 eV** default (user-overridable across
      50-500 eV, optionally lower e.g. 50 eV); **3 amorphization seeds**;
      **beta-cristobalite(100) SiO2 / Si(100)**. Format = **TOML**. The
      values are distilled INTO DESIGN §2.7 (faces), §3.6 (energy /
      fluence-to-depth / seeds), §5.9 (pressure / temperature / hold /
      rate ladder); §4.6 needed no change (the forks touch no MLIP-backend
      knob). Templates authored under `dev/templates/`. Face, polymorph,
      material, energy, and seed count are v1 DEFAULTS, not freezes.
- [ ] Tier-D numeric follow-ons are NOT "pick a value" — they are
      derived or need reference DATASETS (`DESIGN.md` §1.3): lattice
      constants, shared cell / tiling / strain, bond cutoffs, the
      interface-subcell size, the activated depth, and the potential; the
      gate THRESHOLDS (g(r), ring stats, coordination, surface energies,
      the Maszara ratio) need reference data, not chosen constants. These
      are reclassified out of value-pinning; resolve them via their owning
      section's derivation or convergence study, not by typing a number.
      See `dev/V1_VALUES.md` "Tier D".
- [ ] Principle recorded by `DESIGN.md` §1.1, worth defending in review:
      **report, never restrict.** Refusing to evaluate and refusing to
      certify are different acts, and SABSIM performs only the second. A
      relation whose controls disagree, or which is confounded, is still
      computed and reported with its difference set; only the *gate's
      verdict* is withheld. `unresolved` is a statement about the gate's
      competence, never about whether a number may exist. Watch for this
      eroding as gates are implemented — the temptation to refuse the
      computation will be strong and must be resisted.

---

## PSEUDOCODE

<!-- Tasks related to algorithm specifications. -->

- [ ] **§11 gap: Collection 1's dynamics families name no force model.**
      `GenerationPlan` carries `cascade_model` and `protocol_model`, but
      both describe COLLECTION 2 (§4.8 part 5). Collection 1 has two
      families that also require dynamics — family 3, the bulk
      melt-quench amorphous network, and family 6, the warm NVT/NPT runs
      — and neither `QuenchSpec` nor `WarmRunSpec` carries a model field,
      so the chain never says what generates them. By the STRUCTURAL-1b
      argument that put the foundation MLIP in `protocol_model` it should
      be the foundation MLIP here too (generating training configs with
      the model being trained is the circularity 1b exists to break), but
      an argument is not a specification. Fix is one field: either a
      `generator_model` on each of the two records, or a single
      `collection_one_model` on `GenerationPlan` covering both. Prefer
      the latter unless the melt-quench and the warm runs could ever want
      different generators — they could, since a melt visits chemistry a
      warm crystal never does, so decide that explicitly rather than by
      default. Found 2026-08-25 reading the chain against the code.

- [ ] First PSEUDOCODE pass follows `ARCHITECTURE.md` §5.4 — **breadth-
      first shallow, then depth-first per module.** Pass 1 covers only
      control flow and the seam schemas (Tier-A sequencer, member-spec
      load/validate, the labeled-group structure contract, the measure
      schema, the gate precedence chain) — the walking skeleton expressed
      as pseudocode. Deep per-module algorithms (coincidence matcher, UDD
      bias, detector prominence math) are deferred to when each module is
      implemented behind its already-frozen contract. Writing them all to
      full depth up front is itself a way to code into a box (§5.1). Open
      scope question for the session that starts this: confirm the Si/Si
      walking-thread membership from §5.3 Wave 0 before pseudocoding it.
- [x] `/refine` note — sequencing check RAN (2026-07-12). The standing
      ask (does the pseudocode's SHAPE — build order, skeleton-first —
      obey `ARCHITECTURE.md` §5.3's waves, not just its content?) was
      executed. Result: Wave-0 order (§6 vs §5.3), the steps-3/4/5 reorder
      freedom, and the potential/characterization seams all matched. ONE
      substantive finding — the potential-quality gate's two-times split
      (`DESIGN.md` §7.2: bulk/surface BEFORE the builder) was absent from
      §1's control flow — was resolved not by moving the production gate
      but by recognizing its ACTING form lives upstream in the bootstrap's
      convergence check: a §1 marker plus the new bootstrap pass
      (`PSEUDOCODE.md` §11; see the DESIGN-section DONE item above). The
      pre-existing per-atom-committee-spread question stays filed in the
      DESIGN section, tagged "a code-level question for PSEUDOCODE".
- [x] `/refine` leftover — FIXED (2026-07-12): the §6 walking-skeleton
      snippet had shown the PRE-ripple bare-`slabs` flow, contradicting
      §1's post-ripple `ActivatedSlabs` unpack. Now updated to
      `(slab_A, slab_B, shared) = build_slabs(...)` ->
      `activated = stub_activate(slab_A, slab_B)` -> the `slab_A`/`slab_B`
      rebind -> `assemble_pair(slab_A, slab_B, shared)`, matching §1. The
      prose honoring note below it was already correct (`PSEUDOCODE.md`
      §6).
- [x] Second whole-chain `/refine` after §11 (2026-07-12): chain
      consistent (VISION->ARCH, ARCH->DESIGN untouched; DESIGN->PSEUDOCODE
      faithful — §11 maps 1:1 onto DESIGN §4.5; PSEUDOCODE->Code still
      N/A). ONE finding, FIXED same turn: the potential-quality gate was
      asserted to be "the same gate" acting upstream (§11.6) and reporting
      downstream (§5) but was NOT a shared unit — §5 inlined its two
      checks and §11.6 named a `run_potential_quality_gate` defined
      nowhere. Factored `potential_quality_gate` into ONE §5 function that
      both `evaluate_member_gates` (reads into the five-way diagnosis) and
      §11.6 (acts on `.passes`) call, added `PotentialQualityVerdict`, and
      retyped `ConvergenceReport.quality_gate` to it. Also recorded a
      no-change observation: two top-level entry points now exist
      (`exec_full_study`, `bootstrap_potential`) with manual v1 ordering —
      consistent by design (`PSEUDOCODE.md` §5, §11.6).
- [ ] Step-8 characterization §12 pass DONE (`PSEUDOCODE.md` §12,
      2026-07-13) — the SIXTH and last module pass, on `DESIGN.md` §8,
      CLOSING the DESIGN->PSEUDOCODE boundary (all five buildable units +
      the frame now at depth). The four SABSIM-side artifacts are pure
      functions: selector (§12.2), skeleton-prep (§12.3), manifest
      (§12.4), harvester (§12.5). TWO narrow spots stay `[DEPTH-FIRST]`
      pending the in-development Imago — the exact input file-layout /
      command-sequence (§12.3) and Imago's failure taxonomy (§12.5) —
      the honest limit of "finish the pseudocode" pre-Imago (`DESIGN.md`
      §8.8: the SABSIM side needs no Imago; only execution does). CODE
      follow-on: §12 declared three new NumericalKnobs in §2
      (`detector_smoothing_window`, `detector_prominence`, `frame_budget`);
      add them to `src/sabsim/spec/records.py` + the study-spec template
      when step-8 is built (Wave 4). Their VALUES are the DESIGN §8.9
      follow-ons tracked above.
- [~] §9.2 THERMOSTAT BORDER — border-integration half RESOLVED and
      FIXED (2026-07-17); the grip-integration half stays open. Found on
      a compute node (stage 5, 2026-07-16) by running the real press: the
      border did not move AT ALL. Measured, max |displacement| per group
      over `run 500` — bottom_grip 0.000000 A, border 0.000000 A,
      interior 0.900304 A, top_grip 0.250000 A (the top grip's number is
      exactly the 0.5 A/ps drive x 0.5 ps, so the drive itself is
      right). CAUSE: `integrator_commands` (`driver/commands.py`) issued
      `fix nve` on the INTERIOR only, and LAMMPS's `fix langevin`
      modifies forces WITHOUT integrating — so the border was
      thermostatted but never advanced, a reflecting wall rather than the
      heat sink `DESIGN.md` §5.2 describes. FIX (2026-07-17): the design
      level had already ruled (`DESIGN.md` §5.2: "the border must
      actually be integrated"), so `integrator_commands` now also emits
      `fix nve_border border nve`; `PSEUDOCODE.md` §9.2/§9.3 reworded (the
      §9.3 "thermostat the INTERIOR ONLY" line contradicted §9.2's use of
      "interior" for the FREE group — now "thermostat the BORDER only,
      integrate both border and interior"); test updated; 89 green.
      STILL a login-node command-list change only — the physical claim
      that the border now conducts heat needs a compute-node re-run,
      which pairs with the still-blocked §9.4 settle work below.
      STILL OPEN — the second question this exposed: whether the GRIPS
      should be integrated at all. They are not, which is why `fix
      setforce` on the bottom grip acts as a READ-BACK mechanism rather
      than a hold. Deliberately untouched by the border fix; entangled
      with §9.4's "what does the settle hold?" decision.
- [x] §9.4 SETTLE SEQUENCING — RESOLVED (2026-07-17, option 1). Found on
      a compute node (stage 5, 2026-07-16): the press reached contact on
      the dual criterion at chunk 37, then `settle_reference` died with
      `ERROR: lammps_extract_fix(): Fix hold_bottom does not exist`. Three
      coupled faults, all fixed. (1) The read-back gauges (`fix
      hold_bottom` setforce, `compute top_reaction`) were created ONLY by
      `pull_drive_commands`, so in the real order (press -> settle ->
      pull) they did not exist for the settle. FIX: factored into a shared
      `grip_hold_and_readback_commands` issued by the press, settle
      (via the shared instance), and pull. (2) Nothing released the press
      drive, so the reference would have equilibrated while still being
      pressed. FIX: new `press_release_commands` unfixes `drive_top`
      (every mode) and the load-mode grip integrator, issued at the top
      of `settle_reference` before the minimize. (3) DEEPER, exposed on
      re-read: under the v1-default LOAD control the driven grip had NO
      integrator, and `aveforce` sets a force without advancing — so the
      surfaces never approached (the SAME class as the frozen border; the
      stage-5 run that reached contact must have been displacement mode).
      DECISION (asked, user chose option 1): handles are RIGID except the
      load-driven grip, which gets its own `fix nve` so the pressure moves
      it; the settle re-freezes it. Option 3 (rigid-platen via `fix
      rigid`) was priced (~same LOC, ~3 extra compute-node read-back
      re-verifications) and deferred — it is a contained one-function
      swap in `press_drive_commands` if grip deformation ever matters.
      settle now also writes the settled reference to a data file and
      returns its path in `ReferenceResult` (the artifact the pull reads).
      DESIGN §5.2/§5.3 + PSEUDOCODE §9.3/§9.4 reworded; 92 tests green.
      STILL a login-node command-list change — the physical claims (load
      press now closes the gap; settle gate passes on a real bond) need
      the compute-node re-run, which also confirms the border fix above.
- [ ] Note on BOTH findings above: neither is visible to the mock, and
      that is structural rather than an oversight in the tests.
      `MockEngine.grip_reaction` returns a scripted number whether or
      not the command stream ever defined the fix it names, and the mock
      integrates nothing, so a group that never moves is
      indistinguishable from one that does. The seam validates the
      ORCHESTRATION; both of these are facts about what the ENGINE does
      with the stream. Worth remembering when judging what a green
      mock-side suite does and does not license — the same shape as the
      `Masses` and `gather_atoms` faults found at stages 2-4.

---

## CODE

- [x] **Three small wins landed 2026-08-26 (Paul's direction).** (1) The
      force models are named in the study file's `[potential]` block
      (`universal_model`, `universal_weights`, `production_weights`,
      `allow_unvalidated`); the environment variables
      `SABSIM_CASCADE_MLIP_MODEL`, `SABSIM_DEEPMD_MODEL`, and
      `SABSIM_ALLOW_UNVALIDATED_POTENTIAL` are gone, and phase-three
      validation checks the model name and that both weights files exist.
      (2) The passed-along `potential` object and the placeholder
      `resolve_potential` stage are gone; every stage reads
      `member.potential`. (3) Classical potentials are REMOVED from the
      code (registry, `classical_force_model`, the in-process cascade and
      lattice-derivation paths, `mlip_reanneal`/`reanneal_commands`,
      `_reanneal_force_model`, `classical_si_stand_in`,
      `snapshot_amorphized_half`, `share/potentials/`) and marked
      deprecated in DESIGN §3.3/§4.5/§4.7, PSEUDOCODE §10.2, and
      ARCHITECTURE §2.1/§2.2/§4.1/§4.4. `material_domain` stays in the
      spec as recorded provenance for the §4.8 recipe; no code reads it.
      Items below that ask for classical-path work are moot. See
      `dev/notes/state-of-sabsim-2026-08-26.md`.

- **Zero-impact runs skip the relaxation, so a null control comes out
  athermal.** `run_cascade_to_fluence` and the out-of-process script
  builder both put the between-impact relaxation INSIDE the per-impact
  loop, so a zero-fluence run issues no `run` command at all and ends
  minimized, near 0 K. That makes the natural null control — same path,
  no bombardment — unusable as a background for any temperature-sensitive
  measure: T-22's coordination profile differenced a 0 K null against
  ~1 ps of warm MD and reported a 30-39 Å "amorphized skin" at 20 eV,
  where the ion cannot have reached. It is still a valid floor for
  vacancy/reach, which is what T-22's headline result rests on. Decide
  whether a zero-impact cascade SHOULD still relax. It is arguably the
  physically honest answer — "no impacts" ought to mean an equilibrated
  surface, not an unequilibrated one — but zero fluence is not a
  production case, so this may be a harness concern rather than a
  mainline one. Do not change mainline cascade code purely to serve a
  test harness without settling that first.

<!-- Tasks related to implementation. -->

- [ ] **Dead code: `_reanneal_force_model` has no callers.**
      `pipeline/live_stages.py:677` still defines the gentle re-anneal's
      force-model resolver, but nothing calls it — the 2026-08-08
      cascade-only re-arch (§3.4) moved the heal and the §3.5 gate into
      the bond job, which left this helper orphaned. It is not harmless:
      it reads as the live re-anneal path to anyone tracing which
      potential the activate stage uses, and it resolves a CLASSICAL
      form, so it actively suggests the activate job still needs
      `LAMMPS_POTENTIALS` when §3.4 says it does not. Delete it, or — if
      the classical in-process path still wants it — call it from there
      and say so, since `driver/cascade.py:379` does still issue
      `reanneal_commands` on that path. Check which before removing.
      Found 2026-08-25. UPDATE 2026-08-28: with the heal back in the
      activate stage (see the reversed re-arch item under DESIGN), the
      activate script needs a heal block again — anneal then minimize
      under the universal model, from the study's `[protocol.reanneal]`
      schedule — so revive or rewrite that block rather than delete it.

- [ ] **PROPAGATE UP THE CHAIN: two changes landed in CODE on 2026-07-22
      that the documents above do not yet describe.** Both are real
      design decisions, not implementation detail, so they belong in
      ARCHITECTURE/DESIGN before they drift.
      (1) **Trajectory recording is now a RUN-TIME MODE.** `sabsim run`
      grew `--dump-visuals` and `--dump-stride`; every dynamic stage —
      the cascade and re-anneal of each half, the press and settle, and
      each pull rung — records only when asked. Two design points to
      write down: recording is OPERATIONAL rather than physical (two
      runs differing only in it are the SAME study), which is why it is
      a flag and not a spec field and why it lives in
      `pipeline/run_options.py` rather than being threaded through the
      contract runner; and the pull dump, which used to be written
      unconditionally at 1.3 GB per rung, is now conditional — so the
      DEFAULT run got dramatically smaller, and the §8 "snapshot
      selector reads the dump back" language in `commands.py` is
      ASPIRATIONAL, since nothing actually reads it (the analyzer
      measures from the thermo log). Fix that comment or build the
      selector. FRAMES ROLE NOW SETTLED at design level (2026-07-27):
      pinned in `PSEUDOCODE.md` §9.5 / §9.6 / §3 — the pull's reduction
      runs off the live per-chunk SERIES, and the strided dump is a
      SEPARATE coordinate archive written ONLY when a consumer will read
      it (step-8 characterization in the run that feeds Imago / RDF /
      structural descriptors, OR a person via `--dump-visuals`). So the
      reduction no longer "reads frames" (§9.6 now matches the code); the
      `--dump-visuals` half of the write-trigger already exists; the
      characterization half — and the selector that reads this archive —
      lands when step 8 is built. Remaining CODE: build the selector, and
      reword the `commands.py` comment to say the archive is
      consumer-gated, not dead. See also the §13 resume ledger, which is
      the SERIES made durable — a different artifact from this archive.
      (2) **The potential is now resolved per material from ONE
      registry.** `cascade_potential.classical_force_model` serves the
      re-anneal and the press/pull, which previously hard-coded
      `sw Si.sw` in three separate places (one of which mapped EVERY
      atom type to Si — harmless for Si/Si, wrong for anything else).
      DESIGN §4.5 still describes the old arrangement. Also record the
      `SABSIM_ALLOW_UNVALIDATED_POTENTIAL` opt-in: the §4.7 refusal
      stays the default, and bringing up a new material is an explicit,
      per-run, job-script-visible choice whose results are provisional.

- [ ] **The non-cubic box fix lives in a JOB SCRIPT, not the builder.**
      `jobs/bulk_si/run_activation.py:orthogonalize_in_plane` now handles
      a hexagonal surface by swapping in the orthogonal `(a, a + 2b)`
      supercell — needed because alpha-quartz(001) leans at EXACTLY
      LAMMPS's skew limit (legal only by a floating-point tie) and
      because the activation gate's in-plane minimum-image assumes an
      orthogonal cell, so a leaning box would have mis-measured
      neighbour counts SILENTLY rather than crashing. That fix belongs
      in `structure/slab_builder.py`, where `build_standalone_half` and
      `build_facing_pair` can use it. Until it moves, ANY non-cubic
      material going through `sabsim run` still has the problem —
      including `si-sio2`.

- [ ] **`si-sio2` names a crystal file that does not exist.**
      `dev/templates/study_spec.toml` points wafer B at
      `src/sabsim/structure/data/sio2_beta_cristobalite.cif`; there is no
      such file, so the member has never been runnable. We now ship
      `sio2_alpha_quartz.cif` (used by the new `sio2-sio2-reference`
      member). Decide deliberately: quartz is what we have, but
      beta-cristobalite is cubic and lattice-matches silicon far better,
      which is presumably why it was named. Either obtain the
      cristobalite file or re-point the member and record WHY the
      lattice match got worse. CIF LEAD (Paul, 2026-08-21): we ran Si,
      SiO2, and LiNbO3, so CIFs for all three should exist — worst
      case, produce them from the `.skl` files under `~/olcao/jobs/` or
      `~/imago/jobs/`. Shipped today: Si diamond + `sio2_alpha_quartz.
      cif`; the cristobalite and a LiNbO3 CIF are what to recover. Do
      this with the batched node validations.

- [~] **Silica activation reference — STAND-IN shipped, real numbers
      still open.** `share/activation/O_Si.toml` now EXISTS as a
      `real = false` stand-in (Phase-3 item 6, 2026-08-21), so the gate
      RUNS on silica instead of reporting UNRESOLVED for a missing file.
      The 2026-07-22 run confirmed the cascade itself works on silica
      (42 impacts at 75 eV, zero sputtered out of 7920). STILL OPEN (the
      real anchor): a DFT/experimental Si-O first-peak g(r), a
      coordination band and a ring criterion for amorphous silica, and
      silica's own energy x dose sweep (the stand-in reuses silicon's
      operating point + a literature-guided 1.62 A peak / 2.0 A cutoff).
      Same for `Li_Nb_O.toml` (LiNbO3 stand-in, also shipped item 6).

- [ ] **MLIP INTEGRATION STATUS — the socket is built, the plug is
      prototyped, they have NEVER been connected (2026-07-22).** The whole
      MLIP / ALF / committee layer is design-complete and its riskiest
      claim is prototype-proven, yet it has ZERO integration with the
      running pipeline. This item makes that gap first-class so the
      consumer side is never assumed from the producer side. It
      COMPLEMENTS, and does not duplicate, two open items above: the
      producer-side validation ("train + freeze an ensemble once a GPU +
      step-1 data exist") and the DESIGN write-up ("document the
      backend-plugin mechanism"). Those cover MAKING a committee; this
      covers CONSUMING one in the eight-stage pipeline.
      WHAT EXISTS. Design: `DESIGN.md` §4 (the most-filled section),
      `ARCHITECTURE.md` §2.3, `VISION.md` principle 2. Prototype:
      `prototypes/alf_deepmd/` — the two ALF contracts
      (`train_DEEPMD_ensemble_task`, `DEEPMD_ASE_load_ensemble`) plus the
      ANI-HDF5 -> DeePMD converter, round-trip unit-tested. It is NOT
      imported by `src/` (`src/sabsim/__init__.py` states this outright).
      WHAT DOES NOT (revised 2026-08-28). Nothing trains a committee,
      loads one, or computes an uncertainty. Every dynamic stage runs
      on the universal foundation MLIP named by the study file's
      `[potential]` block (`deepmd_model` in `commands.py`, a committee
      of ONE); `uncertainty` is hard-coded 0.0 and only ONE realization
      runs; the bootstrap has `generate` / `label` / `harvest`
      (`src/sabsim/bootstrap/`, LEDGER T-26 / T-27) but no `train`.
      THE SEAMS, and what fills each today (committee = the trained
      DeePMD ensemble; stand-in = the universal foundation MLIP wearing
      the same `ForceModel` seam, which is WHY the swap is deferrable):

      | Stage (step)              | Design -> runs on     | Today -> runs on   |
      |---------------------------|-----------------------|--------------------|
      | bootstrap loop (producer) | trains the committee  | gen/label/harvest  |
      | 2  [potential] lookup     | trained committee     | foundation MLIP    |
      | 4a cascade + ZBL          | foundation MLIP + ZBL | same (correct)     |
      | 4b heal (in activate)     | foundation MLIP       | same (correct)     |
      | 6-7 press / settle / pull | committee             | foundation MLIP    |
      | 8a analyzer (sigma)       | committee spread      | one run, sigma=0   |
      | 8b characterization       | all-electron vs cmte  | mocked             |

      Rows 4a and 4b are correct as-is: the violent cascade AND the heal
      stay on the foundation MLIP by design (STRUCTURAL 1b, §3.4, §4.7 —
      revised 2026-08-28), so the production committee is never trained
      on cascade distortion or on Ar, and the activated surfaces do not
      depend on the committee. Every other "committee" row runs real MD
      on a stand-in that carries no uncertainty.
      THREE COMMITTEE ROLES, all absent, all from one source (which is why
      its absence zeroes all three at once): (i) the production potential
      for the gentle stages (6-7); (ii) the uncertainty SIGNAL —
      `MLMD_calculator` sigma_E / sigma_F feed 8a's reported uncertainty,
      STRUCTURAL 3's interface-fidelity gate, and the §7.3 live-abort
      monitor (`DESIGN.md` §4.4, §7); (iii) the active-learning DRIVER —
      the same sigma steers uncertainty-triggered + UDD-biased sampling in
      the bootstrap (`DESIGN.md` §4.4-§4.5).
      INTEGRATION CHECKLIST (the order is a DEPENDENCY chain, since the
      lower items block on a committee existing at all):
      - [~] Stand up ONE bootstrap pass end to end (generate ->
            VASP-label -> train -> refine) emitting a fingerprinted
            committee (`DESIGN.md` §4.5, `PSEUDOCODE.md` §11). generate
            / label / harvest BUILT (2026-08-26, T-26 / T-27); `train`
            and `refine` block the rest — they need the ALF bridge and a
            dumped member run that reaches the pull (Collection 2).
      - [ ] Make the `[potential]` lookup return that member's committee
            (N weight files) instead of the single foundation-MLIP file
            (`spec/loader.py`, `live_stages.py`).
      - [ ] Emit the committee `pair_style deepmd` line (several models,
            the spread as output) for the press/settle/pull
            (`deepmd_model`, `commands.py`); leave the cascade and the
            heal on the foundation MLIP.
      - [ ] Compute committee sigma along the trajectory and thread it into
            the measure vector, replacing the hard-coded `uncertainty=0.0`
            and lighting up the interface-fidelity gate (`live_stages.py`).
      - [ ] Run the ensemble loop — the `amorphization_count` seeds are
            already READ but only one realization runs today
            (`live_stages.py`).
      Keep this item open until the table's "Today" column matches its
      "Design" column; it is the honest bridge between STRUCTURAL 1b
      (design: RESOLVED) and a pipeline that actually runs on the MLIP.

- [x] Wave-0 walking skeleton BUILT and tested (2026-07-13) — the
      `ARCHITECTURE.md` §5.3 Wave-0 target reached: the Tier-A thread runs
      end-to-end on Si/Si to an HONESTLY UNTRUSTED measure. What exists
      under `src/sabsim/`: the study-spec loader + records (`spec/`, no
      hidden defaults, `PSEUDOCODE.md` §1.4), the sequencer with the
      `run_to_contract` guard plus the measure and exec-artifact schemas
      (`pipeline/`, `PSEUDOCODE.md` §1), stub stages that pass through
      honest verdicts (`pipeline/skeleton_stages.py`), and the minimal
      Si-(100) slab / facing-pair builder (`structure/si_slabs.py`,
      `PSEUDOCODE.md` §7 minus the matcher). 25 tests pass (loader 9,
      sequencer 11, slabs 5). Commits `8537d69`, `c576c9e`, `1ca43cc`.
- [ ] NEXT — replace the skeleton stubs with the real Si/Si run, in
      slices, each landing behind its already-frozen contract. Order:
      1a. GENERAL slab builder — DONE (2026-07-14). ONE
         `structure/slab_builder` (retired the Si-only `structure/si_slabs`
         stand-in) reads a crystal from a CIF (the authoritative
         structure, `DESIGN.md` §1.2) plus a Miller face, cuts the slab
         (pymatgen `SlabGenerator`), and assembles the facing pair through
         pymatgen's Zur-McGill matcher (`DESIGN.md` §2.3 — the ADOPTED
         algorithm, NOT hand-written). No per-material or per-pair script:
         Si/Si is just the first INPUT and exercises the matcher's
         identity/null case (`DESIGN.md` §2.548). `MaterialKnobs` gained a
         CIF source (`spec/records.py`); the loader and study-spec template
         moved with it (no hidden defaults, §1.4). Ships a real Si diamond
         CIF as reference data. 7 unit tests on Si/Si (build, identity
         match, gap, box, type map, LAMMPS round-trip). Login-node geometry
         (pymatgen + ASE membrane), NO force engine. Commit `PENDING`.
      1b. Wire the builder into the pipeline — DEFERRED, coupled to the
         compound build (wave 3). `build_slabs` / `assemble_pair` cannot
         switch to the real builder yet: the live study runs the SiO2/Si
         member, whose real build needs the strained-mismatch assembly
         (`DESIGN.md` §2.4), the SiO2 CIF, and surface-energy termination
         — all wave-3 / execution-layer work. Slice 1a REFUSES a real
         mismatch rather than faking it, so wiring waits for that wave (or
         a Si/Si-only integration path). The skeleton stub stands until
         then; the pipeline stays green end-to-end.
      2. Driver command-generation — DONE (2026-07-14). New `driver/`
         package: `driver/commands.py` maps a `BuiltPair` + protocol/
         numerical knobs to the ordered LAMMPS command stream for the
         press (§9.3) and pull (§9.5). PURE `{value,unit}` -> command
         mapping (metal-units conversion + pressure->force), no LAMMPS.
         The force-model line is a PARAMETER (`ForceModel`): classical
         stand-in (`classical_si_stand_in`) now, trained MLIP
         (`deepmd_model`) later — BOTH served by one generator. BOTH
         control modes generated (load = ramped `aveforce`, displacement
         = `fix move`), one command apart (`DESIGN.md` §5.2). Region
         carving, bias-removed Langevin thermostat (§5.2), grip drives,
         and strided recording all pure functions. 15 unit tests; full
         suite 42 passed. NOTE: the mid-run STOP conditions (dual contact,
         separation) are slice 3, and the region thicknesses + load-ramp
         schedule are documented §3/§5.9 stand-ins, flagged in code.
      3. Control + analysis math — DONE (2026-07-14). `driver/analysis.py`
         is the pure numerics the live driver reads back with:
         density dividing-surfaces + interface opening (§2.6), the
         no-impact gate + DUAL contact criterion (§9.3), the two
         settle-reference gates (§9.4), and the displacement-windowed
         averaged force curve (leading warm-up dropped), its
         re-expression vs interface opening, the separation point, and
         the atom-count gate (§9.6). PURE array math, NO LAMMPS. 13 unit
         tests; full suite 55 passed. NOTE deferred: the bonded-quality
         grading (`contact_quality`, cross-interface bonds + contact
         fraction) reuses §8 geometric machinery not yet built; the
         quasistatic margins are documented §5.9 stand-ins.
      4. Bulk-relaxation execution — MOCK SIDE DONE (2026-07-14). The
         FIRST, smallest use of the force engine: relax the bulk under the
         current (classical stand-in) model to DERIVE the lattice, so the
         hardcoded 5.43 A stand-in is retired (`DESIGN.md` §2.2 cold
         start). Introduced the narrow engine seam `driver/engine.py`
         (`Engine` ABC + `MockEngine`) so the orchestration is written
         ONCE and tested with NO LAMMPS. `driver/bulk_relax.py` builds the
         `p p p` box/relax minimize stream and derives the cubic lattice
         from the relaxed box; `structure/slab_builder.write_bulk_data`
         writes the bulk block. 9 tests; full suite 64 passed. COMPUTE
         SIDE NOW DONE (2026-07-16, commit `e1a1e30`): the real adapter
         runs, `Si.sw` loads, and the emitted stream parses. SW silicon
         relaxes to a = 5.4309 A at -4.3366 eV/atom, matching SW's own
         parameterisation (5.431 A; 2*epsilon = 4.3366). Started
         deliberately 2% DILATED so the answer could not be confused
         with a relaxation that did nothing: it moved 5.5386 -> 5.4309 A,
         shedding 1.3812 eV. Caught one real bug the mock could not —
         both data writers omitted the `Masses` section (ASE defaults
         `masses=False`), which LAMMPS refuses outright; a data file
         identifies species ONLY through `Masses`, so ASE read it back
         with the right atom COUNT and every Si silently relabelled H,
         which is exactly why the count-only round-trip test passed over
         it. NOTE for later materials: Si is the benign case where the
         model and published lattices nearly coincide (5.4309 vs
         5.4300), so this run is a WEAK demonstration of why §2.2 exists;
         the gap should matter far more for SiO2 and LiNbO3.
      5. Press/pull execution layer — MOCK SIDE DONE (2026-07-14).
         `driver/press_pull.py` is the three §9 control loops — press to
         the DUAL contact criterion (§9.3), settle to the gated zero-load
         reference (§9.4), pull to complete separation then reduce (§9.5,
         §9.6) — written ENTIRELY against the `Engine` seam, so each
         mid-run decision is exercised against a SCRIPTED `MockEngine`
         (opening closes, stress turns positive, force decays) with NO
         LAMMPS. Extended the seam with `positions` / `normal_stress` /
         `grip_reaction`. 6 tests; full suite 70 passed. STATUS:
         (a) the REAL `Engine` adapter — DONE and VALIDATED (2026-07-16,
         commit `e1a1e30`, LAMMPS 22 Jul 2025, at 1 and 4 MPI ranks). All
         four `# VERIFY` items resolved, each against an INDEPENDENT
         reference rather than its own assumption: `extract_fix` is
         0-BASED (fz = index 2), `pzz` is positive in compression and so
         already matches §9.3 (the feared flip was unnecessary),
         `gather_atoms` returns the builder's own write order, and
         `get_thermo` is not cached across chunks. Two real faults fixed:
         `positions` called `lmp.numpy.gather_atoms`, which does not
         exist, and the grip reactions came back tension-NEGATIVE while
         the mock scripted tension-POSITIVE — §8.4 would have integrated
         a NEGATIVE work of separation while failing nothing. The
         `Engine` contract now STATES the sign convention (positive in
         tension, load-cell sense) instead of leaving each implementation
         to guess; that silence was the actual defect.
         (b) PARTLY EXERCISED on a compute node (stage 5, 2026-07-16),
         then UNBLOCKED at the design/code level (2026-07-17). The press
         reached contact on the dual criterion (chunk 37, tiny 32-atom
         Si/Si cell) but the settle died; the §9.2 border and §9.4 settle
         findings are both now resolved (see the PSEUDOCODE items above):
         the border is integrated, the grip gauges are shared across all
         three phases, the press drive is released before the settle, the
         load-driven grip has its own integrator (option 1), and the
         settle writes the reference data file the pull restores from.
         COMPUTE-NODE RE-RUN DONE (2026-07-17, single rank, exit 0): the
         full press -> settle -> pull SEQUENCE now runs end to end on real
         LAMMPS via a throwaway driver (`jobs/bulk_si/run_press_settle_
         pull.py`, gitignored) — the §9.4 settle CRASH is gone (settle ran
         and gated), the pull runs and reduces with NO lost atoms, and the
         load-grip integrator + border integration run clean. It ALSO
         found and FIXED a real load-magnitude bug: `fix aveforce` sets the
         per-atom AVERAGE force but `press_drive_commands` passed the TOTAL
         P*A, so the grip felt N_grip x too much — a nominal 500 MPa read
         back 72730 bar (~7.3 GPa). FIXED by dividing by `count(top_grip)`
         at runtime; the re-run then read 4014 bar, the right order.
         (c) the bonded-quality grading (§8 machinery, still deferred).
      FOUR items the 2026-07-17 re-run left open (none a settle/border
      regression):
      1. RAMP SAWTOOTH — CONFIRMED on a compute node (2026-07-17). The
         load drives with `ramp(0.0,-F)/count(top_grip)` while
         `press_and_bond` advances in a LOOP of short `run` chunks, and
         LAMMPS `ramp()` interpolates over the CURRENT run's timesteps.
         A `fix ave/time` probe of `v_press_fz` over eight 200-step chunks
         (`jobs/bulk_si/probe_press_force.py`) showed it climb 0 -> target
         within each chunk and RESET to the one-step value at every 200-
         step boundary, perfectly periodic — so the load never rose once
         and HELD, and its time-average was roughly half the target.
         FIXED (2026-07-17): the drive now uses the ABSOLUTE step via a
         boolean blend — `step<R` selects the rising fraction `step/R`,
         `step>=R` holds at 1 (LAMMPS has no scalar `min()`) — over a
         documented §5.9 rise-time STAND-IN `_LOAD_RISE_TIME_STANDIN =
         10 ps` (commands.py). Re-probed: `v_press_fz` climbs once over
         10 ps then holds flat, with NO reset at any chunk boundary. The
         real load RISE-TIME as a first-class SPEC knob stays a §5.9
         follow-on. A press-drive issue, distinct from the settle work.
      2. CONTACT NOT REACHED at the now-correct gentle ~0.4 GPa load
         within the smoke budget — EXPECTED, a tuning matter (more steps,
         a modestly higher test load, or a smaller start gap), not a bug.
      3. REGISTRY CAVEAT: a same-material identity pair (Si/Si) tiled and
         stacked is in PERFECT lateral registry, so pressing it heals
         toward BULK (gamma_AB -> 0), not a bond — no number from the
         smoke test is a real adhesion measurement. The real pipeline
         breaks registry via activation (step 4) and the §2.6 lateral-
         shift ensemble variable, both absent here. A DESIGN §2.6/§3 point
         for the same-material reference, not just the driver.
      4. FOUR-RANK LAUNCH: plain `srun -n 4 python` ran 4 INDEPENDENT
         serial copies (each rank 0 of a size-1 world); `srun --mpi=pmix`
         fails on this cluster (PMIx psec/munge). The known-good multi-
         rank launcher is OpenMPI `mpirun` in the allocation (already how
         stage 4 validated 4-rank gather order). A launcher-wiring task,
         not a code gap.
      Slices 1-3 are login-node work; slices 4-5 are compute-node
      integration (the two that need LAMMPS). The Wave-4 knob follow-on
      (three §2 NumericalKnobs) is tracked in the PSEUDOCODE section
      above.
- [x] Phase-sequence press + settle + pulls into a `BondDebondResult` —
      DONE (`run_bond_debond_md_live`, `pipeline/live_stages.py`): it
      presses, settles (writing the reference data file), then pulls each
      rung on a FRESH engine restored from that file. The per-rung-filename
      follow-on at the end of this note is also resolved — `_pull_rung_paths`
      gives each rung its own `pull_<slug>/` with its own log, trajectory,
      and `checkpoints/`. Checkbox reconciled 2026-08-07. Original note:
      (promoted 2026-07-15 from a slice-5 sub-note so it is not lost when
      slice 5 is ticked). `driver/press_pull.py` has the three §9 control
      loops as separate functions, but nothing yet drives them in order
      with a FRESH restore of the settled reference per pull rung and a
      persistent-engine lifecycle (`PSEUDOCODE.md` §9, `DESIGN.md` §5.4).
      This is real-adapter territory — the restore/lifecycle only exists
      against a live LAMMPS instance — so it lands with the compute-node
      adapter work below. UNBLOCKED (2026-07-17): the §9.2 / §9.4
      decisions it waited on are resolved, and `settle_reference` now
      writes the reference data file itself, so the sequencer just threads
      that path into each pull's `restore`. What stage 5 pinned down about
      the lifecycle, so it need not be re-derived: press and pull EACH
      re-read a data file (`preamble_commands` issues `units` +
      `read_data`), and LAMMPS rejects `units` once a box exists, so each
      needs a FRESH engine; settle issues no `read_data` and so shares the
      press's engine (which is WHY the shared grip gauges installed at
      press setup are still alive for the settle). The settled reference
      is written out (`write_data`) between settle and pull, because the
      pull restores from a FILE — handing it the original pair data would
      discard the press. Trajectory-dump LOCATION now FIXED (2026-07-17):
      `pull_at_rate` / `pull_script` take a REQUIRED keyword
      `output_directory` and compose the dump path with
      `pull_dump_file(output_directory, member)`, so run output lands under
      the run's scratch job directory, never the CWD (this library owns
      only the dump NAME, which §8 reads back by). Verified on a compute
      node: the dump landed in scratch and the repo root stayed clean.
      Follow-on for the multi-rung ladder: the name is per-MEMBER, so
      several pull rungs would overwrite one file — add the rate/rung to
      the name when the ladder is sequenced.
- [ ] Bonded-quality grading — `contact_quality` / cross-interface bonds
      / contact fraction (promoted 2026-07-15 from slice-3 and slice-5
      sub-notes). `driver/analysis.py` computes the geometric contact
      criteria but NOT the bonded-quality grade, which reuses the §8
      geometric machinery (bond cutoffs from partial g(r), the grid-based
      `contact_area_fraction`, `DESIGN.md` §6.4) that is not built yet.
      Ties to the §8 characterization build (Wave 4); tracked separately
      here so the grade is not forgotten inside the press/pull ledger.
- [x] Apply the atom-count conservation gate in the pull (`/refine` #4) —
      DONE (verified in code 2026-08-07). `pull_at_rate`
      (`driver/press_pull.py`) captures `starting_atom_count` into the
      ledger at pull start (the §5.6 baseline, resume-safe), reads the
      final count at the end, calls `atom_count_conserved`
      (`driver/analysis.py`), and carries the verdict as
      `PullResult.atoms_conserved`; the analyzer (`run_analyzer_live`)
      then refuses to integrate a pull that lost atoms (§9.6). The original
      note ("pull_at_rate never calls it and PullResult omits it") is now
      stale.
- [x] Labeled-group ownership (`/refine` #3) — RESOLVED option C
      (2026-07-15). The DRIVER carves the four depth zones (a frozen base
      OR two grips, the thermostat border, the NVE interior) from the
      builder's per-wafer z-ranges at open time; the builder stays
      protocol-ignorant, recording only the zone GEOMETRY. The activated
      skin is the ONE exception — a MEASURED, irregular atom set
      (`PSEUDOCODE.md` §10.7), not a depth cut — so it travels as an
      explicit atom set from activation to the press. The code already
      carved by depth (`driver/commands.region_group_commands`), so this
      was a docs-catch-up: `LabeledGroups` (§3) now holds the z-ranges +
      `activated_skin`, §7.5 emits `record_zone_geometry`, §9.2 CARVES the
      zones, `DESIGN.md` §2.6/§2.7/§5.4/§6.2 were reworded, and the
      pipeline placeholder (`skeleton_stages._LABELED_GROUPS`) + the
      `BuiltPair` docs were aligned. NAMES: identity stays A/B (spec,
      atom tags, the §6 γ_A/γ_B math); the A = bottom / B = top assembly
      invariant is now stated loudly wherever the z-ranges or tags appear
      (decided 2026-07-15). 72 tests still green. Commit PENDING.
- [x] Widen the MeasureVector seam to carry VERDICTS (`/refine` #6). The
      `PSEUDOCODE.md` §4 seam is a five-field record — provenance,
      geometry, measures, verdicts, checks — but the code
      `MeasureVector` (`pipeline/measures.py`) carries only `measures`,
      so the press outcome is LOST: `run_analyzer`
      (`pipeline/skeleton_stages.py`) emits two measures and never reads
      `result.press`, dropping the `bonded` / `contact_quality` verdict
      the §4 analyzer is supposed to read once and surface. Add a
      `Verdicts` record (`bonded`, `contact_quality`), hang it on the
      vector, and have `run_analyzer` populate it from the
      `PressOutcome`. FIXED below in the same session.
- [x] Relation guards — DESCOPED (2026-07-14, was `/refine` #7).
      Comparison judgment — which systems to compare, which variables
      make a FAIR contrast, whether a difference is entailed or
      incidental — stays the USER's to make by hand. There are too many
      ways to modify a system, and not every modification degrades a
      comparison equally, for an automated confound-check to earn its
      rigidity; a strict guard would obstruct more than it protects.
      This rips nothing out: `DESIGN.md` §1.1 already keeps relations
      REPORT-ONLY, and `_evaluate_one_relation` (`pipeline/sequencer.py`)
      already computes and reports the ratio. The validator-computed
      `confounded` / `controls_disagree` flags (`spec/records.py`) stay
      as informational provenance a user MAY read. We deliberately do
      NOT build the caveat-surfacing / verdict-withholding machinery once
      planned here, so this effort never competes with core capability.
- [x] SERIAL FILE I/O under MPI — root-caused and fixed (2026-07-21).
      SYMPTOM: the 16-rank energy sweep (job 15040489) died on its FIRST
      grid point, then hung until the 8 h wall clock killed it; 15 of 16
      ranks raised `StopIteration` out of `read_standalone_half`, meaning
      ASE parsed ZERO structures from a slab file that was complete and
      well formed on disk. CAUSE: ASE's `read`/`write` become MPI
      COLLECTIVES whenever it detects mpi4py — rank 0 does the I/O and
      broadcasts to all ranks — so our `if rank == 0:` guards posted an
      ASE broadcast from one rank while the other 15 posted our own
      `Barrier()` on the SAME communicator. Mismatched collectives on one
      communicator is undefined behavior, and in ASE's
      `parallel_generator` a non-root rank handed the resulting `None`
      yields nothing, so `next()` raises exactly that `StopIteration`.
      EVIDENCE (probe jobs 15118944 / 15122599, `jobs/bulk_si/
      probe_readback.py`): 16 ranks reading a SETTLED file all succeed;
      the freshly written file was byte-identical (same MD5) and read
      serially in 0.07 s; `AveCPU` 3:43:49 over 15:05 x 16 ranks = 15
      ranks spinning + 1 blocked; and a `faulthandler` watchdog dumped
      the stack `ase/parallel.py:180 broadcast <- ase/io/formats.py:821
      read`. FIX: `parallel=False` on all six package ASE calls plus the
      sweep's, and `MPI.COMM_WORLD.Abort` in the sweep so a dead rank
      ends the job instead of renting a node for 8 h. NOT a slowdown —
      per-rank reads measured 0.02 s vs 0.27 s for the broadcast path.
      PROPAGATED UP THE CHAIN: `ARCHITECTURE.md` §4.1 gains a SECOND
      discipline (SABSIM owns the communicator; no library may post a
      collective on it unasked), `DESIGN.md` §2.6 gains the seam rule
      (one rank writes, barrier, every rank reads for itself) and its
      §5 launcher fact was corrected (`srun -n N python` -> `mpirun -np
      N python`), and `PSEUDOCODE.md` §7.1/§11 carry `[SERIAL I/O]`
      notes. GUARDED: `test_serial_io_invariant.py` walks the shipped
      source with `ast` and fails any ASE call lacking `parallel=False`,
      which is what protects call sites nobody has written yet — the
      real risk, since this bug is INVISIBLE to single-process tests.

- [x] **Coincidence matcher PHASE B + §2.4 pre-cascade relax — DONE
      (2026-08-07).** The dissimilar-pair build is complete: a mismatched
      pair now emerges on ONE commensurate cell and is bombarded relaxed.
      Landings across `pipeline/live_stages.py`, `structure/slab_builder.py`,
      and `driver/{cascade,commands}.py`:
      (1) strained-tiling core — `even_split_shared_cell` (twist-general,
          polar decomposition) + `tile_slab_to_shared_cell` (non-diagonal
          `make_supercell` + in-plane strain), commits `75e0690` / `3deaf55`;
      (2) footprint = TUNABLE `target_footprint_area` knob, retiring the
          hardcoded `_LATERAL_REPEAT=10` (`_footprint_repeat`; the default
          reproduces the pinned 10x10 Si cell), commit `1127d81`;
      (3) §2.5 thickness wired as a FLOOR + the last three sizing hardcodes
          (`_MIN_SLAB_THICKNESS` / `_MIN_VACUUM` / `_BULK_CELLS_PER_AXIS`)
          lifted to spec knobs, commit `b823133` (see the slab-thickness
          convergence item in DESIGN);
      (4) §2.4 out-of-plane relax — `cascade_prerelax_commands` (a fixed-
          cell `minimize` under the cascade potential) issued before the
          first impact, so a strained slab takes its Poisson response at
          fixed lateral cell, commit `b92418f`.
      316 tests. Retires the `_LATERAL_REPEAT` / `_MIN_SLAB_THICKNESS`
      stand-ins the "Run ONE Si/Si member" item above still names as
      constants.
- [ ] Node-validate the MISMATCHED build end to end (opened 2026-08-07,
      from Phase B above). Si/silica emerges commensurate in unit tests,
      but the coincidence matcher's real output has only run the
      activate -> assemble -> bond chain node-side for Si/Si (identity). Run
      a genuine mismatch (Si/SiO2) on a compute node — the first exercise
      of the strained build + pre-cascade relax on real LAMMPS. Gated on
      the `si-sio2` CIF fix and silica activation references (both open
      items above).

- [ ] **Reconcile the universal-cascade re-arch tails — docs and dead
      code lagging a flow that already changed (A.4, review
      2026-08-21).** The code went cascade-only + universal-default,
      but leftovers still describe the old flow: (1) `mlip_reanneal` /
      `reanneal_commands` (`cascade.py`) are ORPHANED — no caller in
      the cascade-only path — remove or archive; (2) gate module +
      function docstrings say "re-annealed surface"
      (`activation_gate.py`), the revision renamed it "healed"; (3)
      PSEUDOCODE §10.2 / DESIGN §3.3 still call the cascade potential a
      "config-selected CLASSICAL generator, NOT the MLIP", but the
      default is now universal MLIP + ZBL (§4.7); (4) the `cascade.py`
      header still frames the re-anneal (§10.5) and gate (§10.6) as
      "land next"; (5) PSEUDOCODE §1 omits the live `derive_lattices`
      stage (step 2b) the sequencer runs. Items (1)-(2) and (4)-(5)
      are cosmetic (comment / dead-code / a missing pseudocode stage,
      no behaviour change). Item (3) is NOT cosmetic (refine catch,
      2026-08-21): "classical generator runs the cascade" is the
      STRUCTURAL-1b framing in ARCHITECTURE §2.3 + DESIGN §3.3/§4.8,
      which the universal-cascade re-arch superseded in §4.7 + code but
      never propagated UP. Reconcile by DISTINGUISHING the UNIVERSAL
      FOUNDATION model (does the cascade by default, §4.7) from the
      per-pair COMMITTEE (still never does cascades — STRUCTURAL 1b's
      rationale is intact for it). ARCH §2.3 + DESIGN §3.3/§4.8 +
      PSEUDOCODE §10.2 edit together; VISION is unaffected.
      DOC-CHAIN PROPAGATION DONE 2026-08-21 (Paul blessed the framing):
      item (3) landed — ARCH §2.3 (4 spots), DESIGN §3.3/§4.5/§4.8, and
      PSEUDOCODE §10.2/§11 now state universal foundation MLIP + ZBL is
      the cascade primary (classical + ZBL the fallback), the universal
      model is ALSO the bootstrap generator for the press/settle/pull
      configs, the per-pair committee is the production potential +
      uncertainty source, and the hand-built-DFT seed step is retired
      (§4.5). Remaining A.4 work is the CODE-side cosmetics — (1)
      orphaned `mlip_reanneal`, (2) gate docstrings "re-annealed" ->
      "healed", (4) the `cascade.py` header, (5) the PSEUDOCODE §1
      `derive_lattices` omission. Minor terminology: "seed committee"
      in §4.8 part 2 / §11 now reads as the FIRST ALF committee
      (anchored by the starting collection), NOT the generator — left
      as-is since the anchor role is unchanged; clarify only if it
      confuses a reader.
      UPDATE 2026-08-28: the "classical + ZBL the fallback" wording that
      the 2026-08-21 propagation left in place is now GONE from ARCH
      §2.1/§2.3/§5, DESIGN §2.2/§2.6/§3.3/§3.6/§4.5/§4.7/§4.8/§5/§7.4 and
      PSEUDOCODE §1/§10.2/§11/§12 (Paul: no fallbacks of any kind), and
      §11.2's "seed committee" is retired in favour of
      `build_collection1`. The CODE-side cosmetics (1), (2), (4), (5)
      remain; (1) is overtaken by the heal returning to activate.
- [ ] **Small code/doc drifts surfaced by the review (A.5,
      2026-08-21) — reconcile each toward the correct side.** (1)
      `loader.py` enforces only `len(pull_rate_ladder) >= 1`, but
      PSEUDOCODE §2 and the field doc say ">= 3 rates over a decade".
      (2) The g(r) auto-pass scores FIRST-PEAK position
      (`activation_gate.py:419`); PSEUDOCODE §10 specifies a coarse
      SECOND-shell RMSD — the discriminator the docs name is not the
      one scored. (3) Residual strain is stored as a rotation-
      invariant SCALAR (`SurfaceMatch.residual_strain`), but PSEUDOCODE
      §7.6 requires the strain TENSOR with shear kept plus a
      post-enumeration `max_component <= tolerance` cut — shear
      provenance is lost today. (4) The `ZSLGenerator` call omits the
      `max_angle_tol` and `lowest=false` (`slab_builder.py:378`) that
      PSEUDOCODE §7.6 maps the one physical knob onto.
- [ ] **Analyzer is a hardcoded tuple, not the §6.7 registry, and M1
      is not per-rate (review 2026-08-21).** `run_analyzer_live`
      (`live_stages.py`) emits a fixed Measure tuple; DESIGN §6.7 /
      PSEUDOCODE §8.1 specify a `registered_measures()` registry the
      gate reads by name. And M1 (mechanical W_sep) collapses the rate
      ladder to the single slowest separated rung and emits ONE record,
      so the §6.5 rate-ladder-monotonicity check has no per-rate
      records to read; DESIGN §4 / §8.4 want one record PER pull with
      the rate in provenance. Related to the M2/M3/M5 measures build
      (already tracked) and the committee-sigma item (uncertainty is
      still hardcoded 0.0).
- [ ] **Spec-layer static checks the review found deferred or absent
      (2026-08-21).** (1) The §1.5 "pair species-union == potential's
      global type map" check — documented as the SHARPEST static check
      — is in practice deferred to a hardcoded `KNOWN_SPECIES` set
      (`loader.py`); the union-equals-type-map test is not computed at
      load. (2) The §2.5 deferred thickness check (`slab_thickness >=
      activated_depth + minimum_bulk_thickness`) is never REGISTERED to
      fire once its input exists. (3) No object->file serializer, so
      the §1.7 exact round-trip is one-way (file->object) only.
      (`controls_disagree` and the difference-set are separately
      tracked / descoped.)
- [ ] **Universal cascade over-coordinates Si — the coordination
      metric blocks the `validated=True` flip (T-10, review
      2026-08-21).** Full-fluence universal DPA-2.4-7M activation of a
      ~2880-atom Si slab (jobs 16324481 + 16345032) FAILED the §3.5
      gate on the COORDINATION metric — measured ~0.916/0.913 vs the
      allowed band (0.05, 0.6) — while rdf, ring, and depth all passed.
      An energy bracket 5/10/15/25/40 eV (jobs 16365791/92,
      16370749/50/51) all failed coordination (0.76-0.94, never in
      band) at every energy. So the §4.7-rung-4 trigger to flip
      `UNIVERSAL_CASCADE_MODEL.validated=True` is NOT met. OPEN
      QUESTION (Paul's call): is the universal cascade genuinely
      driving Si into a densely over-coordinated disordered state, or
      is the coordination reference/band in `share/activation/Si.toml`
      mis-set (a documented stand-in)? Decide before the flip. These
      numbers were never written to LEDGER — capture with a T-10 entry.
- [ ] **Promote the T-17 probes into src/ + write the belated T-17
      LEDGER entry (Phase-2 mining, 2026-08-21).** The uncommitted
      `t17_dpa_lattice/` probes proved the two pieces A.2/A.3 need,
      with GPU numbers that live only in scratch JSON — capture them in
      a T-17 LEDGER entry BEFORE the code is discarded. Promotion
      candidates (each needs the standard doc-chain treatment +
      Engine-seam wiring, NOT a raw lift):
      - `box_relax_probe.py` (`fix box/relax x 0 y 0` + minimize, job
        16453628) -> the #8 combined-cell relax routine (§5.6/§2.6):
        add provenance-record of the relaxed cell + FREEZE x,y. The
        DEMONSTRATED A.2 fix.
      - `build_stiffness_probe.py` (+/-1% strain -> stress slope) -> a
        new `biaxial_stiffness.py` beside `bulk_relax.py` (§2.4).
        DONE 2026-08-21 (Phase-3 item 5): `biaxial_stiffness.py` added
        (Engine-seam'd like `bulk_relax`; `measure_biaxial_modulus`
        walks a `change_box` strain sweep reading in-plane stress, and
        `fit_biaxial_modulus` CODES the slope->modulus fit that was
        missing from the probe -- modulus = -slope, since LAMMPS
        pressure is positive in compression). Added `Engine.
        in_plane_stress` (ABC + MockEngine + LammpsEngine `pxx/pyy`
        mean). DESIGN §2.4 updated. 4 unit tests (fit recovers a known
        modulus ignoring the surface offset; the sweep orchestration).
        Full suite green. REMAINING (A.3, separate item): WIRE the
        measured modulus into a stiffness-weighted `split_strain`,
        replacing `even_split_shared_cell`'s even midpoint.
      - `square_cell_search.py::_worst_axis_strain` -> `slab_builder.py`.
        DONE 2026-08-21 (Phase-3 item 4): `_worst_axis_strain` added
        (generalized to substrate/film; reuses `_coplanar_2d` +
        `_polar_rotation` like `even_split_shared_cell`), and
        `SurfaceMatch.worst_axis_strain` now carries the honest per-axis
        ceiling beside the misleading scalar; `match_surfaces` populates
        it. 2 unit tests (a ribbon reads 0.05% scalar vs 1.25% per-axis;
        identity -> 0). REMAINING (a §2.3 design call, separate item):
        RANK `match_surfaces` by the honest metric + a ribbon-shape
        penalty (`_cell_shape` aspect/angle, `_twist_degrees`) instead
        of pure area -- needs the objective decided (smallest area vs
        lowest worst-axis vs least-ribbon) since it changes which cell
        gets built.
      - a thin login-node/CLI entry over `build_halves` (retires the
        hand-inlined `t12/build_matched_halves.py`).
      - the global->model TYPE-REMAP on assembly (t13) ->
        `write_lammps_data`/`amorphized_assembly`, keyed off the bond
        model's declared type_map.
      Cross-cutting: consolidate `_rescale_crystal` (copied 3-5x) at
      `slab_builder.rescale_crystal_to_cell`; the gate-bypass demo
      monkeypatch copied across t11/t13/t15 is the tell that the oxide
      gate (per-material refs + per-wafer species key) is the missing
      src/ piece.
      OXIDE GATE DONE 2026-08-21 (Phase-3 item 6, A1+B1 per Paul): the
      §3.5 gate keys each wafer by its DECLARED species set, not the
      pair's global type map (`gate_healed_surfaces`, `press_pull.py`).
      `Slab.species` recorded at activation (half type_map minus
      projectile); `BuiltPair.wafer_a_species`/`_b_species` carried
      through `assemble_amorphized_pair`; gate loads each wafer's ref by
      its set, falling back to the global map for a same-material pair.
      `real=false` stand-in refs shipped: `share/activation/O_Si.toml`
      (silica) + `Li_Nb_O.toml` (lithium niobate). DESIGN §3.5 updated.
      2 regression tests (per-wafer keying; the same-material fallback).
      Full suite green. This retires the demo gate-bypass monkeypatch --
      the oxide bond can now run the REAL gate per wafer. REMAINING: real
      DFT/exp reference numbers (the silica/LiNbO3 stand-in items above),
      and the node validation of the oxide bond under the real gate.
- [x] **Press/pull preamble must tolerate lost atoms so the §5.6 gate
      can report them (T-18 finding, 2026-08-22). DONE 2026-08-22:**
      `thermo_modify lost warn` added to `restart_preamble_commands`
      (the shared base, so both a fresh `read_data` and a resumed
      `read_restart` inherit it), + a regression test. Re-running T-18 to
      confirm the full press+settle+pull now completes. The press/pull
      `preamble_commands` (`commands.py`) lacks `thermo_modify lost
      warn`, so a sputtered/evaporated atom during the pull makes LAMMPS
      ABORT (`ERROR: Lost atoms`) BEFORE the driver's §5.6 atom-
      conservation gate (`atom_count_conserved` -> `PullResult.
      atoms_conserved`) can flag it — the designed behaviour is a VOID
      measurement (§5.6, §7.6), not a crash. The cascade already sets it
      (`commands.py:1095`). FIX: add `thermo_modify lost warn` to the
      press/pull preamble so a lost atom is dropped-and-gated, not fatal.
      Surfaced by T-18 (job 16701588): the oxide press HELD to contact
      (the combined-cell relax works — no detonation) but the pull then
      crashed on ONE lost atom (193 -> 192).
- [ ] **The §5.6 atom-conservation gate has a BLIND SPOT over the press
      phase (T-18 correction, 2026-08-22).** `pull_at_rate` captures the
      conservation baseline at PULL start, so any atom lost during the
      PRESS (or settle) is invisible to the gate: T-18-rerun ejected
      ~2440 of 2631 atoms DURING the press yet reported
      `atoms_conserved=True`, because the pull began from the
      already-blown ~193-atom remnant. §5.6 says a lost atom invalidates
      the run — but the gate must span the WHOLE press+settle+pull, or
      the press/settle need their own conservation check, or a VOID run
      slips through as a pass. FIX: baseline the count at the ASSEMBLED
      pair (before the press) and check it at every stage boundary, not
      just across the pull. Also: `contact_reached` can fire on
      flying-atom stress spikes, so a press verdict should not rest on it
      alone -- a disintegrated pair is not a bonded one.
- [ ] **Rebuild the oxide validation pair BEFORE re-validating the press
      (T-18 correction, 2026-08-22).** T-18 pressed a thin-ribbon cell
      (`t12_val/match.pkl`: aspect 5.2:1/6.35:1, tilings 1x6/1x5, x = one
      unit cell) built on CIF lattices -- the ~24 GPa configuration the
      archived T-17 README gates ("nothing downstream runs until
      re-matched at DPA lattices"). The combined-cell relax cannot rescue
      it. Before any further oxide press validation: (a) rebuild each
      half at the DPA-preferred lattice (§2.2 rescale, which mainline
      `build_halves` does but the t12 harness skipped;
      `build_dpa_matched_halves.py` in the archive does it standalone);
      (b) take a LOW-ASPECT 2-D coincidence cell, ranked by the item-4
      worst-axis strain, not the misleading scalar
      (`square_cell_search.py` in the archive); (c) confirm near-zero
      frame-0 stress (the archive's decision gate) BEFORE pressing. This
      is also the concrete motivation to WIRE item-4's worst-axis metric
      into `match_surfaces` ranking (the A.3 follow-on) and to WIRE the
      §2.2 rescale into the oxide build path.
- [ ] **Deploy the universal-GPU activate through the mainline
      `prepare` path — two coupled regressions in the per-job route
      (review 2026-08-21).** The `prepare`/`run_member_job` activate
      path was last green 2026-07-30 (job 15454930, si-si DEPLOY
      SMOKE) and 2026-08-05 (bond on GPU, job 15724578); TWO changes
      since then broke or outdated it, and it has not re-run.
      (A.1.1, ROUTING) `deploy/registry.py:97` still pins activate to
      `resource_class="cpu"` — the ORIGINAL §14 decision (2026-07-30,
      "activate = classical engine / CPU") — which the 2026-08-08
      §10.2/§4.7 revision (universal cascade, GPU by default)
      superseded in the DOCS but not the code. So `prepare` routes
      activate to a CPU partition and `_check_gpu_ceiling`
      (`prepare.py`) would then refuse GPUs there: the universal-GPU
      activate is not deployable, only the classical CPU path. FIX:
      make activate GPU by default with the classical CPU path an
      explicit deployment opt-in (the per-kind `[usage.activate.
      environment]` map already carries the bundle env). Careful bits:
      activate bundles the CPU geometry (build/assemble) with the GPU
      cascade — running the whole job on a GPU node is simplest and the
      geometry is cheap. NOTE the compute logic ALREADY dispatches
      universal-first (`live_stages` activate -> subprocess); ONLY the
      deploy routing lags.
      (A.1.2, BUG) `pipeline/member_jobs.py:131` calls
      `stage_set.build(member, potential, scratch, comm)` — 4 args —
      but `StageSet.build` now takes `(member, pot, lattices, scratch,
      comm)` and the activate job never runs `derive_lattices` at all.
      REGRESSED when step-2b (`derive_lattices`) was wired (commit
      `cf92d30`, 2026-08-06): the SEQUENCER call site was updated
      (`sequencer.py:153-167`) but the parallel `run_member_job` site
      was missed, so the per-job activate mis-aligns every arg after
      `potential` and crashes at `cell_for`. FIX: mirror the sequencer
      — run `derive_lattices` first, thread the result into `build`.
      VALIDATE A.1.1 + A.1.2 TOGETHER: one real `prepare`-generated GPU
      activate on a compute node, logged as the next
      `install/tests/LEDGER.md` entry.
      CODE DONE 2026-08-21 (Phase-3 item 2): A.1.2 fixed —
      `run_member_job` activate now runs `derive_lattices` (step 2b)
      and threads it into `build` (`member_jobs.py`), mirroring the
      sequencer, with a regression test whose `build` inspects its args
      (the fake-stage-set's arg-ignoring `build` was why the bug
      slipped). A.1.1 fixed — activate `resource_class` "cpu" -> "gpu"
      (`registry.py`, per §10.2). Full suite green. REMAINING: the node
      validation above.

---

## ARCHIVE

<!-- Resolved items go here. Keep them for reference; use stable numbering
for cross-references. -->
