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

from sabsim.driver.activation_gate import (
    ActivationVerdict,
    activation_gate,
    load_activation_references,
)
from sabsim.driver.cascade_potential import resolve_cascade_generator
from sabsim.driver.commands import (
    CascadeGeometry,
    ForceModel,
    _lammps_number,
    cascade_adaptive_timestep_commands,
    cascade_fixed_timestep_commands,
    cascade_halt_commands,
    cascade_halt_release_commands,
    cascade_setup_commands,
    force_model_commands,
    insert_projectile_commands,
    to_metal,
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
        control: CascadeControl = CascadeControl()) -> CascadeOutcome:
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
    """
    positions = np.asarray(built.atoms.get_positions())
    base_low = float(positions[:, 2].min())
    surface_high = float(positions[:, 2].max())

    engine.commands(cascade_setup_commands(
        member, force_model, data_file, base_low, surface_high, seed,
        geometry))

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
        seed: int) -> None:
    """Gently re-equilibrate the amorphized surface under the MLIP (§10.5).

    First it tears down the cascade's machinery: the ZBL heat-sink fixes
    are removed and the projectile atoms deleted, because the projectile is
    NOT part of the activated surface (embedded or surface-adsorbed argon
    is stripped, as prior art does with ejecta) and the Si-only MLIP cannot
    see it. The frozen base is KEPT so the bulk lattice anchors the gentle
    relaxation. It then loads the MLIP, minimizes, holds the mobile atoms
    briefly at the anneal temperature, and quenches back to room
    temperature (the ``reanneal_schedule``). A kinetically trapped glass
    bounds how far this may go, so it is deliberately mild — "re-annealed"
    means "as relaxed as this schedule got it" (STRUCTURAL 1b).

    The re-anneal runs at the MLIP MD step (``md_timestep``), not the tiny
    cascade step, and the quench span reuses ``hold_duration`` as a
    documented stand-in (the schedule carries no separate quench time).
    """
    schedule = member.protocol.reanneal_schedule
    hold_temperature = to_metal(schedule.hold_temperature, "temperature")
    room_temperature = to_metal(member.protocol.press_temperature,
                                "temperature")
    damping = to_metal(member.numerical.langevin_damping, "time")
    md_step = to_metal(member.numerical.md_timestep, "time")
    hold_steps = max(1, round(
        to_metal(schedule.hold_duration, "time") / md_step))

    teardown = [
        # Drop the cascade's ballistic integrator and border thermostat;
        # the frozen base stays (it anchors the bulk through the relax).
        "unfix nve_all",
        "unfix langevin_border",
        "uncompute cascade_border_temp",
        # The projectile is not part of the activated surface — strip it,
        # then re-carve the mobile group without it.
        "delete_atoms group projectile compress no",
        "group mobile subtract all frozen_base",
    ]
    teardown += force_model_commands(mlip_force_model)
    teardown += [
        f"timestep {_lammps_number(md_step)}",
        "min_style cg",
        "minimize 1e-8 1e-8 1000 10000",
    ]
    engine.commands(teardown)

    # A gentle hold at the anneal temperature, mobile atoms only.
    engine.commands([
        f"fix reanneal mobile nvt temp {_lammps_number(hold_temperature)} "
        f"{_lammps_number(hold_temperature)} {_lammps_number(damping)}",
        f"run {hold_steps}",
    ])
    # Quench back toward room temperature (ramp the setpoint down).
    engine.commands([
        f"fix reanneal mobile nvt temp {_lammps_number(hold_temperature)} "
        f"{_lammps_number(room_temperature)} {_lammps_number(damping)}",
        f"run {hold_steps}",
    ])
    engine.commands(["unfix reanneal"])


# ---------------------------------------------------------------------
# The activation gate itself lives in `activation_gate` (PSEUDOCODE §10.6)
# — the pluggable metric registry (g(r), coordination, ring statistics,
# depth) that judges the re-annealed structure against the share/
# references (DESIGN §3.5). activate_surface calls it below, and
# ActivationVerdict is imported from there.
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class ActivationResult:
    """One surface's activation: the gated verdict and the cascade note."""

    verdict: ActivationVerdict
    cascade: CascadeOutcome


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
        mlip_force_model: ForceModel,
        data_file: str,
        seed: int,
        geometry: CascadeGeometry = CascadeGeometry(),
        control: CascadeControl = CascadeControl()) -> ActivationResult:
    """Activate ONE surface: cascade, re-anneal, then gate (§10.1).

    Resolves the classical + ZBL cascade force model for this slab's
    species (the §4.7 seam — never named here, only asked for), derives the
    impact plan, bombards the surface to the dose, re-anneals the disorder
    under the MLIP, and judges the re-annealed structure with the §3.5
    metric gate. ``built.type_map`` must already declare the projectile so
    the cascade can create those atoms; ``mlip_force_model`` is the gentle
    potential the re-anneal (and the rest of the pipeline) runs under.
    """
    cascade_force_model = resolve_cascade_generator(
        built.type_map, _projectile_species(member))
    spec = derive_bombardment_spec(built, member)
    cascade = run_cascade_to_fluence(
        engine, built, member, cascade_force_model, data_file, spec, seed,
        geometry, control)
    mlip_reanneal(engine, member, mlip_force_model, seed)
    # Judge the re-annealed surface against the share/ references (§10.6):
    # the projectile was deleted in the re-anneal, so the activated slab is
    # substrate-only and the reference is keyed by the substrate species.
    substrate_species = frozenset(built.type_map) - _projectile_species(member)
    references = load_activation_references(substrate_species)
    verdict = activation_gate(
        engine.positions(), built.atoms.get_cell(), references)
    return ActivationResult(verdict=verdict, cascade=cascade)


def activate_surfaces(
        engine_a: Engine,
        engine_b: Engine,
        built_a,
        built_b,
        member: MemberSpecification,
        mlip_force_model: ForceModel,
        data_file_a: str,
        data_file_b: str,
        seed: int,
        geometry: CascadeGeometry = CascadeGeometry(),
        control: CascadeControl = CascadeControl()) -> tuple:
    """Activate BOTH surfaces independently, in their own engines (§10.1).

    Each surface is amorphized in vacuum on its OWN engine, BEFORE the two
    ever face each other — the whole point of surface-activated bonding
    (§3.1). Returns the two :class:`ActivationResult`\\ s; the pipeline maps
    their verdicts onto the ``ActivatedSlabs`` the ACTIVATED_SLABS_CONTRACT
    checks. The two are independent, so a future parallel map may run them
    concurrently; the sequencer's realization ensemble (STRUCTURAL 4) loops
    ABOVE this, varying the master seed (§10.8).
    """
    activated_a = activate_surface(
        engine_a, built_a, member, mlip_force_model, data_file_a, seed,
        geometry, control)
    activated_b = activate_surface(
        engine_b, built_b, member, mlip_force_model, data_file_b, seed,
        geometry, control)
    return activated_a, activated_b
