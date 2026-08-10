#!/bin/bash
# Re-run the LiNbO3 activation at LOWER beam energies to find the sweet spot
# that amorphizes a thin skin without the heavy, Li-preferential sputtering
# 75 eV caused (~47% atom loss, ~40 A ablated; the bottom ~18 A held, so it
# is surface ablation — lower energy is the fix). Two jobs in parallel, each
# reusing the ONE matched, commensurate half in t12_val and writing to its
# OWN energy-tagged dir (so nothing clobbers the 75 eV result or each other).
# sbatch only — no lmp on the login node.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
BENCH=/cluster/VAST/rulisp-lab/cpg/share/models/dpa_gpu_bench

half="$BENCH/t12_val/linbo3_half.pkl"
[ -f "$half" ] || {
    echo "missing $half — run build_matched_halves.py first"; exit 2; }

for energy in 25 40; do
    out="$BENCH/t12_val_linbo3_${energy}ev"
    # Export the per-run knobs, then carry them in with --export=ALL.
    export T12_HALF_NAME=linbo3
    export T12_ENERGY_EV="$energy"
    export VALWORK="$out"
    export T12_BUILD_DIR="$BENCH/t12_val"
    job=$(sbatch --parsable --export=ALL \
        --job-name="t12-linbo3-${energy}ev" \
        -o "$BENCH/t12-linbo3-${energy}ev-%j.out" \
        -e "$BENCH/t12-linbo3-${energy}ev-%j.err" \
        "$HERE/activate_half.slurm")
    echo "LiNbO3 @ ${energy} eV submitted: job $job -> $out"
done
echo "Compare survivors + stoichiometry across energies to pick the surface."
