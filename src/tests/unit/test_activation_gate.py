"""Unit tests for the activation gate (PSEUDOCODE §10.6, DESIGN §3.5).

These exercise the gate machinery with crafted structures and controlled
references: the reference resolver (share/ lookup, missing -> all-None),
the structural kernels (coordination, g(r), the pluggable ring backend),
and the gate's AND-with-a-named-failure logic. A missing or unresolved
reference must never pass, which is the no-defaults discipline made
testable.

"Crystalline" is judged against an ENVIRONMENT LIBRARY (revised
2026-08-29): the tests hand the gate descriptor vectors built by hand —
an undamaged atom carries the library's cold neighbourhood, a damaged
one a neighbourhood far from it — so no LAMMPS runs here, and the depth
metric's whole-profile rule can be checked layer by layer. The real
descriptor run is LEDGER T-35; the full activate_surface -> gate
integration is covered in test_cascade_driver.py.
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
from tests.unit.support import COLD_VECTOR, THERMAL_SCATTER, hand_built_library


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
    """Displace the top ``skin`` Å of atoms — a crafted amorphized skin.

    Returns the displaced points AND the mask of the atoms displaced, so
    a test can hand the gate the matching descriptor vectors.
    """
    scrambled = points.copy()
    top = scrambled[:, 2] > points[:, 2].max() - skin
    generator = np.random.default_rng(seed)
    scrambled[top] += generator.uniform(
        -magnitude, magnitude, size=(int(top.sum()), 3))
    return scrambled, top


def _vectors(damaged_mask, seed=1):
    """Hand-built descriptors: cold-plus-jitter, or far away if damaged."""
    generator = np.random.default_rng(seed)
    count = len(damaged_mask)
    vectors = np.tile(COLD_VECTOR, (count, 1))
    vectors[:, 1] += generator.uniform(0.0, 0.5 * THERMAL_SCATTER, count)
    vectors[damaged_mask, 2] += 20.0 * THERMAL_SCATTER
    return vectors


def _lenient_references(first_peak=2.5):
    """Material references whose bands a crafted amorphized slab clears.

    The depth REQUIREMENT is not here: it is the study's own knob
    (``required_activated_depth``), passed to the gate directly (DESIGN
    §3.5, revised 2026-08-28).
    """
    return ActivationReferences(
        real=False, bond_cutoff=2.9,
        gr={"first_peak": first_peak, "first_peak_tolerance": 0.5},
        coordination={"defect_fraction_min": 0.0,
                      "defect_fraction_max": 1.0},
        rings={"non_six_fraction_min": 0.0},
        source="test-lenient")


def _gate(points, cell, references, damaged_mask, required_depth=0.0,
          multiple=3.0, bin_width=2.0):
    """Run the gate with hand-built vectors and the hand-built library."""
    return activation_gate(
        points, cell, ["Si"] * len(points), references, required_depth,
        hand_built_library(), multiple, bin_width,
        descriptor_vectors=_vectors(damaged_mask))


# ---------------------------------------------------------------------
# The reference resolver (DESIGN §3.5).
# ---------------------------------------------------------------------

def test_resolver_reads_the_silicon_standin():
    """The share/ silicon reference is found and carries every section."""
    references = load_activation_references({"Si"})
    assert references.real is False                  # v1 stand-in, flagged
    assert references.bond_cutoff == pytest.approx(2.9)
    assert references.gr and references.coordination
    assert references.rings


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
    verdict = _gate(points, cell, missing, np.zeros(len(points), bool))
    assert isinstance(verdict, ActivationVerdict)
    assert not verdict.passed
    assert "no activation reference" in verdict.reason


def test_gate_needs_a_work_directory_or_vectors():
    """Without vectors the engine must run somewhere; that must be said."""
    points, cell = _crystal_slab()
    with pytest.raises(ValueError, match="work_directory"):
        activation_gate(
            points, cell, ["Si"] * len(points), _lenient_references(),
            0.0, hand_built_library(), 3.0, 2.0)


def test_gate_passes_when_every_metric_passes():
    """A crafted amorphized slab clears lenient references on all metrics."""
    points, cell = _crystal_slab()
    scrambled, damaged = _scramble_top(points)
    verdict = _gate(scrambled, cell, _lenient_references(), damaged)
    assert verdict.passed
    assert verdict.activated_depth > 0.0
    assert set(verdict.per_metric) == {
        "radial_distribution", "coordination", "ring_statistics",
        "amorphization_depth"}


def test_gate_fails_and_names_the_failing_metric():
    """An unreachable depth target fails the gate, and the reason says so."""
    points, cell = _crystal_slab()
    scrambled, damaged = _scramble_top(points)
    verdict = _gate(scrambled, cell, _lenient_references(), damaged,
                    required_depth=1000.0)                # unreachable
    assert not verdict.passed
    assert verdict.reason.startswith("amorphization_depth")
    assert "required_activated_depth" in verdict.reason


def test_unresolved_metric_never_passes():
    """A missing per-metric section leaves that metric UNRESOLVED and fails."""
    points, cell = _crystal_slab()
    scrambled, damaged = _scramble_top(points)
    references = ActivationReferences(
        real=False, bond_cutoff=2.9,
        gr={"first_peak": 2.5, "first_peak_tolerance": 0.5},
        coordination=None,                          # missing on purpose
        rings={"non_six_fraction_min": 0.0}, source="test-partial")
    verdict = _gate(scrambled, cell, references, damaged)
    assert not verdict.passed
    assert verdict.per_metric["coordination"].reference == "UNRESOLVED"


# ---------------------------------------------------------------------
# The depth profile against the library (DESIGN §3.5, 2026-08-29).
# ---------------------------------------------------------------------

def _depth(points, cell, damaged, **kwargs):
    return _gate(points, cell, _lenient_references(), damaged,
                 **kwargs).activated_depth


def test_depth_is_the_thickness_of_the_disordered_skin():
    """Three top layers disordered (2.5 Å apart) => depth reaches the
    lower edge of the 2 Å layer holding the third one."""
    points, cell = _crystal_slab(n_layers=12)
    damaged = points[:, 2] > points[:, 2].max() - 5.5     # top 3 layers
    depth = _depth(points, cell, damaged)
    # Layers of 2 Å from the surface: the third crystal layer (5 Å down)
    # sits in the 4-6 Å layer, whose lower edge is 6 Å from the surface.
    assert depth == pytest.approx(6.0)


def test_a_damaged_layer_under_a_clean_one_still_counts():
    """The WHOLE profile is scanned: a healed-clean top over a damaged
    layer reports the deeper damage, not 0 Å (prior art's bug, T-34)."""
    points, cell = _crystal_slab(n_layers=12)
    surface = points[:, 2].max()
    top_layer = points[:, 2] > surface - 1.0               # clean
    buried = (points[:, 2] < surface - 4.0) & (
        points[:, 2] > surface - 6.0)                      # 5 Å down
    depth = _depth(points, cell, buried & ~top_layer)
    assert depth == pytest.approx(6.0)


def test_the_frozen_base_is_not_mistaken_for_damage():
    """A pristine slab — bottom face included — has zero depth, because
    the base's neighbourhoods are in the library, not special-cased."""
    points, cell = _crystal_slab(n_layers=12)
    assert _depth(points, cell, np.zeros(len(points), bool)) == 0.0


def test_one_stray_atom_above_the_surface_cannot_zero_the_depth():
    """A speck hovering above a real skin does not erase the skin.

    There is no sparse-layer cut-off any more: the speck's own layer is
    judged on its one atom (crystalline here), and the damaged layers
    beneath are still found by the whole-profile scan.
    """
    points, cell = _crystal_slab(n_layers=12)
    scrambled, damaged = _scramble_top(points, skin=6.0, seed=3)
    honest = _depth(scrambled, cell, damaged)
    assert honest > 0.0, "the crafted skin must register"

    surface = scrambled[:, 2].max()
    speck = np.vstack([scrambled, [[0.0, 0.0, surface + 3.0]]])
    with_speck = _depth(speck, cell, np.append(damaged, False))
    # Measured from the speck, the skin is 3 Å further down, so the
    # depth grows by the speck's height — never collapses to zero.
    assert with_speck == pytest.approx(honest + 3.0, abs=2.0)
    assert with_speck > honest


def test_baseline_follows_the_scatter_multiple():
    """A tight multiple flags jittered-but-crystalline atoms as
    disordered everywhere; the baseline rises with them, so a pristine
    slab still reads as 0 Å rather than as fully amorphized."""
    points, cell = _crystal_slab(n_layers=12)
    tight = _depth(points, cell, np.zeros(len(points), bool),
                   multiple=0.2)
    assert tight == 0.0


def test_depth_layer_width_is_the_study_knob():
    """A thinner layer resolves the same skin more finely."""
    points, cell = _crystal_slab(n_layers=12)
    damaged = points[:, 2] > points[:, 2].max() - 5.5
    coarse = _depth(points, cell, damaged, bin_width=4.0)
    fine = _depth(points, cell, damaged, bin_width=1.0)
    assert coarse == pytest.approx(8.0)
    assert fine == pytest.approx(6.0)
