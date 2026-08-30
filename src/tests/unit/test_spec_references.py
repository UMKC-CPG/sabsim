"""Unit tests for phase-three validation (DESIGN.md §1.5).

The loader's static pass proves a project file is well-formed and
executable in principle. These cover the third question, which needs
the ENVIRONMENT rather than the file's text: does everything the
project POINTS AT actually exist? A crystal file at a path nobody
created, a prep folder with no environment library, and a weights file
that is not there are all files that parse cleanly and then die partway
through a run, after the node-hours that reached them were spent.
"""

import os
from dataclasses import replace

import pytest

from sabsim.spec.loader import (
    SpecificationError,
    load_and_validate_project,
)
from sabsim.spec.references import (
    check_project_references,
    resolve_crystal_file,
)

_TEMPLATE_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "share", "templates", "project_spec.toml"))


def _template_project():
    """The shipped template, which must itself be fully resolvable."""
    return load_and_validate_project(_TEMPLATE_PATH)


def _with_pair(project, pair):
    """A copy of ``project`` carrying a different pair."""
    return replace(project, pair=pair)


def _with_wafer_a(project, **changes):
    """A copy of ``project`` whose wafer A has ``changes`` applied."""
    pair = project.pair
    wafer_a = replace(pair.material.wafer_a, **changes)
    return _with_pair(project, replace(
        pair, material=replace(pair.material, wafer_a=wafer_a)))


def _prepared_in(project, project_directory):
    """Both prep folders moved under ``project_directory``, keeping the
    ``prep_surf<N>_<label>`` names the loader assigns."""
    pair = project.pair

    def relocate(wafer, surface_number):
        return replace(wafer, preparation_directory=str(
            project_directory
            / f"prep_surf{surface_number}_{wafer.identity.lower()}"))
    return _with_pair(project, replace(pair, material=replace(
        pair.material,
        wafer_a=relocate(pair.material.wafer_a, 1),
        wafer_b=relocate(pair.material.wafer_b, 2))))


def test_the_shipped_template_resolves_completely():
    """The example file must not point at anything that is missing.

    This is the regression that matters most: a shipped template naming
    a file nobody created teaches every new user to write a broken one.

    ONE named exception, until the bootstrap has run: the environment
    library (DESIGN §3.5) is MANUFACTURED by `sabsim bootstrap generate`
    into each surface's prep folder of the project (ARCHITECTURE §1),
    and the template's folder holds none, so the only problems the
    check may report are the ones naming a surface's library. Anything
    else is a broken template.
    """
    try:
        check_project_references(_template_project())
    except SpecificationError as reported:
        problems = [line for line in str(reported).splitlines()
                    if line.lstrip().startswith("- ")]
        assert problems, "a refusal with no listed problem"
        assert all("environment library" in line for line in problems), (
            f"the template points at something missing besides the "
            f"not-yet-built library:\n{reported}")


def test_missing_environment_library_is_reported_on_the_login_node(
        tmp_path):
    """An unprepared surface fails phase three by its prep folder."""
    project = _prepared_in(_template_project(), tmp_path)
    with pytest.raises(SpecificationError) as caught:
        check_project_references(project)
    message = str(caught.value)
    assert str(tmp_path / "prep_surf1_si") in message
    assert str(tmp_path / "prep_surf2_sio2") in message
    assert "bootstrap generate" in message
    assert "prep_surf*_si/" in message


def test_a_mismatched_library_is_refused_before_any_node_hour(tmp_path):
    """The prep job's library checks run here too (PSEUDOCODE §2)."""
    from sabsim.driver.environment_library import write_environment_library
    from tests.unit.support import hand_built_library
    (tmp_path / "prep_surf1_si").mkdir()
    write_environment_library(
        hand_built_library(model_name="DPA-2.4-7M"),
        tmp_path / "prep_surf1_si")
    project = _prepared_in(_template_project(), tmp_path)
    with pytest.raises(SpecificationError) as caught:
        check_project_references(project)
    assert "DPA-2.4-7M" in str(caught.value)


def test_both_surfaces_of_a_same_material_pair_need_a_library(tmp_path):
    """A Si/Si project has TWO prep folders (Paul, 2026-08-30); the
    second usually starts as a copy of the first, and a copy that was
    never made is reported by name."""
    from sabsim.driver.environment_library import write_environment_library
    from tests.unit.support import hand_built_library
    project = _template_project()
    silicon = project.pair.material.wafer_a
    homo = _with_pair(project, replace(
        project.pair,
        material=replace(project.pair.material, wafer_b=silicon)))
    homo = _prepared_in(homo, tmp_path)
    (tmp_path / "prep_surf1_si").mkdir()
    write_environment_library(
        hand_built_library(), tmp_path / "prep_surf1_si")
    with pytest.raises(SpecificationError) as caught:
        check_project_references(homo)
    message = str(caught.value)
    assert "prep_surf2_si" in message
    assert "prep_surf1_si/ is not there" not in message
    # Copy the folder, and the project resolves.
    (tmp_path / "prep_surf2_si").mkdir()
    write_environment_library(
        hand_built_library(), tmp_path / "prep_surf2_si")
    check_project_references(homo)                # passes quietly


def test_a_dry_run_is_not_refused_for_a_missing_library(tmp_path):
    """The walking skeleton never opens the gate, so it needs none."""
    project = _prepared_in(_template_project(), tmp_path)
    check_project_references(project, activation_gate_will_run=False)


def test_missing_crystal_file_is_reported_with_every_path_tried():
    """A bad CIF path names where it looked, not just that it failed."""
    broken = _with_wafer_a(
        _template_project(),
        cif_source="src/sabsim/structure/data/not_a_crystal.cif")

    with pytest.raises(SpecificationError) as caught:
        check_project_references(broken, activation_gate_will_run=False)
    message = str(caught.value)
    assert "not_a_crystal.cif" in message
    assert "wafer_a" in message
    # The message shows WHERE it searched, so a user can tell a wrong
    # file from a missing one.
    assert "Looked in" in message


def test_every_problem_is_reported_in_one_pass():
    """Two broken wafers produce two findings, not the first only.

    Fixing a file one error per run is a bad afternoon, and these
    failures cluster — a moved data directory breaks every CIF at once.
    """
    project = _template_project()
    pair = project.pair
    broken = _with_pair(project, replace(pair, material=replace(
        pair.material,
        wafer_a=replace(pair.material.wafer_a,
                        cif_source="missing_one.cif"),
        wafer_b=replace(pair.material.wafer_b,
                        cif_source="missing_two.cif"))))

    with pytest.raises(SpecificationError) as caught:
        check_project_references(broken, activation_gate_will_run=False)
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
    """The universal model must be a row of the supported table."""
    project = _template_project()
    wrong = replace(project.pair.potential, universal_model="MACE-MP-0")
    with pytest.raises(SpecificationError) as caught:
        check_project_references(
            _with_pair(project, replace(project.pair, potential=wrong)),
            activation_gate_will_run=False)
    assert "DPA-3.1-3M" in str(caught.value)


def test_missing_model_file_is_rejected_on_the_login_node():
    """A weights file that is not there fails phase three, not a GPU job."""
    project = _template_project()
    absent = replace(
        project.pair.potential, production_weights="/no/such/model.pb")
    with pytest.raises(SpecificationError) as caught:
        check_project_references(
            _with_pair(project, replace(project.pair, potential=absent)),
            activation_gate_will_run=False)
    assert "/no/such/model.pb" in str(caught.value)
