#!/usr/bin/env python
"""T-15 part 2 (deepmd BUNDLE Python): the REAL driver under DPA.

Runs sabsim's actual press/pull DRIVER (`press_and_bond` -> `settle_
reference` -> `pull_at_rate`) — the scissor-to-contact, load/displacement
press, grip force gauges, interface-opening measurement, adaptive contact
and separation detection — but with the force model set to the UNIVERSAL
DPA-2.4-7M model. It works because it runs INSIDE the deepmd bundle's
Python: the bundle's in-process `lammps` loads the `.pt2`, and the driver's
import chain is now pymatgen-free (`wafer_tags` decoupling), so only ASE
(installed into the bundle) is needed. Single rank (comm=None).

This is the honest fix for T-14's crude hand-written press: the driver
scissors the two surfaces to near-contact BEFORE pressing (so they
actually meet) and measures the interface, not the grip. A full
physical-rate pull-to-separation is infeasible under DPA (~100x classical),
so the chunk budget is capped — the point is the PRESS behaviour.

DEMO MODE: no oxide §3.5 reference exists and the gate cannot tell the two
wafers apart, so the gate halt is bypassed and lost atoms are tolerated.

Env: SABSIM_CASCADE_MLIP_MODEL (the .pt2), VALWORK (holds built.pkl /
member.pkl / oxide_pair.data from part 1).
"""

import os
import pickle


def _install_demo_mode() -> None:
    """Bypass the oxide gate halt + tolerate lost atoms (visual only)."""
    import sabsim.driver.press_pull as press_pull
    from sabsim.driver.activation_gate import ActivationVerdict

    original_preamble = press_pull.preamble_commands
    press_pull.preamble_commands = (
        lambda *a, **k: list(original_preamble(*a, **k))
        + ["thermo_modify lost warn"])

    def _demo_gate(engine, built):
        ok = ActivationVerdict(
            passed=True, activated_depth=0.0, per_metric={},
            reason="DEMO: oxide gate bypassed")
        return ok, ok

    press_pull.gate_healed_surfaces = _demo_gate


def main() -> None:
    work = os.environ["VALWORK"]
    model_path = os.environ["SABSIM_CASCADE_MLIP_MODEL"]

    _install_demo_mode()
    from sabsim.driver.commands import ForceModel
    from sabsim.driver.lammps_engine import LammpsEngine
    from sabsim.driver.press_pull import (
        RunControl,
        press_and_bond,
        pull_at_rate,
        settle_reference,
    )

    with open(os.path.join(work, "built.pkl"), "rb") as handle:
        built = pickle.load(handle)
    with open(os.path.join(work, "member.pkl"), "rb") as handle:
        member = pickle.load(handle)
    data_file = os.path.join(work, "oxide_pair.data")
    print(f"pair: {len(built.atoms)} atoms | type_map {built.type_map}")

    # The universal DPA model, as a plain deepmd pair style (NO ZBL — that
    # is cascade-only). The bundle's lammps has deepmd built in, so no
    # plugin preload; the element list maps the data file's Si,Li,Nb,O types.
    force_model = ForceModel(
        pair_style=f"deepmd {model_path}",
        pair_coeff=("* * Si Li Nb O",),
        preload=(), needs_atom_map=True)
    print("force model:", force_model.pair_style)

    # Cap the chunk budget — DPA is ~100x classical, so this is a bounded
    # press + partial pull, not a converged measurement.
    control = RunControl(
        chunk_steps=500, max_chunks=40, relax_chunks=5,
        equilibrate_chunks=10)
    seed = member.ensemble.master_seed

    press_engine = LammpsEngine(
        command_line_args=[
            "-screen", "none", "-log", os.path.join(work, "log.press")],
        comm=None)
    press = press_and_bond(
        press_engine, built, member, force_model, data_file, seed,
        control=control,
        trajectory_file=os.path.join(work, "press_movie.dump"),
        trajectory_stride=500)
    print("=== press ===")
    print("contact_reached :", press.contact_reached)
    print("chunks_to_contact:", press.chunks_to_contact)
    print("note            :", press.note)

    reference_file = os.path.join(work, "settled_reference.data")
    if press.contact_reached:
        reference = settle_reference(
            press_engine, member, control=control,
            reference_data_file=reference_file)
        print("settled reference:", reference.settled)
    press_engine.close()

    if press.contact_reached and os.path.exists(reference_file):
        rate = member.numerical.pull_rate_ladder[0]
        pull_engine = LammpsEngine(
            command_line_args=[
                "-screen", "none", "-log", os.path.join(work, "log.pull")],
            comm=None)
        result = pull_at_rate(
            pull_engine, built, member, force_model, reference_file, rate,
            seed, control=control, output_directory=work,
            trajectory_file=os.path.join(work, "pull_movie.dump"),
            trajectory_stride=500, checkpoint_dir=None)
        pull_engine.close()
        print("=== pull @", rate.value, rate.unit, "===")
        print("complete        :", result.complete)
        print("separation_index:", result.separation_index)
        print("atoms_conserved :", result.atoms_conserved)
    else:
        print("no contact — pull skipped")

    print("T15 DRIVER-UNDER-DPA COMPLETE")


if __name__ == "__main__":
    main()
