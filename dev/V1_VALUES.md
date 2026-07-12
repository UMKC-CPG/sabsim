# v1 Knob Values — PROPOSED, awaiting ratification

> **Status:** PROPOSED (2026-07-12), **NOT yet ratified.** These are
> literature-anchored starting values for the v1 frozen point, drafted
> for the PI to ratify. Once ratified they distill INTO DESIGN's
> "…and v1" subsections (§2.7, §3.6, §4.6, §5.9) and become the content
> of the §1.4 generator's fully-populated study spec plus the deployment
> rc template. Until then, treat nothing here as canonical.
>
> **Role:** a working/staging document, **not** a chain level. It exists
> so the value-pinning task survives between sessions. When resumed, see
> "When we resume" at the bottom.

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
- **`force_average_window`:** ~a few ps; noise floors (reference PE
  drift, "force returned to zero," peak resolution) set relative to the
  thermal RMS.
- **`minimum_bulk_thickness`:** stays a §2.5 convergence study, NOT a
  fixed number here.

## Calibration target (reference DATA, not a knob)

For §7.4's ratio criterion — reference data, so it belongs to Tier D, but
worth recording now that it is anchored:

- **The ratio target:** Si–Si SAB is ~2× stronger than Si–SiO₂ ("SiO₂
  bonding about half of Si") — this IS the ~2:1 ratio v1 must reproduce.
- **Absolute anchors:** SiO₂/SiO₂ ~1 J/m² [S6]; room-temperature
  hydrophilic (unactivated) ~0.09 J/m² [S7]; Si–Si SAB approaching bulk
  fracture. The exact SAB-regime numbers still need pinning from one
  specific paper (the standing `VISION.md` TODO).

## Open forks for the PI

1. **Ar energy** — 500 eV (MD-tractable) or ~1 keV (match experiment,
   bigger box)?
2. **Ensemble size** — 3 amorphization seeds (cheap) or 5 (tighter error
   bar)?
3. **SiO₂ face + cristobalite-vs-quartz** — pick the face and polymorph
   (a §2.7 material-knob follow-on).

Everything else above is proposed to take as-is unless redlined.

## Tier D — reminder: these are NOT knobs

Do not pin numbers for these; they are derived or need reference data,
and `DESIGN.md` §1.3 already lists most as "not a setting": lattice
constants, the shared cell / tiling / strain, bond cutoffs, the
interface-subcell size, the activated depth, the potential. The gate
THRESHOLDS (g(r), ring stats, coordination, surface energies, the
Maszara ratio) need reference DATASETS, not chosen constants. Part of
finishing the pinning is pointing the TODO "numeric follow-ons" at §1.3
so they stop masquerading as pinnable.

## When we resume

1. PI ratifies the Tier-C table and resolves the three forks above.
2. Distill the ratified values INTO DESIGN §2.7 / §3.6 / §4.6 / §5.9
   ("…and v1" subsections), replacing "still DESIGN follow-ons" prose.
3. Author the §1.4 generator's fully-populated **study spec** (the
   physics: material + protocol + numerical + ensemble) and the
   deployment **rc template** (hardware + per-kind-of-job usage, `ARCH`
   §4.1).
4. Point the Tier-D "numeric follow-ons" in `TODO.md` at `DESIGN.md`
   §1.3, reclassifying them out of "pick a value."
5. Decide the serialization FORMAT (TOML/YAML/…), the last §1.8 follow-
   on, before the spec files are real.

## Sources

[S1]: https://en.wikipedia.org/wiki/Surface_activated_bonding
[S2]: https://www.mdpi.com/1996-1944/15/9/3115
[S3]: https://www.beilstein-journals.org/bjnano/articles/14/68
[S4]: https://pmc.ncbi.nlm.nih.gov/articles/PMC9105243/
[S5]: https://www.mdpi.com/2072-666X/11/5/454
[S6]: https://iopscience.iop.org/article/10.7567/JJAP.55.026503
[S7]: https://arxiv.org/pdf/0807.3215
