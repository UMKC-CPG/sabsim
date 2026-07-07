# Design

> **Document hierarchy:** VISION → ARCHITECTURE → **DESIGN** → PSEUDOCODE
> → Code. For goals and principles, see `VISION.md`. For repository layout
> and module map, see `ARCHITECTURE.md`.

> **Prior art — read before writing the relevant sections.** Several
> algorithms this document will need already exist, working and in some
> cases validated, in `PRIOR_ART.md` §1.2 (Sunita's `bond_debond`
> pipeline). Lift or adapt rather than re-derive:
> - **Surface amorphization (step 4):** a validated Ar-bombardment
>   LAMMPS recipe, plus the thermostat/relaxation-time settings that
>   were required to make it work.
> - **Amorphization verification:** g(r), coordination-number defect
>   counting, and amorphous-depth estimation — the potential-quality
>   gate's "did the surface activate?" checks.
> - **Polar-slab construction (step 3):** a mirror symmetrizer for
>   dipole-bearing surfaces (LiNbO₃, GaN).
> - **Bond metric and step-8 analysis:** an independent J/m² work-of-
>   separation definition and a worked OLCAO basis / k-point / cost plan.

---

<!-- Organize this document by topic. Each section should describe the
design of a specific subsystem: its data structures, algorithms,
mathematical foundations, and key decisions. Reference VISION.md principles
when a design choice is motivated by one. -->

## 1. Topic One

### 1.1 Subtopic

<!-- Description of the design, including any mathematical formulas, data
flow, or invariants. -->

---

## 2. Topic Two

<!-- Continue with additional sections as the design grows and evolves. -->
