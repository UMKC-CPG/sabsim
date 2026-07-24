"""Unit tests for the cascade orchestration (PSEUDOCODE.md §10.3-§10.4).

The driver runs entirely against the ``Engine`` seam, so these exercise it
with ``MockEngine`` and no LAMMPS: the impact plan derived from the real
study-spec knobs (dose to count, seeds from the master seed, projectile
mass from the species), the reproducible impact sampling (normal incidence
aims straight down; a seed replays exactly), and the per-impact command
stream the loop issues (insert -> adaptive cascade to a time halt ->
fixed-step relax). No mid-run read-back is asserted because a cascade
impact has none — the physical-time halt ends it from inside LAMMPS.
"""

import dataclasses
import math
import os
from types import SimpleNamespace

import numpy as np
import pytest

from sabsim.driver.activation_gate import ActivationVerdict
from sabsim.driver.cascade import (
    ActivationResult,
    BombardmentSpec,
    CascadeControl,
    activate_surface,
    derive_bombardment_spec,
    derive_seeds,
    mlip_reanneal,
    run_cascade_to_fluence,
    sample_impact_position,
    sample_impact_velocity,
)
from sabsim.driver.commands import classical_si_stand_in
from sabsim.driver.cascade_potential import resolve_cascade_generator
from sabsim.driver.commands import CascadeGeometry
from sabsim.driver.engine import MockEngine
from sabsim.spec.loader import load_and_validate_study

_TEMPLATE_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "dev", "templates", "study_spec.toml"))


def _template_member():
    """The template's SILICON member — a real MemberSpecification.

    Deliberately the si-si-reference member rather than the first one:
    every cell fixture in this file is a silicon slab, and a member
    declares the structural/chemical domain its force model must cover
    (DESIGN.md §4.8). Pairing a silicon-only cell with the Si/SiO2
    member would ask the registry for silicon in the silicon-and-silica
    domain, which is correctly not a registered combination. The
    protocol, numerical and ensemble knobs these tests assert on are
    shared across all members, so nothing else changes.
    """
    return load_and_validate_study(_TEMPLATE_PATH).members[1]


def _cascade_built():
    """A light standalone-slab stand-in with a projectile type declared.

    Only the geometry the driver reads: a cubic cell, a handful of atom
    positions spanning z in [0, 20], and a type map that includes the Ar
    projectile as type 2 (the cascade cell must declare it).
    """
    cell = np.array([[10.0, 0.0, 0.0], [0.0, 10.0, 0.0], [0.0, 0.0, 40.0]])
    positions = np.array([
        [1.0, 1.0, 0.0], [2.0, 2.0, 5.0], [3.0, 3.0, 10.0],
        [4.0, 4.0, 15.0], [5.0, 5.0, 20.0]])
    atoms = SimpleNamespace(
        get_cell=lambda: cell,
        get_positions=lambda: positions)
    return SimpleNamespace(atoms=atoms, type_map={"Si": 1, "Ar": 2})


# ---------------------------------------------------------------------
# Deriving the impact plan from the real study-spec knobs (§10.3).
# ---------------------------------------------------------------------

def test_seeds_are_deterministic_and_count_matched():
    """One master seed reproduces a fixed set of per-impact seeds."""
    first = derive_seeds(20260713, 8)
    second = derive_seeds(20260713, 8)
    assert first == second and len(first) == 8
    # A different master seed gives a different plan.
    assert derive_seeds(1, 8) != first


def test_spec_reads_species_mass_energy_and_count():
    """The plan takes mass from the species and the count from the dose."""
    spec = derive_bombardment_spec(_cascade_built(), _template_member())
    assert spec.projectile_symbol == "Ar"
    assert spec.projectile_type == 2
    # Argon's mass (~39.95 amu), from the periodic table, not hand-set.
    assert spec.projectile_mass == pytest.approx(39.95, abs=0.05)
    assert spec.impact_energy == 75.0           # eV, the pinned energy
    assert spec.impact_angle == 0.0             # normal incidence (0 deg)
    # The template now states the dose as an AREAL fluence, so the count
    # is DERIVED from the cell: 0.025 ions/Å² over this toy 10 x 10 Å
    # cell is 2.5 impacts, which rounds to 2. This exercises the general
    # size-independent path rather than the fixed-count shortcut.
    assert spec.impact_count == 2
    assert len(spec.impact_seeds) == 2


# ---------------------------------------------------------------------
# Reproducible impact sampling (§10.4).
# ---------------------------------------------------------------------

def test_normal_incidence_aims_straight_down_at_the_right_speed():
    """A 500 eV Ar impact at normal incidence is (0, 0, -v).

    The energy is pinned HERE rather than taken from the template on
    purpose. This is a check of the energy-to-speed physics, and 500 eV
    Ar = 491.5 Å/ps is the independently-known pair that makes it a real
    check; tying it to whatever energy the protocol currently specifies
    would break this test every time that engineering choice is retuned,
    for no gain in what it verifies.
    """
    spec = dataclasses.replace(
        derive_bombardment_spec(_cascade_built(), _template_member()),
        impact_energy=500.0)
    vx, vy, vz = sample_impact_velocity(spec, seed=123)
    assert vx == pytest.approx(0.0, abs=1e-9)
    assert vy == pytest.approx(0.0, abs=1e-9)
    # v = sqrt(2E/(m c)) ~ 491.5 Å/ps for Ar at 500 eV; it aims DOWN.
    assert vz == pytest.approx(-491.5, abs=1.0)


def test_impact_position_is_above_the_surface_and_reproducible():
    """The birth point sits at surface + spawn height, and replays."""
    built = _cascade_built()
    position = sample_impact_position(built, spawn_height=10.0, seed=7)
    # Surface is z = 20; the projectile is born 10 above it.
    assert position[2] == pytest.approx(30.0)
    # Lateral site lies within the 10x10 cell, and is deterministic.
    assert 0.0 <= position[0] <= 10.0 and 0.0 <= position[1] <= 10.0
    assert sample_impact_position(built, 10.0, 7) == position


# ---------------------------------------------------------------------
# The per-impact command stream the loop issues (§10.4).
# ---------------------------------------------------------------------

def _small_spec():
    """A two-impact plan so the emitted stream is easy to assert."""
    return BombardmentSpec(
        projectile_symbol="Ar", projectile_type=2, projectile_mass=39.95,
        impact_energy=500.0, impact_angle=0.0, impact_count=2,
        impact_seeds=(11, 22), cascade_duration=7.0,
        between_impact_relaxation=7.0)


def test_loop_opens_the_driver_then_runs_each_impact():
    """Setup once, then insert/cascade/relax per impact, fire-and-forget."""
    engine = MockEngine()
    built = _cascade_built()
    member = _template_member()
    force_model = resolve_cascade_generator(
        built.type_map, projectile_species={"Ar"})

    outcome = run_cascade_to_fluence(
        engine, built, member, force_model, data_file="slab.data",
        spec=_small_spec(), seed=99, geometry=CascadeGeometry(),
        control=CascadeControl())

    stream = engine.received_commands
    # The one-time setup opened the box and loaded the classical + ZBL model.
    assert "boundary p p f" in stream
    assert "pair_style hybrid/overlay sw zbl 0.5 2 zbl 0.5 1.2" in stream
    # Two impacts, each creating a projectile of type 2.
    assert sum(1 for line in stream
               if line.startswith("create_atoms 2 single")) == 2
    # Each impact toggles the adaptive step on for the cascade and off for
    # the relaxation, so both fixes appear twice.
    assert stream.count("unfix cascade_dt") == 2
    assert sum(1 for line in stream
               if line.startswith("fix cascade_dt all dt/reset")) == 2
    # Two runs per impact (cascade + relax): four numbered runs total.
    assert sum(1 for line in stream if line.startswith("run ")) == 4
    assert outcome.impacts_run == 2


def test_loop_orders_cascade_before_relax_within_each_impact():
    """The halted cascade run precedes the fixed-step relaxation run."""
    engine = MockEngine()
    built = _cascade_built()
    run_cascade_to_fluence(
        engine, built, _template_member(),
        resolve_cascade_generator(built.type_map, projectile_species={"Ar"}),
        data_file="slab.data", spec=_small_spec(), seed=99)

    stream = engine.received_commands
    # Within the first impact: the time-halt is installed, the capped
    # cascade runs, the halt is released, THEN the fixed step is restored
    # before the relaxation run.
    halt = stream.index("fix cascade_halt all halt 10 "
                        "v_elapsed_cascade > 7 error continue")
    release = stream.index("unfix cascade_halt")
    restore = stream.index("unfix cascade_dt")
    assert halt < release < restore


# ---------------------------------------------------------------------
# The MLIP re-anneal (§10.5).
# ---------------------------------------------------------------------

def test_reanneal_strips_projectile_then_relaxes_under_the_mlip():
    """The re-anneal drops the ZBL fixes and Ar, then gently relaxes."""
    engine = MockEngine()
    member = _template_member()
    mlip = classical_si_stand_in({"Si": 1})
    mlip_reanneal(engine, member, mlip, seed=3, projectile_types=[2])

    stream = engine.received_commands
    # The cascade's ballistic integrator and border thermostat are gone;
    # the frozen base is NOT torn down (it anchors the bulk).
    assert "unfix nve_all" in stream
    assert "unfix langevin_border" in stream
    assert "unfix freeze_base" not in stream
    # EVERY projectile atom is stripped BY TYPE (not just the last impact's
    # spawn-group atom) before the Si-only MLIP relax.
    assert "group cascade_projectiles type 2" in stream
    assert "delete_atoms group cascade_projectiles compress yes" in stream
    assert "group mobile subtract all frozen_base" in stream
    # A minimize, then a hold and a quench (two nvt setpoints), then release.
    assert "minimize 1e-8 1e-8 1000 10000" in stream
    nvt = [line for line in stream if line.startswith("fix reanneal mobile")]
    assert len(nvt) == 2                          # hold, then quench
    assert "unfix reanneal" in stream
    # Ids are renumbered consecutively before the gate reads positions
    # (sputtering + deletion leave gaps that gather_atoms rejects).
    assert "reset_atoms id" in stream


# ---------------------------------------------------------------------
# A crafted crystal slab, shared by the integration test below. The gate
# METRICS themselves are unit-tested in test_activation_gate.py.
# ---------------------------------------------------------------------

def _crystal_slab(spacing=2.5, n_lateral=4, n_layers=8):
    """A simple-cubic crystal slab, periodic in-plane, open in z.

    Interior atoms have coordination 6 within a 2.9 Å shell (four in-plane
    neighbours, since the √2 diagonal lies outside, plus two in z); the top
    and bottom layers are 5-coordinated free surfaces.
    """
    xs = np.arange(n_lateral) * spacing
    ys = np.arange(n_lateral) * spacing
    zs = np.arange(n_layers) * spacing
    points = np.array([[x, y, z] for z in zs for y in ys for x in xs])
    box = n_lateral * spacing
    cell = np.diag([box, box, (n_layers + 4) * spacing])
    return points, cell


# ---------------------------------------------------------------------
# Activating one surface end to end (§10.1).
# ---------------------------------------------------------------------

def test_activate_surface_runs_cascade_reanneal_then_gates():
    """One surface: bombard, re-anneal, and gate — a real verdict falls out."""
    points, cell = _crystal_slab()
    surface = points[:, 2].max()
    scrambled = points.copy()
    top = scrambled[:, 2] > surface - 6.0
    generator = np.random.default_rng(1)
    scrambled[top] += generator.uniform(-1.2, 1.2, size=(int(top.sum()), 3))

    # The engine plays back the amorphized frame for the gate's read.
    engine = MockEngine(positions=[scrambled])
    built = SimpleNamespace(
        atoms=SimpleNamespace(
            get_cell=lambda: cell,
            get_positions=lambda: points),
        type_map={"Si": 1, "Ar": 2})
    member = _template_member()
    mlip = classical_si_stand_in({"Si": 1})

    result = activate_surface(
        engine, built, member, mlip, data_file="slab.data", seed=5)

    assert isinstance(result, ActivationResult)
    # Bombarded to the dose: the areal fluence over this toy cell's small
    # lateral area works out to 2 impacts (see the spec test above).
    assert result.cascade.impacts_run == 2
    # The real §3.5 gate ran against the share/ Si references and produced a
    # verdict over all four metrics (pass/fail depends on the stand-in
    # thresholds, which this thin toy slab need not satisfy).
    assert isinstance(result.verdict, ActivationVerdict)
    assert set(result.verdict.per_metric) == {
        "radial_distribution", "coordination", "ring_statistics",
        "amorphization_depth"}
    # The command stream shows all three phases.
    stream = engine.received_commands
    assert any(line.startswith("create_atoms 2 single") for line in stream)
    assert "delete_atoms group cascade_projectiles compress yes" in stream
