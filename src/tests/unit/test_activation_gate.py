"""Unit tests for the activation gate (PSEUDOCODE §10.6, DESIGN §3.5).

These exercise the gate machinery with crafted structures and controlled
references: the reference resolver (share/ lookup, missing -> all-None),
the structural kernels (coordination, g(r), the pluggable ring backend),
and the gate's AND-with-a-named-failure logic. A missing or unresolved
reference must never pass, which is the no-defaults discipline made
testable. The full activate_surface -> gate integration is covered in
test_cascade_driver.py.
"""

import numpy as np
import networkx as nx
import pytest

from sabsim.driver.activation_gate import (
    ActivationReferences,
    ActivationVerdict,
    RING_BACKEND,
    activation_gate,
    bond_graph,
    coordination_numbers,
    load_activation_references,
    non_six_ring_fraction,
    pair_correlation,
)


def _crystal_slab(spacing=2.5, n_lateral=4, n_layers=8):
    """A simple-cubic crystal slab, periodic in-plane, open in z.

    Interior atoms are six-coordinated within a 2.9 Å shell (four in-plane
    neighbours, the √2 diagonal lying outside, plus two in z).
    """
    xs = np.arange(n_lateral) * spacing
    ys = np.arange(n_lateral) * spacing
    zs = np.arange(n_layers) * spacing
    points = np.array([[x, y, z] for z in zs for y in ys for x in xs])
    box = n_lateral * spacing
    cell = np.diag([box, box, (n_layers + 4) * spacing])
    return points, cell


def _scramble_top(points, skin=6.0, magnitude=1.2, seed=0):
    """Displace the top ``skin`` Å of atoms — a crafted amorphized skin."""
    scrambled = points.copy()
    top = scrambled[:, 2] > points[:, 2].max() - skin
    generator = np.random.default_rng(seed)
    scrambled[top] += generator.uniform(
        -magnitude, magnitude, size=(int(top.sum()), 3))
    return scrambled


def _lenient_references(depth_target=0.0, first_peak=2.5):
    """References whose thresholds a crafted amorphized slab clears."""
    return ActivationReferences(
        real=False, bond_cutoff=2.9,
        gr={"first_peak": first_peak, "first_peak_tolerance": 0.5},
        coordination={"defect_fraction_min": 0.0,
                      "defect_fraction_max": 1.0},
        rings={"non_six_fraction_min": 0.0},
        depth={"target_angstrom": depth_target},
        source="test-lenient")


# ---------------------------------------------------------------------
# The reference resolver (DESIGN §3.5).
# ---------------------------------------------------------------------

def test_resolver_reads_the_silicon_standin():
    """The share/ silicon reference is found and carries every section."""
    references = load_activation_references({"Si"})
    assert references.real is False                  # v1 stand-in, flagged
    assert references.bond_cutoff == pytest.approx(2.9)
    assert references.gr and references.coordination
    assert references.rings and references.depth


def test_missing_reference_is_all_none():
    """A species set with no file yields an all-None reference set."""
    references = load_activation_references({"Xx"})
    assert references.bond_cutoff is None
    assert references.source.startswith("MISSING")


# ---------------------------------------------------------------------
# The structural kernels (PSEUDOCODE §10.6).
# ---------------------------------------------------------------------

def test_coordination_counts_neighbours_within_the_shell():
    """A tiny line of three atoms: ends see one neighbour, middle sees two."""
    positions = np.array([[0.0, 0.0, 0.0], [2.5, 0.0, 0.0], [5.0, 0.0, 0.0]])
    cell = np.diag([100.0, 100.0, 100.0])           # large: no wrap
    counts = coordination_numbers(positions, cell, cutoff=2.9)
    assert list(counts) == [1, 2, 1]


def test_pair_correlation_first_peak_at_the_lattice_spacing():
    """The crystal's g(r) first peak sits at the nearest-neighbour distance."""
    points, cell = _crystal_slab()
    curve = pair_correlation(points, cell, r_max=6.0, bin_width=0.05)
    radii = np.asarray(curve.x)
    values = np.asarray(curve.y)
    first_peak = radii[np.argmax(values)]
    assert first_peak == pytest.approx(2.5, abs=0.1)


def test_ring_backend_counts_single_rings():
    """A six-cycle is one six-ring; a five-cycle is one five-ring."""
    assert RING_BACKEND.ring_size_histogram(nx.cycle_graph(6), 9) == {6: 1}
    assert RING_BACKEND.ring_size_histogram(nx.cycle_graph(5), 9) == {5: 1}


def test_non_six_ring_fraction_helper():
    """The non-six fraction is the share of rings that are not six-membered."""
    assert non_six_ring_fraction({6: 8, 5: 1, 7: 1}) == pytest.approx(0.2)
    assert non_six_ring_fraction({}) == 0.0


def test_bond_graph_joins_only_atoms_within_cutoff():
    """Edges appear exactly between atoms closer than the cutoff."""
    positions = np.array([[0.0, 0.0, 0.0], [2.5, 0.0, 0.0], [6.0, 0.0, 0.0]])
    cell = np.diag([100.0, 100.0, 100.0])
    graph = bond_graph(positions, cell, cutoff=2.9)
    assert graph.has_edge(0, 1)                      # 2.5 < 2.9
    assert not graph.has_edge(1, 2)                  # 3.5 > 2.9


# ---------------------------------------------------------------------
# The gate: AND over metrics, named failure, no-defaults (§10.6).
# ---------------------------------------------------------------------

def test_gate_fails_with_no_reference():
    """No reference file => the gate cannot judge and does not pass."""
    points, cell = _crystal_slab()
    missing = load_activation_references({"Xx"})
    verdict = activation_gate(points, cell, missing)
    assert isinstance(verdict, ActivationVerdict)
    assert not verdict.passed
    assert "no activation reference" in verdict.reason


def test_gate_passes_when_every_metric_passes():
    """A crafted amorphized slab clears lenient references on all metrics."""
    points, cell = _crystal_slab()
    scrambled = _scramble_top(points)
    verdict = activation_gate(scrambled, cell, _lenient_references())
    assert verdict.passed
    assert verdict.activated_depth > 0.0
    assert set(verdict.per_metric) == {
        "radial_distribution", "coordination", "ring_statistics",
        "amorphization_depth"}


def test_gate_fails_and_names_the_failing_metric():
    """An unreachable depth target fails the gate, and the reason says so."""
    points, cell = _crystal_slab()
    scrambled = _scramble_top(points)
    references = _lenient_references(depth_target=1000.0)   # unreachable
    verdict = activation_gate(scrambled, cell, references)
    assert not verdict.passed
    assert verdict.reason.startswith("amorphization_depth")


def test_unresolved_metric_never_passes():
    """A missing per-metric section leaves that metric UNRESOLVED and fails."""
    points, cell = _crystal_slab()
    scrambled = _scramble_top(points)
    references = ActivationReferences(
        real=False, bond_cutoff=2.9,
        gr={"first_peak": 2.5, "first_peak_tolerance": 0.5},
        coordination=None,                          # missing on purpose
        rings={"non_six_fraction_min": 0.0},
        depth={"target_angstrom": 0.0}, source="test-partial")
    verdict = activation_gate(scrambled, cell, references)
    assert not verdict.passed
    assert verdict.per_metric["coordination"].reference == "UNRESOLVED"


# ---------------------------------------------------------------------
# Depth-profile robustness (the regression that halted the first
# end-to-end run, 2026-07-21).
# ---------------------------------------------------------------------

def test_one_stray_atom_above_the_surface_cannot_zero_the_depth():
    """A speck in the topmost bin must not erase a real skin.

    The depth walk starts at the surface and stops at the first bin that
    has returned to the bulk baseline. A cascade routinely ejects an atom
    that lands hovering alone above the surface, and a bin holding ONE
    atom has a defect fraction that is pure noise — it can only be 0.0 or
    1.0. When it came up 0.0 the walk stopped before it started and the
    gate reported a 0.0 Å skin for a slab carrying a good one, which is
    exactly how the first full run halted with one half passing and its
    identical twin failing.
    """
    points, cell = _crystal_slab(n_layers=12)
    scrambled = _scramble_top(points, skin=6.0, seed=3)
    references = _lenient_references(depth_target=0.0)

    honest = activation_gate(scrambled, cell, references)
    assert honest.activated_depth > 0.0, "the crafted skin must register"

    # One atom, placed well above the surface in a bin of its own, and
    # deliberately given NO neighbours-worth of company.
    surface = scrambled[:, 2].max()
    speck = np.vstack([scrambled, [[0.0, 0.0, surface + 3.0]]])

    with_speck = activation_gate(speck, cell, references)
    assert with_speck.activated_depth == pytest.approx(
        honest.activated_depth, abs=1e-9), (
        "a single hovering atom changed the measured skin depth from "
        f"{honest.activated_depth} to {with_speck.activated_depth}")


def test_a_populated_bin_at_baseline_still_stops_the_walk():
    """Skipping sparse bins must not make the scan run away downward.

    The counterpart to the test above: the fix must ignore only bins too
    sparse to judge, never a well-populated one that has genuinely
    returned to the crystalline baseline — otherwise the measurement
    would happily report the whole slab as amorphized.
    """
    points, cell = _crystal_slab(n_layers=12)
    scrambled = _scramble_top(points, skin=6.0, seed=3)
    verdict = activation_gate(scrambled, cell, _lenient_references())

    slab_thickness = float(points[:, 2].max() - points[:, 2].min())
    assert verdict.activated_depth < slab_thickness, (
        "the skin must stop at the crystalline bulk, not swallow the slab")
