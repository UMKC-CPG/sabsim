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
    registered_substrate_sets,
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
            {"Si": 1, "O": 2, "Ar": 3}, projectile_species={"Ar"})
    message = str(caught.value)
    # It carries the entry's own caveat so the reason is diagnosable.
    assert "UNTESTED" in message
    assert "§3.5" in message


def test_only_silicon_is_validated_in_v1():
    """v1 populates the registry but validates silicon alone (scope a)."""
    validated = {
        frozenset(entry.substrate_species)
        for entry in CASCADE_GENERATOR_REGISTRY.values()
        if entry.validated}
    assert validated == {frozenset({"Si"})}


def test_registered_substrate_sets_lists_all_four():
    """The four named materials are all present as registry entries."""
    listed = registered_substrate_sets()
    assert "{Si}" in listed
    assert "{O, Si}" in listed
    assert "{Ga, N}" in listed
    assert "{Li, Nb, O}" in listed


def test_custom_core_cutoffs_flow_into_the_style():
    """The ZBL switching distances are overridable stand-ins (§4.7)."""
    force_model = resolve_cascade_generator(
        SILICON_ARGON_TYPE_MAP, projectile_species={"Ar"},
        long_core=(0.8, 2.5), short_core=(0.3, 1.0))
    assert force_model.pair_style == (
        "hybrid/overlay sw zbl 0.8 2.5 zbl 0.3 1")
