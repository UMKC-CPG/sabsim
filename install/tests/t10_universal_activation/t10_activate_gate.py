#!/usr/bin/env python
"""T-10: first gate-PASSING universal activation (§3.5, §4.7).

Node-validation of the claim that the universal foundation MLIP
(DPA-2.4-7M) drives a cascade that AMORPHIZES a real silicon surface well
enough to clear the §3.5 activation gate — the evidence needed to flip the
model's ``validated`` flag (DESIGN §4.7). Where T-9 proved the split
PLUMBING on a toy, this runs a PRODUCTION-SIZE cascade and judges the
result:

  build a ~2880-atom Si slab (6x6x10 diamond, ~33 A wide x ~53 A thick)
    -> the FULL-fluence universal cascade (27 impacts at 75 eV,
       0.025 ions/A^2), out-of-process in the deepmd bundle on the GPU,
       recording a trajectory MOVIE of the whole bombardment
    -> read the amorphized surface back
    -> run the activation gate DIRECTLY on it (the cascade's own product,
       before any bond-flow heal) and report every metric

A PASS is the first gate-passing universal activation. The gate is an AND
over four metrics (g(r) first peak, coordination-defect band, non-six-ring
fraction, and a >=7 A amorphized depth); the slab is sized so the deep
crystalline third anchors the coordination reference and the skin can
reach the 7 A depth (the measured §3.6 anchor).

Env (slurm wrapper): SABSIM_CASCADE_ENGINE_PREFIX (the bundle),
SABSIM_CASCADE_MLIP_MODEL (the .pt2), SABSIM_ALLOW_UNVALIDATED_POTENTIAL=1,
SABSIM_TEMPLATE (study spec), VALWORK (scratch). Optional: T10_N_LATERAL /
T10_N_DEPTH (slab size), T10_TRAJ_STRIDE (movie stride).
"""

import os

import numpy as np
from ase import Atoms
from ase.io import write as ase_write

from sabsim.driver.activation_gate import (
    activation_gate,
    load_activation_references,
)
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
from sabsim.structure.slab_builder import WAFER_A_TAG

# Diamond-silicon conventional-cell basis (fractional), lattice 5.43 A.
_DIAMOND_BASIS = [
    (0, 0, 0), (0, .5, .5), (.5, 0, .5), (.5, .5, 0),
    (.25, .25, .25), (.25, .75, .75), (.75, .25, .75), (.75, .75, .25)]
_LATTICE_ANGSTROM = 5.43


def _self_log_environment() -> None:
    """Emit the env FIRST, so the log alone reconstructs the run (LEDGER)."""
    import ase
    import sabsim

    print("=== T-10 environment (self-logged) ===")
    print("python          :", os.popen("command -v python").read().strip())
    print("sabsim.__file__ :", sabsim.__file__)
    print("ase version     :", ase.__version__)
    for name in (
            "SABSIM_CASCADE_ENGINE_PREFIX", "SABSIM_CASCADE_MLIP_MODEL",
            "SABSIM_ALLOW_UNVALIDATED_POTENTIAL", "SABSIM_TEMPLATE",
            "VALWORK", "T10_N_LATERAL", "T10_N_DEPTH", "T10_TRAJ_STRIDE",
            "CUDA_VISIBLE_DEVICES"):
        print(f"  {name} = {os.environ.get(name, '(unset)')}")
    print("cascade engine prefix resolves:", resolve_cascade_engine_prefix())
    print("=======================================")


def _build_silicon_slab(n_lateral: int, n_depth: int,
                        work_directory: str) -> tuple:
    """Build a diamond-Si slab and write its cascade data file (two types).

    ``n_lateral`` sets the in-plane repeats (the free +z surface's width)
    and ``n_depth`` the number of cells into the bulk — deep enough that the
    lowest third stays crystalline to anchor the gate's coordination
    reference while the skin amorphizes. A second atom type (argon) is
    declared with a mass but no atoms so the cascade can create projectiles.
    """
    z_shift = 10.0
    positions = np.array([
        ((i + bx) * _LATTICE_ANGSTROM,
         (j + by) * _LATTICE_ANGSTROM,
         (k + bz) * _LATTICE_ANGSTROM + z_shift)
        for i in range(n_lateral) for j in range(n_lateral)
        for k in range(n_depth) for (bx, by, bz) in _DIAMOND_BASIS])
    length_x = n_lateral * _LATTICE_ANGSTROM
    length_y = n_lateral * _LATTICE_ANGSTROM
    z_high = float(positions[:, 2].max()) + 20.0
    cell = np.array([[length_x, 0.0, 0.0],
                     [0.0, length_y, 0.0],
                     [0.0, 0.0, z_high]])
    slab_atoms = Atoms(
        "Si" * len(positions), positions=positions, cell=cell,
        pbc=(True, True, False))

    data_file = os.path.join(work_directory, "slab.data")
    with open(data_file, "w", encoding="utf-8") as handle:
        handle.write(
            "Si slab\n\n%d atoms\n2 atom types\n\n"
            "0.0 %.4f xlo xhi\n0.0 %.4f ylo yhi\n0.0 %.4f zlo zhi\n\n"
            "Masses\n\n1 28.0855\n2 39.948\n\nAtoms # atomic\n\n"
            % (len(positions), length_x, length_y, z_high))
        for index, (x, y, z) in enumerate(positions):
            handle.write("%d 1 %.4f %.4f %.4f\n" % (index + 1, x, y, z))

    thickness = float(positions[:, 2].max() - positions[:, 2].min())
    from types import SimpleNamespace
    built = SimpleNamespace(atoms=slab_atoms, type_map={"Si": 1, "Ar": 2})
    return built, data_file, length_x * length_y, thickness


def _report_gate(verdict) -> None:
    """Print every metric verdict and the g(r) peaks, pass or fail."""
    print("=== activation gate ===")
    print("PASSED         :", verdict.passed)
    print("activated_depth: %.2f A" % verdict.activated_depth)
    if verdict.reason:
        print("first failure  :", verdict.reason)
    for name, metric in verdict.per_metric.items():
        print(f"  {name:20s} measured={metric.measured} "
              f"threshold={metric.threshold} passed={metric.passed}")
    gr = verdict.per_metric["radial_distribution"].detail
    if gr is not None:
        radii = np.asarray(gr.x)
        values = np.asarray(gr.y)
        top = np.argsort(values)[-5:][::-1]
        print("  g(r) top-5 (r,g):",
              [(round(float(radii[i]), 3), round(float(values[i]), 2))
               for i in top])


def main() -> None:
    """Drive T-10: full-fluence universal cascade, then gate the surface."""
    _self_log_environment()
    work_directory = os.environ["VALWORK"]
    template = os.environ["SABSIM_TEMPLATE"]
    os.makedirs(work_directory, exist_ok=True)
    n_lateral = int(os.environ.get("T10_N_LATERAL", "6"))
    n_depth = int(os.environ.get("T10_N_DEPTH", "10"))
    traj_stride = int(os.environ.get("T10_TRAJ_STRIDE", "500"))
    # The cascade seed: a distinct value gives an INDEPENDENT realization
    # (a different impact pattern), for a true A/B pair. Default reproduces
    # the first T-10 run.
    seed = int(os.environ.get("T10_SEED", "20260809"))

    member = load_and_validate_study(template).members[1]   # si-si-reference
    print("member:", member.name, "| domain:", member.material_domain)

    built, data_file, area, thickness = _build_silicon_slab(
        n_lateral, n_depth, work_directory)
    print(f"slab: {len(built.atoms)} atoms | {n_lateral}x{n_lateral}x"
          f"{n_depth} | area {area:.0f} A^2 | thickness {thickness:.1f} A")

    # FULL fluence — no shrink; this is the whole point of T-10.
    spec = derive_bombardment_spec(built, member)
    print(f"cascade: {spec.impact_count} impacts of {spec.projectile_symbol} "
          f"at {spec.impact_energy:.0f} eV | dose "
          f"{spec.impact_count / area:.4f} ions/A^2")

    projectile_species = _projectile_species(member)
    projectile_types = [built.type_map[symbol] for symbol in projectile_species
                        if symbol in built.type_map]
    cascade_force_model = resolve_cascade_generator(
        built.type_map, projectile_species, allow_unvalidated=True,
        domain=member.material_domain, use_classical=False)
    print("cascade pair_style:", cascade_force_model.pair_style)

    dump_path = os.path.join(work_directory, "activated.dump")
    movie_path = os.path.join(work_directory, "cascade_movie.dump")
    script = build_activate_script(
        built, member, cascade_force_model, data_file, spec, seed=seed,
        projectile_types=projectile_types, output_structure_file=dump_path,
        geometry=CascadeGeometry(),
        trajectory_file=movie_path, trajectory_stride=traj_stride)
    print("script lines:", len(script), "| trajectory stride:", traj_stride)

    run_activate_subprocess(
        script, work_directory, dump_path,
        script_name="activate.in", log_name="log.activate")
    print("cascade movie written:", movie_path)

    positions, type_ids = read_dump_structure(dump_path)
    print("readback atoms:", len(positions),
          "| surviving types:", sorted({int(t) for t in type_ids}))

    # Save the amorphized surface for the record and any later bond run.
    amorphized = amorphized_half_from_arrays(
        positions, type_ids, built.atoms.get_cell(), built.type_map,
        WAFER_A_TAG)
    ase_write(os.path.join(work_directory, "activated.extxyz"), amorphized,
              format="extxyz", parallel=False)

    references = load_activation_references(frozenset({"Si"}))
    verdict = activation_gate(positions, built.atoms.get_cell(), references)
    _report_gate(verdict)

    if verdict.passed:
        print("T10 GATE PASSED — first gate-passing universal activation")
    else:
        print("T10 GATE FAILED — see the first failure above")
    print("T10 UNIVERSAL ACTIVATION RUN COMPLETE")


if __name__ == "__main__":
    main()
