"""The materials catalog (DESIGN.md §10.11, PSEUDOCODE §14.9).

One folder per phase and face, named by one rule from its
``material.toml``; ``list`` reads it, ``add`` makes an entry from a
crystal file, refuses what it should, and names what is left to the
person. The shipped catalog is read as it is; ``add`` is exercised on
a copy under ``tmp_path`` so the repository's catalog is never touched.
"""

import shutil

import pytest

from sabsim.catalog import (
    CATALOG_ROOT,
    CatalogError,
    add_entry,
    describe_entries,
    entry_label,
    face_digits,
    lookup_entry,
    read_catalog,
    read_entry,
)
from sabsim.cli import main


def test_the_label_rule():
    assert entry_label("SiO2", "quartz", (0, 0, 1)) == "sio2_quartz_001"
    assert entry_label("SiO2", "alpha-quartz", [0, 0, 1]) == (
        "sio2_alpha_quartz_001")
    assert entry_label("Si", "Diamond", (1, -1, 0)) == "si_diamond_1m10"
    assert face_digits((1, 1, 1)) == "111"


def test_the_shipped_catalog_reads_and_its_names_derive():
    labels = [entry.label for entry in read_catalog()]
    assert labels == ["si_diamond_100", "sio2_quartz_001"]
    quartz = lookup_entry("SiO2_Quartz_001")           # case-insensitive
    assert quartz.formula == "SiO2" and quartz.face == (0, 0, 1)
    assert quartz.cif.is_file() and quartz.recipe.is_file()
    assert quartz.cif_repository_path == (
        "share/catalog/sio2_quartz_001/sio2_alpha_quartz.cif")
    assert quartz.provenance["cod_id"] == 1011097


def test_listing_narrows_by_formula():
    entries = read_catalog()
    assert len(describe_entries(entries)) == 2
    silica = describe_entries(entries, "sio2")
    assert len(silica) == 1 and silica[0].startswith("sio2_quartz_001")
    assert "COD 1011097 rev 303120" in silica[0]
    assert describe_entries(entries, "LiNbO3") == []


def test_a_folder_whose_name_does_not_derive_is_refused(tmp_path):
    bad = tmp_path / "sio2_quartz_100"
    shutil.copytree(CATALOG_ROOT / "sio2_quartz_001", bad)
    with pytest.raises(CatalogError, match="does not derive"):
        read_entry(bad)


@pytest.fixture
def catalog_copy(tmp_path):
    root = tmp_path / "catalog"
    shutil.copytree(CATALOG_ROOT, root)
    return root


def test_add_makes_a_sibling_entry_from_a_crystal_file(catalog_copy):
    """A second silica phase: the recipe is cloned from quartz with the
    phase, crystal and face rewritten, and the melt is flagged."""
    quartz_cif = catalog_copy / "sio2_quartz_001" / "sio2_alpha_quartz.cif"
    report = add_entry(
        "sio2_tridymite_100", str(quartz_cif), "SiO2", "tridymite",
        (1, 0, 0), provenance={"source": "Crystallography Open Database",
                                "cod_id": 1, "cod_revision": 2},
        root=catalog_copy)
    entry = report.entry
    assert entry.label == "sio2_tridymite_100"
    assert entry.face == (1, 0, 0)
    assert entry.provenance["cod_id"] == 1
    assert report.cloned_from == "sio2_quartz_001"
    recipe = entry.recipe.read_text()
    assert 'name = "sio2-tridymite"' in recipe
    assert "share/catalog/sio2_tridymite_100/sio2_alpha_quartz.cif" in recipe
    assert "face              = [1, 0, 0]" in recipe
    assert 'phase             = "sio2-tridymite"' in recipe
    assert 'species_union = ["Si", "O"]' in recipe    # chemistry kept
    assert len(report.notices) == 1 and "verify_melt" in report.notices[0]
    assert [e.label for e in read_catalog(catalog_copy)] == [
        "si_diamond_100", "sio2_quartz_001", "sio2_tridymite_100"]


def test_add_refuses_a_label_that_does_not_derive(catalog_copy):
    cif = catalog_copy / "sio2_quartz_001" / "sio2_alpha_quartz.cif"
    with pytest.raises(CatalogError, match="gives 'sio2_tridymite_100'"):
        add_entry("sio2_trid_100", str(cif), "SiO2", "tridymite",
                  (1, 0, 0), root=catalog_copy)
    with pytest.raises(CatalogError, match="already exists"):
        add_entry("sio2_quartz_001", str(cif), "SiO2", "quartz",
                  (0, 0, 1), root=catalog_copy)
    with pytest.raises(CatalogError, match="is SiO2, not the formula"):
        add_entry("si_beta_100", str(cif), "Si", "beta", (1, 0, 0),
                  root=catalog_copy)


def test_add_without_a_sibling_needs_from_and_names_the_chemistry(
        catalog_copy, tmp_path):
    # Take silicon out of the copy, so a silicon crystal has no
    # sibling of its formula to clone a recipe from.
    si_cif = tmp_path / "si_diamond.cif"
    shutil.copy(catalog_copy / "si_diamond_100" / "si_diamond.cif", si_cif)
    shutil.rmtree(catalog_copy / "si_diamond_100")
    with pytest.raises(CatalogError, match="give --from"):
        add_entry("si_diamond_111", str(si_cif), "Si", "diamond",
                  (1, 1, 1), root=catalog_copy)
    # With a foreign source the chemistry lines are named, not guessed.
    report = add_entry("si_diamond_111", str(si_cif), "Si", "diamond",
                       (1, 1, 1), source_label="sio2_quartz_001",
                       root=catalog_copy)
    assert any("different chemistry" in n and "species_union" in n
               for n in report.notices)


def test_cli_catalog_list_and_verbs(capsys):
    assert main(["catalog", "list"]) == 0
    out = capsys.readouterr().out
    assert "si_diamond_100" in out and "sio2_quartz_001" in out
    assert main(["catalog", "list", "LiNbO3"]) == 0
    assert "no entries of formula LiNbO3" in capsys.readouterr().out
