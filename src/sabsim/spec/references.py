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
Keeping it out of :func:`~sabsim.spec.loader.load_and_validate_study`
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
from sabsim.spec.records import MemberSpecification, Study


def resolve_crystal_file(cif_source: str) -> str:
    """Find a wafer's crystal file, or raise naming everywhere looked.

    A spec's ``cif`` path may be absolute, or relative to any of three
    places, and the first candidate that EXISTS wins:

    1. the directory the run was launched from — what a user editing
       their own spec expects;
    2. the REPO ROOT — how the shipped example specs are written, and
       what a spec copied out of ``dev/templates`` says;
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


def _crystal_problems(member: MemberSpecification) -> list:
    """Report any wafer whose crystal file cannot be resolved."""
    problems = []
    for role, wafer in (("wafer_a", member.material.wafer_a),
                        ("wafer_b", member.material.wafer_b)):
        try:
            resolve_crystal_file(wafer.cif_source)
        except FileNotFoundError as missing:
            problems.append(
                f"member '{member.name}' -> {role}: {missing}")
    return problems


def _species_union_or_none(member: MemberSpecification):
    """The elements both wafers contribute, or None if unreadable.

    Returns None rather than raising when a crystal file is missing or
    unparseable, because that failure is reported on its own by
    :func:`_crystal_problems` and should not be reported twice under a
    different heading.
    """
    from sabsim.structure.slab_builder import load_crystal

    symbols = set()
    for wafer in (member.material.wafer_a, member.material.wafer_b):
        try:
            crystal = load_crystal(resolve_crystal_file(wafer.cif_source))
        except Exception:
            return None
        # ``load_crystal`` strips oxidation states, so these are bare
        # element symbols; ``.symbol`` is belt-and-braces.
        symbols.update(
            element.symbol for element in crystal.composition.elements)
    return frozenset(symbols)


def _potential_problems(study: Study) -> list:
    """Report a ``[potential]`` block the run could not execute (§4.7).

    The universal model's NAME must be the identity the code pins, so a
    study never silently runs under a different release than the one the
    cascade was validated against; and both weights files must exist,
    because a missing model file would otherwise surface an hour into a
    GPU job as a LAMMPS error rather than on the login node now.
    """
    from sabsim.driver.cascade_potential import UNIVERSAL_CASCADE_MODEL
    spec = study.members[0].potential if study.members else None
    if spec is None:
        return []
    problems = []
    if spec.universal_model != UNIVERSAL_CASCADE_MODEL.name:
        problems.append(
            f"[potential] universal_model '{spec.universal_model}' is not "
            f"the pinned universal model '{UNIVERSAL_CASCADE_MODEL.name}' "
            f"(DESIGN §4.7: a universal entry pins the model version)")
    for key, path in (("universal_weights", spec.universal_weights),
                      ("production_weights", spec.production_weights)):
        if not os.path.isfile(path):
            problems.append(
                f"[potential] {key} names a model file that does not "
                f"exist: {path}")
    return problems


def check_study_references(study: Study) -> None:
    """Phase three: every artifact a study POINTS AT must be there.

    Raises :class:`~sabsim.spec.loader.SpecificationError` listing EVERY
    problem found across every member, so one pass over the spec fixes
    all of them. Returns quietly when the study is fully resolvable.

    What is deliberately NOT checked, and why it is named rather than
    skipped: ``potential_ref`` points at a manufactured force model, and
    the bootstrap that produces one (DESIGN.md §4.5, §11) is not built,
    so there is no store to resolve it against. When that store exists
    this is where its lookup belongs.
    """
    problems = []
    for member in study.members:
        problems.extend(_crystal_problems(member))
    problems.extend(_potential_problems(study))

    if problems:
        listed = "\n  - ".join(problems)
        raise SpecificationError(
            f"the study references {len(problems)} artifact(s) that "
            f"could not be resolved (DESIGN §1.5, phase three):\n"
            f"  - {listed}")
