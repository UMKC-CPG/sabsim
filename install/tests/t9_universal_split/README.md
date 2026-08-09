# T-9 — node validation of the re-architected universal split

The reproducible, committed submission path for **T-9**: the first
end-to-end node validation of the re-architected activate -> bond split
(universal MLIP cascade, cascade-only activate, wide-gap assemble, and the
§3.5 gate moved into the bond flow). Record the run as the next entry in
`install/tests/LEDGER.md`. Do NOT re-derive this by hand — edit and re-run
these files instead.

## What T-9 proves (and what it does not)

Two chained jobs, mirroring the production activate -> bond split:

- **T-9a (`t9a_activate_assemble.slurm` + `.py`, GPU).** Builds a small Si
  slab, runs the **cascade-only** `build_activate_script` (no re-anneal,
  no gate) through the deepmd bundle's `lmp` **out-of-process** on the GPU
  (universal **DPA-2.4-7M** + ZBL), reads each amorphized half back, and
  `assemble_amorphized_pair` at the **wide gap** (> the 6 A bond-flow
  separation cutoff). Writes `assembled_pair.data` + `built_pair.pkl`.
- **T-9b (`t9b_bond_press.slurm` + `.py`, GPU, `afterok:A`).** Loads the
  pair and runs `press_and_bond` **in-process** under a **committee of
  one** — a single frozen bespoke DeePMD model via `SABSIM_DEEPMD_MODEL`.
  It **heals** the combined cell, **gates each healed surface per wafer
  tag** (wafer B mirrored in z), **halts** on a failed gate, else scissors
  + presses. Asserts the gate produced a verdict for **both** tags.

**Not proved:** converged physics (one impact, capped cascade, 5 ps hold,
`RunControl` capped); the full `sabsim prepare` deployment path (E5 already
proved that for classical activate); a real N-member committee.

## External artifacts it depends on ([ADAPT] to your cluster)

`$SHARE = /cluster/VAST/rulisp-lab/cpg`, `$B = $SHARE/share/models/
dpa_gpu_bench`:

- `SABSIM_CASCADE_ENGINE_PREFIX` = `$SHARE/programs/`
  `deepmd-kit-3.2.0b0-cuda129`
- `SABSIM_CASCADE_MLIP_MODEL` = `$B/v320fix/dpa24.pt2`
- `SABSIM_DEEPMD_MODEL` = `$SHARE/share/train_deepmd_si/graph.pb`
- in-process engine module = `cpg_lammps_conda/2024.08.29-deepmd`

The `dpa24.pt2` is the working
DPA-2.4-7M export from job 16010337; the deployment template points at the
canonical `share/models/dpa2.4-7m/DPA-2.4-7M.pt2` — host it there too when
convenient so the harness and the template name one path.

## How to submit

From a login shell with the sabsim env active (this only calls `sbatch` —
never run `lmp` on the login node):

```bash
bash install/tests/t9_universal_split/submit.sh
```

It submits T-9a, then T-9b with `--dependency=afterok:<A>`, and prints both
job IDs. Logs land in `$SHARE/share/models/dpa_gpu_bench/`:
`t9-activate-<A>.out` and `t9-bond-<B>.out`.

## Expected evidence (for the ledger entry)

- T-9a: `[half a/b] surviving types: [1]` (Si only, projectile stripped),
  `closest-atom gap: NN.NNN A` (> 6), `T9A ACTIVATE+ASSEMBLE OK`.
- T-9b: `plugin load .../libdeepmd_lmp.so`, `pair_style deepmd .../graph.pb`,
  `activation_a/b : passed=...`, then either `contact_reached : True` or a
  gate halt note, and `GATE RAN PER WAFER TAG`, `T9B ... OK`.
