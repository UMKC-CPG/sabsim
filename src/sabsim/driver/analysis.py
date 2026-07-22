"""Press/pull control and reduction math (PSEUDOCODE.md §9.3, §9.4, §9.6).

This is slice 3 of the driver: the PURE numerics that decide, mid-run,
when the press has made contact and when a pull has fully separated, and
that reduce a finished pull to its two force curves. Every function here
operates on plain arrays — atom z-positions, a normal-stress series, a
force-vs-displacement curve — that the live driver (slices 4-5) will
supply, so the whole module is unit-testable on a login node with
synthetic arrays and no LAMMPS.

It is deliberately separate from :mod:`sabsim.driver.commands` (slice 2,
which emits LAMMPS commands): commands SET UP the run, this module READS
BACK from it. Four groups of routines:

* **Interface geometry (§2.6).** The gap and the opening are measured
  surface-to-surface between the two density DIVIDING SURFACES, never
  between extremal atoms — the fix for prior art's single-asperity error.
* **Press control (§9.3).** The no-impact (quasi-static) gate and the
  DUAL contact criterion: the gap has closed AND the running-average
  normal stress has turned positive.
* **Settle reference (§9.4).** The two gates that certify a zero-load
  reference before the pull integrates over it.
* **Trajectory reduction (§9.6).** The displacement-windowed averaged
  force curve (leading warm-up discarded), its re-expression versus
  interface opening, the separation point, and the conservation gate.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# ---------------------------------------------------------------------
# Interface geometry — the density dividing surfaces (DESIGN.md §2.6).
# ---------------------------------------------------------------------

def density_profile(
        z_positions, bin_width: float) -> tuple:
    """Bin atom z-positions into a number-density profile along z.

    Returns the bin centers and the per-bin atom counts. The profile is
    the raw material for locating a surface by where the density falls to
    half its interior value, rather than at the topmost atom (§2.6).
    """
    z = np.asarray(z_positions, dtype=float)
    low, high = z.min(), z.max()
    bin_count = max(1, int(np.ceil((high - low) / bin_width)))
    edges = low + bin_width * np.arange(bin_count + 1)
    counts, _ = np.histogram(z, bins=edges)
    centers = 0.5 * (edges[:-1] + edges[1:])
    return centers, counts.astype(float)


def _smooth_profile(density: np.ndarray, window_bins: int) -> np.ndarray:
    """Moving-average a density profile over ``window_bins`` bins.

    Edges are handled by averaging over whatever bins exist, so the
    profile keeps its length and its ends are not dragged toward zero —
    which would invent a surface where the slab simply stops.
    """
    if window_bins <= 1 or density.size == 0:
        return density
    half = window_bins // 2
    smoothed = np.empty_like(density, dtype=float)
    for index in range(density.size):
        low = max(0, index - half)
        high = min(density.size, index + half + 1)
        smoothed[index] = density[low:high].mean()
    return smoothed


def dividing_surface(
        z_positions,
        side: str,
        bin_width: float,
        interior_fraction: float = 0.5,
        smoothing_length: float = 3.0) -> float:
    """Locate a slab surface where density falls to half its interior.

    ``side`` is ``"top"`` for the upper surface of the lower slab or
    ``"bottom"`` for the lower surface of the upper slab. The surface is
    the z where the density profile crosses ``interior_fraction`` of its
    peak (bulk) value — the ``"top"`` crossing is the HIGHEST such z, the
    ``"bottom"`` crossing the LOWEST — so a slab's two surfaces are told
    apart by side, and a single stray adatom never sets the plane
    (DESIGN.md §2.6, the same half-bulk rule §3.5 uses for the cascade
    depth).

    THE PROFILE IS SMOOTHED FIRST, and that is load-bearing rather than
    cosmetic. A crystalline slab's density is a COMB: its atomic layers
    sit a fixed distance apart (a/4 = 1.36 Å for Si(100)), so a histogram
    binned finer than that lands alternately on a layer and between two,
    and the raw counts swing between roughly a third and full bulk. The
    half-bulk threshold falls INSIDE that swing, so every trough deep in
    the crystal manufactures a spurious crossing, and taking the extreme
    crossing then picks whichever interior trough happens to reach
    furthest out this frame. Thermal motion re-rolls that dice each time
    the profile is measured.

    That defect was not hypothetical: it made the measured interface
    opening of a bonded pair flicker between 1.4 Å and 11 Å from one
    frame to the next, tripping the pull's stopping rule on a gap that
    was never there and truncating the slowest, most physically valuable
    rate of the pull sweep.

    Averaging over ``smoothing_length`` (Å, a few interatomic spacings)
    erases the layering while leaving the surface RAMP — which is many
    ångströms wide — untouched, so the crossing is set by the envelope of
    the material, which is what a dividing surface means.
    """
    centers, density = density_profile(z_positions, bin_width)
    window_bins = max(1, int(round(smoothing_length / bin_width)))
    if window_bins % 2 == 0:            # keep the window centred
        window_bins += 1
    density = _smooth_profile(np.asarray(density, dtype=float), window_bins)
    threshold = interior_fraction * density.max()
    # A bin sitting EXACTLY on the threshold is a crossing too. The
    # strict sign-change test below reads such a bin as no crossing at
    # all — the product is zero, not negative — and the function then
    # falls back to the box edge and silently reports a surface tens of
    # ångströms from the material. Rare on raw counts, but smoothing
    # makes exact hits ordinary, so it is handled explicitly.
    crossings = []
    for index in range(len(density) - 1):
        here, ahead = density[index], density[index + 1]
        if here == threshold:
            crossings.append(float(centers[index]))
            continue
        if (here - threshold) * (ahead - threshold) < 0.0:  # sign change
            fraction = (threshold - here) / (ahead - here)
            crossings.append(
                centers[index]
                + fraction * (centers[index + 1] - centers[index]))
    if len(density) and density[-1] == threshold:
        crossings.append(float(centers[-1]))
    if not crossings:
        # A profile with no crossing (uniform or single-bin) has no
        # resolvable surface here; fall back to the relevant extreme edge.
        return float(centers[-1] if side == "top" else centers[0])
    return float(max(crossings) if side == "top" else min(crossings))


def interface_opening(
        z_lower_slab,
        z_upper_slab,
        bin_width: float) -> float:
    """The surface-to-surface gap between the two facing slabs (§2.6).

    The opening is the upper slab's BOTTOM dividing surface minus the
    lower slab's TOP dividing surface — the real interface separation,
    which the pull's second curve is expressed against (§9.6). It is NOT
    the grip displacement, which also contains the slabs' elastic
    stretch.
    """
    lower_top = dividing_surface(z_lower_slab, "top", bin_width)
    upper_bottom = dividing_surface(z_upper_slab, "bottom", bin_width)
    return upper_bottom - lower_top


# ---------------------------------------------------------------------
# Press control — the no-impact gate and the dual contact criterion
# (PSEUDOCODE.md §9.3, DESIGN.md §5.2).
# ---------------------------------------------------------------------

def approach_is_quasistatic(
        approach_speed: float,
        sound_speed: float,
        kinetic_energy: float,
        bond_energy: float,
        speed_fraction: float = 0.1,
        energy_fraction: float = 0.1) -> bool:
    """The no-impact gate: the close is a press, not a collision (§9.3).

    Contact is quasi-static only when the approach speed is far below the
    material's sound speed AND the kinetic energy the grip carries is far
    below the bond scale — otherwise the interface is mechanical
    interlock, not adhesion (§5.2). "Far below" is a stated margin
    (default a tenth); the exact fractions are a §5.9 follow-on, so they
    are parameters, not magic numbers buried in a comparison.
    """
    return (approach_speed <= speed_fraction * sound_speed
            and kinetic_energy <= energy_fraction * bond_energy)


def trailing_mean(series, window: int) -> float:
    """Mean of the last ``window`` samples — the current running average.

    Used for the normal-stress running average (§9.3): a single frame's
    stress is noisy, so contact is confirmed on a short running mean, not
    an instantaneous value.
    """
    values = np.asarray(series, dtype=float)
    span = max(1, min(window, len(values)))
    return float(values[-span:].mean())


def contact_reached(
        opening: float,
        gap_threshold: float,
        normal_stress_series,
        window: int) -> bool:
    """The DUAL contact criterion (PSEUDOCODE.md §9.3, DESIGN.md §5.2).

    Contact is real only when BOTH hold: the surface-to-surface opening
    has closed to the gap threshold (PRIMARY), and the running-average
    normal stress has turned positive (CONFIRM). A gap can close on one
    asperity; positive normal stress means the surfaces genuinely load
    each other, so neither test alone is trusted.
    """
    gap_closed = opening <= gap_threshold
    stress_positive = trailing_mean(normal_stress_series, window) > 0.0
    return gap_closed and stress_positive


# ---------------------------------------------------------------------
# Settle reference — the gated zero-load state (PSEUDOCODE.md §9.4).
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class SettleReport:
    """Whether the zero-load reference settled, and which gate failed.

    The pull's curve must start at rest under no applied load; if the
    reference did not settle, §9.4 REPORTS rather than integrating over a
    stressed state (prior art's PE jumped 481 eV in 0.5 ps). Both
    sub-verdicts are carried so the failure names itself.
    """

    settled: bool
    force_ok: bool                 # net grip force within the noise floor
    drift_ok: bool                 # PE drift within the settle threshold


def net_grip_force(top_reaction_fz, bottom_reaction_fz) -> float:
    """Residual unbalanced normal force on the grips (§9.4, §5.4).

    At a settled zero-load reference the two grip reactions cancel
    (Newton's third law), so their summed mean is the residual drive the
    reference still carries. Its magnitude must fall within the noise
    floor for the state to count as at rest.
    """
    top = np.asarray(top_reaction_fz, dtype=float)
    bottom = np.asarray(bottom_reaction_fz, dtype=float)
    return float(abs(top.mean() + bottom.mean()))


def potential_energy_drift(pe_series) -> float:
    """A drift magnitude for a potential-energy series (§9.4).

    Measured as the change between the first and second halves' means, so
    a settled plateau reads ~0 while a state still relaxing (a steady
    slope) reads its net change. Compared against ``reference_pe_drift``
    by :func:`reference_is_settled`.
    """
    values = np.asarray(pe_series, dtype=float)
    if len(values) < 2:
        return 0.0
    half = len(values) // 2
    return float(abs(values[half:].mean() - values[:half].mean()))


def reference_is_settled(
        net_force: float,
        noise_floor: float,
        pe_drift: float,
        pe_drift_threshold: float) -> SettleReport:
    """Both §9.4 gates: net grip force AND PE drift within threshold.

    Takes the already-computed scalars (so unit reconciliation lives with
    the caller that has the atom count) and reports each verdict plus the
    conjunction. A reference that fails either gate is reported, never
    integrated over (§5.3).
    """
    force_ok = net_force <= noise_floor
    drift_ok = pe_drift <= pe_drift_threshold
    return SettleReport(
        settled=(force_ok and drift_ok),
        force_ok=force_ok,
        drift_ok=drift_ok)


# ---------------------------------------------------------------------
# Trajectory reduction — the two curves and the gates (PSEUDOCODE §9.6).
# ---------------------------------------------------------------------

def averaged_force_curve(
        displacement,
        force,
        window: float,
        drop_leading_zero: bool = True) -> tuple:
    """Average the force over a fixed DISPLACEMENT window (§9.5, §5.4).

    For each sample the force is averaged over every earlier sample
    within ``window`` of it in GRIP DISPLACEMENT (not time — a length
    window resolves the peak identically at every rate rung). The
    warm-up, before a full window has accumulated, is where an averaging
    fix emits a spurious leading zero; with ``drop_leading_zero`` those
    points are discarded (prior art kept the zero and anchored a
    trapezoid and a modulus fit on it). Returns the surviving
    displacements and their averaged forces.
    """
    disp = np.asarray(displacement, dtype=float)
    forces = np.asarray(force, dtype=float)
    averaged = np.empty(len(disp))
    window_full = np.empty(len(disp), dtype=bool)
    for index, center in enumerate(disp):
        in_window = (disp <= center) & (disp >= center - window)
        averaged[index] = forces[in_window].mean()
        window_full[index] = (center - disp[0]) >= window
    if drop_leading_zero and window_full.any():
        return disp[window_full], averaged[window_full]
    if drop_leading_zero:
        # NOTHING accumulated a full window: the whole record is shorter
        # than the averaging length. Returning the empty selection here
        # is what a caller cannot recover from — the curve vanishes, the
        # separation search finds nothing, and a pull that DID separate
        # is reported as "unresolved", which reads as "we could not
        # tell" rather than "the answer was discarded". That is exactly
        # how the first full end-to-end run lost its number: the slowest
        # rung separated after 0.49 Å against a 0.5 Å window.
        #
        # So the warm-up trim is skipped rather than applied to
        # extinction. The samples are still averaged over whatever span
        # existed, which is the most the data supports; a short record
        # is a coarse measurement, not an absent one.
        return disp, averaged
    return disp, averaged


def force_scatter_curve(
        displacement,
        force,
        window: float,
        drop_leading_zero: bool = True) -> np.ndarray:
    """The STANDARD ERROR of the mean in each averaging window (§5.5).

    The companion to :func:`averaged_force_curve`, computed over exactly
    the same windows, so entry *i* is the uncertainty on that function's
    entry *i*. It exists because "the force has returned to zero" is a
    statistical claim: the grip reaction is a sum over every grip atom
    and at 300 K it swings across tens of eV/Å even when the slabs are
    far apart and nothing connects them. What settles is the MEAN, not
    the instantaneous value, and a mean is only as meaningful as its
    scatter — so the separation test needs both.

    A window holding a single sample has no scatter to speak of; its
    standard error is reported as zero, which leaves the configured
    noise floor as the only bar (see :func:`separation_point`).
    """
    disp = np.asarray(displacement, dtype=float)
    forces = np.asarray(force, dtype=float)
    scatter = np.zeros(len(disp))
    window_full = np.empty(len(disp), dtype=bool)
    for index, center in enumerate(disp):
        in_window = (disp <= center) & (disp >= center - window)
        sample = forces[in_window]
        if sample.size > 1:
            # Standard error of the mean: the spread of the samples
            # divided by the root of how many there are.
            scatter[index] = float(sample.std(ddof=1) / np.sqrt(sample.size))
        window_full[index] = (center - disp[0]) >= window
    if drop_leading_zero and window_full.any():
        return scatter[window_full]
    return scatter


def reexpress_versus_opening(
        curve_displacement,
        curve_force,
        frame_displacement,
        frame_opening) -> tuple:
    """Re-express a force-vs-displacement curve versus interface opening.

    The averaged curve is sampled at grip displacements; the frames give
    the interface opening at each displacement. Interpolating the opening
    onto the curve's displacements gives force vs OPENING — where the
    interface actually is, separated from the slabs' elastic stretch
    (§9.6, §5.5). Returns the openings and the same forces.
    """
    openings = np.interp(
        np.asarray(curve_displacement, dtype=float),
        np.asarray(frame_displacement, dtype=float),
        np.asarray(frame_opening, dtype=float))
    return openings, np.asarray(curve_force, dtype=float)


def separation_point(
        opening,
        averaged_force,
        cutoff: float,
        noise_floor: float,
        force_scatter=None,
        sigmas: float = 2.0) -> int | None:
    """First frame of COMPLETE separation, or None if never reached (§9.6).

    Complete separation is the first sample where the interface opening
    exceeds the potential cutoff AND the averaged force has returned to
    zero. The M1 work integral stops HERE, not at the record's end (prior
    art integrated the whole noise tail). None means the pull never fully
    separated within the record.

    "Returned to zero" is decided STATISTICALLY when ``force_scatter``
    (the per-window standard error from :func:`force_scatter_curve`) is
    supplied: the force counts as zero when its magnitude falls within
    ``sigmas`` standard errors of it. That is the only test that can work
    on this quantity — a fully separated Si/Si pair still shows a grip
    reaction with a standard deviation near 7 eV/Å, so comparing it to a
    small fixed constant declares "still bonded" forever, which is
    exactly what the first end-to-end run did at every rate it tried.

    ``noise_floor`` remains as a FLOOR under that test, so a noiseless
    record (a quasi-static mock, a zero-temperature run) whose standard
    error collapses toward zero is not asked for impossible exactness.
    With no scatter supplied the floor alone applies, preserving the
    original behaviour for callers that have only a mean.
    """
    openings = np.asarray(opening, dtype=float)
    forces = np.asarray(averaged_force, dtype=float)
    scatter = (np.zeros(len(forces)) if force_scatter is None
               else np.asarray(force_scatter, dtype=float))
    for index in range(len(openings)):
        allowed = noise_floor
        if index < len(scatter):
            allowed = max(noise_floor, sigmas * float(scatter[index]))
        if openings[index] > cutoff and abs(forces[index]) <= allowed:
            return index
    return None


def atom_count_conserved(initial_count: int, final_count: int) -> bool:
    """Gate: no atom escaped the open-z box (PSEUDOCODE.md §9.6, §5.6).

    A non-periodic boundary silently deletes an atom that leaves the box,
    so a changed count voids the run rather than warning — the difference
    between a measurement and a fiction.
    """
    return initial_count == final_count


# eV/Å² expressed in J/m² — the SI face of the mechanical work of
# separation. 1 eV = 1.602176634e-19 J, 1 Å² = 1e-20 m², so the ratio is
# 1.602176634e-19 / 1e-20 = 16.02176634 J/m² per eV/Å².
EV_PER_ANGSTROM_SQ_IN_SI = 16.02176634


def work_of_separation(
        displacement,
        force,
        separation_index: int | None,
        interface_area: float) -> float | None:
    """The mechanical work of separation per unit area (DESIGN.md §8.4).

    The headline mechanical measure (M1): the work the grip does pulling
    the interface apart, per unit interface area. It is the area under the
    resisting-force curve — force (tension-positive, eV/Å) versus grip
    displacement (Å) — integrated from the start of the pull up to COMPLETE
    separation (``separation_index`` from :func:`separation_point`), then
    divided by the lateral ``interface_area`` (Å²). The result is in eV/Å²
    (multiply by :data:`EV_PER_ANGSTROM_SQ_IN_SI` for J/m²).

    Two prior-art errors it refuses: integrating the whole noisy tail past
    separation (the cut at ``separation_index`` stops there, §9.6), and
    anchoring on the averaging fix's spurious leading zero (the curve
    handed in already had it dropped, §9.5). Returns ``None`` when the pull
    never fully separated — there is no work of separation to report for a
    pull that did not finish, and a partial integral would understate it.
    """
    if separation_index is None:
        return None
    grip = np.asarray(displacement, dtype=float)[:separation_index + 1]
    resisting = np.asarray(force, dtype=float)[:separation_index + 1]
    if len(grip) < 2:
        return 0.0
    # Trapezoidal integral, written out so it is version-independent and
    # readable: sum of trapezoids (mean height x width) across the curve.
    segment_work = 0.5 * (resisting[1:] + resisting[:-1]) * np.diff(grip)
    return float(np.sum(segment_work) / interface_area)
