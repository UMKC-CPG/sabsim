#!/bin/bash
# T-36: `sabsim bootstrap generate --skip-collection2` on a GPU node
# under the environment-library code (commit 995bc93): Collection 1 of
# the silicon recipe is rebuilt AND the §3.5 ENVIRONMENT LIBRARY is
# written beside it (descriptors via the bundle's `compute sna/atom`,
# the warm-vs-melt-quench self-check). On success the library is copied
# to the deployment share so a study can name it. Judged from the
# library sidecar it writes (self-check fractions, thermal scatter).
#SBATCH --job-name=t36-env-lib
#SBATCH --partition=gpu,requeue
#SBATCH --account=general
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:H100:1
#SBATCH --mem=48G
#SBATCH --time=03:00:00
#SBATCH --output=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim/jobs/bootstrap_si_lib/t36-%j.out
#SBATCH --error=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim/jobs/bootstrap_si_lib/t36-%j.err
set -uo pipefail
REPO=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim
SHARE=/cluster/VAST/rulisp-lab/cpg
export SABSIM_SCRATCH="$HOME/data/scratch/sabsim"
export SABSIM_SHARE="$SHARE"
export SABSIM_CASCADE_ENGINE_PREFIX="$SHARE/programs/deepmd-kit-3.2.0b0-cuda129"
source "$SHARE/virtual_envs/sabsim/bin/activate"
cd "$REPO/jobs/bootstrap_si_lib"
echo "=== $(date) node $(hostname) commit $(git -C $REPO rev-parse --short HEAD) ==="
nvidia-smi -L || true
unset SLURM_MEM_PER_NODE SLURM_MEM_PER_CPU SLURM_MEM_PER_GPU
srun --mpi=pmix -n 1 sabsim bootstrap generate recipe.toml --skip-collection2
rc=$?
echo "=== generate exit $rc ==="
BOOT="$SABSIM_SCRATCH/CPG/cpg-repo/sabsim/jobs/bootstrap_si_lib/bootstrap/si-lean-v0"
LIB="$BOOT/collection1"
echo "=== library sidecar ==="
cat "$LIB/environment_library.toml" 2>/dev/null | grep -v "^#" | head -60
if [ $rc -eq 0 ] && [ -f "$LIB/environment_library.toml" ]; then
  DEST="$SHARE/share/environment_libraries/silicon"
  mkdir -p "$DEST"
  cp "$LIB/environment_library.toml" "$LIB/environment_library.npz" "$DEST/"
  echo "T36RESULT library copied to $DEST"
  ls -l "$DEST"
fi
exit $rc
