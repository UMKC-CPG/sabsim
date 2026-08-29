"""Unit tests for phase-three validation (DESIGN.md §1.5).

The loader's static pass proves a spec is well-formed and executable in
principle. These cover the third question, which needs the ENVIRONMENT
rather than the file's text: does everything the study POINTS AT
actually exist? A crystal file at a path nobody created and a structural
domain no registry entry covers are both specs that parse cleanly and
then die partway through a run, after the node-hours that reached them
were already spent.
"""

import os
from dataclasses import replace

import pytest

from sabsim.spec.loader import SpecificationError, load_and_validate_study
from sabsim.spec.references import (
    check_study_references,
    resolve_crystal_file,
)

_TEMPLATE_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "share", "templates", "study_spec.toml"))


def _template_study():
    """The shipped template, which must itself be fully resolvable."""
    return load_and_validate_study(_TEMPLATE_PATH)


def _with_members(study, members):
    """A copy of ``study`` carrying a different member tuple."""
    return replace(study, members=tuple(members))


def test_the_shipped_template_resolves_completely():
    """The example spec must not point at anything that is missing.

    This is the regression that matters most: a shipped template naming
    a file nobody created teaches every new user to write a broken spec.

    ONE named exception, until the bootstrap has run: the environment
    library (DESIGN §3.5, 2026-08-29) is MANUFACTURED by `sabsim
    bootstrap generate`, so on a machine where the silicon library has
    not yet been built the only problems the check may report are the
    ones naming it. Anything else is a broken template.
    """
    try:
        check_study_references(_template_study())
    except SpecificationError as reported:
        problems = [line for line in str(reported).splitlines()
                    if line.lstrip().startswith("- ")]
        assert problems, "a refusal with no listed problem"
        assert all("environment_library" in line for line in problems), (
            f"the template points at something missing besides the "
            f"not-yet-built library:\n{reported}")


def test_missing_environment_library_is_reported_on_the_login_node():
    """A study naming a library nobody built fails phase three by name."""
    study = _template_study()
    members = tuple(
        replace(member, protocol=replace(
            member.protocol, environment_library="/no/such/library"))
        for member in study.members)
    with pytest.raises(SpecificationError) as caught:
        check_study_references(_with_members(study, members))
    assert "/no/such/library" in str(caught.value)
    assert "bootstrap generate" in str(caught.value)


def test_a_mismatched_library_is_refused_before_any_node_hour(tmp_path):
    """The activate job's library checks run here too (PSEUDOCODE §2)."""
    from sabsim.driver.environment_library import write_environment_library
    from tests.unit.support import hand_built_library
    manifest = write_environment_library(
        hand_built_library(model_name="DPA-2.4-7M"), tmp_path)
    study = _template_study()
    members = tuple(
        replace(member, protocol=replace(
            member.protocol, environment_library=str(manifest)))
        for member in study.members)
    with pytest.raises(SpecificationError) as caught:
        check_study_references(_with_members(study, members))
    assert "DPA-2.4-7M" in str(caught.value)


def test_missing_crystal_file_is_reported_with_every_path_tried():
    """A bad CIF path names where it looked, not just that it failed."""
    study = _template_study()
    member = study.members[0]
    broken = replace(
        member,
        material=replace(
            member.material,
            wafer_a=replace(
                member.material.wafer_a,
                cif_source="src/sabsim/structure/data/not_a_crystal.cif")))

    with pytest.raises(SpecificationError) as caught:
        check_study_references(_with_members(study, [broken]))
    message = str(caught.value)
    assert "not_a_crystal.cif" in message
    assert member.name in message
    # The message shows WHERE it searched, so a user can tell a wrong
    # spec from a missing file.
    assert "Looked in" in message






def test_every_problem_is_reported_in_one_pass():
    """Two broken members produce two findings, not the first only.

    Fixing a spec one error per run is a bad afternoon, and these
    failures cluster — a moved data directory breaks every CIF at once.
    """
    study = _template_study()
    first, second = study.members[0], study.members[1]
    break_a = replace(
        first,
        material=replace(
            first.material,
            wafer_a=replace(first.material.wafer_a,
                            cif_source="missing_one.cif")))
    break_b = replace(
        second,
        material=replace(
            second.material,
            wafer_a=replace(second.material.wafer_a,
                            cif_source="missing_two.cif")))

    with pytest.raises(SpecificationError) as caught:
        check_study_references(_with_members(study, [break_a, break_b]))
    message = str(caught.value)
    assert "missing_one.cif" in message
    assert "missing_two.cif" in message


def test_absolute_path_is_taken_as_given(tmp_path):
    """An absolute CIF path is returned untouched, not searched for."""
    crystal = tmp_path / "somewhere.cif"
    crystal.write_text("not really a cif")
    assert resolve_crystal_file(str(crystal)) == str(crystal)


def test_search_locations_are_not_repeated(tmp_path, monkeypatch):
    """Running from the repo root must not list one path three times.

    Cosmetic, but a failure message that shows the same directory three
    times reads as though three different places were tried.
    """
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError) as caught:
        resolve_crystal_file("src/sabsim/structure/data/nope.cif")
    listed = [line.strip() for line in str(caught.value).splitlines()
              if line.strip().endswith("nope.cif")]
    assert len(listed) == len(set(listed))


def test_wrong_universal_model_name_is_rejected():
    """The study's universal model must be a row of the supported table."""
    from dataclasses import replace
    study = load_and_validate_study(_TEMPLATE_PATH)
    wrong = replace(study.members[0].potential, universal_model="MACE-MP-0")
    members = tuple(
        replace(member, potential=wrong) for member in study.members)
    with pytest.raises(SpecificationError) as caught:
        check_study_references(replace(study, members=members))
    assert "DPA-3.1-3M" in str(caught.value)


def test_missing_model_file_is_rejected_on_the_login_node():
    """A weights file that is not there fails phase three, not a GPU job."""
    from dataclasses import replace
    study = load_and_validate_study(_TEMPLATE_PATH)
    absent = replace(
        study.members[0].potential, production_weights="/no/such/model.pb")
    members = tuple(
        replace(member, potential=absent) for member in study.members)
    with pytest.raises(SpecificationError) as caught:
        check_study_references(replace(study, members=members))
    assert "/no/such/model.pb" in str(caught.value)
