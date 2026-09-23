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
* The pair is NAMED, and required: two labels from the materials
  catalog (``share/catalog/<label>/``, DESIGN §10.11), the one science
  decision ``init`` asks for. The project file's wafer tables are set
  from the two entries and each prep folder receives its entry's
  recipe. An unknown label is refused with the catalog printed, never
  written with a guessed crystal; a project file that already exists
  must name the same pair, or ``init`` refuses.

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

from sabsim.catalog import (
    RECIPE_FILENAME,
    CatalogError,
    MaterialEntry,
    lookup_entry,
)
from sabsim.spec.records import stage_folder_names

# The tracked templates travel with the repository, three levels above
# this module (src/sabsim/deploy/ -> the clone root), exactly as the
# reference checker locates repository-relative CIF paths.
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
TEMPLATE_ROOT = REPOSITORY_ROOT / "share" / "templates"
PROJECT_FILENAME = "sabsim.toml"
DEPLOYMENT_FILENAME = "deployment.toml"

# The one recipe line that is per-PROJECT rather than per-material: the
# generation plan's pointer at the project file whose runs Collection 2
# harvests. Matched at line start so a commented example never counts.
_GENERATION_PLAN_PROJECT_LINE = re.compile(
    r"^(project\s*=\s*)\"[^\"]*\"", re.MULTILINE)


class InitError(RuntimeError):
    """``init`` could not make a usable folder; the message says why."""


# The four lines of a wafer table `init` sets from a catalog entry.
# Matched at line start within the table, so a commented example in
# the template's prose never counts; the WHOLE line is replaced, so a
# trailing remark about the template's own value cannot outlive it.
_WAFER_LINE = {
    key: re.compile(rf"^({key}\s*=\s*)[^\n]*$", re.MULTILINE)
    for key in ("material", "cif", "structure", "face")
}
_TABLE_HEADER = re.compile(r"^\[[^\]]+\]\s*$", re.MULTILINE)


def set_wafer_table(text: str, table_name: str,
                    entry: MaterialEntry) -> str:
    """Rewrite one ``[wafer_x]`` table's four values in the template text.

    Works on the text, not a parsed tree, so every comment the template
    carries survives — the comments are the documentation a student
    reads. Only the lines between this table's header and the next
    header are touched.
    """
    header = re.search(rf"^\[{table_name}\]\s*$", text, re.MULTILINE)
    if header is None:
        raise InitError(f"the project template has no [{table_name}] "
                        f"table to set")
    following = _TABLE_HEADER.search(text, header.end())
    end = following.start() if following else len(text)
    block = text[header.end():end]
    values = {
        "material": f'"{entry.label}"',
        "cif": f'"{entry.cif_repository_path}"',
        "structure": f'"{entry.structure}"',
        "face": "[" + ", ".join(str(index) for index in entry.face) + "]",
    }
    for key, pattern in _WAFER_LINE.items():
        block, count = pattern.subn(
            lambda match, value=values[key]: f"{match.group(1)}{value}",
            block, count=1)
        if count != 1:
            raise InitError(f"the project template's [{table_name}] "
                            f"table has no '{key}' line to set")
    return text[:header.end()] + block + text[end:]


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


def init_project(project_directory: str | os.PathLike,
                 materials: tuple[str, str]) -> InitReport:
    """Write the missing parts of a project folder (DESIGN §10.9).

    Runs on the login node and touches nothing that already exists.
    ``materials`` names the pair — the science decision, required —
    as two catalog labels for wafer A and wafer B. A new project file
    has its wafer tables set from the two entries; one that already
    exists must name the same pair, or this refuses, because the file
    is the record. Returns the report of what was written, what was
    kept, and what the person should be told. Raises
    :class:`InitError` when a template is missing, a label is not in
    the catalog, or an existing project file names another pair.
    """
    project_directory = Path(project_directory).resolve()
    report = InitReport(project_directory=project_directory)
    _require_template(TEMPLATE_ROOT / "project_spec.toml")
    _require_template(TEMPLATE_ROOT / "deployment_rc.toml")
    try:
        entries = (lookup_entry(materials[0]), lookup_entry(materials[1]))
    except CatalogError as refused:
        raise InitError(str(refused)) from None

    _make_folder(project_directory, ".", report)

    # 1. The two top-level inputs; the wafer tables from the entries.
    project_file = project_directory / PROJECT_FILENAME
    if project_file.exists():
        named = _read_material_labels(project_file)
        wanted = (entries[0].label, entries[1].label)
        if tuple(label.lower() for label in named) != wanted:
            raise InitError(
                f"{project_file} already names the pair {named[0]} / "
                f"{named[1]}, not {wanted[0]} / {wanted[1]}; the file is "
                f"the record — run init with its pair, or move it aside")

    def edit(text: str) -> str:
        text = set_wafer_table(text, "wafer_a", entries[0])
        return set_wafer_table(text, "wafer_b", entries[1])
    _copy_if_missing(TEMPLATE_ROOT / "project_spec.toml", project_file,
                     report, edit=edit)
    _copy_if_missing(TEMPLATE_ROOT / "deployment_rc.toml",
                     project_directory / DEPLOYMENT_FILENAME, report)

    # 2. The four stage folders from the labels, and each entry's
    #    recipe in its prep folder.
    folders = stage_folder_names(entries[0].label, entries[1].label)
    for folder_name in (folders.prep_surf1, folders.prep_surf2,
                        folders.bond, folders.analysis):
        _make_folder(project_directory / folder_name, folder_name, report)
    for prep_folder, entry in ((folders.prep_surf1, entries[0]),
                               (folders.prep_surf2, entries[1])):
        _write_recipe(project_directory, prep_folder, entry, report)
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
                  entry: MaterialEntry, report: InitReport) -> None:
    """Put the catalog entry's recipe into its prep folder.

    The generation plan's ``project`` line is rewritten to THIS
    project's file — the only per-project line in a per-material file.
    """
    target = project_directory / prep_folder / RECIPE_FILENAME
    relative = f"{prep_folder}/{RECIPE_FILENAME}"
    if target.exists():
        report.kept.append(relative)
        return
    text = entry.recipe.read_text()
    project_file = project_directory / PROJECT_FILENAME
    text, substitutions = _GENERATION_PLAN_PROJECT_LINE.subn(
        lambda match: f'{match.group(1)}"{project_file}"', text, count=1)
    if substitutions != 1:
        raise InitError(f"catalog recipe {entry.recipe} has no "
                        f"[generation_plan] project line to point at "
                        f"this project")
    target.write_text(text)
    report.written.append(relative)


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


def _copy_if_missing(template: Path, target: Path, report: InitReport,
                     edit=None) -> None:
    """Copy a template to its target unless the target already exists.

    ``edit``, when given, transforms the template text on the way (the
    wafer tables set from the catalog); it is never applied to a
    file that is already there.
    """
    if target.exists():
        report.kept.append(target.name)
        return
    text = template.read_text()
    if edit is not None:
        text = edit(text)
    target.write_text(text)
    report.written.append(target.name)
