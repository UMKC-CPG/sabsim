"""Unit tests for the cascade potential resolver (DESIGN.md §4.7).

The resolver is a pure lookup-plus-assembly with no LAMMPS present, so
these tests assert the emitted :class:`ForceModel` strings directly: that
silicon resolves to the expected ``hybrid/overlay`` of Stillinger-Weber
with two ZBL cores, that the two cores are assigned from the species set
(projectile-substrate to the long core, substrate-substrate to the short
one), that a projectile type is handed ``NULL`` so the classical form
ignores it, and that the two refusals fire — an unregistered substrate
and a documented-but-untested one. These pin the generalization that
keeps the cascade from being silicon-crafted.
"""

import pytest

from sabsim.driver.cascade_potential import (
    CASCADE_GENERATOR_REGISTRY,
    domains_for_species,
    registered_material_domains,
    resolve_cascade_generator,
)


# A silicon slab bombarded by argon: substrate type 1, projectile type 2.
SILICON_ARGON_TYPE_MAP = {"Si": 1, "Ar": 2}


def test_silicon_resolves_to_hybrid_overlay_with_two_zbl_cores():
    """Silicon is the one validated entry and assembles cleanly (§4.7)."""
    force_model = resolve_cascade_generator(
        SILICON_ARGON_TYPE_MAP, projectile_species={"Ar"})

    # The style splices Stillinger-Weber with two ZBL cores; the long one
    # (2.0 A outer) is listed first, the short one (1.2 A) second.
    assert force_model.pair_style == (
        "hybrid/overlay sw zbl 0.5 2 zbl 0.5 1.2")


def test_classical_line_labels_projectile_null():
    """The projectile is NULL to the classical form (neutral, §3.2)."""
    force_model = resolve_cascade_generator(
        SILICON_ARGON_TYPE_MAP, projectile_species={"Ar"})

    # First pair_coeff is the classical sub-style: Si is an SW element,
    # Ar (the projectile) is NULL so Stillinger-Weber never sees it.
    assert force_model.pair_coeff[0] == "* * sw Si.sw Si NULL"


def test_zbl_cores_assigned_from_species_set():
    """Substrate-substrate -> short core; projectile pairs -> long core."""
    force_model = resolve_cascade_generator(
        SILICON_ARGON_TYPE_MAP, projectile_species={"Ar"})
    zbl_lines = force_model.pair_coeff[1:]

    # Si-Si (types 1 1): the SHORT substrate-substrate core, index 2,
    # carrying both silicon atomic numbers (14).
    assert "1 1 zbl 2 14 14" in zbl_lines
    # Si-Ar (types 1 2): the LONG projectile-substrate core, index 1,
    # with silicon (14) and argon (18).
    assert "1 2 zbl 1 14 18" in zbl_lines
    # Ar-Ar (types 2 2): also the long core, since it involves the
    # projectile.
    assert "2 2 zbl 1 18 18" in zbl_lines
    # Exactly the three upper-triangle pairs, no duplicates.
    assert len(zbl_lines) == 3


def test_unregistered_substrate_refuses_with_helpful_message():
    """A substrate with no entry raises, naming what IS registered."""
    with pytest.raises(KeyError) as caught:
        resolve_cascade_generator(
            {"Ge": 1, "Ar": 2}, projectile_species={"Ar"})
    message = str(caught.value)
    assert "Ge" in message
    # The message lists the registered silicon set as an alternative.
    assert "{Si}" in message


def test_untested_candidate_refuses_loudly():
    """A documented-but-untested entry refuses rather than running (§4.7)."""
    with pytest.raises(NotImplementedError) as caught:
        resolve_cascade_generator(
            {"Si": 1, "O": 2, "Ar": 3}, projectile_species={"Ar"},
            domain="silicon-and-silica")
    message = str(caught.value)
    # It carries the entry's own caveat so the reason is diagnosable.
    assert "UNTESTED" in message
    assert "§3.5" in message
    # And it names the domain, so which of the two {Si, O} forms was
    # asked for is recoverable from the message alone.
    assert "silicon-and-silica" in message


def test_ambiguous_species_refuse_without_a_domain():
    """{Si, O} carries two entries, so the species alone cannot decide.

    This is the refusal that replaces the old ``_silica_only`` marker
    (DESIGN §4.8). The two forms disagree about whether elemental silicon
    can exist at all, so guessing between them would be a silent physics
    decision made on the caller's behalf.
    """
    with pytest.raises(KeyError) as caught:
        resolve_cascade_generator(
            {"Si": 1, "O": 2, "Ar": 3}, projectile_species={"Ar"})
    message = str(caught.value)
    assert "more than one" in message
    # Both candidates are named, so the caller can pick without reading
    # the registry source.
    assert "silica-only" in message
    assert "silicon-and-silica" in message


def test_naming_the_domain_selects_between_two_same_species_forms():
    """The domain picks the form; the species set alone never could."""
    interface_form = resolve_cascade_generator(
        {"Si": 1, "O": 2, "Ar": 3}, projectile_species={"Ar"},
        domain="silicon-and-silica", allow_unvalidated=True)
    silica_form = resolve_cascade_generator(
        {"Si": 1, "O": 2, "Ar": 3}, projectile_species={"Ar"},
        domain="silica-only", allow_unvalidated=True)

    # Same species, same projectile, genuinely different physics.
    assert "tersoff" in interface_form.pair_style
    assert "vashishta" in silica_form.pair_style


def test_unknown_domain_names_the_ones_that_exist():
    """A misspelled domain lists the real ones rather than falling back."""
    with pytest.raises(KeyError) as caught:
        resolve_cascade_generator(
            {"Si": 1, "O": 2, "Ar": 3}, projectile_species={"Ar"},
            domain="cristobalite")
    message = str(caught.value)
    assert "cristobalite" in message
    assert "silica-only" in message


def test_no_marker_species_survives_in_any_key():
    """The ``_silica_only`` fake element is gone from the registry.

    It was a non-element string smuggled into a set of chemical symbols
    to keep two {Si, O} entries apart. Every key component must now be a
    real element symbol (DESIGN §4.8).
    """
    for species, _domain in CASCADE_GENERATOR_REGISTRY:
        for symbol in species:
            assert not symbol.startswith("_")
            assert symbol.isalpha()


def test_only_silicon_is_validated_in_v1():
    """v1 populates the registry but validates silicon alone (scope a)."""
    validated = {
        (frozenset(entry.substrate_species), entry.domain)
        for entry in CASCADE_GENERATOR_REGISTRY.values()
        if entry.validated}
    assert validated == {(frozenset({"Si"}), "diamond-cubic")}


def test_registered_material_domains_lists_every_entry():
    """All five registry rows are listed with species AND domain."""
    listed = registered_material_domains()
    assert "{Si} [diamond-cubic]" in listed
    assert "{O, Si} [silicon-and-silica]" in listed
    assert "{O, Si} [silica-only]" in listed
    assert "{Ga, N} [wurtzite]" in listed
    assert "{Li, Nb, O} [trigonal-ferroelectric]" in listed


def test_domains_for_species_reports_the_ambiguity():
    """One species set, two domains — the fact the resolver acts on."""
    assert domains_for_species({"Si"}) == ["diamond-cubic"]
    assert domains_for_species({"Si", "O"}) == [
        "silica-only", "silicon-and-silica"]
    # An unregistered set reports nothing rather than raising.
    assert domains_for_species({"Ge"}) == []


def test_every_entry_domain_matches_its_key():
    """The entry's own domain field agrees with the key it sits under."""
    for (species, domain), entry in CASCADE_GENERATOR_REGISTRY.items():
        assert entry.domain == domain
        assert frozenset(entry.substrate_species) == species


def test_custom_core_cutoffs_flow_into_the_style():
    """The ZBL switching distances are overridable stand-ins (§4.7)."""
    force_model = resolve_cascade_generator(
        SILICON_ARGON_TYPE_MAP, projectile_species={"Ar"},
        long_core=(0.8, 2.5), short_core=(0.3, 1.0))
    assert force_model.pair_style == (
        "hybrid/overlay sw zbl 0.8 2.5 zbl 0.3 1")
