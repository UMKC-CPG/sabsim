#!/usr/bin/env python
"""Amorphize ONE pre-built matched oxide half with the universal cascade.

Step 2 of the SiO2/LiNbO3 thread: take a half that `build_matched_halves`
already cut on the shared commensurate cell (strain baked in) and bombard
its surface with the universal DPA-2.4-7M cascade, out-of-process on the
GPU, recording a movie of the whole bombardment. It reads the amorphized
surface back and saves it (tagged as its wafer) for the later assembly.

NO gate here: the §3.5 activation-gate references exist only for silicon so
far, so an oxide surface would be UNRESOLVED. The goal of this run is to
CREATE the amorphous surface (and watch it form); judging it against an
oxide reference is a later step, the analogue of Si's T-10.

Env (slurm wrapper): T12_HALF_NAME (sio2 | linbo3), VALWORK (holds the
pre-built {name}_half.{data,pkl}), SABSIM_TEMPLATE, and the out-of-process
cascade engine knobs (SABSIM_CASCADE_ENGINE_PREFIX / _MLIP_MODEL /
_ALLOW_UNVALIDATED_POTENTIAL). Optional T12_TRAJ_STRIDE.
"""

import os
import pickle
from types import SimpleNamespace

from ase.io import write as ase_write

from sabsim.driver.cascade import (
    build_activate_script,
    derive_bombardment_spec,
    _projectile_species,
)
from sabsim.driver.cascade_potential import resolve_cascade_generator
from sabsim.driver.cascade_subprocess import (
    read_dump_structure,
    resolve_cascade_engine_prefix,
    run_activate_subprocess,
)
from sabsim.driver.commands import CascadeGeometry
from sabsim.spec.loader import load_and_validate_study
from sabsim.structure.amorphized_assembly import amorphized_half_from_arrays
from sabsim.structure.slab_builder import WAFER_A_TAG, WAFER_B_TAG

# SiO2 becomes wafer A (bottom), LiNbO3 wafer B (top), the assembly order.
_WAFER_TAG = {"sio2": WAFER_A_TAG, "linbo3": WAFER_B_TAG}


def _self_log_environment(half_name: str) -> None:
    """Emit the env FIRST, so the log alone reconstructs the run (LEDGER)."""
    import ase
    import sabsim

    print(f"=== oxide activation environment ({half_name}) ===")
    print("python          :", os.popen("command -v python").read().strip())
    print("sabsim.__file__ :", sabsim.__file__)
    print("ase version     :", ase.__version__)
    for name in ("T12_HALF_NAME", "SABSIM_CASCADE_ENGINE_PREFIX",
                 "SABSIM_CASCADE_MLIP_MODEL",
                 "SABSIM_ALLOW_UNVALIDATED_POTENTIAL", "SABSIM_TEMPLATE",
                 "VALWORK", "CUDA_VISIBLE_DEVICES"):
        print(f"  {name} = {os.environ.get(name, '(unset)')}")
    print("cascade engine prefix resolves:", resolve_cascade_engine_prefix())
    print("====================================")


def main() -> None:
    half_name = os.environ["T12_HALF_NAME"]
    _self_log_environment(half_name)
    work_directory = os.environ["VALWORK"]
    template = os.environ["SABSIM_TEMPLATE"]
    traj_stride = int(os.environ.get("T12_TRAJ_STRIDE", "500"))

    with open(os.path.join(work_directory, f"{half_name}_half.pkl"),
              "rb") as handle:
        half = pickle.load(handle)
    data_file = os.path.join(work_directory, f"{half_name}_half.data")
    built = SimpleNamespace(atoms=half.atoms, type_map=half.type_map)
    print(f"{half_name}: {len(half.atoms)} atoms | type_map {half.type_map}")

    # The cascade knobs (Ar beam, 75 eV, 0.025 ions/A^2, the 0.1 fs cascade
    # step) are material-agnostic, so any member's protocol carries them; the
    # impact COUNT derives from THIS half's lateral area. The universal force
    # model ignores the member's domain.
    member = load_and_validate_study(template).members[1]   # si-si-reference
    spec = derive_bombardment_spec(built, member)
    print(f"cascade: {spec.impact_count} impacts of {spec.projectile_symbol} "
          f"at {spec.impact_energy:.0f} eV")

    projectile_species = _projectile_species(member)
    projectile_types = [half.type_map[symbol] for symbol in projectile_species
                        if symbol in half.type_map]
    cascade_force_model = resolve_cascade_generator(
        half.type_map, projectile_species, allow_unvalidated=True,
        domain=member.material_domain, use_classical=False)
    print("cascade pair_style:", cascade_force_model.pair_style)

    dump_path = os.path.join(work_directory, f"{half_name}_activated.dump")
    movie_path = os.path.join(work_directory, f"{half_name}_movie.dump")
    script = build_activate_script(
        built, member, cascade_force_model, data_file, spec, seed=20260809,
        projectile_types=projectile_types, output_structure_file=dump_path,
        geometry=CascadeGeometry(),
        trajectory_file=movie_path, trajectory_stride=traj_stride)
    print("script lines:", len(script), "| movie:", movie_path)

    run_activate_subprocess(
        script, work_directory, dump_path,
        script_name=f"activate_{half_name}.in",
        log_name=f"log.activate_{half_name}")

    positions, type_ids = read_dump_structure(dump_path)
    surviving = sorted({int(t) for t in type_ids})
    print("readback atoms:", len(positions), "| surviving types:", surviving)

    amorphized = amorphized_half_from_arrays(
        positions, type_ids, half.atoms.get_cell(), half.type_map,
        _WAFER_TAG[half_name])
    out = os.path.join(work_directory, f"{half_name}_activated.extxyz")
    ase_write(out, amorphized, format="extxyz", parallel=False)
    print("wrote amorphized surface:", out)
    print(f"T12 {half_name.upper()} AMORPHIZATION COMPLETE")


if __name__ == "__main__":
    main()
