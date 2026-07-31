# SABSIM install recipe

**Status: DRAFT (2026-07-31) — not yet validated.** These files are the
reproducible rebuild of the SABSIM deployment environment. They exist
because the original environment was hand-built with no written record
(nobody, including its author, could reproduce it), and because that
hand-built env had a fatal flaw on the compute nodes — see below.

The environment is **two layers**:

1. **`environment.yml`** — the conda/mamba base: Python 3.11 + the binary
   ML/inference stack (deepmd-kit, pytorch, tensorflow, CUDA) + the
   scientific core (numpy/scipy/h5py/pandas/matplotlib).
2. **`build_venv.sh`** — the venv on top: a **site-OpenMPI-4.1.5-built**
   `mpi4py`, the pinned `ase`/`pymatgen`/`parsl`, and the editable
   `ALF` + `sabsim` installs.

LAMMPS is in **neither** layer — it comes only from the site `cpg_lammps`
modules. Read the header of `environment.yml` for the three principles
that decide what is and is not installed; they are not obvious and were
learned by diagnosing a real failure (probe job `15520412`).

## Build (under a DEV name, alongside the production env)

```bash
mamba env create -f environment.yml     # creates conda `sabsim_dev`
bash build_venv.sh                       # builds venv `sabsim_dev`
```

Nothing here touches the production `sabsim` conda env or
`virtual_envs/sabsim`. Retire those only after the dev env passes
validation.

## Validate before adopting

1. **Engine probe** — the `sabsim_dev` env must load the **site**
   `liblammps.so` (glibc 2.14), not a conda copy.
2. **activate** — a single-node, then multi-node, `sabsim run --activate`.
3. **bond** — a real deepmd/`pair_style deepmd` run. This settles the one
   open MPI question: LAMMPS and mpi4py use site OpenMPI 4.1.5, but
   deepmd's `libdeepmd_op_pt.so` links conda OpenMPI 5.0. Check whether a
   parallel bond run is clean on site 4.1.5. If it is, no OpenMPI 5 is
   needed; if it collides, escalate to the OpenMPI-5 contingency in
   `dev/TODO.md` (request a SITE-compiled OpenMPI 5, then rebuild
   `cpg_lammps` + deepmd against it).

Only after all three pass: repoint `.sabsim/sabsimrc` and retire the old
env.
