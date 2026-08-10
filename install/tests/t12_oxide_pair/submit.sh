#!/bin/bash
# Launch BOTH matched-oxide activations in parallel on free V100s:
#   SiO2 (wafer A) and LiNbO3 (wafer B), each amorphized by the universal
#   DPA-2.4-7M cascade. They read the pre-built, commensurate halves
#   `build_matched_halves.py` wrote into VALWORK, so run that FIRST:
#     VALWORK=$SHARE/share/models/dpa_gpu_bench/t12_val \
#       python install/tests/t12_oxide_pair/build_matched_halves.py
# Then submit here (sbatch only — no lmp on the login node). Prints both
# job IDs; append the ledger from these + the .out evidence.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
BENCH=/cluster/VAST/rulisp-lab/cpg/share/models/dpa_gpu_bench

for half in sio2 linbo3; do
    ls "$BENCH/t12_val/${half}_half.pkl" >/dev/null || {
        echo "missing $BENCH/t12_val/${half}_half.pkl — run "
        echo "build_matched_halves.py first"; exit 2; }
done

sio2_job=$(sbatch --parsable \
    --export=ALL,T12_HALF_NAME=sio2 \
    --job-name=t12-sio2 \
    -o "$BENCH/t12-sio2-%j.out" -e "$BENCH/t12-sio2-%j.err" \
    "$HERE/activate_half.slurm")
echo "SiO2 activation (wafer A) submitted: job $sio2_job"

linbo3_job=$(sbatch --parsable \
    --export=ALL,T12_HALF_NAME=linbo3 \
    --job-name=t12-linbo3 \
    -o "$BENCH/t12-linbo3-%j.out" -e "$BENCH/t12-linbo3-%j.err" \
    "$HERE/activate_half.slurm")
echo "LiNbO3 activation (wafer B) submitted: job $linbo3_job"

echo
echo "T-12 oxide activations: SiO2=$sio2_job  LiNbO3=$linbo3_job"
echo "Logs + movies in $BENCH/ (t12-*-<job>.out, t12_val/*_movie.dump)"
