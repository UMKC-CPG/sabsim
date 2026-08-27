#!/bin/bash
# T-26: `sabsim bootstrap generate --skip-collection2` on a GPU node —
# Collection 1 of the silicon recipe built for real: the §2.2 lattice
# derivation, the static families, and the melt-quench + warm-run
# dynamics under DPA-3.1-3M out-of-process. Judged from the structures
# file it writes (counts per family) and the melt-quench frames.
#SBATCH --job-name=t26-boot-gen
#SBATCH --partition=gpu,requeue
#SBATCH --account=general
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:H100:1
#SBATCH --mem=48G
#SBATCH --time=03:00:00
#SBATCH --output=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim/jobs/bootstrap_si/t26-%j.out
#SBATCH --error=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim/jobs/bootstrap_si/t26-%j.err
set -uo pipefail
REPO=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim
SHARE=/cluster/VAST/rulisp-lab/cpg
export SABSIM_SCRATCH="$HOME/data/scratch/sabsim"
export SABSIM_SHARE="$SHARE"
export SABSIM_CASCADE_ENGINE_PREFIX="$SHARE/programs/deepmd-kit-3.2.0b0-cuda129"
source "$SHARE/virtual_envs/sabsim/bin/activate"
cd "$REPO/jobs/bootstrap_si"
echo "=== $(date) node $(hostname) ==="; nvidia-smi -L || true
unset SLURM_MEM_PER_NODE SLURM_MEM_PER_CPU SLURM_MEM_PER_GPU
srun --mpi=pmix -n 1 sabsim bootstrap generate recipe.toml --skip-collection2
rc=$?
echo "=== generate exit $rc ==="
STRUCT="$SABSIM_SCRATCH/CPG/cpg-repo/sabsim/jobs/bootstrap_si/bootstrap/si-lean-v0/structures.extxyz"
python - "$STRUCT" <<'PY'
import sys
from ase.io import read
frames = read(sys.argv[1], index=":")
by = {}
for f in frames:
    by.setdefault(f.info["family"], []).append(f)
for family, fs in sorted(by.items()):
    print(f"T26RESULT family={family} count={len(fs)} atoms={len(fs[0])}")
PY
exit $rc
