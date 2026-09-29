"""The recipe of a new catalog entry — written, not hand-copied.

DESIGN.md §10.11, PSEUDOCODE §14.9 (Paul, 2026-09-28). ``sabsim catalog
add`` needs a force-model recipe (§4.8) for the entry it makes, and
there are two honest places to get one:

* **A sibling of the same formula** is CLONED, because its chemistry
  lines are decisions already made and a difference between siblings
  should read as a diff (:func:`recipe_from_sibling`).
* **A new chemistry** is written from the material-neutral template
  ``share/catalog/recipe.template.toml`` (:func:`recipe_from_template`).
  Cloning another chemistry's recipe carried that material's species,
  pseudopotentials and comments into the new entry, so it is refused.

Every value the template route writes is one of three kinds, and the
comment above the line in the written recipe says which:

``DERIVED``   read or computed from the crystal file; right by rule.
``ESTIMATE``  a starting value from a stated rule, which a named check
              (``verify_melt``, the library self-check in ``generate``)
              refuses if it is wrong — so a bad estimate fails loudly.
``"DECIDE"``  a judgement no rule makes and no check would catch. The
              recipe loader refuses a recipe that still holds one.
"""

from __future__ import annotations

import datetime
import math
import os
import re
import tomllib
from pathlib import Path

import numpy as np

# The marker is the loader's to define, since the loader is what
# refuses it; this module only writes it.
from sabsim.bootstrap.recipe import UNDECIDED_MARKER, undecided_lines

TEMPLATE_FILENAME = "recipe.template.toml"

# Every recipe this command writes is the lean first generation (§4.8,
# "cheap first"); the suffix says so in the recipe's own name.
RECIPE_GENERATION_SUFFIX = "lean-v0"

# Where the gate references live, keyed by species set (DESIGN §3.5).
GATE_REFERENCE_FOLDER = "share/activation"

# The melt's starting point is what melted the hardest material so far
# (alpha quartz, LEDGER T-43): a 72-atom cell only vibrated at 5000 K,
# a 243-atom cell melted there within 2.5 ps. Hence the temperature,
# and a floor on the atom count between the two cells that were tried.
MELT_TEMPERATURE_KELVIN = 5000.0
MELT_MINIMUM_ATOMS = 200

# Neighbour distances closer together than this are ONE shell. Quartz's
# second silicon shell spans 4.35-4.37 A and its third starts at 4.90 A;
# 0.15 A keeps the first together and the two apart.
SHELL_GAP_ANGSTROM = 0.15

# How far out neighbours are searched for three shells, widening in
# turn; a crystal showing fewer than three within the last is too
# sparse for the rule, and the cutoff is left to the person.
SHELL_SEARCH_RADII_ANGSTROM = (8.0, 12.0, 16.0)

# Atoms within this height of a slab's outermost atom are counted as
# its surface PLANE. Planes of a crystal lie further apart than this
# (GaN's alternate 0.6 and 2.0 A apart along c), and atoms of one
# plane that a file's rounding separates lie much closer.
SURFACE_PLANE_DEPTH_ANGSTROM = 0.3

# The surface block's own template values, needed to cut the trial slab
# whose in-plane width sets the lateral repeat.
_TEMPLATE_SLAB_THICKNESS = 10.0
_TEMPLATE_SLAB_VACUUM = 12.0

_UNFILLED_TOKEN = re.compile(r"@[A-Z_]+@")
_PAW_LIBRARY_LINE = re.compile(
    r'^paw_library\s*=\s*"([^"]*)"', re.MULTILINE)
_ANY_TABLE_HEADER = re.compile(r"^\[\[?[^\]]+\]\]?\s*$", re.MULTILINE)
_PHASE_REFERENCE_LINE = re.compile(
    r'^(phase\s*=\s*)"[^"]*"', re.MULTILINE)
_FACE_LINE = re.compile(r"^(face\s*=\s*)\[[^\]]*\]", re.MULTILINE)

_RULE = "# " + "=" * 69
_THIN_RULE = "# " + "-" * 69


class RecipeWriteError(RuntimeError):
    """A recipe could not be written; the message says why."""


# ---------------------------------------------------------------------
# What the crystal file alone tells us.
# ---------------------------------------------------------------------

def species_in_formula_order(crystal) -> list[str]:
    """The crystal's element symbols, ordered as its formula reads.

    pymatgen writes a reduced formula with the elements in order of
    rising electronegativity (``GaN``, ``SiO2``, ``LiNbO3``); the same
    order is used for ``species_union``, which fixes the model's type
    map (DESIGN §4.3).
    """
    elements = sorted(crystal.composition.elements,
                      key=lambda element: (element.X, element.symbol))
    return [element.symbol for element in elements]


def gate_reference_path(species: list[str]) -> str:
    """The repository-relative gate reference of a species set.

    The shipped references name themselves by the symbols sorted and
    joined by an underscore — ``Si.toml``, ``O_Si.toml``,
    ``Li_Nb_O.toml`` — so the path of any set follows.
    """
    return f"{GATE_REFERENCE_FOLDER}/{'_'.join(sorted(species))}.toml"


def neighbour_shells(distances) -> list[tuple[float, float]]:
    """Group sorted distances into shells: (inner edge, outer edge).

    A new shell starts wherever two consecutive distances are further
    apart than :data:`SHELL_GAP_ANGSTROM`.
    """
    ordered = sorted(float(distance) for distance in distances)
    shells = []
    for distance in ordered:
        if shells and distance - shells[-1][1] <= SHELL_GAP_ANGSTROM:
            shells[-1] = (shells[-1][0], distance)
        else:
            shells.append((distance, distance))
    return shells


def like_species_shells(crystal, symbol: str) -> list:
    """The neighbour shells one species sees among its OWN kind.

    The search radius is widened until three shells are in view (the
    outermost shell of a search may be cut by the radius, so one more
    than is needed is required before the third is trusted).
    """
    shells = []
    for radius in SHELL_SEARCH_RADII_ANGSTROM:
        neighbours_of_sites = crystal.get_all_neighbors(radius)
        distances = [
            neighbour.nn_distance
            for site, neighbours in zip(crystal, neighbours_of_sites)
            if site.specie.symbol == symbol
            for neighbour in neighbours
            if neighbour.specie.symbol == symbol]
        shells = neighbour_shells(distances)
        if len(shells) >= 4:
            return shells
    return shells[:-1]


def estimate_descriptor_cutoff(crystal) -> float | None:
    """A starting descriptor cutoff in angstrom, or None (DESIGN §10.11).

    §3.5's rule is "through the second neighbour shell, short of the
    third". In a compound the all-pairs shells crowd together and the
    rule read literally stops inside the first polyhedron, so the
    shells are counted on the SPARSEST species' own sublattice — the
    network former, silicon in silica — and the cutoff is the midpoint
    between its second and third shells. Silicon gives 4.2 A, the
    measured value; quartz gives 4.6 A where 5.0 A measured best
    (LEDGER T-44). Where species tie for sparsest the largest midpoint
    is taken. None when three shells cannot be seen.
    """
    amounts = crystal.composition.get_el_amt_dict()
    fewest = min(amounts.values())
    sparsest = [symbol for symbol, amount in amounts.items()
                if amount == fewest]
    midpoints = []
    for symbol in sparsest:
        shells = like_species_shells(crystal, symbol)
        if len(shells) < 3:
            return None
        second_shell_outer_edge = shells[1][1]
        third_shell_inner_edge = shells[2][0]
        midpoints.append(
            0.5 * (second_shell_outer_edge + third_shell_inner_edge))
    return round(max(midpoints), 1)


def cell_widths(cell_vectors) -> list[float]:
    """The three perpendicular widths of a periodic cell, in angstrom.

    The width along an axis is the distance between the two faces
    spanned by the OTHER two vectors — the volume over that face's
    area — which is what decides whether an atom sees its own image;
    in a skewed cell it is shorter than the vector's length.
    """
    vectors = np.array(cell_vectors, dtype=float)
    volume = abs(np.linalg.det(vectors))
    widths = []
    for axis in range(3):
        first, second = (vectors[other] for other in range(3)
                         if other != axis)
        widths.append(volume / np.linalg.norm(np.cross(first, second)))
    return widths


def reduce_in_plane(first, second) -> tuple:
    """The shortest pair of vectors spanning the same in-plane lattice.

    A surface cell as cut is often skewed — the Si(100) cell arrives
    with a second vector of (-a, a) — and a skewed cell looks narrower
    than the lattice it describes. Repeating n x n tiles the SAME
    lattice whichever pair describes it, so the widths are measured on
    the reduced pair. This is Gauss's reduction: subtract from the
    longer vector the whole multiple of the shorter that shortens it
    most, and swap, until nothing shortens.
    """
    first = np.array(first, dtype=float)
    second = np.array(second, dtype=float)
    while True:
        if np.linalg.norm(second) < np.linalg.norm(first):
            first, second = second, first
        multiple = round(float(np.dot(second, first))
                         / float(np.dot(first, first)))
        if multiple == 0:
            return first, second
        second = second - multiple * first


def in_plane_widths(cell_vectors) -> list[float]:
    """The two in-plane perpendicular widths of a slab's lattice."""
    vectors = np.array(cell_vectors, dtype=float)
    first, second = reduce_in_plane(vectors[0], vectors[1])
    area = np.linalg.norm(np.cross(first, second))
    return [area / np.linalg.norm(second),
            area / np.linalg.norm(first)]


def repeats_to_clear(width: float, cutoff: float) -> int:
    """The smallest repeat n with ``n * width > 2 * cutoff``.

    A cell wider than twice the descriptor cutoff is one in which no
    atom's neighbourhood reaches its own periodic image (LEDGER T-26).
    """
    return int(math.floor(2.0 * cutoff / width)) + 1


def estimate_bulk_cells(crystal, cutoff: float) -> int:
    """Cells per axis that make the bulk block clear the cutoff."""
    narrowest = min(cell_widths(crystal.lattice.matrix))
    return repeats_to_clear(narrowest, cutoff)


def estimate_melt_cells(crystal, cutoff: float) -> int:
    """Cells per axis for the melt: wide enough AND enough atoms.

    A small periodic cell superheats instead of melting (LEDGER T-43),
    so beside clearing the cutoff the block must hold at least
    :data:`MELT_MINIMUM_ATOMS` atoms.
    """
    cells = estimate_bulk_cells(crystal, cutoff)
    while cells ** 3 * len(crystal) < MELT_MINIMUM_ATOMS:
        cells += 1
    return cells


def estimate_lateral_repeat(crystal, face, cutoff: float) -> int:
    """In-plane repeat that makes the clean surface clear the cutoff.

    The trial slab is cut exactly as the surface family will cut it
    (same builder, the template's thickness and vacuum, the first
    termination), at the crystal file's own lattice — the relaxed one
    differs by a per cent or so, which moves the repeat only when a
    width sits on the boundary.
    """
    from sabsim.structure.slab_builder import build_slab

    slab = build_slab(
        crystal, tuple(face), min_slab_thickness=_TEMPLATE_SLAB_THICKNESS,
        min_vacuum=_TEMPLATE_SLAB_VACUUM, termination_index=0)
    narrowest = min(in_plane_widths(slab.get_cell()))
    return repeats_to_clear(narrowest, cutoff)


def surface_plane_species(heights, symbols, top: bool) -> list[str]:
    """The species on a slab's outermost atomic plane, top or bottom.

    The plane is every atom within :data:`SURFACE_PLANE_DEPTH_ANGSTROM`
    of the outermost one; the symbols are returned sorted, each once.
    """
    heights = np.array(heights, dtype=float)
    if top:
        on_plane = heights >= heights.max() - SURFACE_PLANE_DEPTH_ANGSTROM
    else:
        on_plane = heights <= heights.min() + SURFACE_PLANE_DEPTH_ANGSTROM
    return sorted({symbol for symbol, chosen in zip(symbols, on_plane)
                   if chosen})


def describe_terminations(crystal, face) -> list[str]:
    """One line per termination of the face: what each side ends on.

    REPORTED, never chosen (DESIGN §10.11). The recipe and the project
    use termination 0 until §2.5 selects one by surface energy, and on
    a compound face the terminations can end on different species, so
    the person is shown which is which. The BONDING side is the slab's
    top — the side that is bombarded and then pressed (§2.6).
    """
    from sabsim.structure.slab_builder import slab_terminations

    slabs = slab_terminations(
        crystal, tuple(face), _TEMPLATE_SLAB_THICKNESS,
        _TEMPLATE_SLAB_VACUUM)
    face_text = "".join(f"m{-index}" if index < 0 else str(index)
                        for index in face)
    lines = [f"the ({face_text}) face has {len(slabs)} termination(s); "
             f"termination 0 is used, a stand-in until one is "
             f"selected by surface energy (DESIGN §2.5):"]
    for index, slab in enumerate(slabs):
        heights = [site.coords[2] for site in slab]
        symbols = [site.specie.symbol for site in slab]
        bonding = surface_plane_species(heights, symbols, top=True)
        far = surface_plane_species(heights, symbols, top=False)
        lines.append(
            f"  termination {index}: bonding side ends on "
            f"{'+'.join(bonding)}, far side on {'+'.join(far)}")
    return lines


def choose_pseudopotentials(species: list[str],
                            paw_library: Path | None) -> tuple:
    """Element -> PAW directory name, and what to tell the person.

    An element with a directory of its own plain name in the library
    gets that one — the lean choice the recipe note argues for. One
    without, or a library that cannot be reached, gets the undecided
    marker. The library's OTHER directories for each element are
    reported, so a choice such as ``Ga`` against ``Ga_d`` is seen
    rather than made silently. Returns ``(paw, notices)``.
    """
    paw, notices = {}, []
    reachable = paw_library is not None and paw_library.is_dir()
    if not reachable:
        notices.append(
            f"the pseudopotential library could not be reached "
            f"({paw_library or 'its root variable is not set'}), so "
            f"every `paw` entry is left to decide")
    for symbol in species:
        if not reachable:
            paw[symbol] = UNDECIDED_MARKER
            continue
        plain = paw_library / symbol / "POTCAR"
        paw[symbol] = symbol if plain.is_file() else UNDECIDED_MARKER
        others = sorted(
            folder.name for folder in paw_library.iterdir()
            if folder.is_dir() and folder.name.startswith(f"{symbol}_"))
        if paw[symbol] == UNDECIDED_MARKER:
            notices.append(
                f"the library has no plain '{symbol}' pseudopotential; "
                f"choose among: {', '.join(others) or '(none found)'}")
        elif others:
            notices.append(
                f"`paw` for {symbol} is the plain '{symbol}'; the "
                f"library also holds {', '.join(others)}")
    return paw, notices


# ---------------------------------------------------------------------
# TOML fragments. Written by hand so the recipe reads like the shipped
# ones: a quantity is `{ value = ..., unit = "..." }`, nothing else.
# ---------------------------------------------------------------------

def _quoted(text: str) -> str:
    return f'"{text}"'


def _quantity(value: float | None, unit: str) -> str:
    if value is None:
        return _quoted(UNDECIDED_MARKER)
    return f'{{ value = {value}, unit = "{unit}" }}'


def _integer(value: int | None) -> str:
    return _quoted(UNDECIDED_MARKER) if value is None else str(value)


def _inline_table(pairs: dict, quote_values: bool) -> str:
    rendered = ", ".join(
        f"{key} = {_quoted(value) if quote_values else value}"
        for key, value in pairs.items())
    return "{ " + rendered + " }"


def recipe_name(label: str) -> str:
    """``gan_wurtzite_001`` -> ``gan-wurtzite-001-lean-v0``."""
    return f"{label.replace('_', '-')}-{RECIPE_GENERATION_SUFFIX}"


def phase_name(formula: str, phase: str) -> str:
    """The name a recipe's families refer to the phase by.

    Lower-cased, hyphenated: ``GaN`` and ``wurtzite`` give
    ``gan-wurtzite``.
    """
    def hyphenated(text: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return f"{hyphenated(formula)}-{hyphenated(phase)}"


def _today() -> str:
    return datetime.date.today().isoformat()


def _capitalised(lines: list[str]) -> list[str]:
    """The same lines with the first one starting a sentence."""
    if not lines:
        return []
    return [lines[0][0].upper() + lines[0][1:], *lines[1:]]


def _wrapped(lines: list[str], width: int = 69) -> list[str]:
    """Break lines at spaces so a comment block keeps to the width.

    A continuation is indented to the first line's own indent plus
    four, so a list item stays readable as one item.
    """
    wrapped = []
    for line in lines:
        indent = len(line) - len(line.lstrip())
        while len(line) > width:
            cut = line.rfind(" ", 0, width + 1)
            if cut <= indent:
                break
            wrapped.append(line[:cut])
            line = " " * (indent + 4) + line[cut + 1:]
        wrapped.append(line)
    return wrapped


def _comment_block(lines: list[str]) -> str:
    lines = _wrapped(lines)
    return "\n".join(f"# {line}".rstrip() for line in lines)


# ---------------------------------------------------------------------
# Route one: a new chemistry, from the template.
# ---------------------------------------------------------------------

def resolve_pseudopotential_library(template_text: str) -> Path | None:
    """The template's ``paw_library`` with its root variable expanded.

    None when the root variable is not set in this shell, in which
    case the pseudopotential names cannot be checked.
    """
    stated = _PAW_LIBRARY_LINE.search(template_text)
    if stated is None:
        return None
    expanded = os.path.expandvars(stated.group(1))
    return None if "$" in expanded else Path(expanded)


def _template_header(label, formula, phase, face, cif_name,
                     undecided: list[str],
                     terminations: list[str]) -> str:
    """The opening comment block of a recipe written from the template."""
    face_text = "".join(f"m{-index}" if index < 0 else str(index)
                        for index in face)
    if undecided:
        still_open = (["Still to decide in this file, each marked "
                       f'"{UNDECIDED_MARKER}":']
                      + [f"  - {line}" for line in undecided])
    else:
        still_open = ["Nothing in this file is left to decide."]
    return "\n".join([
        _RULE,
        _comment_block([
            f"SABSIM force-model RECIPE — v0, {formula} {phase} "
            f"({face_text}), LEAN",
            f"(DESIGN.md §4.8). Written by `sabsim catalog add` on "
            f"{_today()}.",
            f"  catalog entry  {label}",
            f"  crystal file   {cif_name}",
            f"  written from   {TEMPLATE_FILENAME}",
            "NOTHING in it has been run yet.",
        ]),
        _THIN_RULE,
        _comment_block([
            "Every value written for this material is one of three "
            "kinds, and",
            "the comment above the line says which:",
            "  DERIVED   read or computed from the crystal file; right "
            "by rule.",
            "  ESTIMATE  a starting value from a stated rule. A named "
            "CHECK",
            "            refuses the run if it is wrong, so a bad one "
            "fails",
            "            loudly; expect to revise it after the first "
            "run.",
            f'  "{UNDECIDED_MARKER}"  a judgement no rule makes and no '
            f"check would catch.",
            "            The loader REFUSES a recipe that still holds "
            "one.",
            "Every other value is the same in every lean recipe.",
            "",
            *still_open,
            "",
            *_capitalised(terminations),
        ]),
        _THIN_RULE,
    ])


def recipe_from_template(crystal, label: str, formula: str, phase: str,
                         face, cif_repository_path: str,
                         template_path: Path,
                         repository_root: Path,
                         paw_library: Path | None = None) -> tuple:
    """Write a new chemistry's recipe from the neutral template.

    ``paw_library`` overrides the library the template names (used by
    the tests; normally the template's own, with its root expanded).
    Returns ``(text, undecided, notices)``: the recipe text, the lines
    left to decide as the loader would name them, and what to tell the
    person.
    """
    if not template_path.is_file():
        raise RecipeWriteError(
            f"recipe template {template_path} is missing — the clone's "
            f"share/catalog/ is incomplete")
    template = template_path.read_text()
    notices = []

    species = species_in_formula_order(crystal)
    reference = gate_reference_path(species)
    if not (repository_root / reference).is_file():
        notices.append(
            f"no gate reference exists for the species set "
            f"{{{', '.join(species)}}}: {reference} has to be made "
            f"before a library can be built (DESIGN §3.5)")

    if paw_library is None:
        paw_library = resolve_pseudopotential_library(template)
    paw, paw_notices = choose_pseudopotentials(species, paw_library)
    notices.extend(paw_notices)

    cutoff = estimate_descriptor_cutoff(crystal)
    if cutoff is None:
        bulk_cells = melt_cells = lateral_repeat = None
        notices.append(
            "the crystal shows fewer than three neighbour shells of "
            "its sparsest species, so the descriptor cutoff and the "
            "three cell sizes that follow from it are left to decide")
    else:
        bulk_cells = estimate_bulk_cells(crystal, cutoff)
        melt_cells = estimate_melt_cells(crystal, cutoff)
        lateral_repeat = estimate_lateral_repeat(crystal, face, cutoff)
    weights = {symbol: 1.0 / 2 ** position
               for position, symbol in enumerate(species)}

    values = {
        "@RECIPE_NAME@": recipe_name(label),
        "@SPECIES_UNION@": "[" + ", ".join(
            _quoted(symbol) for symbol in species) + "]",
        "@REFERENCE@": reference,
        "@CUTOFF@": _quantity(cutoff, "angstrom"),
        "@WEIGHTS@": _inline_table(weights, quote_values=False),
        "@PHASE_NAME@": phase_name(formula, phase),
        "@CIF@": cif_repository_path,
        "@BULK_CELLS@": _integer(bulk_cells),
        "@MELT_CELLS@": _integer(melt_cells),
        "@MELT_TEMPERATURE@": _quantity(
            None if melt_cells is None else MELT_TEMPERATURE_KELVIN, "K"),
        "@FACE@": "[" + ", ".join(str(index) for index in face) + "]",
        "@LATERAL_REPEAT@": _integer(lateral_repeat),
        "@PAW@": _inline_table(paw, quote_values=True),
    }
    body = template
    for token, value in values.items():
        body = body.replace(token, value)

    # The header lists the undecided lines, which are only known once
    # the body parses; so the body is filled first and the header last.
    try:
        undecided = undecided_lines(
            tomllib.loads(body.replace("@HEADER@", "")))
    except tomllib.TOMLDecodeError as broken:
        raise RecipeWriteError(
            f"the filled recipe template is not readable TOML: "
            f"{broken}") from None
    terminations = describe_terminations(crystal, face)
    notices.extend(_as_one_notice(terminations))
    text = body.replace("@HEADER@", _template_header(
        label, formula, phase, face, Path(cif_repository_path).name,
        undecided, terminations))
    unfilled = _UNFILLED_TOKEN.findall(text)
    if unfilled:
        raise RecipeWriteError(
            f"recipe template {template_path} holds tokens this command "
            f"does not fill: {sorted(set(unfilled))}")
    if undecided:
        notices.append(
            f"{len(undecided)} line(s) are yours to decide, marked "
            f'"{UNDECIDED_MARKER}": ' + "; ".join(undecided)
            + ". The loader refuses the recipe until they are")
    notices.append(
        "the descriptor cutoff, the species weights, the cell sizes "
        "and the melt are ESTIMATES: `verify_melt` and the library "
        "self-check refuse a wrong one, so revise after the first run")
    return text, undecided, notices


# ---------------------------------------------------------------------
# Route two: a sibling of the same formula, cloned.
# ---------------------------------------------------------------------

def set_in_table(text: str, table_header: str, key: str,
                 literal: str) -> str:
    """Set ``key`` to a TOML literal inside ONE named table of the text.

    Works on the text, not a parsed tree, so the comments survive. Only
    the lines between the first ``table_header`` line and the next
    header are touched — which is how the recipe's own ``name`` and a
    phase's ``name`` are kept apart although the key is the same.
    """
    header = re.search(rf"^{re.escape(table_header)}\s*$", text,
                       re.MULTILINE)
    if header is None:
        raise RecipeWriteError(
            f"the recipe has no {table_header} table to set '{key}' in")
    following = _ANY_TABLE_HEADER.search(text, header.end())
    end = following.start() if following else len(text)
    block = text[header.end():end]
    block, count = re.subn(
        rf"^({key}\s*=\s*)[^\n]*$",
        lambda match: f"{match.group(1)}{literal}",
        block, count=1, flags=re.MULTILINE)
    if count != 1:
        raise RecipeWriteError(
            f"the recipe's {table_header} table has no '{key}' line")
    return text[:header.end()] + block + text[end:]


def _as_one_notice(terminations: list[str]) -> list[str]:
    """The termination lines as ONE notice, the list kept as lines."""
    return ["\n         ".join(terminations)] if terminations else []


def recipe_from_sibling(crystal, source_text: str, source_label: str,
                        source_phase: str, label: str, formula: str,
                        phase: str, face,
                        cif_repository_path: str) -> tuple:
    """Clone a same-formula sibling's recipe for a new phase or face.

    The recipe's name, the phase's name and crystal, every family's
    phase reference and the surface face are rewritten; everything
    else, comments included, is the sibling's, and a note at the top
    says so. Returns ``(text, notices)``.
    """
    new_phase_name = phase_name(formula, phase)
    terminations = describe_terminations(crystal, face)
    text = set_in_table(source_text, "[recipe]", "name",
                        _quoted(recipe_name(label)))
    text = set_in_table(text, "[[phases]]", "name",
                        _quoted(new_phase_name))
    text = set_in_table(text, "[[phases]]", "cif",
                        _quoted(cif_repository_path))
    text = _PHASE_REFERENCE_LINE.sub(
        lambda match: f'{match.group(1)}"{new_phase_name}"', text)
    text = _FACE_LINE.sub(
        lambda match: f"{match.group(1)}"
                      f"[{', '.join(str(index) for index in face)}]",
        text)
    note = "\n".join([
        _RULE,
        _comment_block([
            f"CLONED by `sabsim catalog add` on {_today()}.",
            f"  catalog entry  {label}",
            f"  cloned from    {source_label}",
            "The recipe's name, the phase's name and crystal file, and "
            "the",
            "surface face were rewritten. EVERYTHING ELSE below, the "
            "comments",
            "included, is the sibling's: where a comment speaks of "
            "that",
            "crystal or that face, it is not speaking of this one.",
            "",
            *_capitalised(terminations),
        ]),
        _RULE,
    ])
    same_phase = (phase_name(formula, source_phase) == new_phase_name)
    if same_phase:
        notices = [
            f"the surface block (termination_index, slab_thickness, "
            f"lateral_repeat) is {source_label}'s face's; look at it "
            f"for the new face"]
    else:
        notices = [
            f"the melt settings and descriptor cutoff are "
            f"{source_label}'s; a new phase melts differently (LEDGER "
            f"T-43) and `verify_melt` will refuse one that does not "
            f"melt"]
    notices.extend(_as_one_notice(terminations))
    return note + "\n" + text, notices
