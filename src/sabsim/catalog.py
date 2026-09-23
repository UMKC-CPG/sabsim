"""The materials catalog — one folder per crystal phase and face.

DESIGN.md §10.11 (Paul, 2026-09-23). A material the pipeline can use
needs a crystal file, an entry naming its structure and bonding face,
and a force-model recipe for its environment library. The catalog
keeps those three together in ONE folder under ``share/catalog/``,
named ``<formula>_<phase>_<face>`` lower-cased:

    share/catalog/si_diamond_100/    material.toml, si_diamond.cif,
                                     recipe.toml
    share/catalog/sio2_quartz_001/   material.toml, sio2_alpha_quartz.cif,
                                     recipe.toml

One entry per phase AND face, because the §3.5 environment library is
built for exactly that pair. The name is explicit rather than an
ordinal for the reason Imago gives against numbered settings: the
label names the prep folder and lands in the project file, the
``command`` file and the ledger, and a number's meaning would depend
on a table that changes with the order entries were added. The
``material.toml`` values are AUTHORITATIVE and the folder name is
derived from them; a mismatch is refused, so a reader can trust a
name without opening the folder.

Two commands read and write it: ``sabsim catalog list [<formula>]``
and ``sabsim catalog add``. ``sabsim init`` looks its two labels up
here. The gate references are NOT here: they live in
``share/activation/`` keyed by species set, because one serves every
phase of that chemistry.
"""

from __future__ import annotations

import re
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# The catalog travels with the repository, two levels above this module
# (src/sabsim/ -> the clone root), exactly as the reference checker
# locates repository-relative crystal paths.
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CATALOG_ROOT = REPOSITORY_ROOT / "share" / "catalog"

ENTRY_FILENAME = "material.toml"
RECIPE_FILENAME = "recipe.toml"

# The recipe lines `catalog add` rewrites for a new phase (the crystal
# and the face), matched at line start so a comment never counts, and
# the chemistry lines it leaves alone but names for the person when
# the source entry's formula differs.
_PHASE_NAME_LINE = re.compile(r'^(name\s*=\s*)"[^"]*"', re.MULTILINE)
_PHASE_CIF_LINE = re.compile(r'^(cif\s*=\s*)"[^"]*"', re.MULTILINE)
_PHASE_REF_LINE = re.compile(r'^(phase\s*=\s*)"[^"]*"', re.MULTILINE)
_FACE_LINE = re.compile(r"^(face\s*=\s*)\[[^\]]*\]", re.MULTILINE)
CHEMISTRY_LINES = ("species_union", "domain", "reference_data_ref",
                   "species_weights", "paw", "melt_temperature",
                   "cells_per_axis")


class CatalogError(RuntimeError):
    """The catalog could not do what was asked; the message says why."""


@dataclass(frozen=True)
class MaterialEntry:
    """One catalog entry, as its ``material.toml`` describes it.

    ``label`` is the folder name; ``cif`` and ``recipe`` are absolute
    paths inside the folder; ``cif_repository_path`` is the
    repository-relative form the project file carries, so a project
    made elsewhere still resolves it against the clone.
    """

    label: str
    folder: Path
    formula: str
    structure: str
    face: tuple[int, int, int]
    cif: Path
    recipe: Path
    provenance: dict = field(default_factory=dict)

    @property
    def cif_repository_path(self) -> str:
        return self.cif.relative_to(REPOSITORY_ROOT).as_posix()

    @property
    def face_digits(self) -> str:
        return face_digits(self.face)


def face_digits(face) -> str:
    """A Miller index as bare digits, a negative one as ``m``: ``1m10``."""
    return "".join(f"m{-index}" if index < 0 else str(index)
                   for index in face)


def slug(text: str) -> str:
    """Lower-case, runs of non-alphanumerics to one underscore."""
    return re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")


def entry_label(formula: str, structure: str, face) -> str:
    """``<formula>_<phase>_<face>``: the one rule a label derives by.

    ``SiO2``, ``alpha-quartz``, ``[0, 0, 1]`` gives ``sio2_alpha_quartz_001``;
    ``SiO2``, ``quartz`` gives ``sio2_quartz_001``. The phase word is the
    person's choice; the rule only lower-cases and joins.
    """
    return f"{slug(formula)}_{slug(structure)}_{face_digits(face)}"


def read_entry(folder: Path) -> MaterialEntry:
    """Read one entry folder; refuse one whose name does not derive."""
    entry_file = folder / ENTRY_FILENAME
    try:
        with entry_file.open("rb") as handle:
            raw = tomllib.load(handle)
    except FileNotFoundError:
        raise CatalogError(f"{folder} holds no {ENTRY_FILENAME}") from None
    except tomllib.TOMLDecodeError as broken:
        raise CatalogError(f"{entry_file} is not readable TOML: "
                           f"{broken}") from None
    try:
        formula = str(raw["formula"])
        structure = str(raw["structure"])
        face = tuple(int(index) for index in raw["face"])
        cif_name = str(raw["cif"])
    except (KeyError, TypeError, ValueError) as missing:
        raise CatalogError(
            f"{entry_file} needs formula, structure, face and cif "
            f"({missing})") from None
    if len(face) != 3:
        raise CatalogError(f"{entry_file}: face must be three integers")
    expected = entry_label(formula, structure, face)
    if folder.name != expected:
        raise CatalogError(
            f"catalog folder '{folder.name}' does not derive from its "
            f"material.toml (formula {formula!r}, structure "
            f"{structure!r}, face {list(face)} -> '{expected}'); rename "
            f"the folder or fix the file (DESIGN §10.11)")
    cif = folder / cif_name
    recipe = folder / RECIPE_FILENAME
    for path, what in ((cif, "crystal file"), (recipe, "recipe")):
        if not path.is_file():
            raise CatalogError(f"catalog entry '{folder.name}' has no "
                               f"{what} at {path}")
    return MaterialEntry(
        label=folder.name, folder=folder, formula=formula,
        structure=structure, face=face, cif=cif, recipe=recipe,
        provenance=dict(raw.get("provenance", {})))


def read_catalog(root: Path = CATALOG_ROOT) -> list[MaterialEntry]:
    """Every entry under the catalog root, in name order."""
    if not root.is_dir():
        raise CatalogError(f"no catalog at {root}; the clone's share/ is "
                           f"incomplete")
    entries = []
    for folder in sorted(root.iterdir()):
        if folder.is_dir() and (folder / ENTRY_FILENAME).is_file():
            entries.append(read_entry(folder))
    return entries


def lookup_entry(label: str, root: Path = CATALOG_ROOT) -> MaterialEntry:
    """Find one entry by label; refuse an unknown one with the list."""
    wanted = label.strip().lower()
    entries = read_catalog(root)
    for entry in entries:
        if entry.label == wanted:
            return entry
    known = ", ".join(entry.label for entry in entries) or "(none)"
    raise CatalogError(
        f"no material '{label}' in the catalog ({root}); it holds: "
        f"{known}. `sabsim catalog list` shows them; `sabsim catalog "
        f"add` makes one (DESIGN §10.11)")


def describe_entries(entries, formula: str | None = None) -> list[str]:
    """One printable line per entry, optionally one formula's only."""
    lines = []
    for entry in entries:
        if formula and slug(entry.formula) != slug(formula):
            continue
        source = entry.provenance.get("source", "")
        cod = entry.provenance.get("cod_id")
        if cod is not None:
            revision = entry.provenance.get("cod_revision", "?")
            source = f"COD {cod} rev {revision}"
        lines.append(f"{entry.label:24s} {entry.formula:6s} "
                     f"{entry.structure:18s} ({entry.face_digits})  "
                     f"{source}")
    return lines


@dataclass
class AddReport:
    """What ``catalog add`` made, and what is left to the person."""

    entry: MaterialEntry
    cloned_from: str
    written: list[str] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)


def add_entry(label: str, cif_source: str, formula: str, structure: str,
              face, provenance: dict | None = None,
              source_label: str | None = None,
              root: Path = CATALOG_ROOT) -> AddReport:
    """Make one catalog entry from a crystal file (DESIGN §10.11).

    Refuses a label that does not derive from the values given, one
    that already exists, or a crystal with partial occupancy (the
    builder needs an ordered cell). Copies the crystal in, writes
    ``material.toml``, and clones the recipe from ``source_label`` or,
    by default, the first sibling of the same formula, rewriting the
    phase name, the crystal line and the surface face. When the source
    entry's formula differs, the chemistry lines are left as they were
    and NAMED in the report for the person to decide.
    """
    from sabsim.structure.slab_builder import load_crystal

    face = tuple(int(index) for index in face)
    if len(face) != 3:
        raise CatalogError("face must be three Miller indices, e.g. "
                           "--face 0 0 1")
    expected = entry_label(formula, structure, face)
    if label.strip().lower() != expected:
        raise CatalogError(
            f"label '{label}' does not derive from formula {formula!r}, "
            f"structure {structure!r}, face {list(face)}: the rule "
            f"gives '{expected}' (DESIGN §10.11)")
    folder = root / expected
    if folder.exists():
        raise CatalogError(f"catalog entry '{expected}' already exists at "
                           f"{folder}; remove the folder to replace it")
    cif_path = Path(cif_source)
    if not cif_path.is_file():
        raise CatalogError(f"no crystal file at {cif_source}")
    crystal = load_crystal(str(cif_path))
    if not crystal.is_ordered:
        raise CatalogError(
            f"{cif_source} has partial site occupancy; the slab builder "
            f"needs an ordered cell — pick an ordered entry (COD's "
            f"ambient, fully occupied ones) or order it first")
    found = crystal.composition.reduced_formula
    if slug(found) != slug(formula):
        raise CatalogError(
            f"{cif_source} is {found}, not the formula given ({formula})")

    entries = read_catalog(root)
    if source_label is not None:
        source = lookup_entry(source_label, root)
    else:
        siblings = [e for e in entries if slug(e.formula) == slug(formula)]
        if not siblings:
            raise CatalogError(
                f"no catalog entry of formula {formula} to clone the "
                f"recipe from; give --from <label> (the nearest "
                f"chemistry), then edit the chemistry lines it names")
        source = siblings[0]

    folder.mkdir(parents=True)
    report = AddReport(entry=None, cloned_from=source.label)
    shutil.copy2(cif_path, folder / cif_path.name)
    report.written.append(f"{expected}/{cif_path.name}")
    (folder / ENTRY_FILENAME).write_text(_render_entry(
        formula, structure, face, cif_path.name, provenance or {}))
    report.written.append(f"{expected}/{ENTRY_FILENAME}")

    text = source.recipe.read_text()
    phase_name = f"{slug(formula)}-{slug(structure).replace('_', '-')}"
    text = _PHASE_NAME_LINE.sub(
        lambda m: f'{m.group(1)}"{phase_name}"', text)
    text = _PHASE_CIF_LINE.sub(
        lambda m: f'{m.group(1)}"share/catalog/{expected}/{cif_path.name}"',
        text)
    text = _PHASE_REF_LINE.sub(lambda m: f'{m.group(1)}"{phase_name}"', text)
    text = _FACE_LINE.sub(
        lambda m: f"{m.group(1)}[{', '.join(str(i) for i in face)}]", text)
    (folder / RECIPE_FILENAME).write_text(text)
    report.written.append(f"{expected}/{RECIPE_FILENAME}")

    if slug(source.formula) != slug(formula):
        report.notices.append(
            f"the recipe was cloned from {source.label} ({source.formula}), "
            f"a different chemistry: decide these lines in "
            f"{expected}/{RECIPE_FILENAME} before building a library — "
            f"{', '.join(CHEMISTRY_LINES)} — and make sure a gate "
            f"reference for the species set exists in share/activation/")
    report.notices.append(
        f"the melt settings and descriptor cutoff in "
        f"{expected}/{RECIPE_FILENAME} are {source.label}'s; a new phase "
        f"melts differently (LEDGER T-43) and `verify_melt` will refuse "
        f"one that does not melt")
    report.entry = read_entry(folder)
    return report


def _render_entry(formula, structure, face, cif_name, provenance) -> str:
    """The ``material.toml`` text for a new entry, comments included."""
    lines = [
        "# SABSIM materials catalog entry (DESIGN.md §10.11). This folder",
        "# IS the material: this file, its crystal file, and its recipe.",
        "# The folder's name derives from the three values below —",
        "# <formula>_<phase>_<face>, lower-cased — and `sabsim catalog`",
        "# refuses a mismatch.",
        f'formula   = "{formula}"',
        f'structure = "{structure}"',
        f"face      = [{', '.join(str(i) for i in face)}]",
        f'cif       = "{cif_name}"',
        "",
        "[provenance]",
    ]
    if not provenance:
        lines.append('source = "unrecorded — say where this crystal came '
                     'from"')
    for key, value in provenance.items():
        if isinstance(value, (int, float)):
            lines.append(f"{key} = {value}")
        else:
            lines.append(f'{key} = "{value}"')
    return "\n".join(lines) + "\n"
