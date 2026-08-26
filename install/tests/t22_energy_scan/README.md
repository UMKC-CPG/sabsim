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
