# T-17 — DPA equilibrium-lattice diagnostic (SiO2, LiNbO3)

## Why

The T-16 press-pull runs exploded. The thermo log traced it to a single
number: the geometrically-matched SiO2/LiNbO3 cell starts at ~24 GPa of
internal stress under the universal DPA-2.4-7M model, because the
commensurate lattice is far from the model's OWN preferred lattice. Two
pairs confirmed it quantitatively — frame-0 pressure predicted the
time-to-explosion (24 GPa -> step ~4000; 1.7 GPa -> step ~15,500).

This diagnostic measures the DPA-preferred lattice of each material
INDEPENDENTLY, so we can decide whether re-matching at those lattices
gives a joint cell near zero pressure (proceed) or whether the
commensurability-vs-equilibrium tension is fundamental for this pair
(redesign). It is a DECISION GATE — nothing downstream runs until the
numbers are in.

## What it does

- Part 1 (sabsim env, `build_bulk_crystals.py`): tile each CIF into a
  3D-periodic bulk supercell (SiO2 4x4x4 = 576 atoms; LiNbO3 3x3x2 = 540)
  and record the per-unit-cell CIF lattice as the baseline.
- Part 2 (deepmd bundle, `relax_lattice.py`): for each crystal, report the
  pressure at the CIF lattice (`run 0`), then zero-pressure NPT box-relax
  (aniso + tilt) at 300 K, and report the DPA equilibrium lattice vs the
  CIF baseline plus whether the crystal stayed ordered.

## Run

```bash
sbatch -p requeue --export=ALL,VALWORK=$BENCH/t17_val \
  install/tests/t17_dpa_lattice/t17_dpa_lattice.slurm
```

Outputs land in `$VALWORK`: `{sio2,linbo3}_bulk.data`, `log.{name}`,
`{name}_relax.dump` (movie), `{name}_boxavg.txt`, `lattice_results.json`.

## Reading the result

- `initial_pressure_bar` — how far the CIF lattice sits from DPA
  equilibrium (the single-material analogue of the joint cell's 24 GPa).
- `percent_change_abc` — how much each lattice parameter moved to reach
  zero pressure.
- `final_atoms` well below `starting_atoms`, or a large PE/atom jump —
  the crystal disordered, meaning "pristine" is not a valid reference for
  that material under DPA.
