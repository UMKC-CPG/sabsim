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
* The pair may be NAMED (``--materials Si SiO2``): the one science
  decision ``init`` asks for. Both labels are looked up in the
  materials catalogue (``share/templates/recipes/materials.toml``) and
  the project file's two wafer tables are set from the entries, so
  nobody types a crystal path for a material we already ship. An
  unknown material is refused with the catalogue printed, never
  written with a guessed crystal.

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

MATERIALS_CATALOGUE = RECIPE_TEMPLATES / "materials.toml"

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


@dataclass(frozen=True)
class MaterialEntry:
    """One shipped material, as the catalogue describes it (§10.9).

    Exactly the four values a project file's wafer table needs, plus
    the recipe template that belongs to the material. ``label`` is the
    canonical spelling (``SiO2``), which is what gets written.
    """

    label: str
    recipe: str
    cif: str
    structure: str
    face: tuple[int, int, int]


def read_materials_catalogue() -> dict[str, MaterialEntry]:
    """The catalogue, keyed by canonical label, in file order."""
    _require_template(MATERIALS_CATALOGUE)
    with MATERIALS_CATALOGUE.open("rb") as handle:
        raw = tomllib.load(handle)
    catalogue = {}
    for label, table in raw.items():
        try:
            catalogue[label] = MaterialEntry(
                label=label, recipe=str(table["recipe"]),
                cif=str(table["cif"]), structure=str(table["structure"]),
                face=tuple(int(index) for index in table["face"]))
        except (KeyError, TypeError, ValueError) as broken:
            raise InitError(f"materials catalogue entry [{label}] is "
                            f"incomplete ({broken}); each needs recipe, "
                            f"cif, structure and face") from None
    return catalogue


def lookup_material(catalogue: dict[str, MaterialEntry],
                    requested: str) -> MaterialEntry:
    """Find a material case-insensitively; refuse an unknown one aloud."""
    for label, entry in catalogue.items():
        if label.lower() == requested.strip().lower():
            return entry
    known = ", ".join(catalogue) or "(none)"
    raise InitError(
        f"no material '{requested}' in the catalogue "
        f"({MATERIALS_CATALOGUE}); it ships: {known}. Run `sabsim init` "
        f"without --materials and edit the wafer table by hand, or add "
        f"the material's recipe and catalogue entry (DESIGN §10.9)")


def describe_catalogue(catalogue: dict[str, MaterialEntry]) -> list[str]:
    """One printable line per shipped material."""
    lines = []
    for entry in catalogue.values():
        face = "".join(str(index) for index in entry.face)
        lines.append(f"{entry.label:8s} {entry.structure} ({face}) "
                     f"recipe {entry.recipe}, crystal {entry.cif}")
    return lines


# The four lines of a wafer table `init` sets from a catalogue entry.
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
        "cif": f'"{entry.cif}"',
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
                 materials: tuple[str, str] | None = None) -> InitReport:
    """Write the missing parts of a project folder from the templates.

    Runs on the login node and touches nothing that already exists.
    ``materials`` names the pair — the science decision — as two
    catalogue labels for wafer A and wafer B; with it, the project
    file's wafer tables are set from the catalogue (only when the
    project file is being written now: an existing one is kept as it
    is, and the report says so). Returns the report of what was
    written, what was kept, and what the person should be told. Raises
    :class:`InitError` when the templates are missing, a material is
    not in the catalogue, or the project file cannot yield the two
    material labels.
    """
    project_directory = Path(project_directory).resolve()
    report = InitReport(project_directory=project_directory)
    _require_template(TEMPLATE_ROOT / "project_spec.toml")
    _require_template(TEMPLATE_ROOT / "deployment_rc.toml")
    _require_template(_recipe_template(FALLBACK_RECIPE_LABEL))
    entries = None
    if materials is not None:
        catalogue = read_materials_catalogue()
        entries = (lookup_material(catalogue, materials[0]),
                   lookup_material(catalogue, materials[1]))

    _make_folder(project_directory, ".", report)

    # 1. The two top-level inputs, straight from the templates — the
    #    wafer tables set from the catalogue when the pair was named.
    project_file = project_directory / PROJECT_FILENAME
    if entries is not None and project_file.exists():
        report.notices.append(
            f"{PROJECT_FILENAME} already exists, so --materials "
            f"{entries[0].label} {entries[1].label} was NOT applied to "
            f"it; edit its wafer tables by hand, or move it aside and "
            f"run init again")
    edit = None
    if entries is not None:
        def edit(text: str) -> str:
            text = set_wafer_table(text, "wafer_a", entries[0])
            return set_wafer_table(text, "wafer_b", entries[1])
    _copy_if_missing(TEMPLATE_ROOT / "project_spec.toml", project_file,
                     report, edit=edit)
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


def _copy_if_missing(template: Path, target: Path, report: InitReport,
                     edit=None) -> None:
    """Copy a template to its target unless the target already exists.

    ``edit``, when given, transforms the template text on the way (the
    wafer tables set from the catalogue); it is never applied to a
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
