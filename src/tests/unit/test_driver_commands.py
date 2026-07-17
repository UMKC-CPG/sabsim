"""Unit tests for the press/pull command generator (sabsim.driver).

Slice 2 is a PURE {value, unit} -> LAMMPS-command mapping, so these tests
assert the generated STRINGS with no LAMMPS present: the metal-unit
conversions, the parameterized force-model line (classical AND MLIP), the
by-position region carving, both press control modes, the pull drive, and
the two assembled scripts. The knobs come from the REAL study-spec
template so the field names are checked against the true records; the
geometry is a light fake, since these functions only read a few
attributes and never touch the simulator.
"""

import dataclasses
import os
from types import SimpleNamespace

import numpy as np
import pytest

from sabsim.driver.commands import (
    ForceModel,
    RegionGeometry,
    classical_si_stand_in,
    deepmd_model,
    force_model_commands,
    integrator_commands,
    normal_force_from_pressure,
    preamble_commands,
    press_drive_commands,
    press_script,
    pull_drive_commands,
    pull_script,
    region_group_commands,
    to_metal,
)
from sabsim.spec.loader import load_and_validate_study
from sabsim.spec.records import Quantity

_TEMPLATE_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "dev", "templates", "study_spec.toml"))


def _template_member():
    """The first template member — a real MemberSpecification."""
    return load_and_validate_study(_TEMPLATE_PATH).members[0]


def _fake_pair():
    """A light stand-in with just the geometry the generator reads."""
    cell = np.array([[3.84, 0.0, 0.0], [0.0, 3.84, 0.0], [0.0, 0.0, 60.0]])
    return SimpleNamespace(
        wafer_a_z_range=(10.0, 25.0),
        wafer_b_z_range=(28.0, 43.0),
        type_map={"Si": 1},
        atoms=SimpleNamespace(get_cell=lambda: cell))


# ---------------------------------------------------------------------
# Units carried as data land as bare numbers in metal units (§1.5).
# ---------------------------------------------------------------------

def test_metal_unit_conversions():
    """Each spec unit converts to its LAMMPS metal-unit number."""
    assert to_metal(Quantity(1.0, "MPa"), "pressure") == 10.0
    assert to_metal(Quantity(1.0, "m/s"), "velocity") == 0.01
    assert to_metal(Quantity(1.0, "fs"), "time") == 0.001
    assert to_metal(Quantity(300.0, "K"), "temperature") == 300.0
    assert to_metal(Quantity(2.5, "angstrom"), "distance") == 2.5


def test_wrong_dimension_is_rejected():
    """A time where a distance is expected is caught, not miscommanded."""
    with pytest.raises(ValueError):
        to_metal(Quantity(1.0, "fs"), "distance")


def test_unknown_unit_is_rejected():
    """A unit the metal table does not know is rejected with a message."""
    with pytest.raises(ValueError):
        to_metal(Quantity(1.0, "furlong"), "distance")


def test_normal_force_from_pressure():
    """Pressure times area becomes a metal force (eV/Å)."""
    # 1 MPa = 10 bar; over a 14.7456 Å² cell the total force is small.
    force = normal_force_from_pressure(Quantity(1.0, "MPa"), 14.7456)
    expected = 10.0 * (1.0 / 1.602176634e6) * 14.7456
    assert force == pytest.approx(expected)


# ---------------------------------------------------------------------
# The force model is one parameterized line, serving classical AND MLIP.
# ---------------------------------------------------------------------

def test_classical_stand_in_force_model():
    """The classical stand-in is Stillinger-Weber over the type map."""
    model = classical_si_stand_in({"Si": 1})
    assert model.pair_style == "sw"
    assert model.pair_coeff == ("* * Si.sw Si",)


def test_deepmd_force_model():
    """The trained potential is the SAME shape, a different value."""
    model = deepmd_model("committee.pb")
    assert model.pair_style == "deepmd committee.pb"
    assert model.pair_coeff == ("* *",)


def test_force_model_commands_emit_both_lines():
    """One generator emits pair_style + pair_coeff for any ForceModel."""
    model = ForceModel(pair_style="sw", pair_coeff=("* * Si.sw Si",))
    commands = force_model_commands(model)
    assert commands == ["pair_style sw", "pair_coeff * * Si.sw Si"]


# ---------------------------------------------------------------------
# Preamble and region carving.
# ---------------------------------------------------------------------

def test_preamble_sets_metal_units_and_open_z_box():
    """Metal units, an open-z box, the data file, and the timestep."""
    commands = preamble_commands("pair.data", Quantity(1.0, "fs"))
    assert commands[0] == "units metal"
    assert "boundary p p f" in commands
    assert "read_data pair.data" in commands
    assert "timestep 0.001" in commands


def test_region_groups_carve_by_z_position():
    """Grips, borders, and interior come from the per-wafer z-ranges."""
    commands = region_group_commands(_fake_pair(), RegionGeometry())
    text = "\n".join(commands)
    # grip_thickness 4: bottom grip [10,14], top grip [39,43].
    assert "region bottom_grip block INF INF INF INF 10 14 units box" in text
    assert "region top_grip block INF INF INF INF 39 43 units box" in text
    # border_thickness 6, just inside each grip.
    assert "region lower_border block INF INF INF INF 14 20 units box" in text
    assert "region upper_border block INF INF INF INF 33 39 units box" in text
    assert "group interior subtract all grips border" in text


# ---------------------------------------------------------------------
# Integrators, the bias-removed thermostat, and both drive modes.
# ---------------------------------------------------------------------

def test_integrator_thermostats_border_bias_removed():
    """NVE interior + NVE-and-Langevin border, COM bias removed (§5.2)."""
    commands = integrator_commands(_template_member(), seed=12345)
    text = "\n".join(commands)
    assert "fix nve_interior interior nve" in text
    # The border is INTEGRATED as well as thermostatted: a Langevin fix
    # alone adds forces but never advances, leaving a reflecting wall
    # rather than the §5.2 heat sink. Its own nve is what makes it move.
    assert "fix nve_border border nve" in text
    assert "compute border_temp border temp/com" in text
    # 300 K setpoint, 0.5 ps damping, the given seed.
    assert "fix langevin_border border langevin 300 300 0.5 12345" in text
    assert "fix_modify langevin_border temp border_temp" in text


def test_press_drive_load_mode_ramps_a_normal_force():
    """Load control applies a ramped normal force via aveforce (§9.3)."""
    commands = press_drive_commands(_fake_pair(), _template_member())
    text = "\n".join(commands)
    assert "variable press_fz equal ramp(0.0," in text
    assert "fix drive_top top_grip aveforce 0.0 0.0 v_press_fz" in text


def test_press_drive_displacement_mode_moves_the_grip():
    """Displacement control rigidly moves the top grip down at rate."""
    member = _template_member()
    displacement = dataclasses.replace(
        member,
        protocol=dataclasses.replace(
            member.protocol, press_control="displacement"))
    commands = press_drive_commands(_fake_pair(), displacement)
    # 1 m/s = 0.01 Å/ps, downward.
    assert commands == [
        "fix drive_top top_grip move linear 0.0 0.0 -0.01 units box"]


def test_pull_drive_holds_bottom_and_records_both_reactions():
    """The pull holds the bottom grip and records both reactions (§5.4)."""
    commands = pull_drive_commands(Quantity(3.2, "m/s"))
    text = "\n".join(commands)
    assert "fix hold_bottom bottom_grip setforce 0.0 0.0 0.0" in text
    # 3.2 m/s = 0.032 Å/ps, upward (positive z).
    assert "fix drive_top top_grip move linear 0.0 0.0 0.032 units box" in text
    assert "compute top_reaction top_grip reduce sum fz" in text


# ---------------------------------------------------------------------
# The assembled scripts: ordered, complete, deterministic run lengths.
# ---------------------------------------------------------------------

def test_press_script_is_ordered_and_runs_the_hold():
    """The press script sets up, drives, approaches, and holds in order."""
    member = _template_member()
    model = classical_si_stand_in({"Si": 1})
    commands = press_script(
        _fake_pair(), member, model, "pair.data", seed=7)

    assert commands[0] == "units metal"
    assert "pair_style sw" in commands
    assert "fix drive_top top_grip aveforce 0.0 0.0 v_press_fz" in commands
    # Two runs: approach (gap 3 Å at 0.01 Å/ps = 300 ps / 0.001 ps =
    # 300000 steps) then the 150 ps hold (150000 steps).
    runs = [c for c in commands if c.startswith("run ")]
    assert runs == ["run 300000", "run 150000"]


def test_pull_script_records_and_runs_the_distance():
    """The pull script drives, records strided frames, and runs once."""
    member = _template_member()
    model = classical_si_stand_in({"Si": 1})
    commands = pull_script(
        _fake_pair(), member, model, "reference.data",
        rate=Quantity(3.2, "m/s"),
        pull_distance=Quantity(20.0, "angstrom"), seed=7)

    text = "\n".join(commands)
    assert "fix hold_bottom bottom_grip setforce 0.0 0.0 0.0" in text
    assert "dump traj all custom 100 si-sio2_pull.dump id type x y z" in text
    # 20 Å at 3.2 m/s (0.032 Å/ps) = 625 ps / 0.001 ps = 625000 steps.
    runs = [c for c in commands if c.startswith("run ")]
    assert runs == ["run 625000"]
