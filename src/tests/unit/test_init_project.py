"""``sabsim init`` — the project-folder generator (DESIGN.md §10.9).

Three rules, each a test: it never overwrites (a second run keeps every
file the first wrote, and keeps a person's edit); it names the stage
folders from the labels it reads back out of ``sabsim.toml`` (so the
two-pass use — init, edit the pair, init again — follows the edit);
and each surface gets the recipe template of its own material, with the
silicon recipe and a notice for a material that has none. The generated
files must also pass the REAL loaders, or the generator would hand a
student a folder the tool itself refuses.
"""

import tomllib

import pytest

from sabsim.cli import main
from sabsim.deploy.init_project import (
    InitError,
    RECIPE_TEMPLATES,
    init_project,
)


def _generation_plan_project(recipe_path):
    """The ``[generation_plan] project`` value of a written recipe."""
    with recipe_path.open("rb") as handle:
        return tomllib.load(handle)["generation_plan"]["project"]


def test_a_fresh_folder_gets_the_full_si_sio2_layout(tmp_path):
    """The template pair is Si/SiO2, so the four folders follow it."""
    folder = tmp_path / "si_sio2"
    report = init_project(folder)

    assert (folder / "sabsim.toml").is_file()
    assert (folder / "deployment.toml").is_file()
    for stage in ("prep_surf1_si", "prep_surf2_sio2", "bond_si_sio2",
                  "analysis_si_sio2"):
        assert (folder / stage).is_dir(), stage
    assert (folder / "prep_surf1_si" / "recipe.toml").is_file()
    assert (folder / "prep_surf2_sio2" / "recipe.toml").is_file()
    assert report.kept == [] and report.notices == []
    assert len(report.written) == 8


def test_each_surface_gets_its_own_materials_recipe(tmp_path):
    """Silicon's recipe in prep_surf1_si, silica's in prep_surf2_sio2."""
    folder = tmp_path / "si_sio2"
    init_project(folder)
    silicon = (folder / "prep_surf1_si" / "recipe.toml").read_text()
    silica = (folder / "prep_surf2_sio2" / "recipe.toml").read_text()
    assert 'species_union = ["Si"]' in silicon
    assert 'species_union = ["Si", "O"]' in silica
    assert "sio2_alpha_quartz.cif" in silica
    assert "sio2_alpha_quartz.cif" not in silicon


def test_the_recipes_point_at_this_projects_file(tmp_path):
    """The one per-project line in a per-material file is rewritten."""
    folder = tmp_path / "si_sio2"
    init_project(folder)
    expected = str((folder / "sabsim.toml").resolve())
    for prep in ("prep_surf1_si", "prep_surf2_sio2"):
        assert _generation_plan_project(
            folder / prep / "recipe.toml") == expected


def test_a_second_run_keeps_everything_and_writes_nothing(tmp_path):
    """Never overwrites: a person's edit survives a re-run."""
    folder = tmp_path / "si_sio2"
    init_project(folder)
    edited = folder / "deployment.toml"
    edited.write_text("# my machine\n")

    report = init_project(folder)

    assert report.written == []
    assert sorted(report.kept) == sorted([
        "sabsim.toml", "deployment.toml", "prep_surf1_si/",
        "prep_surf2_sio2/", "bond_si_sio2/", "analysis_si_sio2/",
        "prep_surf1_si/recipe.toml", "prep_surf2_sio2/recipe.toml"])
    assert edited.read_text() == "# my machine\n"


def test_two_pass_use_follows_the_edited_pair(tmp_path):
    """init, edit wafer_b to Si, init again -> Si/Si folders appear."""
    folder = tmp_path / "pair"
    init_project(folder)
    project_file = folder / "sabsim.toml"
    text = project_file.read_text().replace(
        'material  = "SiO2"', 'material  = "Si"', 1)
    project_file.write_text(text)

    report = init_project(folder)

    assert (folder / "prep_surf2_si" / "recipe.toml").is_file()
    assert (folder / "bond_si_si").is_dir()
    assert (folder / "analysis_si_si").is_dir()
    # The first pass's silica folders are NOT removed: init only adds.
    assert (folder / "prep_surf2_sio2").is_dir()
    assert "prep_surf2_si/" in report.written
    assert 'species_union = ["Si"]' in (
        folder / "prep_surf2_si" / "recipe.toml").read_text()


def test_a_material_without_a_template_gets_silicon_and_a_notice(
        tmp_path):
    """No LiNbO3 recipe yet: the silicon one is a start, said aloud."""
    folder = tmp_path / "pair"
    init_project(folder)
    project_file = folder / "sabsim.toml"
    project_file.write_text(project_file.read_text().replace(
        'material  = "SiO2"', 'material  = "LiNbO3"', 1))

    report = init_project(folder)

    recipe = folder / "prep_surf2_linbo3" / "recipe.toml"
    assert recipe.is_file()
    assert 'species_union = ["Si"]' in recipe.read_text()
    assert len(report.notices) == 1
    assert "LiNbO3" in report.notices[0]
    assert "silicon recipe" in report.notices[0]
    assert not (RECIPE_TEMPLATES / "linbo3.toml").exists()


def test_a_project_file_without_labels_is_refused_readably(tmp_path):
    """A half-edited file must still say what init needed from it."""
    folder = tmp_path / "pair"
    folder.mkdir()
    (folder / "sabsim.toml").write_text('[wafer_a]\nmaterial = "Si"\n')
    with pytest.raises(InitError, match=r"\[wafer_b\] material"):
        init_project(folder)


def test_the_generated_project_passes_the_real_loaders(
        tmp_path, monkeypatch):
    """Phase one and two of both loaders accept what init wrote."""
    from sabsim.bootstrap.recipe import load_recipe
    from sabsim.spec.loader import load_and_validate_project

    monkeypatch.setenv("SABSIM_SHARE", str(tmp_path / "share"))
    monkeypatch.setenv("SABSIM_SCRATCH", str(tmp_path / "scratch"))
    folder = tmp_path / "si_sio2"
    init_project(folder)

    project = load_and_validate_project(str(folder / "sabsim.toml"))
    assert project.pair.pair_label == "si_sio2"
    for prep in ("prep_surf1_si", "prep_surf2_sio2"):
        recipe = load_recipe(folder / prep / "recipe.toml")
        assert recipe.generation_plan.project == str(
            (folder / "sabsim.toml").resolve())


def test_cli_init_reports_and_points_at_the_next_steps(tmp_path, capsys):
    """`sabsim init <folder>` exits 0 and prints the three next steps."""
    folder = tmp_path / "si_sio2"
    assert main(["init", str(folder)]) == 0
    out = capsys.readouterr().out
    assert "wrote  sabsim.toml" in out
    assert "sabsim bootstrap generate" in out
    assert "sabsim prepare" in out
    assert (folder / "prep_surf2_sio2" / "recipe.toml").is_file()
