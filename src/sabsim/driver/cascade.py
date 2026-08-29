"""The surface-activation cascade driver (PSEUDOCODE.md §10).

This is the step-4 counterpart of the press/pull driver
(:mod:`sabsim.driver.press_pull`): it turns a member's bombardment
protocol into the per-impact LAMMPS command stream DESIGN.md §3
specifies — the impact plan derived from the fluence, the seeded impact
positions and velocities, and the cleanup that strips the projectile.

The cascade runs on the universal foundation MLIP spliced with ZBL cores
(DESIGN §4.7). That model lives in deepmd's own bundle and cannot load
into this process (ARCHITECTURE §4.1/§4.4), so the whole activate run is
assembled here as ONE self-contained script (:func:`build_activate_script`)
and executed out-of-process, its amorphized structure handed back through
a file. Nothing is read back mid-run: every impact's position and
velocity is derived from a seed, and the physical-time halt (§10.4) ends
each ballistic phase from inside LAMMPS. The gentle heal runs at the end
of the same session (§3.4, revised 2026-08-28: per half, in vacuum, under
the same model) and the §3.5 gate judges the healed half the script hands
back.

This module runs ONE amorphization realization; the ensemble that averages
the bond metric over realizations (STRUCTURAL 4) is the sequencer's job,
varying the master seed above this module (§10.8).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from ase.data import atomic_masses, atomic_numbers

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
    heal_surface_commands,
    insert_projectile_commands,
    to_metal,
    trajectory_dump_commands,
)
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


def cascade_cleanup_commands(projectile_types) -> list:
    """The cascade's own end-of-stage cleanup (§3.4), as one command list.

    Drop the cascade's ballistic integrator and border thermostat, STRIP
    every projectile atom (by type, so embedded ones from earlier impacts
    go too), and RENUMBER the survivors so a ``gather_atoms`` or a sorted
    dump read pairs row-for-row with the type map. The frozen base is kept
    (it anchors the bulk). It leaves the surface SUBSTRATE-ONLY and
    consecutively numbered for the heal that follows
    (:func:`~sabsim.driver.commands.heal_surface_commands`, §3.4). No
    MD is run here: this only tears down and relabels.
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
        heal_marker_file: str,
        geometry: CascadeGeometry = CascadeGeometry(),
        control: CascadeControl = CascadeControl(),
        trajectory_file: str | None = None,
        trajectory_stride: int = 200,
        skip_prerelax: bool = False) -> list:
    """Assemble the activate run — cascade, then heal — as ONE script.

    The cascade runs on the universal-MLIP engine — a separate deepmd
    bundle that cannot share this process's LAMMPS (ARCHITECTURE §4.1/§4.4)
    — so the whole activate stage is emitted here as a script, run under
    that engine's ``lmp`` in ONE subprocess, and its AMORPHIZED structure
    handed back through a FILE (ARCHITECTURE §4.3). The sabsim process builds
    the slab
    before and reads the healed structure back after; nothing is read
    back mid-run. The heal (§3.4) is the script's last dynamic block, on
    the same engine and model; the §3.5 gate then judges the healed half
    the script hands back, in the sabsim process.

    That the cascade needs NO mid-run read-back is what makes this possible:
    every impact's position and velocity is derived from a seed
    (:func:`sample_impact_position` / :func:`sample_impact_velocity`), not
    from the live damaged state, so all impacts are precomputed here and the
    per-impact halt ends each cascade from inside LAMMPS. The command blocks
    are: setup, the §2.4 prerelax, the per-impact insert -> adaptive cascade
    -> fixed-step relax loop, :func:`cascade_cleanup_commands`, then the
    heal (:func:`heal_surface_commands`, which also writes the step it
    begins at to ``heal_marker_file``).

    The script ends by writing the HEALED (substrate-only, re-numbered)
    structure to ``output_structure_file`` as a sorted custom dump
    (``id type x y z``), the handoff the §3.5 gate and the amorphized-half
    snapshot read back.

    An optional ``trajectory_file`` records the WHOLE bombardment as one
    strided movie — a frame every ``trajectory_stride`` steps, opened after
    the prerelax and held open across every impact and the cleanup — so a
    cascade can be watched end to end. It is off (``None``) by default
    because the
    frames cost wall clock in the hot cascade loop (`run_options`).
    """
    positions = np.asarray(built.atoms.get_positions())
    base_low = float(positions[:, 2].min())
    surface_high = float(positions[:, 2].max())

    script = []
    script += cascade_setup_commands(
        member, cascade_force_model, data_file, base_low, surface_high,
        seed, geometry)
    # The §2.4 out-of-plane relax before the first impact (same as live).
    # skip_prerelax omits it — a DIAGNOSTIC to test whether this minimize,
    # run under the universal potential, itself disorders the crystal before
    # any impact (observed for DPA-2.4-7M on Si, the model since retired
    # for failing the Tier-0 screen: the pre-impact frame was
    # already ~8-coordinated).
    if not skip_prerelax:
        script += cascade_prerelax_commands()

    # Optional cascade MOVIE: opened here (after the prerelax, before the
    # first impact) and held open across every impact and the cleanup, so
    # the whole bombardment reads as one continuous trajectory — the SAME
    # placement the in-process `run_cascade_to_fluence` uses.
    if trajectory_file is not None:
        script += trajectory_dump_commands(
            trajectory_file, trajectory_stride)

    # The between-impact relaxation runs at the ORDINARY MD step, not
    # the tiny cascade step (see cascade_fixed_timestep_commands): the
    # cascade has halted and the energy has thermalized, so the step
    # count must be derived from the same step the relaxation is
    # actually integrated with, or the requested duration is wrong.
    relax_steps = max(1, round(
        spec.between_impact_relaxation
        / to_metal(member.numerical.md_timestep, "time")))

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

    # Cascade cleanup (§3.4): strip the projectile + renumber, so the heal
    # and the gate see a substrate-only, consecutively numbered slab.
    script += cascade_cleanup_commands(projectile_types)

    # The heal (§3.4, PSEUDOCODE §10.5): anneal on the study's schedule,
    # then minimize — per half, here, under the same model.
    script += heal_surface_commands(member, seed, heal_marker_file)

    # The handoff: write the HEALED structure for the sabsim process to
    # read back. A sorted custom dump carries id, type, and the coordinates
    # the §3.5 gate and the amorphized-half snapshot need, and its header
    # carries the box; `sort id` gives the consecutive-id order the
    # read-back pairs row-for-row with the type map (ARCHITECTURE §4.3).
    script += [
        f"write_dump all custom {output_structure_file} "
        f"id type x y z modify sort id",
    ]
    return script


# ---------------------------------------------------------------------
# The activation gate lives in `activation_gate` (PSEUDOCODE §10.6) — the
# pluggable metric registry (g(r), coordination, ring statistics, depth).
# It judges the HEALED half this script hands back, in the sabsim process
# (`live_stages.activate_one_half`), and a failed verdict halts the member
# before assembly (revised 2026-08-28, §3.4/§3.5).
#
# Each surface is activated INDEPENDENTLY — cascade to the dose, heal, then
# gate. Two calls, never one co-activation; the pair does not co-exist here
# (activation runs before the two ever face each other, §3.1).
# ---------------------------------------------------------------------

def _projectile_species(member: MemberSpecification) -> set:
    """The projectile species set: the beam plus any co-species (§10.3)."""
    protocol = member.protocol
    species = {protocol.activation_species}
    cospecies = protocol.activation_cospecies
    if cospecies and cospecies.lower() != "none":
        species.add(cospecies)
    return species
