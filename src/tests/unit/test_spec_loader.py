"""Unit tests for the project-file loader (sabsim.spec.loader).

These tests pin the two contracts the loader exists to enforce
(DESIGN.md §1.4, §1.5): the real §1.4 generator template loads and
validates cleanly, and every way a file can be incomplete or
un-executable is REJECTED with a clear error rather than silently
accepted or completed. The negative cases start from the real template
and break exactly one thing, so they stay honest as the template
evolves.
"""

import os
import re
from pathlib import Path

import pytest

from sabsim.spec import (
    Project,
    SpecificationError,
    load_and_validate_project,
    stage_folders,
)

# The real project file the §1.4 generator emits — the happy-path
# fixture and the starting point every negative case mutates.
_TEMPLATE_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "share", "templates", "project_spec.toml"))


def _template_text() -> str:
    """Return the known-good template as text to be mutated."""
    with open(_TEMPLATE_PATH, encoding="utf-8") as spec_file:
        return spec_file.read()


def _write_spec(tmp_path, text: str) -> str:
    """Write ``text`` as a project file under ``tmp_path``; return it."""
    spec_path = os.path.join(tmp_path, "sabsim.toml")
    with open(spec_path, "w", encoding="utf-8") as spec_file:
        spec_file.write(text)
    return spec_path


def _drop_lines_containing(text: str, needle: str) -> str:
    """Remove every line containing ``needle`` (to omit a required key)."""
    return "\n".join(
        line for line in text.splitlines() if needle not in line)


# ---------------------------------------------------------------------
# Happy path: the real template loads and the values land where §2 says.
# ---------------------------------------------------------------------

def test_template_loads_into_a_project_holding_one_pair():
    """The §1.4 generator template validates and parses to a Project."""
    project = load_and_validate_project(_TEMPLATE_PATH)

    assert isinstance(project, Project)
    assert project.description.startswith("Cold SAB")
    # ONE pair per project (Paul, 2026-08-30): the dissimilar bond. The
    # Si/Si reference is a separate project the person runs.
    assert project.pair.pair_label == "si_sio2"
    assert project.project_directory == str(
        Path(_TEMPLATE_PATH).resolve().parent)


def test_stage_folders_are_named_from_the_lower_cased_labels():
    """The four folder names come from ONE place (PSEUDOCODE §2)."""
    pair = load_and_validate_project(_TEMPLATE_PATH).pair
    folders = stage_folders(pair)
    assert folders.prep_surf1 == "prep_surf1_si"
    assert folders.prep_surf2 == "prep_surf2_sio2"
    assert folders.bond == "bond_si_sio2"
    assert folders.analysis == "analysis_si_sio2"


def test_a_same_material_pair_still_has_two_prep_folders(tmp_path):
    """Si/Si: surface 1 and surface 2 are prepared apart, each with its
    own seed, so `prep_surf1_si/` and `prep_surf2_si/` both exist."""
    text = _template_text().replace(
        '[wafer_b]\nmaterial  = "SiO2"', '[wafer_b]\nmaterial  = "Si"', 1)
    text = text.replace(
        'cif       = "share/catalog/sio2_quartz_001/sio2_alpha_quartz.cif"',
        'cif       = "share/catalog/si_diamond_100/si_diamond.cif"', 1)
    assert text != _template_text()
    pair = load_and_validate_project(_write_spec(tmp_path, text)).pair
    folders = stage_folders(pair)
    assert pair.pair_label == "si_si"
    assert (folders.prep_surf1, folders.prep_surf2) == (
        "prep_surf1_si", "prep_surf2_si")
    assert folders.bond == "bond_si_si"


def test_template_values_map_to_the_schema_fields():
    """Representative knobs deserialize onto the right §2 fields."""
    pair = load_and_validate_project(_TEMPLATE_PATH).pair

    # A physical knob keeps its unit (§1.5). The value tracks whatever
    # the template currently pins (75 eV since 2026-07-21); what is being
    # checked is that it lands on the right field WITH its unit.
    assert pair.protocol.activation_energy.value == 75.0
    assert pair.protocol.activation_energy.unit == "eV"
    # The force-average window is a DISPLACEMENT, per the §5.4 fix.
    assert pair.numerical.force_average_window.unit == "angstrom"
    # The ensemble carries the two counts under their ratified names.
    assert pair.ensemble.amorphization_count == 3
    assert pair.ensemble.velocity_count == 1
    # The pull-rate ladder is a numerical knob with >= 3 rungs (§5.4).
    assert len(pair.numerical.pull_rate_ladder) == 3


def test_prep_folders_and_gate_knobs_are_parsed():
    """The §3.5 gate's inputs are project settings, not hidden constants
    (revised 2026-08-30): each surface's prep folder (the project folder
    plus `prep_surf<N>_<label>`, ARCHITECTURE §1 — never a typed path),
    the depth profile's layer thickness, and the scatter multiple."""
    project = load_and_validate_project(_TEMPLATE_PATH)
    pair = project.pair
    project_directory = Path(project.project_directory)
    assert pair.material.wafer_a.preparation_directory == str(
        project_directory / "prep_surf1_si")
    assert pair.material.wafer_b.preparation_directory == str(
        project_directory / "prep_surf2_sio2")
    assert pair.numerical.depth_bin_width.value == pytest.approx(2.0)
    assert pair.numerical.depth_bin_width.unit == "angstrom"
    assert pair.numerical.disorder_scatter_multiple == pytest.approx(3.0)


def test_missing_gate_knob_is_rejected(tmp_path):
    """No hidden default for the scatter multiple (DESIGN §1.4)."""
    broken = _drop_lines_containing(
        _template_text(), "disorder_scatter_multiple = 3.0")
    spec_path = _write_spec(tmp_path, broken)
    with pytest.raises(SpecificationError, match="disorder_scatter_multiple"):
        load_and_validate_project(spec_path)


def test_a_material_label_that_cannot_name_a_folder_is_rejected(
        tmp_path):
    """The label names the prep folder, so a path separator in it is
    refused at load, not discovered as a strange directory later."""
    text = _template_text().replace(
        'material  = "SiO2"', 'material  = "Si/O2"', 1)
    with pytest.raises(SpecificationError, match="prep folder"):
        load_and_validate_project(_write_spec(tmp_path, text))


def test_absent_cospecies_becomes_none():
    """The 'none' co-species sentinel maps to Python None (§3.2)."""
    pair = load_and_validate_project(_TEMPLATE_PATH).pair
    assert pair.protocol.activation_cospecies is None


# ---------------------------------------------------------------------
# Reject the incomplete spec (DESIGN.md §1.4): a missing key is an error
# that names the key, never a silently filled blank.
# ---------------------------------------------------------------------

def test_missing_required_key_is_rejected(tmp_path):
    """Dropping a required numerical knob fails, naming the knob."""
    broken = _drop_lines_containing(_template_text(), "frame_stride")
    spec_path = _write_spec(tmp_path, broken)

    with pytest.raises(SpecificationError) as caught:
        load_and_validate_project(spec_path)
    assert "frame_stride" in str(caught.value)


def test_bare_number_without_unit_is_rejected(tmp_path):
    """A physical knob given as a bare number fails the units rule.

    The energy line is matched by PATTERN, not by its literal text. An
    exact-text match silently stops rewriting anything the day the pinned
    energy changes — which is precisely what happened when 500 eV became
    75 eV — leaving a test that constructs a perfectly VALID spec and
    then reports success for a rejection that never occurred. The
    assertion below that the text actually changed is what keeps this
    test honest about having done its own setup.
    """
    original = _template_text()
    text, substitutions = re.subn(
        r'energy = \{ value = ([0-9.]+), unit = "eV" \}',
        r"energy = \1", original)
    assert substitutions == 1, (
        "the energy knob was not rewritten as a bare number, so this "
        "test would prove nothing — has the template's spelling changed?")
    spec_path = _write_spec(tmp_path, text)

    with pytest.raises(SpecificationError) as caught:
        load_and_validate_project(spec_path)
    assert "unit" in str(caught.value).lower()


# ---------------------------------------------------------------------
# Reject the un-executable spec (DESIGN.md §1.5): things that would stop
# the run, caught early with a reason.
# ---------------------------------------------------------------------

def test_species_outside_type_map_is_rejected(tmp_path):
    """A projectile the potential does not know cannot be run (§1.5)."""
    text = _template_text().replace(
        'species   = "Ar"', 'species   = "Xe"')
    spec_path = _write_spec(tmp_path, text)

    with pytest.raises(SpecificationError) as caught:
        load_and_validate_project(spec_path)
    assert "type map" in str(caught.value)


def test_unknown_press_mode_is_rejected(tmp_path):
    """A press mode the driver cannot run is rejected (§5.2)."""
    text = _template_text().replace(
        'mode        = "load"', 'mode        = "levitation"')
    spec_path = _write_spec(tmp_path, text)

    with pytest.raises(SpecificationError) as caught:
        load_and_validate_project(spec_path)
    assert "press mode" in str(caught.value)


# ---------------------------------------------------------------------
# material_domain — the second half of the force-model lookup key that
# DESIGN.md §4.8 added, because a species set alone cannot select a form.
# ---------------------------------------------------------------------

def test_the_template_pair_declares_a_material_domain():
    """The domain is a required pointer, like potential_ref (§4.8).

    A silica-only pair would share the {Si, O} species set with this
    one and be indistinguishable without it.
    """
    pair = load_and_validate_project(_TEMPLATE_PATH).pair
    assert pair.material_domain == "silicon-and-silica"
    assert pair.potential_ref == "PENDING-BOOTSTRAP"


def test_missing_material_domain_is_rejected(tmp_path):
    """A pair without a domain fails validation, naming the key."""
    broken = _drop_lines_containing(_template_text(), "material_domain")
    spec_path = _write_spec(tmp_path, broken)

    with pytest.raises(SpecificationError) as caught:
        load_and_validate_project(spec_path)
    assert "material_domain" in str(caught.value)


def test_empty_material_domain_is_rejected(tmp_path):
    """An empty domain is refused rather than treated as 'any' (§4.8)."""
    blanked = _template_text().replace(
        'material_domain = "silicon-and-silica"', 'material_domain = ""',
        1)
    spec_path = _write_spec(tmp_path, blanked)

    with pytest.raises(SpecificationError) as caught:
        load_and_validate_project(spec_path)
    message = str(caught.value)
    assert "material_domain" in message
    # The message explains WHY the species alone will not do.
    assert "species" in message


# ---------------------------------------------------------------------
# [potential] — the force models the project runs under (§1.6, §4.7).
# One block, required in full, with location roots expanded.
# ---------------------------------------------------------------------

def test_template_potential_block_names_both_models():
    """The pair carries the [potential] block with its roots expanded."""
    potential = load_and_validate_project(_TEMPLATE_PATH).pair.potential
    assert potential.universal_model == "DPA-3.1-3M"
    assert potential.universal_weights.endswith("dpa3.pth")
    assert "$" not in potential.universal_weights    # root expanded
    assert potential.production_weights.endswith("dpa3.pth")
    assert potential.allow_unvalidated is True


def test_missing_potential_block_is_rejected(tmp_path):
    """A project with no [potential] block cannot say what it runs under."""
    text = _template_text().replace("[potential]", "[potential_gone]", 1)
    spec = tmp_path / "spec.toml"
    spec.write_text(text)
    with pytest.raises(SpecificationError) as caught:
        load_and_validate_project(spec)
    assert "potential" in str(caught.value)


def test_unset_location_root_in_a_weights_path_is_rejected(
        tmp_path, monkeypatch):
    """A weights path using an unset root fails now, not inside LAMMPS."""
    monkeypatch.delenv("SABSIM_NOWHERE", raising=False)
    text = _template_text().replace(
        'production_weights = "$SABSIM_SHARE',
        'production_weights = "$SABSIM_NOWHERE', 1)
    spec = tmp_path / "spec.toml"
    spec.write_text(text)
    with pytest.raises(SpecificationError) as caught:
        load_and_validate_project(spec)
    assert "sabsimrc" in str(caught.value)


def test_contact_test_settings_are_project_knobs_with_units():
    """The press's two contact-test settings come from the project file.

    DESIGN §5.2 (revised 2026-08-28): the trailing-mean window over the
    surface-to-surface opening and the sustained-stress floor were once
    constants inside the driver; a value the run uses must be visible in
    the project file (DESIGN §1.4), so both are knobs here.
    """
    numerical = load_and_validate_project(_TEMPLATE_PATH).pair.numerical
    assert numerical.contact_gap_window == 3
    assert numerical.contact_stress_floor.value == 500.0
    assert numerical.contact_stress_floor.unit == "bar"


# ---------------------------------------------------------------------
# The wafer's termination (DESIGN.md §2.5): a required key, a whole
# number, and never the undecided marker.
# ---------------------------------------------------------------------

def test_the_termination_lands_on_each_wafer(tmp_path):
    text = _template_text().replace(
        "termination_index = 0", "termination_index = 1", 1)
    pair = load_and_validate_project(_write_spec(tmp_path, text)).pair
    assert pair.material.wafer_a.termination_index == 1
    assert pair.material.wafer_b.termination_index == 0


def test_a_project_without_a_termination_is_refused(tmp_path):
    """No hidden default: the first of the builder's list was one."""
    text = _drop_lines_containing(_template_text(), "termination_index =")
    with pytest.raises(SpecificationError,
                       match="missing required key 'termination_index'"):
        load_and_validate_project(_write_spec(tmp_path, text))


@pytest.mark.parametrize("written, complaint", [
    ('"DECIDE"', "the choice is yours"),
    ("-1", "whole number, 0 or more"),
    ("1.5", "whole number, 0 or more"),
    ("true", "whole number, 0 or more"),
])
def test_a_termination_that_is_not_a_choice_is_refused(
        tmp_path, written, complaint):
    text = _template_text().replace(
        "termination_index = 0", f"termination_index = {written}", 1)
    with pytest.raises(SpecificationError, match=complaint):
        load_and_validate_project(_write_spec(tmp_path, text))
