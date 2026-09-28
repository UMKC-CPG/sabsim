"""Phase three of validation — do the referenced artifacts exist?

DESIGN.md §1.5 splits validation in two: STATIC checks at load (types,
units, completeness, ranges) and DEFERRED checks at the point of use
(criteria whose inputs the pipeline must first measure). A third class
sits between them and had no home. A specification can be perfectly
well-formed and perfectly executable in principle while POINTING AT
things that are not there: a crystal file at a path nobody created, a
structural domain no registry entry covers. Those are not type errors,
so the loader passes them; and they are not measured quantities, so the
deferred checks never look. They surface instead partway through a run,
after the node-hours that reached them were already spent.

This module is that third phase. It differs from the loader's static
pass in ONE way that decides where it lives: it needs the ENVIRONMENT —
a filesystem, the potential registry — and not merely the file's text.
Keeping it out of :func:`~sabsim.spec.loader.load_and_validate_project`
keeps parsing pure and testable from anywhere, and puts the
environment-dependent question where the environment actually exists:
the run path, before any engine opens.

Two deliberate behaviours:

* **Every problem is reported, not just the first.** A user fixing a
  spec one error per run is a bad afternoon, and these failures cluster
  (a moved data directory breaks every CIF at once).
* **What CANNOT yet be checked says so.** ``potential_ref`` names an
  artifact the bootstrap (DESIGN.md §4.5, §11) has not been built to
  produce, so there is nothing to resolve it against. Silently skipping
  it would read as "checked and fine"; the gap is named instead.
"""

from __future__ import annotations

import os

from pathlib import Path

from sabsim.spec.loader import SpecificationError
from sabsim.spec.records import PairSpecification, Project


def resolve_crystal_file(cif_source: str) -> str:
    """Find a wafer's crystal file, or raise naming everywhere looked.

    A spec's ``cif`` path may be absolute, or relative to any of three
    places, and the first candidate that EXISTS wins:

    1. the directory the run was launched from — what a user editing
       their own spec expects;
    2. the REPO ROOT — how the shipped example specs are written, and
       what a spec copied out of ``share/templates`` says;
    3. the installed PACKAGE, by the file's path within it, so a
       non-source install resolves the shipped examples too.

    If none exist the error lists every location searched: a bare "no
    such file" for a path the user never typed is a puzzle, while the
    list shows at once whether the spec is wrong or the file is simply
    missing.

    This lives here rather than beside the pipeline stages because both
    the stages and phase-three validation must resolve a path the SAME
    way — a checker that looked in different places than the loader
    would either pass runs that fail or fail runs that would work.
    """
    path = Path(cif_source)
    if path.is_absolute():
        return str(path)

    # .../src/sabsim/spec/references.py -> parents[1] is the package
    # directory, parents[3] the repo root of a source checkout.
    package_directory = Path(__file__).resolve().parents[1]
    repo_root = Path(__file__).resolve().parents[3]
    # Strip a leading "src/sabsim/" so a repo-root-relative spec path can
    # also be found inside an installed package.
    within_package = Path(*path.parts[2:]) if path.parts[:2] == (
        "src", "sabsim") else path

    # Deduplicated, order preserved: running FROM the repo root makes the
    # first two candidates the same path, and listing it three times in a
    # failure message reads as though three different places were tried.
    candidates = []
    for candidate in (Path.cwd() / path,
                      repo_root / path,
                      package_directory / within_package):
        if candidate not in candidates:
            candidates.append(candidate)

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    searched = "\n  ".join(str(candidate) for candidate in candidates)
    raise FileNotFoundError(
        f"crystal file {cif_source!r} was not found. Looked in:\n"
        f"  {searched}\n"
        f"Give an absolute path, or place the file relative to the "
        f"directory the run was launched from.")


def _crystal_problems(pair: PairSpecification) -> list:
    """Report any wafer whose crystal file cannot be resolved."""
    problems = []
    for role, wafer in (("wafer_a", pair.material.wafer_a),
                        ("wafer_b", pair.material.wafer_b)):
        try:
            resolve_crystal_file(wafer.cif_source)
        except FileNotFoundError as missing:
            problems.append(f"[{role}]: {missing}")
    return problems


def _species_union_or_none(pair: PairSpecification):
    """The elements both wafers contribute, or None if unreadable.

    Returns None rather than raising when a crystal file is missing or
    unparseable, because that failure is reported on its own by
    :func:`_crystal_problems` and should not be reported twice under a
    different heading.
    """
    from sabsim.structure.slab_builder import load_crystal

    symbols = set()
    for wafer in (pair.material.wafer_a, pair.material.wafer_b):
        try:
            crystal = load_crystal(resolve_crystal_file(wafer.cif_source))
        except Exception:
            return None
        # ``load_crystal`` strips oxidation states, so these are bare
        # element symbols; ``.symbol`` is belt-and-braces.
        symbols.update(
            element.symbol for element in crystal.composition.elements)
    return frozenset(symbols)


def _potential_problems(pair: PairSpecification) -> list:
    """Report a ``[potential]`` block the run could not execute (§4.7).

    The universal model's NAME must be one SABSIM knows how to run — a
    row of the supported-models table (DESIGN §4.7, revised 2026-08-28) —
    so a project never silently runs under a model the code has no
    record of; and both weights files must exist, because a missing
    model file would otherwise surface an hour into a GPU job as a
    LAMMPS error rather than on the login node now.
    """
    from sabsim.driver.cascade_potential import supported_universal_model
    spec = pair.potential
    problems = []
    try:
        supported_universal_model(spec.universal_model)
    except ValueError as unknown:
        problems.append(f"[potential] universal_model: {unknown}")
    for key, path in (("universal_weights", spec.universal_weights),
                      ("production_weights", spec.production_weights)):
        if not os.path.isfile(path):
            problems.append(
                f"[potential] {key} names a model file that does not "
                f"exist: {path}")
    return problems


# The two wafer roles, in surface order: wafer A is surface 1 (the
# bottom half), wafer B surface 2 (the top half).
WAFER_ROLES = ("wafer_a", "wafer_b")


def _library_problems(pair: PairSpecification,
                      roles: tuple = WAFER_ROLES) -> list:
    """Report an environment library a prep job could not use.

    ``roles`` names the surfaces whose libraries are needed — the ones
    the caller will actually open (DESIGN §10.2, 2026-09-28): a prep
    job names its own surface, a whole-chain run names both.

    The §3.5 gate judges "crystalline" against a bootstrap-made library
    found PER SURFACE in the project: ``prep_surf1_<a>/`` for wafer A
    and ``prep_surf2_<b>/`` for wafer B (DESIGN §1.2/§3.5; Paul,
    2026-08-30). Every check here needs to READ a library file — exactly
    the environment-dependence that defines phase three. For each of
    the two surfaces the file must exist, and if it does the same rules
    the prep job applies (:func:`~sabsim.driver.environment_library.
    check_library_against_project`: model, engine, that wafer's face, the
    temperature warn/refuse band) run now, so a mismatch costs no
    node-hour. A same-material pair has two prep folders and both are
    checked — the second is usually a copy of the first, and a copy
    that was never made is exactly what this catches.
    """
    from sabsim.driver.environment_library import (
        check_library_against_project,
        library_manifest_path,
        read_environment_library,
    )
    problems = []
    wafers = {"wafer_a": pair.material.wafer_a,
              "wafer_b": pair.material.wafer_b}
    for role in roles:
        wafer = wafers[role]
        path = library_manifest_path(wafer)
        prep_folder = os.path.basename(wafer.preparation_directory)
        context = (f"[{role}] '{wafer.identity}' environment library "
                   f"in {prep_folder}/")
        if not os.path.isfile(path):
            problems.append(
                f"{context} is not there: {path} (run `sabsim bootstrap "
                f"generate` inside '{prep_folder}/', or copy a prepared "
                f"prep_surf*_{wafer.identity.lower()}/ folder there under "
                f"this name — ARCHITECTURE §1, DESIGN §4.8 part 2)")
            continue
        try:
            library = read_environment_library(path)
            check_library_against_project(library, pair, wafer)
        except SpecificationError as refused:
            problems.append(str(refused))
        except Exception as unreadable:  # a corrupt or half-written pair
            problems.append(f"{context} could not be read: {unreadable}")
    return problems


def check_project_references(
        project: Project,
        libraries_needed: tuple = WAFER_ROLES) -> None:
    """Phase three: every artifact a project POINTS AT must be there.

    Raises :class:`~sabsim.spec.loader.SpecificationError` listing EVERY
    problem found, so one pass over the file fixes all of them. Returns
    quietly when the project is fully resolvable.

    ``libraries_needed`` names the surfaces whose environment library
    this run will OPEN, as wafer roles (``"wafer_a"``, ``"wafer_b"``);
    only those are checked (DESIGN §10.2, 2026-09-28). A whole-chain
    run opens both, the default. The prep job of one surface opens its
    own and is not refused because the other surface's library is
    still being built — LEDGER T-45's silicon prep was, after thirteen
    seconds. The bond and analysis jobs open none, and neither does the
    walking skeleton (a ``--dry-run``), whose activation stage is a
    stand-in: each passes an empty tuple.

    What is deliberately NOT checked, and why it is named rather than
    skipped: ``potential_ref`` points at a manufactured force model, and
    the bootstrap that produces one (DESIGN.md §4.5, §11) is not built,
    so there is no store to resolve it against. When that store exists
    this is where its lookup belongs.
    """
    pair = project.pair
    problems = list(_crystal_problems(pair))
    unknown = [role for role in libraries_needed
               if role not in WAFER_ROLES]
    if unknown:
        raise ValueError(f"unknown wafer role(s) {unknown}; the roles are "
                         f"{list(WAFER_ROLES)}")
    problems.extend(_library_problems(pair, tuple(libraries_needed)))
    problems.extend(_potential_problems(pair))

    if problems:
        listed = "\n  - ".join(problems)
        raise SpecificationError(
            f"the project references {len(problems)} artifact(s) that "
            f"could not be resolved (DESIGN §1.5, phase three):\n"
            f"  - {listed}")
