#!/bin/bash
# Render the three MOVIE-MODE cascades to MP4, headless, on a CPU node.
# Submit with a dependency on the movie job so it runs when the frames
# exist:
#   sbatch --dependency=afterok:<movie_job_id> \
#          install/tests/t22_energy_scan/render_scan_movies.slurm
#
# The renderer and its OVITO wheel live on SCRATCH, not in this repo:
# the pip `ovito` package is a few hundred megabytes of Qt and is
# regenerable, so it is staged rather than committed. That makes this
# script's one external dependency worth stating out loud -- it checks
# for the renderer and stops with a clear message instead of failing
# somewhere inside Python. (Moving render.py itself into the repo, with
# only the wheel left on scratch, is worth doing and is not done here.)
#
# The library clash is the reason for the two exports below: the wheel
# bundles its own Qt inside PySide6 while the conda environment also
# ships Qt6, and the conda copy wins on the default search path, which
# fails with an undefined-symbol error. Putting the wheel's Qt first
# fixes it. QT_QPA_PLATFORM=offscreen keeps it headless.
#SBATCH --job-name=escan-render
#SBATCH --partition=rulisp-lab
#SBATCH --account=rulisp-lab
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --time=01:00:00
#SBATCH --output=jobs/bulk_si/movie_logs/render-%j.out
#SBATCH --error=jobs/bulk_si/movie_logs/render-%j.err
set -uo pipefail

REPO=/cluster/pixstor/home/rulisp/CPG/cpg-repo/sabsim
FRAMES=$HOME/data/scratch/sabsim/CPG/cpg-repo/sabsim/jobs/bulk_si
TOOLS=$HOME/data/scratch/sabsim/render_tools
OUT=$REPO/jobs/bulk_si/movies
PY=/cluster/VAST/rulisp-lab/cpg/virtual_envs/sabsim/bin/python

if [ ! -f "$TOOLS/render.py" ]; then
    echo "MISSING: $TOOLS/render.py -- the OVITO renderer is staged on"
    echo "scratch and is not there. Nothing to render with; stopping."
    exit 1
fi

mkdir -p "$OUT"
export PYTHONPATH="$TOOLS/ovito_pkg"
export LD_LIBRARY_PATH="$TOOLS/ovito_pkg/PySide6/Qt/lib"
export QT_QPA_PLATFORM=offscreen
export OVITO_THREAD_COUNT=8

# `bombardment` mode colours the argon amber against a muted silicon
# substrate and frames on the ATOMS rather than the simulation box, so
# the slab fills the frame instead of floating in a band of vacuum.
for energy in 040 100 200; do
    dump="$FRAMES/movie_e${energy}/si-si-reference_activation_a.dump"
    if [ ! -f "$dump" ]; then
        echo "=== ${energy} eV: no dump at $dump -- skipped ==="
        continue
    fi
    echo "=== ${energy} eV: $(grep -c '^ITEM: TIMESTEP' "$dump") frames ==="
    "$PY" "$TOOLS/render.py" bombardment \
        "$dump" "$OUT/si_cascade_${energy}eV.mp4" 1280 900
done

echo "=== done ==="
ls -lh "$OUT"
