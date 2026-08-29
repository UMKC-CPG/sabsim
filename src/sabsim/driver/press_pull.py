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
from typing import NamedTuple

import numpy as np

from sabsim.driver.analysis import (
    atom_count_conserved,
    averaged_force_curve,
    contact_reached,
    cross_interface_bridges,
    interface_opening,
    interface_plane,
    net_grip_force,
    potential_energy_drift,
    reexpress_versus_opening,
    reference_is_settled,
    separation_point,
    SettleReport,
    trailing_mean,
)
from sabsim.driver.commands import (
    ForceModel,
    RegionGeometry,
    force_model_commands,
    grip_hold_and_readback_commands,
    integrator_commands,
    combined_cell_relax_commands,
    preamble_commands,
    press_drive_commands,
    press_release_commands,
    pull_drive_commands,
    pull_headroom_commands,
    recording_commands,
    region_group_commands,
    restart_preamble_commands,
    timestep_command,
    to_metal,
    trajectory_dump_commands,
)
from sabsim.driver.engine import Engine
from sabsim.driver.resume import (
    Ledger,
    input_hash,
    load_checkpoint,
    reconcile,
    verify_inputs_or_stop,
    write_checkpoint,
)
from sabsim.spec.records import MemberSpecification, Quantity
from sabsim.structure.wafer_tags import WAFER_A_TAG, WAFER_B_TAG


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
    The contact test's own two settings — the opening's trailing-mean
    window and the sustained-stress floor — are STUDY knobs
    (``numerical.contact_gap_window`` / ``contact_stress_floor``, DESIGN
    §5.2), not fields here. (The TODO item "retire the walking-skeleton
    residue" tracks moving the remaining constants into the study file.)
    """

    chunk_steps: int = 1000
    max_chunks: int = 500
    stress_window: int = 5
    equilibrate_chunks: int = 20
    separation_cutoff: float = 6.0     # Å, the §4.6 potential cutoff
    density_bin_width: float = 1.0     # Å, dividing-surface profile bin
    # The distance within which two atoms count as still JOINED, which
    # is what "the interface has come apart" is measured against (§5.5).
    # STAND-IN matching live_stages' _BOND_CUTOFF; the §3.5 reference
    # data carries a bond_cutoff that both should eventually read.
    bond_cutoff: float = 2.8           # Å, Si first g(r) minimum
    # Engine steps between §13 resume checkpoints, when a checkpoint
    # directory is given. It lives here beside chunk_steps and max_chunks
    # because it is the SAME kind of setting — chunking engineering, not
    # physics; the answer is invariant to it (it trades work-lost-on-a-
    # kill against time spent writing state). Provisional value.
    checkpoint_cadence: int = 10000


@dataclass(frozen=True)
class PressResult:
    """Whether the press reached contact, and when (§9.3).

    Besides the verdict, the press RECORDS where its phases fall in the
    engine's step count (PSEUDOCODE §9.3 ``StageLedger``, DESIGN §5.5):
    ``press_start_step`` (drive installed, first chunk begins),
    ``contact_step`` (the dual criterion fired) and ``hold_end_step``
    (the hold at temperature ended). Every frame of the press recording
    carries its step, so a consumer keys a frame to its phase by these
    numbers rather than guessing from its position in the file. The
    settle adds its own two markers (:class:`ReferenceResult`).
    """

    contact_reached: bool
    chunks_to_contact: int | None
    note: str
    press_start_step: int | None = None
    contact_step: int | None = None
    hold_end_step: int | None = None
    # Whether the pair still holds every atom it was assembled with, read
    # at the END of the press phase (cell relax, press, hold). A press
    # that ejected atoms is VOID (DESIGN §5.6), whatever
    # ``contact_reached`` says — a flying fragment can fire the stress
    # criterion on a pair that has disintegrated (LEDGER T-18).
    atoms_conserved: bool = True


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
    # Conservation against the ASSEMBLED count (§5.6), checked here too so
    # an atom lost during the settle is caught before any pull starts.
    atoms_conserved: bool = True
    # The settle's two ledger markers (PSEUDOCODE §9.4): the step the drive
    # was released and the minimize began, and the step the gated
    # reference was written. Frames between them are the zero-load
    # reference the bootstrap's family 9 is harvested from (§11.3).
    settle_start_step: int | None = None
    settle_end_step: int | None = None


@dataclass(frozen=True)
class PullResult:
    """One pull rung reduced to its two curves and separation (§9.6)."""

    grip_displacement: np.ndarray
    force_vs_grip: np.ndarray
    interface_opening: np.ndarray
    force_vs_opening: np.ndarray
    separation_index: int | None
    complete: bool
    # False when the box silently ate an atom (§9.6): the curve above is
    # then a fiction, not a measurement, and must not be integrated.
    atoms_conserved: bool = True
    # Atom pairs still spanning the interface, per recorded frame, and
    # the count at the moment the pull stopped. Reported so a result
    # that stopped with material still joining the wafers declares
    # itself rather than hiding inside the number (§5.5).
    bridges: np.ndarray | None = None
    bridges_at_separation: int | None = None
    # Whether this rung's result was produced by RESUMING a checkpoint
    # (§13), and whether the §13.4 trust guard was overridden to do so.
    # Carried into the report so the history stays honest about how the
    # number was produced (VISION goal 3) — NOT because the measurement
    # differs, since a resumed pull is the SAME measurement (§11.5).
    resumed: bool = False
    override_used: bool = False


class PullStart(NamedTuple):
    """What :func:`begin_or_resume_pull` hands back to the loop (§13.3).

    The ledger the loop extends, plus whether this pull is RESUMING a
    checkpoint and whether the §13.4 trust guard was overridden to do so —
    the two facts the result carries into provenance (§13.6, §11.5).
    """

    ledger: Ledger
    resumed: bool
    override_used: bool


def _wafer_z(positions: np.ndarray, tags: np.ndarray) -> tuple:
    """Split a position frame into the two wafers' z-columns by tag.

    Wafer A is the bottom slab and wafer B the top by construction (see
    ``slab_builder``), so the A-tagged atoms give the lower z-column and
    the B-tagged atoms the upper one.
    """
    z_lower = positions[tags == WAFER_A_TAG][:, 2]
    z_upper = positions[tags == WAFER_B_TAG][:, 2]
    return z_lower, z_upper


def _positions_with_tags(engine: Engine, tags: np.ndarray) -> tuple:
    """Current positions and their wafer tags, aligned row-for-row.

    The builder's tag array covers the ORIGINAL N atoms, keyed by atom id
    (build order == id order, so atom id ``k`` carries ``tags[k-1]``). Under
    a long universal-MLIP run a free surface evaporates or sputters a few
    atoms, so :meth:`engine.positions` returns only M <= N survivors. Pairing
    those M rows against the full N-entry tag array would misalign (or raise
    on the length mismatch), which is the failure that stalled every DPA
    press/pull once atoms began to shed.

    The engine also exposes the survivors' ids in the same ascending order
    as the positions rows, so re-indexing the tag array by those ids
    (``tags[atom_ids - 1]``) realigns tags onto exactly the survivors. With
    no loss the ids are ``1..N`` and this is the identity, preserving the
    original row-for-row contract.
    """
    frame = np.asarray(engine.positions(), dtype=float)
    survivor_ids = np.asarray(engine.atom_ids(), dtype=int)
    aligned_tags = np.asarray(tags)[survivor_ids - 1]
    return frame, aligned_tags


def _steps(duration: Quantity, timestep: Quantity) -> int:
    """MD steps spanning a duration, given the timestep."""
    return max(1, round(to_metal(duration, "time")
                        / to_metal(timestep, "time")))


def _press_setup(
        built, member, force_model, data_file, seed, geometry,
        trajectory_file=None, trajectory_stride=None) -> list:
    """The press command block WITHOUT the drive or the runs (§9.3).

    Reads the structure, loads the force model, carves the driver zones,
    installs the integrator, and installs the shared grip force gauges —
    everything the press needs EXCEPT the drive itself. The drive is issued
    separately by :func:`press_and_bond`, after the one-time lateral cell
    relax of §5.6 has run with the top grip still free of a drive fix.

    The grip gauges live here, on the instance the press and settle share,
    so the settle can read them without redefining a compute
    (:func:`grip_hold_and_readback_commands`).

    A ``trajectory_file`` opens a strided dump that stays open for the
    press AND the settle that follows on this same engine, so the two
    read as one continuous movie of the wafers meeting and relaxing.
    """
    commands = (
        preamble_commands(data_file, member.numerical.md_timestep,
                          force_model)
        + force_model_commands(force_model)
        + region_group_commands(built, geometry)
        + integrator_commands(member, seed)
        + grip_hold_and_readback_commands())
    if trajectory_file is not None:
        commands += trajectory_dump_commands(
            trajectory_file,
            trajectory_stride or member.numerical.frame_stride)
    return commands


def press_and_bond(
        engine: Engine,
        built,
        member: MemberSpecification,
        force_model: ForceModel,
        data_file: str,
        seed: int,
        geometry: RegionGeometry = RegionGeometry(),
        control: RunControl = RunControl(),
        trajectory_file: str | None = None,
        trajectory_stride: int | None = None) -> PressResult:
    """Relax the shared cell once, press until contact, then hold (§9.3).

    The pair arrives HEALED and GATED (§3.4, revised 2026-08-28: each half
    was annealed, minimized and judged in its own cascade session) and
    assembled at the press-start opening, so the bond flow's first act is
    the ONE-TIME lateral cell relax of DESIGN §5.6 — the shared in-plane
    cell to zero in-plane stress, then frozen for everything after. The
    drive is then installed and the press advances in chunks: after each,
    it measures the surface-to-surface opening (§2.6) and appends the
    normal stress, and stops when the opening's trailing mean has closed
    to the study's gap threshold AND the running-average stress shows a
    sustained load of either sign above the study's floor
    (:func:`contact_reached`, DESIGN §5.2). It then holds at temperature
    for ``press_duration`` where bonding happens, recording the step each
    phase began at (the ledger, :class:`PressResult`). The bonded verdict
    and contact-quality grading reuse §8 geometric machinery not yet
    built, so this reports contact, not a graded bond.
    """
    numerical = member.numerical
    engine.commands(
        _press_setup(built, member, force_model, data_file, seed, geometry,
                     trajectory_file, trajectory_stride))
    # The §5.6 conservation baseline is the ASSEMBLED pair — the count the
    # structure was built with — not whatever the engine holds later. Every
    # exit below reports conservation against it, so an atom ejected in the
    # cell relax or the press is never invisible to the analyzer.
    assembled_atom_count = len(built.atoms.get_tags())

    def conserved_now() -> bool:
        return atom_count_conserved(
            assembled_atom_count, engine.atom_count())

    # One-time combined-cell relax (§5.6, §2.6): resize the shared lateral
    # cell to zero in-plane stress, then FREEZE it for the press. The
    # recorded relaxation that replaces the forbidden live barostat; it
    # relieves the dominant frame-0 stress (the cell off the model's
    # preferred lattice) so a strained pair does not detonate at contact
    # (T-17, job 16453628). It needs the joint cell, which is why it is
    # the one relaxation that did not move to the activation stage.
    tags = np.asarray(built.atoms.get_tags())
    engine.commands(combined_cell_relax_commands())

    # The drive goes on and the press begins; the ledger notes the step.
    engine.commands(press_drive_commands(built, member))
    press_start_step = engine.step()
    gap_threshold = to_metal(numerical.contact_gap_threshold, "distance")
    stress_floor = to_metal(numerical.contact_stress_floor, "pressure")
    stress_series: list = []
    opening_series: list = []
    contact_chunk = None
    for chunk in range(control.max_chunks):
        engine.commands([f"run {control.chunk_steps}"])
        frame, aligned_tags = _positions_with_tags(engine, tags)
        z_lower, z_upper = _wafer_z(frame, aligned_tags)
        opening_series.append(interface_opening(
            z_lower, z_upper, control.density_bin_width))
        stress_series.append(engine.normal_stress())
        # The gap is judged on a TRAILING MEAN of the opening, as the
        # stress already is (DESIGN §5.2): one chunk's density-surface
        # reading jumps by ångströms when loose atoms drift through the
        # gap, and demanding both conditions in the SAME chunk let the
        # wafers touch without contact ever being declared (T-31).
        opening = trailing_mean(opening_series, numerical.contact_gap_window)
        if contact_reached(opening, gap_threshold, stress_series,
                           control.stress_window, stress_floor):
            contact_chunk = chunk
            break

    if contact_chunk is None:
        return PressResult(
            contact_reached=False, chunks_to_contact=None,
            note="no contact within the chunk budget (§9.3)",
            press_start_step=press_start_step,
            atoms_conserved=conserved_now())
    contact_step = engine.step()

    hold_steps = _steps(member.protocol.press_duration, numerical.md_timestep)
    engine.commands([f"run {hold_steps}"])
    hold_end_step = engine.step()
    conserved = conserved_now()
    return PressResult(
        contact_reached=True, chunks_to_contact=contact_chunk,
        note=("contact on the dual criterion, held at temperature (§9.3)"
              if conserved else
              "LOST ATOMS during the press — result VOID (§5.6)"),
        press_start_step=press_start_step, contact_step=contact_step,
        hold_end_step=hold_end_step,
        atoms_conserved=conserved)


def settle_reference(
        engine: Engine,
        member: MemberSpecification,
        control: RunControl = RunControl(),
        reference_data_file: str | None = None,
        expected_atom_count: int | None = None) -> ReferenceResult:
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

    Any trajectory dump the press opened is still open here (same
    engine), so the settle is recorded as the tail of the press movie
    rather than needing a file of its own.

    When ``reference_data_file`` is given, the settled state is written
    there and its path returned — the artifact the pull restores from,
    since the pull runs on a fresh engine and reads a file (§9.6). Handing
    the pull the ORIGINAL pair data instead would silently discard the
    whole press.

    ``expected_atom_count`` is the ASSEMBLED pair's count (§5.6); when
    given, the settled state is also checked for conservation against it,
    and a settle that lost an atom reports ``atoms_conserved=False``.
    """
    numerical = member.numerical
    engine.commands(press_release_commands(member))
    settle_start_step = engine.step()             # ledger (§9.4)
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
    settle_end_step = engine.step()               # ledger (§9.4)
    conserved = (
        atom_count_conserved(expected_atom_count, engine.atom_count())
        if expected_atom_count is not None else True)
    return ReferenceResult(
        settled=report.settled, report=report,
        potential_energy=energies[-1] if energies else engine.energy(),
        reference_data_file=reference_data_file,
        atoms_conserved=conserved,
        settle_start_step=settle_start_step,
        settle_end_step=settle_end_step)


def _pull_fixture_commands(
        built, member, force_model, rate, seed, geometry,
        trajectory_file: str | None = None,
        trajectory_stride: int | None = None) -> list:
    """The pull's fixtures — everything that is NOT the box itself (§13.3).

    The force model, the region/group carve, the integrator, the grip
    gauges, the pull drive, and the recording. These are re-established the
    same way whether the box arrived from a fresh ``read_data`` or a
    resumed ``read_restart``, because none of them live in a restart file:
    a restart carries atoms, box, velocities, and timestep — not fixes,
    computes, regions, or groups. So both setups end with this same block.
    """
    return (
        force_model_commands(force_model)
        + region_group_commands(built, geometry)
        + integrator_commands(member, seed)
        + grip_hold_and_readback_commands()
        + pull_drive_commands(rate)
        + recording_commands(member, trajectory_file, trajectory_stride))


def _pull_setup(
        built, member, force_model, data_file, rate, seed, geometry,
        travel_time: float, trajectory_file: str | None = None,
        trajectory_stride: int | None = None) -> list:
    """The FRESH pull command block WITHOUT the run (the loop issues that).

    ``travel_time`` is how long this rung may pull for, which sizes the
    box headroom so the separation cannot carry atoms out through the top
    (see :func:`pull_headroom_commands`). A resumed pull instead restores
    an already-grown box and reuses :func:`_pull_fixture_commands` over it,
    NEVER re-growing the headroom (§13.3).

    ``trajectory_file`` is optional because nothing downstream reads the
    frames for the reduction — the strided dump is the coordinate archive
    for §8/§12 and human inspection (§9.5). One rung's frames ran to
    1.3 GB, so a run nobody intends to analyze does not write them.
    """
    return (
        preamble_commands(data_file, member.numerical.md_timestep,
                          force_model)
        + pull_headroom_commands(rate, travel_time)
        + _pull_fixture_commands(
            built, member, force_model, rate, seed, geometry,
            trajectory_file, trajectory_stride))


def begin_or_resume_pull(
        engine: Engine,
        built,
        member: MemberSpecification,
        force_model: ForceModel,
        data_file: str,
        rate: Quantity,
        seed: int,
        geometry: RegionGeometry,
        control: RunControl,
        checkpoint_dir: str | None,
        trajectory_file: str | None,
        trajectory_stride: int | None) -> PullStart:
    """Set the pull up fresh, or resume it from a checkpoint (§13.3).

    Whether this is a fresh pull or a resumed one is decided entirely by
    what is on disk: with no checkpoint pair in ``checkpoint_dir`` (or no
    directory given) the pull begins normally and seeds an empty ledger
    carrying only the starting atom count; finding a pair, it restores the
    engine from the saved state, reloads the ledger, and reconciles it to
    the restored step. Either way it returns the ledger the loop extends.

    The two setups differ in exactly two lines. A fresh run reads the
    settled reference with ``read_data`` and grows the box headroom for
    the whole travel; a resume restores the already-grown box with
    ``read_restart`` and so must NOT grow it again, or the box would
    double. Everything else — the fixtures — is identical, because a
    restart file carries none of it (:func:`_pull_fixture_commands`).
    """
    numerical = member.numerical
    timestep = to_metal(numerical.md_timestep, "time")

    checkpoint = (
        load_checkpoint(checkpoint_dir) if checkpoint_dir else None)

    if checkpoint is None:
        # FRESH. Read the reference and size the box for the whole travel.
        travel_time = control.max_chunks * control.chunk_steps * timestep
        engine.commands(_pull_setup(
            built, member, force_model, data_file, rate, seed, geometry,
            travel_time, trajectory_file, trajectory_stride))
        # The atom count as the pull STARTS — the §5.6 conservation
        # baseline, measured once and carried in the ledger so a resume
        # checks against the ORIGINAL count, not a depleted one (§13.1).
        starting_atom_count = int(np.asarray(engine.positions()).shape[0])
        ledger = Ledger(
            starting_atom_count=starting_atom_count,
            input_hash=input_hash(member, data_file, rate))
        return PullStart(ledger=ledger, resumed=False, override_used=False)

    # RESUMING. Trust FIRST (§13.4): if the current inputs hash differently
    # from the run this checkpoint came from, STOP before touching the
    # engine — unless the person has deliberately overridden, which we
    # carry forward so the provenance records it (§13.6).
    override_used = verify_inputs_or_stop(
        checkpoint, member, data_file, rate)

    # Restore the already-grown box with read_restart (never read_data,
    # and NO headroom — the box came back with it), then re-establish the
    # fixtures over it. The step count rides in with the restart, so the
    # ledger reconciles to where the atoms actually are.
    engine.commands(restart_preamble_commands(force_model))
    engine.read_restart(checkpoint.engine_state)
    engine.commands(
        timestep_command(numerical.md_timestep)
        + _pull_fixture_commands(
            built, member, force_model, rate, seed, geometry,
            trajectory_file, trajectory_stride))
    ledger = reconcile(checkpoint.ledger, engine.step())
    return PullStart(
        ledger=ledger, resumed=True, override_used=override_used)


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
        output_directory: str,
        trajectory_file: str | None = None,
        trajectory_stride: int | None = None,
        checkpoint_dir: str | None = None,
        expected_atom_count: int | None = None) -> PullResult:
    """Pull apart at one rate until complete separation, then reduce (§9.5).

    Sets up (or resumes) the pull, then advances in chunks, recording into
    a ledger the grip displacement, the top-grip reaction force, the
    interface opening, and the bridge count — each keyed to the engine's
    ABSOLUTE step so a resumed run stays consistent (§13.5). It stops at
    complete separation — opening past the cutoff with no atom still
    bridging — then reduces to the two curves and the separation point
    (§9.6). ``output_directory`` is a required keyword: the run states
    where its output goes, never the working directory.

    When ``checkpoint_dir`` is given, a resume checkpoint pair is written
    there every ``control.checkpoint_cadence`` steps, and if one is already
    present the pull RESUMES from it rather than starting over (§13.3). A
    strided trajectory is written only when ``trajectory_file`` names one.

    ``expected_atom_count`` is the ASSEMBLED pair's count. When given it is
    the §5.6 conservation baseline instead of the count at pull start, so
    an atom lost anywhere between assembly and separation voids the rung;
    the pull-start count is only a fallback for a rung run on its own.
    """
    numerical = member.numerical
    timestep = to_metal(numerical.md_timestep, "time")

    # Fresh setup or restore-from-checkpoint, decided by what is on disk;
    # either way this returns the ledger the loop below extends, plus
    # whether the pull resumed and whether the trust guard was overridden
    # — the two facts the result carries into provenance (§13.3, §13.6).
    start = begin_or_resume_pull(
        engine, built, member, force_model, data_file, rate, seed,
        geometry, control, checkpoint_dir, trajectory_file,
        trajectory_stride)
    ledger = start.ledger

    tags = np.asarray(built.atoms.get_tags())
    rate_metal = to_metal(rate, "velocity")
    window = to_metal(numerical.force_average_window, "distance")
    # How far the grip travels per chunk, hence how many further chunks
    # are needed to lay down one full averaging window of record.
    per_chunk = rate_metal * control.chunk_steps * timestep
    confirmation_chunks = (
        int(np.ceil(window / per_chunk)) + 1 if per_chunk else 1)

    lateral_cell = np.asarray(built.atoms.get_cell())
    # The total step budget, which is what the box headroom was sized for.
    # Bounding the loop by the engine's ABSOLUTE step means a resume
    # continues toward the SAME ceiling instead of starting a fresh budget
    # that would drive the grip out through the top of the box (§13.5).
    step_budget = control.max_chunks * control.chunk_steps
    remaining_tail = None
    while engine.step() < step_budget:
        engine.commands([f"run {control.chunk_steps}"])
        step = engine.step()
        # THE HINGE (§13.5, DESIGN §11.1): displacement is grip travel =
        # rate x elapsed, and elapsed is the ABSOLUTE step x timestep, not
        # a per-process burst count. Identical on a fresh run; correct
        # across a resume, where a burst counter would restart at zero.
        ledger.sample_steps.append(step)
        ledger.displacement.append(rate_metal * (step * timestep))
        frame, aligned_tags = _positions_with_tags(engine, tags)
        z_lower, z_upper = _wafer_z(frame, aligned_tags)
        ledger.opening.append(interface_opening(
            z_lower, z_upper, control.density_bin_width))
        ledger.force.append(engine.grip_reaction("top"))
        # Bonds crossing the interface plane, over ALL atoms regardless of
        # which wafer they were built in — a transferred atom belongs to
        # whichever body it now sits in.
        ledger.bridges.append(cross_interface_bridges(
            frame, lateral_cell,
            interface_plane(z_lower, z_upper, control.density_bin_width),
            control.bond_cutoff))

        # Save the checkpoint pair on the cadence (§13.2), when resuming is
        # enabled for this rung. It is keyed to the step just run.
        cadence_due = (
            step - ledger.saved_step >= control.checkpoint_cadence)
        if checkpoint_dir is not None and cadence_due:
            write_checkpoint(engine, ledger, checkpoint_dir)

        # The raw test is a STOPPING heuristic, not the verdict. It says
        # "there is probably nothing more to learn here", and the run then
        # continues one more averaging window so the REDUCED curve extends
        # past the separation instead of ending exactly at it. The verdict
        # is taken ONCE, below, from the same curves the work integral is
        # computed over.
        if remaining_tail is None:
            if (ledger.opening[-1] > control.separation_cutoff
                    and ledger.bridges[-1] == 0):
                remaining_tail = confirmation_chunks
        else:
            remaining_tail -= 1
            if remaining_tail <= 0:
                break

    final_atom_count = int(np.asarray(engine.positions()).shape[0])
    baseline = (expected_atom_count if expected_atom_count is not None
                else ledger.starting_atom_count)
    conserved = atom_count_conserved(baseline, final_atom_count)

    grip_curve, averaged = averaged_force_curve(
        ledger.displacement, ledger.force, window)
    opening_curve, _ = reexpress_versus_opening(
        grip_curve, averaged, ledger.displacement, ledger.opening)
    # The bridge count carried onto the same samples as the curve, so the
    # stop is decided on the record the work integral runs over.
    bridge_curve, _ = reexpress_versus_opening(
        grip_curve, averaged, ledger.displacement, ledger.bridges)
    separation_index = separation_point(
        opening_curve, bridge_curve, control.separation_cutoff)
    # ONE definition of "separated": the reduced curves are authoritative,
    # because they are what the §8.4 work integral is taken over. A pull
    # is complete exactly when that integral has an endpoint to stop at.
    return PullResult(
        grip_displacement=grip_curve,
        force_vs_grip=averaged,
        interface_opening=opening_curve,
        force_vs_opening=averaged,
        separation_index=separation_index,
        complete=separation_index is not None,
        atoms_conserved=conserved,
        bridges=np.asarray(bridge_curve, dtype=float),
        bridges_at_separation=(
            int(round(float(bridge_curve[separation_index])))
            if separation_index is not None and len(bridge_curve) else None),
        resumed=start.resumed,
        override_used=start.override_used)
