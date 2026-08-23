# T-22 — Tier-1 energy scan (bombardment energy -> damage depth)

Fans one energy per array task through the MAINLINE pipeline call
(`activate_one_half`), single impact, single seed, many energies —
the allocation that brackets the operating energy, since the
2026-07-21 sweep established that ENERGY sets the depth damage can
REACH while DOSE only fills in disorder.

    sbatch install/tests/t22_energy_scan/energy_scan.slurm
    python install/tests/t22_energy_scan/analyze_energy_scan.py

Runs under DPA-3.1-3M (the model that PASSED the Tier-0 screen) via
its PyTorch `.pth`, which is not GPU-architecture-locked, so it takes
any GPU rather than only the V100s the AOT `.pt2` needs.

## Read this before trusting a result

Three measurement traps, each of which produced confident nonsense
before it was caught (LEDGER T-21):

1. **Do not pair atoms by row order.** The written structure is
   RENUMBERED relative to the input data file (final id N carries
   input id N+1's site). Row pairing reported every atom moving ~55 A
   at every energy. Pair by nearest pristine SITE instead, which needs
   no id correspondence at all.
2. **Do not read amorphization from a cell-averaged coordination.** A
   free surface is already ~50% non-fourfold, which swamps the signal
   from one impact; even an impact-centred cylinder read "no disorder
   above background" at every energy.
3. **One impact is not an amorphized skin.** It leaves 31-98 displaced
   atoms out of 1960 — isolated Frenkel pairs, max deviation ~2 A.
   Amorphization is CUMULATIVE, which is why the classical sweep used
   15-44 impacts. This harness measures damage REACH, not skin depth;
   a dosed run is needed for the latter.
