# Design

> **Document hierarchy:** VISION → ARCHITECTURE → **DESIGN** → PSEUDOCODE
> → Code. For goals and principles, see `VISION.md`. For repository layout
> and module map, see `ARCHITECTURE.md`.

> **Prior art — read before writing the relevant sections.** Several
> algorithms this document needs already exist, and some now run, in
> Sunita's `bond_debond` pipeline: the reusable kernels are catalogued in
> `PRIOR_ART.md` §1.2, and the newer worked examples plus current status
> are in §1.5. Lift or adapt rather than re-derive:
> - **Surface amorphization (§3):** a classical + ZBL Ar-bombardment
>   LAMMPS recipe and the thermostat-damping / inter-impact-timing
>   settings that make it disorder the surface — plus the §1.5 lesson
>   that dropping the frozen substrate and `p p f` sputter boundary
>   breaks it.
> - **Amorphization verification (§3, §7):** g(r), partial-g(r),
>   coordination-defect counting, and amorphous-depth estimation — the
>   validation the potential-quality gate needs (add the thresholds and
>   DFT anchor prior art lacks).
> - **Structure building (§2):** a mirror symmetrizer for polar surfaces
>   (LiNbO₃, GaN) in §1.2, and a worked coincidence supercell
>   (16×SiO₂ ≈ 15×LiNbO₃, strained before amorphization) in §1.5.
> - **Bond/debond and measures (§5, §6):** a built-and-run press/pull
>   protocol and an independent J/m² adhesion definition (mechanical and
>   thermodynamic) in §1.5 — but its interface number is uncalibrated
>   (placeholder pair potential), the gap SABSIM's trained MLIP fills.
> - **Step-8 analysis (§8):** a worked OLCAO full-basis / Γ-point / cost
>   plan (§1.2 item 5); OLCAO itself is still unbuilt in prior art.

---

<!-- Each section designs one subsystem: its data structures,
algorithms, mathematical foundations, and key decisions. Reference
VISION.md principles when a choice is motivated by one. Sections are
numbered in reading order but FILLED in a different order — §4 (MLIP
backend + bootstrap) first, as the most mature (already prototyped and
unit-tested). Each heading below carries a one-line scope note and its
sources; bodies are written section by section. -->

## 1. Run specification and settings layer

<!-- Scope: the editable config a user changes to point the pipeline at
a study — material knobs (crystal, one Miller face, identity) and
protocol knobs (activation species / energy / dose; press and separate
load, depth, duration, speed) — kept apart from the deployment/resource
layer and the fixed machinery, and exposed programmatically. v1 fixes
Si/SiO2 (plus a Si/Si reference) with every protocol knob frozen.
Sources: ARCHITECTURE §2.3 (run specification; settings/deployment
separation; programmatic entry) and §4.1; TODO DESIGN (settings-file
shape). -->

## 2. Structure builder

<!-- Scope: SAB-specific slab construction (step 3) and facing-pair
assembly (step 5) on ASE — the pair-generic coincidence-supercell
lattice matcher, residual-strain application before amorphization, and a
polar-slab symmetrizer hook for future ionic/polar pairs.
Sources: ARCHITECTURE §2.3 (structure builder; STRUCTURAL 4); TODO
DESIGN (STRUCTURAL 4 follow-ons); PRIOR_ART §1.2 (polar symmetrizer) and
§1.5 (worked 16:15 coincidence cell). -->

## 3. Surface activation (amorphization)

<!-- Scope: the step-4 protocol — a classical + ZBL Ar-bombardment
cascade (frozen substrate, `p p f` sputter boundary, thermostat damping
and inter-impact timing), a gentle MLIP re-anneal, and
amorphous-structure validation (g(r) / partial-g(r) / coordination vs
DFT and experiment, with thresholds). The MLIP never runs the cascade.
Sources: ARCHITECTURE §2.3 (surface-dynamics engine; potential-quality
gate) and §4.1; TODO DESIGN (STRUCTURAL 1b follow-ons); PRIOR_ART §1.2
(recipe + verification kernels) and §1.5 (the frozen-layer / `p p f`
lesson). -->

## 4. MLIP backend and bootstrap  (write first)

<!-- Scope: the config-selected DeePMD backend plugin — the ANI-HDF5 to
DeePMD unit-factor conversion (prototyped, unit-tested) and the
potential-agnostic UDD committee-bias math — and the bootstrap loop that
breaks the training circularity: seed potential -> cheap-generator
configs -> VASP label -> ALF refine on committee/UDD uncertainty ->
converge on the potential-quality gate plus an uncertainty threshold.
One multi-species potential over the pair's species.
Sources: ARCHITECTURE §2.3 (MLIP training; STRUCTURAL 1a/1b) and §4.1;
TODO DESIGN (ANI-HDF5 to DeePMD + UDD math). Prototype at
`prototypes/alf_deepmd/`. -->

## 5. Bond/debond MD protocol

<!-- Scope: the step-6/7 press-then-separate protocol on LAMMPS + the
MLIP — gap closure, pressure bonding, controlled separation — and the
force-vs-displacement reduction feeding §6. Runs on GPU (`pair_style
deepmd`).
Sources: ARCHITECTURE §2.3 (surface-dynamics engine; STRUCTURAL 2) and
§4.1; PRIOR_ART §1.5 (a built-and-run press/pull protocol template). -->

## 6. Bond-outcome analyzer and measures

<!-- Scope: the pluggable measure vector — mechanical MD work-integral
(headline, Imago-free), thermodynamic work-of-adhesion at MLIP and
all-electron fidelity (including the quasi-static separation-energy
protocol), and Imago bond descriptors — plus the measure-vector schema
the gate consumes.
Sources: ARCHITECTURE §2.3 (bond-outcome analyzer; STRUCTURAL 2); TODO
DESIGN (STRUCTURAL 2 follow-ons); PRIOR_ART §1.5 (dual measure
definition; uncalibrated-interface caution). -->

## 7. Quality gates and diagnosis

<!-- Scope: the two checks and their routing — the potential-quality
gate (bulk stiffness / surface energies plus the interface-fidelity
check: committee uncertainty along the pull and an MLIP-vs-all-electron
ΔE cross-check) and the bond-outcome gate — with the three-way diagnosis
(bulk-model / interface-coverage / protocol) and its reported
diagnostic-label schema. v1 reports; it does not close the loop.
Sources: ARCHITECTURE §2.3 (two separate checks + diagnosis) and §3;
TODO DESIGN (STRUCTURAL 3 follow-ons). -->

## 8. Step-8 characterization (Imago + Kaleidoscope)

<!-- Scope: OLCAO skeleton preparation (structure -> OLCAO input,
full-basis, Γ-point, run settings) built independent of Imago execution,
the Kaleidoscope batch dispatch, and snapshot selection (which and how
many step-6/7 frames).
Sources: ARCHITECTURE §2.3 (bond characterization) and §4.1; TODO
(snapshot selection; OLCAO skeleton template); PRIOR_ART §1.2 item 5
(OLCAO plan). -->
