# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

## Document Hierarchy

This project uses a five-level document chain. All design documents live
in `dev/`. Read them in order when starting work:

1. `dev/VISION.md` — goals, principles, non-negotiables
2. `dev/ARCHITECTURE.md` — layout, modules, dependencies
3. `dev/DESIGN.md` — algorithms, data structures, math
4. `dev/PSEUDOCODE.md` — language-agnostic algorithm specs
5. Source code in `src/`

`dev/TODO.md` tracks tasks organized by level. Use `/focus` to start a
session and `/refine` to check consistency across the chain.

## Level Awareness

During development conversations, the programmer may shift between levels
of the design chain without explicitly noticing. For example, a discussion
about a code fix may drift into questioning an algorithm's design, or a
design discussion may surface a conflict with a core principle.

When you notice the conversation has moved to a different level than where
it started, say so briefly. For example: "This sounds like it's becoming
an ARCHITECTURE question — should we capture it there before continuing
with the code?" The goal is awareness, not interruption. Let the programmer
decide whether to switch context, propagate the change to the appropriate
document, or stay focused and defer.

Do not enforce rigid boundaries. The levels exist to organize thinking,
not to prevent it. A developer who is on a productive train of thought
should not be stopped — but when the thought resolves, help them recognize
which documents it touches so nothing is left inconsistent.

## Coding Style

### Line Length

Lines MUST NOT exceed 80 characters. This is a hard limit.

### Documentation and Naming

CRITICAL: All program code must include rich, expressive documentation
so that students reading the source can easily follow what is happening.
Every function, class, and non-trivial block should carry clear
explanatory comments or docstrings that describe purpose, inputs,
outputs, and any relevant physics or math.

Variable names must be readable and self-documenting. Avoid cryptic
one- or two-letter abbreviations. Prefer concise but meaningful names
that a reader can understand without cross-referencing a legend.
Slightly-too-long names are far better than opaque short ones.

Good naming examples for an electronic structure program:
- `elec_mom` instead of `em` or `electron_momentum`
- `nuc_pot` instead of `np` or `nuclear_potential`
- `grid_spacing` instead of `gs` or `the_spacing_between_grid_points`

Apply similar logic to the current project if it is something else.

The goal is a middle ground: short enough to keep expressions tidy,
long enough that any student can read the code cold and follow the
logic without guessing what a variable holds.

## Project Overview

<!-- Replace this section with your project description, how to run it,
dependencies, and architecture summary. -->

## Running

```bash
# Replace with your project's run command.
```

## Dependencies

<!-- List your project's dependencies here. -->

## Testing

```bash
# Run the test suite.
pytest tests/ -v
```
