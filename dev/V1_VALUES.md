# v1 Knob Values — RATIFIED

> **Status:** RATIFIED (2026-07-13). The three open forks are resolved
> (see "Ratified decisions" immediately below); the serialization format
> is TOML. These literature-anchored values are now the v1 frozen point.
> The remaining work is to distill them INTO DESIGN's "…and v1"
> subsections (§2.7, §3.6, §4.6, §5.9) and to populate the §1.4
> generator's study spec plus the deployment rc template. This document
> stays as the provenance record for WHY each value was chosen.
>
> **Role:** a working/staging document, **not** a chain level. It exists
> so the value-pinning task survives between sessions.

## Ratified decisions (2026-07-13)

The PI resolved the three forks and fixed the file format:

1. **Ar energy — 500 eV** is the v1 default (the MD-tractable choice). A
   user may override it through the study input file; it is not
   hard-frozen, only defaulted. The validated MD band is 50–500 eV, so
   a user may optionally go **lower (e.g. 50 eV)** for a gentler cascade,
   or higher toward the experimental ~1 keV at a larger-box cost.
2. **Ensemble size — 3 amorphization seeds** to start (the cheaper rung).
3. **SiO₂ face + polymorph — β-cristobalite(100).** The (100) face was
   chosen; the polymorph stays β-cristobalite (closest lattice match to
   silicon), which is cubic, so (100) is a clean low-index face.
4. **Serialization format — TOML** for both the study spec and the
   deployment rc file, unless a concrete blocker appears.

**These are v1 defaults, not freezes.** The Ar energy (1), the crystal
face and polymorph (3), and the target material itself are all knobs the
user changes later through the study input file. v1 fixes a specific,
runnable starting point; it does not remove the choice. Only quantities
listed in Tier D / §1.3 (derived or reference-data-bound) are genuinely
"not a setting."

## Why some "physical" knobs are really MD choices

Real SAB and MD live on different scales, so a few values that look
physical are actually tractability choices — and calling them anything
else would corrupt provenance (`DESIGN.md` §1.6):

- **Ar energy.** Experimental fast-atom-beam is ~1 keV [S1][S2], but MD
  amorphization is validated at 50–500 eV [S3]; a keV cascade needs a
  much bigger box.
- **Hold duration.** Experiments hold ~300 s [S4]; MD reaches ~ns, so the
  MD hold is set by interface equilibration, not by matching 300 s.

This is exactly why `VISION.md` goal 4 calibrates on **ratios and
trends, not absolute values**. The searches also anchored that ratio
target — see "Calibration target" below.

## Tier C — study-point physics (needs ratification)

**Ar energy — 500 eV.** MD amorphization is validated at 50–500 eV with
ZBL+Tersoff [S3]; 500 eV amorphizes reliably and keeps the cascade box
tractable. Experimental FAB is ~1 keV [S1][S2] — bigger box, hence FORK
1. Confidence: medium.

**Angle — normal (0° from surface normal).** SAB FAB is roughly
normal/broad, and §3.6 already froze normal incidence. Amorphous depth
actually peaks ~70° off-normal [S3], a future knob, not v1. Confidence:
high.

**Fluence — tuned to amorphize the skin to ~2–3 nm.** ~500 impacts fully
displaces the surface in MD [S3], and SAB damage layers are thin (~nm).
Fluence is the KNOB; the amorphization DEPTH is the measured outcome
(§3.5), so iterate the fluence until the gate's depth profile hits the
~2–3 nm target. Confidence: medium.

**Co-species / dopant — none (Ar-only).** The dopant is deferred to the
outer-loop sweep (`DESIGN.md` §1.8); iron is only the "first
accommodated" co-species. A clean v1 baseline. Confidence: high.

**Bonding pressure — ~1 MPa (load-controlled).** Si wafers bond at
0.8 MPa held 300 s [S4], and contact loads sit below ~1.6 MPa [S5]. Use
the §5.2 load-controlled press to ~1 MPa, with the displacement cross-
check on the Si/Si reference. Confidence: medium-high (physical target).

**Hold temperature — 300 K.** SAB is a room-temperature process (all
sources; `VISION.md`). Fixed by VISION, not an open knob. Confidence:
high.

**Hold duration — ~100–200 ps (MD).** The experimental ~300 s [S4] is
inaccessible; the MD hold is whatever lets the interface bond and relax,
a convergence-tested quantity, NOT an experiment match. Confidence:
medium.

**Pull-rate ladder — {1, 3.2, 10} m/s** (three rungs, one decade, log-
spaced). §5.4 wants ≥3 rates over a decade; prior art's single 150 m/s
was criticized as far too fast. Slower is better but cost-bounded, and
M3's rate-gap measure reports the distance to quasi-static. Confidence:
medium.

**Miller faces — Si(001) + a low-index β-cristobalite face.** Si(100)/
(001) is the standard wafer orientation; β-cristobalite is the closest-
to-Si SiO₂ polymorph (STRUCTURAL 4). The exact SiO₂ face and cristobalite
-vs-quartz stay a §2.7 follow-on (FORK 3). Confidence: high for Si(001),
medium for the SiO₂ face.

**Ensemble size — 3–5 amorphization seeds × 1–2 velocity seeds.** At
least 3 realizations are needed for the §6.6 spread; more tightens the
error bar at linear cost (FORK 2). Confidence: medium.

## Tier B — numerical/methodology (engineering defaults)

Propose-and-move-on unless the PI objects; converge later:

- **MD timestep:** ~0.5–1 fs for the MLIP MD; sub-fs / adaptive (~0.1 fs)
  during cascade impacts, because ZBL close approaches are stiff.
- **Langevin border damping:** ~0.1–1 ps damping time.
- **`cascade_duration`:** ~5–10 ps per impact (cascade + local quench).
- **`between_impact_relaxation`:** ~5–10 ps, so the border settles back
  to 300 K before the next impact.
- **`reanneal_schedule`:** relax → short NVT hold at ~300–500 K for
  ~tens of ps → quench to 300 K. Gentle by design: it must not un-trap
  the kinetically frozen glass.
- **`force_average_window`:** in grip-DISPLACEMENT units, small vs a
  bond length (DESIGN §5.4), NOT time — a length window resolves the
  pull peak identically across the rate ladder, while a time window
  would smear each rate differently. Noise floors (reference PE drift,
  "force returned to zero," peak resolution) stay relative to thermal RMS.
- **`minimum_bulk_thickness`:** stays a §2.5 convergence study, NOT a
  fixed number here.
- **`target_footprint_area`:** the in-plane area the matched coincidence
  cell is tiled up to, so an areal dose spreads over many impacts rather
  than concentrating on few (§3.6). Default ~1475 Å² reproduces the
  pinned 38.4 Å Si cell (the old 10×10 hardcode); a convergence knob for
  impact statistics, NOT a limit — cost grows with area, so keep it
  minimal and raise it only as the spread demands.

## Calibration target (reference DATA, not a knob)

For §7.4's ratio criterion — reference data, so it belongs to Tier D, but
worth recording now that it is anchored:

- **The ratio target:** Si–Si SAB is ~2× stronger than Si–SiO₂ ("SiO₂
  bonding about half of Si") — this IS the ~2:1 ratio v1 must reproduce.
- **Absolute anchors:** SiO₂/SiO₂ ~1 J/m² [S6]; room-temperature
  hydrophilic (unactivated) ~0.09 J/m² [S7]; Si–Si SAB approaching bulk
  fracture. The exact SAB-regime numbers still need pinning from one
  specific paper (the standing `VISION.md` TODO).

## Open forks for the PI — RESOLVED (2026-07-13)

1. **Ar energy** — resolved to **500 eV** (MD-tractable default;
   user-overridable across 50–500 eV, optionally lower e.g. 50 eV).
2. **Ensemble size** — resolved to **3 amorphization seeds** (the cheaper
   rung; more tightens the error bar at linear cost).
3. **SiO₂ face + polymorph** — resolved to **β-cristobalite(100)** faced
   against **Si(100)**.

Everything else above was taken as proposed.

## Tier D — reminder: these are NOT knobs

Do not pin numbers for these; they are derived or need reference data,
and `DESIGN.md` §1.3 already lists most as "not a setting": lattice
constants, the shared cell / tiling / strain, bond cutoffs, the
interface-subcell size, the activated depth, the potential. The gate
THRESHOLDS (g(r), ring stats, coordination, surface energies, the
Maszara ratio) need reference DATASETS, not chosen constants. Part of
finishing the pinning is pointing the TODO "numeric follow-ons" at §1.3
so they stop masquerading as pinnable.

## What was completed on ratification (2026-07-13)

All five resume steps are now done:

1. ✅ PI ratified the Tier-C table and resolved the three forks.
2. ✅ Distilled the ratified values INTO DESIGN §2.7 (faces),
   §3.6 (energy / fluence-to-depth / seeds), §5.9 (pressure /
   temperature / hold / rate ladder). §4.6 needed no change — the forks
   touch no MLIP-backend knob.
3. ✅ Authored the §1.4 generator's fully-populated **study spec**
   (`dev/templates/study_spec.toml`) and the deployment **rc template**
   (`dev/templates/deployment_rc.toml`, hardware + per-kind-of-job usage).
4. ✅ Pointed the Tier-D "numeric follow-ons" in `TODO.md` at
   `DESIGN.md` §1.3, reclassified out of "pick a value."
5. ✅ Serialization FORMAT decided — **TOML** (§1.8).

**Still genuinely open** (not value-pinning): the schema mechanism on
top of TOML (§1.8); the Tier-D reference-data thresholds and derivations
listed above; and the STRUCTURAL 1b classical-silica choice (BKS vs
Vashishta) behind the bootstrap generator.

## Sources

[S1]: https://en.wikipedia.org/wiki/Surface_activated_bonding
[S2]: https://www.mdpi.com/1996-1944/15/9/3115
[S3]: https://www.beilstein-journals.org/bjnano/articles/14/68
[S4]: https://pmc.ncbi.nlm.nih.gov/articles/PMC9105243/
[S5]: https://www.mdpi.com/2072-666X/11/5/454
[S6]: https://iopscience.iop.org/article/10.7567/JJAP.55.026503
[S7]: https://arxiv.org/pdf/0807.3215
