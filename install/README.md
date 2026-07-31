# SABSIM install recipe

**Status: DRAFT (2026-07-31).** Reproducible rebuild of the SABSIM
deployment environment. It exists because the original was hand-built with
no written record, and because that env had a fatal flaw on the compute
nodes (a vendored `liblammps.so` the python RPATH loaded ahead of a
glibc-safe one — probe `15520412`).

The environment is **two layers**:

1. **`environment.yml`** — the conda/mamba base: Python 3.11, the binary
   ML/inference stack (deepmd-kit, pytorch, tensorflow, CUDA), the
   scientific core (numpy/scipy/h5py/pandas/matplotlib), and **`mpi4py`**.
2. **`build_venv.sh`** — the venv on top: pinned `ase`/`pymatgen`/`parsl`
   and the editable `ALF` + `sabsim`.

Read the header of `environment.yml` for the MPI decision and the two
principles that decide what is and is not installed.

## MPI: conda OpenMPI 5.0.10 + UCX (validated)

The whole stack runs on **conda OpenMPI 5.0.10** — deepmd-kit forces it in,
and the conda python's RPATH makes its `libmpi` the one every in-process
`import` loads. That is the right answer, not a compromise: conda's
OpenMPI 5.0.10 ships UCX and **drives this cluster's InfiniBand fabric at
~12 GB/s** (validated, job `15551674`; UCX selects `rc_mlx5`). No
site-compiled OpenMPI is needed.

**Launcher:** `srun --mpi=pmix` (or `mpirun`) — but first
`unset SLURM_MEM_PER_NODE SLURM_MEM_PER_CPU SLURM_MEM_PER_GPU`. The
allocation exports those mutually-exclusive, which otherwise aborts the
nested launch. Bake the `unset` into every run script.

## Build (under a DEV name, alongside the production env)

```bash
# CONDA_OVERRIDE_CUDA is REQUIRED on the GPU-less login node — without it
# the solver picks CPU-only deepmd/torch/tf builds the bond stage can't use.
CONDA_OVERRIDE_CUDA=12.9 mamba env create -f environment.yml   # -> sabsim_dev
bash build_venv.sh                                             # venv sabsim_dev
```

After the conda step, confirm the GPU builds landed:

```bash
conda list -n sabsim_dev | grep -E '^(deepmd-kit|pytorch|tensorflow) '
# each build string must contain `cuda`, NOT `cpu_`
```

## Remaining work + validation

- **LAMMPS build** (not yet scripted): a source build made on the cluster
  (el8-native, glibc-safe) linked against this env's **conda OpenMPI
  5.0.10**, installed into the venv — both the classical engine and the
  deepmd-2024.08.29 engine. The site `cpg_lammps` modules do NOT fit (they
  are built against site OpenMPI 4.1.5).
- **Validate before adopting:** engine load (the venv LAMMPS must import
  and run under conda 5.0.10), single- then multi-node activate (launched
  as above), and a real deepmd/bond run. Only then repoint
  `.sabsim/sabsimrc` and retire the old env.
