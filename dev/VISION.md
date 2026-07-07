# Vision

> **Document hierarchy:** **VISION** → ARCHITECTURE → DESIGN →
> PSEUDOCODE → Code. This is the top of the chain; every lower level
> must serve the goals and obey the principles stated here.
>
> **Status:** First-pass mapping of the scattered planning notes
> (`onboarding-overview.md`, `imago-session-summary.md`, and the
> session transcript) into the document chain. The vision is not yet
> settled — open questions are tracked in `TODO.md`.

## Purpose

SABSIM (Surface Activated Bonding simulation) builds a **turn-key,
multi-code simulation pipeline** for modeling **surface activated
bonding** — a cold, room-temperature process that fuses two
*dissimilar* solid wafers (for example Si, SiO₂, GaN, LiNbO₃) without
heating them.

The physical process it models has three stages: blast each surface
with argon in vacuum to amorphize and "activate" it (leaving dangling
bonds), press the two activated surfaces together at modest pressure,
and let the dangling bonds link across the interface to fuse the
materials. Doing it cold avoids the thermal-expansion mismatch that
heating a dissimilar pair would cause.

The project answers a practical, funded question: **can we simulate
this process faithfully enough to advise real experimentalists** — to
say "use this much argon energy, this dopant, this pressure, to get a
strong bond"? The promised deliverable is not a single simulation but
a **tool another researcher can point at a different material pair**
and run the same study mostly automatically, including
programmatically.

## Goals

<!-- Concrete outcomes the finished project must accomplish. -->

1. **Faithful SAB simulation.** Model the full
   amorphize → press → separate sequence well enough that its outputs
   can guide a real bonding experiment.
2. **Turn-key, retargetable tool.** A new user supplies a different
   pair of materials and the pipeline runs the same study with minimal
   hand-editing, and can be driven programmatically (not only by hand).
3. **Traceable advice.** Because the deliverable is *funded
   recommendations*, every guidance number must be traceable back to
   the exact simulations, inputs, code versions, and settings that
   justify it.
4. **Bond characterization.** Use Imago's all-electron analysis to
   examine snapshots of the bonded interface (pipeline step 8) and
   report the detailed bonding measurements that become the guidance.
   The headline number is a **work of separation per unit area** — the
   energy needed to pull the bonded layers apart, in joules per square
   meter — chosen so it is commensurable with the experimental
   reference below; a raw pull-off force or stress would not be. The
   way we quantify the bond is kept deliberately open: several measures
   may be developed and compared, not one hardwired formula. Whatever
   measure is used is anchored to **well-characterized reference
   pairs** — silicon-to-silicon and silicon-to-silicon-dioxide — whose
   bonding energies are known from razor-blade crack-opening (Maszara)
   tests *in the surface-activated regime*, not thermal fusion bonding.
   Because a fast, nanoscale molecular-dynamics pull-apart cannot match
   an absolute experimental fracture energy, we calibrate on **trends
   and relative ratios** — is Si-Si stronger than Si-SiO2, in roughly
   the right proportion? — rather than on absolute agreement.
5. **Build only the novel part.** Deliver the genuinely new, fundable
   pieces — the SAB-specific surface models, the press-and-separate
   protocol, the quality gate, and the Imago bond characterization —
   and adopt mature tools for everything else.

## Design Principles

<!-- Non-negotiable constraints. Every architecture, design, and code
decision must be consistent with these. -->

1. **Separate "what" from "where" from the machinery.** Keep the
   changeable choices (which structures, how precise — the control
   parameters) separate from the deployment (which cluster, how many
   nodes, how long) and both separate from the fixed algorithm.
   Mixing run-specific choices into code is where bugs sneak in, and
   deployment must stay a freely-turnable knob so the *same*
   experiment can be run several ways and compared.
2. **Don't build what you can adopt.** Adopt commodity machinery
   (VASP and its error recovery for physics runs; an active-learning
   framework — LANL ALF — with a pluggable machine-learned-potential
   backend, DeePMD / SNAP / HIPPYNN, for potential training). Build
   only the unique edge — for the potential that edge is just a thin,
   config-selected backend adapter, not a fork. Re-implementing an
   existing tool "but worse" is the classic trap.
3. **Thin orchestration; Kaleidoscope owns step 8 and nothing more.**
   Kaleidoscope dispatches and tracks *one kind* of job (Imago runs)
   in a batch and resists becoming anything heavier. The moment we are
   tempted to bolt a results-database onto it, that is the signal to
   adopt an existing heavy tool instead.
4. **ASE is a membrane, not a straitjacket.** Use ASE as the glue and
   format translator that connects the pieces, but never let its
   standard vocabulary (energy, forces, motion) dictate what Imago is
   *for*. Imago's special outputs ride a separate native channel;
   depth lives in the niche, breadth comes through the ecosystem.
5. **Two nested loops — adopt the inner, build the outer.** Making a
   good potential is itself a make-data / train / find-gaps *cycle*;
   adopt that inner loop as a single black box (LANL ALF), selecting
   its potential backend by config (DeePMD / SNAP / HIPPYNN) rather
   than forking it. The *outer* loop — "does the model reproduce the
   real-world quantities *we* care about for bonding?" — is ours to
   build and is the scientific heart of the deliverable. In v1 that
   outer loop is only a **reporter**: it evaluates the model and
   reports pass or fail. Automatically *closing* it — feeding the gaps
   back to ALF as new training systems — is the eventual target, not
   the first milestone.
6. **Start lean; graduate only under real pressure.** Begin the outer
   orchestration with a simple, teachable spine and handle provenance
   by discipline (every step records its inputs, exact tool version,
   and settings). Adopt a heavier provenance system only when a
   genuine need forces it — querying across hundreds of runs, or
   genuinely complex loops.
7. **Right tool for each kind of work.** Group the work by *kind of
   job*, not by step number, and pick the natural tool for each. In
   particular, use VASP for the violent, distorted training
   configurations and reserve Imago for the calm, near-equilibrium
   bonded interfaces where its all-electron accuracy genuinely shines.
