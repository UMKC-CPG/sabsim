"""The ``sabsim bootstrap`` sub-verbs: generate, label, harvest.

The bootstrap manufactures a potential in phases that run on different
machines and at different times — geometry on a login node, dynamics on
a GPU, VASP on a CPU or GPU array, training on a GPU — so each phase is
its own verb and each hands the next a plain file under ONE output
directory, exactly as the four pair jobs hand each other artifacts
(ARCHITECTURE §4.3). The directory is the scratch mirror of the folder the
command runs in, under ``bootstrap/<recipe name>/`` (the same mirror
discipline as a project run, :mod:`sabsim.deploy.scratch`). Run
``generate`` INSIDE the surface's prep folder (``<project>/prep_surfN_
<label>/``): the environment library it manufactures is placed there,
which is exactly where that surface's gate looks for it.

* ``generate``  builds Collection 1 (runs the generator model's short
  dynamics out-of-process — a compute-node step), writes the
  ENVIRONMENT LIBRARY the §3.5 gate judges against beside it
  (``collection1/environment_library.{npz,toml}``, PSEUDOCODE §11.3),
  and harvests Collection 2 from the project run the recipe names;
  writes every structure to ``structures.extxyz``.
* ``label``     selects the labelling subset, writes one VASP directory
  per structure and one SLURM job array; submits nothing.
* ``harvest``   reads the finished calculations, drops what did not
  converge, and writes ``labels.extxyz`` — the input of ``train``.
"""

from __future__ import annotations

import os
from pathlib import Path

from ase.io import read as ase_read
from ase.io import write as ase_write

from sabsim.bootstrap.recipe import (
    ForceModelRecipe,
    check_recipe_references,
    load_recipe,
)
from sabsim.deploy.scratch import job_scratch

STRUCTURES_FILE = "structures.extxyz"


def bootstrap_directory(job_directory, recipe: ForceModelRecipe) -> Path:
    """Where this recipe's phases hand files to each other."""
    directory = Path(job_scratch(job_directory)) / "bootstrap" / recipe.name
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _write_structures(structures: list, path: Path) -> None:
    frames = []
    for family, source, atoms in structures:
        frame = atoms.copy()
        frame.info["family"] = family
        frame.info["source"] = source
        frames.append(frame)
    ase_write(str(path), frames, format="extxyz", parallel=False)


def _read_structures(path: Path) -> list:
    frames = ase_read(str(path), format="extxyz", index=":", parallel=False)
    return [(frame.info["family"], frame.info["source"], frame)
            for frame in frames]


def _place_library_in_prep_folder(manifest: Path, home: Path) -> Path:
    """Copy the library pair (.toml + .npz) into the prep folder."""
    import shutil
    from sabsim.driver.environment_library import (
        LIBRARY_ARRAYS_FILE, LIBRARY_MANIFEST_FILE)
    for name in (LIBRARY_MANIFEST_FILE, LIBRARY_ARRAYS_FILE):
        shutil.copy2(manifest.parent / name, home / name)
    return home / LIBRARY_MANIFEST_FILE


def generate(recipe_path: str, job_directory: str,
             collection1: bool = True, collection2: bool = True) -> dict:
    """Build Collection 1 and/or harvest Collection 2; write structures.

    Returns a small summary (family -> count) for the caller to print.
    Either collection may be skipped — Collection 1 needs a compute node
    for its two dynamic families, Collection 2 only needs the dumps.
    """
    from sabsim.bootstrap.collection1 import build_collection1
    from sabsim.bootstrap.harvest import harvest_collection2
    recipe = load_recipe(recipe_path)
    check_recipe_references(recipe)
    out_dir = bootstrap_directory(job_directory, recipe)
    structures: list = []
    summary: dict = {}
    if collection1:
        calm, library_manifest = build_collection1(
            recipe, out_dir / "collection1")
        structures += calm
        # The library's HOME is the prep folder this command runs in
        # (`<project>/prep_surfN_<label>/`, ARCHITECTURE §1): exactly
        # where that surface's gate looks for its library, so nothing
        # has to be copied by hand. The scratch copy stays too.
        summary["environment_library"] = str(
            _place_library_in_prep_folder(
                Path(library_manifest), Path(job_directory)))
    if collection2:
        structures += harvest_collection2(recipe)
    _write_structures(structures, out_dir / STRUCTURES_FILE)
    for family, _, _ in structures:
        summary[family] = summary.get(family, 0) + 1
    return summary


def label(recipe_path: str, rc_path: str, job_directory: str) -> tuple:
    """Write the VASP inputs and the job array; return (tasks, script)."""
    from sabsim.bootstrap.label import prepare_labels
    from sabsim.deploy.config import load_deployment
    recipe = load_recipe(recipe_path)
    check_recipe_references(recipe)
    deployment = load_deployment(rc_path)
    if "label" not in deployment.usage:
        raise KeyError(
            f"{rc_path} has no [usage.label] block; the labelling job needs "
            f"its partition, module and binaries stated there (DESIGN §10)")
    out_dir = bootstrap_directory(job_directory, recipe)
    structures = _read_structures(out_dir / STRUCTURES_FILE)
    return prepare_labels(recipe, deployment, structures, out_dir / "labels")


def harvest(recipe_path: str, job_directory: str) -> tuple:
    """Collect converged labels into labels.extxyz; return (kept, dropped)."""
    from sabsim.bootstrap.label import harvest_labels
    recipe = load_recipe(recipe_path)
    out_dir = bootstrap_directory(job_directory, recipe)
    return harvest_labels(
        out_dir / "labels",
        recipe.production_settings.max_electronic_steps)
