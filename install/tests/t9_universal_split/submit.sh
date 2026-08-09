#!/bin/bash
# Submit T-9 — the re-architected universal split — as a two-job chain:
#
#   A (t9a) = universal cascade-ONLY activate + wide-gap assemble, on the
#             GPU via the deepmd bundle subprocess; writes the pair.
#   B (t9b) = bond heal + per-wafer gate + press under the committee-of-one
#             deepmd, IN-PROCESS on the GPU; depends on A (afterok) so it
#             reads A's assembled pair across a separate submission — the
#             same activate->bond on-disk handoff production uses.
#
# Prints both job IDs; append the LEDGER (install/tests/LEDGER.md) entry
# from these plus the quoted evidence in their .out files. Run from a login
# shell with the sabsim env active (do NOT run lmp here — sbatch only).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

job_a=$(sbatch --parsable "$HERE/t9a_activate_assemble.slurm")
echo "T-9a (activate + wide assemble) submitted: job $job_a"

job_b=$(sbatch --parsable --dependency=afterok:"$job_a" \
    "$HERE/t9b_bond_press.slurm")
echo "T-9b (bond heal + gate + press) submitted: job $job_b (afterok:$job_a)"

echo
echo "T-9 chain: A=$job_a  B=$job_b"
echo "Logs: /cluster/VAST/rulisp-lab/cpg/share/models/dpa_gpu_bench/"
echo "  t9-activate-$job_a.out  and  t9-bond-$job_b.out"
