"""The project file of a new project — written for ITS pair.

DESIGN.md §10.9, PSEUDOCODE §14.7. ``sabsim init`` writes ``sabsim.toml``
from the tracked template ``share/templates/project_spec.toml``, and the
template names NO material: every line that depends on which two
materials are being bonded is a marker (``@DESCRIPTION@``,
``@MATERIAL_DOMAIN@``, ``@WAFER_A_NOTE@`` ...) that this module fills
from the two catalog entries of the pair (§10.11).

The reason is the one a student meets on their first project. A
template that is a worked example of silicon on silica hands every
project a description, a regime and a page of remarks about silicon and
silica, whatever is actually being bonded — and a file that talks about
another project's materials cannot be trusted line by line. So the rule
is simple to state and to check: if a line of a generated ``sabsim.toml``
names a material, that material is one of THIS pair's, or the line says
in so many words that a number was MEASURED on another material and is
only a starting value here.

Three kinds of thing are filled in:

* VALUES the loader reads — the description, the pair's
  ``material_domain``, and the five lines of each wafer table.
* REMARKS a person reads — which catalog entry a wafer came from and
  where its crystal file came from, the names of this project's stage
  folders, and which regime each wafer's recipe declares.
* An honest WARNING — the activation numbers of the template were
  pinned by a sweep on one material; for any other they are starting
  values, and the file and the ``init`` report both say so.
"""

from __future__ import annotations

import re
import textwrap
import tomllib
from pathlib import Path

from sabsim.catalog import MaterialEntry
from sabsim.spec.records import stage_folder_names

# The marker a recipe or a project file carries where a judgement is
# still the person's to make; both loaders refuse a file that holds it.
UNDECIDED_MARKER = "DECIDE"

# The catalog entry the template's activation numbers were MEASURED on:
# the energy x dose sweep of 2026-07-21 bombarded Si(100) (DESIGN §3.6).
# For any other material the same numbers are a place to start from.
SWEEP_MATERIAL_LABEL = "si_diamond_100"

# The widest a generated comment line may be, the "# " included. The
# template's own prose keeps to about this, so a filled-in remark reads
# as part of the file rather than as something pasted into it.
COMMENT_WIDTH = 72

# What joins the two regimes of a pair whose wafers declare different
# ones. The pair's regime must span BOTH plus the interface (§4.8), so
# both words are written, in wafer order, rather than one being chosen.
DOMAIN_JOINER = " + "

_MARKER = re.compile(r"@[A-Z_]+@")


class InitError(RuntimeError):
    """``init`` could not make a usable folder; the message says why."""


# ---------------------------------------------------------------------
# What a catalog entry and its recipe say about one wafer.
# ---------------------------------------------------------------------

def read_recipe(entry: MaterialEntry) -> dict:
    """The entry's recipe as a plain parsed table.

    The plain parser, not the validating recipe loader: a recipe that
    still holds lines to decide is a legitimate thing to start a
    project from (the library build refuses it later, by name), and all
    that is wanted here are a few of its values.
    """
    try:
        return tomllib.loads(entry.recipe.read_text())
    except tomllib.TOMLDecodeError as broken:
        raise InitError(f"catalog recipe {entry.recipe} is not "
                        f"readable TOML ({broken})") from None


def recipe_termination(entry: MaterialEntry) -> str:
    """The termination the entry's recipe names, as a TOML literal.

    The wafer is cut on the same termination as the clean surface its
    environment library is built from (DESIGN §2.5), so the value is
    read from the recipe's surface of the entry's own face. One still
    marked to be decided is copied as it is — the project loader
    refuses it by name — rather than settled here by guess.
    """
    recipe = read_recipe(entry)
    surfaces = recipe.get("collection1", {}).get("surfaces", [])
    for surface in surfaces:
        if tuple(surface.get("face", ())) != entry.face:
            continue
        termination = surface.get("termination_index")
        if isinstance(termination, str):
            return f'"{termination}"'
        if isinstance(termination, int):
            return str(termination)
    face = "".join(str(index) for index in entry.face)
    raise InitError(
        f"catalog recipe {entry.recipe} declares no clean ({face}) "
        f"surface with a termination_index; the wafer's termination "
        f"is copied from it (DESIGN §2.5)")


def recipe_domain(entry: MaterialEntry) -> str:
    """The structural and chemical regime the entry's recipe declares.

    ``[recipe] domain`` (§4.8 part 1) is the word the person who made
    the catalog entry chose for the regime its force model covers. A
    recipe written from the template by ``sabsim catalog add`` may
    still carry the marker that says the word is not chosen yet; it is
    handed on as it is, never replaced by a guess.
    """
    domain = read_recipe(entry).get("recipe", {}).get("domain")
    if not isinstance(domain, str) or not domain.strip():
        raise InitError(
            f"catalog recipe {entry.recipe} declares no [recipe] domain; "
            f"the project's material_domain is taken from it (DESIGN "
            f"§4.8, §10.9)")
    return domain.strip()


def material_name(entry: MaterialEntry) -> str:
    """How a person would say the material: ``SiO2 quartz (001)``.

    The formula as it is cased in the entry, the phase word, and the
    bonding face as bare Miller indices in round brackets. A negative
    index keeps its minus sign, because the sign of the face is
    honoured (DESIGN §2.5): (001) and (00-1) are different sides.
    """
    face = "".join(str(index) for index in entry.face)
    return f"{entry.formula} {entry.phase} ({face})"


def pair_description(entries) -> str:
    """The one-line description of the project, from its two wafers."""
    wafer_a, wafer_b = entries
    if wafer_a.label == wafer_b.label:
        return (f"Cold surface-activated bonding of two "
                f"{material_name(wafer_a)} wafers")
    return (f"Cold surface-activated bonding of "
            f"{material_name(wafer_a)} (wafer A) to "
            f"{material_name(wafer_b)} (wafer B)")


def pair_domain(entries) -> str:
    """The pair's ``material_domain``, from the two recipes' regimes.

    * Both recipes declare the SAME regime: that word is the pair's.
    * They declare DIFFERENT regimes: the pair must be described across
      both and across the interface between them (§4.8), so both words
      are written, wafer A's first, joined by :data:`DOMAIN_JOINER`.
    * Either is still to decide: so is the pair's, and the project
      loader refuses the file until a person has chosen.
    """
    domain_a, domain_b = (recipe_domain(entry) for entry in entries)
    if UNDECIDED_MARKER in (domain_a, domain_b):
        return UNDECIDED_MARKER
    if domain_a == domain_b:
        return domain_a
    return f"{domain_a}{DOMAIN_JOINER}{domain_b}"


# ---------------------------------------------------------------------
# The remarks: comment blocks written for this pair.
# ---------------------------------------------------------------------

def comment_block(*paragraphs: str) -> str:
    """Wrap sentences into ``# `` comment lines of the file's width.

    Each argument is one paragraph; two paragraphs are separated by a
    bare ``#`` line, the way the template separates its own. Words are
    never broken, so a long folder name stays whole on its line.
    """
    blocks = []
    for paragraph in paragraphs:
        lines = textwrap.wrap(
            " ".join(paragraph.split()), width=COMMENT_WIDTH - 2,
            break_long_words=False, break_on_hyphens=False)
        blocks.append("\n".join(f"# {line}" for line in lines))
    return "\n#\n".join(blocks)


def pair_title_note(entries) -> str:
    """The second line of the file: which pair this project is."""
    wafer_a, wafer_b = entries
    return comment_block(
        f"Pair: {material_name(wafer_a)} (wafer A, surface 1) and "
        f"{material_name(wafer_b)} (wafer B, surface 2).")


def folders_note(entries, project_directory: Path) -> str:
    """The opening remark on the project folder and its stage folders."""
    wafer_a, wafer_b = entries
    folders = stage_folder_names(wafer_a.label, wafer_b.label)
    if wafer_a.label == wafer_b.label:
        reference = (
            "This pair has the same material on both sides, so it is "
            "the kind of project a dissimilar pair is compared against;")
    else:
        reference = (
            f"A reference pair (the same material on both sides — "
            f"{wafer_a.formula}/{wafer_a.formula}, say) is a SEPARATE "
            f"project folder the person makes and runs;")
    return comment_block(
        f"ONE WAFER PAIR PER PROJECT (ARCHITECTURE §1). This file sits "
        f"in a project folder whose name is the person's own label "
        f"(`{project_directory.name}/`) and means nothing to the "
        f"program. Beside it the pipeline finds and fills four stage "
        f"folders, named from the two wafers' material labels "
        f"lower-cased: `{folders.prep_surf1}/`, `{folders.prep_surf2}/`, "
        f"`{folders.bond}/`, `{folders.analysis}/`. {reference} the "
        f"comparison between two projects is the person's, by hand "
        f"(DESIGN §1.1). There is no list of members and no relation "
        f"layer in this file.")


def domain_note(entries) -> str:
    """Where ``material_domain`` came from, in words."""
    wafer_a, wafer_b = entries
    domain_a, domain_b = recipe_domain(wafer_a), recipe_domain(wafer_b)
    source = (
        f"`material_domain` below was taken from the two catalog "
        f"recipes of this pair: wafer A's (`{wafer_a.label}`) declares "
        f"the regime \"{domain_a}\" and wafer B's (`{wafer_b.label}`) "
        f"declares \"{domain_b}\".")
    if UNDECIDED_MARKER in (domain_a, domain_b):
        consequence = (
            f"A regime still marked \"{UNDECIDED_MARKER}\" is a word "
            f"nobody has chosen yet, so the pair's is marked the same "
            f"and the loader refuses this file until it is chosen: "
            f"decide it in the recipe, then write it here.")
    elif domain_a == domain_b:
        consequence = (
            "Both declare the same regime, so that one word is the "
            "pair's.")
    else:
        consequence = (
            "They differ, and the pair's regime must span BOTH and the "
            "interface between them (§4.8), so both words are written, "
            "wafer A's first.")
    return comment_block(f"{source} {consequence}")


def wafer_note(entry: MaterialEntry, surface_number: int) -> str:
    """Which catalog entry a wafer table was filled from, and its source.

    The entry's ``[provenance]`` table is written out key by key, so
    where the crystal file came from travels with the project instead
    of staying behind in the catalog.
    """
    half = "bottom" if surface_number == 1 else "top"
    origin = (
        f"SURFACE {surface_number} (the {half} half): "
        f"{material_name(entry)}, from the catalog entry "
        f"`{entry.label}` (`share/catalog/{entry.label}/`).")
    provenance = ", ".join(
        f"{key} = {value}" for key, value in entry.provenance.items())
    if provenance:
        origin += f" Its crystal file's provenance: {provenance}."
    if recipe_termination(entry) == f'"{UNDECIDED_MARKER}"':
        origin += (
            f" This face has more than one termination and the choice "
            f"is still to make: `termination_index` below is marked "
            f"\"{UNDECIDED_MARKER}\", and the opening comment of this "
            f"wafer's recipe.toml says what each one ends on.")
    return comment_block(origin)


def wafers_not_swept(entries) -> list[MaterialEntry]:
    """The wafers of the pair the activation sweep was NOT run on."""
    unswept = []
    for entry in entries:
        if entry.label != SWEEP_MATERIAL_LABEL and entry not in unswept:
            unswept.append(entry)
    return unswept


def activation_note(entries) -> str:
    """Whether the activation numbers were measured on this pair."""
    measured = (
        f"WHERE THESE NUMBERS CAME FROM. The energy, the dose, the "
        f"required depth and the two per-impact durations below were "
        f"pinned by one sweep, on one material: the catalog entry "
        f"`{SWEEP_MATERIAL_LABEL}` (DESIGN §3.6).")
    unswept = wafers_not_swept(entries)
    if not unswept:
        return comment_block(
            f"{measured} Both wafers of this pair are that material, so "
            f"the numbers are measured ones for this project.")
    names = " and ".join(material_name(entry) for entry in unswept)
    whose = "that material" if len(unswept) == 1 else "those materials"
    return comment_block(
        f"{measured} No such sweep has been run on {names}. For "
        f"{whose} every number in this table is a STARTING value, not "
        f"a measured one: a heavier or more tightly bound surface "
        f"amorphizes at a different energy and dose, and the §3.5 gate "
        f"is what will say so. Re-pin them with a sweep of {whose} "
        f"before quoting a result.")


def library_note(entries) -> str:
    """Where each surface's environment library is looked for."""
    wafer_a, wafer_b = entries
    folders = stage_folder_names(wafer_a.label, wafer_b.label)
    return comment_block(
        f"`{folders.prep_surf1}/environment_library.toml` for wafer_a "
        f"and `{folders.prep_surf2}/environment_library.toml` for "
        f"wafer_b.")


# ---------------------------------------------------------------------
# The file itself.
# ---------------------------------------------------------------------

def _toml_string(text: str) -> str:
    """The text made safe to sit between double quotes in TOML."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def description_literal(description: str) -> str:
    """The description as a TOML value that keeps to the line width.

    A short one is an ordinary quoted string. A long one — two
    materials with long names — is written as a multi-line string whose
    lines end in a backslash: TOML joins such lines and drops the
    indentation that follows, so the loader reads ONE line of text
    while the file stays narrow enough to read.
    """
    quoted = f'"{_toml_string(description)}"'
    if len("description = ") + len(quoted) <= COMMENT_WIDTH:
        return quoted
    pieces = textwrap.wrap(
        _toml_string(description), width=COMMENT_WIDTH - 6,
        break_long_words=False, break_on_hyphens=False)
    body = " \\\n".join(f"    {piece}" for piece in pieces)
    return f'"""\\\n{body}"""'


def _face_literal(entry: MaterialEntry) -> str:
    return "[" + ", ".join(str(index) for index in entry.face) + "]"


def project_file_markers(entries, project_directory: Path) -> dict:
    """Every marker of the template and what this pair puts there."""
    wafer_a, wafer_b = entries
    markers = {
        "@PAIR_TITLE@": pair_title_note(entries),
        "@FOLDERS_NOTE@": folders_note(entries, project_directory),
        "@DESCRIPTION@": description_literal(pair_description(entries)),
        "@DOMAIN_NOTE@": domain_note(entries),
        "@MATERIAL_DOMAIN@": _toml_string(pair_domain(entries)),
        "@ACTIVATION_NOTE@": activation_note(entries),
        "@LIBRARY_NOTE@": library_note(entries),
    }
    for letter, number, entry in (("A", 1, wafer_a), ("B", 2, wafer_b)):
        markers.update({
            f"@WAFER_{letter}_NOTE@": wafer_note(entry, number),
            f"@WAFER_{letter}_MATERIAL@": _toml_string(entry.label),
            f"@WAFER_{letter}_CIF@": _toml_string(
                entry.cif_repository_path),
            # The project file calls the phase word `structure`.
            f"@WAFER_{letter}_STRUCTURE@": _toml_string(entry.phase),
            f"@WAFER_{letter}_FACE@": _face_literal(entry),
            f"@WAFER_{letter}_TERMINATION@": recipe_termination(entry),
        })
    return markers


def render_project_file(template_text: str, entries,
                        project_directory: Path) -> str:
    """The template with every marker filled in for this pair.

    Refuses, rather than writes, a result that still holds a marker or
    lacks one the pair has a value for: either means the template and
    this module have drifted apart, and a project file with a stray
    ``@MARKER@`` in it is a file no loader would explain well.
    """
    text = template_text
    for marker, value in project_file_markers(
            entries, Path(project_directory)).items():
        if marker not in text:
            raise InitError(
                f"the project template has no {marker} marker to fill; "
                f"share/templates/project_spec.toml and "
                f"sabsim/deploy/project_file.py have drifted apart")
        text = text.replace(marker, value)
    unfilled = sorted(set(_MARKER.findall(text)))
    if unfilled:
        raise InitError(
            f"the project template holds marker(s) init does not know "
            f"how to fill: {', '.join(unfilled)}")
    return text


def project_file_notices(entries, project_filename: str) -> list[str]:
    """What the person must be told about the file just written."""
    notices = []
    for table_name, entry in zip(("wafer_a", "wafer_b"), entries):
        if recipe_termination(entry) == f'"{UNDECIDED_MARKER}"':
            notices.append(
                f"{project_filename} [{table_name}] termination_index "
                f"is still to decide: the face of {entry.label} has "
                f"more than one termination, and its recipe's opening "
                f"comment says what each ends on")
    if pair_domain(entries) == UNDECIDED_MARKER:
        # A same-material pair names its one recipe once, not twice.
        undecided = " and ".join(dict.fromkeys(
            entry.label for entry in entries
            if recipe_domain(entry) == UNDECIDED_MARKER))
        notices.append(
            f"{project_filename} [project] material_domain is still to "
            f"decide: the recipe of {undecided} names no regime yet; "
            f"choose the word there, then write it in the project file")
    unswept = wafers_not_swept(entries)
    if unswept:
        names = " and ".join(material_name(entry) for entry in unswept)
        whose = "that material" if len(unswept) == 1 else "those materials"
        notices.append(
            f"{project_filename} [protocol.activation] holds numbers "
            f"pinned by a sweep on {SWEEP_MATERIAL_LABEL}; for {names} "
            f"they are starting values, to be re-pinned by a sweep of "
            f"{whose}")
    return notices
