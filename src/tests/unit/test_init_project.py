"""``sabsim init`` — the project-folder generator (DESIGN.md §10.9).

The pair is REQUIRED and comes from the materials catalog (§10.11):
the wafer tables are set from the two entries, the stage folders are
named from the labels, and each prep folder receives its entry's
recipe. It never overwrites, a second run with the same pair keeps
everything, and a project file that names another pair is refused.
The generated files must also pass the REAL loaders, or the generator
would hand a student a folder the tool itself refuses.
"""

import tomllib

import pytest

from sabsim.cli import main
from sabsim.deploy.init_project import InitError, init_project

PAIR = ("si_diamond_100", "sio2_quartz_001")
PREP_1, PREP_2 = "prep_surf1_si_diamond_100", "prep_surf2_sio2_quartz_001"


def _generation_plan_project(recipe_path):
    """The ``[generation_plan] project`` value of a written recipe."""
    with recipe_path.open("rb") as handle:
        return tomllib.load(handle)["generation_plan"]["project"]


def _wafer_tables(project_file):
    with project_file.open("rb") as handle:
        raw = tomllib.load(handle)
    return raw["wafer_a"], raw["wafer_b"]


def test_a_fresh_folder_gets_the_full_layout_for_the_pair(tmp_path):
    folder = tmp_path / "si_sio2"
    report = init_project(folder, PAIR)

    assert (folder / "sabsim.toml").is_file()
    assert (folder / "deployment.toml").is_file()
    for stage in (PREP_1, PREP_2, "bond_si_diamond_100_sio2_quartz_001",
                  "analysis_si_diamond_100_sio2_quartz_001"):
        assert (folder / stage).is_dir(), stage
    assert (folder / PREP_1 / "recipe.toml").is_file()
    assert (folder / PREP_2 / "recipe.toml").is_file()
    assert report.kept == [] and report.notices == []
    assert len(report.written) == 8


def test_the_wafer_tables_come_from_the_catalog_entries(tmp_path):
    folder = tmp_path / "si_sio2"
    init_project(folder, PAIR)
    wafer_a, wafer_b = _wafer_tables(folder / "sabsim.toml")
    assert wafer_a["material"] == "si_diamond_100"
    assert wafer_a["cif"] == "share/catalog/si_diamond_100/si_diamond.cif"
    assert wafer_a["structure"] == "diamond"
    assert wafer_a["face"] == [1, 0, 0]
    assert wafer_b["material"] == "sio2_quartz_001"
    assert wafer_b["cif"] == (
        "share/catalog/sio2_quartz_001/sio2_alpha_quartz.cif")
    assert wafer_b["face"] == [0, 0, 1]


def test_each_surface_gets_its_own_entrys_recipe(tmp_path):
    folder = tmp_path / "si_sio2"
    init_project(folder, PAIR)
    silicon = (folder / PREP_1 / "recipe.toml").read_text()
    silica = (folder / PREP_2 / "recipe.toml").read_text()
    assert 'species_union = ["Si"]' in silicon
    assert 'species_union = ["Si", "O"]' in silica
    assert "sio2_alpha_quartz.cif" in silica
    assert "sio2_alpha_quartz.cif" not in silicon
    expected = str((folder / "sabsim.toml").resolve())
    for prep in (PREP_1, PREP_2):
        assert _generation_plan_project(
            folder / prep / "recipe.toml") == expected


def test_a_second_run_keeps_everything_and_writes_nothing(tmp_path):
    """Never overwrites: a person's edit survives a re-run."""
    folder = tmp_path / "si_sio2"
    init_project(folder, PAIR)
    edited = folder / "deployment.toml"
    edited.write_text("# my machine\n")

    report = init_project(folder, PAIR)

    assert report.written == []
    assert len(report.kept) == 8
    assert edited.read_text() == "# my machine\n"


def test_a_same_material_pair_gets_two_distinct_prep_folders(tmp_path):
    folder = tmp_path / "si_si"
    init_project(folder, ("si_diamond_100", "si_diamond_100"))
    assert (folder / PREP_1 / "recipe.toml").is_file()
    assert (folder / "prep_surf2_si_diamond_100" / "recipe.toml").is_file()
    assert (folder / "bond_si_diamond_100_si_diamond_100").is_dir()


def test_an_existing_project_file_naming_another_pair_is_refused(
        tmp_path):
    """The file is the record: init with a different pair stops."""
    folder = tmp_path / "pair"
    init_project(folder, PAIR)
    with pytest.raises(InitError, match="already names the pair"):
        init_project(folder, ("sio2_quartz_001", "si_diamond_100"))


def test_a_label_not_in_the_catalog_is_refused_with_the_list(tmp_path):
    with pytest.raises(InitError, match="linbo3.*it holds: si_diamond_100"):
        init_project(tmp_path / "pair", ("si_diamond_100", "linbo3_x_001"))
    assert not (tmp_path / "pair" / "sabsim.toml").exists()


def test_the_generated_project_passes_the_real_loaders(
        tmp_path, monkeypatch):
    """Phase one and two of both loaders accept what init wrote."""
    from sabsim.bootstrap.recipe import load_recipe
    from sabsim.spec.loader import load_and_validate_project

    monkeypatch.setenv("SABSIM_SHARE", str(tmp_path / "share"))
    monkeypatch.setenv("SABSIM_SCRATCH", str(tmp_path / "scratch"))
    folder = tmp_path / "si_sio2"
    init_project(folder, PAIR)

    project = load_and_validate_project(str(folder / "sabsim.toml"))
    assert project.pair.pair_label == "si_diamond_100_sio2_quartz_001"
    for prep in (PREP_1, PREP_2):
        recipe = load_recipe(folder / prep / "recipe.toml")
        assert recipe.generation_plan.project == str(
            (folder / "sabsim.toml").resolve())


def test_cli_init_reports_and_points_at_the_next_steps(tmp_path, capsys):
    folder = tmp_path / "si_sio2"
    assert main(["init", str(folder), *PAIR]) == 0
    out = capsys.readouterr().out
    assert "wrote  sabsim.toml" in out
    assert "sabsim prepare" in out
    assert (folder / PREP_2 / "recipe.toml").is_file()
    assert main(["init", str(folder), "si_diamond_100", "nope_x_1"]) == 1
    assert "catalog" in capsys.readouterr().err
