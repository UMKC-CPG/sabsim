"""Generate the press/pull LAMMPS command stream (PSEUDOCODE.md §9).

This is slice 2 of the driver: the PURE, deterministic translation from
the project's ``{value, unit}`` knobs into the ordered LAMMPS commands that
set up and drive the press (§9.3) and the pull (§9.5). It runs no
simulator — it only produces strings — so the whole module is unit-
testable on a login node with no LAMMPS present. Two things it does NOT
do, by design, are left to later slices: deciding mid-run WHEN to stop
(the dual-contact and separation criteria, slice 3) and actually issuing
these commands to a live LAMMPS and reading forces back (slices 4-5).

Three design commitments show up directly here:

* **The force model is a PARAMETER, not a fork.** The line that tells
  LAMMPS which model supplies the forces is one :class:`ForceModel`
  value, so the foundation MLIP (now) and the trained committee (later)
  are served by the SAME generator (DESIGN.md §5, PSEUDOCODE.md §9.8).
* **Both control modes are generated.** Load control and displacement
  control differ by a single drive command; both are produced so the
  §9.3 displacement-vs-load cross-check is available at once (DESIGN.md
  §5.2).
* **Units travel as data, land as bare numbers.** Every physical knob is
  a :class:`~sabsim.spec.records.Quantity`; it is converted to LAMMPS
  ``metal`` units HERE (§1.5), so no bare, unit-ambiguous number ever
  appears in the project file, only in the generated command.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np

from sabsim.spec.records import PairSpecification, Quantity

# ---------------------------------------------------------------------
# LAMMPS `metal` unit system. The v1 driver runs in metal units: length
# in Å, time in ps, energy in eV, velocity in Å/ps, temperature in K,
# pressure in bars. Each spec Quantity is converted to its metal unit
# before it enters a command, so the {value, unit} the project file carries
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
    "eV/angstrom": ("force", 1.0),  # already the metal force unit
    "eV": ("energy", 1.0),
    "eV/atom": ("energy_per_atom", 1.0),
    "angstrom^2": ("area", 1.0),
    "nm^2": ("area", 100.0),        # 1 nm^2 = 100 Å²
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


def _lammps_number(value: float) -> str:
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
    foundation-MLIP stand-in and the trained committee are two VALUES
    of this one type, so the command generator never branches on which
    potential is in use — it just emits these lines (DESIGN.md §5, §9.8).

    ``preload`` is any command that must run BEFORE ``pair_style`` — for a
    DeePMD model, the ``plugin load`` that registers the ``deepmd`` pair
    style (ARCHITECTURE.md §4.4); it is empty for a pair style built into
    LAMMPS itself. Keeping it on the value, not in the generator,
    preserves the "force model is a parameter, not a fork" commitment:
    the generator still emits lines without branching.

    ``needs_atom_map`` records whether the model requires LAMMPS to keep a
    global atom map (``atom_modify map yes``). A message-passing MLIP (the
    DPA graph-network cascade potential) gathers per-atom features across
    the neighbor graph and cannot run without it, whereas a built-in
    pair form never needs it. Because ``atom_modify`` must be issued BEFORE
    the structure is read, this flag is consulted by the preamble
    generator (not :func:`force_model_commands`), which is why it rides on
    the value here — still a parameter, not a branch in the generator.
    """

    pair_style: str
    pair_coeff: tuple[str, ...]
    preload: tuple[str, ...] = ()
    needs_atom_map: bool = False


def deepmd_model(model_path: str, type_map: dict) -> ForceModel:
    """A DeePMD model — the production potential (DESIGN.md §4, §9.8).

    ``type_map`` maps every element symbol in the cell to its LAMMPS type
    id, and the elements are written on the ``pair_coeff`` line IN TYPE
    ORDER. This is not optional: a deepmd model carries its own element
    list, and without the names LAMMPS type 1 is taken to be the model's
    FIRST element — harmless for a one-element silicon ``graph.pb``, but
    for a 118-element universal model that first element is hydrogen, and
    a silicon cell is then simulated as hydrogen (T-25, job 16822060: the
    box collapsed to a third of its volume). The ``preload``
    registers the ``deepmd`` pair style before it is named: DeePMD ships as
    a runtime LAMMPS PLUGIN, so the engine must ``plugin load`` it first
    (proven job 15686597). The plugin's path is read from the environment
    (``DEEPMD_LMP_PLUGIN``, exported by the deepmd engine module,
    ARCHITECTURE.md §4.4) rather than hard-coded, so one engine rebuild
    retargets it in one place; ``getenv`` resolves it inside LAMMPS.
    """
    elements = " ".join(
        sorted(type_map, key=lambda symbol: type_map[symbol]))
    return ForceModel(
        pair_style=f"deepmd {model_path}",
        pair_coeff=(f"* * {elements}",),
        preload=(
            "variable dp getenv DEEPMD_LMP_PLUGIN",
            "plugin load ${dp}"),
        # A DPA-style graph network gathers per-atom features across the
        # neighbor graph and needs the global atom map to exist before the
        # atoms are created; ``atom_modify map yes`` is harmless for the
        # older descriptor-based graph.pb, so it is set for every deepmd
        # model rather than guessed from the file name.
        needs_atom_map=True)


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

def restart_preamble_commands(force_model: ForceModel | None = None) -> list:
    """The units and box declarations that precede a read (§9.2, §13.3).

    ``metal`` units, ``atomic`` style (charge-free at this fidelity,
    matching the data file), and ``p p f`` — periodic in the plane, fixed
    (open) along z, the box the builder wrote (DESIGN.md §2.6). These three
    lines lead BOTH a fresh ``read_data`` and a resumed ``read_restart``,
    so they live in one place; the structure and masses (and, on a
    restart, the saved timestep) come after the read.

    When ``force_model`` is a message-passing MLIP (``needs_atom_map``),
    ``atom_modify map yes`` is inserted right after ``atom_style`` — it
    MUST precede the read that creates the atoms, which is why it lives in
    the preamble rather than beside the ``pair_style`` lines. A model
    without the flag (or no force model) leaves those lines untouched.

    ``thermo_modify lost warn`` closes the block: the ``p p f`` boundary
    silently deletes any atom that leaves the open-z box (a free surface
    evaporates or sputters under a long run), and LAMMPS ABORTS on a lost
    atom by default. Aborting is the wrong response here — a lost atom is
    meant to INVALIDATE the run through the driver's §5.6 atom-count
    conservation gate (a VOID measurement, §7.6), not to crash it before
    that gate can read the count. Dropping the atom with a warning lets
    the gate be the arbiter, as the cascade already does for its
    sputtering (§10.3). It leads both a fresh ``read_data`` and a resumed
    ``read_restart``, so every press/pull run inherits it.
    """
    lines = [
        "units metal",
        "atom_style atomic",
        "boundary p p f",
    ]
    if force_model is not None and force_model.needs_atom_map:
        # After atom_style, before the read: the global atom map the GNN
        # neighbor gather needs must exist when the atoms are created.
        lines.insert(2, "atom_modify map yes")
    lines.append("thermo_modify lost warn")
    return lines


def timestep_command(timestep: Quantity) -> list:
    """Set the MD timestep (§9.2), as a one-line command list.

    A separate builder because a resumed pull sets the timestep AFTER its
    ``read_restart`` — the restart carries a saved timestep, and this
    re-asserts the pair's value over it (§13.3) — whereas a fresh run
    folds it into :func:`preamble_commands`.
    """
    return [f"timestep {_lammps_number(to_metal(timestep, 'time'))}"]


def preamble_commands(
        data_file: str,
        timestep: Quantity,
        force_model: ForceModel | None = None) -> list:
    """Units, box style, the structure, and the MD timestep (§9.2).

    Opens with :func:`restart_preamble_commands` (the units and z-open
    boundary, plus ``atom_modify map yes`` when ``force_model`` is a
    message-passing MLIP), reads the structure the builder wrote, then sets
    the MD timestep (:func:`timestep_command`).
    """
    return (
        restart_preamble_commands(force_model)
        + [f"read_data {data_file}"]
        + timestep_command(timestep))


def force_model_commands(force_model: ForceModel) -> list:
    """Emit the parameterized force-model lines for ANY force model.

    Any ``preload`` (a DeePMD ``plugin load``) comes FIRST — the pair style
    it registers cannot be named before it is loaded — then the
    ``pair_style`` and its ``pair_coeff`` lines. A built-in pair style has
    an empty preload, so its two lines are unchanged.
    """
    return [*force_model.preload,
            f"pair_style {force_model.pair_style}",
            *[f"pair_coeff {coeff}" for coeff in force_model.pair_coeff]]


def region_group_commands(z_ranges, geometry: RegionGeometry) -> list:
    """Carve the labeled groups by z-position (PSEUDOCODE.md §9.2).

    From per-wafer z-ranges, define the bottom and top grips (the held
    and driven handles), the two Langevin border layers just inside
    them, and the NVE interior as everything left over. The driver need
    not know the MD protocol to place these — they are pure geometry
    (DESIGN.md §2.6). ``z_ranges`` is anything carrying
    ``wafer_a_z_range`` and ``wafer_b_z_range``: the builder's assembled
    structure at press time, when nothing has moved, or a
    :class:`~sabsim.driver.press_pull.WaferZRanges` read off the live
    atoms for any stage that opens later (DESIGN §5.4, 2026-09-23).
    """
    base_low, _ = z_ranges.wafer_a_z_range
    _, top_high = z_ranges.wafer_b_z_range
    grip = geometry.grip_thickness
    border = geometry.border_thickness

    bottom_grip_top = base_low + grip
    top_grip_bottom = top_high - grip
    return [
        f"region bottom_grip block INF INF INF INF "
        f"{_lammps_number(base_low)} "
        f"{_lammps_number(bottom_grip_top)} units box",
        "group bottom_grip region bottom_grip",
        f"region top_grip block INF INF INF INF "
        f"{_lammps_number(top_grip_bottom)} "
        f"{_lammps_number(top_high)} units box",
        "group top_grip region top_grip",
        f"region lower_border block INF INF INF INF "
        f"{_lammps_number(bottom_grip_top)} "
        f"{_lammps_number(bottom_grip_top + border)} "
        f"units box",
        "group lower_border region lower_border",
        f"region upper_border block INF INF INF INF "
        f"{_lammps_number(top_grip_bottom - border)} "
        f"{_lammps_number(top_grip_bottom)} "
        f"units box",
        "group upper_border region upper_border",
        "group grips union bottom_grip top_grip",
        "group border union lower_border upper_border",
        "group interior subtract all grips border",
    ]


def integrator_commands(pair: PairSpecification, seed: int) -> list:
    """Integrate interior AND border; thermostat the border, bias-removed.

    Both the interior and the border are advanced in time by their own
    ``fix nve``. The border ALSO carries a Langevin thermostat whose
    center-of-mass drift is removed FIRST (``temp/com`` + ``fix_modify``),
    so directed motion is never counted as heat — the §5.2 fix for prior
    art's nvt-on-the-drifting-slab error.

    The border needs its OWN ``fix nve`` and cannot rely on the Langevin
    fix to move it: in LAMMPS ``fix langevin`` adds thermostatting forces
    but does NOT integrate the equations of motion. A border given only
    the Langevin fix is thermostatted yet never advances — a reflecting
    wall, not the heat sink DESIGN.md §5.2 requires, so the dissipated
    energy the pull measures has nowhere to go but back into the
    interface it was measured from. Integrating the border is what turns
    it into a real sink (verified on a compute node, stage 5: with the
    interior-only integrator the border's max displacement over 500 steps
    was exactly 0 A).

    The grips are driven or held by their own fixes and are deliberately
    NOT integrated here — whether they SHOULD be is a separate open
    question (PSEUDOCODE.md §9.2 / §9.4), untouched by this border fix.
    """
    temperature = to_metal(pair.protocol.press_temperature, "temperature")
    damping = to_metal(pair.numerical.langevin_damping, "time")
    return [
        "fix nve_interior interior nve",
        "fix nve_border border nve",
        "compute border_temp border temp/com",
        f"fix langevin_border border langevin {_lammps_number(temperature)} "
        f"{_lammps_number(temperature)} {_lammps_number(damping)} {seed}",
        "fix_modify langevin_border temp border_temp",
    ]


def combined_cell_relax_commands() -> list:
    """Relax the assembled pair's IN-PLANE cell to zero stress, ONCE.

    A one-time ``fix box/relax x 0 y 0`` + ``minimize`` run as the bond
    flow's FIRST act, on the assembled pair (DESIGN.md §5.6, §2.6; it
    needs the joint cell, which is why it cannot ride the activation
    stage): the shared lateral cell resizes to its
    zero-in-plane-stress size while z is left to the free surface and the
    grips, then the fix is REMOVED so the cell is frozen for the press,
    settle, and pull. This is the recorded, one-time relaxation §5.6
    sanctions -- NOT a live lateral barostat during the measurement, which
    §5.6 forbids because the cell would drift and the per-area denominator
    would move mid-run. It relieves the dominant frame-0 stress -- the
    cell sitting off the potential's preferred lattice, ~7-8 GPa per
    material (T-17 job 16453628 drove it to ~0 with a sub-0.3% box change,
    the relaxed cell staying ordered) -- so the strained pair does not
    detonate at contact.

    ``vmax`` caps the fractional box change per minimize iteration so the
    relax is smooth rather than lurching; the minimize tolerances are a
    §5.9 stand-in until the convergence study pins them.
    """
    return [
        "fix combined_cell_relax all box/relax x 0.0 y 0.0 vmax 0.001",
        "min_style cg",
        "minimize 1.0e-6 1.0e-4 1000 10000",
        "unfix combined_cell_relax",
    ]


# The load RISE TIME: how long the press load takes to climb from zero to
# the target before it HOLDS there. A documented §5.9 STAND-IN, not a
# converged value — the real load-schedule knob is a follow-on
# (dev/TODO.md). It must be SHORT relative to the whole press yet long
# enough that the onset is a gentle squeeze and not a shock; 10 ps is a
# placeholder in that spirit. Driving the ramp off this rise time and the
# ABSOLUTE step is what stops the load sawtoothing across the run chunks.
_LOAD_RISE_TIME_STANDIN = Quantity(10.0, "ps")


def press_drive_commands(built, pair: PairSpecification) -> list:
    """The press drive — load OR displacement, one command apart (§9.3).

    Load control applies a target normal FORCE (pressure times the cell
    cross-section) to the top grip, climbing from zero to the target over
    a rise time and then HOLDING — driven off the absolute step so it does
    not sawtooth across the run's chunks. Displacement control rigidly
    MOVES the top grip downward at the approach rate. Under load the driven
    grip is INTEGRATED so the applied pressure can move it (option 1,
    PSEUDOCODE.md §9.3); under displacement it is driven kinematically. The
    load rise time is a §5.9 follow-on (:data:`_LOAD_RISE_TIME_STANDIN`).
    """
    protocol = pair.protocol
    if protocol.press_control == "load":
        area = _cell_cross_section_area(built)
        force = normal_force_from_pressure(protocol.press_load, area)
        rise_steps = max(1, round(
            to_metal(_LOAD_RISE_TIME_STANDIN, "time")
            / to_metal(pair.numerical.md_timestep, "time")))
        # THREE things this drive gets right, each learned on a compute
        # node. (1) RAMP SHAPE. The load climbs from zero to the target
        # over the rise time and then HOLDS, driven off the ABSOLUTE step
        # via a boolean blend: ``step<rise`` selects the rising fraction
        # ``step/rise`` and ``step>=rise`` holds it at 1 (LAMMPS boolean
        # operators return 1/0, and it has no scalar ``min()``). LAMMPS
        # ``ramp()`` was wrong here: it interpolates over the CURRENT
        # ``run`` command, and the press runs as many short ``run`` chunks,
        # so the load SAWTOOTHED — climbing then resetting to zero every
        # chunk, never holding (confirmed by a force probe). The absolute
        # step keeps counting across chunks, so the ramp happens once.
        # (2) MAGNITUDE. ``fix aveforce`` sets the AVERAGE per-atom force,
        # not the total, so we divide the target total P*A by the grip's
        # atom count with ``count(top_grip)`` (at runtime, so this
        # generator needs no atom count). Omitting it over-loaded by
        # N_grip: a nominal 500 MPa read back ~7.3 GPa, a ~15x overshoot.
        # (3) INTEGRATOR. ``aveforce`` (like ``fix langevin``) sets a force
        # but does not advance, so the grip needs its own ``nve`` or it
        # never moves and the surfaces never approach. The settle later
        # releases both the integrator and the drive so the reference
        # settles under no load (:func:`press_release_commands`).
        return [
            f"variable press_fz equal {_lammps_number(-force)}*"
            f"((step/{rise_steps})*(step<{rise_steps})"
            f"+(step>={rise_steps}))/count(top_grip)",
            "fix drive_top_nve top_grip nve",
            "fix drive_top top_grip aveforce 0.0 0.0 v_press_fz",
        ]
    # Displacement control drives the grip KINEMATICALLY: ``fix move``
    # overrides integration and advances the grip itself, so it needs no
    # companion integrator (contrast the load branch above).
    rate = to_metal(protocol.press_approach_rate, "velocity")
    return [
        f"fix drive_top top_grip move linear 0.0 0.0 {_lammps_number(-rate)} "
        f"units box",
    ]


def grip_hold_and_readback_commands() -> list:
    """Hold the bottom grip and install BOTH grip force gauges (§5.4, §9.4).

    These two lines are shared by the press, the settle, and the pull,
    because all three need to read the grip reactions — that shared need
    is why they live here rather than inside any one phase's drive. The
    bottom grip is held with ``setforce``, which zeroes its net force AND
    exposes the summed pre-zero force as ``f_hold_bottom[3]``; the top
    grip's reaction is the ``compute reduce sum fz`` scalar. Recording
    both makes Newton's third law a free check (§5.4): the held grip's
    stored force and the driven grip's summed force should be equal and
    opposite at a balanced state.

    Issue these ONCE per LAMMPS instance (a compute cannot be redefined),
    after the groups are carved. The press and settle share one instance,
    so the press setup issues them and the settle reuses them; the pull
    runs on a FRESH instance and issues them again.
    """
    return [
        "fix hold_bottom bottom_grip setforce 0.0 0.0 0.0",
        "compute top_reaction top_grip reduce sum fz",
    ]


def heal_surface_commands(
        pair: PairSpecification, seed: int, marker_file: str) -> list:
    """Heal ONE activated half at the end of its cascade session (§3.4).

    The cascade leaves the surface hot and littered with loosely bound
    atoms and small fragments standing proud of it; those are what mix
    across the interface at the first touch of a press (the 50 eV demo
    press, 2026-08-26). So, after the projectile strip, the half is
    RE-EQUILIBRATED under the same universal model that bombarded it —
    per half, in vacuum, on the same engine (revised 2026-08-28, Paul):
    the project's ``[protocol.reanneal]`` schedule holds every mobile atom
    at ``hold_temperature`` for ``hold_duration``, cools it to the press
    temperature over the same span, and THEN a short minimisation drops
    the slab into a nearby 0 K minimum (PSEUDOCODE §9.7,
    ``anneal_then_minimize``). The frozen base keeps its ``setforce``
    hold from the cascade setup, so it neither moves nor heats.

    The cascade's own integrators are already torn down by the cleanup,
    so this installs its own thermostat on the mobile atoms only. It
    runs at the ordinary MD step the between-impact cool-down restored.

    ``marker_file`` receives the MD step at which the heal begins — a
    one-line file written beside the recording — so a reader of the
    activate movie can tell the cascade-hot frames from the healed ones
    (the bootstrap harvest, PSEUDOCODE §11.3).
    """
    schedule = pair.protocol.reanneal_schedule
    hold_kelvin = to_metal(schedule.hold_temperature, "temperature")
    press_kelvin = to_metal(pair.protocol.press_temperature, "temperature")
    timestep = to_metal(pair.numerical.md_timestep, "time")
    hold_steps = max(1, round(
        to_metal(schedule.hold_duration, "time") / timestep))
    damping = to_metal(pair.numerical.langevin_damping, "time")
    return [
        # Everything the cascade could move, minus the anchored base.
        "group heal_mobile subtract all frozen_base",
        # The ledger marker: the step this heal begins at (§11.3).
        f'print "$(step)" file {marker_file} screen no',
        f"velocity heal_mobile create {_lammps_number(hold_kelvin)} {seed} "
        f"dist gaussian",
        f"fix heal_hold heal_mobile nvt temp {_lammps_number(hold_kelvin)} "
        f"{_lammps_number(hold_kelvin)} {_lammps_number(damping)}",
        f"run {hold_steps}",
        "unfix heal_hold",
        f"fix heal_quench heal_mobile nvt temp {_lammps_number(hold_kelvin)} "
        f"{_lammps_number(press_kelvin)} {_lammps_number(damping)}",
        f"run {hold_steps}",
        "unfix heal_quench",
        "min_style cg",
        "minimize 1e-6 1e-6 200 2000",
    ]



def pull_drive_commands(rate: Quantity) -> list:
    """Drive the top grip apart at ``rate`` (§9.5).

    The bottom grip is held and both reactions are gauged by the shared
    :func:`grip_hold_and_readback_commands`; this adds only the pull's own
    action — moving the top grip upward at the ladder rate. ``fix move``
    drives it kinematically, so (as in the displacement press) it needs no
    companion integrator.
    """
    speed = to_metal(rate, "velocity")
    return [
        f"fix drive_top top_grip move linear 0.0 0.0 {_lammps_number(speed)} "
        f"units box",
    ]


def pull_headroom_commands(
        rate: Quantity, travel_time: float, margin: float = 10.0) -> list:
    """Grow the box upward so the pull cannot drag atoms out of it (§9.5).

    The assembled pair is boxed for CONTACT — it carries only the vacuum
    the two halves were built with. The pull then drives the top grip
    steadily upward, and with a fixed (non-periodic) z boundary any atom
    carried past the top of the box is simply DELETED, which LAMMPS
    reports as "Lost atoms" and treats as a fatal error.

    That is not hypothetical: the first full end-to-end run died exactly
    here. The pair left 12.75 Å of headroom, the 3.2 m/s rung travels
    16 Å within its step budget, and the run lost 100 atoms the moment
    the grip had moved 12.75 Å. The slowest rung had survived only
    because its budget (5 Å) happened to fit.

    So before pulling, the box is extended by the FULL travel this rung
    can demand — its speed times the whole chunk budget — plus a margin
    for the thermal excursion of the freed surface. The box is grown
    rather than the pair re-boxed, so nothing moves and the geometry the
    regions were carved from is untouched; the extra space is vacuum
    above a free surface, which costs only some empty domain.

    ``travel_time`` is the pull's total available time (ps).
    """
    speed = to_metal(rate, "velocity")           # Å/ps
    headroom = speed * travel_time + margin
    return [
        f"change_box all z final $(zlo) $(zhi+{_lammps_number(headroom)}) "
        f"units box",
    ]


def press_release_commands(pair: PairSpecification) -> list:
    """Release the press drive so the reference settles under NO load (§9.4).

    The settle's zero-load reference (§5.3) must be at rest under no
    applied load, so before it minimizes and equilibrates it must undo
    whatever the press was driving with. The drive fix ``drive_top`` is
    removed in every mode; under LOAD control the grip's own integrator
    ``drive_top_nve`` is removed too, which re-freezes the grip into a
    rigid handle at the depth it reached. The grip force gauges from
    :func:`grip_hold_and_readback_commands` are deliberately LEFT in
    place — the settle reads them to check the reference is balanced.
    """
    releases = ["unfix drive_top"]
    if pair.protocol.press_control == "load":
        releases.append("unfix drive_top_nve")
    return releases


def recording_commands(
        pair: PairSpecification,
        dump_file: str | None = None,
        stride: int | None = None) -> list:
    """Log the forces the analyzer reads, and optionally record frames.

    Two different things used to be welded together here, and separating
    them matters. The custom thermo line logs the two grip reactions and
    the energy the reference gate watches — that is the MEASUREMENT, and
    the analyzer cannot work without it, so it is always emitted. The
    coordinate dump is for HUMAN inspection only; nothing in the pipeline
    reads it back. Bundling the two meant every run paid 1.3 GB per pull
    rung for frames that might never be opened.

    So ``dump_file`` is now optional: pass a path to record a strided
    trajectory, or leave it ``None`` to measure without recording. The
    force is NOT time-averaged here — averaging over a displacement
    window is a slice-3 analysis on these logged values, not a driver
    command.
    """
    # The thermo cadence follows the SPEC, because the analyzer reads
    # those lines and its sampling is part of the measurement. Only the
    # DUMP honours an override, since frames are for looking at.
    thermo_stride = pair.numerical.frame_stride
    stride = stride or thermo_stride
    commands = [
        f"thermo {thermo_stride}",
        "thermo_style custom step temp pe f_hold_bottom[3] c_top_reaction",
    ]
    if dump_file is not None:
        commands = trajectory_dump_commands(dump_file, stride) + commands
    return commands


def trajectory_dump_commands(dump_file: str, stride: int) -> list:
    """Record one frame per ``stride`` steps, for visual inspection.

    Used by every DYNAMIC stage — cascade, re-anneal, press, settle and
    each pull rung — so a run requested with trajectories on can be
    watched from end to end rather than only where somebody happened to
    wire a dump in. Atoms are sorted by identity so a viewer sees a
    stable ordering across frames even as the cascade creates and deletes
    projectile atoms.
    """
    return [
        f"dump traj all custom {stride} {dump_file} id type x y z",
        "dump_modify traj sort id",
    ]


def stage_dump_file(output_directory: str, pair_label: str,
                    stage: str) -> str:
    """Where one dynamic stage's trajectory lands.

    Named for the pair and the stage that produced it, so a directory
    of trajectories reads as an account of the run — ``<pair>_
    activation_a.dump``, ``<pair>_press.dump`` — rather than a pile of
    files distinguishable only by timestamp. Run output belongs under the
    run's OWN directory, never the working directory (ARCHITECTURE §4.1).
    """
    return os.path.join(output_directory, f"{pair_label}_{stage}.dump")


def _rate_slug(rate: Quantity) -> str:
    """A filesystem-safe tag for one pull rate, e.g. 3.2 m/s -> 3p2mps."""
    # "/" is not filesystem-friendly and dropping it turns m/s into
    # "ms", which reads as milliseconds; "p" for "per" keeps it legible.
    return f"{rate.value:g}".replace(".", "p") + rate.unit.replace("/", "p")


def pull_dump_file(
        output_directory: str,
        pair: PairSpecification,
        rate: Quantity | None = None) -> str:
    """Where a pull's trajectory dump is written (ARCHITECTURE.md §4.1).

    Run output belongs under the run's OWN directory — the scratch job
    directory the deployment layer owns — never the current working
    directory, or LAMMPS drops the dump wherever the process happened to
    launch from (which is how one once landed in the repo root). The
    orchestrator passes that directory in; this library owns only the file
    NAME, because the §8 snapshot selector reads the dump back by that
    name, so it is part of the contract rather than a caller's choice.
    """
    if rate is None:
        return os.path.join(output_directory, f"{pair.pair_label}_pull.dump")
    return os.path.join(
        output_directory, f"{pair.pair_label}_pull_{_rate_slug(rate)}.dump")


# ---------------------------------------------------------------------
# The two assemblers. Each stitches the blocks above into the ordered
# command stream for one phase, including the deterministic `run`s. The
# EARLY stops (contact reached, complete separation) are slice-3 control
# logic layered on top; here the runs are the full deterministic spans.
# ---------------------------------------------------------------------

def press_script(
        built,
        pair: PairSpecification,
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
    protocol = pair.protocol
    numerical = pair.numerical
    timestep_ps = to_metal(numerical.md_timestep, "time")

    commands = []
    commands += preamble_commands(data_file, numerical.md_timestep)
    commands += force_model_commands(force_model)
    commands += region_group_commands(built, geometry)
    commands += integrator_commands(pair, seed)
    commands += press_drive_commands(built, pair)
    commands += grip_hold_and_readback_commands()

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
        pair: PairSpecification,
        force_model: ForceModel,
        data_file: str,
        rate: Quantity,
        pull_distance: Quantity,
        seed: int,
        geometry: RegionGeometry = RegionGeometry(),
        *,
        output_directory: str) -> list:
    """The full ordered pull command stream for one rate (PSEUDOCODE §9.5).

    Reads the settled reference state, loads the force model, carves the
    groups, starts the thermostatted integrators, holds the bottom grip
    and drives the top grip apart at ``rate``, and records the strided
    frames and grip reactions into ``output_directory`` (a required
    keyword — the run states where its output lands, it is never inferred
    from the working directory). The ``run`` spans ``pull_distance`` at
    the rate; slice 3 stops it EARLY at complete separation (opening past
    the cutoff with the force returned to the noise floor, §9.6).
    """
    numerical = pair.numerical
    timestep_ps = to_metal(numerical.md_timestep, "time")
    dump_file = pull_dump_file(output_directory, pair)

    commands = []
    commands += preamble_commands(data_file, numerical.md_timestep)
    commands += force_model_commands(force_model)
    commands += region_group_commands(built, geometry)
    commands += integrator_commands(pair, seed)
    commands += grip_hold_and_readback_commands()
    commands += pull_drive_commands(rate)
    commands += recording_commands(pair, dump_file)

    distance = to_metal(pull_distance, "distance")
    speed = to_metal(rate, "velocity")
    commands.append(
        f"run {_steps_for_time(distance / speed, timestep_ps)}")
    return commands


# ---------------------------------------------------------------------
# The surface-activation cascade command block (PSEUDOCODE.md §10). These
# generators produce the pure command strings for the step-4 amorphization
# cascade — the universal MLIP + ZBL potential (resolved by cascade_potential.
# resolve_cascade_generator, DESIGN.md §4.7) driving an energetic-particle
# bombardment. Like the press/pull block above, nothing here runs a
# simulator; the per-impact SEQUENCING (insert -> cascade -> relax, with
# the read-backs that size each run) is the cascade driver's job, one
# slice up. This block is only the reusable pieces it stitches.
#
# The cascade runs on a STANDALONE slab in vacuum (activation is per-wafer,
# BEFORE the two ever face each other, DESIGN.md §3.1), so its regions are
# the slab's OWN geometry — a frozen base, a Langevin border just above it,
# and the NVE interior up to the free top surface being amorphized —
# DISTINCT from the pair-level grips the press/pull carve.
# ---------------------------------------------------------------------

# Cascade region thicknesses and projectile-spawn geometry (Å). DOCUMENTED
# STAND-INS pending the §3.3 heat-sink / §4.7 convergence work, not
# ratified numbers — the same status as RegionGeometry's press depths.
@dataclass(frozen=True)
class CascadeGeometry:
    """The z-depths that split a standalone activation slab (§10.2).

    The slab is carved by position into a FROZEN BASE (an immobile anchor
    at the bottom that absorbs recoil so the slab does not drift), a
    Langevin thermostat BORDER just above it (the heat sink that drains
    the cascade at a physical rate — the piece prior art's frozen-base-only
    design lacks, so its shock REFLECTS, `PRIOR_ART.md` §1.9), and the NVE
    interior that is everything above the border up to the free surface.
    The projectile is born ``spawn_height`` above the surface, in the open
    ``p p f`` vacuum, and flies down onto it.
    """

    frozen_base_thickness: float = 4.0   # Å: immobile bottom anchor depth
    border_thickness: float = 6.0        # Å: Langevin heat-sink layer depth
    spawn_height: float = 10.0           # Å: projectile birth above surface


# The projectile-spawn region is a thin lateral slab at the birth height;
# a new atom created anywhere in the cell's plane lands inside it, and the
# vacuum above the surface is otherwise empty, so grouping by this region
# catches exactly the atom just created (DESIGN.md §3.2, §10.4).
_PROJECTILE_SPAWN_HALF_THICKNESS = 1.0   # Å: half-depth of the spawn band

# Adaptive-timestep bounds for the violent NVE cascade (DESIGN §3.3,
# `PRIOR_ART.md` §1.9). ``fix dt/reset`` shrinks the step so no atom moves
# more than a small fraction of an ångström per step — a fast recoil at a
# fixed step can jump straight THROUGH the steep ZBL wall into an overlap.
# The MAX step is the spec's cascade_timestep; the MIN and the max-move are
# documented stand-ins, and the fix is REMOVED for the thermostatted
# relaxation (an adaptive step destabilises Nose-Hoover). Pinning these is
# a §4.7 follow-on.
_ADAPTIVE_MIN_TIMESTEP_STANDIN = Quantity(1.0e-5, "ps")   # ~0.01 fs floor
_ADAPTIVE_MAX_MOVE_STANDIN = 0.1        # Å: cap on per-step atom motion
_ADAPTIVE_TIMESTEP_CHECK_INTERVAL = 1   # recompute dt every step
_CASCADE_HALT_CHECK_INTERVAL = 10       # check elapsed cascade time every N


def cascade_region_group_commands(
        base_low: float,
        surface_high: float,
        geometry: CascadeGeometry = CascadeGeometry()) -> list:
    """Carve the standalone slab into base / border / interior (§10.2).

    ``base_low`` is the bottom z of the slab and ``surface_high`` the z of
    its free (top) surface; the frozen base and Langevin border are stacked
    up from the bottom, and the interior is left implicit — it is
    integrated as part of ``all`` (see :func:`cascade_integrator_commands`),
    so that projectile atoms CREATED mid-run are integrated automatically.
    This also defines the fixed projectile-spawn region and an initially
    empty ``projectile`` group that each impact refills (§10.4).
    """
    base = geometry.frozen_base_thickness
    border = geometry.border_thickness
    base_top = base_low + base
    border_top = base_top + border
    spawn_z = surface_high + geometry.spawn_height
    half = _PROJECTILE_SPAWN_HALF_THICKNESS
    return [
        f"region frozen_base block INF INF INF INF "
        f"{_lammps_number(base_low)} {_lammps_number(base_top)} units box",
        "group frozen_base region frozen_base",
        f"region border block INF INF INF INF "
        f"{_lammps_number(base_top)} {_lammps_number(border_top)} units box",
        "group border region border",
        # The fixed spawn band and the (empty for now) projectile group.
        f"region spawn block INF INF INF INF "
        f"{_lammps_number(spawn_z - half)} {_lammps_number(spawn_z + half)} "
        f"units box",
        "group projectile region spawn",
    ]


def cascade_integrator_commands(
        pair: PairSpecification, seed: int) -> list:
    """Integrate ALL atoms; freeze the base; thermostat the border (§10.2).

    Three fixes make the heat sink DESIGN.md §3.3 requires. (1) ``fix nve
    all`` advances every atom — crucially INCLUDING projectiles created
    later, since the ``all`` group always contains new atoms, which a
    static ``interior`` group would miss. (2) The frozen base is held
    immobile by zeroing its force each step; started at rest (the driver
    initialises velocities), a zero-force atom does not move, so the base
    anchors the slab and absorbs recoil without reflecting it as a rigid
    wall would. (3) The border carries a Langevin thermostat, its
    center-of-mass drift removed FIRST (``temp/com`` + ``fix_modify``) so
    directed motion is never counted as heat — the same bias-removal the
    press border uses. Together the cascade stays BALLISTIC in the interior
    while the border drains the shock at a physical rate, the fix prior art
    lacks (`PRIOR_ART.md` §1.9).

    The border/substrate target temperature is the ambient the experiment
    sits at; v1 reads ``press_temperature`` for it (the room-temperature
    setpoint the press hold also targets). A dedicated activation
    temperature knob is a possible spec follow-on (dev/TODO.md).
    """
    temperature = to_metal(pair.protocol.press_temperature, "temperature")
    damping = to_metal(pair.numerical.langevin_damping, "time")
    return [
        "fix nve_all all nve",
        "fix freeze_base frozen_base setforce 0.0 0.0 0.0",
        "compute cascade_border_temp border temp/com",
        f"fix langevin_border border langevin {_lammps_number(temperature)} "
        f"{_lammps_number(temperature)} {_lammps_number(damping)} {seed}",
        "fix_modify langevin_border temp cascade_border_temp",
    ]


def cascade_adaptive_timestep_commands(
        pair: PairSpecification) -> list:
    """Turn ON the adaptive timestep for the violent NVE cascade (§10.4).

    ``fix dt/reset`` recomputes the step so no atom moves more than
    :data:`_ADAPTIVE_MAX_MOVE_STANDIN` per step, between a small floor and
    the spec's ``cascade_timestep`` ceiling. This is what stops a fast
    recoil from tunnelling through the steep ZBL wall into an overlap
    (`PRIOR_ART.md` §1.9). It is removed again by
    :func:`cascade_fixed_timestep_commands` for the thermostatted
    relaxation, where an adaptive step would destabilise the thermostat.
    """
    min_step = to_metal(_ADAPTIVE_MIN_TIMESTEP_STANDIN, "time")
    max_step = to_metal(pair.numerical.cascade_timestep, "time")
    return [
        f"fix cascade_dt all dt/reset {_ADAPTIVE_TIMESTEP_CHECK_INTERVAL} "
        f"{_lammps_number(min_step)} {_lammps_number(max_step)} "
        f"{_lammps_number(_ADAPTIVE_MAX_MOVE_STANDIN)}",
    ]


def cascade_fixed_timestep_commands(
        pair: PairSpecification) -> list:
    """Restore the fixed step for the between-impact relaxation (§10.4).

    Removes the adaptive fix and pins the step to ``md_timestep`` — the
    ordinary MLIP molecular-dynamics step — for the border-thermostatted
    cool-down, so the substrate settles back toward the target
    temperature before the next impact starts from an equilibrated
    state, not a hot one.

    **It is deliberately NOT ``cascade_timestep``.** That tiny step
    (0.1 fs by default) exists to stop a fast recoil tunnelling through
    the steep ZBL wall during the violent phase. By the time this
    relaxation runs the cascade has already ended on its physical-time
    halt and the projectile's energy has thermalized, so nothing in the
    cell is moving fast enough to need it; the ordinary MD step (1 fs)
    integrates the cool-down perfectly stably. Running the cool-down at
    the cascade step instead spends TEN TIMES the steps for the same
    physical duration — measured at 49% of a whole single-impact run
    (LEDGER T-21), which is pure waste. The re-anneal already made this
    distinction (:func:`reanneal_commands` runs at ``md_timestep``);
    this brings the between-impact relaxation into line with it.
    """
    fixed_step = to_metal(pair.numerical.md_timestep, "time")
    return [
        "unfix cascade_dt",
        f"timestep {_lammps_number(fixed_step)}",
    ]


def insert_projectile_commands(
        projectile_type: int,
        position: tuple,
        velocity: tuple) -> list:
    """Create one projectile above the surface and aim it (§10.4).

    ``position`` is the birth point ``(x, y, z)`` in box coordinates (z in
    the spawn band :func:`cascade_region_group_commands` defined) and
    ``velocity`` the ``(vx, vy, vz)`` the driver sampled from the impact
    energy and angle. The ``projectile`` group is CLEARED and refilled from
    the spawn region so it holds exactly this impact's atom — never a
    previous, now-embedded projectile — and the velocity is set on that
    lone atom. The projectile is neutral and interacts only through ZBL
    (DESIGN.md §3.2), which the resolved force model already arranges.
    """
    x, y, z = position
    vx, vy, vz = velocity
    return [
        "group projectile clear",
        f"create_atoms {projectile_type} single "
        f"{_lammps_number(x)} {_lammps_number(y)} {_lammps_number(z)} "
        f"units box",
        "group projectile region spawn",
        f"velocity projectile set {_lammps_number(vx)} {_lammps_number(vy)} "
        f"{_lammps_number(vz)} units box",
    ]


def cascade_halt_commands(duration: float) -> list:
    """Stop the NVE cascade after a PHYSICAL time has elapsed (§10.4).

    ``duration`` is the per-impact cascade time in ps (the spec's
    ``cascade_duration``). The halt is kept ENTIRELY inside LAMMPS so the
    driver needs no clock read-back: the current time is snapshotted into
    ``cascade_start`` with immediate expansion (``$(time)`` is substituted
    with the numeric time when the line is read), and ``elapsed_cascade``
    (defined by :func:`cascade_setup_commands`) is ``time - cascade_start``.
    ``fix halt`` watches that elapsed time — which accumulates the true
    simulated time even as the adaptive step changes — and ends the run
    when it passes ``duration``. Sizing the cascade by TIME, not a constant
    step count, is what stops a high-energy impact being cut off early: the
    exact defect of prior art's fixed ``run 5000`` under an adaptive step
    (`PRIOR_ART.md` §1.9). Re-snapshotting ``cascade_start`` here resets the
    clock for each impact.
    """
    return [
        "variable cascade_start equal $(time)",
        f"fix cascade_halt all halt {_CASCADE_HALT_CHECK_INTERVAL} "
        f"v_elapsed_cascade > {_lammps_number(duration)} error continue",
    ]


def cascade_halt_release_commands() -> list:
    """Remove the cascade time-halt before the relaxation run (§10.4)."""
    return ["unfix cascade_halt"]


def cascade_setup_commands(
        pair: PairSpecification,
        force_model: ForceModel,
        data_file: str,
        base_low: float,
        surface_high: float,
        seed: int,
        geometry: CascadeGeometry = CascadeGeometry()) -> list:
    """The one-time cascade setup, before any impact runs (§10.2).

    Sets the box up (``p p f`` open top so sputtered atoms LEAVE, §3.3),
    loads the resolved universal MLIP + ZBL force model, carves the standalone
    slab's regions and the projectile-spawn scaffolding, and starts the
    frozen-base / Langevin-border / NVE-all integrators. It also defines
    ``elapsed_cascade`` — the simulated-time variable :func:`cascade_halt_
    commands` watches — and allows lost atoms (sputtering). The per-impact
    loop (insert -> adaptive cascade to a time target -> fixed-step border
    relaxation) is issued by the cascade driver on top of this, one slice
    up; this returns only the shared preamble every impact builds on.
    """
    commands = []
    commands += preamble_commands(
        data_file, pair.numerical.cascade_timestep, force_model)
    # Sputtered atoms LEAVE through the open `p p f` top (§10.4), so a
    # SHRINKING atom count is expected physics, not an error — warn on a
    # lost atom rather than aborting (LAMMPS aborts by default).
    commands.append("thermo_modify lost warn")
    # The cascade-clock variables the per-impact halt watches: a start
    # snapshot (re-taken each impact by cascade_halt_commands) and the time
    # elapsed since it. Defining them here means the halt line stays a
    # single fix (DESIGN.md §10.4).
    commands.append("variable cascade_start equal $(time)")
    commands.append("variable elapsed_cascade equal time-v_cascade_start")
    commands += force_model_commands(force_model)
    commands += cascade_region_group_commands(base_low, surface_high, geometry)
    commands += cascade_integrator_commands(pair, seed)
    return commands


def cascade_prerelax_commands() -> list:
    """Relax the slab under the cascade potential BEFORE the first impact.

    DESIGN.md §2.4 / §2.7 step 2. A dissimilar pair is strained in-plane
    onto the shared coincidence cell at build (:func:`sabsim.structure.
    slab_builder.tile_slab_to_shared_cell`), which scales the atoms in the
    plane but leaves their OUT-OF-PLANE spacing exactly as cut — the Poisson
    response to that strain has not been taken. This energy-minimizes the
    slab once, under the already-loaded cascade force model, so the
    bombardment is not run on a slab still stressed by that un-relaxed
    out-of-plane response (and, once a committee exists, by the
    committee<->cascade lattice difference the same handoff introduces).

    It is genuinely "relax the out-of-plane coordinates at FIXED lateral
    cell": ``minimize`` never changes the box, and the frozen base is held
    put by its ``setforce 0 0 0`` (which minimization honours), so only the
    border and interior atoms settle while the bulk lattice stays anchored.
    The ballistic ``nve`` and Langevin fixes are time-integration fixes that
    minimization simply ignores, so they are harmless left in place. Same
    tolerances as the §10.5 re-anneal minimize, for one consistent
    relaxation criterion everywhere. For an unstrained (same-material) slab
    it is a cheap near-no-op — a small surface settle — so it can run
    unconditionally rather than being gated on the match.
    """
    return [
        "min_style cg",
        "minimize 1e-8 1e-8 1000 10000",
    ]
