# T-11 — bond-debond on the T-10 universal-activated surface

The reproducible, committed submission path for **T-11**: the first
end-to-end chain from a genuinely **universal-activated** surface (T-10)
through the bespoke **committee-of-one** bond flow to a **work of
separation**. Record the run as the next entry in `install/tests/
LEDGER.md`. Submit only after T-10 has completed and **passed the gate**.

## What it does

One GPU job (`t11_bond_debond.slurm` + `.py`, ~2–4 h under the fast
`graph.pb`):

1. Load T-10's gate-passing DPA-2.4-7M-activated Si surface
   (`t10_val/activated.extxyz`) and use it for **both** wafers (wafer B is
   its mirror at assembly) → assemble a facing pair at the wide gap.
2. Run the full bond-debond **in-process** under the committee-of-one
   (`SABSIM_DEEPMD_MODEL=graph.pb`): **heal → per-wafer gate → press →
   settle → pull → work of separation**, recording a press/pull **movie**.

The bond heals under `graph.pb` first, bridging the DPA-activated surface
into that model's distribution (the §3.4 heal-under-bond-potential); a
degraded heal would fail the post-heal gate and halt as a first-class "did
not bond" (§5.2), never a crash.

## Prerequisite

**T-10 must have completed and PASSED** (`t10_val/activated.extxyz` present
and the T-10 `.out` shows `T10 GATE PASSED`). If T-10's gate failed, the
surface is not validated — fix the activation first, do not run T-11 on it.

## External artifacts ([ADAPT])

`$SHARE = /cluster/VAST/rulisp-lab/cpg`:

- `SABSIM_DEEPMD_MODEL` = `$SHARE/share/train_deepmd_si/graph.pb`
- in-process engine module = `cpg_lammps_conda/2024.08.29-deepmd`
- T-10 surface = `$SHARE/share/models/dpa_gpu_bench/t10_val/activated.extxyz`

## How to submit

From a login shell with the sabsim env active (sbatch only):

```bash
sbatch install/tests/t11_bond_debond/t11_bond_debond.slurm
```

Logs + artifacts land in `…/dpa_gpu_bench/`: `t11-bond-debond-<job>.out`
and the `t11_val/` scratch (`log.press`, the pull rung dir, the press/pull
trajectory movie, `settled_reference.data`).

## Scope (for the ledger entry)

- **One realization, both wafers** (Si/Si symmetric) — not a two-surface
  ensemble; the amorphization-seed spread is §10.8, later.
- **Committee of ONE** `graph.pb`, not an N-member committee.
- **Trimmed**: 10 ps press hold, ONE pull rung at the fastest rate — a
  first work-of-separation number and a plumbing proof, not a converged
  M1/M3 rate study.
- Single V100, in-process; provenance still labels the classical stand-in
  (`resolve_potential` unwired), as in T-8.
