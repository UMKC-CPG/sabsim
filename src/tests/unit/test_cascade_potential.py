"""Unit tests for the cascade potential resolver (DESIGN.md §4.7).

The resolver is a pure assembly with no LAMMPS present, so these tests
assert the emitted :class:`ForceModel` strings directly. The cascade
potential is the universal foundation MLIP: a resolve returns a
``hybrid/overlay deepmd ... zbl zbl``, refuses until the model has cleared
the §3.5 gate, maps the projectile to its real element (no NULL), and asks
for the global atom map the graph network needs.
"""

import pytest

from sabsim.driver.cascade_potential import (
    UNIVERSAL_CASCADE_MODEL,
    resolve_cascade_generator,
    universal_force_model,
)

# A silicon slab bombarded by argon: substrate type 1, projectile type 2.
SILICON_ARGON_TYPE_MAP = {"Si": 1, "Ar": 2}

# A fake weights path, as the study file's [potential] universal_weights
# would hand it in; no real (tens-of-MB) artifact is needed to assemble.
FAKE_MODEL_PATH = "/models/dpa3.pth"


# ---------------------------------------------------------------------
# The universal default (DESIGN §4.7, "universal by default").
# ---------------------------------------------------------------------

def test_universal_is_the_default_and_refuses_until_gate_cleared():
    """A bare resolve picks the universal model and refuses until validated."""
    with pytest.raises(NotImplementedError) as caught:
        resolve_cascade_generator(
            SILICON_ARGON_TYPE_MAP, projectile_species={"Ar"})
    message = str(caught.value)
    # It names the model and the on-the-record exploratory opt-in.
    assert UNIVERSAL_CASCADE_MODEL.name in message
    assert "allow_unvalidated" in message


def test_universal_force_model_is_deepmd_alone_no_zbl():
    """The quiet-stage universal form is deepmd only — no ZBL cores (§2.2).

    ZBL is a keV close-approach hard core; the §2.2 bulk relax equilibrates
    at ordinary bond lengths, so the working lattice is the pure MLIP
    equilibrium. It is the universal sibling of ``classical_force_model``.
    """
    force_model = universal_force_model(
        {"O": 1, "Si": 2}, FAKE_MODEL_PATH, allow_unvalidated=True)

    assert force_model.pair_style == f"deepmd {FAKE_MODEL_PATH}"
    assert "zbl" not in force_model.pair_style
    # Real elements in LAMMPS type-id order (deepmd has no NULL slot), and
    # the graph network needs the global atom map; no runtime plugin load.
    assert force_model.pair_coeff == ("* * O Si",)
    assert force_model.needs_atom_map is True
    assert force_model.preload == ()


def test_universal_force_model_refuses_until_gate_cleared():
    """Like the cascade, an unvalidated bulk derivation refuses by default."""
    with pytest.raises(NotImplementedError) as caught:
        universal_force_model({"Si": 1}, FAKE_MODEL_PATH)
    assert "allow_unvalidated" in str(caught.value)


def test_universal_overlay_assembles_deepmd_plus_two_zbl():
    """The default assembles deepmd spliced with the two ZBL cores (§4.7)."""
    force_model = resolve_cascade_generator(
        SILICON_ARGON_TYPE_MAP, projectile_species={"Ar"},
        weights_path=FAKE_MODEL_PATH, allow_unvalidated=True)

    # deepmd is the base sub-style, then the long core (2.0 outer) and the
    # short core (1.2) — the same two cores the classical path carries.
    assert force_model.pair_style == (
        f"hybrid/overlay deepmd {FAKE_MODEL_PATH} zbl 0.5 2 zbl 0.5 1.2")


def test_universal_maps_projectile_to_its_real_element_not_null():
    """The universal model covers the projectile: real element, not NULL."""
    force_model = resolve_cascade_generator(
        SILICON_ARGON_TYPE_MAP, projectile_species={"Ar"},
        weights_path=FAKE_MODEL_PATH, allow_unvalidated=True)

    # Every type is a real element symbol; the projectile is handled by the
    # long ZBL core, not hidden from the model as NULL.
    assert force_model.pair_coeff[0] == "* * deepmd Si Ar"
    assert "NULL" not in force_model.pair_coeff[0]


def test_universal_asks_for_the_atom_map_and_has_no_preload():
    """The GNN needs a global atom map; the bundle ships deepmd built in."""
    force_model = resolve_cascade_generator(
        SILICON_ARGON_TYPE_MAP, projectile_species={"Ar"},
        weights_path=FAKE_MODEL_PATH, allow_unvalidated=True)

    assert force_model.needs_atom_map is True
    assert force_model.preload == ()




def test_universal_missing_model_path_is_a_loud_stop():
    """An empty weights path is a loud failure, not a silent default."""
    with pytest.raises(RuntimeError) as caught:
        resolve_cascade_generator(
            SILICON_ARGON_TYPE_MAP, projectile_species={"Ar"},
            weights_path="", allow_unvalidated=True)
    assert "universal_weights" in str(caught.value)


def test_universal_model_is_pinned_and_unvalidated():
    """The universal entry pins name+branch+version and is not yet validated."""
    assert UNIVERSAL_CASCADE_MODEL.name == "DPA-3.1-3M"
    assert UNIVERSAL_CASCADE_MODEL.model_branch == "MP_traj_v024_alldata_mixu"
    assert UNIVERSAL_CASCADE_MODEL.version                 # non-empty
    assert UNIVERSAL_CASCADE_MODEL.validated is False


def test_universal_model_is_not_the_tier0_failing_model():
    """The universal default must never regress to DPA-2.4-7M (§4.7).

    That model FAILS the Tier-0 inherent-structure screen on silicon — it
    ranks a damaged slab 0.378 eV/atom BELOW the perfect crystal (LEDGER
    T-21) — so a surface under it has a thermodynamic incentive to destroy
    itself and an activation self-heats instead of amorphizing. The swap to
    DPA-3.1-3M was a physics correction, and this pins it so a future
    convenience edit (an easier export, a faster model) cannot quietly undo
    it without a test saying why it must not.
    """
    assert UNIVERSAL_CASCADE_MODEL.name != "DPA-2.4-7M"


def test_universal_zbl_cores_cover_every_pair_once():
    """Projectile pairs get the long core, substrate pairs the short one."""
    force_model = resolve_cascade_generator(
        {"O": 1, "Si": 2, "Ar": 3}, projectile_species={"Ar"},
        weights_path=FAKE_MODEL_PATH, allow_unvalidated=True)
    zbl_lines = force_model.pair_coeff[1:]
    # Six unordered pairs of three types, one line each.
    assert len(zbl_lines) == 6
    assert "1 3 zbl 1 8 18" in zbl_lines        # O-Ar: long core (#1)
    assert "2 3 zbl 1 14 18" in zbl_lines       # Si-Ar: long core (#1)
    assert "1 2 zbl 2 8 14" in zbl_lines        # O-Si: short core (#2)
    assert "1 1 zbl 2 8 8" in zbl_lines         # O-O: short core (#2)
