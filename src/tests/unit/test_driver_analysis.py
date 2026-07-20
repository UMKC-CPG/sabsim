"""Unit tests for the press/pull control and reduction math (driver).

Slice 3 is PURE numerics on arrays, so these drive every routine with
synthetic data and no LAMMPS: the density dividing surfaces and the
interface opening (§2.6), the no-impact gate and the dual contact
criterion (§9.3), the two settle-reference gates (§9.4), and the
displacement-windowed averaged curve, its re-expression versus opening,
and the separation point (§9.6).
"""

import numpy as np
import pytest

from sabsim.driver.analysis import (
    approach_is_quasistatic,
    atom_count_conserved,
    averaged_force_curve,
    contact_reached,
    dividing_surface,
    interface_opening,
    net_grip_force,
    potential_energy_drift,
    reexpress_versus_opening,
    reference_is_settled,
    separation_point,
    trailing_mean,
)


# ---------------------------------------------------------------------
# Interface geometry — the density dividing surfaces (§2.6).
# ---------------------------------------------------------------------

def _slab_with_diffuse_top():
    """A dense core in [10, 20] with a sparse tail out to 24."""
    core = np.linspace(10.0, 20.0, 200)
    tail = np.linspace(20.0, 24.0, 20)
    return np.concatenate([core, tail])


def test_dividing_surface_finds_the_half_density_edge():
    """The top surface sits where density falls to half its interior."""
    surface = dividing_surface(
        _slab_with_diffuse_top(), "top", bin_width=1.0)
    # The core->tail drop (density ~20 to ~5) crosses half near z=20.
    assert 19.0 <= surface <= 21.0


def test_interface_opening_is_surface_to_surface():
    """The opening is upper-bottom minus lower-top, not atom extremes."""
    # Each slab has a dense core and a sparse tail well below half
    # density, so the half-bulk crossing is clean at the core edge.
    lower = np.concatenate(
        [np.linspace(0.0, 10.0, 200), np.linspace(10.0, 13.0, 15)])
    upper = np.concatenate(
        [np.linspace(17.0, 20.0, 15), np.linspace(20.0, 30.0, 200)])
    opening = interface_opening(lower, upper, bin_width=1.0)
    # lower top ~10, upper bottom ~20, so the opening is about 10 Å.
    assert 8.5 <= opening <= 11.5


# ---------------------------------------------------------------------
# Press control — the no-impact gate and the dual contact criterion.
# ---------------------------------------------------------------------

def test_quasistatic_gate_passes_slow_and_gentle():
    """A slow, low-energy approach is a press, not a collision (§9.3)."""
    assert approach_is_quasistatic(
        approach_speed=10.0, sound_speed=8000.0,
        kinetic_energy=0.1, bond_energy=10.0)


def test_quasistatic_gate_rejects_fast_or_energetic():
    """Too fast, or too much kinetic energy, fails the no-impact gate."""
    assert not approach_is_quasistatic(
        approach_speed=2000.0, sound_speed=8000.0,
        kinetic_energy=0.1, bond_energy=10.0)
    assert not approach_is_quasistatic(
        approach_speed=10.0, sound_speed=8000.0,
        kinetic_energy=5.0, bond_energy=10.0)


def test_trailing_mean_uses_the_last_window():
    """The running average is the mean of the last window samples."""
    assert trailing_mean([1.0, 2.0, 3.0, 4.0], window=2) == 3.5
    assert trailing_mean([1.0, 2.0, 3.0, 4.0], window=10) == 2.5


def test_contact_needs_both_gap_and_positive_stress():
    """Contact requires the gap closed AND the stress running positive."""
    positive = [-1.0, 0.5, 1.0, 1.0]
    negative = [1.0, 1.0, -0.5, -1.0]
    # Gap closed and stress positive: contact.
    assert contact_reached(2.0, 2.5, positive, window=2)
    # Gap closed but stress not yet positive: no contact (one asperity).
    assert not contact_reached(2.0, 2.5, negative, window=2)
    # Stress positive but gap still open: no contact.
    assert not contact_reached(3.0, 2.5, positive, window=2)


# ---------------------------------------------------------------------
# Settle reference — the two zero-load gates (§9.4).
# ---------------------------------------------------------------------

def test_net_grip_force_cancels_at_rest():
    """Equal and opposite grip reactions leave no residual force."""
    assert net_grip_force([5.0, 5.0, 5.0], [-5.0, -5.0, -5.0]) == 0.0
    assert net_grip_force([5.0], [-3.0]) == 2.0


def test_potential_energy_drift_is_zero_on_a_plateau():
    """A settled PE plateau drifts ~0; a steady slope drifts its change."""
    assert potential_energy_drift([1.0, 1.0, 1.0, 1.0]) == 0.0
    assert potential_energy_drift([0.0, 1.0, 2.0, 3.0]) == 2.0


def test_reference_is_settled_names_the_failing_gate():
    """Each gate is reported so a failed settle names itself (§5.3)."""
    good = reference_is_settled(0.01, 0.05, 0.0005, 0.001)
    assert good.settled and good.force_ok and good.drift_ok

    loud_force = reference_is_settled(0.1, 0.05, 0.0005, 0.001)
    assert not loud_force.settled and not loud_force.force_ok

    drifting = reference_is_settled(0.01, 0.05, 0.002, 0.001)
    assert not drifting.settled and not drifting.drift_ok


# ---------------------------------------------------------------------
# Trajectory reduction — the two curves and the gates (§9.6).
# ---------------------------------------------------------------------

def test_averaged_curve_drops_the_leading_warmup():
    """The average discards points before a full displacement window."""
    displacement = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
    force = np.array([0.0, 2.0, 4.0, 6.0, 8.0, 10.0])
    disp, avg = averaged_force_curve(displacement, force, window=2.0)
    # Warm-up (displacement < 2 past the start) is dropped.
    assert disp[0] == 2.0
    # At displacement 2 the window [0, 2] averages forces 0, 2, 4 -> 2.
    assert avg[0] == pytest.approx(2.0)


def test_reexpress_versus_opening_interpolates_the_opening():
    """The curve is re-expressed versus interface opening by interp."""
    openings, forces = reexpress_versus_opening(
        curve_displacement=[2.0, 3.0, 4.0],
        curve_force=[1.0, 2.0, 3.0],
        frame_displacement=[0.0, 2.0, 4.0, 6.0],
        frame_opening=[0.0, 2.0, 4.0, 6.0])
    assert list(openings) == [2.0, 3.0, 4.0]
    assert list(forces) == [1.0, 2.0, 3.0]


def test_separation_point_finds_open_and_force_free_frame():
    """Separation is the first frame past the cutoff at the noise floor."""
    opening = [1.0, 2.0, 5.0, 7.0, 9.0]
    force = [5.0, 3.0, 0.5, 0.02, 0.01]
    index = separation_point(opening, force, cutoff=6.0, noise_floor=0.05)
    assert index == 3
    # Never separated within the record -> None.
    assert separation_point(
        opening, force, cutoff=100.0, noise_floor=0.05) is None


def test_atom_count_conservation_is_a_gate():
    """A changed atom count voids the run (an escaped atom, §5.6)."""
    assert atom_count_conserved(128, 128)
    assert not atom_count_conserved(128, 127)


# ---------------------------------------------------------------------
# The mechanical work of separation (§8.4): integrate the resisting force
# over grip displacement up to complete separation, per unit area.
# ---------------------------------------------------------------------

from sabsim.driver.analysis import work_of_separation


def test_work_of_separation_integrates_the_curve_to_area():
    """Trapezoidal area under force-vs-displacement, divided by area."""
    # Triangular resisting force 0 -> 1 -> 0.5 -> 0 over unit steps.
    displacement = [0.0, 1.0, 2.0, 3.0]
    force = [0.0, 1.0, 0.5, 0.0]
    # Trapezoids: 0.5 + 0.75 + 0.25 = 1.5 eV; over area 2 Å² = 0.75 eV/Å².
    work = work_of_separation(displacement, force, 3, interface_area=2.0)
    assert work == pytest.approx(0.75)


def test_work_of_separation_stops_at_separation_not_the_tail():
    """The integral ends at separation; a noisy tail is NOT counted."""
    displacement = [0.0, 1.0, 2.0, 3.0, 4.0]
    force = [0.0, 1.0, 0.0, 5.0, 5.0]     # spurious tail past index 2
    # Up to index 2 only: 0.5 + 0.5 = 1.0 eV; /area 1 = 1.0 eV/Å².
    work = work_of_separation(displacement, force, 2, interface_area=1.0)
    assert work == pytest.approx(1.0)


def test_work_of_separation_is_none_when_never_separated():
    """A pull that never fully separated has no work to report."""
    assert work_of_separation([0.0, 1.0], [0.0, 1.0], None, 1.0) is None
