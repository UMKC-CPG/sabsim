"""Cascade potential resolution — the classical + ZBL generator seam.

DESIGN.md §4.7. The surface-activation cascade (`DESIGN.md` §3,
`PSEUDOCODE.md` §10) runs on a CLASSICAL interatomic potential spliced
with ZBL hard cores, deliberately NOT the production MLIP (STRUCTURAL 1b:
the production model must never see cascade-level distortion or the
projectile species). That classical potential is the one genuinely
per-material piece of an otherwise chemistry-agnostic cascade, so it is
chosen behind a seam: :func:`resolve_cascade_generator` takes the species
present (substrate ∪ projectile) and returns a ready-to-load
:class:`~sabsim.driver.commands.ForceModel` — a ``hybrid/overlay`` of the
config-selected classical form with the two ZBL cores of DESIGN §3.3. The
cascade driver never names a potential; it asks this resolver.

Two design points make this module general rather than silicon-only:

- **The registry carries per-material entries with provenance.** v1
  populates SILICON (Stillinger-Weber) as the one VALIDATED entry, and
  records silica, gallium nitride, and lithium niobate as DOCUMENTED but
  UNTESTED candidates (§4.7). Resolving an unvalidated entry refuses
  loudly rather than running an unproven potential — the same
  no-defaults, gate-not-warn discipline as the rest of the pipeline.
- **Entries are keyed by species AND domain** (§4.8). A species set does
  not identify a material model, because one composition can span
  distinct chemistries — carbon as diamond or graphite, silica from
  alpha-quartz to an amorphous network. {Si, O} is the live case: one
  entry spans a silicon wafer, a silica wafer and the interface between
  them, while the other is better for amorphous silica but cannot
  describe elemental silicon at all. Asked for {Si, O} with no domain,
  the resolver REFUSES rather than picking one.
- **The two ZBL cores are DERIVED from the species set**, never
  hand-enumerated: the projectile-substrate collisions get the
  longer-range core, and every substrate-substrate pair gets the short
  core that switches off below the bond length (`PSEUDOCODE.md` §10.3).
  A new material or projectile needs no code change — only a registry
  entry — which is why prior art's argon-only enumeration is not repeated
  here (`PRIOR_ART.md` §1.9).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ase.data import atomic_numbers

from sabsim.driver.commands import ForceModel, _lammps_number

# The ZBL switching distances (Å) — where each core turns on (inner) and
# has faded to zero (outer). These are DOCUMENTED STAND-INS, not converged
# physics: the LONG core covers projectile-substrate collisions and the
# SHORT core gives every substrate-substrate pair a hard wall that must
# switch off well BELOW the bond length (~1.6 Å for Si) so normal bonding
# is untouched (DESIGN §3.3, §4.7; the values follow prior art's working
# cascade, `PRIOR_ART.md` §1.9). Pinning them is a §4.7 DESIGN follow-on.
_LONG_CORE_INNER_STANDIN = 0.5      # Å: projectile-substrate ZBL turns on
_LONG_CORE_OUTER_STANDIN = 2.0      # Å: projectile-substrate ZBL faded out
_SHORT_CORE_INNER_STANDIN = 0.5     # Å: substrate-substrate ZBL turns on
_SHORT_CORE_OUTER_STANDIN = 1.2     # Å: below the bond, so bonding is kept

# Which ``hybrid/overlay`` sub-style index names each ZBL core. LAMMPS
# disambiguates a repeated sub-style by a trailing 1..M index in the
# ``pair_coeff`` line; the long core is listed first, the short second.
_LONG_CORE_INDEX = 1
_SHORT_CORE_INDEX = 2


@dataclass(frozen=True)
class CascadeGeneratorEntry:
    """One material's classical cascade potential, with provenance (§4.7).

    A registry row. It names the classical form (``pair_style`` plus its
    parameter file), the literature source for those parameters, and the
    equilibrium lattice that form produces — the latter needed both by the
    §4.7 acceptance check (a large disagreement with the MLIP-relaxed
    lattice is the step-zero-stress artifact of `PRIOR_ART.md` §1.6) and
    by the structure builder's lattice matching (`DESIGN.md` §2.2). The
    ``caveat`` field carries per-form hazards, and ``validated`` records
    whether this entry has actually cleared the §3.5 activation gate — v1
    validates SILICON only; the others are documented starting points, not
    decisions.

    ``domain`` names the structural and chemical regime the entry claims
    to cover, and it is half the registry key (`DESIGN.md` §4.8). The
    species set alone is not enough to identify a material model: the
    same composition can span genuinely different chemistries — carbon as
    diamond or as graphite, the boron allotropes, silica running from
    alpha-quartz through cristobalite to an amorphous network — and a
    form fit to one regime is not merely untested in another, it is
    confidently wrong there. Silicon-and-oxygen is the case that forced
    this field: two legitimate entries cover {Si, O} and differ entirely
    in what they can describe.
    """

    substrate_species: frozenset       # the species this entry covers
    domain: str                        # the structural/chemical regime
    classical_style: str               # LAMMPS pair_style, e.g. "sw"
    classical_param_file: str          # parameter file, e.g. "Si.sw"
    source: str                        # literature provenance
    equilibrium_lattice_angstrom: float | None   # this form's lattice
    caveat: str                        # per-form hazards (empty if none)
    validated: bool                    # has it cleared the §3.5 gate?


# The per-material registry (DESIGN §4.7, §4.8). v1 populates SILICON
# only; the other named materials are DOCUMENTED but UNTESTED candidates —
# their presence gives a future contributor a sourced starting point, and
# the ``validated=False`` flag makes the resolver refuse to run them until
# someone confirms them against the §3.5 gate.
#
# Keyed by ``(substrate species, domain)`` — the frozen set of SUBSTRATE
# species (the projectile is never part of the key) TOGETHER WITH the
# structural/chemical regime. The domain half is not decoration: {Si, O}
# carries two entries that describe different physics, and before §4.8
# named the concept they were kept apart by smuggling a fake element
# ``"_silica_only"`` into a set that is otherwise chemical symbols. That
# marker was unreachable from any real cell, so the silica form could
# never actually be selected — a safety property by accident rather than
# by design. The domain makes it selectable AND explicit.
CASCADE_GENERATOR_REGISTRY: dict = {
    (frozenset({"Si"}), "diamond-cubic"): CascadeGeneratorEntry(
        substrate_species=frozenset({"Si"}),
        domain="diamond-cubic",
        classical_style="sw",
        classical_param_file="Si.sw",
        source="Stillinger & Weber, Phys. Rev. B 31, 5262 (1985); "
               "Si.sw ships with LAMMPS. One silicon model spans the "
               "whole pipeline (press/pull uses the same, 2026-07-17).",
        equilibrium_lattice_angstrom=5.4309,   # matches the SW bulk relax
        caveat="",
        validated=True),
    # Silicon + oxygen. This one entry has to serve THREE regimes at
    # once — a crystalline silicon wafer, a silica wafer, and the Si/SiO2
    # interface between them — because the `si-sio2` member puts silicon
    # on one side and silica on the other, in ONE box. That requirement
    # is what selects the form. The Vashishta silica model (registered
    # below as the silica-only alternative) fails it outright: there,
    # silicon carries a formal +1.6e charge and its Si-Si three-body
    # strength is zero, so two silicons REPEL and no silicon crystal can
    # exist. The Munetoh Tersoff instead reduces to the standard Tersoff
    # silicon parameterization for Si-Si while carrying real Si-O and
    # O-O terms, and being charge-free it needs no Coulomb solver (which
    # matches the charge-free data files of DESIGN §2.6) and splices
    # cleanly onto the ZBL cores below.
    (frozenset({"Si", "O"}),
     "silicon-and-silica"): CascadeGeneratorEntry(
        substrate_species=frozenset({"Si", "O"}),
        domain="silicon-and-silica",
        classical_style="tersoff",
        classical_param_file="SiO.tersoff",
        source="Munetoh, Motooka, Moriguchi & Shintani, Comput. Mater. "
               "Sci. 39, 334 (2007) — a Tersoff form covering Si-Si, "
               "Si-O and O-O, so ONE file spans a silicon wafer, a "
               "silica wafer, and the interface between them. Shipped "
               "at share/potentials/SiO.tersoff (Laino 2010 conversion "
               "as distributed with LAMMPS).",
        equilibrium_lattice_angstrom=None,     # to be measured on adoption
        caveat="Charge-free and bond-order, so it splices onto the ZBL "
               "cores without double-counting a Coulomb term — but it "
               "has NOT cleared the §3.5 activation gate here and its "
               "equilibrium lattice is unmeasured. Its silica is less "
               "well validated than Vashishta's; if amorphous-silica "
               "structure disappoints, compare against that entry.",
        validated=False),
    # Silica ALONE — better validated for amorphous SiO2 than the
    # Tersoff above (it is fit to the alpha-quartz energy-volume curve),
    # but usable ONLY when every silicon is oxygen-coordinated. It shares
    # the {Si, O} species set with the entry above and is told apart by
    # its DOMAIN, which is the honest expression of the constraint the
    # old ``_silica_only`` marker was faking. Because two entries now
    # share a species set, {Si, O} can no longer be resolved without
    # naming a domain — the resolver refuses to guess between two forms
    # that disagree about whether elemental silicon can exist at all.
    (frozenset({"Si", "O"}), "silica-only"): CascadeGeneratorEntry(
        substrate_species=frozenset({"Si", "O"}),
        domain="silica-only",
        classical_style="vashishta",
        classical_param_file="SiO.1990.vashishta",
        source="Vashishta, Kalia, Rino & Ebbsjo, Phys. Rev. B 41, 12197 "
               "(1990) — the standard amorphous-silica model. Shipped "
               "at share/potentials/SiO.1990.vashishta.",
        equilibrium_lattice_angstrom=None,
        caveat="Documented, untested, and SILICA-ONLY. Silicon carries a "
               "formal +1.6e charge with zero Si-Si three-body strength, "
               "so two silicon atoms repel: this form CANNOT describe "
               "elemental silicon and must never be used for a member "
               "with a silicon wafer. It also carries its own screened "
               "Coulomb and steric wall, so a ZBL overlay double-counts "
               "the short-range repulsion — resplice before adopting.",
        validated=False),
    (frozenset({"Ga", "N"}), "wurtzite"): CascadeGeneratorEntry(
        substrate_species=frozenset({"Ga", "N"}),
        domain="wurtzite",
        classical_style="tersoff",
        classical_param_file="GaN.tersoff",
        source="Nord, Albe, Erhart & Nordlund, J. Phys.: Condens. Matter "
               "15, 5649 (2003) — a bond-order GaN form parameterized "
               "WITH a ZBL splice for radiation damage (the ideal kind).",
        equilibrium_lattice_angstrom=None,
        caveat="Documented, untested. The published form already reasons "
               "the ZBL hard core — reuse its channels when adopting.",
        validated=False),
    (frozenset({"Li", "Nb", "O"}),
     "trigonal-ferroelectric"): CascadeGeneratorEntry(
        substrate_species=frozenset({"Li", "Nb", "O"}),
        domain="trigonal-ferroelectric",
        classical_style="buck/coul/long",
        classical_param_file="LiNbO3.buck",
        source="Shell-model Buckingham (e.g. Jackson & Valerio) OR a "
               "reduced-charge bond-valence Morse form; see "
               "`PRIOR_ART.md` §1.9.",
        equilibrium_lattice_angstrom=None,
        caveat="Documented, untested — the hard case. A RIGID-ion "
               "Buckingham runs to -inf under bombardment (the Buckingham "
               "catastrophe); use a shell-model or reduced-charge "
               "bond-valence Morse form, or fall to the Tier-2 foundation "
               "MLIP (§4.7). Shell models add per-step shell relaxation.",
        validated=False),
}


def registered_material_domains() -> list:
    """Human-readable list of the (species, domain) pairs registered.

    Used to build a helpful error when a resolve misses — so the message
    names what IS available rather than only what was asked for. Each
    entry reads like ``{O, Si} [silica-only]``.
    """
    return sorted(
        "{" + ", ".join(sorted(species)) + "} [" + domain + "]"
        for species, domain in CASCADE_GENERATOR_REGISTRY)


def domains_for_species(substrate) -> list:
    """Every domain registered for one substrate species set.

    The species set is what a cell can tell us on its own — it falls out
    of the type map. The domain cannot be inferred that way, so this is
    what lets a caller discover the legitimate choices, and what the
    ambiguity refusal below lists when it declines to guess.
    """
    substrate = frozenset(substrate)
    return sorted(
        domain
        for species, domain in CASCADE_GENERATOR_REGISTRY
        if species == substrate)


def _resolve_registry_entry(
        substrate: frozenset,
        domain: str | None,
        allow_unvalidated: bool,
        purpose: str) -> CascadeGeneratorEntry:
    """Look one entry up by species and domain, refusing rather than guessing.

    Shared by both public resolvers so the cascade form and the quiet
    form are selected by exactly one rule (DESIGN §4.7, §4.8). Three
    refusals, each naming what the caller could do instead:

    - **No entry for these species at all** — :class:`KeyError` listing
      every registered (species, domain) pair.
    - **Species registered under SEVERAL domains, and no domain named** —
      :class:`KeyError` listing the candidates. This is the refusal the
      old ``_silica_only`` marker existed to fake. Two forms covering
      {Si, O} disagree about whether elemental silicon can exist, so
      picking one by position or by luck would be a silent physics
      decision; the caller must say which regime it means.
    - **Entry found but not yet gate-cleared** —
      :class:`NotImplementedError` carrying the entry's own caveat,
      unless ``allow_unvalidated`` is the deliberate EXPLORATORY opt-in.

    When a species set has exactly ONE registered domain, omitting the
    domain resolves to it. That is not a default in the sense §4.8's
    no-hidden-defaults rule forbids — there is nothing to choose between,
    so nothing is being guessed on the caller's behalf.

    ``purpose`` names the caller in the message ("cascade generator" or
    "interatomic potential") so a failure says which stage wanted what.
    """
    wanted = "{" + ", ".join(sorted(substrate)) + "}"
    available = domains_for_species(substrate)

    if not available:
        have = ", ".join(registered_material_domains())
        raise KeyError(
            f"no {purpose} registered for substrate {wanted}; registered "
            f"materials are: {have}. Add a CascadeGeneratorEntry "
            f"(DESIGN §4.7) before running this material.")

    if domain is None:
        if len(available) > 1:
            raise KeyError(
                f"substrate {wanted} is registered under more than one "
                f"domain — {', '.join(available)} — so the {purpose} "
                f"cannot be chosen from the species alone (DESIGN §4.8). "
                f"These entries describe different physics and are not "
                f"interchangeable; name the domain explicitly.")
        domain = available[0]

    entry = CASCADE_GENERATOR_REGISTRY.get((substrate, domain))
    if entry is None:
        raise KeyError(
            f"no {purpose} registered for substrate {wanted} in domain "
            f"'{domain}'; registered domains for these species are: "
            f"{', '.join(available)}.")

    if not entry.validated and not allow_unvalidated:
        raise NotImplementedError(
            f"the {purpose} for substrate {wanted} in domain "
            f"'{entry.domain}' is a DOCUMENTED but UNTESTED candidate "
            f"(DESIGN §4.7): {entry.caveat} Validate it against the §3.5 "
            f"activation gate, then set validated=True. To run it "
            f"deliberately as EXPLORATORY work — whose results are "
            f"provisional and must be reported as such — pass "
            f"allow_unvalidated=True.")

    return entry


# Where a shipped parameter file lives relative to the repository root.
# Forms that ship WITH LAMMPS (``Si.sw``) are found by LAMMPS itself, so
# a bare name is left alone; forms we vendor ourselves must be handed to
# LAMMPS as a path it can actually open, whatever the working directory.
_SHIPPED_POTENTIAL_DIRECTORY = "share/potentials"


def resolve_parameter_file(param_file: str) -> str:
    """Turn a registry parameter-file name into something LAMMPS opens.

    A ``pair_coeff`` line names its parameter file, and LAMMPS resolves
    that name against its own potentials directory and the working
    directory — neither of which is where WE keep vendored forms. Since
    ``sabsim run`` makes the JOB directory the working directory, a bare
    ``SiO.tersoff`` would point nowhere.

    So: if the named file is one we ship under ``share/potentials``, hand
    back its ABSOLUTE path; otherwise return the name untouched, which is
    the right answer for the forms that ship with LAMMPS (``Si.sw``).
    The search mirrors the crystal-file resolver in the live stages —
    working directory first, then the repository root inferred from this
    module's own location, so an installed package works too.
    """
    if Path(param_file).is_absolute():
        return param_file

    # The repository root is four parents up from this module:
    # src/sabsim/driver/cascade_potential.py -> repo root.
    repository_root = Path(__file__).resolve().parents[3]
    candidates = (
        Path.cwd() / _SHIPPED_POTENTIAL_DIRECTORY / param_file,
        repository_root / _SHIPPED_POTENTIAL_DIRECTORY / param_file,
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    # Not one of ours — let LAMMPS resolve it from its own distribution.
    return param_file


def resolve_cascade_generator(
        type_map: dict,
        projectile_species,
        long_core: tuple = (_LONG_CORE_INNER_STANDIN,
                            _LONG_CORE_OUTER_STANDIN),
        short_core: tuple = (_SHORT_CORE_INNER_STANDIN,
                            _SHORT_CORE_OUTER_STANDIN),
        allow_unvalidated: bool = False,
        domain: str | None = None) -> ForceModel:
    """Assemble the classical + two-ZBL cascade potential (§4.7, §10.2/3).

    ``type_map`` maps every element symbol present in the cascade cell —
    substrate AND projectile — to its LAMMPS type id (the projectile type
    must already be declared so the cascade can create those atoms). The
    substrate species are inferred as ``type_map`` minus
    ``projectile_species``, and the registry is looked up by that
    substrate set.

    ``domain`` names the structural/chemical regime (DESIGN §4.8) and is
    the other half of the registry key. It may be omitted when the
    substrate species carry exactly one registered domain, which covers
    every material in v1 except silicon-and-oxygen.

    The refusals that keep the pipeline honest all live in
    :func:`_resolve_registry_entry` (DESIGN §4.7, §4.8): unregistered
    species, species registered under several domains with none named,
    and a documented-but-untested entry run without the deliberate
    ``allow_unvalidated`` opt-in.

    ``allow_unvalidated`` is the deliberate escape hatch for EXPLORATORY
    work — the first run of a new material, whose whole purpose is to
    produce the evidence the §3.5 gate would judge. It is a caller-side
    decision, never a default, and it exists so that bringing up a new
    material does not tempt anyone to edit ``validated=True`` in the
    registry before the evidence exists. Anything it returns is a
    PROVISIONAL result and must be reported as such; the registry flag
    stays ``False`` until the gate is genuinely cleared.

    On success it returns a :class:`~sabsim.driver.commands.ForceModel`
    the driver emits through ``force_model_commands`` unchanged — the
    classical form provides the bonding, ZBL core #1 (longer range) the
    projectile-substrate collisions, and ZBL core #2 (short) a hard wall
    on every substrate-substrate pair (DESIGN §3.3).
    """
    projectile = frozenset(projectile_species)
    substrate = frozenset(type_map) - projectile
    entry = _resolve_registry_entry(
        substrate, domain, allow_unvalidated, "cascade generator")

    return _assemble_hybrid_overlay(
        entry, type_map, projectile, long_core, short_core)


def classical_force_model(
        type_map: dict,
        substrate,
        allow_unvalidated: bool = False,
        domain: str | None = None) -> ForceModel:
    """The plain classical potential — no ZBL — for the QUIET stages.

    The cascade needs ZBL hard cores because it drives atoms together at
    keV-scale energies. Every other stage — the gentle re-anneal after
    the cascade, the press, the settle, the pull — runs at ordinary
    temperatures where no pair ever approaches the ZBL regime, so those
    stages want the classical form ALONE (DESIGN §4.5).

    This resolves that form from the SAME registry the cascade uses, so a
    material is described in exactly one place. Previously the re-anneal
    and press/pull stages each hard-coded ``sw Si.sw``, which silently
    assumed silicon everywhere.

    ``substrate`` names the species that carry real bonding. Any declared
    type outside it — a projectile type still declared after its atoms
    were deleted — is passed to the classical form as ``NULL``. LAMMPS
    then insists every declared type PAIR be set even when one of them
    has no atoms left, so whenever a ``NULL`` appears a no-op ``zero``
    sub-style is overlaid to satisfy exactly those dead pairs while the
    classical form does all the real physics. With no ``NULL`` at all the
    overlay is pointless, so the plain style is emitted instead.

    ``domain`` selects among several forms registered for the same
    species (DESIGN §4.8); it may be omitted when only one is registered.
    The quiet stages must resolve the SAME entry the cascade did, or a
    surface would be annealed under one description of the material and
    pressed under another — so whatever domain the cascade was given,
    this must be given too.
    """
    substrate = frozenset(substrate)
    entry = _resolve_registry_entry(
        substrate, domain, allow_unvalidated, "interatomic potential")

    # Element labels in LAMMPS type-id order, NULL for any non-substrate.
    symbols_in_order = sorted(type_map, key=lambda symbol: type_map[symbol])
    labels = " ".join(
        symbol if symbol in substrate else "NULL"
        for symbol in symbols_in_order)

    param_file = resolve_parameter_file(entry.classical_param_file)
    classical_coeff = f"* * {entry.classical_style} {param_file} {labels}"

    if "NULL" not in labels:
        # Every declared type bonds; no dead pairs to satisfy.
        return ForceModel(
            pair_style=entry.classical_style,
            pair_coeff=(f"* * {param_file} {labels}",))

    return ForceModel(
        pair_style=f"hybrid/overlay {entry.classical_style} zero 1.0",
        pair_coeff=(classical_coeff, "* * zero"))


def _assemble_hybrid_overlay(
        entry: CascadeGeneratorEntry,
        type_map: dict,
        projectile: frozenset,
        long_core: tuple,
        short_core: tuple) -> ForceModel:
    """Build the ``hybrid/overlay`` ForceModel from a validated entry.

    The classical sub-style bonds only the substrate atoms — each
    projectile type is passed to it as ``NULL`` so the classical form
    ignores the projectile (which interacts purely through ZBL, the
    neutral-projectile choice of DESIGN §3.2). Every element pair then
    gets exactly one ZBL core: the long one (#1) if the pair involves the
    projectile, the short one (#2) if it is substrate-substrate. The ZBL
    ``pair_coeff`` carries the two atomic numbers, looked up from the
    element symbols so ANY element works without a hand-maintained table.
    """
    long_inner, long_outer = long_core
    short_inner, short_outer = short_core

    # Element symbols in LAMMPS type-id order (1, 2, ...).
    symbols_in_order = sorted(type_map, key=lambda symbol: type_map[symbol])

    # The classical pair_coeff: each type's element label, or NULL for a
    # projectile type the classical form must not see.
    classical_labels = " ".join(
        "NULL" if symbol in projectile else symbol
        for symbol in symbols_in_order)
    classical_coeff = (
        f"* * {entry.classical_style} "
        f"{resolve_parameter_file(entry.classical_param_file)} "
        f"{classical_labels}")

    pair_style = (
        f"hybrid/overlay {entry.classical_style} "
        f"zbl {_lammps_number(long_inner)} {_lammps_number(long_outer)} "
        f"zbl {_lammps_number(short_inner)} {_lammps_number(short_outer)}")

    pair_coeff = [classical_coeff]

    # One ZBL pair_coeff per element pair (upper triangle in type id), the
    # core chosen by whether the projectile is involved.
    for first_symbol in symbols_in_order:
        for second_symbol in symbols_in_order:
            first_id = type_map[first_symbol]
            second_id = type_map[second_symbol]
            if first_id > second_id:
                continue                       # upper triangle only
            involves_projectile = (
                first_symbol in projectile or second_symbol in projectile)
            core_index = (
                _LONG_CORE_INDEX if involves_projectile
                else _SHORT_CORE_INDEX)
            first_z = atomic_numbers[first_symbol]
            second_z = atomic_numbers[second_symbol]
            pair_coeff.append(
                f"{first_id} {second_id} zbl {core_index} "
                f"{_lammps_number(float(first_z))} "
                f"{_lammps_number(float(second_z))}")

    return ForceModel(pair_style=pair_style, pair_coeff=tuple(pair_coeff))
