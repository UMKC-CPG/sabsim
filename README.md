# SABSIM

**Surface Activated Bonding simulation** — a turn-key, multi-code
pipeline for modeling **surface activated bonding**, a cold,
room-temperature process that fuses two *dissimilar* solid wafers
(for example Si, SiO₂, GaN, LiNbO₃) without heating them.

The physical process has three stages: blast each surface with argon
in vacuum to amorphize and "activate" it (leaving dangling bonds),
press the two activated surfaces together at modest pressure, and let
the dangling bonds link across the interface to fuse the materials.
Doing it cold avoids the thermal-expansion mismatch that heating a
dissimilar pair would cause.

The project answers a practical, funded question: **can we simulate
this process faithfully enough to advise real experimentalists** — to
say "use this much argon energy, this dopant, this pressure, to get a
strong bond"? The deliverable is not a single simulation but a **tool
another researcher can point at a different material pair** and drive,
including programmatically, to run the same study.

## Status

SABSIM is in its **top-down design phase**. The substance currently
lives in the `dev/` document chain, not in runnable code: `VISION.md`
and `ARCHITECTURE.md` are a consistent first-pass baseline, while
`DESIGN.md` and `PSEUDOCODE.md` are still scaffolds awaiting work.
The one build artifact so far is a backend prototype under
`prototypes/` (see below).

## The pipeline (eight steps)

```
1. Generate training data — many physics calcs on Si, SiO2, GaN, LiNbO3
2. Train a machine-learned interatomic potential (MLIP)
3. Build wafer slab models
4. Amorphize ("activate") the model surfaces
5. Build the facing-pair (two amorphized surfaces toward each other)
6. Press the slabs together and let them settle   (uses the MLIP)
7. Pull them back apart                            (uses the MLIP)
8. Characterize the interface bonding from snapshots of steps 6-7
```

The guiding strategy is **adopt mature tools, build only the novel
edge**: VASP for the training-data physics (step 1), LANL **ALF** with
a config-selected DeePMD backend for potential training (step 2), ASE
for structure building and format translation (steps 3, 5), LAMMPS for
the surface dynamics (steps 4, 6, 7), and our own Imago + Kaleidoscope
for the all-electron bond characterization (step 8). What we build is
the SAB-specific surface recipes, the press-and-separate protocol, the
outer quality-gate loop, and the step-8 analysis. See
`dev/ARCHITECTURE.md` for the full module map and rationale.

## Repository layout

```
sabsim/
  dev/                Design document chain (read in order; see below)
    VISION.md         Goals, principles, non-negotiables
    ARCHITECTURE.md   Repository layout, modules, dependencies
    DESIGN.md         Algorithms, data structures, math (scaffold)
    PSEUDOCODE.md     Language-agnostic algorithm specs (scaffold)
    TODO.md           Open tasks, organized by design level
  prototypes/
    alf_deepmd/       ALF DeePMD-backend prototype (data converter +
                      train/load adapters + config snippets)
  src/                Source code and test scaffold (early)
  CLAUDE.md           Guidance for the Claude Code assistant
  HANDOFF.md          Human-readable "where we are" session mirror
```

## Document hierarchy

The project is developed top-down through a five-level chain; each
level serves the one above it:

```
VISION        Why does this project exist?
  -> ARCHITECTURE   How is it organized?
     -> DESIGN          How do the algorithms work?
        -> PSEUDOCODE       What are the steps, precisely?
           -> Code              The implementation.
```

When a change is made at any level, check upward (does it invalidate a
parent claim?) and downward (does it require child updates?), and keep
all affected levels consistent. Start reading at `dev/VISION.md`.

## Prototype: ALF DeePMD backend

`prototypes/alf_deepmd/` explores plugging a **DeePMD** potential into
ALF's active-learning loop as a config-selected backend, with no fork
of ALF. It includes an ANI-HDF5 → DeePMD data converter (round-trip
unit-tested), train/load adapter stubs, and example ALF config
snippets. See `prototypes/alf_deepmd/README.md` for the plug points,
assumptions, and test plan.

## Dependencies

External tools the pipeline drives (none vendored here):

- **VASP** — training-data physics (step 1).
- **LANL ALF** + **DeePMD-kit** — MLIP training (step 2), driven
  through **Parsl**.
- **ASE** — structure building and format translation (steps 3, 5,
  and snapshot transport into step 8).
- **LAMMPS** — surface dynamics (steps 4, 6, 7).
- **Imago** + **Kaleidoscope** — all-electron bond characterization
  (step 8); sibling projects, not modules of this repository.

The outer orchestrator is still an open choice (`dev/ARCHITECTURE.md`
§4). See `dev/` for how the local ALF + DeePMD environment is built.

## Testing

```bash
# Prototype converter round-trip test.
pytest prototypes/alf_deepmd/tests/ -v
```

The `src/` test scaffold under `src/tests/` will grow as the outer
controller and quality gate are implemented.

## Development workflow

This repository uses Claude Code skills to keep the document chain
coherent: `/focus` to start a session from `dev/TODO.md`, `/refine`
to check consistency across the chain, and `/commit` / `/bigcommit`
for commits. The definitions live in `.claude/commands/`.
