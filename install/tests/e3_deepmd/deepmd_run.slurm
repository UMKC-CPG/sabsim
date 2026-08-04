#!/bin/bash
# E3 step 2 of 2 — run a REAL pair_style deepmd force step on the Stack C
# engine, using Prakash's PRODUCTION Si model: a fully-trained (400k step)
# deepmd-kit 2.2.10 / TensorFlow graph (`graph.pb`) in the shared
# train_deepmd_si dir.  This doubles as the training->inference SEAM test:
# a 2.2.10 / TF `.pb` loaded by our Stack C deepmd 3.1.3 plugin (which
# ships both TF and PyTorch backends).  One GPU node — the bond stage is
# GPU.  Single rank: the force computation is what E3 adds; multi-rank
# comm-sharing is already E4-proven.
#SBATCH --job-name=sabsim-e3-deepmd-run
#SBATCH --partition=gpu
#SBATCH --account=rulisp-lab
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=8
#SBATCH --gres=gpu:A100:1
#SBATCH --mem=32G
#SBATCH --time=00:20:00
#SBATCH --output=/home/rulisp/data/scratch/sabsim/install-tests/e3_deepmd_si/run-%j.out
#SBATCH --error=/home/rulisp/data/scratch/sabsim/install-tests/e3_deepmd_si/run-%j.err

# No `set -e`: we want the probe's own verdict, not an early abort.

HERE=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim/install/tests/e3_deepmd
DEV=/cluster/VAST/rulisp-lab/cpg/mamba/envs/sabsim_dev
ENGINE=/cluster/VAST/rulisp-lab/cpg/programs/lammps/2024.08.29-deepmd-conda-ompi5.0.10
VENV_PYTHON=/cluster/VAST/rulisp-lab/cpg/virtual_envs/sabsim_dev/bin/python
MODEL=/cluster/VAST/rulisp-lab/cpg/share/train_deepmd_si/graph.pb

# --- Fully activate sabsim_dev, then layer the Stack C engine ---------
# A TF `.pb` needs the deepmd TensorFlow backend + its runtime libs, which
# the env's activate.d hooks wire up.  So we activate the WHOLE env (the
# correct system mamba hook — the cpg-local one does not exist), exactly
# as sabsimrc_dev / a real bond job would, THEN prepend the Stack C engine
# so `lammps` resolves to its wrapper + liblammps (conda libmpi 5.0.10).
set +u
source /cluster/software/common/mamba/1.4.2/etc/profile.d/conda.sh
conda activate sabsim_dev
set -u

export PYTHONPATH="$ENGINE/lib64/python:${PYTHONPATH:-}"
export LD_LIBRARY_PATH="$ENGINE/lib64:$DEV/lib:${LD_LIBRARY_PATH:-}"
export DEEPMD_LMP_PLUGIN="$DEV/lib/libdeepmd_lmp.so"
export E3_MODEL="$MODEL"

# Launcher fixes proven earlier: clear the mutually-exclusive memory
# exports, and drop any inherited LAMMPS_PLUGIN_PATH so the plugin loads
# ONLY from the explicit `plugin load` the probe issues (ARCHITECTURE §4.4).
unset SLURM_MEM_PER_NODE SLURM_MEM_PER_CPU SLURM_MEM_PER_GPU
unset LAMMPS_PLUGIN_PATH

# --- Self-logging (ledger rule #2) -----------------------------------
echo "host       : $(hostname)"
echo "node GPUs  : ${CUDA_VISIBLE_DEVICES:-<none>}"
echo "engine     : $ENGINE"
echo "python     : $VENV_PYTHON"
echo "model      : $E3_MODEL  (deepmd 2.2.10 / TF graph.pb)"
echo "plugin     : $DEEPMD_LMP_PLUGIN"
echo "conda env  : ${CONDA_DEFAULT_ENV:-<none>}"
echo "--- model file present? ---"
ls -la "$E3_MODEL" 2>&1
echo "--- libmpi that liblammps links ---"
ldd "$ENGINE/lib64/liblammps.so" | grep -iE "libmpi|open-pal" | head -2
echo "====================================================================="

echo "########### E3: pair_style deepmd force step (1 GPU) ###########"
srun --mpi=pmix -n 1 "$VENV_PYTHON" "$HERE/deepmd_run_probe.py"
echo "=== E3 run exit: $? ==="
