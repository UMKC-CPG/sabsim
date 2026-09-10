"""Unit tests for the descriptor engine adapter and the environment
library (DESIGN §3.5 / §4.8 part 2, PSEUDOCODE §10.6 / §11.2).

No LAMMPS runs here: the adapter's PARAMETER derivation, script and
dump parsing are pure; the library's assembly is tested with an
injected descriptor function; and the project-side checks use the
shipped template's pair with the hand-built library of ``support``. The
real ``compute sna/atom`` run is LEDGER T-35.
"""

from __future__ import annotations

import os
from dataclasses import replace

import numpy as np
import pytest
from ase import Atoms

from sabsim.driver.descriptors import (
    DESCRIPTOR_ENGINE_NAME,
    DescriptorSettings,
    descriptor_script,
    neighbour_cutoff,
    read_dump_columns,
    sna_compute_commands,
    to_lammps_parameters,
)
from sabsim.driver.environment_library import (
    build_environment_library,
    check_library_against_project,
    disordered_atoms,
    DISTANCE_METRIC,
    false_alarm_rate,
    LIBRARY_ARRAYS_FILE,
    LIBRARY_MANIFEST_FILE,
    load_environment_library,
    read_environment_library,
    warm_ruler,
    write_environment_library,
)
from sabsim.spec.loader import SpecificationError, load_and_validate_project
from sabsim.spec.records import Quantity
from tests.unit.support import COLD_VECTOR, THERMAL_SCATTER, hand_built_library

_TEMPLATE = os.path.abspath(os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "share", "templates", "project_spec.toml"))


def _template_pair():
    """The shipped template's pair; wafer A is Si(100), the face the
    hand-built library catalogues."""
    return load_and_validate_project(_TEMPLATE).pair


def _settings(cutoff=2.6, order=6, weights=None):
    return DescriptorSettings(
        descriptor_cutoff=cutoff, expansion_order=order,
        species_weights=weights or {"Si": 1.0, "O": 0.5})


# ---------------------------------------------------------------------
# The adapter: physical cutoff -> LAMMPS parameters (ARCHITECTURE §2.3).
# ---------------------------------------------------------------------

def test_every_pair_cutoff_equals_the_physical_descriptor_cutoff():
    """SNAP cuts at rcutfac x (R_i + R_j); the derivation makes that the
    physical cutoff for EVERY species pair (the T-35 trap, closed)."""
    rcutfac, _rfac0, twojmax, radii, weights = to_lammps_parameters(
        _settings(cutoff=2.6), ["Si", "O"])
    for radius_i in radii:
        for radius_j in radii:
            assert rcutfac * (radius_i + radius_j) == pytest.approx(2.6)
    assert twojmax == 6
    assert weights == [1.0, 0.5]


def test_a_species_without_a_weight_is_a_loud_error():
    with pytest.raises(ValueError, match="species weight"):
        to_lammps_parameters(_settings(weights={"Si": 1.0}), ["Si", "O"])


def test_neighbour_list_reaches_past_the_snap_cutoff():
    """LAMMPS refuses a compute wider than its neighbour list (T-35)."""
    settings = _settings(cutoff=2.6)
    assert neighbour_cutoff(settings) > 2.6
    script = descriptor_script("x.data", settings, ["Si", "O"], "x.dump")
    pair_line = next(line for line in script
                     if line.startswith("pair_style zero"))
    assert float(pair_line.split()[-1]) >= neighbour_cutoff(settings)
    assert "boundary p p p" in script


def test_compute_lines_name_the_derived_parameters_and_dump_by_id():
    lines = sna_compute_commands(_settings(), ["Si", "O"], "out.dump")
    assert lines[0].startswith("compute sna all sna/atom 1 0.99363 6 ")
    assert "1.3 1.3 1 0.5" in lines[0]
    assert "c_sna[*]" in lines[1] and "sort id" in lines[2]
    assert lines[-1] == "run 0"


def test_read_dump_columns_returns_components_in_id_order(tmp_path):
    """Rows are sorted by atom id and only the c_sna columns are kept."""
    dump = tmp_path / "d.dump"
    dump.write_text(
        "ITEM: TIMESTEP\n0\nITEM: NUMBER OF ATOMS\n2\n"
        "ITEM: BOX BOUNDS pp pp pp\n0 1\n0 1\n0 1\n"
        "ITEM: ATOMS id type x y z c_sna[1] c_sna[2]\n"
        "2 1 0 0 0 0.5 0.6\n"
        "1 1 0 0 0 0.1 0.2\n")
    columns = read_dump_columns(str(dump))
    assert columns.shape == (2, 2)
    assert list(columns[0]) == pytest.approx([0.1, 0.2])
    assert list(columns[1]) == pytest.approx([0.5, 0.6])


def test_read_dump_columns_without_components_is_an_error(tmp_path):
    dump = tmp_path / "d.dump"
    dump.write_text("ITEM: ATOMS id type x y z\n1 1 0 0 0\n")
    with pytest.raises(ValueError, match="c_sna"):
        read_dump_columns(str(dump))


# ---------------------------------------------------------------------
# The two questions the gate asks of a library (PSEUDOCODE §10.6).
# ---------------------------------------------------------------------

def test_disordered_atoms_flags_a_strange_neighbourhood_not_a_jittered_one():
    library = hand_built_library()
    jittered = COLD_VECTOR + np.array([0.0, 0.5 * THERMAL_SCATTER, 0, 0])
    strange = COLD_VECTOR + np.array([0.0, 0.0, 10.0 * THERMAL_SCATTER, 0])
    flags = disordered_atoms(
        np.array([COLD_VECTOR, jittered, strange]), ["Si", "Si", "Si"],
        library, scatter_multiple=3.0)
    assert list(flags) == [False, False, True]


def test_the_ruler_counts_an_unexplored_direction_at_full_weight():
    """DESIGN §3.5 (2026-09-10): a displacement thermal motion never
    makes is disorder however small it is in absolute terms, while a
    large one along the thermal direction is not."""
    library = hand_built_library()
    along_thermal = COLD_VECTOR + np.array([0.0, 0.8 * THERMAL_SCATTER,
                                            0.0, 0.0])
    tiny_but_strange = COLD_VECTOR + np.array([0.0, 0.0,
                                               0.2 * THERMAL_SCATTER, 0.0])
    flags = disordered_atoms(
        np.array([along_thermal, tiny_but_strange]), ["Si", "Si"],
        library, scatter_multiple=3.0)
    assert list(flags) == [False, True]


def test_warm_ruler_floors_a_still_direction_instead_of_blowing_up():
    """A direction with zero spread gets the ridge floor, so the
    whitening is finite and the ruler still works there."""
    rng = np.random.default_rng(1)
    rows = np.zeros((50, 3))
    rows[:, 0] = rng.normal(0.0, 2.0, 50)       # one live direction
    rows[:, 1] = rng.normal(0.0, 0.5, 50)       # a quieter one
    mean, whitening = warm_ruler(rows)          # axis 2 never moves
    assert np.all(np.isfinite(whitening))
    unit = np.eye(3)
    scaled = np.linalg.norm(unit @ whitening, axis=1)
    # Loud direction scaled down, quiet one less, still one most of all,
    # but by the floor, not to infinity.
    assert scaled[0] < scaled[1] < scaled[2] < 1.0e4


def test_an_uncatalogued_species_cannot_be_judged():
    with pytest.raises(SpecificationError, match="'O'"):
        disordered_atoms(np.array([COLD_VECTOR]), ["O"],
                         hand_built_library(), 3.0)


def test_false_alarm_rate_follows_the_scatter_multiple():
    """At a multiple of one some warm atoms are flagged; at three, none.

    The baseline is recomputed from the recorded warm-run distances at
    whatever multiple the PROJECT names, never frozen at the recipe's.
    """
    library = hand_built_library()
    tight = false_alarm_rate(library, "Si", scatter_multiple=0.5)
    loose = false_alarm_rate(library, "Si", scatter_multiple=3.0)
    assert 0.0 < tight < 1.0
    assert loose == 0.0


# ---------------------------------------------------------------------
# The on-disk pair (PSEUDOCODE §11.3).
# ---------------------------------------------------------------------

def test_library_round_trips_through_npz_and_toml(tmp_path):
    library = hand_built_library()
    manifest = write_environment_library(library, tmp_path)
    assert manifest.name == LIBRARY_MANIFEST_FILE
    assert (tmp_path / LIBRARY_ARRAYS_FILE).is_file()
    text = manifest.read_text()
    assert "DPA-3.1-3M" in text and DESCRIPTOR_ENGINE_NAME in text

    for path in (manifest, tmp_path):        # the file, or its directory
        back = read_environment_library(path)
        assert back.model_name == library.model_name
        assert back.settings == library.settings
        assert back.thermal_scatter == library.thermal_scatter
        assert back.warm_run_temperature == 600.0
        np.testing.assert_allclose(
            back.environments["Si"], library.environments["Si"])
        np.testing.assert_allclose(
            back.warm_distances["Si"], library.warm_distances["Si"])
        np.testing.assert_allclose(
            back.whitening["Si"], library.whitening["Si"])
        np.testing.assert_allclose(back.warm_mean["Si"],
                                   library.warm_mean["Si"])
        assert back.self_check == library.self_check
        assert back.provenance["surfaces"][0]["face"] == "100"
    assert f'distance_metric = "{DISTANCE_METRIC}"' in text


def test_a_library_built_under_another_ruler_is_refused(tmp_path):
    """No silent fallback: an old-format library names its rebuild."""
    manifest = write_environment_library(hand_built_library(), tmp_path)
    old = manifest.read_text().replace(
        f'distance_metric = "{DISTANCE_METRIC}"',
        'distance_metric = "plain-euclidean"')
    manifest.write_text(old)
    with pytest.raises(SpecificationError, match="rebuild it"):
        read_environment_library(manifest)
    manifest.write_text("\n".join(
        line for line in old.split("\n")
        if not line.startswith("distance_metric")))
    with pytest.raises(SpecificationError, match="ruler None"):
        read_environment_library(manifest)


# ---------------------------------------------------------------------
# The project-side checks: three refusals and the temperature band.
# ---------------------------------------------------------------------

def _pair_at(kelvin):
    pair = _template_pair()
    protocol = replace(
        pair.protocol,
        press_temperature=Quantity(value=kelvin, unit="K"))
    return replace(pair, protocol=protocol)


def _check(library, pair):
    """Check against the pair's wafer A (silicon, face 100)."""
    return check_library_against_project(
        library, pair, pair.material.wafer_a)


def test_matching_library_passes_with_no_warning():
    assert _check(hand_built_library(), _pair_at(300.0)) == []


def test_library_from_another_model_is_refused():
    with pytest.raises(SpecificationError, match="rebuild"):
        _check(hand_built_library(model_name="DPA-2.4-7M"),
               _pair_at(300.0))


def test_library_from_another_engine_is_refused():
    with pytest.raises(SpecificationError, match="one engine"):
        _check(hand_built_library(engine="imago-bispectrum"),
               _pair_at(300.0))


def test_library_lacking_the_wafer_face_is_refused():
    only_111 = [{"phase": "silicon-diamond", "face": "111",
                 "termination": 0, "species": ["Si"]}]
    with pytest.raises(SpecificationError, match=r"\(100\)"):
        _check(hand_built_library(surfaces=only_111), _pair_at(300.0))


def test_gate_temperature_a_little_above_the_warm_runs_warns():
    warnings = _check(
        hand_built_library(warm_run_temperature=600.0), _pair_at(660.0))
    assert len(warnings) == 1 and "a little tight" in warnings[0]


def test_gate_temperature_far_above_the_warm_runs_is_refused():
    with pytest.raises(SpecificationError, match="20 %"):
        _check(hand_built_library(warm_run_temperature=600.0),
               _pair_at(750.0))


def _pair_prepared_in(pair, project_directory):
    """The pair with both prep folders moved under ``project_directory``
    — ``prep_surf1_<a>/`` and ``prep_surf2_<b>/`` (ARCHITECTURE §1)."""
    def relocate(wafer, surface_number):
        return replace(wafer, preparation_directory=str(
            project_directory
            / f"prep_surf{surface_number}_{wafer.identity.lower()}"))
    return replace(pair, material=replace(
        pair.material,
        wafer_a=relocate(pair.material.wafer_a, 1),
        wafer_b=relocate(pair.material.wafer_b, 2)))


def test_load_environment_library_finds_the_surfaces_prep_folder(
        tmp_path):
    """The library lives at <project>/prep_surf1_<label>/ and the prep
    folder the loader assigned is the only key (Paul, 2026-08-30)."""
    pair = _pair_prepared_in(_pair_at(300.0), tmp_path)
    wafer = pair.material.wafer_a
    assert wafer.preparation_directory == str(tmp_path / "prep_surf1_si")
    (tmp_path / "prep_surf1_si").mkdir()
    write_environment_library(
        hand_built_library(), tmp_path / "prep_surf1_si")
    library, warnings = load_environment_library(pair, wafer)
    assert library.model_name == "DPA-3.1-3M" and warnings == []

    unprepared = _pair_prepared_in(pair, tmp_path / "elsewhere")
    with pytest.raises(SpecificationError, match="bootstrap generate"):
        load_environment_library(
            unprepared, unprepared.material.wafer_a)


# ---------------------------------------------------------------------
# Manufacturing a library from Collection 1 (PSEUDOCODE §11.2).
# ---------------------------------------------------------------------

class _FakeRecipe:
    """Just the recipe fields build_environment_library reads."""

    def __init__(self, multiple=3.0):
        from types import SimpleNamespace
        self.descriptor_settings = DescriptorSettings(
            descriptor_cutoff=2.6, expansion_order=6,
            species_weights={"Si": 1.0})
        self.gate_scatter_multiple = multiple
        self.generator = SimpleNamespace(model="DPA-3.1-3M")
        self.phases = [SimpleNamespace(
            name="silicon-diamond",
            cif="src/sabsim/structure/data/si_diamond.cif")]
        self.starting_collection = SimpleNamespace(
            warm_runs=[SimpleNamespace(
                temperature=Quantity(value=600.0, unit="K")),
                SimpleNamespace(temperature=Quantity(value=800.0, unit="K"))],
            surfaces=[SimpleNamespace(
                phase="silicon-diamond", face=(1, 0, 0),
                termination_index=0)])


def _frame(tag):
    atoms = Atoms("Si4", positions=np.zeros((4, 3)), cell=np.eye(3) * 10,
                  pbc=True)
    atoms.info["tag"] = tag
    return atoms


def _describe_by_tag(disorder_of_melt):
    """A deterministic stand-in engine keyed on the frame's family tag."""
    generator = np.random.default_rng(3)

    def describe(atoms, settings, work_directory, tag):
        base = np.tile(COLD_VECTOR, (len(atoms), 1))
        if atoms.info["tag"] == "warm":
            base[:, 1] += generator.uniform(0.0, 0.05, size=len(atoms))
        if atoms.info["tag"] == "melt":
            base[:, 2] += disorder_of_melt
        return base
    return describe


def _collection():
    return [("bulk", "si", _frame("bulk")),
            ("strain", "si:+0.02", _frame("strain")),
            ("surface", "si:(100)", _frame("surface")),
            ("rattle", "si:0", _frame("rattle")),
            ("warm_nvt", "si:0:0", _frame("warm")),
            ("warm_npt", "si:0:0", _frame("warm")),
            ("melt_quench", "si:0:0", _frame("melt"))]


def test_build_environment_library_catalogues_the_right_families(tmp_path):
    library = build_environment_library(
        _collection(), _FakeRecipe(), tmp_path,
        describe=_describe_by_tag(disorder_of_melt=5.0))
    # bulk (4) + surface (4) + two warm runs (8): never strain or rattle.
    assert library.environments["Si"].shape[0] == 16
    assert library.provenance["frame_counts"] == {
        "bulk": 1, "surface": 1, "warm_nvt": 1, "warm_npt": 1,
        "melt_quench": 1}
    assert library.thermal_scatter["Si"] > 0.0
    assert library.warm_distances["Si"].shape == (8,)
    assert library.warm_run_temperature == 600.0        # the LOWEST
    assert library.self_check.melt_quench_disordered == 1.0
    assert library.self_check.warm_disordered <= 0.10
    assert library.provenance["surfaces"] == [
        {"phase": "silicon-diamond", "face": "100", "termination": 0,
         "species": ["Si"]}]
    assert library.engine == DESCRIPTOR_ENGINE_NAME


def test_generate_refuses_a_library_that_cannot_tell_glass_from_crystal(
        tmp_path):
    """Melt-quench atoms indistinguishable from warm ones: refused."""
    with pytest.raises(RuntimeError, match="cannot separate"):
        build_environment_library(
            _collection(), _FakeRecipe(), tmp_path,
            describe=_describe_by_tag(disorder_of_melt=0.0))
