# Engine / MPI Decision Matrix

One question drives everything: **which stack does SABSIM adopt as its
primary engine + MPI?**  We fill this grid with committed scripts and
logged job IDs (see `LEDGER.md`), then choose — instead of swapping the
verdict every hour from prose.

## The two candidate stacks

- **Stack S (SITE engine).** conda env (`sabsim_dev`) for
  Python / ALF / deepmd-inference **+** Imago's site module
  `cpg_lammps/2024.08.29-deepmd` as the LAMMPS engine (site OpenMPI
  4.1.5).  This is ARCHITECTURE §4.4's model; it *adopts* the group's
  existing engine (VISION principle #2).
- **Stack C (CONDA engine).** conda env **+** our source-built LAMMPS
  linked to conda OpenMPI 5.0.10 (`…-conda-ompi5.0.10`).  This is what
  ARCHITECTURE §4.1 currently describes; single MPI end-to-end, but a
  self-maintained rebuild that diverges from Imago and dropped two
  packages (ML-HDNNP, VORONOI).

## The checks (rows)

- **F1** — MPI reaches the IB fabric, 2 nodes (bandwidth-measured).
- **E1** — engine imports + runs a real MD step, 2 nodes, in-process
  (LAMMPS-owns-MPI: no `comm=`, no mpi4py).
- **E2** — `pair_style deepmd` registers.
- **E3** — deepmd runs a real force step with a trained model.
- **E4** — the **mpi4py comm-sharing** model works, 2 nodes.  This is
  not optional: the CODE already requires it —
  `cli.py:158` (`comm = MPI.COMM_WORLD`),
  `lammps_engine.py:85` and `live_stages.py:411` (`lammps(comm=comm)`),
  `live_stages.py:518` (`comm.bcast(...)`).  Python shares LAMMPS's
  `MPI_COMM_WORLD`, so mpi4py and liblammps MUST link the same libmpi.
- **E5** — full `sabsim prepare` -> activate job runs green end-to-end.

## Status grid (cite job IDs, never prose)

| Check | Stack S (site 4.1.5)        | Stack C (conda 5.0.10)      |
|-------|-----------------------------|-----------------------------|
| F1    | site is the cluster's prod  | **PASS** 15551674 (rc_mlx5, |
|       | MPI (assumed; not measured  | 12.09 GB/s)                 |
|       | by us — could add a probe)  |                             |
| E1    | **PASS** 15580445           | **PASS** 15582291           |
| E2    | **PASS** 15580445           | **PASS** 15582291           |
| E3    | UNTESTED (needs a model)    | **PASS** 15686597 — real    |
|       |                             | 2.2.10/TF graph.pb runs on  |
|       |                             | 3.1.3 plugin, forces finite |
| E4    | UNTESTED — needs an mpi4py  | **PASS** 15582291           |
|       | built vs site 4.1.5 first,  | (comm=comm + comm.bcast,    |
|       | OR a code change to drop it | 2 nodes)                    |
| E5    | UNTESTED                    | **PASS** 15703266 — full    |
|       |                             | prepare->activate green,    |
|       |                             | wrote assembled_pair        |
| build | already maintained by group | **PASS** 15554787 (static)  |
| feat  | 26 pkgs (ML-HDNNP+VORONOI)  | **PASS** 15683172 — 25 pkgs;|
|       | — the superset              | MISSING_REQUIRED (none);    |
|       |                             | only ML-HDNNP+VORONOI cut,  |
|       |                             | neither used by any code    |

## What the empty cells cost

- **Stack C, E1/E2/E4 are testable NOW** with existing pieces:
  `engine_run.py` already uses `from mpi4py import MPI` +
  `lammps(comm=comm)` — i.e. it exercises E1, E2, and the E4 comm-share
  model in one 2-node job, because the conda engine and conda mpi4py are
  the same MPI.  One `sbatch` fills three cells.
- **Stack S, E4 needs one added build** — an `mpi4py` compiled against
  site OpenMPI 4.1.5 — OR a DESIGN change to the LAMMPS-owns-MPI model
  (in which case E4 becomes moot for S and E1/E2 already PASS).
- **E3 (both stacks)** needs a small trained deepmd model file to run a
  real `pair_style deepmd` step.  Registration (E2) is already proven
  for S; a runnable model is a separate artifact to locate/produce.

## Decision rule (agreed before filling)

Pick the stack that reaches **E1–E5 all PASS** with the least added
machinery, breaking ties toward VISION principle #2 (adopt, don't
rebuild).  Do NOT rewrite ARCHITECTURE §4.1 / §4.4 until the chosen
stack's row is complete in the ledger.

## DECISION — 2026-08-04: **Stack C locked in as primary.**

Stack C reaches F1/E1/E2/E4/build/feat all PASS; Stack S is blocked at
E4 (the comm-sharing model the code already requires) without an added
site-4.1.5 mpi4py build or DESIGN surgery.  The one feature worry —
does the conda build cover what the pipeline needs — is closed by
T-FEATURES (15683172): MISSING_REQUIRED (none); only ML-HDNNP + VORONOI
cut, neither invoked by any code path.  We accept the two-package gap
as-is (restorable per the build_lammps.sh note if a future study needs
them) rather than rebuild now.  Stack S stays DOCUMENTED as a proven
fallback (T-SITE-ENGINE 15580445) at zero maintenance cost to us.
Remaining before ARCHITECTURE reconcile: E3 (real deepmd force step)
and E5 (full prepare -> activate).

## Next jobs to run (in order)

1. **J1 — Stack C, E1+E2+E4:** `sbatch install/tests/engine_run.slurm`
   (conda engine, conda mpi4py, comm-sharing, 2 nodes).  Fills three
   Stack-C cells at once and is the fair counterpart to 15580445.
2. **J2 — E3 model:** locate/produce a small trained deepmd model, then
   run one deepmd force step on the chosen engine(s).
3. **J3 — Stack S, E4 (only if we keep the comm-sharing design):** build
   `mpi4py` vs site 4.1.5, rerun the comm-share probe against the site
   engine.
4. **J4 — E5:** `sabsim prepare` -> activate on whichever stack wins
   E1–E4.
