#!/bin/bash
# Si activation at LOWER energy on a SMALLER, faster slab, to find a
# gentle-enough universal-cascade dose (the full 27-impact/75 eV run
# over-drove Si into a dense disordered state that failed the coordination
# gate and shed atoms when pressed). T10_ENERGY_EV / T10_N_LATERAL /
# T10_N_DEPTH / VALWORK arrive via --export (submit_si_energy_bracket.sh).
# On requeue (idle V100s); ~3 h for a 4x4x8 slab, so preemption risk is low.
#SBATCH --job-name=si-bracket
#SBATCH --partition=requeue
#SBATCH --account=general
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:V100-PCIE-32GB:1
#SBATCH --mem=48G
#SBATCH --time=06:00:00
#SBATCH --chdir=/cluster/VAST/rulisp-lab/cpg/share/models/dpa_gpu_bench
#SBATCH --output=si-bracket-%j.out
#SBATCH --error=si-bracket-%j.err
set -uo pipefail

REPO=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim
SHARE=/cluster/VAST/rulisp-lab/cpg
BENCH="$SHARE/share/models/dpa_gpu_bench"

export SABSIM_CASCADE_ENGINE_PREFIX="$SHARE/programs/deepmd-kit-3.2.0b0-cuda129"
export SABSIM_CASCADE_MLIP_MODEL="$BENCH/v320fix/dpa24.pt2"
export SABSIM_ALLOW_UNVALIDATED_POTENTIAL=1
export SABSIM_TEMPLATE="$REPO/share/templates/study_spec.toml"
export VALWORK="${VALWORK:-$BENCH/si_bracket_val}"
mkdir -p "$VALWORK"

echo "=== Si bracket: energy=${T10_ENERGY_EV:-75} eV  slab="\
"${T10_N_LATERAL:-6}x${T10_N_LATERAL:-6}x${T10_N_DEPTH:-10} ==="
echo "=== node / gpu ==="; nvidia-smi -L || true
source "$SHARE/virtual_envs/sabsim/bin/activate" 2>/dev/null || true
python -c "import sabsim, ase; print('sabsim env OK')" || exit 2
ls "$SABSIM_CASCADE_MLIP_MODEL" || { echo "MODEL missing"; exit 3; }

python "$REPO/install/tests/t10_universal_activation/t10_activate_gate.py"
rc=$?
echo "=== si-bracket exit $rc ==="
echo "=== DONE ==="
exit $rc
