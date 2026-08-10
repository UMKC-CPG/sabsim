#!/usr/bin/env python
"""T-14: press-pull the SiO2/LiNbO3 pair under the UNIVERSAL DPA model.

Bonds the two matched amorphized oxide surfaces under the SAME potential
that MADE them (DPA-2.4-7M), out-of-process in the deepmd bundle on the
GPU. Because the surfaces are in-distribution for DPA, there is no
potential-change out-of-distribution collapse — the failure mode of T-13
(pressing DPA surfaces under Prakash's model). This is the honest test of
whether the interface holds together at all when the potential is not
switched.

It is a self-contained, precomputed press-pull LAMMPS script (no in-process
driver — the bundle runs it as `lmp -in`): freeze the bottom grip, thermal
mobile interior, HEAL at the gap, DRIVE the top grip down to press the
surfaces together, HOLD to bond, then DRIVE the top grip up to pull them
apart — recording a movie throughout. A workflow visual under the
in-distribution potential, not a converged measurement.

Env (slurm wrapper): SABSIM_CASCADE_ENGINE_PREFIX (the bundle),
SABSIM_CASCADE_MLIP_MODEL (the .pt2), OXIDE_PAIR_DATA (the assembled pair),
VALWORK (scratch).
"""

import os

import numpy as np
from ase.data import atomic_numbers
from ase.io import read as ase_read

from sabsim.driver.cascade_subprocess import (
    resolve_cascade_engine_prefix,
    run_activate_subprocess,
)

# The data file's LAMMPS type order (written by T-13 to match Prakash's
# model): 1=Si, 2=Li, 3=Nb, 4=O. DPA maps types to elements by this list.
TYPE_ELEMENTS = ["Si", "Li", "Nb", "O"]


def _press_pull_script(data_file, model_path, movie_path, output_path,
                       base_low, top_high, seed=20260810) -> list:
    """A precomputed press-pull command stream for the bundle's lmp.

    Groups by z: the bottom ~5 A is a frozen grip, the top ~5 A is the
    driven grip, and everything between is thermal NVE interior. The press
    drives the top grip down (closing the ~8 A gap and engaging), a hold
    lets the interface bond, and the pull drives it back up to separate.
    Velocities are in A/ps (metal); at a 1 fs step, `run N` spans N fs.
    """
    z_of_type = " ".join(TYPE_ELEMENTS)
    return [
        "units metal",
        "atom_style atomic",
        "atom_modify map yes sort 0 0.0",     # required for the GNN model
        "boundary p p f",
        f"read_data {data_file}",
        f"pair_style deepmd {model_path}",
        f"pair_coeff * * {z_of_type}",
        "neighbor 2.0 bin",
        "timestep 0.001",                     # 1 fs
        # Zones: frozen bottom grip, driven top grip, thermal interior.
        f"region r_bot block INF INF INF INF {base_low - 1} {base_low + 5}",
        f"region r_top block INF INF INF INF {top_high - 5} {top_high + 200}",
        "group g_bot region r_bot",
        "group g_top region r_top",
        "group g_mob subtract all g_bot g_top",
        f"velocity g_mob create 300.0 {seed} mom yes rot yes",
        "fix hold_bot g_bot setforce 0.0 0.0 0.0",
        "fix nve_mob g_mob nve",
        f"fix lang_mob g_mob langevin 300.0 300.0 0.1 {seed}",
        "fix hold_top g_top setforce 0.0 0.0 0.0",
        "thermo 200",
        "thermo_style custom step temp pe press",
        "thermo_modify lost warn",            # tolerate any stray atom
        f"dump movie all custom 50 {movie_path} id type x y z",
        "dump_modify movie sort id",
        # HEAL at the gap (both grips held, interior relaxes).
        "run 3000",
        # PRESS: release the top grip's hold and drive it DOWN (close the
        # ~8 A gap + engage over ~12 A).
        "unfix hold_top",
        "fix drive_top g_top move linear 0.0 0.0 -2.0",
        "run 6000",
        # HOLD at contact to let the interface bond.
        "unfix drive_top",
        "fix hold_top2 g_top setforce 0.0 0.0 0.0",
        "run 4000",
        # PULL: drive the top grip UP to separate the wafers.
        "unfix hold_top2",
        "fix pull_top g_top move linear 0.0 0.0 3.0",
        "run 8000",
        f"write_dump all custom {output_path} id type x y z modify sort id",
    ]


def main() -> None:
    work_directory = os.environ["VALWORK"]
    os.makedirs(work_directory, exist_ok=True)
    data_file = os.environ["OXIDE_PAIR_DATA"]
    model_path = os.environ["SABSIM_CASCADE_MLIP_MODEL"]

    print("=== T-14 DPA press-pull (SiO2/LiNbO3, in-distribution) ===")
    print("engine prefix:", resolve_cascade_engine_prefix())
    print("model:", model_path)
    print("pair:", data_file)

    # Read the pair's z-range to set the grip zones.
    z_of_type = {i + 1: atomic_numbers[el]
                 for i, el in enumerate(TYPE_ELEMENTS)}
    atoms = ase_read(data_file, format="lammps-data",
                     Z_of_type=z_of_type, style="atomic")
    z = atoms.get_positions()[:, 2]
    base_low, top_high = float(z.min()), float(z.max())
    print(f"pair: {len(atoms)} atoms | z {base_low:.1f}..{top_high:.1f}")

    movie_path = os.path.join(work_directory, "press_pull_movie.dump")
    output_path = os.path.join(work_directory, "final.dump")
    script = _press_pull_script(
        data_file, model_path, movie_path, output_path, base_low, top_high)
    with open(os.path.join(work_directory, "script_preview.in"), "w") as fh:
        fh.write("\n".join(script) + "\n")
    print("script lines:", len(script))

    run_activate_subprocess(
        script, work_directory, output_path,
        script_name="press_pull.in", log_name="log.press_pull")

    frames = 0
    if os.path.exists(movie_path):
        with open(movie_path) as handle:
            frames = sum(1 for line in handle if line.startswith("ITEM: TIME"))
    print(f"press-pull movie: {movie_path} | frames={frames}")
    print("T14 DPA PRESS-PULL COMPLETE")


if __name__ == "__main__":
    main()
