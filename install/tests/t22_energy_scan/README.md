# T-22 — Tier-1 energy scan (bombardment energy -> damage reach)

Fans one energy per array task through the MAINLINE pipeline call
(`activate_one_half`), single impact, single seed, many energies —
the allocation that brackets the operating energy, since the
2026-07-21 sweep established that ENERGY sets the depth damage can
REACH while DOSE only fills in disorder.

    mkdir -p jobs/bulk_si/scan_logs
    sbatch install/tests/t22_energy_scan/energy_scan.slurm
    python install/tests/t22_energy_scan/analyze_energy_scan.py

Runs under DPA-3.1-3M (the model that PASSED the Tier-0 screen) via
its PyTorch `.pth`, which is not GPU-architecture-locked, so it takes
any GPU rather than only the V100s the AOT `.pt2` needs.

Task 12 is a NULL CONTROL: the identical path with ZERO impacts, so
the slab is still read, still pre-relaxed, still cleaned up and still
written out. Its vacated-site count is the measurement's
false-positive floor.

## What is measured, and what is not

**Reach** — the deepest lattice site the cascade EMPTIED. This is the
ion-range proxy the energy bracket needs, and one impact is enough to
place it.

**Not a skin thickness.** A single ion empties a scattering of sites
along one track; it does not dissolve a layer. Every slab-averaged
skin measure therefore reads flat here, the §3.5 gate's
`activated_depth` among them. Amorphization is CUMULATIVE — the
classical sweep used 15–44 impacts — so the skin needs a dosed run,
which this is not.

## Read this before trusting a result

Five measurement traps, each of which produced confident nonsense
before it was caught (LEDGER T-21, T-22):

1. **Do not pair atoms by row order.** The written structure is
   RENUMBERED relative to the input data file (final id N carries
   input id N+1's site). Row pairing reported every atom moving ~55 Å
   at every energy. `damage_reach` instead asks, for each pristine
   SITE, how far away the nearest damaged atom is — a judgement that
   needs no id correspondence at all.
2. **Do not read amorphization from a cell-averaged coordination.** A
   free surface is already ~50% non-fourfold, which swamps the signal
   from one impact; even an impact-centred cylinder read "no disorder
   above background" at every energy.
3. **Do not use the as-cut slab as the background.** The first
   analysis compared bombarded slabs (relaxed, cascaded, cleaned up)
   against the input data file (none of those things) and had the
   bombarded surfaces reading LESS disordered — 0.26–0.48 against a
   0.52 "pristine" — because it was measuring the pre-relax, not
   damage. The null control exists to be that background.
4. **The zero-impact null is a background for REACH, not for
   COORDINATION.** The relaxation lives inside the impact loop, so a
   zero-impact run issues no `run` command at all and comes out
   minimized, near 0 K, while every bombarded point ran ~1 ps of warm
   MD. Differencing their coordinations measures TEMPERATURE — thermal
   rattle across the 3.0 Å cutoff — and duly reported a 30-39 Å "skin"
   at 20 eV. It is a perfectly good floor for vacancy (thermal rattle
   is ~0.1 Å against a 1 Å threshold, and the null's own subsurface
   reach came out exactly 0.00 Å). A thermally matched null needs the
   relaxation to run at zero impacts.
5. **A reporting bug can cost a whole allocation.** Job 16733423 ran
   all twelve cascades and then died in every task on
   `result.verdict`: activation became cascade-only in the 2026-08-08
   re-arch and the §3.5 gate moved to the bond flow, so
   `activate_one_half` returns a bare `CascadeOutcome`. The physics
   was fine; nothing was reported.

## Movie mode — watching a point instead of measuring it

The scan records numbers, not pictures. Trajectory recording is off by
default across the whole code base (`sabsim.pipeline.run_options`)
because frames cost wall clock inside the hot cascade loop and the
files are large, so a measurement run writes exactly ONE frame: the
closing `write_dump` of the final structure, which is a snapshot and
not a trajectory. Job 16795220 therefore left nothing to animate.

Passing `--movie` after the task index turns recording on for that
invocation:

```bash
mkdir -p jobs/bulk_si/movie_logs jobs/bulk_si/movies
sbatch install/tests/t22_energy_scan/energy_scan_movie.slurm
sbatch --dependency=afterok:<job> \
       install/tests/t22_energy_scan/render_scan_movies.slurm
```

Three things about it are deliberate.

**It never touches the measurement.** Movie runs write to `movie_e100`
rather than `scan_e100`, and their logs go to `movie_logs/` rather than
`scan_logs/`. The analyser globs `escan-*.out` under `scan_logs/` and
keeps only the NEWEST job's `SCANRESULT` lines, so a three-point movie
run landing there would quietly replace the thirteen-point measured
table with three rows and look entirely plausible doing it.

**The frame spacing is not a clock.** The cascade integrates under
`fix dt/reset` with the timestep floating between 1e-5 and 0.1 ps, so
one frame per 100 STEPS samples the violent opening densely and the
cooling tail sparsely. It reads as natural slow-motion on impact, which
is what makes the movie legible — but no velocity can be read off it.

**The count is reported, not assumed.** Each movie task prints a
`SCANMOVIE` line carrying the dump's actual frame count, so the log
says whether a movie exists rather than leaving that to be found out at
render time. A count of 1 means the switch did not take effect.

The renderer itself (`render.py`, `bombardment` mode: argon amber
against muted silicon, framed on the atoms rather than the vacuum-
filled box) is staged on scratch under `render_tools/` along with the
pip OVITO wheel, which is a few hundred megabytes of Qt and does not
belong in the repository. Moving `render.py` alone into the repo is
worth doing and has not been done.
