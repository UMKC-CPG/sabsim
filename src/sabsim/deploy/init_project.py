"""``sabsim init`` — the project-folder generator (DESIGN.md §10.9).

DESIGN §1.4 forbids a hidden default and promises, in exchange, a
GENERATOR: a command that writes a complete, editable input for the
person to start from. This module is that generator for a whole project
folder (ARCHITECTURE.md §1): the project file, the deployment rc, the
four stage folders named from the pair's material labels, and a
force-model recipe for each surface's own material. It obeys three
rules, each with a reason a student can follow:

* It NEVER overwrites. A file that exists is reported and left alone,
  so ``init`` is safe to run again in a half-made folder — after the
  person has edited the wafer tables, say — and the second run adds
  only what the first could not.
* It reads the project file it wrote to learn the rest. The stage
  folders are named from the two ``material`` labels, read back with
  the PLAIN TOML parser rather than the validating loader, so a file
  the person is midway through editing still yields its labels.
* Each surface gets the recipe of ITS material, from
  ``share/templates/recipes/<label>.toml``. A material with no recipe
  of its own gets the silicon recipe as a starting point, and the
  report says so out loud (PSEUDOCODE §14.7).

It submits nothing and runs nothing: the environment library is a
compute-node job and ``prepare`` reads files the person is expected to
look at first. The result is complete in the §1.4 sense — every knob
written — and unread in the science sense until the person reads it.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from sabsim.spec.records import folder_label, stage_folder_names

# The tracked templates travel with the repository, three levels above
# this module (src/sabsim/deploy/ -> the clone root), exactly as the
# reference checker locates repository-relative CIF paths.
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
TEMPLATE_ROOT = REPOSITORY_ROOT / "share" / "templates"
RECIPE_TEMPLATES = TEMPLATE_ROOT / "recipes"

# The silicon recipe is the one every other recipe was derived from
# (DESIGN §4.8, "the first slice is silicon"), so it is the honest
# starting point for a material that has no template of its own.
FALLBACK_RECIPE_LABEL = "si"

PROJECT_FILENAME = "sabsim.toml"
DEPLOYMENT_FILENAME = "deployment.toml"
RECIPE_FILENAME = "recipe.toml"

# The one recipe line that is per-PROJECT rather than per-material: the
# generation plan's pointer at the project file whose runs Collection 2
# harvests. Matched at line start so a commented example never counts.
_GENERATION_PLAN_PROJECT_LINE = re.compile(
    r"^(project\s*=\s*)\"[^\"]*\"", re.MULTILINE)


class InitError(RuntimeError):
    """``init`` could not make a usable folder; the message says why."""


@dataclass
class InitReport:
    """What one ``init`` run did, for the CLI to print (PSEUDOCODE §14.7).

    ``written`` and ``kept`` hold paths relative to the project folder
    so the printout reads like a directory listing; ``notices`` carries
    the things the person must know that no path can say, such as a
    material that received the silicon recipe as a stand-in.
    """

    project_directory: Path
    written: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)


def init_project(project_directory: str | os.PathLike) -> InitReport:
    """Write the missing parts of a project folder from the templates.

    Runs on the login node and touches nothing that already exists.
    Returns the report of what was written, what was kept, and what
    the person should be told. Raises :class:`InitError` when the
    templates themselves are missing or the project file cannot yield
    the two material labels.
    """
    project_directory = Path(project_directory).resolve()
    report = InitReport(project_directory=project_directory)
    _require_template(TEMPLATE_ROOT / "project_spec.toml")
    _require_template(TEMPLATE_ROOT / "deployment_rc.toml")
    _require_template(_recipe_template(FALLBACK_RECIPE_LABEL))

    _make_folder(project_directory, ".", report)

    # 1. The two top-level inputs, straight from the templates.
    _copy_if_missing(TEMPLATE_ROOT / "project_spec.toml",
                     project_directory / PROJECT_FILENAME, report)
    _copy_if_missing(TEMPLATE_ROOT / "deployment_rc.toml",
                     project_directory / DEPLOYMENT_FILENAME, report)

    # 2. The pair's labels, read back out of the project file.
    material_a, material_b = _read_material_labels(
        project_directory / PROJECT_FILENAME)
    folders = stage_folder_names(material_a, material_b)

    # 3. The four stage folders, and a recipe in each prep folder.
    for folder_name in (folders.prep_surf1, folders.prep_surf2,
                        folders.bond, folders.analysis):
        _make_folder(project_directory / folder_name, folder_name, report)
    for prep_folder, material in ((folders.prep_surf1, material_a),
                                  (folders.prep_surf2, material_b)):
        _write_recipe(project_directory, prep_folder, material, report)
    return report


def _read_material_labels(project_file: Path) -> tuple[str, str]:
    """The two ``material`` labels, with the plain parser (§10.9).

    The validating loader would refuse a file the person is halfway
    through editing; all ``init`` needs is the two strings that name
    the stage folders, so it asks for exactly those and explains
    itself when they are not there.
    """
    try:
        with project_file.open("rb") as handle:
            raw = tomllib.load(handle)
    except tomllib.TOMLDecodeError as broken:
        raise InitError(f"{project_file} is not readable TOML ({broken}); "
                        f"fix it, then run `sabsim init` again to add "
                        f"the stage folders") from None
    labels = []
    for wafer in ("wafer_a", "wafer_b"):
        material = raw.get(wafer, {}).get("material")
        if not isinstance(material, str) or not material.strip():
            raise InitError(f"{project_file} has no [{wafer}] material "
                            f"label; the stage folders are named from "
                            f"it (ARCHITECTURE §1)")
        labels.append(material.strip())
    return labels[0], labels[1]


def _write_recipe(project_directory: Path, prep_folder: str,
                  material: str, report: InitReport) -> None:
    """Put this material's recipe template into its prep folder.

    The template is chosen by the lower-cased material label; a
    material without one gets the silicon recipe and a notice. The
    generation plan's ``project`` line is rewritten to THIS project's
    file — the only per-project line in a per-material file.
    """
    target = project_directory / prep_folder / RECIPE_FILENAME
    relative = f"{prep_folder}/{RECIPE_FILENAME}"
    if target.exists():
        report.kept.append(relative)
        return
    template = _recipe_template(folder_label(material))
    if not template.is_file():
        report.notices.append(
            f"no recipe template for material '{material}' under "
            f"{RECIPE_TEMPLATES}; wrote the silicon recipe to {relative} "
            f"as a starting point — edit its species, domain, gate "
            f"reference, crystal, melt temperature, face and "
            f"pseudopotentials before building a library")
        template = _recipe_template(FALLBACK_RECIPE_LABEL)
    text = template.read_text()
    project_file = project_directory / PROJECT_FILENAME
    text, substitutions = _GENERATION_PLAN_PROJECT_LINE.subn(
        lambda match: f'{match.group(1)}"{project_file}"', text, count=1)
    if substitutions != 1:
        raise InitError(f"recipe template {template} has no "
                        f"[generation_plan] project line to point at "
                        f"this project")
    target.write_text(text)
    report.written.append(relative)


def _recipe_template(label: str) -> Path:
    """Where the recipe template for a lower-cased material label lives."""
    return RECIPE_TEMPLATES / f"{label}.toml"


def _require_template(path: Path) -> None:
    """A missing template is an install problem, said plainly."""
    if not path.is_file():
        raise InitError(f"template {path} is missing — the clone's "
                        f"share/templates/ is incomplete")


def _make_folder(path: Path, relative: str, report: InitReport) -> None:
    """Create a folder if it is not there; a folder counts as a file."""
    if path.is_dir():
        if relative != ".":
            report.kept.append(f"{relative}/")
        return
    if path.exists():
        raise InitError(f"{path} exists and is not a folder")
    path.mkdir(parents=True)
    if relative != ".":
        report.written.append(f"{relative}/")


def _copy_if_missing(template: Path, target: Path,
                     report: InitReport) -> None:
    """Copy a template to its target unless the target already exists."""
    if target.exists():
        report.kept.append(target.name)
        return
    target.write_text(template.read_text())
    report.written.append(target.name)
