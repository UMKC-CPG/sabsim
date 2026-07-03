# Prototype: a DeePMD backend for ALF (no fork required)

This prototype validates the central claim from our ALF study: that
ALF's MLIP backend is a **config-selected plugin**, so we can run the
active-learning loop with a cheaper **DeePMD** potential instead of
HIPPYNN by writing two small modules and swapping three strings — with
**no change to ALF's source**.

It is a prototype to *review and then test*, not yet wired into the
SABSIM document chain. Nothing here edits VISION/ARCHITECTURE.

## What plugs in where

ALF loads each task/calculator from a dotted path in its JSON config
(`load_module_from_string` / `load_module_from_config`). The NeuroChem
example already references modules *outside* the `alframework` package,
so our plugin can live in its own importable package on `PYTHONPATH`.

Three strings change versus a HIPPYNN run (see `configs/`):

- `master_config` → `ML_task`:
  `sabsim_alf_deepmd.deepmd_interface.train_DEEPMD_ensemble_task`
- `master_config` → `ML_config_path`: `deepmd_ml_config.json`
- `mlmd_config` → `ase_calculator`:
  `sabsim_alf_deepmd.deepmd_interface.DEEPMD_ASE_load_ensemble`

Everything else (builders, QM/VASP interface, sampler core, the
`MLMD_calculator` uncertainty math, queue sizes, Parsl configs) is
untouched.

## Contents

```
sabsim_alf_deepmd/
  data_conversion.py   ANI-style HDF5  ->  DeePMD systems
  deepmd_interface.py  train_DEEPMD_ensemble_task + DEEPMD_ASE_load_ensemble
configs/
  deepmd_ml_config.json        the DeePMD input.json template + n_models
  master_config_snippet.json   the three swaps + properties_list
  mlmd_config_snippet.json      the one-line ase_calculator swap
```

## How the two ALF contracts are honoured

1. **Training task** — `train_DEEPMD_ensemble_task` matches ALF's exact
   call signature and returns `(list_of_success_flags,
   current_training_id)`, writing members to
   `model_path.format(id)/model-NN/`. ALF accepts the round only when
   `all(flags)` is True (`__main__.py` model-update block).
2. **Ensemble loader** — `DEEPMD_ASE_load_ensemble` returns a *list of
   `deepmd.calculator.DP` ASE calculators*. ALF's `MLMD_calculator`
   already derives `energy_stdev` / `forces_stdev_*` from any list of
   ASE calculators, so uncertainty-driven sampling works with zero
   DeePMD-specific code.

**Committee uncertainty** is obtained the same cheap way ALF does for
HIPPYNN: `n_models` networks trained from different random seeds; their
disagreement is the uncertainty signal.

## Assumptions to verify before trusting results

1. **Unit round-trip — VALIDATED (`tests/test_data_conversion.py`).**
   ALF stores values as `ASE_value * properties_list[prop][factor]`; the
   converter divides by that same factor to return eV / eV·Å⁻¹ / Å,
   which are DeePMD's standard units. The test writes a synthetic
   two-group file with ALF's *own* `pyanitools.datapacker` (so the schema
   matches a real run), then asserts the converted `coord/energy/force/
   box` arrays equal the known natives — exercising both the periodic
   (`box.npy`) and non-periodic (`nopbc`) branches. It passes. The one
   remaining check against a *real* `data-*.h5` is only to confirm the
   live `master_config`'s `properties_list` factors match; the math
   itself is proven.
2. **UDD sampler variant — RESOLVED (Kulichenko 2023 + ALF `UDD`
   branch).** Plain `mlmd_sampling.py` does uncertainty-*triggered
   frame capture* (run MD, grab the frame once the ensemble std-dev
   exceeds `Escut`/`Fscut`). The full *biasing-energy* UDD is **not** a
   separate sampler — it is baked into `MLMD_calculator` in
   `samplers/ASE_ensemble_constructor.py`, gated by a `use_bias` flag:
   it adds `E_bias = E_en_bias_weight * energy_stdev` (the paper's
   *linear* one-parameter variant, not the Gaussian of Eq. 4) plus the
   matching bias force `-w * d(sigma_E)/dx` (paper Eq. 7), computed
   purely from per-member energies/forces. The same `mlmd_sampling.py`
   drives both MD-AL and UDD-AL; the only difference is whether the
   calculator's bias is on. On the `UDD` branch it is toggled by
   attribute assignment in the example notebook
   (`mlmd.use_bias = True; mlmd.E_en_bias_weight = 0.45`), NOT wired
   into `simple_mlmd_sampling_task`'s config path.
   (`samplers/ml_driven_md_sampling.py` is an unrelated legacy MD
   sampler with no bias code — earlier suspicion was wrong.)
   **Consequence for us:** UDD is potential-agnostic — the bias reads
   any list of ASE calculators, so a DeePMD committee gets UDD with
   zero DeePMD-specific code. Enabling automated UDD needs only a small
   ALF-side wiring change (add `use_bias`/`E_en_bias_weight` as
   `MLMD_calculator` ctor kwargs, or set them in the sampler task) that
   is independent of the potential backend and helps HIPPYNN equally.
3. **DeePMD backend / freeze extension.** Defaults assume a TensorFlow
   freeze (`frozen_model.pb`). For the DeePMD-kit v3 PyTorch backend set
   `frozen_model_name` to `frozen_model.pth`; the loader accepts either.

## Why this is the cheaper path end-to-end

For the production SAB runs (LAMMPS, steps 4/6/7) DeePMD deploys via a
first-class `pair_style deepmd`, and SNAP is native LAMMPS
(`pair_style snap`) — both simpler than HIPPYNN's MLIAP-Kokkos route.
So a cheaper potential simplifies *both* the ALF training side (this
plugin) and the LAMMPS production side. A SNAP backend would be the same
shape as this module (swap the trainer for FitSNAP, return a SNAP ASE
calculator / `pair_style snap` committee).

## Dependencies

- `alframework` (ALF) and `parsl` — the loop and the `@python_app`.
- `deepmd-kit` (provides the `dp` CLI and `deepmd.calculator.DP`).
- `ase`, `numpy`, `h5py` — already required by ALF.

## Test plan (run in the ALF + deepmd-kit environment, not here)

This sandbox has neither `alframework` nor `deepmd-kit`, so only static
checks run here (syntax compiles clean). Stage the real validation:

1. **Converter unit test.** Point `ani_h5_to_deepmd` at one existing
   `data-*.h5`; confirm a `deepmd_data/<formula>/set.000/` with
   `coord/energy/force/box.npy` of the right shapes, and that a couple
   of energies/forces match the h5 values divided by the factors.
2. **`--test_ml`.** Run ALF with the swapped `ML_task` on a tiny
   bootstrap set; confirm `model-NN/frozen_model.pb` appears and the
   task returns all-True.
3. **`--test_sampler`.** Confirm `DEEPMD_ASE_load_ensemble` loads the
   committee and that `MLMD_calculator` reports non-zero `energy_stdev`
   / `forces_stdev_*` along a short trajectory.
4. **Short full loop.** A few iterations on one SAB material to confirm
   build → sample → VASP-label → retrain cycles and that uncertainty
   falls as data accrues.
5. **LAMMPS deploy.** Load a frozen member via `pair_style deepmd` and
   run a few MD steps to confirm the step-4/6/7 deployment path.
