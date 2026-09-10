"""Unit tests for the bootstrap's first slice (DESIGN.md §4.8, §11).

No LAMMPS and no VASP: the recipe loader, the static Collection-1
families, the dynamic families' SCRIPTS, the sub-cell cut, the VASP
input writers and the selection rule are all pure Python, so they are
exercised here on the login node. The out-of-process runs are the node
validation logged in the LEDGER.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest
from ase import Atoms
from ase.build import bulk

from sabsim.bootstrap.collection1 import (
    MELT_CHECK_INTERVALS,
    melt_diffusion_ratio,
    verify_melt,
    bulk_family,
    melt_quench_script,
    rattle_family,
    strain_family,
    surface_family,
    warm_run_script,
)
from sabsim.bootstrap.label import (
    BULK_FAMILIES,
    select_for_labelling,
    write_incar,
    write_kpoints,
    write_label_directory,
)
from sabsim.bootstrap.recipe import (
    SpecificationError,
    load_recipe,
)
from sabsim.bootstrap.subcell import (
    atomic_layer_spacing,
    cut_interface_subcell,
)
from sabsim.driver.commands import ForceModel
from sabsim.spec.references import resolve_crystal_file
from sabsim.structure.slab_builder import (
    WAFER_A_TAG,
    WAFER_B_TAG,
    load_crystal,
)

_RECIPE = os.path.abspath(os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "share", "templates", "recipes", "si.toml"))


def _recipe_text() -> str:
    with open(_RECIPE, encoding="utf-8") as handle:
        return handle.read()


# ---------------------------------------------------------------------
# The recipe loader.
# ---------------------------------------------------------------------

def test_template_recipe_loads_with_all_six_families():
    recipe = load_recipe(_RECIPE)
    assert recipe.name == "si-lean-v0"
    assert recipe.species_union == frozenset({"Si"})
    collection = recipe.starting_collection
    assert collection.bulk.cells_per_axis == 2
    assert len(collection.strain.magnitudes) == 6
    assert len(collection.melt_quench) == 1
    assert len(collection.surfaces) == 1
    assert collection.rattle.count == 10
    assert {w.ensemble for w in collection.warm_runs} == {"NVT", "NPT"}
    # Roots are expanded, so no consumer ever sees a literal $SABSIM_SHARE.
    assert "$" not in recipe.generator.weights
    assert "$" not in recipe.production_settings.paw_library
    assert recipe.production_settings.audited is False
    # The gate's ruler (DESIGN §4.8 part 2, 2026-08-29): a physical
    # cutoff in angstrom, the expansion order, one weight per species.
    assert recipe.descriptor_settings.descriptor_cutoff == pytest.approx(4.2)
    assert recipe.descriptor_settings.expansion_order == 6
    assert recipe.descriptor_settings.species_weights == {"Si": 1.0}
    assert recipe.gate_scatter_multiple == pytest.approx(3.0)


def test_recipe_descriptor_must_weight_every_species(tmp_path):
    text = _recipe_text().replace("species_weights       = { Si = 1.0 }",
                                  "species_weights       = { O = 1.0 }")
    path = tmp_path / "recipe.toml"
    path.write_text(text)
    with pytest.raises(SpecificationError, match="species_weights"):
        load_recipe(path)


def test_recipe_missing_key_is_rejected(tmp_path):
    text = _recipe_text().replace("budget_per_family = 10", "")
    path = tmp_path / "recipe.toml"
    path.write_text(text)
    with pytest.raises(SpecificationError) as caught:
        load_recipe(path)
    assert "budget_per_family" in str(caught.value)


def test_recipe_without_an_npt_run_is_rejected(tmp_path):
    text = _recipe_text().replace('ensemble        = "NPT"',
                                  'ensemble        = "NVT"')
    path = tmp_path / "recipe.toml"
    path.write_text(text)
    with pytest.raises(SpecificationError, match="NPT"):
        load_recipe(path)


def test_recipe_family_naming_unknown_phase_is_rejected(tmp_path):
    text = _recipe_text().replace(
        'phase             = "silicon-diamond"\nface',
        'phase             = "silicon-wurtzite"\nface', 1)
    path = tmp_path / "recipe.toml"
    path.write_text(text)
    with pytest.raises(SpecificationError, match="silicon-wurtzite"):
        load_recipe(path)


def test_recipe_paw_must_cover_every_species(tmp_path):
    text = _recipe_text().replace('paw                   = { Si = "Si" }',
                                  'paw                   = { O = "O" }', 1)
    path = tmp_path / "recipe.toml"
    path.write_text(text)
    with pytest.raises(SpecificationError, match="PAW"):
        load_recipe(path)


# ---------------------------------------------------------------------
# Collection 1 — the static families, from a stand-in derived lattice.
# ---------------------------------------------------------------------

def _lattices(recipe):
    """A fake §2.2 result: the CIF crystal as-is, a = 5.43."""
    crystal = load_crystal(resolve_crystal_file(recipe.phases[0].cif))
    return {recipe.phases[0].name: (crystal, 5.43)}


def test_bulk_family_replicates_the_cell():
    recipe = load_recipe(_RECIPE)
    (family, source, atoms), = bulk_family(recipe, _lattices(recipe))
    assert family == "bulk"
    assert len(atoms) == 8 * 2 ** 3          # 8-atom diamond cell, 2x2x2
    assert set(atoms.get_chemical_symbols()) == {"Si"}


def test_strain_family_deforms_cell_and_atoms_together():
    recipe = load_recipe(_RECIPE)
    structures = strain_family(recipe, _lattices(recipe))
    assert len(structures) == 6 * 3          # magnitudes x modes
    reference = bulk_family(recipe, _lattices(recipe))[0][2]
    volumetric = next(
        atoms for family, source, atoms in structures
        if source.endswith("volumetric:+0.100"))
    ratio = volumetric.get_volume() / reference.get_volume()
    assert ratio == pytest.approx(1.1 ** 3, rel=1e-6)
    # Atoms scaled with the cell: fractional coordinates unchanged.
    np.testing.assert_allclose(
        volumetric.get_scaled_positions(), reference.get_scaled_positions(),
        atol=1e-9)


def test_rattle_family_is_seeded_and_small():
    recipe = load_recipe(_RECIPE)
    first = rattle_family(recipe, _lattices(recipe))
    again = rattle_family(recipe, _lattices(recipe))
    assert len(first) == 10
    np.testing.assert_allclose(
        first[3][2].get_positions(), again[3][2].get_positions())
    reference = bulk_family(recipe, _lattices(recipe))[0][2]
    displacement = np.abs(
        first[0][2].get_positions() - reference.get_positions())
    assert displacement.max() < 1.0          # 0.15 A kicks, no explosion


def test_surface_family_cuts_a_slab_with_vacuum():
    recipe = load_recipe(_RECIPE)
    (family, source, slab), = surface_family(recipe, _lattices(recipe))
    assert family == "surface" and "(100)" in source
    z = slab.get_positions()[:, 2]
    assert slab.get_cell()[2, 2] - (z.max() - z.min()) >= 12.0 - 1e-6
    # Tiled 3x3 in plane so the cell is wider than twice the 6 A cutoff.
    assert np.linalg.norm(slab.get_cell()[0]) > 11.0
    assert len(slab) == 9 * 8                    # 8-atom column x 3 x 3


def _model():
    return ForceModel(pair_style="deepmd /m.pth", pair_coeff=("* * Si",),
                      needs_atom_map=True)


def test_melt_quench_script_melts_holds_then_ramps_down():
    recipe = load_recipe(_RECIPE)
    spec = recipe.starting_collection.melt_quench[0]
    script = melt_quench_script(
        spec, "start.data", _model(), 0.001, "frames.dump", seed=11)
    assert "atom_modify map yes" in script
    assert "fix melt all nvt temp 3000 3000 0.1" in script
    assert "run 5000" in script                     # 5 ps at 1 fs
    # Quench 3000 -> 300 K at 200 K/ps = 13.5 ps = 13500 steps.
    assert "fix quench all nvt temp 3000 300 0.1" in script
    assert "run 13500" in script
    assert any(line.startswith("dump frames all custom 1350 ")
               for line in script)                 # 10 frames
    # The hold dumps UNWRAPPED positions at eighths for verify_melt.
    assert any(line.startswith("dump melt_check all custom 625 ")
               and line.endswith("id type xu yu zu") for line in script)
    assert script.index("undump melt_check") < script.index("unfix melt")


def _write_melt_check_dump(path, frames):
    """Write an ``id type xu yu zu`` dump of the given (N, 3) frames."""
    with open(path, "w", encoding="utf-8") as dump:
        for step, positions in enumerate(frames):
            dump.write(f"ITEM: TIMESTEP\n{step}\nITEM: NUMBER OF ATOMS\n"
                       f"{len(positions)}\nITEM: BOX BOUNDS pp pp pp\n"
                       f"0 10\n0 10\n0 10\nITEM: ATOMS id type xu yu zu\n")
            for index, (x, y, z) in enumerate(positions, start=1):
                dump.write(f"{index} 1 {x} {y} {z}\n")


def test_verify_melt_passes_a_liquid_and_refuses_a_hot_crystal(tmp_path):
    """Diffusive travel grows fourfold; vibration saturates at onefold."""
    rng = np.random.default_rng(3)
    sites = rng.uniform(0.0, 10.0, size=(40, 3))
    # A liquid: a random walk, so the mean-square displacement from the
    # half-way frame grows in proportion to the number of intervals.
    walk, position = [], sites.copy()
    for _ in range(MELT_CHECK_INTERVALS + 1):
        walk.append(position.copy())
        position = position + rng.normal(0.0, 0.5, size=sites.shape)
    liquid = tmp_path / "liquid.dump"
    _write_melt_check_dump(liquid, walk)
    assert melt_diffusion_ratio(str(liquid)) > 2.5
    # A crystal, however hot: independent vibrations about fixed sites,
    # so every frame is the same distance from every other.
    vibrating = [sites + rng.normal(0.0, 0.5, size=sites.shape)
                 for _ in range(MELT_CHECK_INTERVALS + 1)]
    crystal = tmp_path / "crystal.dump"
    _write_melt_check_dump(crystal, vibrating)
    assert melt_diffusion_ratio(str(crystal)) < 1.5

    recipe = load_recipe(_RECIPE)
    spec = recipe.starting_collection.melt_quench[0]
    assert verify_melt(str(liquid), spec, "silicon-diamond") > 2.5
    with pytest.raises(RuntimeError, match="never melted.*melt_temperature"):
        verify_melt(str(crystal), spec, "silicon-diamond")


def test_warm_run_script_uses_npt_when_asked():
    recipe = load_recipe(_RECIPE)
    npt = next(w for w in recipe.starting_collection.warm_runs
               if w.ensemble == "NPT")
    script = warm_run_script(
        npt, "start.data", _model(), 0.001, "frames.dump", seed=22)
    assert any(line.startswith("fix warm all npt temp 300 300")
               for line in script)
    assert "run 1000" in script                     # 1 ps equilibration
    assert "run 3000" in script                     # the remaining 3 ps


# ---------------------------------------------------------------------
# The sub-cell cut.
# ---------------------------------------------------------------------

def _joint_cell():
    """Two 40 A silicon-ish columns meeting at z = 40, 80 A cell."""
    z_a = np.arange(0.0, 40.0, 1.0)
    z_b = np.arange(40.5, 80.5, 1.0)
    positions = np.zeros((80, 3))
    positions[:40, 2] = z_a
    positions[40:, 2] = z_b
    atoms = Atoms("Si80", positions=positions,
                  cell=[[5.0, 0, 0], [0, 5.0, 0], [0, 0, 90.0]], pbc=True)
    tags = np.array([WAFER_A_TAG] * 40 + [WAFER_B_TAG] * 40)
    return atoms, tags


def test_subcell_keeps_skin_plus_layers_on_both_sides():
    atoms, tags = _joint_cell()
    cut = cut_interface_subcell(
        atoms, tags, interface_z=40.25, skin_depth=7.0,
        layer_spacing=1.0, crystalline_layers=2, vacuum=10.0)
    # Each side keeps 7 + 2 = 9 A: A keeps z >= 31.25 (32..39, eight
    # atoms), B keeps z <= 49.25 (40.5..48.5, nine atoms).
    assert len(cut) == 17
    z = cut.get_positions()[:, 2]
    assert z.min() == pytest.approx(0.0)
    assert cut.get_cell()[2, 2] == pytest.approx(z.max() + 10.0)
    assert set(cut.get_tags()) == {WAFER_A_TAG, WAFER_B_TAG}
    np.testing.assert_allclose(cut.get_cell()[:2, :2], atoms.get_cell()[:2, :2])


def test_atomic_layer_spacing_for_diamond_100_is_a_over_4():
    assert atomic_layer_spacing(5.43, (1, 0, 0)) == pytest.approx(5.43 / 4)
    assert atomic_layer_spacing(5.43, (1, 1, 1)) == pytest.approx(
        5.43 * np.sqrt(3) / 4)


# ---------------------------------------------------------------------
# The labeller.
# ---------------------------------------------------------------------

def test_incar_carries_the_production_block(tmp_path):
    recipe = load_recipe(_RECIPE)
    write_incar(recipe.production_settings, tmp_path / "INCAR")
    text = (tmp_path / "INCAR").read_text()
    assert "ENCUT  = 350" in text
    assert "ISMEAR = 0" in text and "SIGMA  = 0.1" in text
    assert "EDIFF  = 0.0001" in text and "NELM   = 60" in text
    assert "NSW    = 0" in text and "ISPIN  = 1" in text
    assert "LREAL  = Auto" in text


def test_kpoints_are_gamma_off_bulk_and_a_spacing_on_bulk(tmp_path):
    recipe = load_recipe(_RECIPE)
    write_kpoints(recipe.production_settings, True, tmp_path / "K1")
    write_kpoints(recipe.production_settings, False, tmp_path / "K2")
    assert "Gamma\n1 1 1" in (tmp_path / "K1").read_text()
    assert "Auto\n2.0000" in (tmp_path / "K2").read_text()   # 1 / 0.5
    assert BULK_FAMILIES == {"bulk", "strain"}


def test_label_directory_concatenates_potcar_in_poscar_order(tmp_path):
    from dataclasses import replace
    recipe = load_recipe(_RECIPE)
    library = tmp_path / "potpaw"
    (library / "Si").mkdir(parents=True)
    (library / "Si" / "POTCAR").write_text("PAW_PBE Si 05Jan2001\n")
    settings = replace(
        recipe.production_settings, paw_library=str(library))
    atoms = bulk("Si", "diamond", a=5.43)
    write_label_directory(atoms, settings, tmp_path / "label_0", True)
    for name in ("POSCAR", "INCAR", "KPOINTS", "POTCAR"):
        assert (tmp_path / "label_0" / name).is_file()
    assert "PAW_PBE Si" in (tmp_path / "label_0" / "POTCAR").read_text()


def test_selection_is_even_per_family_within_budget():
    atoms = bulk("Si", "diamond", a=5.43)
    structures = ([("bulk", f"b{i}", atoms) for i in range(3)]
                  + [("pulled", f"p{i}", atoms) for i in range(25)])
    chosen = select_for_labelling(structures, budget_per_family=5)
    families = [family for family, _, _ in chosen]
    assert families.count("bulk") == 3           # fewer than the budget
    assert families.count("pulled") == 5
    picked = [source for family, source, _ in chosen if family == "pulled"]
    assert picked[0] == "p0" and picked[-1] == "p24"   # spans the record


# ---------------------------------------------------------------------
# The ledger-keyed harvest (PSEUDOCODE §11.3, 2026-08-28): frames are
# keyed to a phase by the MD step every dump frame carries.
# ---------------------------------------------------------------------

def _write_dump(path, steps):
    """A minimal two-atom custom dump with one frame per step."""
    lines = []
    for step in steps:
        lines += [
            "ITEM: TIMESTEP", str(step), "ITEM: NUMBER OF ATOMS", "2",
            "ITEM: BOX BOUNDS pp pp ff", "0 5", "0 5", "0 20",
            "ITEM: ATOMS id type x y z",
            f"1 1 0.0 0.0 {1.0 + 0.001 * step}", "2 1 2.5 2.5 3.0"]
    path.write_text("\n".join(lines) + "\n")


def test_dump_frames_carry_their_step_and_key_by_the_ledger(tmp_path):
    from sabsim.bootstrap.harvest import (
        _read_dump,
        frame_at,
        frames_between,
    )
    dump = tmp_path / "press.dump"
    _write_dump(dump, [0, 1000, 2000, 3000, 4000])
    frames = _read_dump(str(dump), {"Si": 1})
    assert [f.info["step"] for f in frames] == [0, 1000, 2000, 3000, 4000]
    assert all(f.get_chemical_symbols() == ["Si", "Si"] for f in frames)
    # Inclusive bounds, open on a None side.
    assert [f.info["step"] for f in frames_between(frames, 1000, 3000)] == [
        1000, 2000, 3000]
    assert [f.info["step"] for f in frames_between(frames, 3000, None)] == [
        3000, 4000]
    # The frame AT a step, or the first after it; nothing for no step.
    assert frame_at(frames, 2000)[0].info["step"] == 2000
    assert frame_at(frames, 2500)[0].info["step"] == 3000
    assert frame_at(frames, None) == []
    assert frame_at(frames, 9000) == []
