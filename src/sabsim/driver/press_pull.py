"""The persistent press/pull driver control loops (PSEUDOCODE.md §9).

This is slice 5's logic: the orchestration that opens a driver, presses
until contact, settles a zero-load reference, and pulls apart at a rate —
tying slice 2's command generation and slice 3's control math together
into the stateful, mid-run-decided protocol ARCHITECTURE.md §4.1 chose a
persistent in-process driver for. It is written ENTIRELY against the
:class:`~sabsim.driver.engine.Engine` seam, so every branch is tested
against ``MockEngine`` with no LAMMPS; the real adapter drops in
unchanged on a compute node.

The three phase functions mirror §9.3-§9.5. Each runs the simulation in
CHUNKS and, after each chunk, reads the state back and asks slice 3
whether to stop — the essence of a protocol whose transitions are
decided at runtime, not written into a static input script. Sequencing
the phases into one member's BondDebondResult (with a fresh restore per
pull rung) is thin wiring that lands with the real adapter, where the
persistent-engine lifecycle is real; here each phase is exercised on its
own.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from sabsim.driver.analysis import (
    averaged_force_curve,
    contact_reached,
    interface_opening,
    net_grip_force,
    potential_energy_drift,
    reexpress_versus_opening,
    reference_is_settled,
    separation_point,
    SettleReport,
)
from sabsim.driver.commands import (
    ForceModel,
    RegionGeometry,
    force_model_commands,
    grip_hold_and_readback_commands,
    integrator_commands,
    preamble_commands,
    press_drive_commands,
    press_release_commands,
    pull_drive_commands,
    pull_dump_file,
    recording_commands,
    region_group_commands,
    to_metal,
)
from sabsim.driver.engine import Engine
from sabsim.spec.records import MemberSpecification, Quantity
from sabsim.structure.slab_builder import WAFER_A_TAG, WAFER_B_TAG


@dataclass(frozen=True)
class RunControl:
    """How the phases chunk the run and where they stop (§9.3-§9.6).

    The simulation advances ``chunk_steps`` at a time, up to
    ``max_chunks``, reading the state back between chunks; ``stress_
    window`` is how many chunks the normal-stress running average spans;
    ``equilibrate_chunks`` is the settle span; ``separation_cutoff`` is
    the potential cutoff past which the interface counts as open (§4.6);
    ``density_bin_width`` bins the profile that locates the dividing
    surfaces (§2.6). These are engineering settings, not physics knobs.
    """

    chunk_steps: int = 1000
    max_chunks: int = 500
    stress_window: int = 5
    equilibrate_chunks: int = 20
    separation_cutoff: float = 6.0     # Å, the §4.6 potential cutoff
    density_bin_width: float = 1.0     # Å, dividing-surface profile bin


@dataclass(frozen=True)
class PressResult:
    """Whether the press reached contact, and when (§9.3)."""

    contact_reached: bool
    chunks_to_contact: int | None
    note: str


@dataclass(frozen=True)
class ReferenceResult:
    """The settled zero-load reference and its two gates (§9.4).

    ``reference_data_file`` is the path the settled state was written to,
    the artifact the pull restores from (§9.6). It is ``None`` when the
    settle was asked to write nowhere (the unit tests, which exercise the
    gates against a scripted engine and need no file on disk).
    """

    settled: bool
    report: SettleReport
    potential_energy: float
    reference_data_file: str | None = None


@dataclass(frozen=True)
class PullResult:
    """One pull rung reduced to its two curves and separation (§9.6)."""

    grip_displacement: np.ndarray
    force_vs_grip: np.ndarray
    interface_opening: np.ndarray
    force_vs_opening: np.ndarray
    separation_index: int | None
    complete: bool


def _wafer_z(positions: np.ndarray, tags: np.ndarray) -> tuple:
    """Split a position frame into the two wafers' z-columns by tag.

    Wafer A is the bottom slab and wafer B the top by construction (see
    ``slab_builder``), so the A-tagged atoms give the lower z-column and
    the B-tagged atoms the upper one.
    """
    z_lower = positions[tags == WAFER_A_TAG][:, 2]
    z_upper = positions[tags == WAFER_B_TAG][:, 2]
    return z_lower, z_upper


def _steps(duration: Quantity, timestep: Quantity) -> int:
    """MD steps spanning a duration, given the timestep."""
    return max(1, round(to_metal(duration, "time")
                        / to_metal(timestep, "time")))


def _press_setup(
        built, member, force_model, data_file, seed, geometry) -> list:
    """The press command block WITHOUT the runs (the loop issues those).

    Installs the shared grip force gauges here, on the instance the press
    and settle share, so the settle can read them without redefining a
    compute (:func:`grip_hold_and_readback_commands`).
    """
    return (
        preamble_commands(data_file, member.numerical.md_timestep)
        + force_model_commands(force_model)
        + region_group_commands(built, geometry)
        + integrator_commands(member, seed)
        + press_drive_commands(built, member)
        + grip_hold_and_readback_commands())


def press_and_bond(
        engine: Engine,
        built,
        member: MemberSpecification,
        force_model: ForceModel,
        data_file: str,
        seed: int,
        geometry: RegionGeometry = RegionGeometry(),
        control: RunControl = RunControl()) -> PressResult:
    """Press until the DUAL contact criterion fires, then hold (§9.3).

    Sets up the press, then advances in chunks: after each, it measures
    the surface-to-surface opening (§2.6) and appends the normal stress,
    and stops when the gap has closed AND the running-average stress has
    turned positive (:func:`contact_reached`). It then holds at
    temperature for ``press_duration`` where bonding happens. The bonded
    verdict and contact-quality grading reuse §8 geometric machinery not
    yet built, so this reports contact, not a graded bond.
    """
    numerical = member.numerical
    engine.commands(
        _press_setup(built, member, force_model, data_file, seed, geometry))

    tags = np.asarray(built.atoms.get_tags())
    gap_threshold = to_metal(numerical.contact_gap_threshold, "distance")
    stress_series: list = []
    contact_chunk = None
    for chunk in range(control.max_chunks):
        engine.commands([f"run {control.chunk_steps}"])
        z_lower, z_upper = _wafer_z(np.asarray(engine.positions()), tags)
        opening = interface_opening(
            z_lower, z_upper, control.density_bin_width)
        stress_series.append(engine.normal_stress())
        if contact_reached(opening, gap_threshold, stress_series,
                           control.stress_window):
            contact_chunk = chunk
            break

    if contact_chunk is None:
        return PressResult(
            contact_reached=False, chunks_to_contact=None,
            note="no contact within the chunk budget (§9.3)")

    hold_steps = _steps(member.protocol.press_duration, numerical.md_timestep)
    engine.commands([f"run {hold_steps}"])
    return PressResult(
        contact_reached=True, chunks_to_contact=contact_chunk,
        note="contact on the dual criterion, held at temperature (§9.3)")


def settle_reference(
        engine: Engine,
        member: MemberSpecification,
        control: RunControl = RunControl(),
        reference_data_file: str | None = None) -> ReferenceResult:
    """Minimize and equilibrate to a GATED zero-load reference (§9.4).

    Runs on the SAME engine as the preceding press (the settle re-reads no
    data file, so the box, the groups, and the grip force gauges all
    persist). It first RELEASES the press drive
    (:func:`press_release_commands`) so the reference settles under no
    applied load — otherwise it would equilibrate a structure that is
    still being pressed. It then relaxes to a local minimum, equilibrates
    in chunks while collecting the potential-energy series and both grip
    reactions, and applies the two gates
    (:func:`reference_is_settled`): the net grip force within the noise
    floor and the PE drift within threshold. A reference that fails either
    is reported as unsettled, never integrated over (§5.3).

    When ``reference_data_file`` is given, the settled state is written
    there and its path returned — the artifact the pull restores from,
    since the pull runs on a fresh engine and reads a file (§9.6). Handing
    the pull the ORIGINAL pair data instead would silently discard the
    whole press.
    """
    numerical = member.numerical
    engine.commands(press_release_commands(member))
    engine.commands(["min_style cg", "minimize 1e-8 1e-8 1000 10000"])

    energies: list = []
    bottom: list = []
    top: list = []
    for _ in range(control.equilibrate_chunks):
        engine.commands([f"run {control.chunk_steps}"])
        energies.append(engine.energy())
        bottom.append(engine.grip_reaction("bottom"))
        top.append(engine.grip_reaction("top"))

    net_force = net_grip_force(top, bottom)
    drift = potential_energy_drift(energies)
    noise_floor = to_metal(numerical.noise_floor, "force")
    drift_threshold = (
        to_metal(numerical.reference_pe_drift, "energy_per_atom")
        * engine.atom_count())
    report = reference_is_settled(
        net_force, noise_floor, drift, drift_threshold)

    if reference_data_file is not None:
        engine.commands([f"write_data {reference_data_file}"])
    return ReferenceResult(
        settled=report.settled, report=report,
        potential_energy=energies[-1] if energies else engine.energy(),
        reference_data_file=reference_data_file)


def _pull_setup(
        built, member, force_model, data_file, rate, seed, geometry,
        output_directory) -> list:
    """The pull command block WITHOUT the run (the loop issues that)."""
    return (
        preamble_commands(data_file, member.numerical.md_timestep)
        + force_model_commands(force_model)
        + region_group_commands(built, geometry)
        + integrator_commands(member, seed)
        + grip_hold_and_readback_commands()
        + pull_drive_commands(rate)
        + recording_commands(
            member, pull_dump_file(output_directory, member)))


def pull_at_rate(
        engine: Engine,
        built,
        member: MemberSpecification,
        force_model: ForceModel,
        data_file: str,
        rate: Quantity,
        seed: int,
        geometry: RegionGeometry = RegionGeometry(),
        control: RunControl = RunControl(),
        *,
        output_directory: str) -> PullResult:
    """Pull apart at one rate until complete separation, then reduce (§9.5).

    Restores the reference (a fresh setup reading its data file), then
    advances in chunks, recording the grip displacement, the top-grip
    reaction force, and the interface opening. It stops at complete
    separation — opening past the cutoff with the force at the noise floor
    — then reduces to the two curves: the averaged force versus grip
    displacement (leading warm-up dropped) and versus interface opening,
    plus the separation point (§9.6). The strided trajectory dump lands in
    ``output_directory`` (a required keyword — the run states where its
    output goes, never the current working directory).
    """
    numerical = member.numerical
    engine.commands(_pull_setup(
        built, member, force_model, data_file, rate, seed, geometry,
        output_directory))

    tags = np.asarray(built.atoms.get_tags())
    timestep = to_metal(numerical.md_timestep, "time")
    rate_metal = to_metal(rate, "velocity")
    noise_floor = to_metal(numerical.noise_floor, "force")

    displacement: list = []
    force: list = []
    opening: list = []
    separated = False
    for chunk in range(control.max_chunks):
        engine.commands([f"run {control.chunk_steps}"])
        elapsed = (chunk + 1) * control.chunk_steps * timestep
        displacement.append(rate_metal * elapsed)
        z_lower, z_upper = _wafer_z(np.asarray(engine.positions()), tags)
        opening.append(interface_opening(
            z_lower, z_upper, control.density_bin_width))
        force.append(engine.grip_reaction("top"))
        if (opening[-1] > control.separation_cutoff
                and abs(force[-1]) <= noise_floor):
            separated = True
            break

    window = to_metal(numerical.force_average_window, "distance")
    grip_curve, averaged = averaged_force_curve(displacement, force, window)
    opening_curve, _ = reexpress_versus_opening(
        grip_curve, averaged, displacement, opening)
    separation_index = separation_point(
        opening_curve, averaged, control.separation_cutoff, noise_floor)
    return PullResult(
        grip_displacement=grip_curve,
        force_vs_grip=averaged,
        interface_opening=opening_curve,
        force_vs_opening=averaged,
        separation_index=separation_index,
        complete=separated)
