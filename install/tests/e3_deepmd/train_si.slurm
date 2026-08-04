#!/bin/bash
# E3 step 1 of 2 — TRAIN + FREEZE a small Si deepmd model IN sabsim_dev.
#
# Purpose: mint a version-matched frozen model so E3 step 2 can run a real
# `pair_style deepmd` force step on the Stack C engine.  We train with
# sabsim_dev's OWN deepmd-kit 3.1.3 (PyTorch backend) — NOT the students'
# separate deepmd 2.2.10 / TensorFlow env — so the frozen .pth is
# guaranteed loadable by our 3.1.3 LAMMPS plugin.  The run is deliberately
# SHORT (input.json: numb_steps=3000): the goal is a valid, finite-force
# model, not converged physics.  Training data is the real shared AIMD Si
# set (read-only); all writable output goes to SABSIM_SCRATCH.
#SBATCH --job-name=sabsim-e3-train-si
#SBATCH --partition=gpu
#SBATCH --account=rulisp-lab
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=8
#SBATCH --gres=gpu:A100:1
#SBATCH --mem=48G
#SBATCH --time=00:40:00
#SBATCH --output=/home/rulisp/data/scratch/sabsim/install-tests/e3_deepmd_si/train-%j.out
#SBATCH --error=/home/rulisp/data/scratch/sabsim/install-tests/e3_deepmd_si/train-%j.err

set -euo pipefail

REPO=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim/install/tests/e3_deepmd
ART=/home/rulisp/data/scratch/sabsim/install-tests/e3_deepmd_si

# Activate sabsim_dev (deepmd-kit 3.1.3 + torch 2.11 + TF 2.19) via the
# cpg mamba that owns this env.  We do NOT source the venv: training uses
# the conda `dp` CLI, not the editable sabsim package.
source /cluster/VAST/rulisp-lab/cpg/mamba/etc/profile.d/conda.sh
conda activate sabsim_dev

cd "$ART"

# --- Self-logging (ledger rule #2) -----------------------------------
echo "host        : $(hostname)"
echo "node GPUs   : ${CUDA_VISIBLE_DEVICES:-<none>}"
echo "dp binary   : $(command -v dp)"
echo "deepmd ver  : $(python -c 'import deepmd,sys; print(deepmd.__version__)')"
echo "torch ver   : $(python -c 'import torch; print(torch.__version__, \
                      \"cuda\", torch.cuda.is_available())')"
echo "input.json  : $REPO/input.json"
echo "workdir     : $ART"
echo "====================================================================="

# --- Train (PyTorch backend), then FREEZE to a portable .pth ----------
# `--pt` selects the PyTorch backend explicitly.  Checkpoints (model.ckpt*)
# and lcurve.out land in $ART; freezing reads the latest checkpoint here.
dp --pt train "$REPO/input.json" 2>&1 | tail -40
echo "=== training exit: $? ==="

dp --pt freeze -o "$ART/frozen_model_si.pth" 2>&1 | tail -20
echo "=== freeze exit: $? ==="

echo "--- frozen model produced ---"
ls -la "$ART/frozen_model_si.pth"
