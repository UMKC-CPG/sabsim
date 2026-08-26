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
one-off script. One extra task past the energies is a NULL CONTROL: the
same path with zero impacts, which measures how much of the signal the
pre-relax alone would have produced.

What is recorded is REACH — the depth of the deepest lattice site the
cascade emptied — and NOT a skin thickness. The distinction matters at
one impact. A single ion empties a scattering of sites along one track;
it does not dissolve a layer, so any slab-averaged skin measure (the
§3.5 gate's `activated_depth` among them) reads essentially zero and
says nothing about where the ion stopped. Reach is what brackets the
operating energy; the skin needs dose, which is a later run.

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
SUBSTRATE_SYMBOL = "Si"          # the species whose sites are counted
VACANCY_THRESHOLD = 1.0          # A: beyond thermal rattle

# The NULL CONTROL runs as one extra array task past the energies: the
# identical path with ZERO impacts, so the slab still gets read, gets its
# §2.4 pre-relax, gets cleaned up and gets written out -- everything the
# bombarded points get EXCEPT the bombardment. Its vacated-site count is
# the measurement's false-positive floor, which is what turns "31 sites
# vacated at 20 eV" from a number into a number above a measured
# background. Without it the pre-relax's own settling is indistinguishable
# from damage, and comparing against an as-cut file instead (the first
# analysis did) measures RELAXATION, not damage.
NULL_TASK_INDEX = len(SCAN_ENERGIES_EV)


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


def damage_reach(pristine_file: str, amorphized_file: str) -> tuple:
    """How deep the damage reached, measured by VACATED LATTICE SITES.

    The obvious measurement — pair each atom with its own former self and
    ask how far it moved — is not available here, and quietly produces
    nonsense if attempted. The cascade cleanup strips the projectile and
    RENUMBERS what is left, so final id ``N`` carries the input's id
    ``N + 1``; pairing the two files row for row therefore compares each
    atom against its neighbour's site and reports the whole slab moving
    a lattice spacing at every energy (LEDGER T-22).

    Vacancy sidesteps the correspondence problem entirely. For every site
    in the PRISTINE slab this asks how far away the nearest atom in the
    DAMAGED slab is, whichever atom that turns out to be. A site with no
    atom within ``VACANCY_THRESHOLD`` was emptied — its occupant left and
    nothing took its place — and that judgement needs no id agreement
    between the files at all. The deepest emptied site is how far the
    damage reached, which is the ion-range proxy the energy bracket
    needs.

    Note this is a REACH measure, not a skin thickness: a single impact
    empties a scattering of sites along one track rather than dissolving
    a layer. Returns ``(reach_angstrom, vacated_count)``.
    """
    pristine = ase_read(pristine_file, format="lammps-data",
                        Z_of_type={1: 18, 2: 14}, parallel=False)
    damaged = ase_read(amorphized_file, parallel=False)
    # Both slabs are filtered to the SUBSTRATE species: the projectile is
    # neither present in the pristine cut nor kept past the cleanup, and
    # a stray argon would otherwise read as an occupied silicon site.
    pristine_sites = pristine.get_positions()[
        np.array(pristine.get_chemical_symbols()) == SUBSTRATE_SYMBOL]
    damaged_atoms = damaged.get_positions()[
        np.array(damaged.get_chemical_symbols()) == SUBSTRATE_SYMBOL]
    cell = np.diag(np.asarray(pristine.get_cell()))
    surface_z = float(pristine_sites[:, 2].max())

    # Nearest damaged atom to each pristine site. x and y are periodic,
    # so every separation is folded to its nearest image first; z is the
    # open direction (`p p f`) and is left alone.
    nearest_distance = np.empty(len(pristine_sites))
    for index, site in enumerate(pristine_sites):
        separation = damaged_atoms - site
        for axis in (0, 1):
            separation[:, axis] -= cell[axis] * np.round(
                separation[:, axis] / cell[axis])
        nearest_distance[index] = np.sqrt(
            np.min(np.einsum("ij,ij->i", separation, separation)))

    vacated = nearest_distance > VACANCY_THRESHOLD
    if not np.any(vacated):
        return 0.0, 0
    deepest = float(surface_z - pristine_sites[vacated, 2].min())
    return deepest, int(np.count_nonzero(vacated))


def main() -> None:
    """Run the one energy this array task owns."""
    communicator = MPI.COMM_WORLD
    rank = communicator.Get_rank()
    task_index = int(sys.argv[1])
    # The null control borrows the lowest energy so the member it builds
    # is a well-formed one; with zero impacts that energy is never used.
    is_null = task_index == NULL_TASK_INDEX
    energy = SCAN_ENERGIES_EV[0 if is_null else task_index]

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
    # Exactly one impact, whatever the cell came out to -- or none at
    # all for the null control, which the impact loop honours by simply
    # never entering (it iterates the per-impact seeds).
    fluence = 0.0 if is_null else 1.0 / area

    scratch = job_scratch(JOB_DIR) if rank == 0 else None
    scratch = communicator.bcast(scratch, root=0)
    label = "scan_null" if is_null else f"scan_e{int(energy):03d}"
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
              f"fluence {fluence:.6f} -> "
              f"{0 if is_null else 1} impact(s)", flush=True)

    started = time.perf_counter()
    result, amorphized_file = activate_one_half(
        handle, member_for(base, energy, fluence), SEED, output,
        communicator)
    elapsed = time.perf_counter() - started

    if rank == 0:
        # `activate_one_half` returns the driver's CascadeOutcome itself.
        # It carries NO gate verdict, and that is by design rather than
        # by omission: the 2026-08-08 re-arch made activation
        # cascade-only and moved the §3.5 gate into the bond flow, where
        # a per-wafer reference can be applied to an assembled pair. The
        # earlier version of this harness still reached for
        # `result.verdict` and killed all twelve tasks after their
        # cascades had already run (LEDGER T-22).
        survivors = len(ase_read(amorphized_file, parallel=False))
        reach, vacated = damage_reach(data_file, amorphized_file)
        sputtered = len(half.atoms) - survivors
        print(f"SCANRESULT energy_eV={0 if is_null else energy:.0f} "
              f"null={int(is_null)} "
              f"impacts={result.impacts_run} "
              f"atoms={len(half.atoms)} survivors={survivors} "
              f"sputtered={sputtered} "
              f"vacated_sites={vacated} "
              f"reach_depth={reach:.3f} seconds={elapsed:.0f}",
              flush=True)
        print(f"SCANNOTE energy_eV={0 if is_null else energy:.0f} "
              f"{result.note}", flush=True)


if __name__ == "__main__":
    main()
