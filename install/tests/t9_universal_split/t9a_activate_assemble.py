#!/usr/bin/env python
"""T-9a: universal cascade-only activate (GPU) + wide-gap assemble.

Node-validation Job A of the re-architected activate->bond split
(DESIGN.md §3.4/§3.5/§4.7). It exercises the GENUINELY NEW seams on a real
V100, end to end:

  build a small Si slab
    -> cascade-ONLY ``build_activate_script`` (NO re-anneal, NO gate:
       the re-anneal and the §3.5 gate MOVED to the bond flow, Job B)
    -> ``run_activate_subprocess`` (the deepmd bundle's ``lmp``, the
       universal DPA-2.4-7M model + ZBL, out-of-process on the GPU)
    -> ``read_dump_structure`` -> ``amorphized_half_from_arrays``
  for BOTH wafers (A, and B — assembled flips B face-down)
    -> ``assemble_amorphized_pair`` at the WIDE gap (> the bond flow's
       6 Angstrom separation cutoff, so each surface healed as free)

It writes the assembled pair for Job B: the ``BuiltPair`` (pickled) and a
LAMMPS data file. This is the substrate-only, cascade-only activate the
re-architecture introduced — the projectile is stripped as cascade
cleanup, so the handoff carries silicon only. One impact and a capped
cascade keep the GPU time small; this checks the PLUMBING and the wide-gap
handoff, not converged physics.

Env (set by the slurm wrapper): SABSIM_CASCADE_ENGINE_PREFIX (the deepmd
bundle), SABSIM_CASCADE_MLIP_MODEL (the .pt2 universal model),
SABSIM_ALLOW_UNVALIDATED_POTENTIAL=1 (DPA-2.4-7M has not cleared the gate
yet), SABSIM_TEMPLATE (the study spec), VALWORK (the shared scratch dir
Job A writes and Job B reads).
"""

import dataclasses
import os
import pickle
from types import SimpleNamespace

import numpy as np
from ase import Atoms

from sabsim.driver.cascade import (
    CascadeControl,
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
from sabsim.driver.commands import CascadeGeometry, to_metal
from sabsim.spec.loader import load_and_validate_study
from sabsim.structure.amorphized_assembly import (
    amorphized_half_from_arrays,
    assemble_amorphized_pair,
)
from sabsim.structure.slab_builder import (
    WAFER_A_TAG,
    WAFER_B_TAG,
    SurfaceMatch,
    write_lammps_data,
)

# The connectivity cutoff the assembler drops sputtered ejecta by (Angstrom,
# the Si first-g(r)-minimum stand-in the live pipeline uses, live_stages.py).
BOND_CUTOFF_ANGSTROM = 2.8


def _self_log_environment() -> None:
    """Emit the env FIRST, so the log alone reconstructs what ran (LEDGER).

    Job A drives NO in-process LAMMPS (the cascade runs in the isolated
    bundle subprocess), so the relevant facts are the driver Python, the
    two out-of-process engine knobs, and the versions sabsim built with.
    """
    import ase
    import sabsim

    print("=== T-9a environment (self-logged) ===")
    print("python          :", os.popen("command -v python").read().strip())
    print("sabsim.__file__ :", sabsim.__file__)
    print("ase version     :", ase.__version__)
    for name in (
            "SABSIM_CASCADE_ENGINE_PREFIX", "SABSIM_CASCADE_MLIP_MODEL",
            "SABSIM_ALLOW_UNVALIDATED_POTENTIAL", "SABSIM_TEMPLATE",
            "VALWORK", "CUDA_VISIBLE_DEVICES"):
        print(f"  {name} = {os.environ.get(name, '(unset)')}")
    print("cascade engine prefix resolves:", resolve_cascade_engine_prefix())
    print("=======================================")


def _build_small_silicon_slab(work_directory: str) -> tuple:
    """Build a small diamond-Si slab and write its cascade data file.

    A 2x2 lateral by 4-deep diamond cell, lifted off ``zlo`` with vacuum on
    both z faces so the +z surface is free for the beam, and a second atom
    type declared (argon) so the cascade's ``create_atoms`` can spawn the
    projectile. Returns the ``built`` stand-in (atoms + type map), the data
    file path, and the lateral cell area the assembler's match records.
    """
    lattice_constant = 5.43
    n_lateral = 2
    n_depth = 4
    diamond_basis = [
        (0, 0, 0), (0, .5, .5), (.5, 0, .5), (.5, .5, 0),
        (.25, .25, .25), (.25, .75, .75), (.75, .25, .75), (.75, .75, .25)]
    z_shift = 10.0
    positions = np.array([
        ((i + bx) * lattice_constant,
         (j + by) * lattice_constant,
         (k + bz) * lattice_constant + z_shift)
        for i in range(n_lateral) for j in range(n_lateral)
        for k in range(n_depth) for (bx, by, bz) in diamond_basis])
    length_x = n_lateral * lattice_constant
    length_y = n_lateral * lattice_constant
    z_high = float(positions[:, 2].max()) + 20.0
    cell = np.array([[length_x, 0.0, 0.0],
                     [0.0, length_y, 0.0],
                     [0.0, 0.0, z_high]])
    slab_atoms = Atoms(
        "Si" * len(positions), positions=positions, cell=cell,
        pbc=(True, True, False))
    built = SimpleNamespace(atoms=slab_atoms, type_map={"Si": 1, "Ar": 2})

    data_file = os.path.join(work_directory, "half.data")
    with open(data_file, "w", encoding="utf-8") as handle:
        handle.write(
            "Si slab\n\n%d atoms\n2 atom types\n\n"
            "0.0 %.4f xlo xhi\n0.0 %.4f ylo yhi\n0.0 %.4f zlo zhi\n\n"
            "Masses\n\n1 28.0855\n2 39.948\n\nAtoms # atomic\n\n"
            % (len(positions), length_x, length_y, z_high))
        for index, (x, y, z) in enumerate(positions):
            handle.write("%d 1 %.4f %.4f %.4f\n" % (index + 1, x, y, z))
    lateral_area = length_x * length_y
    return built, data_file, lateral_area


def _activate_one_half(built, member, data_file, seed, wafer_tag,
                       work_directory) -> Atoms:
    """Run one cascade-only activate through the bundle subprocess.

    Emits the cascade-ONLY script (no re-anneal, no gate), runs it in the
    isolated bundle ``lmp`` on the GPU, reads the amorphized structure back
    from the dump, and wraps it as a tagged, substrate-only half. The
    projectile has already been stripped as cascade cleanup, so the
    read-back is silicon only.
    """
    projectile_species = _projectile_species(member)
    projectile_types = [built.type_map[symbol] for symbol in projectile_species
                        if symbol in built.type_map]
    cascade_force_model = resolve_cascade_generator(
        built.type_map, projectile_species, allow_unvalidated=True,
        domain=member.material_domain, use_classical=False)

    # One impact and a small step cap keep the GPU time short — the seam,
    # not the fluence, is under test.
    spec = derive_bombardment_spec(built, member)
    spec = dataclasses.replace(
        spec, impact_seeds=spec.impact_seeds[:1], impact_count=1)
    control = CascadeControl(cascade_step_cap=300)

    role = "a" if wafer_tag == WAFER_A_TAG else "b"
    dump_path = os.path.join(work_directory, f"activated_{role}.dump")
    script = build_activate_script(
        built, member, cascade_force_model, data_file, spec, seed,
        projectile_types, dump_path, CascadeGeometry(), control)
    print(f"[half {role}] cascade pair_style: {cascade_force_model.pair_style}")
    print(f"[half {role}] script lines: {len(script)}  seed: {seed}")

    run_activate_subprocess(
        script, work_directory, dump_path,
        script_name=f"activate_{role}.in", log_name=f"log.activate_{role}")

    positions, type_ids = read_dump_structure(dump_path)
    surviving_types = sorted({int(t) for t in type_ids})
    print(f"[half {role}] readback atoms: {len(positions)}  "
          f"surviving types: {surviving_types}")
    return amorphized_half_from_arrays(
        positions, type_ids, built.atoms.get_cell(), built.type_map,
        wafer_tag)


def main() -> None:
    """Drive Job A: activate both halves, assemble wide, persist the pair."""
    _self_log_environment()
    work_directory = os.environ["VALWORK"]
    template = os.environ["SABSIM_TEMPLATE"]
    os.makedirs(work_directory, exist_ok=True)

    # si-si-reference (members[1]): the diamond-cubic Si null test, the
    # cleanest single-species case for a plumbing validation.
    member = load_and_validate_study(template).members[1]
    print("member:", member.name, "| domain:", member.material_domain)

    built, data_file, lateral_area = _build_small_silicon_slab(work_directory)

    # Two DISTINCT seeds so the two halves are independent realizations.
    half_a = _activate_one_half(
        built, member, data_file, 12345, WAFER_A_TAG, work_directory)
    half_b = _activate_one_half(
        built, member, data_file, 67890, WAFER_B_TAG, work_directory)

    # Assemble at the WIDE gap. The match is an identity (both halves share
    # the same lateral cell), so there is no registry search — an
    # amorphous-amorphous contact has none (STRUCTURAL 4).
    match = SurfaceMatch(
        residual_strain=0.0, match_area=lateral_area, is_identity=True)
    clash_floor = to_metal(member.numerical.clash_floor, "distance")
    initial_gap = to_metal(member.protocol.initial_gap, "distance")
    built_pair = assemble_amorphized_pair(
        half_a, half_b, match, bond_cutoff=BOND_CUTOFF_ANGSTROM,
        initial_gap=initial_gap, clash_floor=clash_floor)

    _, lower_high = built_pair.wafer_a_z_range
    upper_low, _ = built_pair.wafer_b_z_range
    assembled_gap = float(upper_low - lower_high)
    print(f"assembled pair atoms: {len(built_pair.atoms)}  "
          f"closest-atom gap: {assembled_gap:.3f} A")
    # The whole point of the wide gap: it must clear the 6 A bond-flow
    # separation cutoff so each surface heals as a genuine free surface.
    assert assembled_gap > 6.0, (
        f"assembled gap {assembled_gap:.3f} A does NOT clear the 6 A "
        f"separation cutoff — the surfaces would not heal as free")

    data_out = os.path.join(work_directory, "assembled_pair.data")
    write_lammps_data(built_pair, data_out)
    pickle_out = os.path.join(work_directory, "built_pair.pkl")
    with open(pickle_out, "wb") as handle:
        pickle.dump(built_pair, handle)
    print("wrote:", data_out)
    print("wrote:", pickle_out)
    print("T9A ACTIVATE+ASSEMBLE OK")


if __name__ == "__main__":
    main()
