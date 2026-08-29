#!/bin/bash
# T-13 — SiO2/LiNbO3 interface bond-debond under Prakash's trained model.
# Assembles the two matched amorphized oxide surfaces and runs the bond
# flow IN-PROCESS on the GPU under model.pb (type_map [Si,Li,Nb,O]),
# recording a press/pull movie. DEMO MODE (no oxide gate reference; the
# gate cannot tell the two wafers apart) — a workflow visual, not a
# measurement.
#SBATCH --job-name=t13-oxide-bond
#SBATCH --partition=gpu
#SBATCH --account=general
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:V100-PCIE-32GB:1
#SBATCH --mem=48G
#SBATCH --time=04:00:00
#SBATCH --chdir=/cluster/VAST/rulisp-lab/cpg/share/models/dpa_gpu_bench
#SBATCH --output=t13-oxide-bond-%j.out
#SBATCH --error=t13-oxide-bond-%j.err
set -uo pipefail

REPO=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim
SHARE=/cluster/VAST/rulisp-lab/cpg
BENCH="$SHARE/share/models/dpa_gpu_bench"

# Prakash's trained SiO2+LiNbO3 model (the interface potential), the two
# matched amorphized surfaces, their shared-cell match, and demo mode.
export SABSIM_DEEPMD_MODEL="$SHARE/share/training_deepmd_sio2_linbo3/model.pb"
export SABSIM_BOND_DEMO=1
export SABSIM_TEMPLATE="$REPO/share/templates/study_spec.toml"
export SIO2_SURFACE="$BENCH/t12_val/sio2_activated.extxyz"
export LINBO3_SURFACE="$BENCH/t12_val_linbo3_25ev/linbo3_activated.extxyz"
export MATCH_PKL="$BENCH/t12_val/match.pkl"
export VALWORK="$BENCH/t13_val"
mkdir -p "$VALWORK"

unset SLURM_MEM_PER_NODE SLURM_MEM_PER_CPU SLURM_MEM_PER_GPU
unset LAMMPS_PLUGIN_PATH

echo "=== node / gpu ==="; nvidia-smi -L || true
source "$SHARE/virtual_envs/sabsim/bin/activate" 2>/dev/null || true
module use "$SHARE/modulefiles"
module load cpg_lammps_conda/2024.08.29-deepmd
module list 2>&1 || true
python -c "import sabsim, lammps; print('sabsim + lammps import OK')" || exit 2
ls "$SABSIM_DEEPMD_MODEL" || { echo "Prakash model missing"; exit 3; }
ls "$SIO2_SURFACE" "$LINBO3_SURFACE" || { echo "surfaces missing"; exit 4; }

echo "=== running T-13 (SiO2/LiNbO3 bond-debond, demo) ==="
srun --mpi=pmix -n 1 \
    python "$REPO/install/tests/t13_oxide_bond/t13_oxide_bond.py"
rc=$?
echo "=== T-13 exit $rc ==="
if [ $rc -ne 0 ]; then
    echo "--- press log tail ---"
    tail -40 "$VALWORK/log.press" 2>/dev/null || true
fi
echo "=== DONE ==="
exit $rc
