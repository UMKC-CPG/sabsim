# Installing SABSIM

SABSIM is a multi-code pipeline for simulating **surface activated
bonding** — argon-blasting two wafer surfaces to amorphize them, then
pressing them together cold so the dangling bonds fuse across the
interface. It does not do the physics itself: it drives LAMMPS, VASP,
ALF/DeePMD and ASE. Installing SABSIM therefore means **building the
environment those tools run in**, not just installing a Python package.

Plan for an afternoon, not five minutes. This is an HPC install.

## What you are actually building

Four pieces, layered. Each exists for a reason, and skipping one is
the usual way this install fails.

| Layer | What it provides | Built by |
|---|---|---|
| 1. Conda base | Python 3.11, deepmd-kit, torch, TensorFlow, CUDA, MPI | `install/environment.yml` |
| 2. Venv | ase / pymatgen / parsl pinned, editable ALF + SABSIM | `install/build_venv.sh` |
| 3. LAMMPS | two engines, built from source on the cluster | `install/build_lammps.sh` |
| 4. Cascade engine | deepmd's official bundle, for universal MLIPs | `install/cascade-engine-deepmd-official.md` |

Layers 1–2 are the SABSIM environment. Layer 3 is the classical and
DeePMD dynamics engine. Layer 4 is a **separate, deliberately isolated**
install used only for the universal-potential cascade step.

## One shared base, one venv per person

Layers 1, 3 and 4 are **shared and read-mostly** — the 16 GB conda base,
the LAMMPS engines, the cascade bundle. Install them once for the group.

Layer 2, the venv, is **per user**. This is not a preference; it is
forced. The venv holds SABSIM as an *editable* install pointing at a
working clone, and a venv can hold exactly one package named `sabsim`.
The moment a second person runs `pip install -e` against the same venv,
pip silently overwrites the first person's pointer — the package name
and its `dist-info` are identical, so there is nothing for pip to
object to. The first person's `import sabsim` then resolves into
somebody else's home directory, and typically fails outright, because
home directories are usually not group-readable.

So each person edits the two variables at the top of `build_venv.sh`:

```bash
VENV="$HOME/virtual_envs/sabsim"        # YOUR venv, not the group's
SABSIM_CLONE="$HOME/sabsim"             # YOUR clone
```

and runs `bash install/build_venv.sh`. The venv layer is thin — pip
metadata and a handful of pinned pure-Python packages — because
`--system-site-packages` lets it see the shared conda stack. Nobody
duplicates the 16 GB.

Two rules follow, and they are worth stating plainly:

- **Never `pip install` into a venv you did not build.** Cloning the
  repository into your own home and then installing it into the group
  venv is the specific mistake this section exists to prevent.
- **Never re-run `python -m venv` over an existing venv.** Without
  `--system-site-packages` it rewrites `pyvenv.cfg` with
  `include-system-site-packages = false`, which severs the venv from
  the entire conda stack and breaks every import at once. If imports
  suddenly fail for everyone, check that line first.

A shared venv should therefore be **group read-only** (`drwxr-sr-x`),
and on this installation it is. That is deliberate, not a broken
permission: a `pip install` aimed at it fails immediately with a
permission error, instead of quietly succeeding and redirecting
somebody else's `import sabsim` into a directory they cannot read. If
pip refuses to write to a venv, you are pointed at the wrong one —
build your own rather than trying to gain write access to that one.

The shared **conda base**, by contrast, is left group-writable on
purpose. Mamba builds environments by hardlinking from a shared
package cache, so many of its files are the same inodes as in other
people's environments. Permissions live on the inode, not the path, so
tightening them there would reach into unrelated environments. Leave
it alone.

## Prerequisites

- A Linux HPC cluster with Slurm and conda/mamba.
- A login node with outbound HTTPS (compute nodes are often offline).
- GPU nodes for the cascade and bonding stages.
- Roughly 40 GB of disk across shared and scratch storage.

## Quick start

```bash
git clone <your-sabsim-remote> sabsim && cd sabsim

# Layer 1 — the conda base. CONDA_OVERRIDE_CUDA is REQUIRED on a
# GPU-less login node, or the solver silently picks CPU-only builds.
CONDA_OVERRIDE_CUDA=12.9 mamba env create -f install/environment.yml

# Confirm the GPU builds landed. Every build string must contain
# `cuda`, never `cpu_`. If they say cpu_, stop and redo layer 1.
conda list -n sabsim | grep -E '^(deepmd-kit|pytorch|tensorflow) '

# Layer 2 — the venv over that base. EDIT THE PATHS AT THE TOP FIRST.
bash install/build_venv.sh

# Layer 3 — LAMMPS from source, as a batch job (~hours).
sbatch install/build_lammps.sh
```

Then, from the venv you just built, let `sabsim setup` check every
layer and write `.sabsim/sabsimrc` (it fills the template's three
machine-specific lines and never overwrites; a value it could only
take from the template's worked example is marked EDIT):

```bash
source <your venv>/bin/activate
sabsim setup --scratch $HOME/data/scratch/sabsim   # --share, --venv too
source .sabsim/sabsimrc
pytest src/tests/ -q
```

## Your first project

Do not copy another person's job folder. `sabsim init` writes a
complete project folder from the tracked templates — the project file,
the machine rc, the four stage folders, and a force-model recipe for
each surface's material — and never overwrites, so it is safe to run
again after you edit the pair (`DESIGN.md` §10.9):

```bash
mkdir -p ~/sabsim/jobs
sabsim init ~/sabsim/jobs/si_sio2 --materials Si SiO2   # no flag: lists them
cd ~/sabsim/jobs/si_sio2
# 1. read and edit sabsim.toml, deployment.toml, prep_surf*/recipe.toml
sabsim prepare          # 2. writes six .slurm + SUBMISSION_GUIDE.md
# 3. submit in the guide's order: the two .library builds (once per
#    recipe), the two preps, bond, analysis — or its chained form
```

## The four things that trip people up

**Edit the paths.** `build_venv.sh` and `build_lammps.sh` both open with
an "EDIT for your machine" block naming conda prefixes, clone locations
and install roots. They are one site's paths, not defaults. Nothing
auto-detects them.

**Do not install LAMMPS from conda or pip.** A packaged LAMMPS drops a
competing `liblammps.so` that Python's RPATH loads ahead of everything
else, and its glibc floor kills it on older compute nodes. LAMMPS must
be built on the cluster and linked against *this environment's* conda
OpenMPI 5.0.10 — which is exactly what `build_lammps.sh` does. For the
same reason, install SABSIM itself with `--no-deps`, so pip never
re-resolves the hand-pinned stack out from under you.

**Read `.sabsim/sabsimrc` after `sabsim setup` writes it.** It is
gitignored, so a fresh clone never has one. It declares three location
roots — `SABSIM_SCRATCH` (regenerable run output), `SABSIM_SHARE` (the
group-readable install, engines and reference data), and the optional
`SABSIM_LOCAL` override — and then activates the conda env and the venv
on top of it. Nothing in SABSIM guesses where to run; this file states
it, and `setup` says where each value came from (a flag, a variable
already set, or the template's example, which you must edit).

**Launching MPI needs one unset.** Slurm exports mutually-exclusive
memory variables that abort a nested launch. Every run script should
begin:

```bash
unset SLURM_MEM_PER_NODE SLURM_MEM_PER_CPU SLURM_MEM_PER_GPU
srun --mpi=pmix ...
```

## The cascade engine (layer 4)

The universal DPA foundation models are PyTorch message-passing
networks, and running them inside LAMMPS needs a deepmd-kit, libtorch
and LAMMPS that were **built and tested together**. Assembling your own
from conda-forge does not work — that combination crashes these models
in LAMMPS's TorchScript force path. Use deepmd's official offline
installer bundle, which ships a matched stack, and keep it isolated from
the environment above. Full recipe, with the site-specific knobs marked
`[ADAPT]`, is in `install/cascade-engine-deepmd-official.md`.

Point SABSIM at it with two environment variables:
`SABSIM_CASCADE_ENGINE_PREFIX` (the bundle) and
`SABSIM_CASCADE_MLIP_MODEL` (the model file).

## Status and expectations

This is **research software under active development**, installed so far
on one cluster. The recipe is written to be redone elsewhere, but expect
to adapt it rather than run it verbatim. `install/README.md` is the
authoritative recipe and records why each decision was made — read it
before deviating, because most of the constraints above were discovered
the expensive way.
