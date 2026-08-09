"""The persistent surface-activation cascade driver (PSEUDOCODE.md §10).

This is the step-4 counterpart of the press/pull driver
(:mod:`sabsim.driver.press_pull`): the orchestration that opens a cascade
driver on a STANDALONE slab in vacuum and bombards its surface to the
target dose, tying slice 2's cascade command generation and the §4.7
classical + ZBL force model together into the per-impact loop DESIGN.md §3
specifies. Like the press/pull driver it is written ENTIRELY against the
:class:`~sabsim.driver.engine.Engine` seam, so every branch is tested
against ``MockEngine`` with no LAMMPS; the real adapter drops in unchanged
on a compute node.

Two things it does NOT do live one slice up and land next: the MLIP
re-anneal (§10.5, which relaxes the disorder this authored) and the
activation gate (§10.6, the pass/fail check on the re-annealed structure).
This module runs ONE amorphization realization; the ensemble that averages
the bond metric over realizations (STRUCTURAL 4) is the sequencer's job,
varying the master seed above this module (§10.8).

The cascade differs from the press/pull loop in one structural way: each
impact is FIRE-AND-FORGET. The press reads the state back between chunks to
decide when contact is real; a cascade impact has no such mid-run decision
— the physical-time halt (§10.4) ends the ballistic phase from inside
LAMMPS — so the loop only ISSUES commands and never blocks on a read-back.
The damaged state it leaves in the engine is what the re-anneal and gate
read afterward.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from ase.data import atomic_masses, atomic_numbers

from sabsim.driver.cascade_potential import resolve_cascade_generator
from sabsim.driver.commands import (
    CascadeGeometry,
    ForceModel,
    _lammps_number,
    cascade_adaptive_timestep_commands,
    cascade_fixed_timestep_commands,
    cascade_halt_commands,
    cascade_halt_release_commands,
    cascade_prerelax_commands,
    cascade_setup_commands,
    force_model_commands,
    insert_projectile_commands,
    to_metal,
    trajectory_dump_commands,
)
from sabsim.driver.engine import Engine
from sabsim.spec.records import MemberSpecification, Quantity

# The energy of a 1 amu mass moving at 1 Å/ps, expressed in eV — the
# metal-unit bridge from an impact ENERGY to a projectile SPEED. Derivation:
# 1 amu (Å/ps)^2 = 1.66053906660e-27 kg * (100 m/s)^2 = 1.66053906660e-23 J
# = 1.036426965e-4 eV. So E[eV] = 1/2 * m[amu] * v[Å/ps]^2 * this, and
# v = sqrt(2 E / (m * this)).
_AMU_ANGSTROM_PER_PS_SQ_IN_EV = 1.036426965e-4


@dataclass(frozen=True)
class CascadeControl:
    """Engineering settings for the cascade loop (not physics knobs).

    ``cascade_step_cap`` is a BACKSTOP on the adaptive NVE cascade run: the
    physical-time halt (§10.4) should end each cascade well before this
    many steps, but a finite cap keeps a pathological impact from running
    unbounded. It is not a duration — the duration is the spec's
    ``cascade_duration``, enforced by the halt. The activation GATE has its
    own settings (:class:`~sabsim.driver.activation_gate.GateControl`);
    this controls only the cascade.
    """

    cascade_step_cap: int = 100000


@dataclass(frozen=True)
class BombardmentSpec:
    """The concrete impact plan for one slab (PSEUDOCODE.md §10.3).

    Everything the per-impact loop needs, derived from the member's
    protocol and ensemble knobs: the projectile (its LAMMPS type id and
    mass), the per-impact energy and incidence angle, how many impacts the
    dose implies, the per-impact seeds derived from the one master seed,
    and the two per-impact durations. Metal units throughout (eV, radians,
    ps), so the loop emits bare numbers.
    """

    projectile_symbol: str
    projectile_type: int               # LAMMPS type id in the cascade cell
    projectile_mass: float             # amu, from the species
    impact_energy: float               # eV
    impact_angle: float                # radians from the surface normal
    impact_count: int                  # from the dose (fluence x area)
    impact_seeds: tuple                # one derived seed per impact
    cascade_duration: float            # ps, the NVE cascade per impact
    between_impact_relaxation: float   # ps, the border cool between impacts


@dataclass(frozen=True)
class CascadeOutcome:
    """What the bombardment loop leaves behind (the damaged slab is live).

    The amorphized state itself lives in the engine (the re-anneal and gate
    read it back); this records only that the planned dose was delivered.
    """

    impacts_run: int
    note: str


def derive_seeds(master_seed: int, count: int) -> tuple:
    """Derive ``count`` per-impact seeds from the one master seed (§10.3).

    A single recorded master seed reproduces the whole ensemble
    (`VISION.md` goal 3); every per-impact seed is drawn from it
    deterministically, so a run replays exactly. Prior art's rewrite uses
    unseeded randomness and does not reproduce (`PRIOR_ART.md` §1.9).
    """
    generator = np.random.default_rng(master_seed)
    return tuple(
        int(seed) for seed in generator.integers(1, 2**31 - 1, size=count))


def _lateral_area(built) -> float:
    """The slab's in-plane cell area (Å²), for the fluence-to-count map."""
    cell = np.asarray(built.atoms.get_cell())
    return float(np.linalg.norm(np.cross(cell[0], cell[1])))


def _impact_count(fluence: Quantity, built) -> int:
    """Turn the dose into a number of impacts (DESIGN.md §3.2, §10.3).

    Dose is designed as a FLUENCE (ions·Å⁻²) so it is comparable across
    cell sizes; v1's template freezes it directly as an impact COUNT (unit
    ``impacts``) for simplicity, so both are accepted: an ``impacts`` value
    is the count itself, while an areal fluence is multiplied by the slab's
    lateral area.
    """
    if fluence.unit == "impacts":
        return int(round(fluence.value))
    if fluence.unit in ("1/angstrom^2", "angstrom^-2", "ions/angstrom^2"):
        return int(round(fluence.value * _lateral_area(built)))
    raise ValueError(
        f"activation fluence unit '{fluence.unit}' is neither an impact "
        f"count ('impacts') nor an areal fluence (ions/angstrom^2)")


def _angle_in_radians(angle: Quantity) -> float:
    """Read an incidence angle Quantity as radians (degrees or radians).

    The activation angle is measured from the surface normal (0 = normal
    incidence). ``to_metal`` has no angle dimension, so this converts here.
    """
    unit = angle.unit.lower()
    if unit in ("deg", "degree", "degrees"):
        return math.radians(angle.value)
    if unit in ("rad", "radian", "radians"):
        return float(angle.value)
    raise ValueError(
        f"activation angle unit '{angle.unit}' is not an angle (deg/rad)")


def _speed_from_energy(energy_ev: float, mass_amu: float) -> float:
    """Projectile speed (Å/ps) from its kinetic energy (eV) and mass (amu).

    From E = 1/2 m v² in metal units (see
    :data:`_AMU_ANGSTROM_PER_PS_SQ_IN_EV`): v = sqrt(2 E / (m · c)).
    """
    return math.sqrt(
        2.0 * energy_ev / (mass_amu * _AMU_ANGSTROM_PER_PS_SQ_IN_EV))


def derive_bombardment_spec(
        built, member: MemberSpecification) -> BombardmentSpec:
    """Build the concrete impact plan from the member's knobs (§10.3).

    ``built`` is the cascade cell wrapper (its ``type_map`` MUST already
    include the projectile species, since the cascade creates those atoms);
    ``member`` supplies the protocol (species, energy, angle, dose, per-
    impact durations) and ensemble (master seed). The projectile mass is
    taken from the species — nothing is hand-set per material — and the
    impact count follows from the dose (§10.3).
    """
    protocol = member.protocol
    symbol = protocol.activation_species
    projectile_mass = float(atomic_masses[atomic_numbers[symbol]])

    impact_energy = to_metal(protocol.activation_energy, "energy")
    impact_angle = _angle_in_radians(protocol.activation_angle)
    impact_count = _impact_count(protocol.activation_fluence, built)
    impact_seeds = derive_seeds(member.ensemble.master_seed, impact_count)

    return BombardmentSpec(
        projectile_symbol=symbol,
        projectile_type=built.type_map[symbol],
        projectile_mass=projectile_mass,
        impact_energy=impact_energy,
        impact_angle=impact_angle,
        impact_count=impact_count,
        impact_seeds=impact_seeds,
        cascade_duration=to_metal(protocol.cascade_duration, "time"),
        between_impact_relaxation=to_metal(
            protocol.between_impact_relaxation, "time"))


def sample_impact_position(
        built, spawn_height: float, seed: int) -> tuple:
    """A reproducible impact site above the surface (§10.4).

    The lateral (x, y) site is drawn uniformly over the cell's in-plane
    parallelogram from the impact's own seed, so impacts spread across the
    surface rather than pile on one spot; the birth height is the free
    surface plus ``spawn_height`` (the spawn band the cascade regions
    defined, so the created atom is grouped as the projectile).
    """
    generator = np.random.default_rng(seed)
    fraction_a, fraction_b = generator.random(), generator.random()
    cell = np.asarray(built.atoms.get_cell())
    in_plane = fraction_a * cell[0] + fraction_b * cell[1]
    surface_high = float(np.asarray(built.atoms.get_positions())[:, 2].max())
    return (float(in_plane[0]), float(in_plane[1]),
            surface_high + spawn_height)


def sample_impact_velocity(spec: BombardmentSpec, seed: int) -> tuple:
    """A reproducible impact velocity (Å/ps), aimed at the surface (§10.4).

    The speed is fixed by the impact energy and projectile mass; the
    DIRECTION is the incidence angle from the surface normal, with the
    downward (−z) component ``v·cos θ`` and the lateral component ``v·sin
    θ`` sent along a seed-chosen azimuth. Normal incidence (θ = 0, v1)
    reduces to straight down, ``(0, 0, −v)``.
    """
    speed = _speed_from_energy(spec.impact_energy, spec.projectile_mass)
    normal_speed = speed * math.cos(spec.impact_angle)
    lateral_speed = speed * math.sin(spec.impact_angle)
    # Decorrelate the azimuth from the position draw with an offset seed.
    generator = np.random.default_rng(seed + 1)
    azimuth = generator.random() * 2.0 * math.pi
    return (lateral_speed * math.cos(azimuth),
            lateral_speed * math.sin(azimuth),
            -normal_speed)


def run_cascade_to_fluence(
        engine: Engine,
        built,
        member: MemberSpecification,
        force_model: ForceModel,
        data_file: str,
        spec: BombardmentSpec,
        seed: int,
        geometry: CascadeGeometry = CascadeGeometry(),
        control: CascadeControl = CascadeControl(),
        trajectory_file: str | None = None,
        trajectory_stride: int = 200) -> CascadeOutcome:
    """Bombard the surface to the target dose (PSEUDOCODE.md §10.4).

    Opens the cascade driver (the classical + ZBL force model, the
    frozen-base / Langevin-border / NVE heat sink, the ``p p f`` open top),
    then for each impact: inserts the projectile aimed at a fresh site,
    runs the NVE cascade under the adaptive timestep until the physical-time
    halt fires (§10.4), then removes the adaptive fix and relaxes under the
    border thermostat at a fixed step so the next impact starts from an
    equilibrated substrate. Every impact is fire-and-forget — the halt ends
    the ballistic phase from inside LAMMPS — so the loop only issues
    commands; the damaged state it leaves in the engine is what the
    re-anneal (§10.5) and gate (§10.6) read next.

    ``seed`` seeds the border thermostat; the per-impact position and
    velocity seeds come from ``spec.impact_seeds``.

    ``trajectory_file`` optionally records the whole bombardment for
    visual inspection — one frame per ``trajectory_stride`` steps, held
    open across every impact so the result is a single continuous movie
    rather than one file per collision. It is off unless asked for: the
    frames cost wall clock inside the hot cascade loop and the files are
    large.
    """
    positions = np.asarray(built.atoms.get_positions())
    base_low = float(positions[:, 2].min())
    surface_high = float(positions[:, 2].max())

    engine.commands(cascade_setup_commands(
        member, force_model, data_file, base_low, surface_high, seed,
        geometry))

    # Relax the freshly-read slab under the cascade potential before the
    # first impact (§2.4 / §2.7 step 2): a strained mismatched slab takes
    # its out-of-plane Poisson response at fixed lateral cell here, rather
    # than being bombarded while still stressed. The frozen base stays put
    # (setforce), so only the surface settles. Issued before the dump opens
    # so the recorded movie stays about the bombardment, not this settle.
    engine.commands(cascade_prerelax_commands())

    # Opened once, before the first impact, and deliberately never closed
    # here: the re-anneal that follows runs on this same engine, so
    # leaving the dump open captures the surface HEALING as well as being
    # damaged — which is the more informative half of the movie.
    if trajectory_file is not None:
        engine.commands(
            trajectory_dump_commands(trajectory_file, trajectory_stride))

    relax_steps = max(1, round(
        spec.between_impact_relaxation
        / to_metal(member.numerical.cascade_timestep, "time")))

    for impact_seed in spec.impact_seeds:
        position = sample_impact_position(
            built, geometry.spawn_height, impact_seed)
        velocity = sample_impact_velocity(spec, impact_seed)
        engine.commands(insert_projectile_commands(
            spec.projectile_type, position, velocity))

        # The violent NVE cascade under the adaptive step, ended by the
        # physical-time halt (the step cap is only a backstop, §10.4).
        engine.commands(cascade_adaptive_timestep_commands(member))
        engine.commands(cascade_halt_commands(spec.cascade_duration))
        engine.commands([f"run {control.cascade_step_cap}"])
        engine.commands(cascade_halt_release_commands())

        # The fixed-step border-thermostatted relaxation between impacts.
        engine.commands(cascade_fixed_timestep_commands(member))
        engine.commands([f"run {relax_steps}"])

    return CascadeOutcome(
        impacts_run=spec.impact_count,
        note=f"delivered {spec.impact_count} impacts of "
             f"{spec.projectile_symbol} at "
             f"{spec.impact_energy:.0f} eV (§10.4)")


# ---------------------------------------------------------------------
# The MLIP re-anneal (PSEUDOCODE.md §10.5) — a stage prior art does NOT
# have. The classical cascade AUTHORED the disorder; this gently settles
# it under the MLIP so the final structure is MLIP/DFT-quality, before the
# gate judges it. In v1 the "MLIP" is the classical stand-in (§4.5), so
# this exercises the plumbing; the trained committee drops in unchanged.
# ---------------------------------------------------------------------

def mlip_reanneal(
        engine: Engine,
        member: MemberSpecification,
        mlip_force_model: ForceModel,
        seed: int,
        projectile_types) -> None:
    """Gently re-equilibrate the amorphized surface under the MLIP (§10.5).

    First it tears down the cascade's machinery: the ZBL heat-sink fixes
    are removed and EVERY projectile atom deleted, because the projectile
    is NOT part of the activated surface (embedded or surface-adsorbed
    argon is stripped, as prior art does with ejecta) and the Si-only MLIP
    cannot see it. Deletion is BY TYPE (``projectile_types``, the LAMMPS
    type ids of the projectile species), because the spawn-region
    ``projectile`` group holds only the LAST impact's atom — it is cleared
    and refilled each impact — so a group-based delete would leave the
    earlier embedded projectiles behind. The frozen base is KEPT so the
    bulk lattice anchors the gentle relaxation. It then loads the MLIP,
    minimizes, holds the mobile atoms briefly at the anneal temperature,
    and quenches back to room temperature (the ``reanneal_schedule``). A
    kinetically trapped glass bounds how far this may go, so it is
    deliberately mild — "re-annealed" means "as relaxed as this schedule
    got it" (STRUCTURAL 1b).

    The re-anneal runs at the MLIP MD step (``md_timestep``), not the tiny
    cascade step, and the quench span reuses ``hold_duration`` as a
    documented stand-in (the schedule carries no separate quench time).
    """
    engine.commands(
        reanneal_commands(member, mlip_force_model, projectile_types))


def reanneal_commands(
        member: MemberSpecification,
        mlip_force_model: ForceModel,
        projectile_types) -> list:
    """The re-anneal command block (§10.5), as one ordered list.

    Split out of :func:`mlip_reanneal` so the SAME sequence can be either
    issued to a live in-process engine (the classical-cascade path) OR
    assembled into a self-contained script run out-of-process under the
    universal-MLIP cascade engine (:func:`build_activate_script`,
    ARCHITECTURE §4.3 file handoff). The commands are identical either way;
    only who executes them differs.

    The block: tear down the cascade's ballistic integrator and border
    thermostat (the frozen base stays, anchoring the bulk), delete EVERY
    projectile atom by type, load the MLIP, minimize, hold the mobile atoms
    at the anneal temperature, quench toward room temperature, and RENUMBER
    the survivors so the gate's ``gather_atoms`` read sees consecutive ids.
    """
    schedule = member.protocol.reanneal_schedule
    hold_temperature = to_metal(schedule.hold_temperature, "temperature")
    room_temperature = to_metal(member.protocol.press_temperature,
                                "temperature")
    damping = to_metal(member.numerical.langevin_damping, "time")
    md_step = to_metal(member.numerical.md_timestep, "time")
    hold_steps = max(1, round(
        to_metal(schedule.hold_duration, "time") / md_step))

    commands = [
        # Drop the cascade's ballistic integrator and border thermostat;
        # the frozen base stays (it anchors the bulk through the relax).
        "unfix nve_all",
        "unfix langevin_border",
        "uncompute cascade_border_temp",
        # The projectile is not part of the activated surface — strip EVERY
        # projectile atom (by type, so embedded ones from earlier impacts go
        # too, not just the last), then re-carve the mobile group without
        # them.
        f"group cascade_projectiles type "
        f"{' '.join(str(type_id) for type_id in sorted(projectile_types))}",
        # compress yes RENUMBERS the remaining atoms to consecutive ids —
        # required because the gate reads positions with gather_atoms, which
        # rejects the id gaps that sputtered (lost) atoms and this deletion
        # would otherwise leave.
        "delete_atoms group cascade_projectiles compress yes",
        "group mobile subtract all frozen_base",
    ]
    commands += force_model_commands(mlip_force_model)
    commands += [
        f"timestep {_lammps_number(md_step)}",
        "min_style cg",
        "minimize 1e-8 1e-8 1000 10000",
        # A gentle hold at the anneal temperature, mobile atoms only.
        f"fix reanneal mobile nvt temp {_lammps_number(hold_temperature)} "
        f"{_lammps_number(hold_temperature)} {_lammps_number(damping)}",
        f"run {hold_steps}",
        # Quench back toward room temperature (ramp the setpoint down).
        f"fix reanneal mobile nvt temp {_lammps_number(hold_temperature)} "
        f"{_lammps_number(room_temperature)} {_lammps_number(damping)}",
        f"run {hold_steps}",
        # Sputtering (during the cascade) and the projectile deletion leave
        # the atom ids non-consecutive; the gate reads positions with
        # gather_atoms, which requires consecutive ids, so RENUMBER the
        # survivors here — the last touch of the atom set before the gate.
        # Losing atoms is EXPECTED for an open `p p f` surface (§10.4), the
        # OPPOSITE of the pull's closed-box atom-count gate; this only
        # relabels the survivors 1..N, it changes no atom and hides no loss.
        "unfix reanneal",
        "reset_atoms id",
    ]
    return commands


def cascade_cleanup_commands(projectile_types) -> list:
    """The cascade's own end-of-stage cleanup (§3.4), as one command list.

    This is what stays in the CASCADE-ONLY activate stage after the anneal
    moved to the bond flow (§3.4, revised 2026-08-08): drop the cascade's
    ballistic integrator and border thermostat, STRIP every projectile atom
    (by type, so embedded ones from earlier impacts go too), and RENUMBER
    the survivors so a ``gather_atoms`` or a sorted dump read pairs
    row-for-row with the type map. The frozen base is kept (it anchors the
    bulk). It leaves the surface SUBSTRATE-ONLY and consecutively numbered,
    ready to hand off — the re-equilibration (heal) is NOT here; it runs on
    the assembled pair in the bond flow (§9.1). No MLIP is loaded and no MD
    is run: this only tears down and relabels.
    """
    return [
        # Drop the cascade's ballistic integrator and border thermostat;
        # the frozen base stays (it anchors the bulk lattice).
        "unfix nve_all",
        "unfix langevin_border",
        "uncompute cascade_border_temp",
        # The projectile is not part of the activated surface — strip EVERY
        # projectile atom by type (embedded ones from earlier impacts too),
        # leaving the surface substrate-only for the handoff (§3.4).
        f"group cascade_projectiles type "
        f"{' '.join(str(type_id) for type_id in sorted(projectile_types))}",
        # compress yes RENUMBERS the remaining atoms to consecutive ids —
        # sputtering and this deletion leave gaps, and the read-back
        # (gather_atoms / a sorted dump) needs consecutive ids.
        "delete_atoms group cascade_projectiles compress yes",
        "reset_atoms id",
    ]


def build_activate_script(
        built,
        member: MemberSpecification,
        cascade_force_model: ForceModel,
        data_file: str,
        spec: BombardmentSpec,
        seed: int,
        projectile_types,
        output_structure_file: str,
        geometry: CascadeGeometry = CascadeGeometry(),
        control: CascadeControl = CascadeControl()) -> list:
    """Assemble the CASCADE-ONLY activate run as one self-contained script.

    This is the out-of-process twin of :func:`run_cascade_to_fluence` plus
    :func:`cascade_cleanup_commands`. When the cascade runs on the
    universal-MLIP engine — a separate deepmd bundle that cannot share this
    process's LAMMPS (ARCHITECTURE §4.1/§4.4) — the cascade half of the
    activate stage is emitted here as a script, run under that engine's
    ``lmp`` in ONE subprocess, and its AMORPHIZED structure handed back
    through a FILE (ARCHITECTURE §4.3). The sabsim process builds the slab
    before and reads the amorphized structure back after; nothing is read
    back mid-run. The heal and the §3.5 gate are NOT here — the §3.4 revision
    moved them to the bond flow (§9.1), so this stage is cascade-only.

    That the cascade needs NO mid-run read-back is what makes this possible:
    every impact's position and velocity is derived from a seed
    (:func:`sample_impact_position` / :func:`sample_impact_velocity`), not
    from the live damaged state, so all impacts are precomputed here and the
    per-impact halt ends each cascade from inside LAMMPS. The command blocks
    are the SAME ones the in-process path issues — setup, the §2.4 prerelax,
    the per-impact insert -> adaptive cascade -> fixed-step relax loop, then
    :func:`cascade_cleanup_commands` — so the two paths run identical physics.

    The script ends by writing the AMORPHIZED (substrate-only, re-numbered)
    structure to ``output_structure_file`` as a sorted custom dump
    (``id type x y z``), the handoff the §3.5 gate (now in the bond flow) and
    the amorphized-half snapshot read back.
    """
    positions = np.asarray(built.atoms.get_positions())
    base_low = float(positions[:, 2].min())
    surface_high = float(positions[:, 2].max())

    script = []
    script += cascade_setup_commands(
        member, cascade_force_model, data_file, base_low, surface_high,
        seed, geometry)
    # The §2.4 out-of-plane relax before the first impact (same as live).
    script += cascade_prerelax_commands()

    relax_steps = max(1, round(
        spec.between_impact_relaxation
        / to_metal(member.numerical.cascade_timestep, "time")))

    # Every impact, precomputed from its seed — no live state is consulted,
    # so the whole bombardment is known before the run starts.
    for impact_seed in spec.impact_seeds:
        position = sample_impact_position(
            built, geometry.spawn_height, impact_seed)
        velocity = sample_impact_velocity(spec, impact_seed)
        script += insert_projectile_commands(
            spec.projectile_type, position, velocity)
        script += cascade_adaptive_timestep_commands(member)
        script += cascade_halt_commands(spec.cascade_duration)
        script += [f"run {control.cascade_step_cap}"]
        script += cascade_halt_release_commands()
        script += cascade_fixed_timestep_commands(member)
        script += [f"run {relax_steps}"]

    # Cascade cleanup (§3.4): strip the projectile + renumber, the SAME block
    # the live path issues. NO heal here — it moved to the bond flow.
    script += cascade_cleanup_commands(projectile_types)

    # The handoff: write the AMORPHIZED structure for the sabsim process to
    # read back. A sorted custom dump carries id, type, and the coordinates
    # the amorphized-half snapshot (and, later, the bond-flow gate) need, and
    # its header carries the box; `sort id` gives the consecutive-id order the
    # read-back pairs row-for-row with the type map (ARCHITECTURE §4.3).
    script += [
        f"write_dump all custom {output_structure_file} "
        f"id type x y z modify sort id",
    ]
    return script


# ---------------------------------------------------------------------
# The activation gate lives in `activation_gate` (PSEUDOCODE §10.6) — the
# pluggable metric registry (g(r), coordination, ring statistics, depth).
# Revised 2026-08-08 (§3.4): the gate no longer runs in the activate stage;
# it moved to the bond flow (`press_pull.gate_healed_surfaces`), which judges
# each HEALED surface and produces the `ActivationVerdict` directly. The
# activate stage itself is cascade-only and returns a `CascadeOutcome`.
# ---------------------------------------------------------------------


# ---------------------------------------------------------------------
# Tying it together (PSEUDOCODE.md §10.1): each surface is activated
# INDEPENDENTLY — cascade to the dose, re-anneal, then GATE the re-annealed
# structure. Two calls, never one co-activation; the pair does not co-exist
# here (activation runs before the two ever face each other, §3.1).
# ---------------------------------------------------------------------

def _projectile_species(member: MemberSpecification) -> set:
    """The projectile species set: the beam plus any co-species (§10.3)."""
    protocol = member.protocol
    species = {protocol.activation_species}
    cospecies = protocol.activation_cospecies
    if cospecies and cospecies.lower() != "none":
        species.add(cospecies)
    return species


def activate_surface(
        engine: Engine,
        built,
        member: MemberSpecification,
        data_file: str,
        seed: int,
        geometry: CascadeGeometry = CascadeGeometry(),
        control: CascadeControl = CascadeControl(),
        allow_unvalidated_potential: bool = False,
        use_classical_cascade: bool = False,
        trajectory_file: str | None = None,
        trajectory_stride: int = 200) -> CascadeOutcome:
    """Activate ONE surface: CASCADE ONLY (§10.1, revised 2026-08-08).

    Resolves the cascade force model for this slab's species (the §4.7 seam
    — never named here, only asked for), derives the impact plan, bombards
    the surface to the dose, then runs the cascade CLEANUP (§3.4): strip the
    projectile and renumber, leaving the surface SUBSTRATE-ONLY and ready to
    snapshot. The heal and the §3.5 gate are NOT here — the §3.4 revision
    moved them to the bond flow (§9.1). ``built.type_map`` must already
    declare the projectile so the cascade can create those atoms.

    Returns the :class:`CascadeOutcome` (provenance: impacts delivered); the
    amorphized structure stays LIVE in the engine for the caller to snapshot.

    ``allow_unvalidated_potential`` forwards the §4.7 escape hatch for
    EXPLORATORY bring-up of a new material. It stays False unless a caller
    deliberately asks, and results obtained under it are provisional.

    ``use_classical_cascade`` selects a curated CLASSICAL cascade form
    (silicon's Stillinger-Weber, keyed by the member's ``material_domain``)
    instead of the DESIGN-default universal foundation MLIP (§4.7,
    "universal by default, classical by choice"). It stays False so the
    default is universal.

    ``trajectory_file`` optionally records the bombardment as a movie, for
    visual inspection only — nothing downstream reads it.
    """
    cascade_force_model = resolve_cascade_generator(
        built.type_map, _projectile_species(member),
        allow_unvalidated=allow_unvalidated_potential,
        domain=member.material_domain,
        use_classical=use_classical_cascade)
    spec = derive_bombardment_spec(built, member)
    cascade = run_cascade_to_fluence(
        engine, built, member, cascade_force_model, data_file, spec, seed,
        geometry, control, trajectory_file, trajectory_stride)
    projectile_types = [
        built.type_map[species]
        for species in _projectile_species(member)
        if species in built.type_map]
    # Cascade cleanup (§3.4): strip the projectile + renumber survivors, so
    # the surface left live in the engine is substrate-only and ready to
    # snapshot. No heal, no gate — those moved to the bond flow (§9.1).
    engine.commands(cascade_cleanup_commands(projectile_types))
    return cascade


def activate_surfaces(
        engine_a: Engine,
        engine_b: Engine,
        built_a,
        built_b,
        member: MemberSpecification,
        data_file_a: str,
        data_file_b: str,
        seed: int,
        geometry: CascadeGeometry = CascadeGeometry(),
        control: CascadeControl = CascadeControl()) -> tuple:
    """Activate BOTH surfaces independently, in their own engines (§10.1).

    Each surface is amorphized in vacuum on its OWN engine, BEFORE the two
    ever face each other — the whole point of surface-activated bonding
    (§3.1). Cascade-only (revised 2026-08-08, §3.4): returns the two
    :class:`CascadeOutcome`\\ s (provenance); the amorphized structures stay
    live in each engine for the caller to snapshot, and the heal + §3.5 gate
    run later in the bond flow. The two are independent, so a future parallel
    map may run them concurrently; the sequencer's realization ensemble
    (STRUCTURAL 4) loops ABOVE this, varying the master seed (§10.8).
    """
    outcome_a = activate_surface(
        engine_a, built_a, member, data_file_a, seed, geometry, control)
    outcome_b = activate_surface(
        engine_b, built_b, member, data_file_b, seed, geometry, control)
    return outcome_a, outcome_b
