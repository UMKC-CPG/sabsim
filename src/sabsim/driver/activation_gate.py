"""The activation gate — pluggable structural metrics (PSEUDOCODE §10.6).

This is Phase 2 of surface activation: the formal pass/fail gate that
replaces Phase 1's stand-in `activation_disorder_check`. It judges the
re-annealed surface with a registry of structural metrics (DESIGN §3.5),
each measuring one property and comparing it against a reference with a
threshold; the gate is the AND over all of them. The four metrics are the
radial pair-correlation g(r), the coordination-number distribution, the
ring statistics, and a robust amorphization-depth profile.

Three design commitments from DESIGN §3.5 show up directly here:

- **References and thresholds live OUTSIDE the physics spec** — a
  threshold is a criterion of the gate, not a knob of the experiment — in
  an easily-locatable `share/` directory, resolved by species set
  (:func:`load_activation_references`). A reference a required metric needs
  but cannot find leaves that metric UNRESOLVED, which never passes (the
  no-defaults discipline, `DESIGN.md` §1.4).
- **g(r) is report-leaning** (the confirmed choice): its full curve is
  recorded for by-hand inspection and its automated pass is only a coarse
  first-peak sanity check, while the strict auto-thresholds are the
  coordination, ring, and depth metrics.
- **Ring enumeration is a pluggable backend** (:data:`RING_BACKEND`): v1
  binds it to `networkx` King / shortest-path rings; the Imago
  `bond_analysis.py` ring tool is the door-open replacement (evaluated
  before adoption), and swapping it changes no metric.

Judgment is per realization: the gate judges ONE re-annealed slab; the
amorphization-seed spread is taken above this module (§10.8).
"""

from __future__ import annotations

import os
import tomllib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import networkx as nx
import numpy as np


# ---------------------------------------------------------------------
# Verdict records (the concrete form of PSEUDOCODE §10.1).
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class Curve:
    """A recorded 1-D curve — a g(r) or a ring-size histogram (§10.1).

    Kept for human inspection (the report-leaning g(r), the ring
    distribution); the automated pass is decided on a scalar, not the
    curve, so this rides along in a verdict's ``detail`` rather than
    driving the gate.
    """

    x: tuple
    y: tuple


@dataclass(frozen=True)
class MetricVerdict:
    """One metric's result (PSEUDOCODE §10.1).

    ``measured`` is the SCALAR the pass is decided on (a first-peak
    position, a defect fraction, a non-six-ring fraction, a depth);
    ``reference`` names the reference used (or ``"UNRESOLVED"`` when the
    reference was missing); ``threshold`` is the criterion; ``detail``
    carries a recorded curve for inspection where the metric has one.
    """

    name: str
    measured: float | None
    reference: str
    threshold: object                  # a number, a (min, max) band, or None
    passed: bool
    detail: Curve | None = None


@dataclass(frozen=True)
class ActivationVerdict:
    """The activation gate result (PSEUDOCODE §10.1).

    ``passed`` is the AND over every registered metric; ``activated_depth``
    is the MEASURED amorphization depth that build_slab's thickness
    criterion (§2.5) only estimated a-priori and that §10.7 uses to label
    the activated skin; ``per_metric`` maps each metric name to its
    :class:`MetricVerdict`; ``reason`` names the failing metric.
    """

    passed: bool
    activated_depth: float
    per_metric: dict
    reason: str


# ---------------------------------------------------------------------
# Reference data, resolved from the share/ directory (DESIGN §3.5).
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class ActivationReferences:
    """Reference values + thresholds for one material's gate (§3.5).

    Each section (``gr``, ``coordination``, ``rings``, ``depth``) is a
    small map of stand-in numbers, or ``None`` when the reference file did
    not provide it (making the corresponding metric UNRESOLVED). ``real``
    records whether these are the real DFT/experimental anchors or the v1
    literature-anchored stand-ins; ``source`` is the provenance string a
    report cites.
    """

    real: bool
    bond_cutoff: float | None
    gr: dict | None
    coordination: dict | None
    rings: dict | None
    depth: dict | None
    source: str


# The repository `share/` directory holds the small, version-controlled v1
# stand-ins (this file lives at src/sabsim/driver/, so the repo root is
# three parents up). Large real references (a DFT/exp g(r), the a-Si CRN
# model) are resolved from the deployment SABSIM_SHARE root when present.
_REPO_SHARE = Path(__file__).resolve().parents[3] / "share" / "activation"


def _reference_search_paths() -> list:
    """Where to look for a species set's reference file (DESIGN §3.5).

    The repo `share/` directory first (the v1 stand-ins that travel with
    the code), then the deployment ``SABSIM_SHARE`` root if it is set — so
    a large real reference need not live in the repository.
    """
    paths = [_REPO_SHARE]
    deployment_share = os.environ.get("SABSIM_SHARE")
    if deployment_share:
        paths.append(Path(deployment_share) / "activation")
    return paths


def load_activation_references(species) -> ActivationReferences:
    """Load the gate references for a species set (PSEUDOCODE §10.6).

    Keyed by the species set — so a new material adds a reference FILE, not
    code — the key is the species symbols sorted and underscore-joined
    (silicon => ``Si``; a compound => ``O_Si``). A missing file yields an
    all-``None`` reference set, which makes every metric UNRESOLVED rather
    than silently passing (no-defaults, `DESIGN.md` §1.4).
    """
    key = "_".join(sorted(species))
    for directory in _reference_search_paths():
        candidate = directory / f"{key}.toml"
        if candidate.is_file():
            with open(candidate, "rb") as handle:
                data = tomllib.load(handle)
            return ActivationReferences(
                real=bool(data.get("real", False)),
                bond_cutoff=data.get("bond_cutoff"),
                gr=data.get("gr"),
                coordination=data.get("coordination"),
                rings=data.get("rings"),
                depth=data.get("depth"),
                source=str(candidate))
    return ActivationReferences(
        real=False, bond_cutoff=None, gr=None, coordination=None,
        rings=None, depth=None, source=f"MISSING ({key})")


# ---------------------------------------------------------------------
# Shared structural kernels. Each is O(N^2) but runs once per activation
# (a validation step, not per MD step), on a slab of a few thousand atoms.
# Minimum-image is applied in the two PERIODIC in-plane directions only
# (the z-boundary is open, `p p f`); the stand-in assumes an orthogonal
# in-plane cell, and the real gate uses the triclinic kernel prior art got
# right (`PRIOR_ART.md` §1.8).
# ---------------------------------------------------------------------

def coordination_numbers(
        positions: np.ndarray, cell: np.ndarray, cutoff: float) -> np.ndarray:
    """Count each atom's neighbours within ``cutoff`` (PSEUDOCODE §10.6)."""
    positions = np.asarray(positions, float)
    cell = np.asarray(cell, float)
    box_x, box_y = float(cell[0][0]), float(cell[1][1])
    counts = np.zeros(len(positions), int)
    for index in range(len(positions)):
        delta = positions - positions[index]
        if box_x > 0.0:
            delta[:, 0] -= box_x * np.round(delta[:, 0] / box_x)
        if box_y > 0.0:
            delta[:, 1] -= box_y * np.round(delta[:, 1] / box_y)
        distance = np.linalg.norm(delta, axis=1)
        counts[index] = int(np.count_nonzero(
            (distance > 1.0e-6) & (distance <= cutoff)))
    return counts


def pair_correlation(
        positions: np.ndarray, cell: np.ndarray,
        r_max: float, bin_width: float) -> Curve:
    """The radial pair-correlation g(r), density-reference normalized (§3.5).

    A histogram of pairwise distances (minimum-image in-plane) normalized
    by the ideal-gas count in each spherical shell — shell volume times the
    LOCAL slab number density, the density-reference normalization that is
    the sound prior-art kernel (`PRIOR_ART.md` §1.5): using the slab's own
    density, not a full-cell density, keeps sputtering losses from
    inflating the peaks. Returns the recorded curve.
    """
    positions = np.asarray(positions, float)
    cell = np.asarray(cell, float)
    box_x, box_y = float(cell[0][0]), float(cell[1][1])
    z = positions[:, 2]
    slab_volume = box_x * box_y * max(float(z.max() - z.min()), 1.0e-6)
    number_density = len(positions) / slab_volume

    edges = np.arange(0.0, r_max + bin_width, bin_width)
    counts = np.zeros(len(edges) - 1)
    for index in range(len(positions)):
        delta = positions - positions[index]
        delta[:, 0] -= box_x * np.round(delta[:, 0] / box_x)
        delta[:, 1] -= box_y * np.round(delta[:, 1] / box_y)
        distance = np.linalg.norm(delta, axis=1)
        distance = distance[(distance > 1.0e-6) & (distance < r_max)]
        counts += np.histogram(distance, bins=edges)[0]

    shell_volume = (4.0 / 3.0) * np.pi * (edges[1:] ** 3 - edges[:-1] ** 3)
    ideal = len(positions) * shell_volume * number_density
    g = np.divide(counts, ideal, out=np.zeros_like(counts), where=ideal > 0)
    centres = 0.5 * (edges[1:] + edges[:-1])
    return Curve(x=tuple(centres.tolist()), y=tuple(g.tolist()))


def bond_graph(
        positions: np.ndarray, cell: np.ndarray, cutoff: float,
        subset: np.ndarray | None = None) -> nx.Graph:
    """Build the bond network within ``cutoff`` (PSEUDOCODE §10.6).

    Nodes are atom indices (optionally restricted to ``subset`` — the
    near-surface skin, so the ring search stays small); an edge joins two
    atoms closer than ``cutoff`` under the in-plane minimum image.
    """
    positions = np.asarray(positions, float)
    cell = np.asarray(cell, float)
    box_x, box_y = float(cell[0][0]), float(cell[1][1])
    indices = (np.arange(len(positions)) if subset is None
               else np.asarray(subset))
    graph = nx.Graph()
    graph.add_nodes_from(int(i) for i in indices)
    subset_positions = positions[indices]
    for local_index, atom_index in enumerate(indices):
        delta = subset_positions - positions[atom_index]
        delta[:, 0] -= box_x * np.round(delta[:, 0] / box_x)
        delta[:, 1] -= box_y * np.round(delta[:, 1] / box_y)
        distance = np.linalg.norm(delta, axis=1)
        for other_local, other_index in enumerate(indices):
            if (other_index > atom_index
                    and 1.0e-6 < distance[other_local] <= cutoff):
                graph.add_edge(int(atom_index), int(other_index))
    return graph


# ---------------------------------------------------------------------
# The pluggable ring-enumeration backend (DESIGN §3.5). v1 = networkx King
# / shortest-path rings; the Imago bond_analysis.py ring tool is the
# candidate replacement, evaluated for narrowness before adoption.
# ---------------------------------------------------------------------

class NetworkxRingBackend:
    """King / shortest-path ring enumeration on a `networkx` graph.

    A ring through an atom for a pair of its bonded neighbours is that atom
    plus the shortest path between the two neighbours that does NOT pass
    back through the atom; its size is that path length plus one. Rings are
    de-duplicated by their atom set, and the search is capped at
    ``max_ring_size`` so a slab's large-scale connectivity does not blow up
    the count. This is the standard definition for amorphous silicon.
    """

    name = "networkx"

    def ring_size_histogram(
            self, graph: nx.Graph, max_ring_size: int) -> dict:
        """Return ``{ring_size: count}`` for the graph's shortest-path rings."""
        histogram: Counter = Counter()
        seen: set = set()
        for node in list(graph.nodes):
            neighbours = list(graph.neighbors(node))
            if len(neighbours) < 2:
                continue
            reduced = graph.copy()
            reduced.remove_node(node)
            for first in range(len(neighbours)):
                for second in range(first + 1, len(neighbours)):
                    try:
                        path = nx.shortest_path(
                            reduced, neighbours[first], neighbours[second])
                    except (nx.NetworkXNoPath, nx.NodeNotFound):
                        continue
                    ring_size = len(path) + 1
                    if ring_size > max_ring_size:
                        continue
                    ring_nodes = frozenset(path) | {node}
                    if len(ring_nodes) != ring_size or ring_nodes in seen:
                        continue
                    seen.add(ring_nodes)
                    histogram[ring_size] += 1
        return dict(histogram)


RING_BACKEND = NetworkxRingBackend()


def non_six_ring_fraction(histogram: dict) -> float:
    """The fraction of rings that are NOT six-membered (PSEUDOCODE §10.6).

    Crystalline silicon is all six-rings; five- and seven-rings are the
    signature of the amorphous network, so their share is the discriminator.
    """
    total = sum(histogram.values())
    if total == 0:
        return 0.0
    return (total - histogram.get(6, 0)) / total


# ---------------------------------------------------------------------
# Gate control (engineering settings) and the shared per-run context.
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class GateControl:
    """Engineering settings for the gate (not physics; DESIGN §3.5).

    ``near_surface_window`` is the skin-region thickness the coordination
    and ring metrics work in (so the crystalline bulk does not dilute the
    signal and the ring search stays small); ``depth_bin_width`` bins the
    depth profile; the ``gr_*`` settings size the g(r) histogram; and
    ``max_ring_size`` caps the ring search.
    """

    near_surface_window: float = 15.0     # Å, the skin region
    depth_bin_width: float = 2.0          # Å, depth-profile bin
    gr_r_max: float = 6.0                 # Å, g(r) range
    gr_bin_width: float = 0.05            # Å, g(r) bin
    max_ring_size: int = 9                # cap on the ring search


@dataclass(frozen=True)
class GateContext:
    """Precomputed quantities shared by the metrics (efficiency).

    The coordination count and the crystalline reference are computed ONCE
    here and reused by the coordination and depth metrics, rather than each
    metric recomputing the O(N^2) neighbour list. The ring metric builds
    its own (near-surface) graph.
    """

    positions: np.ndarray
    cell: np.ndarray
    bond_cutoff: float
    coordination: np.ndarray
    reference_coordination: int
    is_defect: np.ndarray
    near_surface: np.ndarray              # boolean mask of the skin atoms


def _reference_coordination(
        positions: np.ndarray, coordination: np.ndarray) -> int:
    """The crystalline reference coordination: the mode of the deep third.

    Self-referential (DESIGN §3.5) — the deep bulk of the same slab is
    still crystalline — so no per-material constant is needed.
    """
    z = positions[:, 2]
    low, high = float(z.min()), float(z.max())
    deep = z < low + (high - low) / 3.0
    sample = coordination[deep] if deep.any() else coordination
    return int(np.bincount(sample).argmax())


def _unresolved(name: str) -> MetricVerdict:
    """A verdict for a metric whose reference was missing — never passes."""
    return MetricVerdict(
        name=name, measured=None, reference="UNRESOLVED",
        threshold=None, passed=False)


# ---------------------------------------------------------------------
# The four registered metrics (PSEUDOCODE §10.6). Each takes the shared
# context, the references, and the gate control, and returns a
# MetricVerdict. They are plain objects with a `name` and `evaluate`.
# ---------------------------------------------------------------------

class RadialDistributionMetric:
    """g(r) — RECORDED for inspection, coarse first-peak auto-pass (§3.5)."""

    name = "radial_distribution"

    def evaluate(self, context: GateContext,
                 references: ActivationReferences,
                 control: GateControl) -> MetricVerdict:
        if references.gr is None:
            return _unresolved(self.name)
        curve = pair_correlation(
            context.positions, context.cell,
            control.gr_r_max, control.gr_bin_width)
        radii = np.asarray(curve.x)
        values = np.asarray(curve.y)
        # The first peak: the tallest g(r) within the first-neighbour window.
        window = radii <= references.gr["first_peak"] + 1.0
        first_peak = float(radii[window][np.argmax(values[window])]) \
            if window.any() else 0.0
        tolerance = float(references.gr["first_peak_tolerance"])
        passed = abs(first_peak - references.gr["first_peak"]) <= tolerance
        return MetricVerdict(
            name=self.name, measured=first_peak, reference=references.source,
            threshold=tolerance, passed=passed, detail=curve)


class CoordinationMetric:
    """Defect fraction in the skin, within an amorphous band (§3.5)."""

    name = "coordination"

    def evaluate(self, context: GateContext,
                 references: ActivationReferences,
                 control: GateControl) -> MetricVerdict:
        if references.coordination is None:
            return _unresolved(self.name)
        skin = context.near_surface
        # Fraction of skin atoms whose coordination differs from the
        # crystalline reference — NOT the mean, since a-Si stays ~4-fold.
        defect_fraction = (float(context.is_defect[skin].mean())
                           if skin.any() else 0.0)
        low = float(references.coordination["defect_fraction_min"])
        high = float(references.coordination["defect_fraction_max"])
        return MetricVerdict(
            name=self.name, measured=defect_fraction,
            reference=references.source, threshold=(low, high),
            passed=low <= defect_fraction <= high)


class RingStatisticsMetric:
    """Non-six-ring fraction in the skin, via the pluggable backend (§3.5)."""

    name = "ring_statistics"

    def evaluate(self, context: GateContext,
                 references: ActivationReferences,
                 control: GateControl) -> MetricVerdict:
        if references.rings is None:
            return _unresolved(self.name)
        skin_indices = np.where(context.near_surface)[0]
        graph = bond_graph(
            context.positions, context.cell, context.bond_cutoff,
            subset=skin_indices)
        histogram = RING_BACKEND.ring_size_histogram(
            graph, control.max_ring_size)
        fraction = non_six_ring_fraction(histogram)
        target = float(references.rings["non_six_fraction_min"])
        sizes = sorted(histogram)
        detail = Curve(x=tuple(sizes),
                       y=tuple(histogram[size] for size in sizes))
        return MetricVerdict(
            name=self.name, measured=fraction, reference=references.source,
            threshold=target, passed=fraction >= target, detail=detail)


class AmorphizationDepthMetric:
    """Return-to-baseline amorphization depth (§3.5); supplies the depth."""

    name = "amorphization_depth"

    def evaluate(self, context: GateContext,
                 references: ActivationReferences,
                 control: GateControl) -> MetricVerdict:
        if references.depth is None:
            return _unresolved(self.name)
        depth = self._depth(context, control)
        target = float(references.depth["target_angstrom"])
        return MetricVerdict(
            name=self.name, measured=depth, reference=references.source,
            threshold=target, passed=depth >= target)

    def _depth(self, context: GateContext, control: GateControl) -> float:
        """The skin depth: contiguous-from-surface above the bulk baseline.

        Bin the coordination-defect fraction by depth, take the bulk
        baseline from the deep third, and measure from the free surface
        down the contiguous region whose defect fraction stays above the
        baseline — using the whole profile and ignoring the frozen BOTTOM
        surface (also under-coordinated), the robust replacement for prior
        art's stop-at-first-crystalline scan (DESIGN §3.5).
        """
        z = context.positions[:, 2]
        low, high = float(z.min()), float(z.max())
        width = control.depth_bin_width
        edges = np.arange(low, high + width, width)

        def bin_fraction(mask):
            return float(context.is_defect[mask].mean()) if mask.any() else 0.0

        fractions = []
        for lower, upper in zip(edges[:-1], edges[1:]):
            in_bin = (z >= lower) & (z < upper)
            fractions.append((lower, bin_fraction(in_bin)))

        deep_cut = low + (high - low) / 3.0
        deep = [frac for lower, frac in fractions if lower < deep_cut]
        baseline = (float(np.mean(deep)) if deep else 0.0) + 0.05

        depth = 0.0
        for lower, fraction in reversed(fractions):        # surface downward
            if fraction > baseline:
                depth = high - lower
            else:
                break
        return depth


ACTIVATION_METRICS = [
    RadialDistributionMetric(),
    CoordinationMetric(),
    RingStatisticsMetric(),
    AmorphizationDepthMetric(),
]


# ---------------------------------------------------------------------
# The gate (PSEUDOCODE §10.6).
# ---------------------------------------------------------------------

def activation_gate(
        positions: np.ndarray,
        cell: np.ndarray,
        references: ActivationReferences,
        control: GateControl = GateControl()) -> ActivationVerdict:
    """Judge a re-annealed slab with every registered metric (§10.6).

    Builds the shared context (coordination, crystalline self-reference,
    skin mask), runs each metric, and passes iff EVERY metric passes,
    naming the first failure. The depth metric supplies ``activated_depth``.
    With no reference at all (a missing file), every metric is UNRESOLVED
    and the gate fails — a stand-in is never silently defaulted.
    """
    positions = np.asarray(positions, float)
    if positions.shape[0] == 0:
        return ActivationVerdict(
            passed=False, activated_depth=0.0, per_metric={},
            reason="no atoms to judge")
    if references.bond_cutoff is None:
        return ActivationVerdict(
            passed=False, activated_depth=0.0, per_metric={},
            reason=f"no activation reference found ({references.source})")

    cell = np.asarray(cell, float)
    coordination = coordination_numbers(
        positions, cell, references.bond_cutoff)
    reference_coordination = _reference_coordination(positions, coordination)
    surface_high = float(positions[:, 2].max())
    context = GateContext(
        positions=positions, cell=cell, bond_cutoff=references.bond_cutoff,
        coordination=coordination,
        reference_coordination=reference_coordination,
        is_defect=coordination != reference_coordination,
        near_surface=positions[:, 2] > surface_high
        - control.near_surface_window)

    per_metric = {}
    for metric in ACTIVATION_METRICS:
        per_metric[metric.name] = metric.evaluate(context, references, control)

    depth_verdict = per_metric["amorphization_depth"]
    activated_depth = float(depth_verdict.measured or 0.0)
    passed = all(verdict.passed for verdict in per_metric.values())
    reason = "" if passed else next(
        f"{name}: measured {verdict.measured} vs {verdict.threshold} "
        f"({verdict.reference})"
        for name, verdict in per_metric.items() if not verdict.passed)
    return ActivationVerdict(
        passed=passed, activated_depth=activated_depth,
        per_metric=per_metric, reason=reason)
