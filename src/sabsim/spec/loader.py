"""Read and validate a SABSIM study spec (PSEUDOCODE.md §2, DESIGN §1.4).

This module is ``load_and_validate_study`` made real. It turns the TOML
file the §1.4 generator emits into the typed records of
:mod:`sabsim.spec.records`, and it enforces the two rules that make the
spec a trustworthy contract between the human and the pipeline:

* **Reject the incomplete spec (DESIGN.md §1.4).** There are NO hidden
  defaults. Every knob must be present in the file; a missing key is an
  error we report, naming exactly what is missing and where, never a
  blank the machinery fills silently. This is enforced by pulling every
  required key explicitly through :func:`_require` — the records have no
  defaults, so nothing can be quietly completed.
* **Reject the un-executable spec (DESIGN.md §1.5).** Validation rejects
  a spec that cannot be RUN — a projectile species outside the
  potential's type map, a missing unit, an unknown press mode — never
  one whose comparisons would merely be hard to interpret. Interpreting
  is the gate's job (DESIGN.md §1.1: report, never restrict).

The mechanism chosen for the §1.8 schema follow-on is plain dataclasses
plus this hand-written validator: transparent, dependency-free, and
readable beside PSEUDOCODE.md §2, which is exactly what a study spec
built on "no hidden defaults" wants.

The on-disk TOML layout (the ``[DEPTH-FIRST] deserialize`` of §2) is
pinned HERE. v1 hoists the shared protocol, numerical, and ensemble
blocks to study level and distributes them to every member, because a
v1 study shares one protocol across its members (DESIGN.md §1.1); the
per-member override is a later-wave extension of this reader.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from sabsim.spec.records import (
    AnnealSchedule,
    EnsembleKnobs,
    MaterialKnobs,
    MemberSpecification,
    NumericalKnobs,
    PotentialSpec,
    ProtocolKnobs,
    Quantity,
    Relation,
    Study,
    WaferPair,
)

# The v1 potential's type map: the elements the {Si, O, Ar} MLIP knows
# (STRUCTURAL 1a made concrete). A projectile species outside this set
# cannot be executed, so the spec is rejected (DESIGN.md §1.5). Material
# COMPOSITION checking (that "SiO2" resolves to known elements) needs a
# formula parser and lands with the structure builder in a later wave.
KNOWN_SPECIES = frozenset({"Si", "O", "Ar"})

# The press modes the driver knows how to run (DESIGN.md §5.2).
KNOWN_PRESS_MODES = frozenset({"load", "displacement"})

# The sentinel a co-species field carries when there is no co-deposit.
# The spec writes it explicitly rather than omitting the key, so the
# "no hidden defaults" rule still holds; the loader maps it to None.
NO_COSPECIES = "none"


class SpecificationError(Exception):
    """A study spec is incomplete or cannot be executed.

    Raised with a message that names WHAT is wrong and WHERE, so the
    person editing the spec can fix it without reading the loader. This
    is the single failure type both rejection rules raise.
    """


# ---------------------------------------------------------------------
# Small helpers that pull required values and enforce completeness.
# Every knob the records need is pulled through one of these, so an
# omission surfaces as a clear SpecificationError, not a raw KeyError.
# ---------------------------------------------------------------------

def _require(table: dict, key: str, context: str) -> object:
    """Return ``table[key]`` or reject the spec if the key is absent.

    ``context`` names the location (e.g. "member 'si-sio2' -> press") so
    the error points the editor straight at the missing knob. This is
    the concrete face of "reject the incomplete spec" (DESIGN.md §1.4).
    """
    if key not in table:
        raise SpecificationError(
            f"{context}: missing required key '{key}'")
    return table[key]


def _require_quantity(table: dict, key: str, context: str) -> Quantity:
    """Pull a required ``{ value, unit }`` inline table as a Quantity.

    A physical value must carry its unit (DESIGN.md §1.5), so a bare
    number, or a table missing ``value`` or ``unit``, is rejected as
    un-executable rather than silently accepted.
    """
    raw = _require(table, key, context)
    where = f"{context} -> {key}"
    if not isinstance(raw, dict):
        raise SpecificationError(
            f"{where}: expected a {{ value, unit }} table, "
            f"got a bare value — physical knobs carry units (§1.5)")
    value = _require(raw, "value", where)
    unit = _require(raw, "unit", where)
    return Quantity(value=float(value), unit=str(unit))


def _require_face(table: dict, key: str, context: str) -> tuple:
    """Pull a Miller-index face as a 3-integer tuple.

    A crystal face is three whole numbers (DESIGN.md §2.2), so anything
    that is not a length-three integer list is rejected here rather than
    surfacing as a confusing error deep in the structure builder.
    """
    raw = _require(table, key, context)
    where = f"{context} -> {key}"
    if not isinstance(raw, list) or len(raw) != 3:
        raise SpecificationError(
            f"{where}: expected three Miller indices, got {raw!r}")
    return tuple(int(component) for component in raw)


# ---------------------------------------------------------------------
# Deserialize: map the on-disk TOML layout onto the §2 records. This is
# where the concrete file shape (short grouped keys) meets the schema
# field names, so the reader can see exactly how one becomes the other.
# ---------------------------------------------------------------------

def _material_from_wafer(table: dict, context: str) -> MaterialKnobs:
    """Build one wafer's MaterialKnobs from its ``[member.wafer_x]``.

    The ``cif`` key names the authoritative structure file (DESIGN.md
    §1.2). The loader keeps it as a string; whether the file EXISTS and
    parses is checked by the structure builder when it opens it, the same
    way material composition against the type map is a later-wave check
    (§1.5) — not something this reader can know from the spec alone.
    """
    return MaterialKnobs(
        identity=str(_require(table, "material", context)),
        cif_source=str(_require(table, "cif", context)),
        crystal_structure=str(_require(table, "structure", context)),
        surface_face=_require_face(table, "face", context),
    )


def _anneal_from_table(table: dict, context: str) -> AnnealSchedule:
    """Build the re-anneal schedule from ``[protocol.reanneal]``."""
    return AnnealSchedule(
        hold_temperature=_require_quantity(
            table, "hold_temperature", context),
        hold_duration=_require_quantity(table, "hold_duration", context),
        ensemble=str(_require(table, "ensemble", context)),
    )


def _protocol_from_tables(protocol: dict, context: str) -> ProtocolKnobs:
    """Assemble ProtocolKnobs from the ``[protocol.*]`` sub-tables.

    The activation, assembly, press, and pull knobs live in separate
    sub-tables on disk for readability; here they are gathered into the
    one ProtocolKnobs record PSEUDOCODE.md §2 defines.
    """
    activation = _require(protocol, "activation", context)
    reanneal = _require(protocol, "reanneal", context)
    assembly = _require(protocol, "assembly", context)
    press = _require(protocol, "press", context)
    pull = _require(protocol, "pull", context)

    act_ctx = f"{context} -> activation"
    press_ctx = f"{context} -> press"

    # A co-species written as the "none" sentinel becomes Python None;
    # any other value is kept as the named co-deposit element.
    cospecies_raw = str(_require(activation, "cospecies", act_ctx))
    cospecies = None if cospecies_raw == NO_COSPECIES else cospecies_raw

    return ProtocolKnobs(
        activation_mechanism=str(_require(
            activation, "mechanism", act_ctx)),
        activation_species=str(_require(activation, "species", act_ctx)),
        activation_cospecies=cospecies,
        activation_cospecies_fraction=float(_require(
            activation, "cospecies_fraction", act_ctx)),
        activation_energy=_require_quantity(activation, "energy", act_ctx),
        activation_angle=_require_quantity(activation, "angle", act_ctx),
        activation_fluence=_require_quantity(
            activation, "fluence", act_ctx),
        cascade_duration=_require_quantity(
            activation, "cascade_duration", act_ctx),
        between_impact_relaxation=_require_quantity(
            activation, "between_impact_relaxation", act_ctx),
        reanneal_schedule=_anneal_from_table(
            reanneal, f"{context} -> reanneal"),
        initial_gap=_require_quantity(
            assembly, "initial_gap", f"{context} -> assembly"),
        press_control=_validate_press_mode(
            str(_require(press, "mode", press_ctx)), press_ctx),
        press_load=_require_quantity(press, "pressure", press_ctx),
        press_depth=_require_quantity(press, "depth", press_ctx),
        press_duration=_require_quantity(press, "duration", press_ctx),
        press_temperature=_require_quantity(
            press, "temperature", press_ctx),
        press_approach_rate=_require_quantity(
            press, "approach_rate", press_ctx),
        separation_speed=_require_quantity(
            pull, "separation_speed", f"{context} -> pull"),
    )


def _numerical_from_table(table: dict, context: str) -> NumericalKnobs:
    """Assemble NumericalKnobs from the ``[numerical]`` block."""
    ladder_raw = _require(table, "pull_rate_ladder", context)
    ladder_ctx = f"{context} -> pull_rate_ladder"
    if not isinstance(ladder_raw, list) or len(ladder_raw) < 1:
        raise SpecificationError(
            f"{ladder_ctx}: expected a list of rate quantities")
    ladder = tuple(
        Quantity(
            value=float(_require(rung, "value", f"{ladder_ctx}[{index}]")),
            unit=str(_require(rung, "unit", f"{ladder_ctx}[{index}]")),
        )
        for index, rung in enumerate(ladder_raw)
    )

    return NumericalKnobs(
        md_timestep=_require_quantity(table, "md_timestep", context),
        cascade_timestep=_require_quantity(
            table, "cascade_timestep", context),
        langevin_damping=_require_quantity(
            table, "langevin_damping", context),
        pull_rate_ladder=ladder,
        force_average_window=_require_quantity(
            table, "force_average_window", context),
        frame_stride=int(_require(table, "frame_stride", context)),
        noise_floor=_require_quantity(table, "noise_floor", context),
        misfit_tolerance=float(_require(
            table, "misfit_tolerance", context)),
        max_coincidence_area=_require_quantity(
            table, "max_coincidence_area", context),
        target_footprint_area=_require_quantity(
            table, "target_footprint_area", context),
        minimum_bulk_thickness=_require_quantity(
            table, "minimum_bulk_thickness", context),
        slab_thickness=_require_quantity(
            table, "slab_thickness", context),
        expected_activated_depth=_require_quantity(
            table, "expected_activated_depth", context),
        slab_vacuum=_require_quantity(table, "slab_vacuum", context),
        bulk_cells_per_axis=int(_require(
            table, "bulk_cells_per_axis", context)),
        clash_floor=_require_quantity(table, "clash_floor", context),
        contact_grid_spacing=_require_quantity(
            table, "contact_grid_spacing", context),
        contact_gap_threshold=_require_quantity(
            table, "contact_gap_threshold", context),
        contact_gap_window=int(_require(
            table, "contact_gap_window", context)),
        contact_stress_floor=_require_quantity(
            table, "contact_stress_floor", context),
        bonded_contact_threshold=float(_require(
            table, "bonded_contact_threshold", context)),
        reference_pe_drift=_require_quantity(
            table, "reference_pe_drift", context),
    )


def _ensemble_from_table(table: dict, context: str) -> EnsembleKnobs:
    """Assemble the two-axis EnsembleKnobs from the ``[ensemble]`` block."""
    return EnsembleKnobs(
        master_seed=int(_require(table, "master_seed", context)),
        amorphization_count=int(_require(
            table, "amorphization_count", context)),
        velocity_count=int(_require(table, "velocity_count", context)),
    )


def _expand_roots(path: str, context: str) -> str:
    """Expand ``$SABSIM_SHARE``-style roots in a weights path.

    A study file may name a model file relative to one of the three
    location roots (ARCHITECTURE.md §4.1) so the same study runs on any
    machine that sources its ``sabsimrc``. A root that is referenced but
    not set in the environment is rejected here, because a path with a
    literal ``$SABSIM_SHARE`` left in it would fail much later, inside
    LAMMPS, with a far less helpful message.
    """
    expanded = os.path.expandvars(path)
    if "$" in expanded:
        raise SpecificationError(
            f"{context}: '{path}' names a location root that is not set "
            f"in the environment; source your sabsimrc first (§4.1)")
    return expanded


def _potential_from_table(table: dict, context: str) -> PotentialSpec:
    """Assemble the study-level PotentialSpec from the ``[potential]`` block.

    Every key is required (no hidden defaults, DESIGN.md §1.4): the
    universal model's pinned name and weights, the production model's
    weights, and the explicit unvalidated opt-in. The weights paths have
    their location roots expanded here so every later consumer sees a
    plain path.
    """
    allow = _require(table, "allow_unvalidated", context)
    if not isinstance(allow, bool):
        raise SpecificationError(
            f"{context} -> allow_unvalidated: expected true or false")
    return PotentialSpec(
        universal_model=str(_require(table, "universal_model", context)),
        universal_weights=_expand_roots(
            str(_require(table, "universal_weights", context)),
            f"{context} -> universal_weights"),
        production_weights=_expand_roots(
            str(_require(table, "production_weights", context)),
            f"{context} -> production_weights"),
        allow_unvalidated=allow,
    )


# ---------------------------------------------------------------------
# The executability checks (DESIGN.md §1.5) — reject a spec that cannot
# be RUN, with a message that says why.
# ---------------------------------------------------------------------

def _validate_press_mode(mode: str, context: str) -> str:
    """Reject a press mode the driver has no way to run (§5.2)."""
    if mode not in KNOWN_PRESS_MODES:
        raise SpecificationError(
            f"{context} -> mode: '{mode}' is not a known press mode "
            f"{sorted(KNOWN_PRESS_MODES)}")
    return mode


def _reject_if_not_executable(
        member: MemberSpecification) -> None:
    """Reject a member the pipeline could not actually run (§1.5).

    Checks the parts that would stop execution: the projectile species
    must live in the potential's type map, and any co-species too.
    Structural checks that need built geometry (material composition
    against the type map, box sizes) belong to later waves and are noted
    where they will land, not silently skipped.
    """
    context = f"member '{member.name}'"
    species = member.protocol.activation_species
    if species not in KNOWN_SPECIES:
        raise SpecificationError(
            f"{context}: activation species '{species}' is outside the "
            f"potential type map {sorted(KNOWN_SPECIES)} (§1.5)")

    cospecies = member.protocol.activation_cospecies
    if cospecies is not None and cospecies not in KNOWN_SPECIES:
        raise SpecificationError(
            f"{context}: co-species '{cospecies}' is outside the "
            f"potential type map {sorted(KNOWN_SPECIES)} (§1.5)")

    if not member.potential_ref:
        raise SpecificationError(
            f"{context}: potential_ref is empty — a member must point "
            f"at a potential generation (§1.3, §1.6)")

    if not member.material_domain:
        raise SpecificationError(
            f"{context}: material_domain is empty — a member must name "
            f"the structural/chemical regime its force model describes, "
            f"because the species alone cannot select one (§4.8)")


# ---------------------------------------------------------------------
# Relation validation — compute what the schema says the validator
# attaches, without ever deleting the relation (report, never restrict).
# ---------------------------------------------------------------------

def _relation_from_table(table: dict, context: str) -> Relation:
    """Build a Relation and attach the checks §2 says are computed here.

    ``confounded`` is set now — a relation with more than one contrast
    confuses its own signal (DESIGN.md §1.1). The full difference set
    (entailed vs incidental) is ``sort_differences``, marked
    ``[DEPTH-FIRST]`` in §2, so it lands with the relation-evaluation
    module; it is left unset here rather than faked.
    """
    contrast = tuple(str(path) for path in _require(
        table, "contrast", context))
    return Relation(
        kind=str(_require(table, "kind", context)),
        members=tuple(str(name) for name in _require(
            table, "members", context)),
        measures=tuple(str(name) for name in _require(
            table, "measures", context)),
        contrast=contrast,
        controls=tuple(str(path) for path in _require(
            table, "controls", context)),
        confounded=(len(contrast) > 1),
    )


def _reject_if_relation_dangling(
        relation: Relation, member_names: set[str]) -> None:
    """Reject a relation that names a member the study does not define.

    A relation over a missing member cannot be computed at all, so this
    is an executability failure (§1.5), distinct from a relation that is
    merely confounded — which stays, and is reported (§1.1).
    """
    for name in relation.members:
        if name not in member_names:
            raise SpecificationError(
                f"relation '{relation.kind}': names member '{name}', "
                f"which the study does not define")


# ---------------------------------------------------------------------
# The public entry point.
# ---------------------------------------------------------------------

def load_and_validate_study(spec_path: str | Path) -> Study:
    """Load a study spec from ``spec_path`` and validate it (§2).

    Reads the TOML file, builds the typed :class:`Study`, and applies
    both rejection rules: incomplete specs fail while their keys are
    pulled, and un-executable specs fail their executability checks.
    Relations are validated but never deleted — even a confounded one is
    computed and reported (DESIGN.md §1.1). Returns the validated Study,
    or raises :class:`SpecificationError` naming the first problem.
    """
    path = Path(spec_path)
    with path.open("rb") as spec_file:
        raw = tomllib.load(spec_file)

    study_table = _require(raw, "study", "top level")
    name = str(_require(study_table, "name", "[study]"))
    description = str(_require(study_table, "description", "[study]"))

    # v1 shares one protocol, numerical, and ensemble block across all
    # members (DESIGN.md §1.1), so they are read once at study level and
    # distributed, as is the [potential] block that names the force
    # models. Material and potential_ref are per member.
    protocol = _protocol_from_tables(
        _require(raw, "protocol", "top level"), "protocol")
    numerical = _numerical_from_table(
        _require(raw, "numerical", "top level"), "[numerical]")
    ensemble = _ensemble_from_table(
        _require(raw, "ensemble", "top level"), "[ensemble]")
    potential = _potential_from_table(
        _require(raw, "potential", "top level"), "[potential]")

    member_tables = _require(raw, "member", "top level")
    members = []
    for member_table in member_tables:
        member_name = str(_require(member_table, "name", "member"))
        context = f"member '{member_name}'"
        member = MemberSpecification(
            name=member_name,
            material=WaferPair(
                wafer_a=_material_from_wafer(
                    _require(member_table, "wafer_a", context),
                    f"{context} -> wafer_a"),
                wafer_b=_material_from_wafer(
                    _require(member_table, "wafer_b", context),
                    f"{context} -> wafer_b"),
            ),
            protocol=protocol,
            numerical=numerical,
            ensemble=ensemble,
            potential_ref=str(_require(
                member_table, "potential_ref", context)),
            material_domain=str(_require(
                member_table, "material_domain", context)),
            potential=potential,
        )
        _reject_if_not_executable(member)
        members.append(member)

    member_names = {member.name for member in members}

    # Relations are OPTIONAL (a study may declare none); read any given.
    relations = []
    for relation_table in raw.get("relation", []):
        relation = _relation_from_table(relation_table, "[[relation]]")
        _reject_if_relation_dangling(relation, member_names)
        relations.append(relation)

    return Study(
        name=name,
        description=description,
        members=tuple(members),
        relations=tuple(relations),
    )
