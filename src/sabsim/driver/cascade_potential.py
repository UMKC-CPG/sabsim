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
    """

    substrate_species: frozenset       # the species this entry covers
    classical_style: str               # LAMMPS pair_style, e.g. "sw"
    classical_param_file: str          # parameter file, e.g. "Si.sw"
    source: str                        # literature provenance
    equilibrium_lattice_angstrom: float | None   # this form's lattice
    caveat: str                        # per-form hazards (empty if none)
    validated: bool                    # has it cleared the §3.5 gate?


# The per-material registry (DESIGN §4.7). v1 populates SILICON only; the
# other three named materials are DOCUMENTED but UNTESTED candidates —
# their presence gives a future contributor a sourced starting point, and
# the ``validated=False`` flag makes the resolver refuse to run them until
# someone confirms them against the §3.5 gate. Keyed by the frozen set of
# SUBSTRATE species (the projectile is not part of the key).
CASCADE_GENERATOR_REGISTRY: dict = {
    frozenset({"Si"}): CascadeGeneratorEntry(
        substrate_species=frozenset({"Si"}),
        classical_style="sw",
        classical_param_file="Si.sw",
        source="Stillinger & Weber, Phys. Rev. B 31, 5262 (1985); "
               "Si.sw ships with LAMMPS. One silicon model spans the "
               "whole pipeline (press/pull uses the same, 2026-07-17).",
        equilibrium_lattice_angstrom=5.4309,   # matches the SW bulk relax
        caveat="",
        validated=True),
    frozenset({"Si", "O"}): CascadeGeneratorEntry(
        substrate_species=frozenset({"Si", "O"}),
        classical_style="vashishta",
        classical_param_file="SiO2.vashishta",
        source="Vashishta et al., Phys. Rev. B 41, 12197 (1990) — built "
               "for amorphous silica; a Munetoh-style Tersoff (Comput. "
               "Mater. Sci. 39, 334, 2007) is the fallback form.",
        equilibrium_lattice_angstrom=None,     # to be measured on adoption
        caveat="Documented, untested. BKS is usable ONLY with a repulsive "
               "splice — its -C/r^6 diverges to -inf at short range.",
        validated=False),
    frozenset({"Ga", "N"}): CascadeGeneratorEntry(
        substrate_species=frozenset({"Ga", "N"}),
        classical_style="tersoff",
        classical_param_file="GaN.tersoff",
        source="Nord, Albe, Erhart & Nordlund, J. Phys.: Condens. Matter "
               "15, 5649 (2003) — a bond-order GaN form parameterized "
               "WITH a ZBL splice for radiation damage (the ideal kind).",
        equilibrium_lattice_angstrom=None,
        caveat="Documented, untested. The published form already reasons "
               "the ZBL hard core — reuse its channels when adopting.",
        validated=False),
    frozenset({"Li", "Nb", "O"}): CascadeGeneratorEntry(
        substrate_species=frozenset({"Li", "Nb", "O"}),
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


def registered_substrate_sets() -> list:
    """Human-readable list of the substrate sets the registry covers.

    Used to build a helpful error when a resolve misses — so the message
    names what IS available rather than only what was asked for.
    """
    return sorted(
        "{" + ", ".join(sorted(species)) + "}"
        for species in CASCADE_GENERATOR_REGISTRY)


def resolve_cascade_generator(
        type_map: dict,
        projectile_species,
        long_core: tuple = (_LONG_CORE_INNER_STANDIN,
                            _LONG_CORE_OUTER_STANDIN),
        short_core: tuple = (_SHORT_CORE_INNER_STANDIN,
                            _SHORT_CORE_OUTER_STANDIN)) -> ForceModel:
    """Assemble the classical + two-ZBL cascade potential (§4.7, §10.2/3).

    ``type_map`` maps every element symbol present in the cascade cell —
    substrate AND projectile — to its LAMMPS type id (the projectile type
    must already be declared so the cascade can create those atoms). The
    substrate species are inferred as ``type_map`` minus
    ``projectile_species``, and the registry is looked up by that
    substrate set.

    Two refusals keep the pipeline honest (DESIGN §4.7):

    - a substrate set with no registry entry raises :class:`KeyError`,
      naming the sets that ARE registered;
    - a registry entry that is documented-but-untested
      (``validated=False``) raises :class:`NotImplementedError`, carrying
      its own caveat, rather than silently running an unproven potential.

    On success it returns a :class:`~sabsim.driver.commands.ForceModel`
    the driver emits through ``force_model_commands`` unchanged — the
    classical form provides the bonding, ZBL core #1 (longer range) the
    projectile-substrate collisions, and ZBL core #2 (short) a hard wall
    on every substrate-substrate pair (DESIGN §3.3).
    """
    projectile = frozenset(projectile_species)
    substrate = frozenset(type_map) - projectile
    entry = CASCADE_GENERATOR_REGISTRY.get(substrate)

    if entry is None:
        wanted = "{" + ", ".join(sorted(substrate)) + "}"
        have = ", ".join(registered_substrate_sets())
        raise KeyError(
            f"no cascade generator registered for substrate {wanted}; "
            f"registered substrate sets are: {have}. Add a "
            f"CascadeGeneratorEntry (DESIGN §4.7) before activating this "
            f"material.")

    if not entry.validated:
        raise NotImplementedError(
            f"the cascade generator for substrate "
            f"{{{', '.join(sorted(substrate))}}} is a DOCUMENTED but "
            f"UNTESTED candidate (DESIGN §4.7): {entry.caveat} Validate it "
            f"against the §3.5 activation gate, then set validated=True.")

    return _assemble_hybrid_overlay(
        entry, type_map, projectile, long_core, short_core)


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
        f"* * {entry.classical_style} {entry.classical_param_file} "
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
