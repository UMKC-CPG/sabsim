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


def test_averaging_a_record_shorter_than_the_window_keeps_the_samples():
    """A record shorter than the window degrades, it does not vanish.

    Dropping the warm-up when NOTHING has a full window behind it erases
    the whole curve -- the failure that made a genuine separation report
    as unresolved. The trim must be skipped in that case, not applied to
    extinction.
    """
    import numpy as np
    from sabsim.driver.analysis import averaged_force_curve
    # Five samples spanning 0.4 A, a 0.5 A window: none is a full window
    # deep, so the old code returned an empty selection.
    disp = [0.1, 0.2, 0.3, 0.4, 0.5]
    force = [0.3, 0.25, 0.2, 0.1, 0.02]
    kept_disp, kept_force = averaged_force_curve(disp, force, window=0.5)
    assert len(kept_disp) == len(disp), "no sample may be discarded"
    assert len(kept_force) == len(disp)


# ---------------------------------------------------------------------
# Complete separation is a STATISTICAL test (DESIGN.md §5.5 / §9.6).
# ---------------------------------------------------------------------

def test_a_thermally_noisy_but_zero_force_counts_as_separated():
    """A force indistinguishable from zero must resolve as separated.

    Calibrated on the real measurement that exposed this: a fully
    separated Si/Si pair, the slabs 40 A apart with nothing between
    them, still showed a grip reaction with a standard deviation near
    7 eV/A and a windowed mean of +0.54 eV/A -- about one standard error
    from zero. Against the configured 0.05 eV/A floor that reads as
    "still bonded" forever, which is exactly what the first end-to-end
    run reported at every rate it pulled.
    """
    import numpy as np
    from sabsim.driver.analysis import separation_point

    opening = [2.0, 4.0, 8.0, 12.0]        # opens past the 6 A cutoff
    force = [-1.62, -1.20, 0.54, 0.51]     # settles to ~zero, noisily
    scatter = [0.50, 0.50, 0.50, 0.50]     # standard error of each mean

    index = separation_point(
        opening, force, cutoff=6.0, noise_floor=0.05,
        force_scatter=scatter, sigmas=2.0)
    assert index == 2, (
        "a mean of 0.54 with a standard error of 0.50 is ~1 sigma from "
        "zero and must count as separated")

    # Without the scatter the old absolute test still governs, and this
    # same record never resolves -- the regression in one assertion.
    assert separation_point(
        opening, force, cutoff=6.0, noise_floor=0.05) is None


def test_a_real_load_is_not_mistaken_for_zero():
    """A force well outside its own scatter is NOT separated.

    The counterpart: making the test statistical must not make it
    permissive. A still-bonded interface carries a mean many standard
    errors from zero and has to stay unresolved.
    """
    from sabsim.driver.analysis import separation_point
    opening = [8.0, 9.0, 10.0]
    force = [-1.62, -1.55, -1.60]          # a real, sustained load
    scatter = [0.10, 0.10, 0.10]           # tight: 16 sigma from zero
    assert separation_point(
        opening, force, cutoff=6.0, noise_floor=0.05,
        force_scatter=scatter, sigmas=2.0) is None


def test_scatter_curve_matches_the_averaged_curve_length():
    """The scatter must align sample-for-sample with the means."""
    from sabsim.driver.analysis import (averaged_force_curve,
                                        force_scatter_curve)
    disp = [0.1 * (i + 1) for i in range(30)]
    force = [0.3, 0.1] * 15
    _, averaged = averaged_force_curve(disp, force, window=0.5)
    scatter = force_scatter_curve(disp, force, window=0.5)
    assert len(scatter) == len(averaged)
    assert (scatter > 0).any(), "an alternating force has real scatter"


# ---------------------------------------------------------------------
# Dividing-surface robustness (the defect that flickered a bonded
# interface between 1.4 A and 11 A, 2026-07-21).
# ---------------------------------------------------------------------

def test_a_bin_exactly_on_the_threshold_is_a_crossing():
    """An exact threshold hit must not be read as "no crossing".

    Bin counts are INTEGERS and the threshold is half the peak, so a bin
    landing exactly on it is ordinary: a peak of 100 puts the threshold
    at 50, and any bin holding exactly 50 atoms sits on it. The strict
    sign-change test scored that as no crossing (the product is zero,
    not negative). The real surface was then skipped and the extreme
    crossing fell back to an interior one about 10 A inside the slab --
    which is how a bonded interface reported an 11 A gap that was never
    there, tripping the pull's stopping rule.
    """
    import numpy as np
    from sabsim.driver.analysis import dividing_surface
    # A dense core, then a bin sitting EXACTLY on the half-of-peak
    # threshold, then a LONG sparse tail. The tail matters: when the
    # exact hit is missed there is no crossing at all and the function
    # falls back to the far box edge, so a fixture whose edge sits close
    # to the true surface would pass for the wrong reason.
    z = np.concatenate([
        np.full(100, 10.5), np.full(100, 11.5), np.full(100, 12.5),
        np.full(50, 13.5),                      # exactly half of 100
        np.concatenate([np.full(1, edge + 0.5)
                        for edge in range(14, 30)])])
    surface = dividing_surface(z, "top", bin_width=1.0,
                               smoothing_length=0.0)
    assert surface <= 16.0, (
        f"the surface must sit at the density edge near 13-14 A, got "
        f"{surface} — the far box edge (~29 A) means the exact-threshold "
        f"crossing was missed entirely")


def test_layered_crystal_does_not_scatter_the_surface():
    """A combed (crystalline) profile still yields a stable surface.

    A crystal's layers sit a fixed distance apart, so a histogram binned
    finer than that spacing alternates full and near-empty bins. Every
    trough that dips past the threshold offers a spurious crossing deep
    inside the material; smoothing over a few interatomic spacings must
    leave the surface set by the density ENVELOPE instead.
    """
    import numpy as np
    from sabsim.driver.analysis import dividing_surface
    # Layers every 1.36 A (Si(100) spacing) through a 30 A slab.
    layers = [np.full(80, z) for z in np.arange(10.0, 40.0, 1.36)]
    z = np.concatenate(layers)
    smoothed = dividing_surface(z, "top", bin_width=1.0,
                                smoothing_length=3.0)
    # The surface belongs at the last layer, not somewhere in the bulk.
    assert smoothed >= 36.0, (
        f"a combed profile put the surface at {smoothed}, well inside "
        f"a slab that runs to ~39 A")
