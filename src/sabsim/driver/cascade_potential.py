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

import os
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


# The environment variable that names the universal cascade model's ON-DISK
# weights. The registry entry below PINS the model's identity (name, branch,
# version) for reproducibility, but the weights themselves are a large
# deploy-time artifact (tens of MB) rather than a checked-in file, so the
# path is supplied at run time here — the same override-by-environment
# discipline the bespoke committee model uses (``SABSIM_DEEPMD_MODEL``).
#
# The artifact is a PyTorch ``.pth``, which LAMMPS loads directly through
# ``pair_style deepmd`` and which is NOT tied to a GPU architecture: the
# same file runs on V100, A100 and H100 alike. An AOT-compiled ``.pt2`` is
# roughly 2.5x faster per step but IS architecture-locked and must be
# rebuilt per GPU type, so it is an optional deploy-time optimisation, not
# the contract (DESIGN §4.7).
_UNIVERSAL_MODEL_PATH_VARIABLE = "SABSIM_CASCADE_MLIP_MODEL"


@dataclass(frozen=True)
class UniversalCascadeModel:
    """The universal foundation MLIP used as the DEFAULT cascade potential.

    Unlike a per-material :class:`CascadeGeneratorEntry`, a universal model
    is chemistry-agnostic — one already-trained foundation network covers
    the whole periodic table with no per-material fitting — so it carries NO
    species key and serves every material behind the same resolver seam
    (DESIGN §4.7). It is the DESIGN default: the cascade only ever needs a
    scaffold-grade potential to land the surface in a reasonable amorphous
    basin, and a foundation model gives that for free across all species,
    dissolving the per-material potential search entirely.

    What a universal entry must pin INSTEAD of a species key is the exact
    model IDENTITY. A foundation network shifts between upstream releases,
    so reproducibility depends on recording the model ``name``, the
    multitask ``model_branch`` frozen out of it, and a ``version`` tag — the
    universal analogue of a classical form's frozen parameter-file citation
    (DESIGN §4.7, "a universal entry pins the model version").

    ``validated`` follows the SAME gate-not-warn discipline as the classical
    registry: it stays ``False`` until a full activation under this model has
    cleared the §3.5 gate on a real material, and until then the resolver
    refuses unless the run opts in with ``SABSIM_ALLOW_UNVALIDATED_POTENTIAL``
    — the on-the-record path §4.7 defines for bringing up any new material.
    """

    name: str                 # e.g. "DPA-3.1-3M"
    model_branch: str         # the multitask fitting branch frozen out
    version: str              # upstream release / provenance tag
    source: str               # literature / repository provenance
    caveat: str               # per-model hazards
    validated: bool           # has it cleared the §3.5 activation gate?


# The universal cascade model: DPA-3.1-3M (adopted 2026-08-25, replacing
# DPA-2.4-7M). The change is a PHYSICS correction, not a performance one.
# The Tier-0 inherent-structure screen — minimize a pristine crystal and a
# damaged configuration under the candidate, and require the crystal to sit
# LOWER — is a hard gate, and DPA-2.4-7M FAILS it on silicon: it ranks the
# damaged slab 0.378 eV/atom BELOW the perfect crystal, so under that model
# a silicon surface has a thermodynamic incentive to destroy itself, and an
# activation run self-heats rather than amorphizing (LEDGER T-21, job
# 16731025). DPA-3.1-3M PASSES the same screen at +0.361 eV/atom.
#
# The earlier reason for preferring DPA-2.4-7M was an ENGINEERING one — it
# exported cleanly to AOTInductor ``.pt2`` while DPA-3.1-3M hit an unbacked-
# symint export failure — and that reason no longer binds: LAMMPS loads the
# PyTorch ``.pth`` DIRECTLY, with energy conserved (4e-6 drift over 100 NVE
# steps), so no export is needed at all. The ``.pth`` route is also PORTABLE
# where ``.pt2`` is architecture-locked, which unpins the cascade from any
# one GPU type. Speed is the only thing given up (~2.5x per step); the
# export patch is documented in dev/notes/mlip-cascade-integration.md
# should it ever be worth reclaiming.
UNIVERSAL_CASCADE_MODEL = UniversalCascadeModel(
    name="DPA-3.1-3M",
    model_branch="MP_traj_v024_alldata_mixu",
    version="deepmodelingcommunity/DPA-3.1-3M (CC-BY-4.0); the broad "
            "Materials-Project branch frozen to a singletask .pth, run "
            "under deepmd-kit 3.1.x",
    source="DPA-3 universal foundation model, trained multitask on the "
           "OpenLAM datasets and covering the full periodic table. "
           "HuggingFace deepmodelingcommunity/DPA-3.1-3M.",
    caveat="Universal foundation MLIP: OUT-OF-DISTRIBUTION deep in the "
           "repulsive regime the cascade visits, so it is spliced with the "
           "two ZBL cores and treated as scaffold-grade (DESIGN §4.7), never "
           "trusted there. It PASSES the Tier-0 inherent-structure screen on "
           "silicon (+0.361 eV/atom, crystal below damaged) where DPA-2.4-7M "
           "failed, but Tier-0 is per material AND per model — no oxide has "
           "been screened, and passing Tier-0 is a floor, not a validation. "
           "It has NOT yet cleared the §3.5 activation gate on any material, "
           "so validated stays False: a default cascade refuses unless the "
           "run sets SABSIM_ALLOW_UNVALIDATED_POTENTIAL, and results obtained "
           "that way are EXPLORATORY. The weights are a portable PyTorch "
           ".pth; its path is given via SABSIM_CASCADE_MLIP_MODEL.",
    validated=False)


def resolve_universal_model_path(
        model: UniversalCascadeModel = UNIVERSAL_CASCADE_MODEL) -> str:
    """Resolve the on-disk weights for the universal cascade model.

    The registry pins the model IDENTITY (name/branch/version); the weights
    themselves are a large deploy-time artifact rather than a checked-in
    file, so their path is supplied at run time via the
    ``SABSIM_CASCADE_MLIP_MODEL`` environment variable. The expected form is
    a portable PyTorch ``.pth``, which ``pair_style deepmd`` loads directly
    on any GPU; an architecture-specific AOT ``.pt2`` also works and is
    faster, but must be rebuilt per GPU type. A missing path is a LOUD
    failure naming the variable and the model — the same no-hidden-defaults
    discipline as the rest of the pipeline, so a cascade never silently runs
    under the wrong (or no) model.
    """
    model_path = os.environ.get(_UNIVERSAL_MODEL_PATH_VARIABLE)
    if not model_path:
        raise RuntimeError(
            f"the universal cascade model '{model.name}' needs its "
            f"weights, but {_UNIVERSAL_MODEL_PATH_VARIABLE} is unset. The "
            f"weights are a deploy-time artifact, not a checked-in file "
            f"(DESIGN §4.7), so point the variable at this model's .pth (or "
            f"an architecture-matched .pt2), or request a classical "
            f"potential explicitly.")
    return model_path


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
        domain: str | None = None,
        use_classical: bool = False) -> ForceModel:
    """Assemble the cascade potential — universal by default (§4.7, §10.2/3).

    ``type_map`` maps every element symbol present in the cascade cell —
    substrate AND projectile — to its LAMMPS type id (the projectile type
    must already be declared so the cascade can create those atoms). The
    substrate species are inferred as ``type_map`` minus
    ``projectile_species``.

    **Universal-first (DESIGN §4.7).** By default the cascade runs on the
    chemistry-agnostic universal foundation MLIP
    (:data:`UNIVERSAL_CASCADE_MODEL`) spliced with the two ZBL cores — it
    needs no per-material work and covers every species, so it is the
    default for ALL materials, silicon included. A CLASSICAL form is used
    only on explicit request (``use_classical=True``), which is why silicon
    no longer silently resolves to Stillinger-Weber: the validated classical
    silicon path is opt-in, the universal path is the default (§4.7,
    "universal by default, classical by choice").

    ``domain`` names the structural/chemical regime (DESIGN §4.8) and is the
    other half of the CLASSICAL registry key. It is consulted only when
    ``use_classical=True``; a universal model has no species/domain key.

    ``allow_unvalidated`` is the deliberate escape hatch for EXPLORATORY
    work — the first run of a new material (or, for the universal model, its
    first activation), whose whole purpose is to produce the evidence the
    §3.5 gate would judge. It is a caller-side decision, never a default. The
    universal model has RUN but not yet cleared that gate, so a DEFAULT
    cascade refuses unless this is set — the same on-the-record opt-in the
    classical registry uses. Anything returned under it is PROVISIONAL.

    On success it returns a :class:`~sabsim.driver.commands.ForceModel` the
    driver emits through ``force_model_commands`` unchanged — the base form
    (universal MLIP or classical) provides the bonding, ZBL core #1 (longer
    range) the projectile-substrate collisions, and ZBL core #2 (short) a
    hard wall on every substrate-substrate pair (DESIGN §3.3).
    """
    projectile = frozenset(projectile_species)

    if not use_classical:
        # The DESIGN default: the universal foundation MLIP + ZBL, for every
        # material. It follows the same gate-not-warn refusal as the classical
        # registry — unvalidated until it clears the §3.5 gate on a real run.
        model = UNIVERSAL_CASCADE_MODEL
        if not model.validated and not allow_unvalidated:
            raise NotImplementedError(
                f"the universal cascade model '{model.name}' is the default "
                f"(DESIGN §4.7) but has NOT yet cleared the §3.5 activation "
                f"gate: {model.caveat} To run it as EXPLORATORY bring-up — "
                f"whose results are provisional and must be reported as such "
                f"— set SABSIM_ALLOW_UNVALIDATED_POTENTIAL. Or request a "
                f"validated classical form explicitly (use_classical=True).")
        return _assemble_universal_overlay(
            model, type_map, projectile, long_core, short_core)

    # Explicit classical request (DESIGN §4.7, "classical by choice"): the
    # per-material registry, keyed by (substrate species, domain).
    substrate = frozenset(type_map) - projectile
    entry = _resolve_registry_entry(
        substrate, domain, allow_unvalidated, "cascade generator")
    return _assemble_classical_overlay(
        entry, type_map, projectile, long_core, short_core)


def universal_force_model(
        type_map: dict,
        allow_unvalidated: bool = False,
        model: UniversalCascadeModel = UNIVERSAL_CASCADE_MODEL) -> ForceModel:
    """The universal MLIP ALONE — no ZBL — for the QUIET stages (§4.7).

    The universal counterpart of :func:`classical_force_model`: the same
    no-ZBL form the gentle stages want, but built on the chemistry-agnostic
    foundation model instead of a per-material classical potential. ZBL is
    a keV close-approach hard core; the §2.2 bulk relax equilibrates a
    crystal at ordinary bond lengths where ZBL contributes nothing, so the
    working lattice is the pure MLIP equilibrium. Deriving that lattice
    under the SAME model the cascade then bombards under is the point (DESIGN
    §2.2, §4.7): a cell equilibrated under one description and bombarded
    under another starts stressed — exactly the offset that detonated the
    oxide bring-up. For silicon the classical and MLIP lattices nearly
    coincide, so this only matters at the margins, but the discipline is
    uniform: match first, tile second, under one potential.

    Every LAMMPS type maps to its REAL element — the universal model covers
    the whole periodic table and deepmd's element map has no ``NULL`` slot —
    and ``needs_atom_map`` is set because the graph network gathers features
    across the neighbor graph. It carries no ``preload``: the deepmd bundle
    ships the ``deepmd`` pair style built in (no runtime ``plugin load``),
    matching :func:`_assemble_universal_overlay`. Like the default cascade
    it follows the gate-not-warn discipline — the universal model is
    unvalidated until it clears the §3.5 gate, so a bulk derivation refuses
    unless ``allow_unvalidated`` opts into the same on-the-record bring-up.
    """
    if not model.validated and not allow_unvalidated:
        raise NotImplementedError(
            f"the universal model '{model.name}' is the §2.2 lattice-"
            f"derivation default (DESIGN §4.7) but has NOT yet cleared the "
            f"§3.5 activation gate: {model.caveat} To derive under it as "
            f"EXPLORATORY bring-up — provisional, reported as such — set "
            f"SABSIM_ALLOW_UNVALIDATED_POTENTIAL, or request a validated "
            f"classical form explicitly (SABSIM_CASCADE_CLASSICAL).")
    # Element labels in LAMMPS type-id order; deepmd needs no NULL slot.
    symbols_in_order = sorted(type_map, key=lambda symbol: type_map[symbol])
    element_labels = " ".join(symbols_in_order)
    model_path = resolve_universal_model_path(model)
    return ForceModel(
        pair_style=f"deepmd {model_path}",
        pair_coeff=(f"* * {element_labels}",),
        needs_atom_map=True)


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


def _zbl_overlay(
        type_map: dict,
        projectile: frozenset,
        long_core: tuple,
        short_core: tuple) -> tuple[str, list]:
    """The ZBL half of the ``hybrid/overlay``, derived from the species set.

    Returns the ZBL ``pair_style`` FRAGMENT (the two ``zbl`` sub-styles, long
    core first) and one ``pair_coeff`` line per element pair. Every pair gets
    exactly one core: the long one (#1) if it involves the projectile, the
    short one (#2) if it is substrate-substrate (DESIGN §3.3). The two atomic
    numbers are looked up from the element symbols, so ANY element works
    without a hand-maintained table — the same derivation whether the base
    sub-style underneath is a classical form or the universal MLIP, which is
    why it lives here shared by both assemblers.
    """
    long_inner, long_outer = long_core
    short_inner, short_outer = short_core

    style_fragment = (
        f"zbl {_lammps_number(long_inner)} {_lammps_number(long_outer)} "
        f"zbl {_lammps_number(short_inner)} {_lammps_number(short_outer)}")

    # Element symbols in LAMMPS type-id order (1, 2, ...).
    symbols_in_order = sorted(type_map, key=lambda symbol: type_map[symbol])

    coeffs = []
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
            coeffs.append(
                f"{first_id} {second_id} zbl {core_index} "
                f"{_lammps_number(float(first_z))} "
                f"{_lammps_number(float(second_z))}")

    return style_fragment, coeffs


def _assemble_classical_overlay(
        entry: CascadeGeneratorEntry,
        type_map: dict,
        projectile: frozenset,
        long_core: tuple,
        short_core: tuple) -> ForceModel:
    """Build the classical-form ``hybrid/overlay`` ForceModel (§4.7 option).

    The classical sub-style bonds only the substrate atoms — each projectile
    type is passed to it as ``NULL`` so the classical form ignores the
    projectile (which interacts purely through ZBL, the neutral-projectile
    choice of DESIGN §3.2). The two ZBL cores (:func:`_zbl_overlay`) are then
    overlaid on top. A classical form is built into LAMMPS, so the ForceModel
    needs no ``preload`` and no atom map.
    """
    # Element symbols in LAMMPS type-id order; NULL for a projectile type the
    # classical form must not see.
    symbols_in_order = sorted(type_map, key=lambda symbol: type_map[symbol])
    classical_labels = " ".join(
        "NULL" if symbol in projectile else symbol
        for symbol in symbols_in_order)
    classical_coeff = (
        f"* * {entry.classical_style} "
        f"{resolve_parameter_file(entry.classical_param_file)} "
        f"{classical_labels}")

    zbl_style, zbl_coeffs = _zbl_overlay(
        type_map, projectile, long_core, short_core)

    return ForceModel(
        pair_style=f"hybrid/overlay {entry.classical_style} {zbl_style}",
        pair_coeff=(classical_coeff, *zbl_coeffs))


def _assemble_universal_overlay(
        model: UniversalCascadeModel,
        type_map: dict,
        projectile: frozenset,
        long_core: tuple,
        short_core: tuple) -> ForceModel:
    """Build the universal-MLIP ``hybrid/overlay`` ForceModel (§4.7 default).

    The base sub-style is ``deepmd <model>``, and EVERY LAMMPS type is
    mapped to its real element — the universal model covers the whole
    periodic table, projectile included, and deepmd's element map has no
    ``NULL`` slot the way a classical form does. The near-equilibrium MLIP is
    still wrong deep in the collision, but the LONG ZBL core (#1) overlaid on
    every projectile pair dominates there, so the projectile is handled by
    ZBL exactly as in the classical path — the model merely also sees it at
    long range, which is scaffold-grade acceptable (DESIGN §4.7).

    Two things distinguish this ForceModel from the classical one. It needs
    the global atom map (``needs_atom_map``) because the graph network
    gathers per-atom features across the neighbor graph; and it carries no
    ``preload``, because the deepmd LAMMPS engine used for the cascade ships
    the ``deepmd`` pair style built in (no runtime ``plugin load``).
    """
    # Every type mapped to its REAL element (no NULL): the universal model
    # covers the projectile too, and the long ZBL core dominates the collision.
    symbols_in_order = sorted(type_map, key=lambda symbol: type_map[symbol])
    element_labels = " ".join(symbols_in_order)
    model_path = resolve_universal_model_path(model)
    deepmd_coeff = f"* * deepmd {element_labels}"

    zbl_style, zbl_coeffs = _zbl_overlay(
        type_map, projectile, long_core, short_core)

    return ForceModel(
        pair_style=f"hybrid/overlay deepmd {model_path} {zbl_style}",
        pair_coeff=(deepmd_coeff, *zbl_coeffs),
        needs_atom_map=True)
