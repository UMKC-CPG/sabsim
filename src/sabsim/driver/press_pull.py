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
    integrator_commands,
    preamble_commands,
    press_drive_commands,
    pull_drive_commands,
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
    """The settled zero-load reference and its two gates (§9.4)."""

    settled: bool
    report: SettleReport
    potential_energy: float


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
    """Split a position frame into the two wafers' z-columns by tag."""
    z_lower = positions[tags == WAFER_A_TAG][:, 2]
    z_upper = positions[tags == WAFER_B_TAG][:, 2]
    return z_lower, z_upper


def _steps(duration: Quantity, timestep: Quantity) -> int:
    """MD steps spanning a duration, given the timestep."""
    return max(1, round(to_metal(duration, "time")
                        / to_metal(timestep, "time")))


def _press_setup(
        built, member, force_model, data_file, seed, geometry) -> list:
    """The press command block WITHOUT the runs (the loop issues those)."""
    return (
        preamble_commands(data_file, member.numerical.md_timestep)
        + force_model_commands(force_model)
        + region_group_commands(built, geometry)
        + integrator_commands(member, seed)
        + press_drive_commands(built, member))


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
        control: RunControl = RunControl()) -> ReferenceResult:
    """Minimize and equilibrate to a GATED zero-load reference (§9.4).

    Relaxes to a local minimum, equilibrates in chunks while collecting
    the potential-energy series and both grip reactions, then applies the
    two gates (:func:`reference_is_settled`): the net grip force within
    the noise floor and the PE drift within threshold. A reference that
    fails either is reported as unsettled, never integrated over (§5.3).
    """
    numerical = member.numerical
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
    return ReferenceResult(
        settled=report.settled, report=report,
        potential_energy=energies[-1] if energies else engine.energy())


def _pull_setup(
        built, member, force_model, data_file, rate, seed, geometry) -> list:
    """The pull command block WITHOUT the run (the loop issues that)."""
    return (
        preamble_commands(data_file, member.numerical.md_timestep)
        + force_model_commands(force_model)
        + region_group_commands(built, geometry)
        + integrator_commands(member, seed)
        + pull_drive_commands(rate)
        + recording_commands(member, f"{member.name}_pull.dump"))


def pull_at_rate(
        engine: Engine,
        built,
        member: MemberSpecification,
        force_model: ForceModel,
        data_file: str,
        rate: Quantity,
        seed: int,
        geometry: RegionGeometry = RegionGeometry(),
        control: RunControl = RunControl()) -> PullResult:
    """Pull apart at one rate until complete separation, then reduce (§9.5).

    Restores the reference (a fresh setup reading its data file), then
    advances in chunks, recording the grip displacement, the top-grip
    reaction force, and the interface opening. It stops at complete
    separation — opening past the cutoff with the force at the noise floor
    — then reduces to the two curves: the averaged force versus grip
    displacement (leading warm-up dropped) and versus interface opening,
    plus the separation point (§9.6).
    """
    numerical = member.numerical
    engine.commands(_pull_setup(
        built, member, force_model, data_file, rate, seed, geometry))

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
