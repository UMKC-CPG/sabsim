#!/usr/bin/env python
"""T-9b: bond-flow heal + per-wafer gate + press (committee of one).

Node-validation Job B of the re-architected split. It loads Job A's
WIDE-gap assembled pair and runs the re-architected bond flow IN-PROCESS
on the GPU under a SINGLE frozen bespoke DeePMD model — a "committee of
one", supplied through the ``SABSIM_DEEPMD_MODEL`` override, standing in
for the eventual N-member committee:

  press_and_bond
    -> HEAL the combined cell (the free surfaces, assembled beyond the
       potential cutoff, relax as free surfaces — DESIGN §2.6/§3.4)
    -> GATE each healed surface PER WAFER TAG (§3.5; wafer B is mirrored
       in z first, since assembly flipped it face-down)
    -> HALT on a failed gate (no scissor, no press), else scissor + press
       to the dual contact criterion

The KEY assertion is the new seam ran: ``press_and_bond`` returned a
per-wafer ``ActivationVerdict`` for BOTH tags (the gate executed on each
healed surface). Whether the press then reached contact or the gate halted
it are BOTH valid plumbing outcomes — the script reports which happened.

Env (set by the slurm wrapper): SABSIM_DEEPMD_MODEL (the graph.pb
committee-of-one), SABSIM_TEMPLATE (the study spec), VALWORK (the shared
dir Job A wrote), plus the ``cpg_lammps_conda/2024.08.29-deepmd`` module
(the in-process engine + DEEPMD_LMP_PLUGIN).
"""

import dataclasses
import os
import pickle

from sabsim.driver.commands import deepmd_model
from sabsim.driver.lammps_engine import LammpsEngine
from sabsim.driver.press_pull import RunControl, press_and_bond
from sabsim.spec.loader import load_and_validate_study
from sabsim.spec.records import Quantity


def _self_log_environment() -> None:
    """Emit the env FIRST (LEDGER rule 2) — including the in-process engine.

    Job B DOES drive in-process LAMMPS (the committee-of-one press), so the
    loaded ``liblammps`` and the deepmd model path are the facts that make
    the run reconstructable.
    """
    import lammps

    print("=== T-9b environment (self-logged) ===")
    print("python          :", os.popen("command -v python").read().strip())
    print("lammps.__file__ :", lammps.__file__)
    liblammps = os.path.join(os.path.dirname(lammps.__file__), "liblammps.so")
    if os.path.exists(liblammps):
        print("ldd liblammps (libmpi/libstdc++/libtorch lines):")
        for line in os.popen(f"ldd {liblammps}").read().splitlines():
            if any(k in line for k in ("libmpi", "libstdc++", "libtorch",
                                       "libdeepmd", "libtensorflow")):
                print("   ", line.strip())
    for name in ("SABSIM_DEEPMD_MODEL", "DEEPMD_LMP_PLUGIN",
                 "LAMMPS_PLUGIN_PATH", "SABSIM_TEMPLATE", "VALWORK",
                 "CUDA_VISIBLE_DEVICES"):
        print(f"  {name} = {os.environ.get(name, '(unset)')}")
    print("=======================================")


def _trim_press_hold(member):
    """Shorten the press HOLD so a validation press is cheap, not converged.

    The study protocol holds 150 ps at contact — far more than a plumbing
    check needs. Replace it with 5 ps so, if the gate passes and the press
    reaches contact, the hold is a short confirmation rather than a
    production run. Everything else about the member is untouched.
    """
    trimmed_protocol = dataclasses.replace(
        member.protocol, press_duration=Quantity(5.0, "ps"))
    return dataclasses.replace(member, protocol=trimmed_protocol)


def main() -> None:
    """Drive Job B: heal + per-wafer gate + press under the committee of one."""
    _self_log_environment()
    work_directory = os.environ["VALWORK"]
    template = os.environ["SABSIM_TEMPLATE"]
    model_path = os.environ["SABSIM_DEEPMD_MODEL"]

    with open(os.path.join(work_directory, "built_pair.pkl"), "rb") as handle:
        built_pair = pickle.load(handle)
    data_file = os.path.join(work_directory, "assembled_pair.data")
    print("loaded pair atoms:", len(built_pair.atoms),
          "| type_map:", built_pair.type_map)

    member = _trim_press_hold(load_and_validate_study(template).members[1])

    # The committee of one: a single frozen bespoke DeePMD model behind the
    # SAME ForceModel seam the eventual committee uses.
    force_model = deepmd_model(model_path)
    print("bond pair_style:", force_model.pair_style)

    # Cap the press: a few short chunks are enough to prove the heal, the
    # gate, and that the press advances — this is not an M1/M3 measurement.
    control = RunControl(
        chunk_steps=200, max_chunks=20, relax_chunks=3,
        equilibrate_chunks=5)

    log_file = os.path.join(work_directory, "log.bond_press")
    with LammpsEngine(
            command_line_args=["-screen", "none", "-log", log_file]) as engine:
        press = press_and_bond(
            engine, built_pair, member, force_model, data_file, seed=2024,
            control=control)

    print("=== press result ===")
    print("contact_reached :", press.contact_reached)
    print("chunks_to_contact:", press.chunks_to_contact)
    print("note            :", press.note)
    for tag, verdict in (("a", press.activation_a), ("b", press.activation_b)):
        if verdict is None:
            print(f"activation_{tag}   : None")
        else:
            print(f"activation_{tag}   : passed={verdict.passed}  "
                  f"reason={verdict.reason}")

    # The re-architecture's headline seam: the gate ran on BOTH healed
    # surfaces, per wafer tag, inside the bond flow. Missing verdicts would
    # mean the wide-gap heal+gate path never engaged.
    assert press.activation_a is not None and press.activation_b is not None, (
        "the per-wafer activation gate did NOT run — the wide-gap "
        "heal+gate path did not engage (check the assembled gap > 6 A)")
    print("GATE RAN PER WAFER TAG (a and b) — new bond-flow seam engaged")
    print("T9B BOND HEAL+GATE+PRESS OK")


if __name__ == "__main__":
    main()
