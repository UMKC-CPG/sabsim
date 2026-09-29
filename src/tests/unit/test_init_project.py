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
    assert report.kept == []
    assert len(report.written) == 8
    # The one thing to be told: the activation numbers were measured on
    # silicon, so for the silica wafer they are starting values.
    assert len(report.notices) == 1
    assert "SiO2 quartz (001)" in report.notices[0]
    assert "starting values" in report.notices[0]


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
    # The termination is the one each entry's recipe names.
    assert wafer_a["termination_index"] == 0
    assert wafer_b["termination_index"] == 0


def _project_table(project_file):
    with project_file.open("rb") as handle:
        return tomllib.load(handle)["project"]


def _entry_with_edited_recipe(tmp_path, label, edits=()):
    """A catalog entry whose recipe is a private, edited copy.

    The crystal file stays the catalog's own, so the entry still names
    it by its path in the repository; only the recipe is swapped.
    """
    from dataclasses import replace

    from sabsim.catalog import lookup_entry
    entry = lookup_entry(label)
    text = entry.recipe.read_text()
    for old, new in edits:
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    recipe = tmp_path / f"{label}.recipe.toml"
    recipe.write_text(text)
    return replace(entry, recipe=recipe)


def test_the_description_is_written_from_the_two_materials(tmp_path):
    """The description names THIS pair, whatever the pair is."""
    folder = tmp_path / "si_sio2"
    init_project(folder, PAIR)
    assert _project_table(folder / "sabsim.toml")["description"] == (
        "Cold surface-activated bonding of Si diamond (100) (wafer A) "
        "to SiO2 quartz (001) (wafer B)")
    same = tmp_path / "si_si"
    init_project(same, ("si_diamond_100", "si_diamond_100"))
    assert _project_table(same / "sabsim.toml")["description"] == (
        "Cold surface-activated bonding of two Si diamond (100) wafers")


def test_the_material_domain_comes_from_the_two_recipes(tmp_path):
    """One word when the recipes agree, both when they differ."""
    same = tmp_path / "si_si"
    init_project(same, ("si_diamond_100", "si_diamond_100"))
    assert _project_table(
        same / "sabsim.toml")["material_domain"] == "diamond-cubic"
    folder = tmp_path / "si_sio2"
    init_project(folder, PAIR)
    assert _project_table(folder / "sabsim.toml")["material_domain"] == (
        "diamond-cubic + silicon-and-silica")


def test_an_undecided_domain_is_handed_on_and_refused_by_the_loader(
        tmp_path, monkeypatch):
    """A recipe that names no regime yet leaves the pair's to decide."""
    from pathlib import Path

    from sabsim.deploy.init_project import TEMPLATE_ROOT
    from sabsim.deploy.project_file import (
        pair_domain,
        project_file_notices,
        render_project_file,
    )
    from sabsim.spec.loader import (
        SpecificationError,
        load_and_validate_project,
    )
    silicon = _entry_with_edited_recipe(tmp_path, "si_diamond_100")
    undecided = _entry_with_edited_recipe(
        tmp_path, "sio2_quartz_001",
        [('domain        = "silicon-and-silica"',
          'domain        = "DECIDE"')])
    entries = (silicon, undecided)
    assert pair_domain(entries) == "DECIDE"
    notices = project_file_notices(entries, "sabsim.toml")
    assert any("material_domain is still to decide" in notice
               and "sio2_quartz_001" in notice for notice in notices)

    monkeypatch.setenv("SABSIM_SHARE", str(tmp_path / "share"))
    monkeypatch.setenv("SABSIM_SCRATCH", str(tmp_path / "scratch"))
    project_file = tmp_path / "sabsim.toml"
    project_file.write_text(render_project_file(
        (TEMPLATE_ROOT / "project_spec.toml").read_text(), entries,
        Path(tmp_path)))
    with pytest.raises(SpecificationError, match="material_domain"):
        load_and_validate_project(str(project_file))


def test_the_project_file_names_only_its_own_materials(tmp_path):
    """Nothing is left over from another pair (DESIGN §10.9).

    A project of two materials that are neither silicon nor silica may
    mention silicon only where it says a number was MEASURED there; it
    never names silica, quartz, or another project's folders.
    """
    from sabsim.catalog import read_catalog
    labels = [entry.label for entry in read_catalog()]
    others = [label for label in labels
              if not label.startswith(("si_", "sio2_"))]
    if len(others) < 2:
        pytest.skip("the catalog holds fewer than two other materials")
    folder = tmp_path / "other_pair"
    init_project(folder, (others[0], others[1]))
    text = (folder / "sabsim.toml").read_text()
    for foreign in ("SiO2", "silica", "quartz", "cristobalite",
                    "prep_surf1_si/", "si_sio2", "Si/Si"):
        assert foreign not in text, foreign
    assert "@" not in text
    assert f"prep_surf1_{others[0]}/" in text
    assert f"prep_surf2_{others[1]}/" in text
    assert all(len(line) <= 80 for line in text.splitlines())
    # The remarks about silicon that remain say where a number or a
    # model was measured, which is true whatever is being bonded.
    prose = " ".join(text.replace("#", " ").split())
    assert "STARTING value" in prose


def test_the_template_names_no_material(tmp_path):
    """The shipped template holds markers, not a worked example."""
    from sabsim.deploy.init_project import TEMPLATE_ROOT
    text = (TEMPLATE_ROOT / "project_spec.toml").read_text()
    for foreign in ("SiO2", "silica", "quartz", "prep_surf1_si"):
        assert foreign not in text, foreign
    assert "@DESCRIPTION@" in text and "@MATERIAL_DOMAIN@" in text


def test_a_long_description_keeps_to_the_line_width():
    """A long description is folded, and reads back as one line."""
    from sabsim.deploy.project_file import description_literal
    long = ("Cold surface-activated bonding of LiNbO3 trigonal (001) "
            "(wafer A) to GaN hexagonal (001) (wafer B)")
    literal = description_literal(long)
    assert all(len(line) <= 80 for line in literal.splitlines())
    assert tomllib.loads(f"description = {literal}")["description"] == long
    assert description_literal("short") == '"short"'


def test_an_undecided_termination_is_copied_not_settled(tmp_path):
    """A recipe whose termination is still to decide hands the marker
    on to the wafer table, where the project loader refuses it."""
    import shutil

    from sabsim.catalog import CATALOG_ROOT, read_entry
    from sabsim.deploy.init_project import recipe_termination
    folder = tmp_path / "sio2_quartz_001"
    shutil.copytree(CATALOG_ROOT / "sio2_quartz_001", folder)
    recipe = folder / "recipe.toml"
    recipe.write_text(recipe.read_text().replace(
        "termination_index = 0", 'termination_index = "DECIDE"'))
    entry = read_entry(folder)
    assert recipe_termination(entry) == '"DECIDE"'
    # A recipe with no clean surface of the entry's face has nothing
    # to copy, and says so.
    recipe.write_text(recipe.read_text().replace(
        "face              = [0, 0, 1]", "face              = [1, 0, 0]"))
    with pytest.raises(InitError, match="declares no clean"):
        recipe_termination(read_entry(folder))


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
    with pytest.raises(InitError, match="linbo3.*it holds: .*si_diamond_100"):
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
