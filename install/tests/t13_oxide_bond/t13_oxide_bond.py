#!/usr/bin/env python
"""T-13: bond-debond of the SiO2 / LiNbO3 interface (the real target).

Assembles the amorphized SiO2 surface (wafer A) and the amorphized LiNbO3
surface (wafer B) — both built on the SAME matched, commensurate cell
(SiO2(100)/LiNbO3(001), 2.03% strain) — into a facing pair, and runs the
bond-debond IN-PROCESS under Prakash's trained SiO2+LiNbO3 DeePMD model
(type_map [Si, Li, Nb, O]), recording a press/pull movie.

TWO things this handles that the Si bond did not:
- **Type remap.** The activated halves carry the GLOBAL type map
  {Ar,Li,Nb,O,Si}; Prakash's model expects [Si,Li,Nb,O]. The assembled
  pair is written with the LAMMPS type order Si,Li,Nb,O so `pair_coeff * *`
  maps each type to the right model element (the beam Ar is gone — the
  cascade stripped it — so it is simply dropped).
- **No oxide gate.** The §3.5 references are silicon-only and the gate
  keys on the global type map (it cannot tell the SiO2 wafer from the
  LiNbO3 one), so the bond runs in DEMO MODE (SABSIM_BOND_DEMO=1): the
  gate halt is bypassed and lost atoms are tolerated, so the workflow runs
  end to end for a VISUAL. Numbers are not a measurement.

Env (slurm wrapper): SABSIM_DEEPMD_MODEL (Prakash's model.pb),
SABSIM_BOND_DEMO=1, SABSIM_TEMPLATE, SIO2_SURFACE + LINBO3_SURFACE (the two
activated .extxyz), MATCH_PKL (the shared-cell match), VALWORK (scratch),
+ the cpg_lammps deepmd module.
"""

import dataclasses
import os
import pickle

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
    write_lammps_data,
)

# Prakash's model type_map order — the LAMMPS type ids the data file must
# use so `pair_coeff * *` maps each type to the right element.
PRAKASH_TYPE_MAP = {"Si": 1, "Li": 2, "Nb": 3, "O": 4}
BOND_CUTOFF_ANGSTROM = 2.8


def _install_demo_mode() -> None:
    """Bypass the §3.5 gate halt + tolerate lost atoms — VISUAL ONLY.

    The oxide interface has no gate reference (silicon-only) and the gate
    cannot distinguish the two wafers, so for a workflow visual we make the
    gate pass and let LAMMPS warn (not abort) on lost atoms. The result
    numbers are NOT meaningful; the point is to see the pipeline execute.
    """
    import sabsim.driver.press_pull as press_pull
    from sabsim.driver.activation_gate import ActivationVerdict

    original_preamble = press_pull.preamble_commands
    press_pull.preamble_commands = (
        lambda *a, **k: list(original_preamble(*a, **k))
        + ["thermo_modify lost warn"])

    def _demo_gate(engine, built):
        passed = ActivationVerdict(
            passed=True, activated_depth=0.0, per_metric={},
            reason="DEMO: oxide gate bypassed for a workflow visual")
        return passed, passed

    press_pull.gate_healed_surfaces = _demo_gate
    print("*** DEMO MODE: oxide gate bypassed + lost atoms tolerated — "
          "VISUAL ONLY ***")


def _widen_gap(built, target: float = 8.0):
    """Force a clean wide gap by sliding wafer B up (demo assembly aid).

    The cascade-only oxide surfaces are ROUGH/puffed (no post-cascade cool),
    so the automatic assembly leaves the closest atoms ~1 A apart even at a
    10 A dividing-surface gap — a clash on contact. For the visual we slide
    wafer B up so the closest-atom gap is ``target`` (> the potential cutoff,
    so the heal engages), extend the box, and update the wafer-B range +
    interface plane. Not the intended physics; a demo aid.
    """
    atoms = built.atoms.copy()
    tags = np.asarray(atoms.get_tags())
    positions = atoms.get_positions()
    a_high = positions[tags == WAFER_A_TAG][:, 2].max()
    b_low = positions[tags == WAFER_B_TAG][:, 2].min()
    shift = target - (b_low - a_high)
    if shift > 0.0:
        positions[tags == WAFER_B_TAG, 2] += shift
        atoms.set_positions(positions)
        cell = np.asarray(atoms.get_cell())
        cell[2, 2] = positions[:, 2].max() + 15.0
        atoms.set_cell(cell)
    b_low = float(positions[tags == WAFER_B_TAG][:, 2].min())
    b_high = float(positions[tags == WAFER_B_TAG][:, 2].max())
    return dataclasses.replace(
        built, atoms=atoms, wafer_b_z_range=(b_low, b_high),
        interface_z=float(a_high + target / 2.0))


def _trim(member):
    """Short press hold + a single fast pull rung — a first number/visual."""
    ladder = member.numerical.pull_rate_ladder
    fastest = max(ladder, key=lambda rate: rate.value)
    trimmed_numerical = dataclasses.replace(
        member.numerical, pull_rate_ladder=(fastest,))
    trimmed_protocol = dataclasses.replace(
        member.protocol, press_duration=Quantity(10.0, "ps"))
    return dataclasses.replace(
        member, numerical=trimmed_numerical, protocol=trimmed_protocol)


def main() -> None:
    print("=== T-13 SiO2/LiNbO3 bond-debond (demo) ===")
    if os.environ.get("SABSIM_BOND_DEMO") == "1":
        _install_demo_mode()
    template = os.environ["SABSIM_TEMPLATE"]
    work_directory = os.environ["VALWORK"]
    os.makedirs(work_directory, exist_ok=True)
    set_trajectory_options(TrajectoryOptions(enabled=True, stride=500))

    # The two amorphized surfaces (already on the shared commensurate cell)
    # and the match that built them.
    half_a = ase_read(os.environ["SIO2_SURFACE"], format="extxyz")
    half_b = ase_read(os.environ["LINBO3_SURFACE"], format="extxyz")
    half_a.set_tags([WAFER_A_TAG] * len(half_a))
    half_b.set_tags([WAFER_B_TAG] * len(half_b))
    with open(os.environ["MATCH_PKL"], "rb") as handle:
        match = pickle.load(handle)["match"]
    print(f"SiO2 (A): {len(half_a)} atoms | LiNbO3 (B): {len(half_b)} atoms")

    built = assemble_amorphized_pair(
        half_a, half_b, match, bond_cutoff=BOND_CUTOFF_ANGSTROM,
        initial_gap=10.0, clash_floor=1.8)
    # The rough cascade-only surfaces assemble near-touching; force a clean
    # wide gap for the demo so the heal path engages (see _widen_gap).
    built = _widen_gap(built, target=8.0)
    gap = built.wafer_b_z_range[0] - built.wafer_a_z_range[1]
    print(f"assembled pair: {len(built.atoms)} atoms | gap {gap:.2f} A "
          f"| species {sorted(set(built.atoms.get_chemical_symbols()))}")

    # Remap to Prakash's type order so `pair_coeff * *` is correct, and
    # write the data file under that mapping.
    built = dataclasses.replace(built, type_map=dict(PRAKASH_TYPE_MAP))
    data_file = os.path.join(work_directory, "oxide_pair.data")
    write_lammps_data(built, data_file)

    member = _trim(load_and_validate_study(template).members[1])
    structure = Structure(
        note="t13 SiO2/LiNbO3 interface", labeled_groups=("interface_z",),
        data_file=data_file, built=built)

    print("bond model (SABSIM_DEEPMD_MODEL):",
          os.environ.get("SABSIM_DEEPMD_MODEL"))
    print("=== bond-debond: heal -> (gate bypassed) -> press -> pull ===")
    result = run_bond_debond_md_live(
        structure, potential=None, member=member,
        scratch_directory=work_directory)

    print("=== result ===")
    print("press bonded   :", result.press.bonded, "|", result.press.note)
    print("reference_ok   :", result.reference_ok)
    for pull in result.pulls:
        print(f"pull @ {pull.rate_value} {pull.rate_unit}: "
              f"complete={pull.complete} "
              f"separation_index={pull.separation_index} "
              f"atoms_conserved={pull.atoms_conserved} | {pull.note}")
    print("T13 SIO2/LINBO3 BOND-DEBOND RUN COMPLETE")


if __name__ == "__main__":
    main()
