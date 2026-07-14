"""Generate the press/pull LAMMPS command stream (PSEUDOCODE.md §9).

This is slice 2 of the driver: the PURE, deterministic translation from
the study's ``{value, unit}`` knobs into the ordered LAMMPS commands that
set up and drive the press (§9.3) and the pull (§9.5). It runs no
simulator — it only produces strings — so the whole module is unit-
testable on a login node with no LAMMPS present. Two things it does NOT
do, by design, are left to later slices: deciding mid-run WHEN to stop
(the dual-contact and separation criteria, slice 3) and actually issuing
these commands to a live LAMMPS and reading forces back (slices 4-5).

Three design commitments show up directly here:

* **The force model is a PARAMETER, not a fork.** The line that tells
  LAMMPS which model supplies the forces is one :class:`ForceModel`
  value, so the classical stand-in (now) and the trained MLIP (later)
  are served by the SAME generator (DESIGN.md §5, PSEUDOCODE.md §9.8).
* **Both control modes are generated.** Load control and displacement
  control differ by a single drive command; both are produced so the
  §9.3 displacement-vs-load cross-check is available at once (DESIGN.md
  §5.2).
* **Units travel as data, land as bare numbers.** Every physical knob is
  a :class:`~sabsim.spec.records.Quantity`; it is converted to LAMMPS
  ``metal`` units HERE (§1.5), so no bare, unit-ambiguous number ever
  appears in the study spec, only in the generated command.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from sabsim.spec.records import MemberSpecification, Quantity

# ---------------------------------------------------------------------
# LAMMPS `metal` unit system. The v1 driver runs in metal units: length
# in Å, time in ps, energy in eV, velocity in Å/ps, temperature in K,
# pressure in bars. Each spec Quantity is converted to its metal unit
# before it enters a command, so the {value, unit} the study carries
# lands as a bare number in exactly the units LAMMPS expects.
# ---------------------------------------------------------------------

# unit string -> (physical dimension, multiplicative factor to metal unit)
_METAL_UNITS = {
    "angstrom": ("distance", 1.0),
    "nm": ("distance", 10.0),
    "ps": ("time", 1.0),
    "fs": ("time", 1.0e-3),
    "ns": ("time", 1.0e3),
    "K": ("temperature", 1.0),
    "angstrom/ps": ("velocity", 1.0),
    "m/s": ("velocity", 0.01),      # 1 m/s = 1e10 Å / 1e12 ps = 0.01 Å/ps
    "bar": ("pressure", 1.0),
    "MPa": ("pressure", 10.0),      # 1 MPa = 1e6 Pa = 10 bar
    "GPa": ("pressure", 1.0e4),     # 1 GPa = 1e9 Pa = 1e4 bar
    "Pa": ("pressure", 1.0e-5),
}

# 1 bar expressed in eV/Å³ (metal energy density), so a pressure times an
# area becomes a force in eV/Å: force[eV/Å] = P[bar] * this * area[Å²].
# Derivation: 1 eV/Å³ = 1.602176634e11 Pa = 1.602176634e6 bar, so
# 1 bar = 1 / 1.602176634e6 eV/Å³.
_BAR_IN_EV_PER_CUBIC_ANGSTROM = 1.0 / 1.602176634e6


def to_metal(quantity: Quantity, dimension: str) -> float:
    """Convert a spec Quantity to its LAMMPS metal-unit bare number.

    ``dimension`` is the physical kind the caller expects ("distance",
    "time", "temperature", "velocity", or "pressure"); a unit of the
    wrong kind — a time where a distance was expected — is rejected here
    rather than silently producing a nonsense command. This is where
    "units are carried" (DESIGN.md §1.5) becomes "the command is right".
    """
    entry = _METAL_UNITS.get(quantity.unit)
    if entry is None:
        raise ValueError(
            f"unit '{quantity.unit}' is not a known metal-convertible "
            f"unit {sorted(_METAL_UNITS)}")
    unit_dimension, factor = entry
    if unit_dimension != dimension:
        raise ValueError(
            f"unit '{quantity.unit}' is a {unit_dimension}, but a "
            f"{dimension} was expected here")
    return quantity.value * factor


def normal_force_from_pressure(pressure: Quantity, area: float) -> float:
    """Total normal force (eV/Å) a pressure exerts over an area (Å²).

    A rigid grip loaded to a target normal STRESS feels a total FORCE of
    stress times the cell's cross-sectional area (§9.3 load control).
    Converting the pressure to metal energy-density and multiplying by
    the area gives that force in eV/Å, the metal force unit.
    """
    return (to_metal(pressure, "pressure")
            * _BAR_IN_EV_PER_CUBIC_ANGSTROM * area)


def _num(value: float) -> str:
    """Format a number for a LAMMPS command: compact but unambiguous."""
    return f"{value:.6g}"


def _steps_for_time(duration_ps: float, timestep_ps: float) -> int:
    """How many MD steps span a duration, given the timestep (both ps)."""
    return max(1, round(duration_ps / timestep_ps))


# ---------------------------------------------------------------------
# The force model — the one parameterized line that names which model
# supplies the forces (PSEUDOCODE.md §9.8, [DELEGATE -> POTENTIAL]).
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class ForceModel:
    """How LAMMPS loads the forces between atoms — a parameter, not code.

    ``pair_style`` is the LAMMPS ``pair_style`` argument string and
    ``pair_coeff`` the one or more ``pair_coeff`` argument strings. The
    classical stand-in and the trained MLIP are two VALUES of this one
    type, so the command generator never branches on which potential is
    in use — it just emits these lines (DESIGN.md §5, §9.8).
    """

    pair_style: str
    pair_coeff: tuple[str, ...]


def classical_si_stand_in(type_map: dict) -> ForceModel:
    """The wave-0 classical stand-in: Stillinger-Weber silicon (§9.8).

    The element list in the ``pair_coeff`` follows ``type_map`` so LAMMPS
    type ids line up with the species order the structure was written
    with. This is the honest wave-0 placeholder the trained committee
    replaces behind the SAME :class:`ForceModel` seam.
    """
    elements = " ".join(
        sorted(type_map, key=lambda symbol: type_map[symbol]))
    return ForceModel(
        pair_style="sw",
        pair_coeff=(f"* * Si.sw {elements}",))


def deepmd_model(model_path: str) -> ForceModel:
    """The trained DeePMD committee potential (DESIGN.md §4, §9.8).

    The generator emits these lines exactly as it does the classical
    stand-in's; only the value differs. ``pair_coeff * *`` is DeePMD's
    convention (the type map is baked into the model file).
    """
    return ForceModel(
        pair_style=f"deepmd {model_path}",
        pair_coeff=("* *",))


# ---------------------------------------------------------------------
# How the slab thickness is carved into driver regions (§9.2). The grip
# and border thicknesses are §3 / §5.9 numeric follow-ons; the defaults
# below are documented STAND-INS so the command is well-formed, not
# converged physics values.
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class RegionGeometry:
    """The z-depths that split each slab into driver regions (§9.2).

    A slab is carved by position into a GRIP (the held/driven handle at
    its outer face), a Langevin thermostat BORDER just inside it, and the
    NVE interior that is everything else. These depths are provisional
    stand-ins pending the §3 heat-sink / §5.9 convergence work, not
    ratified numbers.
    """

    grip_thickness: float = 4.0      # Å: held/driven handle depth
    border_thickness: float = 6.0    # Å: Langevin thermostat layer depth


def _cell_cross_section_area(built) -> float:
    """The in-plane cell area (Å²) — the grip's loaded cross-section.

    The pair's box is periodic in the plane and open along z, so the
    cross-section the press loads is the area of the first two (in-plane)
    cell vectors, valid for a tilted (non-orthogonal) cell too.
    """
    cell = np.asarray(built.atoms.get_cell())
    return float(np.linalg.norm(np.cross(cell[0], cell[1])))


# ---------------------------------------------------------------------
# The command-block generators. Each returns a list of LAMMPS command
# strings; the two assemblers at the bottom stitch them in order.
# ---------------------------------------------------------------------

def preamble_commands(data_file: str, timestep: Quantity) -> list:
    """Units, box style, the structure, and the MD timestep (§9.2).

    ``metal`` units, ``atomic`` style (charge-free at this fidelity,
    matching the data file), and ``p p f`` — periodic in the plane, fixed
    (open) along z, the box the builder wrote (DESIGN.md §2.6).
    """
    return [
        "units metal",
        "atom_style atomic",
        "boundary p p f",
        f"read_data {data_file}",
        f"timestep {_num(to_metal(timestep, 'time'))}",
    ]


def force_model_commands(force_model: ForceModel) -> list:
    """Emit the parameterized force-model lines (classical OR MLIP)."""
    return [f"pair_style {force_model.pair_style}",
            *[f"pair_coeff {coeff}" for coeff in force_model.pair_coeff]]


def region_group_commands(built, geometry: RegionGeometry) -> list:
    """Carve the labeled groups by z-position (PSEUDOCODE.md §9.2).

    From the builder's per-wafer z-ranges, define the bottom and top
    grips (the held and driven handles), the two Langevin border layers
    just inside them, and the NVE interior as everything left over. The
    driver need not know the MD protocol to place these — they are pure
    geometry (DESIGN.md §2.6).
    """
    base_low, _ = built.wafer_a_z_range
    _, top_high = built.wafer_b_z_range
    grip = geometry.grip_thickness
    border = geometry.border_thickness

    bottom_grip_top = base_low + grip
    top_grip_bottom = top_high - grip
    return [
        f"region bottom_grip block INF INF INF INF "
        f"{_num(base_low)} {_num(bottom_grip_top)} units box",
        "group bottom_grip region bottom_grip",
        f"region top_grip block INF INF INF INF "
        f"{_num(top_grip_bottom)} {_num(top_high)} units box",
        "group top_grip region top_grip",
        f"region lower_border block INF INF INF INF "
        f"{_num(bottom_grip_top)} {_num(bottom_grip_top + border)} "
        f"units box",
        "group lower_border region lower_border",
        f"region upper_border block INF INF INF INF "
        f"{_num(top_grip_bottom - border)} {_num(top_grip_bottom)} "
        f"units box",
        "group upper_border region upper_border",
        "group grips union bottom_grip top_grip",
        "group border union lower_border upper_border",
        "group interior subtract all grips border",
    ]


def integrator_commands(member: MemberSpecification, seed: int) -> list:
    """Integrate the interior and thermostat the border, bias-removed.

    The interior runs plain NVE; the border runs a Langevin thermostat
    whose center-of-mass drift is removed FIRST (``temp/com`` +
    ``fix_modify``), so directed motion is never counted as heat — the
    §5.2 fix for prior art's nvt-on-the-drifting-slab error. The grips
    are driven or held by their own fixes, so they are not integrated
    here.
    """
    temperature = to_metal(member.protocol.press_temperature, "temperature")
    damping = to_metal(member.numerical.langevin_damping, "time")
    return [
        "fix nve_interior interior nve",
        "compute border_temp border temp/com",
        f"fix langevin_border border langevin {_num(temperature)} "
        f"{_num(temperature)} {_num(damping)} {seed}",
        "fix_modify langevin_border temp border_temp",
    ]


def press_drive_commands(built, member: MemberSpecification) -> list:
    """The press drive — load OR displacement, one command apart (§9.3).

    Load control applies a target normal FORCE (pressure times the cell
    cross-section) to the top grip, ramped from zero to avoid a shock;
    ``aveforce`` spreads it over the grip's atoms. Displacement control
    rigidly MOVES the top grip downward at the approach rate. Either way
    the grip is a rigid handle, so no thermostat sees the drive (§5.2).
    The exact load path/ramp is a §5.9 follow-on; the ramp variable makes
    the current choice explicit rather than hidden.
    """
    protocol = member.protocol
    if protocol.press_control == "load":
        area = _cell_cross_section_area(built)
        force = normal_force_from_pressure(protocol.press_load, area)
        return [
            f"variable press_fz equal ramp(0.0,{_num(-force)})",
            "fix drive_top top_grip aveforce 0.0 0.0 v_press_fz",
        ]
    # displacement control: drive the grip down at the approach rate
    rate = to_metal(protocol.press_approach_rate, "velocity")
    return [
        f"fix drive_top top_grip move linear 0.0 0.0 {_num(-rate)} "
        f"units box",
    ]


def pull_drive_commands(rate: Quantity) -> list:
    """Hold the bottom grip and pull the top grip apart at ``rate`` (§9.5).

    The bottom grip is held with ``setforce`` (which exposes the summed
    pre-zero force as ``f_hold_bottom[3]``) and the top grip is moved
    upward at the ladder rate. Recording BOTH reactions makes Newton's
    third law a free check (§5.4): the held grip's stored force and the
    driven grip's summed force should be equal and opposite.
    """
    speed = to_metal(rate, "velocity")
    return [
        "fix hold_bottom bottom_grip setforce 0.0 0.0 0.0",
        f"fix drive_top top_grip move linear 0.0 0.0 {_num(speed)} "
        f"units box",
        "compute top_reaction top_grip reduce sum fz",
    ]


def recording_commands(
        member: MemberSpecification, dump_file: str) -> list:
    """Dump strided frames and log the forces the analyzer reads (§9.5).

    A strided coordinate dump (one frame per ``frame_stride`` steps, §2)
    feeds the §8 snapshot selector; the custom thermo line logs the two
    grip reactions and the energy the reference gate watches. The force
    is NOT time-averaged here — averaging over a displacement window is a
    slice-3 analysis on these dumped values, not a driver command.
    """
    stride = member.numerical.frame_stride
    return [
        f"dump traj all custom {stride} {dump_file} id type x y z",
        f"thermo {stride}",
        "thermo_style custom step temp pe f_hold_bottom[3] c_top_reaction",
    ]


# ---------------------------------------------------------------------
# The two assemblers. Each stitches the blocks above into the ordered
# command stream for one phase, including the deterministic `run`s. The
# EARLY stops (contact reached, complete separation) are slice-3 control
# logic layered on top; here the runs are the full deterministic spans.
# ---------------------------------------------------------------------

def press_script(
        built,
        member: MemberSpecification,
        force_model: ForceModel,
        data_file: str,
        seed: int,
        geometry: RegionGeometry = RegionGeometry()) -> list:
    """The full ordered press command stream (PSEUDOCODE.md §9.3).

    Sets the box up, loads the force model, carves the groups, starts the
    thermostatted integrators, applies the mode-appropriate drive, brings
    the surfaces together, and holds at temperature where bonding happens.
    The approach ``run`` is the deterministic span (initial gap closed at
    the approach rate); slice 3 may stop it EARLY when the dual-contact
    criterion fires. The hold ``run`` is the full ``press_duration``.
    """
    protocol = member.protocol
    numerical = member.numerical
    timestep_ps = to_metal(numerical.md_timestep, "time")

    commands = []
    commands += preamble_commands(data_file, numerical.md_timestep)
    commands += force_model_commands(force_model)
    commands += region_group_commands(built, geometry)
    commands += integrator_commands(member, seed)
    commands += press_drive_commands(built, member)

    # Approach span: the time to close the initial gap at the approach
    # rate (a deterministic upper bound; slice 3 stops early on contact).
    gap = to_metal(protocol.initial_gap, "distance")
    approach_rate = to_metal(protocol.press_approach_rate, "velocity")
    approach_steps = _steps_for_time(gap / approach_rate, timestep_ps)
    commands.append(f"run {approach_steps}")

    # The hold at temperature, where bonding actually happens (§9.3).
    hold_ps = to_metal(protocol.press_duration, "time")
    commands.append(f"run {_steps_for_time(hold_ps, timestep_ps)}")
    return commands


def pull_script(
        built,
        member: MemberSpecification,
        force_model: ForceModel,
        data_file: str,
        rate: Quantity,
        pull_distance: Quantity,
        seed: int,
        geometry: RegionGeometry = RegionGeometry()) -> list:
    """The full ordered pull command stream for one rate (PSEUDOCODE §9.5).

    Reads the settled reference state, loads the force model, carves the
    groups, starts the thermostatted integrators, holds the bottom grip
    and drives the top grip apart at ``rate``, and records the strided
    frames and grip reactions. The ``run`` spans ``pull_distance`` at the
    rate; slice 3 stops it EARLY at complete separation (opening past the
    cutoff with the force returned to the noise floor, §9.6).
    """
    numerical = member.numerical
    timestep_ps = to_metal(numerical.md_timestep, "time")
    dump_file = f"{member.name}_pull.dump"

    commands = []
    commands += preamble_commands(data_file, numerical.md_timestep)
    commands += force_model_commands(force_model)
    commands += region_group_commands(built, geometry)
    commands += integrator_commands(member, seed)
    commands += pull_drive_commands(rate)
    commands += recording_commands(member, dump_file)

    distance = to_metal(pull_distance, "distance")
    speed = to_metal(rate, "velocity")
    commands.append(
        f"run {_steps_for_time(distance / speed, timestep_ps)}")
    return commands
