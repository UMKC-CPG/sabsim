# Cascade engine: deepmd-kit OFFICIAL bundle (universal-MLIP install recipe)

How to install the engine that runs a **universal foundation MLIP (DPA)**
in LAMMPS for the SABSIM cascade/amorphization step, on an HPC system.
Written to be redone elsewhere with minimal adaptation — the
system-specific knobs are called out as **[ADAPT]**.

## Why this recipe (the non-obvious part)

The universal DPA models are PyTorch-backend message-passing GNNs. Running
them in LAMMPS needs a deepmd-kit + libtorch + LAMMPS that were **built and
tested together**. Do NOT assemble your own from conda-forge: conda-forge's
`deepmd-kit` pins the *latest* torch (2.11 at time of writing), and that
combination — plus a separately-built LAMMPS — **crashes these models in
LAMMPS's C++ TorchScript force path** (DPA-3 at `custom_silu`, DPA-2 at the
autograd force). deepmd's OWN offline-installer bundle ships a matched,
tested stack (deepmd 3.1.3 + **torch 2.10** + their LAMMPS) that RUNS them.
Use the official bundle.

## What you get

A self-contained conda environment (one directory) containing `dp`, `lmp`
(with the deepmd pair style as a runtime plugin), Python, torch, and CUDA
libs — all version-matched. It is ISOLATED from any other environment.

## Prerequisites

- A login/build node with **outbound HTTPS** (compute nodes are often
  offline — fetch everything on the login node). NOTE: some systems'
  `/usr/bin/curl` is built without HTTPS; use **`wget`**.
- Disk: ~10 GB (CPU bundle) or ~30 GB (GPU/CUDA bundle) per install
  **[ADAPT: pick a location with room; here `$CPG_SHARE/programs/`]**.
- For GPU: a CUDA build whose **CUDA version is compatible with the target
  GPU driver** (installers exist for cuda126/128/129) **[ADAPT]**.

## 1. Download the offline installer

Releases: `https://github.com/deepmodeling/deepmd-kit/releases`. Pick a
version that supports your models (DPA-2.4/DPA-3.1 need **v3.1.x**) and a
CPU or `cudaXXX` variant. GPU installers are **split into N parts**
(`.sh.0`, `.sh.1`, ...) — download all and `cat` them together.

```bash
VER=3.1.3                 # [ADAPT: >=3.1.0 for DPA-3; 3.1.3 for DPA-2.4]
VARIANT=cuda129           # [ADAPT: cpu | cuda126 | cuda128 | cuda129]
BASE=https://github.com/deepmodeling/deepmd-kit/releases/download/v$VER
cd /some/scratch          # [ADAPT]
# CPU = single file; GPU = split parts (here 3):
for i in 0 1 2; do
  wget -q --tries=3 -O part.$i \
    "$BASE/deepmd-kit-$VER-$VARIANT-Linux-x86_64.sh.$i"
done
cat part.0 part.1 part.2 > deepmd-kit-$VER-$VARIANT.sh && rm -f part.*
# (CPU variant is one file: deepmd-kit-$VER-cpu-Linux-x86_64.sh)
```

## 2. Install (self-extracting; do NOT time it out early)

```bash
PREFIX=/cluster/VAST/rulisp-lab/cpg/programs/deepmd-kit-$VER-$VARIANT  # [ADAPT]
bash deepmd-kit-$VER-$VARIANT.sh -b -p "$PREFIX"
```

A large GPU bundle takes several minutes (it byte-compiles ~30 GB). Let it
finish — it ends with "installation finished." The installer `.sh` is
disposable after install.

## 3. Verify

```bash
ls "$PREFIX"/bin/lmp "$PREFIX"/bin/dp
"$PREFIX"/bin/dp --version                    # -> DeePMD-kit v3.1.3
"$PREFIX"/bin/python -c \
  "import torch; print(torch.__version__, torch.version.cuda)"
# GPU: check the arch list includes your GPU (V100 = sm_70):
"$PREFIX"/bin/python -c "import torch; print(torch.cuda.get_arch_list())"
```

## 4. Activate — ISOLATED (mandatory)

The bundle's `lmp` loads libtorch and the deepmd plugin at RUNTIME. If any
OTHER conda/deepmd env (a different torch) leaks in via `PATH` /
`LD_LIBRARY_PATH` / `LAMMPS_PLUGIN_PATH`, LAMMPS loads the wrong libtorch
and crashes. So FULLY reset the environment before activating:

```bash
unset PYTHONPATH LD_LIBRARY_PATH LAMMPS_PLUGIN_PATH DEEPMD_LMP_PLUGIN
unset CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_PROMPT_MODIFIER
unset CONDA_PREFIX_1 CONDA_PREFIX_2
export CONDA_SHLVL=0
export PATH=/usr/bin:/bin
source "$PREFIX/etc/profile.d/conda.sh"
conda activate "$PREFIX"
# hard-verify: python MUST be the bundle's
command -v python | grep -q "^$PREFIX/" || { echo "WRONG env"; exit 2; }
```
The bundle's activate hook sets `LAMMPS_PLUGIN_PATH=$PREFIX/lib/deepmd_lmp`
(its own plugin). In SLURM, submit with a clean env or reset as above —
`--export=ALL` (default) will otherwise carry a caller's active env in.

## 5. Get a model and freeze it for LAMMPS

Universal foundation models (HuggingFace `deepmodelingcommunity`, CC-BY-4.0,
full periodic table): `DPA-3.1-3M` (3.3M params, newer/faster) or
`DPA-2.4-7M` (6.4M). They are MULTITASK checkpoints — freeze ONE fitting
branch to a single-task TorchScript `.pth`:

```bash
wget -O DPA-3.1-3M.pt \
  https://huggingface.co/deepmodelingcommunity/DPA-3.1-3M/resolve/main/DPA-3.1-3M.pt
# MUST pass --pt (else dp defaults to the TensorFlow backend and fails):
dp --pt freeze -c DPA-3.1-3M.pt -o cascade_model.pth \
   --model-branch MP_traj_v024_alldata_mixu   # broad materials branch
```
(For DPA-2.4-7M use the `DPA-2.4-7M-patched-mt.pt` checkpoint — the one
tagged v3.1.3-compatible.)

## 6. Run in LAMMPS

```
units metal
atom_style atomic
atom_modify map yes            # REQUIRED for message-passing (GNN) models
...
pair_style deepmd /path/cascade_model.pth
pair_coeff * * Si              # map LAMMPS types -> element symbols
```

## Constraints, status, and hardware adaptation

- **[ADAPT] SLURM**: account/partition/gres/memory are site-specific. DPA
  models need generous RAM (a 16 GB cap OOM-killed DPA-3 mid-run; use
  >=32-48 GB). CPU throughput scales with `OMP_NUM_THREADS`.
- **[ADAPT] CUDA/GPU**: match the installer's `cudaXXX` to the driver; the
  bundle's torch supports a wide arch range (sm_50..sm_120, incl. V100
  sm_70). Newer GPUs (A100/H100) are untested here and worth trying for the
  GPU path below.
- **KNOWN STATUS (this system: V100 + deepmd 3.1.3/3.2.0b0, 2026-08):**
  - **CPU LAMMPS: WORKS** (both DPA models run, forces correct). This is
    the adopted production path.
  - **GPU LAMMPS: BLOCKED** — deepmd 3.1.3's C++ TorchScript path crashes
    on the V100 (works CPU + Python-eager, so it's a TorchScript-on-CUDA
    bug). deepmd 3.2.0b0 adds an AOTInductor `.pt2` path (compiled, not
    TorchScript) meant to fix this, but exporting these GNN models to
    `.pt2` fails in `torch.export` on an unbacked-symint (data-dependent
    shape). Re-test on newer GPUs / a stable deepmd >3.2.0.
- **Models run in Python eager on GPU regardless** — so an ASE-based MD
  driver (deepmd's ASE calculator) can use the GPU without LAMMPS, if a
  LAMMPS-free MD path is acceptable.

## Provenance (what was installed here, 2026-08-08)

- `$CPG_SHARE/programs/deepmd-kit-3.1.3-cuda129` — production cascade engine
  (deepmd 3.1.3, torch 2.10, py312).
- `$CPG_SHARE/programs/deepmd-kit-3.2.0b0-cuda129` — for the deferred
  AOTInductor (GPU) experiment; removable (reinstall from this recipe).
- Models: `$CPG_SHARE/share/models/dpa{3.1-3m,2.4-7m}/`.
