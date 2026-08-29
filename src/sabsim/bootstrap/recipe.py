"""The force-model RECIPE: records + loader (DESIGN.md §4.8, PSEUDOCODE §11.1).

A recipe is the third input file of the project, beside the study
specification and the deployment rc, and it lives on a third clock: a
potential is manufactured ONCE from it and then consumed unchanged by
many studies. This module is the in-memory shape of that file and the
loader that reads it with the study file's own discipline — every key
required (no hidden defaults, DESIGN.md §1.4), units carried, and the
location roots expanded so every later consumer sees plain paths.

The first slice (2026-08-26) reads parts 1–6 of the eight §4.8 parts:
the key, Collection 1, the two settings blocks, the generation plan and
the labelling budget. Parts 7–8 (the learning loop and the stopping
rule) are required once ``sabsim bootstrap train`` exists.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from sabsim.spec.loader import (
    SpecificationError,
    _expand_roots,
    _require,
    _require_quantity,
)
from sabsim.driver.descriptors import DescriptorSettings
from sabsim.spec.records import Quantity

# The unit strings the recipe accepts for the two quantities LAMMPS's
# metal table does not carry: a quench RATE and a reciprocal-space
# SPACING. Accepting exactly one spelling each keeps the file honest.
QUENCH_RATE_UNIT = "K/ps"
RECIPROCAL_SPACING_UNIT = "1/angstrom"


@dataclass(frozen=True)
class GeneratorModel:
    """The universal model that runs the recipe's own dynamics (§4.5)."""
    model: str                  # pinned identity, e.g. "DPA-3.1-3M"
    weights: str                # its weights file, roots expanded
    allow_unvalidated: bool     # the on-the-record exploratory opt-in
    md_timestep: Quantity       # step for the Collection-1 dynamics


@dataclass(frozen=True)
class PhaseSpec:
    """One crystal phase of the declared domain (§4.8 part 2, family 1)."""
    name: str                   # the phase, not just the composition
    cif: str                    # where symmetry, basis, connectivity come


@dataclass(frozen=True)
class BulkSpec:
    """Family 1 — the perfect crystal, replicated (§4.8 part 2)."""
    cells_per_axis: int


@dataclass(frozen=True)
class StrainSpec:
    """Family 2 — a deformation sweep past the reversible range."""
    magnitudes: tuple[float, ...]
    modes: tuple[str, ...]      # "volumetric" | "uniaxial_z" | "shear_xy"


@dataclass(frozen=True)
class QuenchSpec:
    """Family 3 — one bulk melt-quench amorphous network."""
    phase: str
    cells_per_axis: int
    melt_temperature: Quantity
    melt_duration: Quantity
    quench_rate: Quantity       # temperature per unit time, K/ps
    final_temperature: Quantity
    replicas: int
    frames: int                 # frames kept from the quench
    seed: int


@dataclass(frozen=True)
class SurfaceSpec:
    """Family 4 — one clean, unbombarded free surface."""
    phase: str
    face: tuple[int, int, int]
    termination_index: int
    slab_thickness: Quantity
    vacuum: Quantity
    lateral_repeat: int         # in-plane tiling of the primitive slab
                                # cell, so the cell is wider than twice
                                # the descriptor cutoff (a 1x1 Si(100)
                                # column is 3.9 A wide: every atom would
                                # see its own image, T-26)


@dataclass(frozen=True)
class RattleSpec:
    """Family 5 — seeded static displacements about the cold cell."""
    amplitude: Quantity
    count: int
    seed: int


@dataclass(frozen=True)
class WarmRunSpec:
    """Family 6 — one short warm run of one crystal, NVT or NPT."""
    phase: str
    ensemble: str               # "NVT" | "NPT"
    temperature: Quantity
    duration: Quantity
    equilibration: Quantity     # leading interval discarded
    sampling_stride: Quantity   # spacing between harvested frames
    replicas: int
    seed: int


@dataclass(frozen=True)
class StartingCollection:
    """Collection 1 — the six calm families, all required (§4.8 part 2)."""
    bulk: BulkSpec
    strain: StrainSpec
    melt_quench: tuple[QuenchSpec, ...]
    surfaces: tuple[SurfaceSpec, ...]
    rattle: RattleSpec
    warm_runs: tuple[WarmRunSpec, ...]


@dataclass(frozen=True)
class GenerationPlan:
    """Collection 2 — how the hard configurations are harvested (part 5).

    Nothing here runs new MD: the plan names an ordinary member run,
    recorded with ``--dump-visuals`` under the universal model, whose
    trajectories the harvester reads (PSEUDOCODE §11.3, "generate mode
    is a consumer difference").
    """
    study: str                  # the study spec that member belongs to
    member: str                 # which member's dumps to harvest
    job_directory: str          # that run's home (scratch mirror holds
                                # the dumps)
    frames_per_stage: dict      # stage -> frames kept
    subcell_crystalline_layers: int   # layers kept under each skin
    subcell_vacuum: Quantity    # vacuum closing the cut sub-cell


@dataclass(frozen=True)
class LabellingBudget:
    """Part 6 in its first-slice form: the budget alone."""
    budget_per_family: int


@dataclass(frozen=True)
class ReferenceSettings:
    """One accurate-calculation settings block (§4.8 parts 3–4).

    Two instances live in a recipe — production and audit — and they are
    not interchangeable: the production block is inherited by every
    label and every reference differenced against the model; the audit
    block is run once to measure the method error.
    """
    paw_library: str            # the POTCAR library root, roots expanded
    paw: dict                   # element symbol -> PAW directory name
    functional: str
    plane_wave_cutoff: Quantity
    reciprocal_spacing: Quantity    # a spacing, 1/angstrom
    gamma_only_off_bulk: bool
    smearing_scheme: str        # "gaussian" (ISMEAR 0) in v0
    smearing_width: Quantity
    electronic_tolerance: Quantity
    max_electronic_steps: int
    spin_polarized: bool
    real_space_projection: str  # LREAL value: "Auto" or "False"
    audited: bool


@dataclass(frozen=True)
class ForceModelRecipe:
    """The recipe, parts 1–6 (§4.8; PSEUDOCODE §11.1)."""
    name: str
    species_union: frozenset
    domain: str
    reference_data_ref: str
    generator: GeneratorModel
    phases: tuple[PhaseSpec, ...]
    starting_collection: StartingCollection
    generation_plan: GenerationPlan
    labelling: LabellingBudget
    production_settings: ReferenceSettings
    audit_settings: ReferenceSettings
    # The gate's RULER (DESIGN §4.8 part 2, 2026-08-29): how the
    # environment library — and therefore the §3.5 gate — describes one
    # atom's first neighbour shell, and the scatter multiple the library
    # is self-checked at. Distinct from the trained model's descriptor
    # (part 7): this one only asks "is this neighbourhood undamaged?".
    descriptor_settings: DescriptorSettings
    gate_scatter_multiple: float

    def phase_named(self, name: str) -> PhaseSpec:
        """The phase entry a family refers to by name (a loud miss)."""
        for phase in self.phases:
            if phase.name == name:
                return phase
        raise KeyError(
            f"recipe '{self.name}' names no phase '{name}'; it has "
            f"{[phase.name for phase in self.phases]}")


# ---------------------------------------------------------------------
# Helpers that pull one table each. Kept small and named so a reader can
# hold the TOML and this file side by side.
# ---------------------------------------------------------------------

def _require_unit(quantity: Quantity, unit: str, context: str) -> Quantity:
    """Reject a quantity whose unit is not the one accepted here."""
    if quantity.unit != unit:
        raise SpecificationError(
            f"{context}: expected unit '{unit}', got '{quantity.unit}'")
    return quantity


def _require_int(table: dict, key: str, context: str) -> int:
    return int(_require(table, key, context))


def _require_bool(table: dict, key: str, context: str) -> bool:
    value = _require(table, key, context)
    if not isinstance(value, bool):
        raise SpecificationError(
            f"{context} -> {key}: expected true or false")
    return value


def _generator_from_table(table: dict, context: str) -> GeneratorModel:
    return GeneratorModel(
        model=str(_require(table, "model", context)),
        weights=_expand_roots(
            str(_require(table, "weights", context)),
            f"{context} -> weights"),
        allow_unvalidated=_require_bool(table, "allow_unvalidated", context),
        md_timestep=_require_quantity(table, "md_timestep", context),
    )


def _phases_from_tables(tables: list, context: str) -> tuple:
    phases = []
    for table in tables:
        name = str(_require(table, "name", context))
        phases.append(PhaseSpec(
            name=name, cif=str(_require(table, "cif", f"{context} '{name}'"))))
    if not phases:
        raise SpecificationError(f"{context}: at least one phase is required")
    return tuple(phases)


def _collection_from_table(table: dict, context: str) -> StartingCollection:
    bulk_table = _require(table, "bulk", context)
    strain_table = _require(table, "strain", context)
    rattle_table = _require(table, "rattle", context)
    quenches = []
    for index, quench in enumerate(_require(table, "melt_quench", context)):
        where = f"{context}.melt_quench[{index}]"
        quenches.append(QuenchSpec(
            phase=str(_require(quench, "phase", where)),
            cells_per_axis=_require_int(quench, "cells_per_axis", where),
            melt_temperature=_require_quantity(
                quench, "melt_temperature", where),
            melt_duration=_require_quantity(quench, "melt_duration", where),
            quench_rate=_require_unit(
                _require_quantity(quench, "quench_rate", where),
                QUENCH_RATE_UNIT, f"{where} -> quench_rate"),
            final_temperature=_require_quantity(
                quench, "final_temperature", where),
            replicas=_require_int(quench, "replicas", where),
            frames=_require_int(quench, "frames", where),
            seed=_require_int(quench, "seed", where)))
    surfaces = []
    for index, surface in enumerate(_require(table, "surfaces", context)):
        where = f"{context}.surfaces[{index}]"
        face = tuple(int(component)
                     for component in _require(surface, "face", where))
        if len(face) != 3:
            raise SpecificationError(f"{where} -> face: three integers")
        surfaces.append(SurfaceSpec(
            phase=str(_require(surface, "phase", where)),
            face=face,
            termination_index=_require_int(
                surface, "termination_index", where),
            slab_thickness=_require_quantity(
                surface, "slab_thickness", where),
            vacuum=_require_quantity(surface, "vacuum", where),
            lateral_repeat=_require_int(surface, "lateral_repeat", where)))
    warm_runs = []
    for index, warm in enumerate(_require(table, "warm_runs", context)):
        where = f"{context}.warm_runs[{index}]"
        ensemble = str(_require(warm, "ensemble", where)).upper()
        if ensemble not in ("NVT", "NPT"):
            raise SpecificationError(
                f"{where} -> ensemble: 'NVT' or 'NPT', got '{ensemble}'")
        warm_runs.append(WarmRunSpec(
            phase=str(_require(warm, "phase", where)),
            ensemble=ensemble,
            temperature=_require_quantity(warm, "temperature", where),
            duration=_require_quantity(warm, "duration", where),
            equilibration=_require_quantity(warm, "equilibration", where),
            sampling_stride=_require_quantity(
                warm, "sampling_stride", where),
            replicas=_require_int(warm, "replicas", where),
            seed=_require_int(warm, "seed", where)))
    ensembles = {warm.ensemble for warm in warm_runs}
    if ensembles != {"NVT", "NPT"}:
        raise SpecificationError(
            f"{context}.warm_runs: BOTH an NVT and an NPT run are required "
            f"(§4.8 family 6); found {sorted(ensembles)}")
    return StartingCollection(
        bulk=BulkSpec(cells_per_axis=_require_int(
            bulk_table, "cells_per_axis", f"{context}.bulk")),
        strain=StrainSpec(
            magnitudes=tuple(float(m) for m in _require(
                strain_table, "magnitudes", f"{context}.strain")),
            modes=tuple(str(m) for m in _require(
                strain_table, "modes", f"{context}.strain"))),
        melt_quench=tuple(quenches),
        surfaces=tuple(surfaces),
        rattle=RattleSpec(
            amplitude=_require_quantity(
                rattle_table, "amplitude", f"{context}.rattle"),
            count=_require_int(rattle_table, "count", f"{context}.rattle"),
            seed=_require_int(rattle_table, "seed", f"{context}.rattle")),
        warm_runs=tuple(warm_runs))


def _plan_from_table(table: dict, context: str) -> GenerationPlan:
    frames = _require(table, "frames_per_stage", context)
    for stage in ("activate", "press", "pull"):
        if stage not in frames:
            raise SpecificationError(
                f"{context} -> frames_per_stage: missing '{stage}'")
    return GenerationPlan(
        study=str(_require(table, "study", context)),
        member=str(_require(table, "member", context)),
        job_directory=str(_require(table, "job_directory", context)),
        frames_per_stage={key: int(value) for key, value in frames.items()},
        subcell_crystalline_layers=_require_int(
            table, "subcell_crystalline_layers", context),
        subcell_vacuum=_require_quantity(table, "subcell_vacuum", context))


def _settings_from_table(table: dict, context: str) -> ReferenceSettings:
    paw = _require(table, "paw", context)
    if not isinstance(paw, dict) or not paw:
        raise SpecificationError(
            f"{context} -> paw: a non-empty element -> PAW-name table")
    return ReferenceSettings(
        paw_library=_expand_roots(
            str(_require(table, "paw_library", context)),
            f"{context} -> paw_library"),
        paw={str(k): str(v) for k, v in paw.items()},
        functional=str(_require(table, "functional", context)),
        plane_wave_cutoff=_require_quantity(
            table, "plane_wave_cutoff", context),
        reciprocal_spacing=_require_unit(
            _require_quantity(table, "reciprocal_spacing", context),
            RECIPROCAL_SPACING_UNIT, f"{context} -> reciprocal_spacing"),
        gamma_only_off_bulk=_require_bool(
            table, "gamma_only_off_bulk", context),
        smearing_scheme=str(_require(table, "smearing_scheme", context)),
        smearing_width=_require_quantity(table, "smearing_width", context),
        electronic_tolerance=_require_quantity(
            table, "electronic_tolerance", context),
        max_electronic_steps=_require_int(
            table, "max_electronic_steps", context),
        spin_polarized=_require_bool(table, "spin_polarized", context),
        real_space_projection=str(
            _require(table, "real_space_projection", context)),
        audited=_require_bool(table, "audited", context))


# ---------------------------------------------------------------------
# The loader, and the validation mirroring the study's three phases.
# ---------------------------------------------------------------------

def _reject_if_inconsistent(recipe: ForceModelRecipe) -> None:
    """Phase two: the recipe must agree with itself (PSEUDOCODE §11.1)."""
    phase_names = {phase.name for phase in recipe.phases}
    families = (
        [("melt_quench", q.phase) for q in
         recipe.starting_collection.melt_quench]
        + [("surfaces", s.phase) for s in
           recipe.starting_collection.surfaces]
        + [("warm_runs", w.phase) for w in
           recipe.starting_collection.warm_runs])
    for family, phase in families:
        if phase not in phase_names:
            raise SpecificationError(
                f"[collection1.{family}] names phase '{phase}', which "
                f"[[phases]] does not declare {sorted(phase_names)}")
    for block, settings in (("production_settings",
                             recipe.production_settings),
                            ("audit_settings", recipe.audit_settings)):
        missing = recipe.species_union - set(settings.paw)
        if missing:
            raise SpecificationError(
                f"[{block}] -> paw: no PAW named for {sorted(missing)}; "
                f"every element of species_union needs one")
    if not recipe.domain:
        raise SpecificationError("[recipe] -> domain: must not be empty")
    unweighted = recipe.species_union - set(
        recipe.descriptor_settings.species_weights)
    if unweighted:
        raise SpecificationError(
            f"[descriptor] -> species_weights: no weight for "
            f"{sorted(unweighted)}; every element of species_union needs "
            f"one, or the library cannot describe it")


def check_recipe_references(recipe: ForceModelRecipe) -> None:
    """Phase three: every artifact the recipe POINTS AT must exist.

    The generator weights, every phase's crystal file, the POTCAR of
    every named PAW in both settings blocks, and the reference-data file
    — all checked on the login node, so a missing file never surfaces
    an hour into a job. Raises :class:`SpecificationError` listing every
    problem at once.
    """
    from sabsim.spec.references import resolve_crystal_file
    problems = []
    if not os.path.isfile(recipe.generator.weights):
        problems.append(
            f"[generator] weights not found: {recipe.generator.weights}")
    for phase in recipe.phases:
        try:
            resolve_crystal_file(phase.cif)
        except FileNotFoundError as missing:
            problems.append(f"[[phases]] '{phase.name}': {missing}")
    for block, settings in (("production_settings",
                             recipe.production_settings),
                            ("audit_settings", recipe.audit_settings)):
        for element, paw_name in settings.paw.items():
            potcar = Path(settings.paw_library) / paw_name / "POTCAR"
            if not potcar.is_file():
                problems.append(
                    f"[{block}] no POTCAR for {element} at {potcar}")
    if not os.path.isfile(recipe.reference_data_ref):
        problems.append(
            f"[recipe] reference_data_ref not found: "
            f"{recipe.reference_data_ref}")
    if problems:
        listed = "\n  - ".join(problems)
        raise SpecificationError(
            f"the recipe references {len(problems)} artifact(s) that "
            f"could not be resolved:\n  - {listed}")


def _descriptor_from_table(table: dict, context: str) -> tuple:
    """The ``[descriptor]`` table -> (DescriptorSettings, scatter multiple).

    The cutoff is stated as a PHYSICAL length (converted to angstrom
    here); LAMMPS's own parameters are derived from it by the engine
    adapter, never written in the recipe (ARCHITECTURE §2.3).
    """
    from sabsim.driver.commands import to_metal
    weights = _require(table, "species_weights", context)
    if not isinstance(weights, dict) or not weights:
        raise SpecificationError(
            f"{context} -> species_weights: a non-empty element -> weight "
            f"table")
    multiple = float(_require(table, "gate_scatter_multiple", context))
    if multiple <= 0.0:
        raise SpecificationError(
            f"{context} -> gate_scatter_multiple: must be positive")
    settings = DescriptorSettings(
        first_shell_cutoff=to_metal(
            _require_quantity(table, "first_shell_cutoff", context),
            "distance"),
        expansion_order=_require_int(table, "expansion_order", context),
        species_weights={str(k): float(v) for k, v in weights.items()})
    return settings, multiple


def load_recipe(recipe_path: str | Path) -> ForceModelRecipe:
    """Load and validate a recipe file (phases one and two).

    Phase three — do the referenced files exist — is
    :func:`check_recipe_references`, called by the commands that are
    about to spend on them, exactly as the study loader splits its own
    checks.
    """
    with Path(recipe_path).open("rb") as recipe_file:
        raw = tomllib.load(recipe_file)
    head = _require(raw, "recipe", "top level")
    species = frozenset(
        str(symbol) for symbol in _require(head, "species_union", "[recipe]"))
    if not species:
        raise SpecificationError("[recipe] -> species_union: must not be empty")
    descriptor_settings, gate_scatter_multiple = _descriptor_from_table(
        _require(raw, "descriptor", "top level"), "[descriptor]")
    recipe = ForceModelRecipe(
        name=str(_require(head, "name", "[recipe]")),
        species_union=species,
        domain=str(_require(head, "domain", "[recipe]")),
        reference_data_ref=str(
            _require(head, "reference_data_ref", "[recipe]")),
        generator=_generator_from_table(
            _require(raw, "generator", "top level"), "[generator]"),
        phases=_phases_from_tables(
            _require(raw, "phases", "top level"), "[[phases]]"),
        starting_collection=_collection_from_table(
            _require(raw, "collection1", "top level"), "[collection1]"),
        generation_plan=_plan_from_table(
            _require(raw, "generation_plan", "top level"),
            "[generation_plan]"),
        labelling=LabellingBudget(budget_per_family=_require_int(
            _require(raw, "labelling", "top level"), "budget_per_family",
            "[labelling]")),
        production_settings=_settings_from_table(
            _require(raw, "production_settings", "top level"),
            "[production_settings]"),
        audit_settings=_settings_from_table(
            _require(raw, "audit_settings", "top level"),
            "[audit_settings]"),
        descriptor_settings=descriptor_settings,
        gate_scatter_multiple=gate_scatter_multiple,
    )
    _reject_if_inconsistent(recipe)
    return recipe
