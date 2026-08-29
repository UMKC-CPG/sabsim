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


def interface_plane(
        z_lower_slab,
        z_upper_slab,
        bin_width: float) -> float:
    """The z midway between the two slabs' facing dividing surfaces.

    Where the interface IS, as a single plane: halfway between the lower
    slab's top surface and the upper slab's bottom one (§2.6). Bonds
    that straddle this plane are what still joins the two bodies.
    """
    lower_top = dividing_surface(z_lower_slab, "top", bin_width)
    upper_bottom = dividing_surface(z_upper_slab, "bottom", bin_width)
    return 0.5 * (lower_top + upper_bottom)


def cross_interface_bridges(
        positions,
        lateral_cell,
        plane_z: float,
        bond_cutoff: float) -> int:
    """Bonded atom PAIRS that straddle the interface plane (§5.5, §8).

    A pair counts when two atoms lie within ``bond_cutoff`` of each other
    — nearest periodic image in the plane, since the cell repeats
    sideways — AND sit on OPPOSITE sides of ``plane_z``. That is the
    quantity which says whether the two bodies are still joined, and it
    is what the pull stops on: force can persist on a few drawn-out
    strands long after the faces are beyond each other's reach, but no
    bond crossing the plane means nothing connects them.

    DELIBERATELY GEOMETRIC, NOT BY PROVENANCE. The obvious version of
    this — count atoms of wafer A within a bond of wafer B — was written
    first and is WRONG, as the trajectory showed immediately: it never
    fell below about 130 even with the slabs 53 Å apart. Those wafer
    labels record which half an atom was BUILT in, not where it now is,
    and pulling transfers a few dozen atoms permanently into the
    opposite block. Every transferred atom then sits surrounded by
    neighbours of the other label and counts as a bridge forever, so the
    measure could never reach zero and the pull could never stop.

    Only atoms within a bond of the plane can straddle it, so the search
    is restricted to that band. That keeps this cheap enough to evaluate
    after every chunk of a running pull.
    """
    atoms = np.asarray(positions, dtype=float)
    if atoms.shape[0] == 0:
        return 0
    z = atoms[:, 2]
    near = np.abs(z - plane_z) <= bond_cutoff
    if not near.any():
        return 0

    band = atoms[near]
    below = band[band[:, 2] < plane_z]
    above = band[band[:, 2] >= plane_z]
    if below.shape[0] == 0 or above.shape[0] == 0:
        return 0

    cell = np.asarray(lateral_cell, dtype=float)
    period_x = float(cell[0][0])
    period_y = float(cell[1][1])

    delta_x = above[:, 0][:, None] - below[:, 0][None, :]
    delta_y = above[:, 1][:, None] - below[:, 1][None, :]
    delta_z = above[:, 2][:, None] - below[:, 2][None, :]
    if period_x > 0.0:
        delta_x -= period_x * np.round(delta_x / period_x)
    if period_y > 0.0:
        delta_y -= period_y * np.round(delta_y / period_y)

    squared = delta_x ** 2 + delta_y ** 2 + delta_z ** 2
    return int((squared < bond_cutoff ** 2).sum())


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
        window: int,
        stress_floor: float = 0.0) -> bool:
    """The DUAL contact criterion (PSEUDOCODE.md §9.3, DESIGN.md §5.2).

    Contact is real only when BOTH hold: the surface-to-surface opening
    has closed to the gap threshold (PRIMARY), and the running-average
    normal stress shows the surfaces genuinely LOADING each other
    (CONFIRM). A gap can close on one asperity, and an asperity carries
    almost no stress — that is what the confirmation guards against.

    Revised 2026-08-27: the confirming stress may be of EITHER sign, as
    long as its magnitude clears ``stress_floor``. Compressive (positive)
    stress is the press doing its work; a sustained TENSILE stress across
    a closed gap is the opposite of an asperity — the two surfaces have
    already bonded and are pulling on each other, which a press too weak
    to register as compression (1 MPa on a 137 Å² demo footprint, T-30)
    left reading as "no contact" indefinitely.
    """
    gap_closed = opening <= gap_threshold
    mean_stress = trailing_mean(normal_stress_series, window)
    loading = (mean_stress > stress_floor) or (mean_stress < -stress_floor)
    return gap_closed and loading


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
    force_ok: bool                 # net grip force zero within its scatter
    drift_ok: bool                 # PE drift within the settle threshold
    # What the force gate actually compared, so a report can show the
    # number and the bar it had to clear (DESIGN §5.3, 2026-08-28).
    net_force_mean: float = 0.0    # |mean(top + bottom)| over the settle
    net_force_threshold: float = 0.0   # max(2 x standard error, floor)


def net_force_series(top_reaction_fz, bottom_reaction_fz) -> np.ndarray:
    """The per-chunk net grip force, top + bottom (§9.4).

    At rest the two reactions cancel chunk by chunk (Newton's third law),
    so this series scatters about zero with the thermal noise of the
    system — which is exactly the scatter the settle gate calibrates
    itself to.
    """
    return (np.asarray(top_reaction_fz, dtype=float)
            + np.asarray(bottom_reaction_fz, dtype=float))


def force_is_zero(series, noise_floor: float,
                  standard_errors: float = 2.0) -> tuple:
    """Is a force series zero within its own scatter? (DESIGN §5.3, §5.5)

    The one criterion the program uses wherever a force must be judged
    zero — the settle's net grip force and the pull's returned force: the
    magnitude of the mean lies within ``standard_errors`` standard errors
    of zero. ``noise_floor`` is the FLOOR beneath that bar, for the
    degenerate noiseless record (a quasi-static mock, a 0 K run) whose
    standard error collapses toward zero and would otherwise demand
    impossible exactness. Returns ``(ok, |mean|, threshold)`` so the
    caller can report the numbers, not only the verdict.
    """
    values = np.asarray(series, dtype=float)
    if len(values) == 0:
        return False, 0.0, float(noise_floor)
    mean = float(abs(values.mean()))
    standard_error = (float(values.std(ddof=1)) / np.sqrt(len(values))
                      if len(values) > 1 else 0.0)
    threshold = max(standard_errors * standard_error, float(noise_floor))
    return mean <= threshold, mean, threshold


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
        net_force_series,
        noise_floor: float,
        pe_drift: float,
        pe_drift_threshold: float) -> SettleReport:
    """Both §9.4 gates: net grip force zero within its scatter AND the PE
    drift within threshold (DESIGN §5.3, revised 2026-08-28).

    ``net_force_series`` is the per-chunk top + bottom reaction over the
    settle (:func:`net_force_series`); it is judged by
    :func:`force_is_zero`, the same statistical test the pull uses — a
    fixed floor alone judged a visibly settled demo unsettled (LEDGER
    T-32). The drift is the already-computed scalar (its unit
    reconciliation lives with the caller that has the atom count). A
    reference that fails either gate is reported, never integrated over.
    """
    force_ok, mean, threshold = force_is_zero(net_force_series, noise_floor)
    drift_ok = pe_drift <= pe_drift_threshold
    return SettleReport(
        settled=(force_ok and drift_ok),
        force_ok=force_ok,
        drift_ok=drift_ok,
        net_force_mean=mean,
        net_force_threshold=threshold)


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
        bridges,
        cutoff: float,
        sustained_frames: int = 3) -> int | None:
    """First frame of COMPLETE separation, or None if never reached (§5.5).

    Complete separation is the first sample where the interface opening
    exceeds the potential cutoff AND nothing bridges the two wafers any
    more — no atom of one lies within a bond of the other
    (:func:`cross_interface_bridges`). The M1 work integral stops HERE,
    not at the record's end (prior art integrated the whole noise tail).
    None means the pull never fully separated within the record.

    The obvious alternative — integrate until the pulling FORCE dies
    away — was tried and measures the wrong thing. Rough surfaces do not
    let go all at once: in scattered places atoms stay attached to both
    sides and draw out into thin strands, which carry force long after
    the faces are beyond each other's reach. Waiting for zero force
    means waiting for the last strand to snap. On the v1 Si/Si pair that
    put HALF the reported work after the faces could no longer touch,
    carried by about one percent of the atoms — a few filaments credited
    to the whole contact area. Bridging asks the question the measure
    actually means: has the interface come apart?
    """
    openings = np.asarray(opening, dtype=float)
    bridge_counts = np.asarray(bridges, dtype=float)
    span = min(len(openings), len(bridge_counts))
    for index in range(span):
        if openings[index] <= cutoff:
            continue
        # The LAST strand flickers. Thermal motion carries a single
        # surviving bond in and out of range from one frame to the next,
        # so a momentary zero is not separation: on the v1 Si/Si pair one
        # bond persisted, intermittently, from 32 Å of pulling to 42 Å,
        # and stopping at the first zero would have set the endpoint by a
        # single lucky jiggle. The count must stay down.
        window = bridge_counts[index:index + sustained_frames]
        if len(window) < min(sustained_frames, span - index):
            break
        # Below one whole pair: interpolation onto the reduced curve's
        # samples can land between frames, and "less than one bond" is
        # the honest reading of no connection.
        if np.all(window < 1.0):
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
