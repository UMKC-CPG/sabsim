"""Collection 2 — harvest the hard configurations from a member run.

The bootstrap runs NO cascade and NO press of its own (PSEUDOCODE §11.3):
it reads the trajectories an ordinary member job recorded when run with
``sabsim run --dump-visuals`` under the universal model, and takes from
them the five families the protocol visits — the amorphized surface
(family 7, from the activate dumps), the initial, relaxed and pressed
joint cells (8–10, from the press dump), and the pulled cell through
failure (11, from the pull dumps). Interface frames are cut to the
labelling sub-cell of :mod:`sabsim.bootstrap.subcell`.

Two lean choices are made here and named. The press record is split
into thirds by frame index to stand for "initial / relaxed / pressed"
— the press dump opens after the heal and the scissor, so its early
frames are the freshly closed contact and its late frames the loaded
one; a chunk-keyed split can replace this once the press ledger is
written to the handoff. And any argon still present in an activate
frame is dropped, because the labelling model's species union does not
contain the projectile (§3.4): the frames after the cascade cleanup are
argon-free anyway, and earlier ones become substrate-only snapshots.
"""

from __future__ import annotations

import glob
import os
from pathlib import Path

import numpy as np
from ase import Atoms
from ase.io import read as ase_read

from sabsim.bootstrap.recipe import ForceModelRecipe
from sabsim.bootstrap.subcell import (
    atomic_layer_spacing,
    cut_interface_subcell,
)
from sabsim.deploy.scratch import member_scratch
from sabsim.driver.commands import stage_dump_file, to_metal
from sabsim.pipeline.handoff import read_assembled_pair
from sabsim.spec.loader import load_and_validate_study


def _evenly(frames: list, count: int) -> list:
    """``count`` frames spread evenly along ``frames`` (all if fewer)."""
    if len(frames) <= count:
        return list(frames)
    picks = np.linspace(0, len(frames) - 1, count)
    return [frames[int(round(pick))] for pick in picks]


def _read_dump(path: str, type_map: dict) -> list:
    """A custom dump's frames as Atoms with real element symbols."""
    if not os.path.isfile(path):
        return []
    frames = ase_read(path, format="lammps-dump-text", index=":",
                      parallel=False)
    if isinstance(frames, Atoms):
        frames = [frames]
    by_id = {type_id: symbol for symbol, type_id in type_map.items()}
    for frame in frames:
        type_ids = (frame.arrays["type"] if "type" in frame.arrays
                    else frame.get_atomic_numbers())
        frame.set_chemical_symbols([by_id[int(t)] for t in type_ids])
    return frames


def _without_species(atoms: Atoms, species: set) -> Atoms:
    keep = np.array([symbol not in species
                     for symbol in atoms.get_chemical_symbols()])
    return atoms[keep]


def harvest_collection2(recipe: ForceModelRecipe) -> list:
    """Read the member run named by the plan; return ``(family, source,
    Atoms)`` triples for families 7–11.

    Raises :class:`FileNotFoundError` naming the missing dump when the
    member was not run with ``--dump-visuals``: a silent empty harvest
    would look like a labelled-but-empty collection.
    """
    plan = recipe.generation_plan
    study = load_and_validate_study(plan.study)
    member = next(
        (m for m in study.members if m.name == plan.member), None)
    if member is None:
        raise KeyError(
            f"[generation_plan] member '{plan.member}' is not in "
            f"{plan.study}")
    scratch = member_scratch(plan.job_directory, study.name, member.name)
    structure = read_assembled_pair(scratch)
    built = structure.built
    type_map = dict(built.type_map)
    projectile = {member.protocol.activation_species}
    tags = np.asarray(built.atoms.get_tags())
    # The working lattice constant: the assembled cell's x edge is a whole
    # number of conventional cells, and the CIF's published constant says
    # how many (the derived and published constants differ by ~1 %, far
    # less than one cell), so the ratio rounds to that repeat exactly.
    from sabsim.spec.references import resolve_crystal_file
    from sabsim.structure.slab_builder import load_crystal
    published = float(load_crystal(resolve_crystal_file(
        member.material.wafer_a.cif_source)).lattice.a)
    edge = float(np.linalg.norm(np.asarray(built.atoms.get_cell())[0]))
    lattice_constant = edge / max(1.0, round(edge / published))
    skin_depth = to_metal(member.numerical.expected_activated_depth,
                          "distance")
    layer = atomic_layer_spacing(
        lattice_constant, member.material.wafer_a.surface_face)
    vacuum = to_metal(plan.subcell_vacuum, "distance")

    def subcell(frame: Atoms) -> Atoms:
        return cut_interface_subcell(
            frame, tags, float(built.interface_z), skin_depth, layer,
            plan.subcell_crystalline_layers, vacuum)

    structures = []
    # Family 7 — the activated surfaces, one dump per half. The half's
    # own type map includes the projectile; the assembled map does too.
    for role in ("a", "b"):
        dump = stage_dump_file(str(scratch), member.name, f"activate_{role}")
        frames = _read_dump(dump, type_map)
        if not frames:
            raise FileNotFoundError(
                f"no activate dump for half {role} at {dump}: run the "
                f"member with --dump-visuals first")
        for index, frame in enumerate(
                _evenly(frames, plan.frames_per_stage["activate"])):
            structures.append((
                "activated_surface", f"{member.name}:activate_{role}:{index}",
                _without_species(frame, projectile)))
    # Families 8–10 — the press record in thirds (see the module note).
    press_frames = _read_dump(
        stage_dump_file(str(scratch), member.name, "press"), type_map)
    if not press_frames:
        raise FileNotFoundError(
            f"no press dump under {scratch}: run the bond job with "
            f"--dump-visuals first")
    thirds = np.array_split(
        np.arange(len(press_frames)), 3)
    for family, indices in zip(
            ("joint_initial", "joint_relaxed", "joint_pressed"), thirds):
        chosen = _evenly([press_frames[i] for i in indices],
                         max(1, plan.frames_per_stage["press"] // 3))
        for index, frame in enumerate(chosen):
            structures.append((
                family, f"{member.name}:press:{family}:{index}",
                subcell(frame)))
    # Family 11 — every pull rung's record, through separation.
    pull_dumps = sorted(glob.glob(
        os.path.join(str(scratch), "pull_*", f"{member.name}_pull.dump")))
    for dump in pull_dumps:
        rung = Path(dump).parent.name
        frames = _read_dump(dump, type_map)
        for index, frame in enumerate(
                _evenly(frames, plan.frames_per_stage["pull"])):
            structures.append((
                "pulled", f"{member.name}:{rung}:{index}", subcell(frame)))
    return structures
