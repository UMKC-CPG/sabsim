# T-10 — first gate-passing universal activation

The reproducible, committed submission path for **T-10**: does the
universal foundation MLIP (DPA-2.4-7M) drive a cascade that amorphizes a
real Si surface well enough to clear the §3.5 activation gate? A PASS is
the evidence to flip the model's `validated` flag (DESIGN §4.7) and drop
the `SABSIM_ALLOW_UNVALIDATED_POTENTIAL` opt-in. Record the run as the next
entry in `install/tests/LEDGER.md`.

## What it does

One long GPU job (`t10_activate_gate.slurm` + `.py`):

1. Build a ~2880-atom Si slab (6×6×10 diamond, ~33 Å wide × ~53 Å thick —
   the §3.6 depth-reference geometry).
2. Run the **full-fluence** universal cascade (27 impacts, 75 eV,
   0.025 ions/Å²) **out-of-process** in the deepmd bundle on the GPU,
   recording a trajectory **movie** of the whole bombardment
   (`cascade_movie.dump`, loadable in OVITO/VMD).
3. Read the amorphized surface back and run the activation gate **directly**
   on the cascade's product (before any bond-flow heal), reporting every
   metric: g(r) first peak, coordination-defect band, non-six-ring
   fraction, and the ≥7 Å amorphized depth.

The slab is sized so the deep crystalline third anchors the gate's
coordination reference while the skin reaches the 7 Å depth — the two
size-driven metrics T-9's toy could not satisfy. The cascade itself was
already shown to amorphize (T-9's pre-heal g(r) and rings passed).

**Cost:** ~12 h on one V100 (27 impacts × ~6.5k steps at DPA-2.4-7M speed).
`--partition=gpu` (no requeue): the cascade subprocess is not checkpointed,
so a preemption restarts from zero. Walltime 20 h for margin.

## External artifacts ([ADAPT])

`$SHARE = /cluster/VAST/rulisp-lab/cpg`,
`$B = $SHARE/share/models/dpa_gpu_bench`:

- `SABSIM_CASCADE_ENGINE_PREFIX` = `$SHARE/programs/`
  `deepmd-kit-3.2.0b0-cuda129`
- `SABSIM_CASCADE_MLIP_MODEL` = `$B/v320fix/dpa24.pt2`

Knobs (env, defaults in the slurm): `T10_N_LATERAL=6`, `T10_N_DEPTH=10`,
`T10_TRAJ_STRIDE=500`.

## How to submit

From a login shell with the sabsim env active (sbatch only — no `lmp` on
the login node):

```bash
sbatch install/tests/t10_universal_activation/t10_activate_gate.slurm
```

Logs + artifacts land in `$B/`: `t10-activate-gate-<job>.out` and the
`t10_val/` scratch (`cascade_movie.dump`, `activated.dump`,
`activated.extxyz`).

## Expected evidence (for the ledger entry)

`cascade pair_style: hybrid/overlay deepmd .../dpa24.pt2 zbl ...`,
`27 impacts ... 75 eV`, `readback atoms: ~2880 | surviving types: [1]`,
then the four metric verdicts and either `T10 GATE PASSED` (→ flip
`validated=True`) or `T10 GATE FAILED` with the first failing metric.

## Trajectory movies, generally

This run also exercises the new opt-in trajectory support in
`build_activate_script` (the out-of-process cascade path). For a **pipeline**
run, enable frames via the CLI trajectory switch (`run_options`) and the
universal activate will emit the same movie per surface — the feature is
not T-10-specific.
