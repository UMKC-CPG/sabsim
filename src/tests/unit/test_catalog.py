"""The materials catalog (DESIGN.md §10.11, PSEUDOCODE §14.9).

One folder per phase and face, named by one rule from its
``material.toml``; ``list`` reads it, ``add`` makes an entry from a
crystal file, refuses what it should, and names what is left to the
person. The shipped catalog is read as it is; ``add`` is exercised on
a copy under ``tmp_path`` so the repository's catalog is never touched.

Materials live in a person's own clone (DESIGN §10.11), so the real
catalog may hold more than the two entries the repository ships. The
tests therefore count entries only in the copy, which takes the
SHIPPED entries and the recipe template and nothing else.
"""

import shutil
import tomllib

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
from sabsim.bootstrap.recipe import (
    UNDECIDED_MARKER,
    load_recipe,
)
from sabsim.catalog_recipe import (
    TEMPLATE_FILENAME,
    estimate_descriptor_cutoff,
    in_plane_widths,
    repeats_to_clear,
)
from sabsim.cli import main
from sabsim.spec.loader import SpecificationError
from sabsim.structure.slab_builder import load_crystal


def test_the_label_rule():
    assert entry_label("SiO2", "quartz", (0, 0, 1)) == "sio2_quartz_001"
    assert entry_label("SiO2", "alpha-quartz", [0, 0, 1]) == (
        "sio2_alpha_quartz_001")
    assert entry_label("Si", "Diamond", (1, -1, 0)) == "si_diamond_1m10"
    assert face_digits((1, 1, 1)) == "111"


SHIPPED_ENTRIES = ("si_diamond_100", "sio2_quartz_001")


def test_the_shipped_catalog_reads_and_its_names_derive():
    labels = [entry.label for entry in read_catalog()]
    assert set(SHIPPED_ENTRIES) <= set(labels)
    quartz = lookup_entry("SiO2_Quartz_001")           # case-insensitive
    assert quartz.formula == "SiO2" and quartz.face == (0, 0, 1)
    assert quartz.cif.is_file() and quartz.recipe.is_file()
    assert quartz.cif_repository_path == (
        "share/catalog/sio2_quartz_001/sio2_alpha_quartz.cif")
    assert quartz.provenance["cod_id"] == 1011097


def test_listing_narrows_by_formula(catalog_copy):
    entries = read_catalog(catalog_copy)
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


def test_an_entry_under_the_old_structure_key_is_refused(tmp_path):
    """The phase word's key was `structure` until 2026-09-28; an entry
    still written that way is refused with the repair named."""
    old = tmp_path / "sio2_quartz_001"
    shutil.copytree(CATALOG_ROOT / "sio2_quartz_001", old)
    entry_file = old / "material.toml"
    entry_file.write_text(entry_file.read_text().replace(
        "\nphase     = ", "\nstructure = "))
    with pytest.raises(CatalogError, match="rename that key to 'phase'"):
        read_entry(old)


@pytest.fixture
def catalog_copy(tmp_path):
    root = tmp_path / "catalog"
    root.mkdir()
    for label in SHIPPED_ENTRIES:
        shutil.copytree(CATALOG_ROOT / label, root / label)
    shutil.copy(CATALOG_ROOT / TEMPLATE_FILENAME, root)
    return root


def test_add_makes_a_sibling_entry_from_a_crystal_file(catalog_copy):
    """A second silica phase: the recipe is cloned from quartz with the
    phase, crystal and face rewritten, and the melt is flagged."""
    quartz_cif = catalog_copy / "sio2_quartz_001" / "sio2_alpha_quartz.cif"
    report = add_entry(
        str(quartz_cif), "tridymite", (1, 0, 0), formula="SiO2",
        label="sio2_tridymite_100",
        provenance={"source": "Crystallography Open Database",
                    "cod_id": 1, "cod_revision": 2},
        root=catalog_copy)
    entry = report.entry
    assert entry.label == "sio2_tridymite_100"
    assert entry.face == (1, 0, 0)
    assert entry.provenance["cod_id"] == 1
    assert report.cloned_from == "sio2_quartz_001"
    recipe = entry.recipe.read_text()
    # The recipe's OWN name and the phase's name are different lines
    # of different tables, and each gets its own value.
    assert 'name          = "sio2-tridymite-100-lean-v0"' in recipe
    assert 'name = "sio2-tridymite"' in recipe
    assert "sio2-quartz-lean-v0" not in recipe
    assert recipe.startswith("# ====") and "cloned from    " in recipe
    assert load_recipe(entry.recipe).phases[0].name == "sio2-tridymite"
    assert "share/catalog/sio2_tridymite_100/sio2_alpha_quartz.cif" in recipe
    assert "face              = [1, 0, 0]" in recipe
    assert 'phase             = "sio2-tridymite"' in recipe
    assert 'species_union = ["Si", "O"]' in recipe    # chemistry kept
    assert len(report.notices) == 1 and "verify_melt" in report.notices[0]
    # A second FACE of the same phase is cloned from that phase, and
    # what is flagged is the surface block, not the melt.
    second_face = add_entry(str(quartz_cif), "tridymite", (0, 0, 1),
                            root=catalog_copy)
    assert second_face.cloned_from == "sio2_tridymite_100"
    assert "lateral_repeat" in second_face.notices[0]
    catalog_labels = [e.label for e in read_catalog(catalog_copy)]
    assert "sio2_tridymite_001" in catalog_labels
    shutil.rmtree(catalog_copy / "sio2_tridymite_001")
    assert [e.label for e in read_catalog(catalog_copy)] == [
        "si_diamond_100", "sio2_quartz_001", "sio2_tridymite_100"]


def test_add_refuses_a_label_that_does_not_derive(catalog_copy):
    cif = catalog_copy / "sio2_quartz_001" / "sio2_alpha_quartz.cif"
    with pytest.raises(CatalogError, match="gives 'sio2_tridymite_100'"):
        add_entry(str(cif), "tridymite", (1, 0, 0), formula="SiO2",
                  label="sio2_trid_100", root=catalog_copy)
    with pytest.raises(CatalogError, match="already exists"):
        add_entry(str(cif), "quartz", (0, 0, 1), root=catalog_copy)
    with pytest.raises(CatalogError, match="is SiO2, not the formula"):
        add_entry(str(cif), "beta", (1, 0, 0), formula="Si",
                  root=catalog_copy)
    # Nothing a refusal touched was written: the copy is as it was.
    assert [e.label for e in read_catalog(catalog_copy)] == [
        "si_diamond_100", "sio2_quartz_001"]


def test_add_derives_the_label_and_reads_the_formula(catalog_copy):
    """Crystal, phase and face are enough: no label, no formula. A
    formula typed in lower case is a check only — the entry records
    the crystal's own casing."""
    cif = catalog_copy / "sio2_quartz_001" / "sio2_alpha_quartz.cif"
    report = add_entry(str(cif), "Beta Cristobalite", (1, -1, 0),
                       root=catalog_copy)
    assert report.entry.label == "sio2_beta_cristobalite_1m10"
    assert report.entry.formula == "SiO2"
    assert report.entry.phase == "Beta Cristobalite"
    assert any("sio2_beta_cristobalite_1m10" in line
               for line in report.derived)
    assert any("SiO2" in line for line in report.derived)
    lower_case = add_entry(str(cif), "tridymite", (1, 0, 0),
                           formula="sio2", root=catalog_copy)
    assert lower_case.entry.formula == "SiO2"
    with pytest.raises(CatalogError, match="phase name is empty"):
        add_entry(str(cif), " - ", (1, 0, 0), root=catalog_copy)


@pytest.fixture
def silicon_as_a_new_chemistry(catalog_copy, tmp_path):
    """Silicon taken out of the catalog copy, so its crystal is a
    chemistry the catalog does not hold; and a pseudopotential library
    of one element, so the test needs no machine-local root."""
    si_cif = tmp_path / "si_diamond.cif"
    shutil.copy(catalog_copy / "si_diamond_100" / "si_diamond.cif", si_cif)
    shutil.rmtree(catalog_copy / "si_diamond_100")
    library = tmp_path / "paw_library"
    for folder in ("Si", "Si_sv_GW"):
        (library / folder).mkdir(parents=True)
        (library / folder / "POTCAR").write_text("stand-in\n")
    return si_cif, library


def test_another_chemistry_is_never_cloned(
        catalog_copy, silicon_as_a_new_chemistry):
    si_cif, library = silicon_as_a_new_chemistry
    with pytest.raises(CatalogError, match="is SiO2, not Si"):
        add_entry(str(si_cif), "diamond", (1, 1, 1),
                  source_label="sio2_quartz_001", root=catalog_copy,
                  paw_library=library)
    assert not (catalog_copy / "si_diamond_111").exists()


def test_a_new_chemistry_is_written_from_the_template(
        catalog_copy, silicon_as_a_new_chemistry):
    """No sibling: the recipe is filled from the neutral template —
    chemistry derived from the crystal, the ruler and cells estimated
    by rule, and the domain left for the person."""
    si_cif, library = silicon_as_a_new_chemistry
    report = add_entry(str(si_cif), "diamond", (1, 0, 0),
                       root=catalog_copy, paw_library=library)
    assert report.cloned_from is None
    assert report.undecided == ["[recipe] -> domain"]
    text = report.entry.recipe.read_text()
    raw = tomllib.loads(text)
    assert raw["recipe"]["name"] == "si-diamond-100-lean-v0"
    assert raw["recipe"]["species_union"] == ["Si"]
    assert raw["recipe"]["reference_data_ref"] == (
        "share/activation/Si.toml")
    assert raw["recipe"]["domain"] == UNDECIDED_MARKER
    assert raw["phases"][0] == {
        "name": "si-diamond",
        "cif": "share/catalog/si_diamond_100/si_diamond.cif"}
    assert raw["production_settings"]["paw"] == {"Si": "Si"}
    assert raw["audit_settings"]["paw"] == {"Si": "Si"}
    # The estimates reproduce what silicon's shipped recipe measured.
    assert raw["descriptor"]["descriptor_cutoff"]["value"] == 4.2
    assert raw["descriptor"]["species_weights"] == {"Si": 1.0}
    assert raw["collection1"]["bulk"]["cells_per_axis"] == 2
    assert raw["collection1"]["surfaces"][0]["lateral_repeat"] == 3
    assert raw["collection1"]["surfaces"][0]["face"] == [1, 0, 0]
    melt = raw["collection1"]["melt_quench"][0]
    assert melt["cells_per_axis"] == 3            # 216 atoms >= 200
    assert melt["melt_temperature"]["value"] == 5000.0
    # The text is this material's: no other material's story in it.
    assert "SILICA" not in text and "quartz, LEDGER T-43" in text
    assert "@" not in text
    assert max(len(line) for line in text.splitlines()) <= 80
    assert any("also holds Si_sv_GW" in n for n in report.notices)
    # Everything the template does not fill is the shipped recipe's.
    shipped = tomllib.loads(
        (CATALOG_ROOT / "si_diamond_100" / "recipe.toml").read_text())
    for table in ("generator", "generation_plan", "labelling"):
        assert raw[table] == shipped[table]
    for table in ("production_settings", "audit_settings"):
        assert raw[table] == shipped[table]
    assert raw["collection1"]["strain"] == shipped["collection1"]["strain"]
    assert raw["collection1"]["warm_runs"] == [
        dict(run, phase="si-diamond")
        for run in shipped["collection1"]["warm_runs"]]

    # The loader refuses it until the domain is decided, then reads it.
    with pytest.raises(SpecificationError, match=r"\[recipe\] -> domain"):
        load_recipe(report.entry.recipe)
    report.entry.recipe.write_text(text.replace(
        f'domain        = "{UNDECIDED_MARKER}"',
        'domain        = "diamond-cubic"'))
    assert load_recipe(report.entry.recipe).domain == "diamond-cubic"


def test_an_unreachable_library_leaves_the_pseudopotentials_to_decide(
        catalog_copy, silicon_as_a_new_chemistry, tmp_path):
    si_cif, _ = silicon_as_a_new_chemistry
    report = add_entry(str(si_cif), "diamond", (1, 0, 0),
                       root=catalog_copy,
                       paw_library=tmp_path / "no_such_library")
    assert report.undecided == [
        "[recipe] -> domain",
        "[production_settings] -> paw -> Si",
        "[audit_settings] -> paw -> Si"]


def test_the_cutoff_rule_on_a_compound_and_a_skewed_surface_cell():
    """Quartz: shells are counted on the silicon sublattice. And a
    skewed description of a square lattice is as wide as the square."""
    quartz = load_crystal(
        CATALOG_ROOT / "sio2_quartz_001" / "sio2_alpha_quartz.cif")
    assert estimate_descriptor_cutoff(quartz) == 4.6
    assert repeats_to_clear(3.84, 4.2) == 3
    skewed = [[3.84, 0.0, 0.0], [-3.84, 3.84, 0.0], [0.0, 0.0, 30.0]]
    assert in_plane_widths(skewed) == pytest.approx([3.84, 3.84])


def test_cli_catalog_list_and_verbs(capsys):
    assert main(["catalog", "list"]) == 0
    out = capsys.readouterr().out
    assert "si_diamond_100" in out and "sio2_quartz_001" in out
    # A formula no crystal has, so no clone's catalog can hold it.
    assert main(["catalog", "list", "Xx9"]) == 0
    assert "no entries of formula Xx9" in capsys.readouterr().out


def test_cli_catalog_add_needs_only_crystal_phase_and_face(capsys):
    """The parser takes `add` with no label and no --formula; the old
    --structure flag is gone. A missing crystal halts before any
    write, so the repository's own catalog is never touched."""
    assert main(["catalog", "add", "--cif", "/no/such/crystal.cif",
                 "--phase", "wurtzite", "--face", "0", "0", "1"]) == 1
    assert "no crystal file" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main(["catalog", "add", "--cif", "/no/such/crystal.cif",
              "--structure", "wurtzite", "--face", "0", "0", "1"])
