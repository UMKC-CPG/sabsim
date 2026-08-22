#!/usr/bin/env python
"""T-19 part 2 (deepmd BUNDLE python): the REAL per-wafer gate + press.

Runs sabsim's actual press/bond driver under the universal DPA .pt2, with
NO demo gate-bypass -- so the §3.5 activation gate runs for real, keying
EACH wafer by its own material species (item 6): wafer A (SiO2) against
share/activation/O_Si.toml, wafer B (LiNbO3) against Li_Nb_O.toml. A FAILED
gate halts the bond BEFORE the press (§9.1), which is the correct behaviour
and itself validates the per-wafer plumbing; a PASS proceeds into the
combined-cell relax + press. The lost-atom tolerance is now in mainline
(thermo_modify lost warn), so no monkeypatch is needed.

Env: SABSIM_CASCADE_MLIP_MODEL (the .pt2), VALWORK (built.pkl / member.pkl
/ oxide_pair.data from part 1).
"""

import os
import pickle


def main() -> None:
    work = os.environ["VALWORK"]
    model_path = os.environ["SABSIM_CASCADE_MLIP_MODEL"]

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
    print(f"wafer A species {sorted(built.wafer_a_species)} | "
          f"wafer B species {sorted(built.wafer_b_species)}")

    force_model = ForceModel(
        pair_style=f"deepmd {model_path}",
        pair_coeff=("* * Si Li Nb O",),
        preload=(), needs_atom_map=True)

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
    print("gate wafer A :", press.activation_a)
    print("gate wafer B :", press.activation_b)
    print("contact_reached :", press.contact_reached)
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
        print("no contact (or gate halt) — pull skipped")

    print("T19 REAL-GATE DRIVER COMPLETE")


if __name__ == "__main__":
    main()
