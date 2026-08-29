"""Collection 1 — the six calm families, built from the recipe (§4.8).

These are the structures computed BEFORE anything else, so that the
first committee does not fly apart near equilibrium. Four of the six
families are static geometry (the bulk ground state, the strain sweep,
the rattled snapshots, the clean surfaces) and need no simulation; two
(the bulk melt-quench and the warm runs) are short molecular-dynamics
runs under the universal generator model, run OUT-OF-PROCESS in the
deepmd bundle exactly as the cascade is (ARCHITECTURE §4.4), with a
strided dump the harvester reads back.

Every family starts from the lattice the generator model itself relaxes
the crystal to (the §2.2 discipline): a cell built on the CIF's
published scale would be strained at step zero under the model, and
that strain would be taught to the committee as if it were physics.

Each function returns a list of ``(family, source, Atoms)`` triples —
the shape the labeller selects from — and writes nothing itself except
the LAMMPS inputs and dumps of the two dynamic families.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from ase import Atoms
from ase.io import read as ase_read

from sabsim.bootstrap.recipe import (
    ForceModelRecipe,
    QuenchSpec,
    WarmRunSpec,
)
from sabsim.driver.bulk_relax import (
    bulk_relax_subprocess_script,
    conventional_cell,
    cubic_lattice_constant,
    read_data_box,
)
from sabsim.driver.cascade_potential import universal_force_model
from sabsim.driver.cascade_subprocess import run_activate_subprocess
from sabsim.driver.environment_library import (
    build_environment_library,
    write_environment_library,
)
from sabsim.driver.commands import ForceModel, force_model_commands, to_metal
from sabsim.spec.references import resolve_crystal_file
from sabsim.structure.slab_builder import (
    build_slab,
    bulk_atoms,
    bulk_type_map,
    load_crystal,
    rescale_crystal_to_cell,
    write_bulk_data,
)

# How many frames the dumps of the dynamic families keep at most, so a
# long warm run does not write thousands of near-duplicate frames the
# labeller would only stride over anyway.
_DUMP_FRAME_CAP = 200


def _symbols_from_types(type_ids, type_map: dict) -> list:
    """LAMMPS type ids -> element symbols, by the data file's map."""
    by_id = {type_id: symbol for symbol, type_id in type_map.items()}
    return [by_id[int(type_id)] for type_id in type_ids]


def _read_dump_frames(dump_path: str, type_map: dict) -> list:
    """Every frame of a custom dump as ASE Atoms with real symbols."""
    frames = ase_read(dump_path, format="lammps-dump-text", index=":",
                      parallel=False)
    if isinstance(frames, Atoms):
        frames = [frames]
    for frame in frames:
        frame.set_chemical_symbols(
            _symbols_from_types(frame.get_atomic_numbers(), type_map)
            if "type" not in frame.arrays
            else _symbols_from_types(frame.arrays["type"], type_map))
        frame.set_pbc([True, True, True])
    return frames


def _generator_model(recipe: ForceModelRecipe, type_map: dict) -> ForceModel:
    """The universal model alone (no ZBL) for the calm dynamics."""
    return universal_force_model(
        type_map, recipe.generator.weights,
        allow_unvalidated=recipe.generator.allow_unvalidated,
        model_name=recipe.generator.model)


# ---------------------------------------------------------------------
# The working lattice of every phase, derived under the generator.
# ---------------------------------------------------------------------

def derive_phase_lattices(
        recipe: ForceModelRecipe, work_dir: Path) -> dict:
    """Relax each phase's bulk cell under the generator model (§2.2).

    Returns ``phase name -> (rescaled crystal, lattice constant)``; the
    rescaled crystal is what every family is built from. Runs one
    out-of-process box relax per phase, exactly as the study pipeline's
    lattice derivation does.
    """
    cells = recipe.starting_collection.bulk.cells_per_axis
    lattices = {}
    for phase in recipe.phases:
        crystal = load_crystal(resolve_crystal_file(phase.cif))
        type_map = bulk_type_map(crystal, cells)
        phase_dir = work_dir / "lattice" / phase.name
        phase_dir.mkdir(parents=True, exist_ok=True)
        bulk_file = str(phase_dir / "bulk.data")
        relaxed_file = str(phase_dir / "relaxed_bulk.data")
        write_bulk_data(crystal, cells, bulk_file)
        script = bulk_relax_subprocess_script(
            bulk_file, _generator_model(recipe, type_map), relaxed_file)
        run_activate_subprocess(
            script, str(phase_dir), relaxed_file,
            script_name="derive.in", log_name="log.derive")
        relaxed_block_cell, _ = read_data_box(relaxed_file)
        derived = conventional_cell(relaxed_block_cell, cells)
        rescaled = rescale_crystal_to_cell(crystal, derived)
        lattices[phase.name] = (
            rescaled, cubic_lattice_constant(relaxed_block_cell, cells))
    return lattices


# ---------------------------------------------------------------------
# The four static families.
# ---------------------------------------------------------------------

def bulk_family(recipe: ForceModelRecipe, lattices: dict) -> list:
    """Family 1 — each phase's perfect crystal at its derived lattice."""
    cells = recipe.starting_collection.bulk.cells_per_axis
    return [
        ("bulk", f"{phase.name}", bulk_atoms(lattices[phase.name][0], cells))
        for phase in recipe.phases]


def _deformation(mode: str, magnitude: float) -> np.ndarray:
    """The 3x3 deformation gradient for one mode and magnitude."""
    gradient = np.eye(3)
    if mode == "volumetric":
        gradient *= 1.0 + magnitude
    elif mode == "uniaxial_z":
        gradient[2, 2] = 1.0 + magnitude
    elif mode == "shear_xy":
        gradient[0, 1] = magnitude       # x picks up a component along y
    else:
        raise ValueError(
            f"strain mode '{mode}' is not one of volumetric, uniaxial_z, "
            f"shear_xy")
    return gradient


def strain_family(recipe: ForceModelRecipe, lattices: dict) -> list:
    """Family 2 — the bulk cell under every (mode, magnitude) pair.

    The deformation is applied to the cell and the atoms scale with it
    (the whole crystal is stretched, not the box around fixed atoms), so
    each structure is the affinely deformed lattice — the reference the
    §7.2 stiffness gate needs and the regime the press and pull visit.
    """
    spec = recipe.starting_collection.strain
    structures = []
    for family_entry in bulk_family(recipe, lattices):
        _, phase_name, relaxed = family_entry
        for mode in spec.modes:
            for magnitude in spec.magnitudes:
                deformed = relaxed.copy()
                gradient = _deformation(mode, magnitude)
                deformed.set_cell(
                    np.asarray(relaxed.get_cell()) @ gradient.T,
                    scale_atoms=True)
                structures.append((
                    "strain", f"{phase_name}:{mode}:{magnitude:+.3f}",
                    deformed))
    return structures


def rattle_family(recipe: ForceModelRecipe, lattices: dict) -> list:
    """Family 5 — seeded Gaussian kicks about the cold bulk cell."""
    spec = recipe.starting_collection.rattle
    amplitude = to_metal(spec.amplitude, "distance")
    rng = np.random.default_rng(spec.seed)
    structures = []
    for _, phase_name, relaxed in bulk_family(recipe, lattices):
        for index in range(spec.count):
            shaken = relaxed.copy()
            shaken.set_positions(
                shaken.get_positions()
                + rng.normal(0.0, amplitude, size=(len(shaken), 3)))
            structures.append(("rattle", f"{phase_name}:{index}", shaken))
    return structures


def surface_family(recipe: ForceModelRecipe, lattices: dict) -> list:
    """Family 4 — each declared clean face, cut by the §7 slab builder."""
    structures = []
    for surface in recipe.starting_collection.surfaces:
        crystal, _ = lattices[surface.phase]
        slab = build_slab(
            crystal, surface.face,
            min_slab_thickness=to_metal(surface.slab_thickness, "distance"),
            min_vacuum=to_metal(surface.vacuum, "distance"),
            termination_index=surface.termination_index)
        repeat = max(1, surface.lateral_repeat)
        slab = slab * (repeat, repeat, 1)
        face = "".join(str(component) for component in surface.face)
        structures.append(("surface", f"{surface.phase}:({face})", slab))
    return structures


# ---------------------------------------------------------------------
# The two dynamic families, as out-of-process LAMMPS scripts.
# ---------------------------------------------------------------------

def _dynamics_preamble(data_file: str, model: ForceModel,
                       timestep_ps: float) -> list:
    lines = [
        "units metal",
        "atom_style atomic",
        "boundary p p p",
    ]
    if model.needs_atom_map:
        lines.insert(2, "atom_modify map yes")
    lines += [
        f"read_data {data_file}",
        *force_model_commands(model),
        f"timestep {timestep_ps:g}",
        "thermo 100",
    ]
    return lines


def melt_quench_script(
        spec: QuenchSpec, data_file: str, model: ForceModel,
        timestep_ps: float, dump_file: str, seed: int) -> list:
    """Melt far above melting, hold, then quench at the stated rate.

    The quench is a linear temperature ramp under a Nosé–Hoover
    thermostat at fixed volume; ``spec.frames`` frames are dumped evenly
    across it, so the label set samples the network as it freezes rather
    than only its end point. The melt itself is verified by the caller
    (PSEUDOCODE §11.1: a melt that stayed crystalline is wrong data).
    """
    melt_kelvin = to_metal(spec.melt_temperature, "temperature")
    final_kelvin = to_metal(spec.final_temperature, "temperature")
    melt_steps = max(1, round(
        to_metal(spec.melt_duration, "time") / timestep_ps))
    quench_ps = (melt_kelvin - final_kelvin) / spec.quench_rate.value
    quench_steps = max(1, round(quench_ps / timestep_ps))
    stride = max(1, quench_steps // max(1, spec.frames))
    damping = 100.0 * timestep_ps
    return [
        *_dynamics_preamble(data_file, model, timestep_ps),
        f"velocity all create {melt_kelvin:g} {seed} dist gaussian",
        f"fix melt all nvt temp {melt_kelvin:g} {melt_kelvin:g} "
        f"{damping:g}",
        f"run {melt_steps}",
        "unfix melt",
        f"dump frames all custom {stride} {dump_file} id type x y z",
        "dump_modify frames sort id",
        f"fix quench all nvt temp {melt_kelvin:g} {final_kelvin:g} "
        f"{damping:g}",
        f"run {quench_steps}",
        f"write_data {dump_file}.final.data nocoeff",
    ]


def warm_run_script(
        spec: WarmRunSpec, data_file: str, model: ForceModel,
        timestep_ps: float, dump_file: str, seed: int) -> list:
    """A short NVT or NPT run; frames start after the equilibration."""
    kelvin = to_metal(spec.temperature, "temperature")
    total_steps = max(1, round(
        to_metal(spec.duration, "time") / timestep_ps))
    settle_steps = max(1, round(
        to_metal(spec.equilibration, "time") / timestep_ps))
    stride = max(1, round(
        to_metal(spec.sampling_stride, "time") / timestep_ps))
    damping = 100.0 * timestep_ps
    if spec.ensemble == "NPT":
        integrator = (f"fix warm all npt temp {kelvin:g} {kelvin:g} "
                      f"{damping:g} iso 0.0 0.0 {10.0 * damping:g}")
    else:
        integrator = f"fix warm all nvt temp {kelvin:g} {kelvin:g} {damping:g}"
    return [
        *_dynamics_preamble(data_file, model, timestep_ps),
        f"velocity all create {kelvin:g} {seed} dist gaussian",
        integrator,
        f"run {settle_steps}",
        f"dump frames all custom {stride} {dump_file} id type x y z",
        "dump_modify frames sort id",
        f"run {max(1, total_steps - settle_steps)}",
        f"write_data {dump_file}.final.data nocoeff",
    ]


def _run_dynamic(
        recipe: ForceModelRecipe, lattices: dict, phase_name: str,
        cells: int, script_builder, spec, family: str, replica: int,
        work_dir: Path) -> list:
    """Write the data file and script, run the bundle, read the frames."""
    crystal, _ = lattices[phase_name]
    run_dir = work_dir / family / f"{phase_name}_{replica}"
    run_dir.mkdir(parents=True, exist_ok=True)
    data_file = str(run_dir / "start.data")
    type_map = write_bulk_data(crystal, cells, data_file)
    dump_file = str(run_dir / "frames.dump")
    timestep_ps = to_metal(recipe.generator.md_timestep, "time")
    script = script_builder(
        spec, data_file, _generator_model(recipe, type_map), timestep_ps,
        dump_file, spec.seed + replica)
    run_activate_subprocess(
        script, str(run_dir), f"{dump_file}.final.data",
        script_name=f"{family}.in", log_name=f"log.{family}")
    frames = _read_dump_frames(dump_file, type_map)[-_DUMP_FRAME_CAP:]
    return [(family, f"{phase_name}:{replica}:{index}", frame)
            for index, frame in enumerate(frames)]


def melt_quench_family(
        recipe: ForceModelRecipe, lattices: dict, work_dir: Path) -> list:
    """Family 3 — every declared melt-quench, every replica."""
    structures = []
    for spec in recipe.starting_collection.melt_quench:
        for replica in range(spec.replicas):
            structures += _run_dynamic(
                recipe, lattices, spec.phase, spec.cells_per_axis,
                melt_quench_script, spec, "melt_quench", replica, work_dir)
    return structures


def warm_run_family(
        recipe: ForceModelRecipe, lattices: dict, work_dir: Path) -> list:
    """Family 6 — every declared warm run, every replica."""
    cells = recipe.starting_collection.bulk.cells_per_axis
    structures = []
    for spec in recipe.starting_collection.warm_runs:
        for replica in range(spec.replicas):
            structures += _run_dynamic(
                recipe, lattices, spec.phase, cells, warm_run_script, spec,
                f"warm_{spec.ensemble.lower()}", replica, work_dir)
    return structures


def build_collection1(recipe: ForceModelRecipe, work_dir: Path) -> tuple:
    """All six families, in order, AND the environment library.

    Returns ``(structures, library_manifest_path)``: the ``(family,
    source, Atoms)`` triples, and the path of the library's TOML
    sidecar. The same six families also yield the ENVIRONMENT LIBRARY
    the §3.5 gate judges against (DESIGN §4.8 part 2, 2026-08-29): the
    cold bulk, the clean surfaces and the warm runs are catalogued, the
    melt-quench family is the self-check, and the pair of files
    (``environment_library.npz`` + ``.toml``) is written beside the
    collection under ``work_dir`` (PSEUDOCODE §11.2/§11.3).
    """
    lattices = derive_phase_lattices(recipe, work_dir)
    structures = []
    structures += bulk_family(recipe, lattices)
    structures += strain_family(recipe, lattices)
    structures += melt_quench_family(recipe, lattices, work_dir)
    structures += surface_family(recipe, lattices)
    structures += rattle_family(recipe, lattices)
    structures += warm_run_family(recipe, lattices, work_dir)
    library = build_environment_library(
        structures, recipe, Path(work_dir) / "descriptors")
    manifest_path = write_environment_library(library, work_dir)
    return structures, manifest_path
