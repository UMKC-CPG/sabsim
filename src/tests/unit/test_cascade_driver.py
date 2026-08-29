"""Unit tests for the cascade orchestration (PSEUDOCODE.md §10.3-§10.4).

The driver only assembles command streams, so these run with no LAMMPS:
the impact plan derived from the real
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

from sabsim.driver.cascade import (
    BombardmentSpec,
    CascadeControl,
    CascadeOutcome,
    build_activate_script,
    cascade_cleanup_commands,
    derive_bombardment_spec,
    derive_seeds,
    sample_impact_position,
    sample_impact_velocity,
)
from sabsim.driver.cascade_potential import resolve_cascade_generator
from sabsim.driver.commands import CascadeGeometry
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








# ---------------------------------------------------------------------
# The out-of-process activate script (§10.1, ARCHITECTURE §4.3): the whole
# LAMMPS half emitted as one self-contained script for the universal-MLIP
# cascade engine, which cannot share this process's LAMMPS.
# ---------------------------------------------------------------------

def test_build_activate_script_emits_setup_impacts_cleanup_and_handoff():
    """The script is setup -> prerelax -> impacts -> cleanup -> heal -> dump.

    Revised 2026-08-28 (§3.4): the heal runs at the end of the same
    session, after the strip, and writes its start-step marker; the gate
    then judges the healed half the final dump hands back.
    """
    built = _cascade_built()
    member = _template_member()
    spec = _small_spec()
    cascade = resolve_cascade_generator(
        built.type_map, projectile_species={"Ar"},
        weights_path="/models/dpa3.pth", allow_unvalidated=True)

    script = build_activate_script(
        built, member, cascade, data_file="slab.data", spec=spec,
        seed=99, projectile_types=[2],
        output_structure_file="activated.dump",
        heal_marker_file="activated.heal_step")

    # It is one flat list of command strings, no engine involved.
    assert all(isinstance(line, str) for line in script)
    # The box is opened once and the cascade + ZBL model is loaded (setup).
    assert "boundary p p f" in script
    assert ("pair_style hybrid/overlay deepmd /models/dpa3.pth "
            "zbl 0.5 2 zbl 0.5 1.2") in script
    # One projectile is created per impact (the small spec delivers two).
    assert sum(1 for line in script
               if line.startswith("create_atoms 2 single")) == spec.impact_count
    # The cleanup renumbers survivors, THEN the heal: its marker, the
    # anneal on the study's schedule, and the closing minimize — in that
    # order (anneal, then minimize, PSEUDOCODE §9.7).
    strip = script.index("reset_atoms id")
    marker = script.index(
        'print "$(step)" file activated.heal_step screen no')
    hold = next(i for i, line in enumerate(script)
                if line.startswith("fix heal_hold heal_mobile nvt"))
    quench = next(i for i, line in enumerate(script)
                  if line.startswith("fix heal_quench heal_mobile nvt"))
    minimize = len(script) - 1 - script[::-1].index(
        "minimize 1e-6 1e-6 200 2000")
    assert strip < marker < hold < quench < minimize
    # ...and the LAST line is the healed-structure handoff.
    assert script[-1] == (
        "write_dump all custom activated.dump id type x y z modify sort id")


def test_activate_script_records_a_trajectory_when_asked():
    """An opt-in trajectory_file opens ONE strided movie, off by default.

    The dump is opened after the §2.4 prerelax and BEFORE the first impact,
    so the whole bombardment is one continuous movie; it is ABSENT unless a
    trajectory_file is given — the frames are expensive, so a run nobody
    watches pays nothing (`run_options`).
    """
    built = _cascade_built()
    member = _template_member()
    spec = _small_spec()
    cascade = resolve_cascade_generator(
        built.type_map, projectile_species={"Ar"},
        weights_path="/models/dpa3.pth", allow_unvalidated=True)

    quiet = build_activate_script(
        built, member, cascade, data_file="slab.data", spec=spec,
        seed=99, projectile_types=[2],
        output_structure_file="activated.dump",
        heal_marker_file="activated.heal_step")
    assert not any(line.startswith("dump traj") for line in quiet)

    movie = build_activate_script(
        built, member, cascade, data_file="slab.data", spec=spec,
        seed=99, projectile_types=[2],
        output_structure_file="activated.dump",
        heal_marker_file="activated.heal_step",
        trajectory_file="cascade.dump", trajectory_stride=250)
    dump_lines = [index for index, line in enumerate(movie)
                  if line.startswith("dump traj")]
    assert len(dump_lines) == 1
    assert movie[dump_lines[0]] == (
        "dump traj all custom 250 cascade.dump id type x y z")
    # Opened BEFORE the first impact, so the movie covers every collision.
    first_impact = next(index for index, line in enumerate(movie)
                        if line.startswith("create_atoms 2 single"))
    assert dump_lines[0] < first_impact




# ---------------------------------------------------------------------
# The MLIP re-anneal (§10.5).
# ---------------------------------------------------------------------



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
