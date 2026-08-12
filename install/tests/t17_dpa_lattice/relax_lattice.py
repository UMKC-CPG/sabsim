#!/usr/bin/env python
"""T-17 part 2 (deepmd BUNDLE Python): DPA box-relax each bulk crystal.

For each pre-built bulk supercell this measures the universal DPA model's
OWN preferred lattice, the number the T-16 explosion hinged on. The recipe
per material:

  1. Read the crystal at its CIF lattice and evaluate the pressure with
     `run 0`. That INITIAL pressure is "how far off the CIF lattice is"
     under DPA -- the single-material analogue of the joint cell's 24 GPa.
  2. Relax the box to zero pressure with an anisotropic-plus-tilt NPT at a
     modest temperature, so the lattice finds the DPA equilibrium while
     the crystal's own restoring forces (if it is dynamically stable) keep
     it ordered. A crystal that MELTS or disorders here is itself the
     answer: "pristine" is not a valid reference for this material under
     this potential.
  3. Average the box over a trailing window and report the equilibrium
     lattice parameters, per unit cell, beside the CIF baseline.

Runs INSIDE the deepmd bundle so its in-process LAMMPS loads the `.pt2`;
the model needs `atom_modify map yes` (single-rank C API). Lost atoms are
demoted to a warning so an unstable crystal is OBSERVED, not a crash.

Env: VALWORK (holds the *_bulk.data files + baseline.json + outputs),
SABSIM_CASCADE_MLIP_MODEL (the .pt2). Optional T17_TEMP (K, default 300),
T17_NSTEPS (relax steps, default 20000), T17_DT (ps, default 0.0005 =
0.5 fs -- conservative against the run-away the joint cell showed).
"""

import json
import math
import os

import numpy as np
from lammps import lammps

# Atomic masses (metal units, g/mol) for the elements this pair spans.
_ELEMENT_MASS = {
    "Si": 28.0855, "O": 15.999, "Li": 6.941, "Nb": 92.90638,
}


def _box_cellpar(handle) -> tuple:
    """Return (a, b, c, alpha, beta, gamma) from the live LAMMPS box.

    LAMMPS carries a restricted-triclinic box whose three edge vectors are
    A = (lx, 0, 0), B = (xy, ly, 0), C = (xz, yz, lz). The lattice
    parameters are the vector lengths and the angles between them, exactly
    as a crystallographer reports a unit cell.
    """
    boxlo, boxhi, xy, yz, xz, _period, _changed = handle.extract_box()
    length_x = boxhi[0] - boxlo[0]
    length_y = boxhi[1] - boxlo[1]
    length_z = boxhi[2] - boxlo[2]
    edge_a = np.array([length_x, 0.0, 0.0])
    edge_b = np.array([xy, length_y, 0.0])
    edge_c = np.array([xz, yz, length_z])

    def _angle(vec_one, vec_two) -> float:
        cosine = (float(np.dot(vec_one, vec_two))
                  / (np.linalg.norm(vec_one) * np.linalg.norm(vec_two)))
        return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))

    return (float(np.linalg.norm(edge_a)), float(np.linalg.norm(edge_b)),
            float(np.linalg.norm(edge_c)),
            _angle(edge_b, edge_c), _angle(edge_a, edge_c),
            _angle(edge_a, edge_b))


def _relax_one(name: str, info: dict, work: str, model: str,
               temperature: float, relax_steps: int, timestep: float) -> dict:
    """Box-relax one crystal and return its measured DPA lattice."""
    elements = info["specorder"]
    repeats = info["repeats"]
    data_file = os.path.join(work, f"{name}_bulk.data")

    handle = lammps(cmdargs=[
        "-screen", "none", "-log", os.path.join(work, f"log.{name}")])
    setup = [
        "units metal", "atom_style atomic", "atom_modify map yes",
        "boundary p p p", "thermo_modify lost warn",
        f"read_data {data_file}",
        f"pair_style deepmd {model}",
        f"pair_coeff * * {' '.join(elements)}",
    ]
    # The data file carries no masses; set them from the species order so
    # the dynamics have inertia (deepmd forces do not use mass, but NPT
    # integration does).
    for type_id, element in enumerate(elements, start=1):
        setup.append(f"mass {type_id} {_ELEMENT_MASS[element]}")
    setup += [
        "thermo 200",
        "thermo_style custom step temp pe press pxx pyy pzz lx ly lz vol",
        "run 0",
    ]
    handle.commands_list(setup)

    starting_atoms = int(handle.get_natoms())
    initial_pressure = float(handle.get_thermo("press"))
    initial_pe_per_atom = float(handle.get_thermo("pe")) / starting_atoms
    initial_cellpar = _box_cellpar(handle)
    print(f"\n=== {name}: INITIAL (at CIF lattice) ===")
    print(f"  atoms={starting_atoms}  pressure={initial_pressure:.1f} bar  "
          f"pe/atom={initial_pe_per_atom:.4f} eV")

    # Zero-pressure box relax. `tri` frees all three lengths and the tilts,
    # so a hexagonal cell can breathe without being forced orthogonal.
    seed = 20260812
    handle.commands_list([
        f"velocity all create {temperature} {seed} mom yes rot yes",
        f"timestep {timestep}",
        f"dump traj all custom 500 {os.path.join(work, name + '_relax.dump')} "
        "id type x y z",
        f"fix relax all npt temp {temperature} {temperature} 0.05 "
        "tri 0.0 0.0 0.5",
        f"run {relax_steps}",
    ])

    # Average the equilibrated box over a trailing window so a single
    # thermal snapshot does not skew the lattice we report.
    handle.commands_list([
        "variable va equal lx", "variable vb equal ly",
        "variable vc equal lz", "variable vxy equal xy",
        "variable vxz equal xz", "variable vyz equal yz",
        f"fix boxavg all ave/time 10 200 2000 v_va v_vb v_vc "
        f"v_vxy v_vxz v_vyz file {os.path.join(work, name + '_boxavg.txt')}",
        "run 2000",
    ])

    final_atoms = int(handle.get_natoms())
    final_pressure = float(handle.get_thermo("press"))
    final_pe_per_atom = float(handle.get_thermo("pe")) / max(1, final_atoms)
    final_cellpar = _box_cellpar(handle)
    handle.close()

    # Per-unit-cell lattice = supercell edge lengths divided by the repeats
    # (repeat() scaled each edge by its count); angles are unchanged.
    per_cell = [final_cellpar[i] / repeats[i] for i in range(3)]
    cif = info["unit_cell_cellpar"]
    percent = [100.0 * (per_cell[i] - cif[i]) / cif[i] for i in range(3)]

    print(f"=== {name}: RELAXED (DPA zero-pressure) ===")
    print(f"  atoms={final_atoms} (lost {starting_atoms - final_atoms})  "
          f"pressure={final_pressure:.1f} bar  "
          f"pe/atom={final_pe_per_atom:.4f} eV")
    print(f"  per-cell a,b,c = {per_cell[0]:.4f} {per_cell[1]:.4f} "
          f"{per_cell[2]:.4f}  angles {final_cellpar[3]:.2f} "
          f"{final_cellpar[4]:.2f} {final_cellpar[5]:.2f}")
    print(f"  CIF     a,b,c = {cif[0]:.4f} {cif[1]:.4f} {cif[2]:.4f}")
    print(f"  change  a,b,c = {percent[0]:+.2f}% {percent[1]:+.2f}% "
          f"{percent[2]:+.2f}%")

    return {
        "name": name,
        "starting_atoms": starting_atoms, "final_atoms": final_atoms,
        "initial_pressure_bar": initial_pressure,
        "final_pressure_bar": final_pressure,
        "initial_pe_per_atom": initial_pe_per_atom,
        "final_pe_per_atom": final_pe_per_atom,
        "cif_per_cell_cellpar": cif,
        "dpa_per_cell_cellpar": per_cell + list(final_cellpar[3:]),
        "percent_change_abc": percent,
    }


def main() -> None:
    work = os.environ["VALWORK"]
    model = os.environ["SABSIM_CASCADE_MLIP_MODEL"]
    temperature = float(os.environ.get("T17_TEMP", "300"))
    relax_steps = int(os.environ.get("T17_NSTEPS", "20000"))
    timestep = float(os.environ.get("T17_DT", "0.0005"))

    with open(os.path.join(work, "baseline.json")) as handle:
        baseline = json.load(handle)

    results = {}
    for name, info in baseline.items():
        results[name] = _relax_one(
            name, info, work, model, temperature, relax_steps, timestep)

    with open(os.path.join(work, "lattice_results.json"), "w") as handle:
        json.dump(results, handle, indent=2)
    print("\nT17 DPA LATTICE DIAGNOSTIC COMPLETE ->",
          os.path.join(work, "lattice_results.json"))


if __name__ == "__main__":
    main()
