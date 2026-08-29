#!/bin/bash
# T-35 — which bispectrum engine can SABSIM bind (ARCHITECTURE §2.3,
# §4; DESIGN §3.5)? Runs the deepmd bundle's `lmp` in the same
# isolation the cascade subprocess uses, lists its packages, and tries
# `compute sna/atom` on a small silicon box. Self-logging: the LEDGER
# entry quotes this job's .out verbatim.
#SBATCH --job-name=sabsim-t35-sna
#SBATCH --partition=gpu,requeue
#SBATCH --account=general
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:1
#SBATCH --mem=8G
#SBATCH --time=00:10:00
#SBATCH --output=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim/install/tests/t35_bispectrum_engine/sna_check-%j.out
#SBATCH --error=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim/install/tests/t35_bispectrum_engine/sna_check-%j.err
set -uo pipefail
cd /cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim/install/tests/t35_bispectrum_engine
PREFIX=/cluster/VAST/rulisp-lab/cpg/programs/deepmd-kit-3.2.0b0-cuda129
unset PYTHONPATH LD_LIBRARY_PATH LAMMPS_PLUGIN_PATH DEEPMD_LMP_PLUGIN
unset CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_PREFIX_1 CONDA_PREFIX_2
for v in $(compgen -e); do case "$v" in PMIX_*|OMPI_*|PMI_*) unset "$v";; esac; done
export CONDA_SHLVL=0 PATH=/usr/bin:/bin
source "$PREFIX/etc/profile.d/conda.sh"; conda activate "$PREFIX"
echo "== lmp: $(command -v lmp)"; echo "== node: $(hostname)"
echo "== installed packages (from lmp -h):"
lmp -h | sed -n '/Installed packages/,/^$/p'
echo "== compute sna/atom trial:"
lmp -in sna_check.in -log log.sna_check
STATUS=$?
echo "== lmp exit status: $STATUS"
if [ -f sna_check.dump ]; then
  echo "== dump written: $(grep -c . sna_check.dump) lines; first atom:"
  sed -n '10p' sna_check.dump
  echo "== components per atom: $(($(sed -n '10p' sna_check.dump | wc -w) - 5))"
fi
echo "== bundle python: dscribe?"; python -c "import dscribe; print('dscribe', dscribe.__version__)" 2>&1 | tail -1
echo "T-35 DONE"
