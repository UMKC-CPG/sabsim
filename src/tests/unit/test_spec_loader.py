"""Unit tests for the study-spec loader (sabsim.spec.loader).

These tests pin the two contracts the loader exists to enforce
(DESIGN.md §1.4, §1.5): the real §1.4 generator template loads and
validates cleanly, and every way a spec can be incomplete or
un-executable is REJECTED with a clear error rather than silently
accepted or completed. The negative cases start from the real template
and break exactly one thing, so they stay honest as the template
evolves.
"""

import os
import re

import pytest

from sabsim.spec import (
    SpecificationError,
    Study,
    load_and_validate_study,
)

# The real spec the §1.4 generator emits — the happy-path fixture and
# the starting point every negative case mutates.
_TEMPLATE_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "share", "templates", "study_spec.toml"))


def _template_text() -> str:
    """Return the known-good template spec as text to be mutated."""
    with open(_TEMPLATE_PATH, encoding="utf-8") as spec_file:
        return spec_file.read()


def _write_spec(tmp_path, text: str) -> str:
    """Write ``text`` as a spec file under ``tmp_path`` and return it."""
    spec_path = os.path.join(tmp_path, "study.toml")
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

def test_template_loads_into_a_study():
    """The §1.4 generator template validates and parses to a Study."""
    study = load_and_validate_study(_TEMPLATE_PATH)

    assert isinstance(study, Study)
    assert study.name == "sio2-si-sab-v1"
    # v1 has the dissimilar bond plus TWO same-material null tests (§2.7,
    # §7.4): silicon, and the silica one that proves the pipeline is not
    # silicon-only.
    assert tuple(m.name for m in study.members) == (
        "si-sio2", "si-si-reference", "sio2-sio2-reference")


def test_template_values_map_to_the_schema_fields():
    """Representative knobs deserialize onto the right §2 fields."""
    study = load_and_validate_study(_TEMPLATE_PATH)
    member = study.members[0]

    # A physical knob keeps its unit (§1.5). The value tracks whatever
    # the template currently pins (75 eV since 2026-07-21); what is being
    # checked is that it lands on the right field WITH its unit.
    assert member.protocol.activation_energy.value == 75.0
    assert member.protocol.activation_energy.unit == "eV"
    # The force-average window is a DISPLACEMENT, per the §5.4 fix.
    assert member.numerical.force_average_window.unit == "angstrom"
    # The ensemble carries the two counts under their ratified names.
    assert member.ensemble.amorphization_count == 3
    assert member.ensemble.velocity_count == 1
    # The pull-rate ladder is a numerical knob with >= 3 rungs (§5.4).
    assert len(member.numerical.pull_rate_ladder) == 3


def test_environment_library_and_gate_knobs_are_parsed():
    """The §3.5 gate's inputs are study settings, not hidden constants
    (revised 2026-08-29): the library path (roots expanded), the depth
    profile's layer thickness, and the scatter multiple."""
    study = load_and_validate_study(_TEMPLATE_PATH)
    member = study.members[0]
    assert "$" not in member.protocol.environment_library
    assert member.protocol.environment_library.endswith(
        "environment_libraries/silicon")
    assert member.numerical.depth_bin_width.value == pytest.approx(2.0)
    assert member.numerical.depth_bin_width.unit == "angstrom"
    assert member.numerical.disorder_scatter_multiple == pytest.approx(3.0)


def test_missing_gate_knob_is_rejected(tmp_path):
    """No hidden default for the scatter multiple (DESIGN §1.4)."""
    broken = _drop_lines_containing(
        _template_text(), "disorder_scatter_multiple = 3.0")
    spec_path = _write_spec(tmp_path, broken)
    with pytest.raises(SpecificationError, match="disorder_scatter_multiple"):
        load_and_validate_study(spec_path)


def test_relation_is_computed_not_deleted():
    """The single ratio relation loads and is flagged not-confounded."""
    study = load_and_validate_study(_TEMPLATE_PATH)

    assert len(study.relations) == 1
    relation = study.relations[0]
    assert relation.kind == "ratio"
    # One contrast (the material pair) means it is NOT confounded (§1.1).
    assert relation.confounded is False
    assert relation.measures == ("mechanical_work_of_separation",)


def test_absent_cospecies_becomes_none():
    """The 'none' co-species sentinel maps to Python None (§3.2)."""
    study = load_and_validate_study(_TEMPLATE_PATH)
    assert study.members[0].protocol.activation_cospecies is None


# ---------------------------------------------------------------------
# Reject the incomplete spec (DESIGN.md §1.4): a missing key is an error
# that names the key, never a silently filled blank.
# ---------------------------------------------------------------------

def test_missing_required_key_is_rejected(tmp_path):
    """Dropping a required numerical knob fails, naming the knob."""
    broken = _drop_lines_containing(_template_text(), "frame_stride")
    spec_path = _write_spec(tmp_path, broken)

    with pytest.raises(SpecificationError) as caught:
        load_and_validate_study(spec_path)
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
        load_and_validate_study(spec_path)
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
        load_and_validate_study(spec_path)
    assert "type map" in str(caught.value)


def test_unknown_press_mode_is_rejected(tmp_path):
    """A press mode the driver cannot run is rejected (§5.2)."""
    text = _template_text().replace(
        'mode        = "load"', 'mode        = "levitation"')
    spec_path = _write_spec(tmp_path, text)

    with pytest.raises(SpecificationError) as caught:
        load_and_validate_study(spec_path)
    assert "press mode" in str(caught.value)


def test_relation_naming_a_missing_member_is_rejected(tmp_path):
    """A relation over an undefined member cannot be computed (§1.5)."""
    text = _template_text().replace(
        '["si-sio2", "si-si-reference"]',
        '["si-sio2", "ghost-member"]')
    spec_path = _write_spec(tmp_path, text)

    with pytest.raises(SpecificationError) as caught:
        load_and_validate_study(spec_path)
    assert "ghost-member" in str(caught.value)


# ---------------------------------------------------------------------
# material_domain — the second half of the force-model lookup key that
# DESIGN.md §4.8 added, because a species set alone cannot select a form.
# ---------------------------------------------------------------------

def test_every_template_member_declares_a_material_domain():
    """The domain is a required pointer, like potential_ref (§4.8)."""
    study = load_and_validate_study(_TEMPLATE_PATH)
    by_name = {member.name: member for member in study.members}

    # Two members share the {Si, O} species set and would be
    # indistinguishable without the domain; the silicon null test sits
    # in the one domain registered for {Si} alone.
    assert by_name["si-sio2"].material_domain == "silicon-and-silica"
    assert by_name["si-si-reference"].material_domain == "diamond-cubic"
    assert (by_name["sio2-sio2-reference"].material_domain
            == "silicon-and-silica")


def test_missing_material_domain_is_rejected(tmp_path):
    """A member without a domain fails validation, naming the key."""
    broken = _drop_lines_containing(_template_text(), "material_domain")
    spec_path = _write_spec(tmp_path, broken)

    with pytest.raises(SpecificationError) as caught:
        load_and_validate_study(spec_path)
    assert "material_domain" in str(caught.value)


def test_empty_material_domain_is_rejected(tmp_path):
    """An empty domain is refused rather than treated as 'any' (§4.8)."""
    blanked = _template_text().replace(
        'material_domain = "diamond-cubic"', 'material_domain = ""', 1)
    spec_path = _write_spec(tmp_path, blanked)

    with pytest.raises(SpecificationError) as caught:
        load_and_validate_study(spec_path)
    message = str(caught.value)
    assert "material_domain" in message
    # The message explains WHY the species alone will not do.
    assert "species" in message


# ---------------------------------------------------------------------
# [potential] — the force models the study runs under (§1.6, §4.7). A
# study-level block, required in full, with location roots expanded.
# ---------------------------------------------------------------------

def test_template_potential_block_names_both_models():
    """Every member carries the study's [potential] block, roots expanded."""
    study = load_and_validate_study(_TEMPLATE_PATH)
    for member in study.members:
        potential = member.potential
        assert potential.universal_model == "DPA-3.1-3M"
        assert potential.universal_weights.endswith("dpa3.pth")
        assert "$" not in potential.universal_weights    # root expanded
        assert potential.production_weights.endswith("dpa3.pth")
        assert potential.allow_unvalidated is True


def test_missing_potential_block_is_rejected(tmp_path):
    """A study with no [potential] block cannot say what it runs under."""
    text = _template_text().replace("[potential]", "[potential_gone]", 1)
    spec = tmp_path / "spec.toml"
    spec.write_text(text)
    with pytest.raises(SpecificationError) as caught:
        load_and_validate_study(spec)
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
        load_and_validate_study(spec)
    assert "sabsimrc" in str(caught.value)


def test_contact_test_settings_are_study_knobs_with_units():
    """The press's two contact-test settings come from the study file.

    DESIGN §5.2 (revised 2026-08-28): the trailing-mean window over the
    surface-to-surface opening and the sustained-stress floor were once
    constants inside the driver; a value the run uses must be visible in
    the study file (DESIGN §1.4), so both are knobs here.
    """
    numerical = load_and_validate_study(_TEMPLATE_PATH).members[0].numerical
    assert numerical.contact_gap_window == 3
    assert numerical.contact_stress_floor.value == 500.0
    assert numerical.contact_stress_floor.unit == "bar"
