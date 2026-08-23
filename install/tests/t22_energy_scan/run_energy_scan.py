#!/usr/bin/env python
"""TIER-1 ENERGY SCAN: bombardment energy -> reachable damage depth.

The 2026-07-21 sweep established that ENERGY sets the depth the damage
can REACH (it is the ion range) while DOSE only fills in disorder once
that range is saturated. Tier 1 exploits that: it spends its budget on
MANY ENERGIES at ONE impact and ONE seed rather than on full dose rows,
which is what brackets the operating energy. Seeds come later, on the
chosen point only (Paul, 2026-08-23).

Each array task runs ONE energy through the mainline pipeline call
(`activate_one_half`), so this is the real cascade path and not a
one-off script. Two depths are recorded because they answer different
questions at one impact:

  * the §3.5 gate's `activated_depth`, which is a SLAB-AVERAGED skin
    thickness and therefore reads low when a single impact leaves most
    of the surface pristine; and
  * the maximum depth of any displaced substrate atom, measured here
    against the pristine slab, which is the ion-range proxy the energy
    bracket actually needs.

The slab is rescaled to the WORKING LATTICE OF THE MODEL BEING USED
(DESIGN §2.2) before it is cut. Bombarding a cell cut on the CIF's
published scale under a model with a different equilibrium leaves the
slab strained, which is the error that produced the T-18 oxide
detonation and was measured at -1.52% for DPA-2.4-7M (LEDGER T-21).
"""

from __future__ import annotations

import dataclasses
import os
import sys
import time

import numpy as np
from ase.io import read as ase_read
from mpi4py import MPI

from sabsim.deploy.scratch import job_scratch
from sabsim.pipeline.exec_artifacts import HalfHandle
from sabsim.pipeline.live_stages import activate_one_half
from sabsim.spec.loader import load_and_validate_study
from sabsim.spec.records import MemberSpecification, Quantity
from sabsim.structure.slab_builder import (
    WAFER_A_TAG,
    build_standalone_half,
    load_crystal,
    rescale_crystal_to_cell,
    write_standalone_half,
)

# install/tests/t22_energy_scan/<this file> -> four levels to the root.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
JOB_DIR = os.path.join(REPO_ROOT, "jobs", "bulk_si")
STUDY_SPEC = os.path.join(REPO_ROOT, "dev", "templates", "study_spec.toml")

# The energies to bracket. Deliberately wider than the 40-75 eV the
# classical sweep covered, so BOTH bounds fall inside the scan: the
# amorphization threshold below (where the skin degrades into a rough
# crystalline surface) and the sputtering threshold above (where atoms
# start leaving and the gate fails outright).
SCAN_ENERGIES_EV = [20.0, 30.0, 40.0, 50.0, 60.0, 70.0,
                    85.0, 100.0, 120.0, 140.0, 170.0, 200.0]

# One impact per point: this measures REACH, not fill. The cell is sized
# to roughly one cascade footprint (~625 A^2/ion is the measured
# spacing), so a single impact is not diluted across a wide slab the way
# it would be in the 10x10 production cell.
LATERAL_REPEAT = 7
MIN_SLAB_THICKNESS = 55.0        # A: base + border + undamaged bulk
MIN_VACUUM = 30.0                # A: room above for the beam spawn
CASCADE_PS, RELAX_PS, REANNEAL_PS = 0.5, 0.5, 2.0
SEED = 12345

# Working lattice of DPA-3.1-3M, measured by the Tier-0 screen
# (a = 5.5147 A, +1.54% vs experiment) -- the model this scan runs
# under. DPA-2.4-7M's 5.3475 A is NOT usable: it fails Tier-0.
MODEL_LATTICE_ANGSTROM = 5.5147
CIF_LATTICE_ANGSTROM = 5.4300     # what the CIF ships (for contrast)
DISPLACEMENT_THRESHOLD = 1.0     # A: beyond thermal rattle


def member_for(base: MemberSpecification, energy: float,
               fluence: float) -> MemberSpecification:
    """The base member re-pointed at this scan's energy and dose."""
    reanneal = dataclasses.replace(
        base.protocol.reanneal_schedule,
        hold_duration=Quantity(REANNEAL_PS, "ps"))
    protocol = dataclasses.replace(
        base.protocol,
        activation_energy=Quantity(energy, "eV"),
        activation_fluence=Quantity(fluence, "1/angstrom^2"),
        cascade_duration=Quantity(CASCADE_PS, "ps"),
        between_impact_relaxation=Quantity(RELAX_PS, "ps"),
        reanneal_schedule=reanneal)
    return dataclasses.replace(base, protocol=protocol)


def deepest_displacement(pristine_file: str, amorphized_file: str) -> float:
    """Depth below the pristine surface of the deepest displaced atom.

    Atoms are paired BY ORDER after both files are read with the same
    reader and the same sorting, which holds because the cascade writes
    an id-sorted structure and no substrate atom is created. Any atom
    that lost more than the thermal-rattle threshold counts as
    displaced; the deepest such atom marks how far the damage reached.
    Lateral wrap is folded to the nearest image before the distance is
    taken, since x and y are periodic.
    """
    pristine = ase_read(pristine_file, format="lammps-data",
                        Z_of_type={1: 18, 2: 14}, parallel=False)
    damaged = ase_read(amorphized_file, parallel=False)
    pristine_positions = pristine.get_positions()
    damaged_positions = damaged.get_positions()
    shared = min(len(pristine_positions), len(damaged_positions))
    cell = np.diag(pristine.get_cell())
    surface_z = float(pristine_positions[:, 2].max())

    separation = damaged_positions[:shared] - pristine_positions[:shared]
    for axis in (0, 1):
        separation[:, axis] -= cell[axis] * np.round(
            separation[:, axis] / cell[axis])
    distance = np.linalg.norm(separation, axis=1)
    moved = distance > DISPLACEMENT_THRESHOLD
    if not np.any(moved):
        return 0.0
    return float(surface_z - pristine_positions[:shared][moved, 2].min())


def main() -> None:
    """Run the one energy this array task owns."""
    communicator = MPI.COMM_WORLD
    rank = communicator.Get_rank()
    task_index = int(sys.argv[1])
    energy = SCAN_ENERGIES_EV[task_index]

    study = load_and_validate_study(STUDY_SPEC)
    base = next(m for m in study.members if m.name == "si-si-reference")
    wafer = base.material.wafer_a
    crystal = load_crystal(os.path.join(REPO_ROOT, wafer.cif_source))

    # DESIGN §2.2: cut the slab on the model's own working lattice,
    # through the SAME mainline call the pipeline uses (it keeps the
    # fractional coordinates, so the basis rides along).
    crystal = rescale_crystal_to_cell(
        crystal, np.diag([MODEL_LATTICE_ANGSTROM] * 3))

    half = build_standalone_half(
        crystal, wafer.surface_face, wafer.identity,
        {base.protocol.activation_species},
        min_slab_thickness=MIN_SLAB_THICKNESS, min_vacuum=MIN_VACUUM,
        lateral_repeat=LATERAL_REPEAT)

    cell = half.atoms.get_cell()
    area = float(abs(np.cross(cell[0], cell[1])[2]))
    # Exactly one impact, whatever the cell came out to.
    fluence = 1.0 / area

    scratch = job_scratch(JOB_DIR) if rank == 0 else None
    scratch = communicator.bcast(scratch, root=0)
    label = f"scan_e{int(energy):03d}"
    data_file = os.path.join(scratch, f"scan_slab_{label}.data")
    output = os.path.join(scratch, label)
    if rank == 0:
        write_standalone_half(half, data_file)
        os.makedirs(output, exist_ok=True)
    communicator.Barrier()

    handle = HalfHandle(
        data_file=data_file, type_map=half.type_map,
        identity=wafer.identity, wafer_tag=WAFER_A_TAG)

    if rank == 0:
        print(f"SCAN point {label}: {len(half.atoms)} Si atoms, "
              f"{float(cell[0][0]):.1f} A wide, area {area:.0f} A^2, "
              f"lattice {MODEL_LATTICE_ANGSTROM} A, "
              f"fluence {fluence:.6f} -> 1 impact", flush=True)

    started = time.perf_counter()
    result, amorphized_file = activate_one_half(
        handle, member_for(base, energy, fluence), SEED, output,
        communicator)
    elapsed = time.perf_counter() - started

    if rank == 0:
        verdict = result.verdict
        survivors = len(ase_read(amorphized_file, parallel=False))
        reach = deepest_displacement(data_file, amorphized_file)
        sputtered = len(half.atoms) - survivors
        print(f"SCANRESULT energy_eV={energy:.0f} "
              f"impacts={result.cascade.impacts_run} "
              f"atoms={len(half.atoms)} survivors={survivors} "
              f"sputtered={sputtered} "
              f"gate_depth={verdict.activated_depth:.3f} "
              f"reach_depth={reach:.3f} "
              f"gate_passed={verdict.passed} seconds={elapsed:.0f}",
              flush=True)
        for name, metric in verdict.per_metric.items():
            measured = (f"{metric.measured:.4f}"
                        if isinstance(metric.measured, (int, float))
                        else "curve")
            print(f"SCANMETRIC energy_eV={energy:.0f} {name}={measured} "
                  f"threshold={metric.threshold} passed={metric.passed}",
                  flush=True)


if __name__ == "__main__":
    main()
