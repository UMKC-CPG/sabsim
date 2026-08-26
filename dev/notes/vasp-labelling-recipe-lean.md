# The lean VASP labelling recipe — v0, 2026-08-26

The settings block DESIGN §4.8 says the force-model recipe must carry:
the VASP settings every training label is computed with, and which the
all-electron cross-check (`interface_fidelity`, §6.4) later inherits
unchanged. This is the FIRST version, chosen on Paul's direction to be
cheap: get the whole bootstrap to run end to end, learn the cost by
spending, then dial the accuracy up. Every number here is a starting
value, and the "later" column says what the upgrade is.

## 1. Which pseudopotential for which element

VASP's PAW library offers several potentials per element, differing in
how many electrons are treated explicitly (the rest are frozen into the
core) and therefore in how hard the wavefunctions are — which sets the
plane-wave cutoff and so the cost. The lean choices:

| Element | Choice (lean) | Valence e⁻ | ENMAX (eV) | Why, and the upgrade |
|---|---|---|---|---|
| Si | `Si` | 4 | 245 | The standard one; nothing cheaper is sensible. No upgrade needed. |
| O | `O` | 6 | 400 | Oxygen sets the cutoff for every oxide. `O_s` (soft, ENMAX 283) would be cheaper but softens the short, stiff Si–O and Nb–O bonds, which is exactly the chemistry at the interface; not worth the saving. Upgrade: `O_h` (hard) only if bond lengths under 1.5 Å ever matter — they do not here. |
| Ar | — | — | — | The projectile is stripped before any structure is labelled (§3.4), so no argon potential is needed in the training set at all. |
| Li | `Li` | 1 (2s) | 140 | The 1s² shell frozen in the core. In lithium niobate Li is essentially Li⁺ in an ionic site, and the frozen 1s is a small error for bond lengths and energies at training-data quality. The alternative `Li_sv` treats 1s as valence (3 e⁻, ENMAX 499) and would DOUBLE the cutoff of the whole oxide set; it is the Materials-Project default and the upgrade if Li site energies look wrong against the DPA model or experiment. |
| Nb | `Nb_pv` | 11 (4p⁶ 5s¹ 4d⁴) | 209 | The 4p semicore MUST be explicit: Nb is formally Nb⁵⁺ in LiNbO₃, and with only the 5s/4d electrons (`Nb`, 5 e⁻) the ion is described badly. `Nb_pv` is the Materials-Project choice and is cheap (ENMAX 209). `Nb_sv` (4s too, 13 e⁻, ENMAX 293) is the upgrade; it changes little for an oxide at this level. |

Functional: PBE, no +U (Nb is d⁰ in LiNbO₃; the Materials Project
applies no U to Nb), no van der Waals correction, no spin polarisation
(`ISPIN = 1` — every system here is closed-shell; dangling bonds in an
amorphous skin can carry a moment, and turning `ISPIN = 2` on is a
"later" item that roughly doubles the cost).

## 2. Plane-wave cutoff

`ENCUT = 350 eV` for every calculation, every material. One value for
the whole committee so energies are comparable across the training set.
It is below the conservative 1.3 × ENMAX(O) = 520 eV, and slightly below
1.0 × ENMAX(O) = 400 eV — "a bit on the lower side", as asked. Forces
are converged more slowly than energies with cutoff, so the first thing
to check when the committee looks noisy is a 350 → 450 eV comparison on
a handful of structures. Since ENCUT is fixed across a cell-size series
(the bulk strain family), Pulay stress is present but is common to all
members of the series; `PREC = Normal` (the cheaper FFT grid).

## 3. k-points — Γ only except for bulk crystals

- **Bulk ground state and bulk strain families** (small periodic
  crystals, 8–64 atoms): a real Brillouin-zone sampling,
  `KSPACING = 0.5` Å⁻¹ with `KGAMMA = .TRUE.` (a Γ-centred grid; for a
  5.43 Å Si cell this is 3×3×3, for a 2×2×2 supercell it is 2×2×2).
  Coarse, but energies of a semiconductor converge fast with k.
- **Everything else** — clean surfaces, rattled cells, melt-quench
  amorphous blocks, warm runs, activated surfaces, the joint/pressed/
  pulled interface sub-cells — exactly one k-point, Γ. Written as an
  explicit `KPOINTS` file (`Gamma`, `1 1 1`) and run with the
  Γ-only VASP build (`vasp_gam`), which is roughly twice as fast and
  uses half the memory of the standard build for the same calculation.
  These cells are all ≥ 10 Å in every direction, where Γ is a fair
  sampling for a semiconductor or insulator.

## 4. Smearing and convergence — not demanding

```
ISMEAR = 0        # Gaussian smearing — safe for insulators, amorphous
SIGMA  = 0.10     # eV
EDIFF  = 1e-4     # eV, electronic convergence per cell
NELM   = 60       # give up on a cell that will not converge
ALGO   = Fast     # Davidson then RMM-DIIS
PREC   = Normal
LREAL  = Auto     # real-space projection: cheaper for > ~50 atoms,
                  # costs a little force noise — fine for training data
NSW    = 0        # single-point labels: no relaxation
IBRION = -1
LWAVE  = .FALSE.  # write no WAVECAR / CHGCAR (disk)
LCHARG = .FALSE.
```

A cell that fails to converge in `NELM` steps is DROPPED from the
training set and logged, never labelled with a half-converged energy.

## 5. The interface sub-cell for labelling

Confirmed with Paul: the sub-cell is the joint cell with the deeper
crystalline (or near-crystalline) layers removed, keeping only a couple
of ordered layers under each activated skin — the surface atoms are what
the training is for. Rules (§6.4): full lateral periodicity kept;
truncated only along the interface normal; removal in WHOLE crystal
layers so the new join is seamless; and the outer faces that result are
real free surfaces. For silicon (100) a layer is 1.36 Å, so "two
layers" under a 7–10 Å activated skin gives a sub-cell of roughly
2 × (10 + 3) Å = 26 Å thick, ~150–250 atoms at the 7×7 footprint.
That is a Γ-only `vasp_gam` job of order 10–30 minutes on one node at
these settings.

## 6. What is NOT decided here, and the budget

- The number of labels per family. §4.8 names six calm families and
  five hard families; the cost is learned by spending: label a small
  batch (say 10 per family, ~110 calculations) first and time it.
- `ISPIN = 2`, `ENCUT` 450, `Li_sv`, `KSPACING` 0.3 are the four
  "later" knobs, in that order of expected effect.
- Whether the colleague's silicon `graph.pb` and SiO₂/LiNbO₃ `model.pb`
  were trained with retrievable VASP settings. If so, matching them
  makes the borrowed models and the new committee comparable — worth
  asking before the first batch runs.
