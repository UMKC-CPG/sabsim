"""Unit tests for the surface-activation cascade command block (§10).

Like the press/pull command tests these assert the generated STRINGS with
no LAMMPS present: the standalone-slab region carving (frozen base,
Langevin border, projectile-spawn scaffolding), the heat-sink integrators
(``fix nve all`` + a frozen base + a bias-removed border thermostat), the
adaptive-then-fixed timestep toggle, projectile insertion, the
physical-time cascade halt, and the one-time setup assembler. The knobs
come from the real study-spec template so the field names are checked
against the true records.
"""

import os

import pytest

from sabsim.driver.cascade_potential import resolve_cascade_generator
from sabsim.driver.commands import (
    CascadeGeometry,
    cascade_adaptive_timestep_commands,
    _lammps_number,
    cascade_fixed_timestep_commands,
    cascade_halt_commands,
    cascade_integrator_commands,
    cascade_prerelax_commands,
    cascade_region_group_commands,
    cascade_setup_commands,
    insert_projectile_commands,
)
from sabsim.spec.loader import load_and_validate_study

_TEMPLATE_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "dev", "templates", "study_spec.toml"))


def _template_member():
    """The first template member — a real MemberSpecification."""
    return load_and_validate_study(_TEMPLATE_PATH).members[0]


# ---------------------------------------------------------------------
# Region carving: a standalone slab, base and border stacked from the
# bottom, the spawn band above the free surface (§10.2).
# ---------------------------------------------------------------------

def test_cascade_regions_stack_base_then_border_from_the_bottom():
    """Frozen base then Langevin border rise from ``base_low`` (§10.2)."""
    commands = cascade_region_group_commands(
        base_low=10.0, surface_high=40.0,
        geometry=CascadeGeometry(
            frozen_base_thickness=4.0, border_thickness=6.0,
            spawn_height=10.0))
    # Base spans [10, 14]; border sits just above it, [14, 20].
    assert "region frozen_base block INF INF INF INF 10 14 units box" \
        in commands
    assert "region border block INF INF INF INF 14 20 units box" in commands
    assert "group frozen_base region frozen_base" in commands
    assert "group border region border" in commands


def test_cascade_spawn_band_sits_above_the_free_surface():
    """The projectile is born in a thin band above the surface (§10.4)."""
    commands = cascade_region_group_commands(
        base_low=10.0, surface_high=40.0,
        geometry=CascadeGeometry(spawn_height=10.0))
    # Surface 40 + spawn height 10 = 50, half-band 1.0 -> [49, 51], and the
    # projectile group starts (empty) from that region.
    assert "region spawn block INF INF INF INF 49 51 units box" in commands
    assert "group projectile region spawn" in commands


# ---------------------------------------------------------------------
# The heat-sink integrators (§10.2).
# ---------------------------------------------------------------------

def test_cascade_integrator_is_nve_all_plus_frozen_base_plus_border():
    """All atoms integrate; base is frozen; border is thermostatted."""
    commands = cascade_integrator_commands(_template_member(), seed=4242)
    # NVE on ALL, so projectiles created mid-run integrate automatically.
    assert "fix nve_all all nve" in commands
    # The base is held immobile by zeroing its force (the recoil anchor).
    assert "fix freeze_base frozen_base setforce 0.0 0.0 0.0" in commands
    # The border thermostat has its center-of-mass drift removed first.
    assert "compute cascade_border_temp border temp/com" in commands
    assert any(line.startswith("fix langevin_border border langevin")
               and line.endswith("4242") for line in commands)
    assert "fix_modify langevin_border temp cascade_border_temp" in commands


# ---------------------------------------------------------------------
# Adaptive-then-fixed timestep toggle (§10.4).
# ---------------------------------------------------------------------

def test_adaptive_timestep_caps_move_and_uses_cascade_step_as_ceiling():
    """dt/reset caps the per-step move; the ceiling is cascade_timestep."""
    member = _template_member()
    commands = cascade_adaptive_timestep_commands(member)
    line = commands[0]
    assert line.startswith("fix cascade_dt all dt/reset 1 ")
    # The documented max-move stand-in (0.1 A) is the final argument.
    assert line.endswith(" 0.1")


def test_fixed_timestep_removes_adaptive_and_pins_the_step():
    """The relaxation restores a fixed step (dt/reset off, timestep set)."""
    commands = cascade_fixed_timestep_commands(_template_member())
    assert commands[0] == "unfix cascade_dt"
    assert commands[1].startswith("timestep ")


def test_relaxation_runs_at_the_md_step_not_the_cascade_step():
    """The cool-down uses md_timestep, NOT the tiny cascade step.

    The cascade step exists only to keep a fast recoil off the ZBL
    wall; by the relaxation the cascade has halted and the energy has
    thermalized. Pinning the cool-down to the cascade step would spend
    ten times the steps for the same physical time (LEDGER T-21 put it
    at 49% of a single-impact run).
    """
    from sabsim.driver.commands import to_metal
    member = _template_member()
    commands = cascade_fixed_timestep_commands(member)
    md_step = to_metal(member.numerical.md_timestep, "time")
    cascade_step = to_metal(member.numerical.cascade_timestep, "time")
    # The two must differ, or the test proves nothing.
    assert md_step != cascade_step
    assert commands[1] == f"timestep {_lammps_number(md_step)}"


# ---------------------------------------------------------------------
# Projectile insertion and the physical-time halt (§10.4).
# ---------------------------------------------------------------------

def test_insert_projectile_clears_creates_groups_and_aims():
    """Each impact refills the projectile group and sets its velocity."""
    commands = insert_projectile_commands(
        projectile_type=2, position=(5.0, 6.0, 50.0),
        velocity=(0.0, 0.0, -155.3))
    assert commands[0] == "group projectile clear"       # never a stale atom
    assert commands[1] == (
        "create_atoms 2 single 5 6 50 units box")
    assert commands[2] == "group projectile region spawn"
    assert commands[3] == (
        "velocity projectile set 0 0 -155.3 units box")


def test_cascade_halt_watches_elapsed_simulation_time():
    """The cascade ends after a TIME span, not a fixed step count (§10.4)."""
    commands = cascade_halt_commands(duration=5.0)
    # The start time is re-snapshotted for this impact, then the halt
    # watches time elapsed since it — kept inside LAMMPS, no clock
    # read-back needed by the driver.
    assert commands[0] == "variable cascade_start equal $(time)"
    assert commands[1] == (
        "fix cascade_halt all halt 10 v_elapsed_cascade > 5 error continue")


# ---------------------------------------------------------------------
# The one-time setup assembler (§10.2).
# ---------------------------------------------------------------------

def test_cascade_setup_opens_the_top_and_defines_elapsed_time():
    """Setup uses the open p p f box and defines the halt's time variable."""
    member = _template_member()
    force_model = resolve_cascade_generator(
        {"Si": 1, "Ar": 2}, projectile_species={"Ar"}, use_classical=True)
    commands = cascade_setup_commands(
        member, force_model, data_file="slab.data",
        base_low=10.0, surface_high=40.0, seed=7)
    # The open top so sputtered atoms leave rather than wrap (§3.3).
    assert "boundary p p f" in commands
    # The cascade-clock variable the per-impact halt watches.
    assert "variable elapsed_cascade equal time-v_cascade_start" in commands
    # The classical + ZBL force model is loaded, and the heat-sink
    # integrators are present — one coherent setup.
    assert "pair_style hybrid/overlay sw zbl 0.5 2 zbl 0.5 1.2" in commands
    assert "fix nve_all all nve" in commands
    assert "fix freeze_base frozen_base setforce 0.0 0.0 0.0" in commands


def test_prerelax_minimizes_at_fixed_cell_before_the_first_impact():
    """The §2.4 pre-cascade relax is a plain position minimize (fixed box)."""
    commands = cascade_prerelax_commands()
    # A conjugate-gradient minimize with the same tolerances as the §10.5
    # re-anneal — positions only, so the box (the shared lateral cell) is
    # untouched and the frozen base's setforce keeps the bulk anchored.
    assert commands == [
        "min_style cg",
        "minimize 1e-8 1e-8 1000 10000",
    ]
    # No box/relax here: the lateral cell must NOT move (that would undo the
    # coincidence match), unlike the §2.2 bulk lattice derivation.
    assert not any("box/relax" in line for line in commands)
