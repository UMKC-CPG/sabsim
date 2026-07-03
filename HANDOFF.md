# Session handoff (2026-06-30)

Quick "where we are" so we can resume cleanly. Fuller state lives in
Claude project memory; this is the human-visible mirror.

## Where we are

Top-down **design phase** of SABSIM (VISION → ARCHITECTURE → DESIGN →
PSEUDOCODE → Code). Vision/architecture are a consistent first-pass
baseline but deliberately **not yet finalized** — still shaping ideas
before DESIGN/PSEUDOCODE/code.

Done this session:
- `dev/VISION.md` + `dev/ARCHITECTURE.md` filled from the planning
  notes; `/refine` run twice → VISION→ARCHITECTURE consistent.
- Open questions parked in `dev/TODO.md`.
- Studied LANL **ALF** and found its MLIP backend is a config-string
  plugin (no fork needed).
- Built a **DeePMD backend prototype** at `prototypes/alf_deepmd/`
  (compiles clean; not runnable in the sandbox — needs the ALF +
  deepmd-kit env).

Not done / constraints:
- Project is **not a git repo yet** — do not commit until the user
  creates the GitHub repo.

## Resume here (next session)

1. **Analyze the paper** now in the project root:
   `Kulichenko et al. - 2023 - Uncertainty-driven dynamics...pdf`.
   Goal: settle the **UDD sampler-variant** question — uncertainty-
   *triggered capture* (`mlmd_sampling.py`) vs the full biasing-energy
   UDD (likely `samplers/ml_driven_md_sampling.py`). Pick the sampler
   the DeePMD backend should run under.
2. Optionally **unit-test the converter** against a real ALF
   `data-*.h5` to confirm the unit round-trip.
3. Then decide whether to fold "pluggable MLIP backend
   (HIPPYNN | DeePMD | SNAP)" into `dev/ARCHITECTURE.md` + `dev/TODO.md`.

## Pointers

- Prototype: `prototypes/alf_deepmd/README.md` (plug points, assumptions,
  test plan).
- ALF source: re-clone `https://github.com/lanl/ALF.git` (the scratchpad
  clone may be gone).
