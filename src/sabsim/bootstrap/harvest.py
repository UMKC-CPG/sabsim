"""Collection 2 — harvest the hard configurations from a member run.

The bootstrap runs NO cascade and NO press of its own (PSEUDOCODE §11.3):
it reads the trajectories an ordinary member job recorded when run with
trajectories on under the universal model, and takes from them the five
families the protocol visits (DESIGN §4.8 part 5, revised 2026-08-28):

* family 7, the HEALED activated surface — the tail of each half's
  activate movie, from the step its heal began (the ``heal_start_step``
  marker the session wrote, carried on the assembled-pair manifest);
* family 8, the pair at press start — the press-movie frame AT the
  ledger's ``press_start``;
* family 9, the settled zero-load reference — the frames between the
  ledger's ``settle_start`` and ``settle_end`` (§5.3);
* family 10, the pair under compression — the frames between
  ``press_start`` and ``hold_end``;
* family 11, the pulled cell through failure — every pull rung's movie.

Every frame is keyed to its phase by the MD step it carries and the
StageLedger the bond job wrote into its manifest (PSEUDOCODE §9.3) —
never by its position in the file. Interface frames (8–11) are cut to
the labelling sub-cell of :mod:`sabsim.bootstrap.subcell`.

Any projectile atom still present in an activate frame is dropped,
because the labelling model's species union does not contain the beam
(§3.4); the healed frames are projectile-free anyway.
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
from sabsim.pipeline.handoff import read_assembled_pair, read_pull_results
from sabsim.spec.loader import load_and_validate_study


def _evenly(frames: list, count: int) -> list:
    """``count`` frames spread evenly along ``frames`` (all if fewer)."""
    if len(frames) <= count:
        return list(frames)
    picks = np.linspace(0, len(frames) - 1, count)
    return [frames[int(round(pick))] for pick in picks]


def _dump_steps(path: str) -> list:
    """The MD step of every frame in a LAMMPS dump, in file order.

    Read straight from the ``ITEM: TIMESTEP`` headers, because that step
    is the key the StageLedger speaks in; ASE's reader does not keep it.
    """
    steps = []
    with open(path, encoding="utf-8") as dump:
        take_next = False
        for line in dump:
            if take_next:
                steps.append(int(line.split()[0]))
                take_next = False
            elif line.startswith("ITEM: TIMESTEP"):
                take_next = True
    return steps


def _read_dump(path: str, type_map: dict) -> list:
    """A custom dump's frames as Atoms with real element symbols, each
    carrying its MD step in ``atoms.info["step"]``."""
    if not os.path.isfile(path):
        return []
    frames = ase_read(path, format="lammps-dump-text", index=":",
                      parallel=False)
    if isinstance(frames, Atoms):
        frames = [frames]
    by_id = {type_id: symbol for symbol, type_id in type_map.items()}
    steps = _dump_steps(path)
    for frame, step in zip(frames, steps):
        type_ids = (frame.arrays["type"] if "type" in frame.arrays
                    else frame.get_atomic_numbers())
        frame.set_chemical_symbols([by_id[int(t)] for t in type_ids])
        frame.info["step"] = step
    return frames


def frames_between(frames: list, first: int | None,
                   last: int | None) -> list:
    """The frames whose step lies in ``[first, last]`` (inclusive).

    A None bound is open on that side. Frames without a recorded step are
    never selected: an unkeyed frame cannot be assigned to a phase.
    """
    chosen = []
    for frame in frames:
        step = frame.info.get("step")
        if step is None:
            continue
        if first is not None and step < first:
            continue
        if last is not None and step > last:
            continue
        chosen.append(frame)
    return chosen


def frame_at(frames: list, step: int | None) -> list:
    """The first frame recorded AT or after ``step`` (a one-element list),
    or nothing when there is no such frame or no step to look for."""
    if step is None:
        return []
    later = frames_between(frames, step, None)
    return later[:1]


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
    # Family 7 — the HEALED activated surfaces: each half's movie from
    # the step its heal began (the session's marker, on the manifest).
    heal_steps = {"a": structure.heal_start_step_a,
                  "b": structure.heal_start_step_b}
    for role in ("a", "b"):
        dump = stage_dump_file(str(scratch), member.name, f"activate_{role}")
        frames = _read_dump(dump, type_map)
        if not frames:
            raise FileNotFoundError(
                f"no activate dump for half {role} at {dump}: run the "
                f"member with trajectories on first")
        if heal_steps[role] is None:
            raise KeyError(
                f"the assembled-pair manifest under {scratch} records no "
                f"heal_start_step for half {role}: the activate stage "
                f"that wrote it predates the heal marker (2026-08-28)")
        healed = frames_between(frames, heal_steps[role], None)
        for index, frame in enumerate(
                _evenly(healed, plan.frames_per_stage["activate"])):
            structures.append((
                "activated_surface", f"{member.name}:activate_{role}:{index}",
                _without_species(frame, projectile)))
    # Families 8–10 — the press movie, keyed on the bond job's ledger.
    press_frames = _read_dump(
        stage_dump_file(str(scratch), member.name, "press"), type_map)
    if not press_frames:
        raise FileNotFoundError(
            f"no press dump under {scratch}: run the bond job with "
            f"trajectories on first")
    ledger = read_pull_results(scratch).press.stage_steps
    if ledger is None or ledger.press_start is None:
        raise KeyError(
            f"the bond result under {scratch} carries no stage ledger: "
            f"the bond job that wrote it predates the ledger (2026-08-28)")
    press_budget = max(1, plan.frames_per_stage["press"])
    for family, chosen in (
            ("joint_initial", frame_at(press_frames, ledger.press_start)),
            ("joint_settled", _evenly(
                frames_between(press_frames, ledger.settle_start,
                               ledger.settle_end), press_budget)),
            ("joint_pressed", _evenly(
                frames_between(press_frames, ledger.press_start,
                               ledger.hold_end), press_budget))):
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
