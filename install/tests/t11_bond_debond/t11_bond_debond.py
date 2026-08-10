#!/usr/bin/env python
"""T-11: bond-debond on the T-10 universal-activated surface (§9.1).

The payoff run of the universal-cascade thread: take the gate-PASSING
surface T-10 produced under the universal DPA-2.4-7M cascade, assemble a
facing pair from it, and run the FULL bond-debond sequence in-process under
a single frozen bespoke DeePMD model (a "committee of one") — heal, gate
each healed surface per wafer tag, press to contact, settle a zero-load
reference, then PULL the interface apart and report the work of separation.

This is the first end-to-end chain from a genuinely UNIVERSAL-activated
surface through the bespoke bond flow. Where T-9 proved the split plumbing
on an under-activated toy (its gate rightly failed), this feeds the bond a
surface that already cleared the §3.5 gate (T-10), so the heal starts from
a well-formed amorphous skin rather than a thin toy.

Design choices (both recorded in the ledger's "Scope NOT covered"):
- **One realization, both wafers.** Si/Si is symmetric, so the single
  T-10 surface serves as BOTH wafers (wafer B is its mirror at assembly),
  saving a second ~11 h activation. The amorphization-seed spread across
  distinct realizations is a later ensemble concern (§10.8).
- **Committee of one.** A single frozen `graph.pb` behind the same
  ForceModel seam the eventual N-member committee uses
  (`SABSIM_DEEPMD_MODEL`). The bond HEALS under it first, bridging the
  DPA-activated surface into this model's distribution (§3.4).
- **Trimmed protocol.** Press hold 10 ps and ONE pull rung (the fastest),
  so this is a first work-of-separation number and a plumbing proof, not a
  converged M1/M3 rate study.

Env (slurm wrapper): SABSIM_DEEPMD_MODEL (the graph.pb committee-of-one),
SABSIM_TEMPLATE (study spec), T10_VALWORK (T-10's dir, holds
activated.extxyz), VALWORK (this run's scratch), + the
`cpg_lammps_conda/2024.08.29-deepmd` module (the in-process engine).
"""

import dataclasses
import os

import numpy as np
from ase.io import read as ase_read

from sabsim.pipeline.exec_artifacts import Structure
from sabsim.pipeline.live_stages import run_bond_debond_md_live
from sabsim.pipeline.run_options import (
    TrajectoryOptions,
    set_trajectory_options,
)
from sabsim.spec.loader import load_and_validate_study
from sabsim.spec.records import Quantity
from sabsim.structure.amorphized_assembly import assemble_amorphized_pair
from sabsim.structure.slab_builder import (
    WAFER_A_TAG,
    WAFER_B_TAG,
    SurfaceMatch,
    write_lammps_data,
)

BOND_CUTOFF_ANGSTROM = 2.8


def _self_log_environment() -> None:
    """Emit the env FIRST (LEDGER rule 2), including the in-process engine."""
    import lammps

    print("=== T-11 environment (self-logged) ===")
    print("python          :", os.popen("command -v python").read().strip())
    print("lammps.__file__ :", lammps.__file__)
    liblammps = os.path.join(os.path.dirname(lammps.__file__), "liblammps.so")
    if os.path.exists(liblammps):
        print("ldd liblammps (engine libs):")
        for line in os.popen(f"ldd {liblammps}").read().splitlines():
            if any(k in line for k in ("libmpi", "libstdc++", "libtorch",
                                       "libdeepmd", "libtensorflow")):
                print("   ", line.strip())
    for name in ("SABSIM_DEEPMD_MODEL", "DEEPMD_LMP_PLUGIN",
                 "LAMMPS_PLUGIN_PATH", "SABSIM_TEMPLATE", "T10_VALWORK",
                 "VALWORK", "CUDA_VISIBLE_DEVICES"):
        print(f"  {name} = {os.environ.get(name, '(unset)')}")
    print("=======================================")


def _trim_for_a_first_number(member):
    """Shorten the press hold and the pull ladder for a first bond number.

    The study presses 150 ps and pulls three rungs (1, 3.2, 10 m/s); that
    is a converged rate study, far more than a first plumbing-and-number
    run needs. Keep the SINGLE fastest rung and a 10 ps hold — enough to
    reach contact, settle, and separate once — leaving everything else
    (energies, cutoffs, geometry) untouched.
    """
    ladder = member.numerical.pull_rate_ladder
    fastest = max(ladder, key=lambda rate: rate.value)
    trimmed_numerical = dataclasses.replace(
        member.numerical, pull_rate_ladder=(fastest,))
    trimmed_protocol = dataclasses.replace(
        member.protocol, press_duration=Quantity(10.0, "ps"))
    return dataclasses.replace(
        member, numerical=trimmed_numerical, protocol=trimmed_protocol)


def _work_of_separation(pull, area_angstrom2: float) -> float | None:
    """Trapezoidal work under the force-vs-grip curve, per unit area.

    A coarse first estimate (eV/Å^2) — the integral of the recorded normal
    force over the grip displacement, divided by the interface area. Not
    the §5 measure machinery; just enough to report a number the pull
    actually produced.
    """
    displacement = np.asarray(pull.grip_displacement, dtype=float)
    force = np.asarray(pull.force_vs_grip, dtype=float)
    if displacement.size < 2 or force.size != displacement.size:
        return None
    # Trapezoidal rule by hand (np.trapz was removed in NumPy 2): the sum
    # of each interval's average force times its width.
    work = float(np.sum(
        0.5 * (force[1:] + force[:-1]) * np.diff(displacement)))
    return work / area_angstrom2 if area_angstrom2 > 0 else None


def main() -> None:
    """Drive T-11: assemble the T-10 surface into a pair, bond and debond."""
    _self_log_environment()
    template = os.environ["SABSIM_TEMPLATE"]
    t10_work = os.environ["T10_VALWORK"]
    work_directory = os.environ["VALWORK"]
    os.makedirs(work_directory, exist_ok=True)

    # Record a press/pull MOVIE (the run's visualization), the same switch
    # the pipeline exposes — set here since we call the stage directly.
    set_trajectory_options(TrajectoryOptions(enabled=True, stride=500))

    # DEMO MODE (SABSIM_BOND_DEMO=1) — for a WORKFLOW VISUAL ONLY, never a
    # measurement. It lets the bond flow run end to end on a surface that is
    # not gate-passing (e.g. the over-amorphized Si) by (a) bypassing the
    # §3.5 gate halt and (b) tolerating LAMMPS "lost atoms" (thermo_modify
    # lost warn) instead of aborting, so the press/pull records a movie even
    # as the over-driven surface sheds atoms. The result numbers are NOT
    # meaningful; the point is to see the pipeline execute.
    if os.environ.get("SABSIM_BOND_DEMO") == "1":
        import sabsim.driver.press_pull as press_pull
        from sabsim.driver.activation_gate import ActivationVerdict
        original_preamble = press_pull.preamble_commands
        press_pull.preamble_commands = (
            lambda *args, **kw: list(original_preamble(*args, **kw))
            + ["thermo_modify lost warn"])

        def _demo_gate(engine, built):
            passed = ActivationVerdict(
                passed=True, activated_depth=0.0, per_metric={},
                reason="DEMO: gate bypassed for a workflow visual")
            return passed, passed

        press_pull.gate_healed_surfaces = _demo_gate
        print("*** DEMO MODE: gate bypassed + lost atoms tolerated — "
              "VISUAL ONLY, numbers not meaningful ***")

    member = _trim_for_a_first_number(
        load_and_validate_study(template).members[1])   # si-si-reference
    print("member:", member.name, "| pull ladder:",
          member.numerical.pull_rate_ladder,
          "| press:", member.protocol.press_duration)

    # The T-10 universal-activated surface serves as BOTH wafers. Load it
    # twice so the two halves are independent objects; assembly flips B.
    activated_path = os.path.join(t10_work, "activated.extxyz")
    half_a = ase_read(activated_path, format="extxyz")
    half_b = ase_read(activated_path, format="extxyz")
    half_a.set_tags([WAFER_A_TAG] * len(half_a))
    half_b.set_tags([WAFER_B_TAG] * len(half_b))
    cell = half_a.get_cell()
    area = float(cell[0][0] * cell[1][1])
    print(f"loaded T-10 surface: {len(half_a)} atoms | area {area:.0f} A^2")

    match = SurfaceMatch(
        residual_strain=0.0, match_area=area, is_identity=True)
    built_pair = assemble_amorphized_pair(
        half_a, half_b, match, bond_cutoff=BOND_CUTOFF_ANGSTROM,
        initial_gap=10.0, clash_floor=1.8)
    gap = built_pair.wafer_b_z_range[0] - built_pair.wafer_a_z_range[1]
    print(f"assembled pair: {len(built_pair.atoms)} atoms | gap {gap:.2f} A")

    data_file = os.path.join(work_directory, "assembled_pair.data")
    write_lammps_data(built_pair, data_file)
    structure = Structure(
        note="t11 bond-debond on the T-10 universal-activated surface",
        labeled_groups=("interface_z",), data_file=data_file,
        built=built_pair)

    print("=== bond-debond: heal -> gate -> press -> settle -> pull ===")
    result = run_bond_debond_md_live(
        structure, potential=None, member=member,
        scratch_directory=work_directory)

    print("=== bond-debond result ===")
    print("press bonded   :", result.press.bonded, "|", result.press.note)
    print("reference_ok   :", result.reference_ok)
    for tag, verdict in (("a", result.activation_a),
                         ("b", result.activation_b)):
        if verdict is not None:
            print(f"activation_{tag}   : passed={verdict.passed} "
                  f"reason={verdict.reason}")
    for pull in result.pulls:
        work = _work_of_separation(pull, area)
        print(f"pull @ {pull.rate_value} {pull.rate_unit}: "
              f"complete={pull.complete} "
              f"separation_index={pull.separation_index} "
              f"atoms_conserved={pull.atoms_conserved}")
        print(f"  note: {pull.note}")
        if work is not None:
            print(f"  work of separation (coarse): {work:.4f} eV/A^2")

    print("T11 BOND-DEBOND RUN COMPLETE")


if __name__ == "__main__":
    main()
