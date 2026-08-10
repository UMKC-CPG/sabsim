#!/bin/bash
# Launch a Si activation ENERGY BRACKET on a small, fast 4x4x8 slab (~1024
# atoms, ~12 impacts, ~3 h each) to find a gentle-enough universal-cascade
# dose after the full-fluence 75 eV run over-amorphized. Two energies in
# parallel on requeue V100s; each gates its surface directly. sbatch only.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
BENCH=/cluster/VAST/rulisp-lab/cpg/share/models/dpa_gpu_bench

for energy in 25 40; do
    out="$BENCH/si_bracket_${energy}ev"
    export T10_ENERGY_EV="$energy"
    export T10_N_LATERAL=4
    export T10_N_DEPTH=8
    export VALWORK="$out"
    job=$(sbatch --parsable --export=ALL \
        --job-name="si-bracket-${energy}ev" \
        -o "$BENCH/si-bracket-${energy}ev-%j.out" \
        -e "$BENCH/si-bracket-${energy}ev-%j.err" \
        "$HERE/si_energy_bracket.slurm")
    echo "Si @ ${energy} eV (4x4x8) submitted: job $job -> $out"
done
echo "Each gates its surface; compare to pick a gate-passing Si activation."
