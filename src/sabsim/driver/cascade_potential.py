"""The cascade potential: the universal foundation MLIP spliced with ZBL.

The ion-beam cascade (DESIGN.md §3.3) drives atoms together at energies
far outside anything a near-equilibrium potential was fitted to, so the
bonding model is composed with two ZBL screened-Coulomb hard cores
through ``pair_style hybrid/overlay``: a longer-range core on every
projectile-substrate pair (the collision itself) and a short core on
every substrate-substrate pair (a wall against fusion). The bonding model
underneath is the chemistry-agnostic universal foundation MLIP pinned in
:data:`UNIVERSAL_CASCADE_MODEL` (DESIGN.md §4.7), which needs no
per-material work; its weights path comes from the study file's
``[potential]`` block.

This module is a pure assembler: it returns a
:class:`~sabsim.driver.commands.ForceModel` and never talks to LAMMPS,
so it is unit-tested by asserting the emitted strings.

There is exactly ONE kind of cascade potential — a universal foundation
MLIP from the supported-models table below, spliced with ZBL cores — and
no fall-back of any kind (DESIGN §4.7, revised 2026-08-28).
"""

from __future__ import annotations

import os
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


# WHERE the universal model's weights live is a study-file decision, not
# an environment one: the study's ``[potential]`` block names the weights
# path (``universal_weights``) beside the pinned model identity, so the
# provenance record says which file ran (DESIGN §1.6). The registry entry
# below pins the IDENTITY (name, branch, version); the loader hands the
# path in. The artifact is a PyTorch ``.pth``, which LAMMPS loads directly
# through ``pair_style deepmd`` and which is NOT tied to a GPU
# architecture; an AOT-compiled ``.pt2`` is ~2.5x faster but is
# architecture-locked, so it is an optional optimisation, not the
# contract (DESIGN §4.7).


@dataclass(frozen=True)
class UniversalCascadeModel:
    """The universal foundation MLIP used as the DEFAULT cascade potential.

    A universal model is chemistry-agnostic — one already-trained
    foundation network covers
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
    universal analogue of a frozen parameter-file citation (DESIGN §4.7,
    "a universal entry pins the model version").

    ``validated`` follows the gate-not-warn discipline: it stays ``False``
    until a full activation under this model has
    cleared the §3.5 gate on a real material, and until then the resolver
    refuses unless the study's ``[potential] allow_unvalidated`` opts in —
    the on-the-record path §4.7 defines for bringing up any new material.
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
           "study opts in with [potential] allow_unvalidated, and results "
           "obtained that way are EXPLORATORY. The weights are a portable "
           "PyTorch .pth named by the study's [potential] universal_weights.",
    validated=False)


# The TABLE of universal models SABSIM knows how to run (DESIGN §4.7,
# revised 2026-08-28). The user names one of these in the study file's
# ``[potential] universal_model`` (and the bootstrap recipe's
# ``[generator] model``); nothing in the code assumes a particular row.
# Bringing up a newer foundation model (a DPA-4, or another family that
# LAMMPS can load through ``pair_style deepmd``) means adding a row here —
# its identity, provenance, caveat and validation status — never editing
# a resolver. One row today, because one model has been screened.
SUPPORTED_UNIVERSAL_MODELS: tuple = (UNIVERSAL_CASCADE_MODEL,)


def supported_universal_model(name: str) -> UniversalCascadeModel:
    """Look a universal model up by the name the study file gives.

    The lookup is the ONLY place a model name is turned into a model
    record, so the study file (not the code) decides which foundation
    model a run uses, while an unknown name is a loud stop on the login
    node that lists what IS supported — never a silent fall-through to a
    default (DESIGN §4.7: no fall-backs).
    """
    for model in SUPPORTED_UNIVERSAL_MODELS:
        if model.name == name:
            return model
    known = ", ".join(model.name for model in SUPPORTED_UNIVERSAL_MODELS)
    raise ValueError(
        f"universal model '{name}' is not in SABSIM's table of supported "
        f"universal models ({known}); add a row to "
        f"SUPPORTED_UNIVERSAL_MODELS (DESIGN §4.7) to bring it up")


def resolve_universal_model_path(
        weights_path: str,
        model: UniversalCascadeModel = UNIVERSAL_CASCADE_MODEL) -> str:
    """Check the weights path the study file gave for the universal model.

    The registry pins the model IDENTITY (name/branch/version); the study
    file's ``[potential] universal_weights`` says where its file is on this
    machine. An empty path is a LOUD failure naming the model — the same
    no-hidden-defaults discipline as the rest of the pipeline, so a cascade
    never silently runs under the wrong (or no) model. Existence of the
    file is checked at load time by the phase-three reference check.
    """
    if not weights_path:
        raise RuntimeError(
            f"the universal cascade model '{model.name}' needs its "
            f"weights, but the study's [potential] universal_weights is "
            f"empty (DESIGN §4.7).")
    return weights_path


def resolve_cascade_generator(
        type_map: dict,
        projectile_species,
        weights_path: str = "",
        long_core: tuple = (_LONG_CORE_INNER_STANDIN,
                            _LONG_CORE_OUTER_STANDIN),
        short_core: tuple = (_SHORT_CORE_INNER_STANDIN,
                            _SHORT_CORE_OUTER_STANDIN),
        allow_unvalidated: bool = False,
        model_name: str = UNIVERSAL_CASCADE_MODEL.name) -> ForceModel:
    """Assemble the cascade potential: the universal MLIP + ZBL (§4.7).

    ``type_map`` maps every element symbol present in the cascade cell —
    substrate AND projectile — to its LAMMPS type id (the projectile type
    must already be declared so the cascade can create those atoms). The
    substrate species are inferred as ``type_map`` minus
    ``projectile_species``.

    The cascade runs on a chemistry-agnostic universal foundation MLIP
    spliced with the two ZBL cores — it needs no per-material work and
    covers every species. WHICH universal model is the study file's
    choice: ``model_name`` is its ``[potential] universal_model``, looked
    up in :data:`SUPPORTED_UNIVERSAL_MODELS` (an unknown name stops
    loudly, DESIGN §4.7), and ``weights_path`` is its ``[potential]
    universal_weights`` (the study file is the provenance record, DESIGN
    §1.6). There is no other cascade potential and no fall-back.

    ``allow_unvalidated`` is the deliberate escape hatch for EXPLORATORY
    work — the first run of a new material (or, for the universal model, its
    first activation), whose whole purpose is to produce the evidence the
    §3.5 gate would judge. It comes from the study's ``[potential]
    allow_unvalidated``, never a default. The universal model has RUN but
    not yet cleared that gate, so a cascade refuses unless this is set.
    Anything returned under it is PROVISIONAL.

    On success it returns a :class:`~sabsim.driver.commands.ForceModel` the
    driver emits through ``force_model_commands`` unchanged — the universal
    MLIP provides the bonding, ZBL core #1 (longer range) the
    projectile-substrate collisions, and ZBL core #2 (short) a hard wall on
    every substrate-substrate pair (DESIGN §3.3).
    """
    projectile = frozenset(projectile_species)
    model = supported_universal_model(model_name)
    if not model.validated and not allow_unvalidated:
        raise NotImplementedError(
            f"the universal cascade model '{model.name}' is the cascade "
            f"potential (DESIGN §4.7) but has NOT yet cleared the §3.5 "
            f"activation gate: {model.caveat} To run it as EXPLORATORY "
            f"bring-up — whose results are provisional and must be reported "
            f"as such — set allow_unvalidated = true in the study's "
            f"[potential] block.")
    return _assemble_universal_overlay(
        model, weights_path, type_map, projectile, long_core, short_core)


def universal_force_model(
        type_map: dict,
        weights_path: str,
        allow_unvalidated: bool = False,
        model_name: str = UNIVERSAL_CASCADE_MODEL.name) -> ForceModel:
    """The universal MLIP ALONE — no ZBL — for the QUIET stages (§4.7).

    The same no-ZBL form the gentle stages want, built on the
    chemistry-agnostic foundation model. ZBL is
    a keV close-approach hard core; the §2.2 bulk relax equilibrates a
    crystal at ordinary bond lengths where ZBL contributes nothing, so the
    working lattice is the pure MLIP equilibrium. Deriving that lattice
    under the SAME model the cascade then bombards under is the point (DESIGN
    §2.2, §4.7): a cell equilibrated under one description and bombarded
    under another starts stressed — exactly the offset that detonated the
    oxide bring-up. For silicon the published and MLIP lattices nearly
    coincide, so this only matters at the margins, but the discipline is
    uniform: match first, tile second, under one potential. ``model_name``
    is the study file's ``[potential] universal_model`` (or the bootstrap
    recipe's ``[generator] model``), looked up in
    :data:`SUPPORTED_UNIVERSAL_MODELS`.

    Every LAMMPS type maps to its REAL element — the universal model covers
    the whole periodic table and deepmd's element map has no ``NULL`` slot —
    and ``needs_atom_map`` is set because the graph network gathers features
    across the neighbor graph. It carries no ``preload``: the deepmd bundle
    ships the ``deepmd`` pair style built in (no runtime ``plugin load``),
    matching :func:`_assemble_universal_overlay`. Like the default cascade
    it follows the gate-not-warn discipline — the universal model is
    unvalidated until it clears the §3.5 gate, so a bulk derivation refuses
    unless ``allow_unvalidated`` opts into the same on-the-record bring-up.
    ``weights_path`` is the study's ``[potential] universal_weights``.
    """
    model = supported_universal_model(model_name)
    if not model.validated and not allow_unvalidated:
        raise NotImplementedError(
            f"the universal model '{model.name}' is the §2.2 lattice-"
            f"derivation default (DESIGN §4.7) but has NOT yet cleared the "
            f"§3.5 activation gate: {model.caveat} To derive under it as "
            f"EXPLORATORY bring-up — provisional, reported as such — set "
            f"allow_unvalidated = true in the study's [potential] block.")
    # Element labels in LAMMPS type-id order; deepmd needs no NULL slot.
    symbols_in_order = sorted(type_map, key=lambda symbol: type_map[symbol])
    element_labels = " ".join(symbols_in_order)
    model_path = resolve_universal_model_path(weights_path, model)
    return ForceModel(
        pair_style=f"deepmd {model_path}",
        pair_coeff=(f"* * {element_labels}",),
        needs_atom_map=True)


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
    without a hand-maintained table.
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


def _assemble_universal_overlay(
        model: UniversalCascadeModel,
        weights_path: str,
        type_map: dict,
        projectile: frozenset,
        long_core: tuple,
        short_core: tuple) -> ForceModel:
    """Build the universal-MLIP ``hybrid/overlay`` ForceModel (§4.7 default).

    The base sub-style is ``deepmd <model>``, and EVERY LAMMPS type is
    mapped to its real element — the universal model covers the whole
    periodic table, projectile included, and deepmd's element map has no
    ``NULL`` slot to leave a species unmapped. The near-equilibrium MLIP is
    still wrong deep in the collision, but the LONG ZBL core (#1) overlaid
    on every projectile pair dominates there, so the projectile is handled
    by ZBL — the model merely also sees it at long range, which is
    scaffold-grade acceptable (DESIGN §4.7).

    Two things distinguish this ForceModel from a built-in one. It needs
    the global atom map (``needs_atom_map``) because the graph network
    gathers per-atom features across the neighbor graph; and it carries no
    ``preload``, because the deepmd LAMMPS engine used for the cascade ships
    the ``deepmd`` pair style built in (no runtime ``plugin load``).
    """
    # Every type mapped to its REAL element (no NULL): the universal model
    # covers the projectile too, and the long ZBL core dominates the collision.
    symbols_in_order = sorted(type_map, key=lambda symbol: type_map[symbol])
    element_labels = " ".join(symbols_in_order)
    model_path = resolve_universal_model_path(weights_path, model)
    deepmd_coeff = f"* * deepmd {element_labels}"

    zbl_style, zbl_coeffs = _zbl_overlay(
        type_map, projectile, long_core, short_core)

    return ForceModel(
        pair_style=f"hybrid/overlay deepmd {model_path} {zbl_style}",
        pair_coeff=(deepmd_coeff, *zbl_coeffs),
        needs_atom_map=True)
