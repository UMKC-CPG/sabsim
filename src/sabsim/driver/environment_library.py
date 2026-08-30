"""The environment library — what the undamaged material looks like.

The §3.5 activation gate calls an atom CRYSTALLINE if its first-shell
bispectrum (:mod:`sabsim.driver.descriptors`) lies within the material's
own thermal scatter of SOME environment of the undamaged material —
"does this neighbourhood exist anywhere in the undamaged crystal?" —
and DISORDERED otherwise (DESIGN §3.5, revised 2026-08-29). This module
holds the catalogue that question is asked of:

* :class:`EnvironmentLibrary` — the record: the descriptors of every
  atom of the cold bulk crystal (family 1), the warm bulk crystal
  (family 6) and the clean unbombarded surfaces (family 4) of the
  bootstrap's Collection 1, the measured thermal scatter that fixes the
  tolerance, and the provenance a reader needs to know exactly what
  "crystalline" was compared against.
* :func:`build_environment_library` — MANUFACTURES one from Collection 1
  (PSEUDOCODE §11.2), with the self-check that a sound tolerance must
  pass: nearly every warm-run atom crystalline, nearly every melt-quench
  atom disordered.
* :func:`write_environment_library` / :func:`read_environment_library`
  — the on-disk pair ``environment_library.npz`` (the arrays) and
  ``environment_library.toml`` (everything a person reads).
* :func:`disordered_atoms` and :func:`false_alarm_rate` — the two
  questions the gate asks of a library.
* :func:`load_environment_library` — the study's entry point, with the
  refusals and the temperature warn/refuse band of DESIGN §3.5.

The library is never written by hand: it is a product of ``sabsim
bootstrap generate`` under the same universal model the study runs,
copied under ``SABSIM_SHARE`` and named by the study file's
``[protocol.activation] environment_library`` (ARCHITECTURE §2.3).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from sabsim.driver.commands import to_metal
from sabsim.driver.descriptors import (
    DESCRIPTOR_ENGINE_NAME,
    DescriptorSettings,
    describe_atoms,
)
from sabsim.spec.loader import SpecificationError

# The on-disk pair (PSEUDOCODE §11.3).
LIBRARY_ARRAYS_FILE = "environment_library.npz"
LIBRARY_MANIFEST_FILE = "environment_library.toml"

# Which Collection-1 families are CATALOGUED as undamaged environments,
# which one is the disorder SELF-CHECK, and which are deliberately left
# out (DESIGN §4.8 part 2): the strain family is carried past bond
# failure and the rattled snapshots are static kicks, so neither is a
# neighbourhood the undamaged material actually has.
COLD_BULK_FAMILY = "bulk"
SURFACE_FAMILY = "surface"
WARM_FAMILIES = ("warm_nvt", "warm_npt")
MELT_QUENCH_FAMILY = "melt_quench"
CATALOGUED_FAMILIES = (COLD_BULK_FAMILY, SURFACE_FAMILY, *WARM_FAMILIES)

# The thermal scatter is the TYPICAL nearest-cold distance of a warm-run
# atom; the 90th percentile is "typical" here so that a handful of
# unusually displaced atoms in a warm run do not set the unit for all.
_SCATTER_PERCENTILE = 90.0

# The self-check's acceptance limits (DESIGN §3.5): a tolerance that
# calls more than this fraction of WARM crystal atoms disordered is too
# tight, and one that calls fewer than this fraction of MELT-QUENCH
# atoms disordered is too loose; either way the library cannot tell the
# two apart and `generate` refuses to write it.
SELF_CHECK_MAX_WARM_DISORDERED = 0.10
SELF_CHECK_MIN_MELT_DISORDERED = 0.50

# The temperature warn/refuse band (DESIGN §3.5, Paul 2026-08-29). The
# gate judges a slab at the heal's cool-to target, the press temperature.
# Above the library's warm-run temperature the tolerance was measured a
# little tight — WARN; more than this fraction above it, the thermal
# scatter grows roughly with the square root of temperature, so 20 %
# hotter is ~10 % more scatter, past what one scatter multiple absorbs —
# REFUSE. A validation criterion of the loader, like a gate threshold
# (DESIGN §7.5), not a study knob.
LIBRARY_TEMPERATURE_REFUSE_FRACTION = 0.20

# Query vectors are compared with the catalogue in chunks so the N x M
# distance matrix of a big slab against a big library never has to fit
# in memory all at once.
_QUERY_CHUNK = 2000


@dataclass(frozen=True)
class SelfCheck:
    """The library's own proof that its tolerance separates order from
    disorder (DESIGN §3.5), recorded at the recipe's scatter multiple."""

    scatter_multiple: float            # the multiple the check ran at
    warm_disordered: float             # fraction of warm-run atoms flagged
    melt_quench_disordered: float      # fraction of melt-quench atoms flagged


@dataclass(frozen=True)
class EnvironmentLibrary:
    """What the undamaged material looks like, atom by atom (§3.5).

    ``environments`` maps each species to an ``(M, K)`` array of every
    catalogued descriptor vector of that species; ``thermal_scatter`` is
    the unit the gate's tolerance is counted in; ``warm_distances`` keeps
    every warm-run atom's nearest-cold distance so the false-alarm rate
    — the depth profile's baseline — can be recomputed at whatever
    scatter multiple a study names. ``warm_run_temperature`` (kelvin, the
    LOWEST warm run catalogued) is what the loader's temperature band is
    judged against, and ``provenance`` records the families, frame
    counts and clean surfaces (as ``{"phase", "face", "termination",
    "species"}`` tables) the catalogue was built from.
    """

    model_name: str
    engine: str
    settings: DescriptorSettings
    environments: dict
    thermal_scatter: dict
    warm_distances: dict
    self_check: SelfCheck
    warm_run_temperature: float
    provenance: dict


# ---------------------------------------------------------------------
# The two questions the gate asks of a library.
# ---------------------------------------------------------------------

def _nearest_distances(
        queries: np.ndarray, catalogue: np.ndarray) -> np.ndarray:
    """Distance from each query vector to its nearest catalogue vector.

    Uses the expansion |q - c|^2 = |q|^2 + |c|^2 - 2 q.c so one matrix
    product per chunk does the work of a double loop; the tiny negative
    round-off that expansion can produce is clipped before the root.
    """
    queries = np.asarray(queries, dtype=float)
    catalogue = np.asarray(catalogue, dtype=float)
    if queries.shape[0] == 0:
        return np.zeros(0, dtype=float)
    if catalogue.shape[0] == 0:
        raise ValueError("the environment catalogue is empty")
    catalogue_norms = np.einsum("ij,ij->i", catalogue, catalogue)
    nearest = np.empty(queries.shape[0], dtype=float)
    for start in range(0, queries.shape[0], _QUERY_CHUNK):
        chunk = queries[start:start + _QUERY_CHUNK]
        chunk_norms = np.einsum("ij,ij->i", chunk, chunk)
        squared = (chunk_norms[:, None] + catalogue_norms[None, :]
                   - 2.0 * chunk @ catalogue.T)
        nearest[start:start + _QUERY_CHUNK] = np.sqrt(
            np.clip(squared.min(axis=1), 0.0, None))
    return nearest


def disordered_atoms(
        vectors: np.ndarray, symbols: list, library: EnvironmentLibrary,
        scatter_multiple: float) -> np.ndarray:
    """One verdict per atom: True = DISORDERED (PSEUDOCODE §10.6).

    An atom is crystalline if the library holds an environment of its
    species within ``scatter_multiple`` thermal scatters of its vector.
    Asked that way — not "is it what THIS atom used to have" — a
    displaced atom the heal re-settled onto a good site is crystalline,
    and both slab faces are in the catalogue through the surface family,
    so the frozen base needs no special case. A species the library has
    never seen cannot be judged, and says so.
    """
    vectors = np.asarray(vectors, dtype=float)
    symbols = list(symbols)
    flags = np.zeros(len(symbols), dtype=bool)
    for species in set(symbols):
        if species not in library.environments:
            raise SpecificationError(
                f"the environment library catalogues no '{species}' "
                f"environments (it has {sorted(library.environments)}); "
                f"the slab cannot be judged against it")
        rows = np.array([index for index, symbol in enumerate(symbols)
                         if symbol == species])
        nearest = _nearest_distances(
            vectors[rows], library.environments[species])
        tolerance = scatter_multiple * library.thermal_scatter[species]
        flags[rows] = nearest > tolerance
    return flags


def false_alarm_rate(
        library: EnvironmentLibrary, species: str,
        scatter_multiple: float) -> float:
    """The fraction of WARM-RUN atoms the tolerance calls disordered.

    What the tolerance would flag in a slab that was never bombarded:
    the depth profile's baseline (DESIGN §3.5), recomputed at the
    study's own multiple from the recorded warm-run distances.
    """
    distances = np.asarray(library.warm_distances[species], dtype=float)
    if distances.size == 0:
        return 0.0
    tolerance = scatter_multiple * library.thermal_scatter[species]
    return float(np.mean(distances > tolerance))


# ---------------------------------------------------------------------
# Manufacturing a library from Collection 1 (PSEUDOCODE §11.2).
# ---------------------------------------------------------------------

def _by_species(atoms, vectors: np.ndarray, into: dict) -> None:
    """Append one frame's vectors to ``into`` (species -> list of rows)."""
    for symbol, vector in zip(atoms.get_chemical_symbols(), vectors):
        into.setdefault(symbol, []).append(np.asarray(vector, float))


def _stack(rows_by_species: dict) -> dict:
    """Turn species -> list of rows into species -> (M, K) array."""
    return {species: np.array(rows, dtype=float)
            for species, rows in rows_by_species.items()}


def build_environment_library(
        structures: list, recipe, work_directory,
        describe=describe_atoms) -> EnvironmentLibrary:
    """Catalogue the undamaged environments of Collection 1 (§11.2).

    ``structures`` are the ``(family, source, Atoms)`` triples
    :func:`~sabsim.bootstrap.collection1.build_collection1` produced.
    Families 1, 4 and 6 are catalogued; the strain and rattle families
    are excluded; the melt-quench family is the SELF-CHECK. ``describe``
    is the descriptor engine (injectable so the assembly can be tested
    without LAMMPS); every frame is described under ``work_directory``.

    The tolerance is MEASURED, not guessed: the thermal scatter of a
    species is the typical distance of a warm-run atom from its nearest
    cold-bulk environment. The self-check then asks, at the recipe's
    scatter multiple, what fraction of warm atoms and of melt-quench
    atoms the tolerance flags; a library that cannot keep the first low
    and the second high is refused loudly rather than written.
    """
    settings = recipe.descriptor_settings
    work_directory = Path(work_directory)
    catalogued: dict = {}
    cold: dict = {}
    warm: dict = {}
    melt: dict = {}
    frame_counts: dict = {}
    for index, (family, _source, atoms) in enumerate(structures):
        if family not in CATALOGUED_FAMILIES and (
                family != MELT_QUENCH_FAMILY):
            continue
        vectors = describe(atoms, settings, str(work_directory),
                           f"{family}_{index}")
        frame_counts[family] = frame_counts.get(family, 0) + 1
        if family == MELT_QUENCH_FAMILY:
            _by_species(atoms, vectors, melt)
            continue
        _by_species(atoms, vectors, catalogued)
        if family == COLD_BULK_FAMILY:
            _by_species(atoms, vectors, cold)
        elif family in WARM_FAMILIES:
            _by_species(atoms, vectors, warm)
    for family in (COLD_BULK_FAMILY, *WARM_FAMILIES):
        if not any(frame_counts.get(f, 0) for f in (
                (family,) if family == COLD_BULK_FAMILY else WARM_FAMILIES)):
            raise RuntimeError(
                f"Collection 1 holds no '{family}' frames; the library "
                f"needs the cold bulk AND the warm runs (DESIGN §4.8)")

    environments = _stack(catalogued)
    cold_arrays = _stack(cold)
    thermal_scatter: dict = {}
    warm_distances: dict = {}
    for species, rows in _stack(warm).items():
        if species not in cold_arrays:
            raise RuntimeError(
                f"warm runs contain '{species}' but the cold bulk does "
                f"not; every species needs a cold reference")
        distances = _nearest_distances(rows, cold_arrays[species])
        warm_distances[species] = distances
        thermal_scatter[species] = float(
            np.percentile(distances, _SCATTER_PERCENTILE))
    for species in environments:
        if species not in thermal_scatter:
            raise RuntimeError(
                f"no warm-run atoms of '{species}': its thermal scatter "
                f"cannot be measured, so its tolerance is undefined")

    multiple = float(recipe.gate_scatter_multiple)
    warm_flags = [
        distances > multiple * thermal_scatter[species]
        for species, distances in warm_distances.items()]
    warm_disordered = float(np.mean(np.concatenate(warm_flags)))
    melt_flags = []
    for species, rows in _stack(melt).items():
        if species not in environments:
            continue
        nearest = _nearest_distances(rows, environments[species])
        melt_flags.append(nearest > multiple * thermal_scatter[species])
    melt_disordered = (float(np.mean(np.concatenate(melt_flags)))
                       if melt_flags else float("nan"))
    if warm_disordered > SELF_CHECK_MAX_WARM_DISORDERED or not (
            melt_disordered >= SELF_CHECK_MIN_MELT_DISORDERED):
        raise RuntimeError(
            f"the environment library cannot separate warm crystal from "
            f"melt-quench glass at scatter multiple {multiple:g}: "
            f"{warm_disordered:.3f} of warm-run atoms and "
            f"{melt_disordered:.3f} of melt-quench atoms read as "
            f"disordered (limits {SELF_CHECK_MAX_WARM_DISORDERED:g} and "
            f"{SELF_CHECK_MIN_MELT_DISORDERED:g}; DESIGN §3.5)")

    warm_temperatures = [
        to_metal(spec.temperature, "temperature")
        for spec in recipe.starting_collection.warm_runs]
    surfaces = []
    for surface in recipe.starting_collection.surfaces:
        phase = next(p for p in recipe.phases if p.name == surface.phase)
        surfaces.append({
            "phase": surface.phase,
            "face": "".join(str(component) for component in surface.face),
            "termination": int(surface.termination_index),
            "species": sorted(_phase_species(phase))})
    return EnvironmentLibrary(
        model_name=recipe.generator.model,
        engine=DESCRIPTOR_ENGINE_NAME,
        settings=settings,
        environments=environments,
        thermal_scatter=thermal_scatter,
        warm_distances=warm_distances,
        self_check=SelfCheck(
            scatter_multiple=multiple, warm_disordered=warm_disordered,
            melt_quench_disordered=melt_disordered),
        warm_run_temperature=float(min(warm_temperatures)),
        provenance={
            "families": sorted(frame_counts),
            "frame_counts": dict(frame_counts),
            "surfaces": surfaces})


def _phase_species(phase) -> set:
    """The element symbols a recipe phase's crystal contains."""
    from sabsim.spec.references import resolve_crystal_file
    from sabsim.structure.slab_builder import load_crystal
    crystal = load_crystal(resolve_crystal_file(phase.cif))
    return {element.symbol for element in crystal.composition.elements}


# ---------------------------------------------------------------------
# The on-disk pair.
# ---------------------------------------------------------------------

def write_environment_library(
        library: EnvironmentLibrary, directory) -> Path:
    """Write the ``.npz`` + ``.toml`` pair; return the manifest path.

    The arrays — per-species environment vectors and warm-run distances
    — go to the ``.npz``; everything a person reads (model, engine,
    settings, thermal scatter, self-check, warm-run temperature,
    provenance) goes to the TOML sidecar, written with the same
    hand-rolled emitter the run manifests use.
    """
    from sabsim.pipeline.handoff import _dump_toml
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    arrays = {}
    for species, vectors in library.environments.items():
        arrays[f"env_{species}"] = np.asarray(vectors, dtype=float)
    for species, distances in library.warm_distances.items():
        arrays[f"warm_{species}"] = np.asarray(distances, dtype=float)
    np.savez(directory / LIBRARY_ARRAYS_FILE, **arrays)
    manifest = {
        "model_name": library.model_name,
        "engine": library.engine,
        "arrays_file": LIBRARY_ARRAYS_FILE,
        "warm_run_temperature": float(library.warm_run_temperature),
        "settings": {
            "descriptor_cutoff": float(library.settings.descriptor_cutoff),
            "expansion_order": int(library.settings.expansion_order),
            "species_weights": {
                symbol: float(weight) for symbol, weight in
                library.settings.species_weights.items()}},
        "thermal_scatter": {
            species: float(value)
            for species, value in library.thermal_scatter.items()},
        "self_check": {
            "scatter_multiple": float(library.self_check.scatter_multiple),
            "warm_disordered": float(library.self_check.warm_disordered),
            "melt_quench_disordered": float(
                library.self_check.melt_quench_disordered)},
        "provenance": {
            "families": list(library.provenance.get("families", [])),
            "frame_counts": {
                str(k): int(v) for k, v in
                library.provenance.get("frame_counts", {}).items()},
            "surfaces": [dict(entry) for entry in
                         library.provenance.get("surfaces", [])]},
    }
    manifest_path = directory / LIBRARY_MANIFEST_FILE
    manifest_path.write_text(_dump_toml(manifest), encoding="utf-8")
    return manifest_path


def read_environment_library(path) -> EnvironmentLibrary:
    """Read a library from its manifest path (or the directory holding it)."""
    path = Path(path)
    manifest_path = path / LIBRARY_MANIFEST_FILE if path.is_dir() else path
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"no environment library manifest at {manifest_path}")
    with manifest_path.open("rb") as handle:
        manifest = tomllib.load(handle)
    arrays_path = manifest_path.parent / manifest["arrays_file"]
    with np.load(arrays_path) as arrays:
        environments = {
            name[len("env_"):]: np.array(arrays[name], dtype=float)
            for name in arrays.files if name.startswith("env_")}
        warm_distances = {
            name[len("warm_"):]: np.array(arrays[name], dtype=float)
            for name in arrays.files if name.startswith("warm_")}
    settings_table = manifest["settings"]
    check = manifest["self_check"]
    return EnvironmentLibrary(
        model_name=str(manifest["model_name"]),
        engine=str(manifest["engine"]),
        settings=DescriptorSettings(
            descriptor_cutoff=float(settings_table["descriptor_cutoff"]),
            expansion_order=int(settings_table["expansion_order"]),
            species_weights={
                str(k): float(v) for k, v in
                settings_table["species_weights"].items()}),
        environments=environments,
        thermal_scatter={
            str(k): float(v) for k, v in
            manifest["thermal_scatter"].items()},
        warm_distances=warm_distances,
        self_check=SelfCheck(
            scatter_multiple=float(check["scatter_multiple"]),
            warm_disordered=float(check["warm_disordered"]),
            melt_quench_disordered=float(check["melt_quench_disordered"])),
        warm_run_temperature=float(manifest["warm_run_temperature"]),
        provenance=dict(manifest.get("provenance", {})))


# ---------------------------------------------------------------------
# The study's entry point: refusals and the temperature band (§10.6).
# ---------------------------------------------------------------------

def _wafer_species(wafer) -> frozenset | None:
    """The elements a wafer's crystal contains, or None if unreadable.

    A missing crystal file is reported by phase-three validation on its
    own; here it only means the face check falls back to the face alone.
    """
    from sabsim.spec.references import resolve_crystal_file
    from sabsim.structure.slab_builder import load_crystal
    try:
        crystal = load_crystal(resolve_crystal_file(wafer.cif_source))
    except Exception:
        return None
    return frozenset(element.symbol
                     for element in crystal.composition.elements)


def _surface_catalogued(library: EnvironmentLibrary, wafer) -> bool:
    """Does the library catalogue a clean surface of this wafer's face?

    A study wafer names its face but no termination and no recipe phase
    (:class:`~sabsim.spec.records.MaterialKnobs`), so the match is on
    the face AND, where the wafer's crystal can be read, the species set
    of the catalogued phase — enough to tell a silicon (100) face from a
    silica one. Any termination of that face counts.
    """
    face = "".join(str(component) for component in wafer.surface_face)
    species = _wafer_species(wafer)
    for entry in library.provenance.get("surfaces", []):
        if str(entry.get("face")) != face:
            continue
        catalogued = entry.get("species")
        if species is None or catalogued is None:
            return True
        if frozenset(catalogued) == species:
            return True
    return False


def library_manifest_path(wafer) -> str:
    """Where one wafer's library lives: its preparation subfolder.

    ``<study>/<material label>/environment_library.toml`` (ARCHITECTURE
    §1, DESIGN §1.2; Paul, 2026-08-29 after LEDGER T-39): each wafer
    has a library of its own, found by its ``material`` label, and the
    study file names no path.
    """
    return os.path.join(wafer.preparation_directory, LIBRARY_MANIFEST_FILE)


def check_library_against_study(
        library: EnvironmentLibrary, member, wafer,
        bound_engine_name: str = DESCRIPTOR_ENGINE_NAME) -> list:
    """The three refusals and the temperature band (PSEUDOCODE §10.6).

    Checks ONE wafer's library (the other wafer has its own). Refuses
    (:class:`SpecificationError`) a library built under a model other
    than the study's, computed by an engine other than the bound one,
    or cataloguing no clean surface of THIS wafer's face — the slab's
    own faces would then read as damage. Then the warn/refuse band: the
    gate judges at the press temperature; above the library's warm-run
    temperature it WARNS, more than 20 % above it REFUSES (DESIGN §3.5).
    Returns the list of warning strings for the caller to print.
    """
    context = (f"member '{member.name}' wafer '{wafer.identity}' "
               f"environment library")
    if library.model_name != member.potential.universal_model:
        raise SpecificationError(
            f"{context} was built under '{library.model_name}', the "
            f"study runs '{member.potential.universal_model}' — rebuild "
            f"the library under the study's model (DESIGN §3.5)")
    if library.engine != bound_engine_name:
        raise SpecificationError(
            f"{context} was computed with '{library.engine}', this "
            f"deployment binds '{bound_engine_name}' — both sides of the "
            f"comparison must use one engine (ARCHITECTURE §2.3)")
    if not _surface_catalogued(library, wafer):
        face = "".join(str(c) for c in wafer.surface_face)
        raise SpecificationError(
            f"{context} catalogues no clean ({face}) surface of the "
            f"wafer; the slab's own faces would read as damage — add "
            f"the face to the recipe's surfaces and rebuild (DESIGN §4.8)")

    warnings = []
    judged_at = to_metal(member.protocol.press_temperature, "temperature")
    warm_at = float(library.warm_run_temperature)
    if judged_at > warm_at:
        if judged_at > (1.0 + LIBRARY_TEMPERATURE_REFUSE_FRACTION) * warm_at:
            raise SpecificationError(
                f"{context}: the study judges the gate at {judged_at:g} K, "
                f"more than {100 * LIBRARY_TEMPERATURE_REFUSE_FRACTION:.0f} % "
                f"above the library's warm runs at {warm_at:g} K; the "
                f"tolerance no longer describes the slab — rebuild the "
                f"library with a warm run at the study's temperature")
        warnings.append(
            f"{context}: the study judges the gate at {judged_at:g} K, "
            f"above the library's warm runs at {warm_at:g} K — the "
            f"tolerance was measured a little tight, so some crystalline "
            f"atoms may read as disordered")
    return warnings


def load_environment_library(
        member, wafer,
        bound_engine_name: str = DESCRIPTOR_ENGINE_NAME) -> tuple:
    """Read ONE wafer's library and check it; ``(library, warnings)``.

    The library is found in the wafer's preparation subfolder of the
    study (:func:`library_manifest_path`); a wafer whose folder holds
    none has not been prepared, and the message says how to prepare it.
    """
    path = library_manifest_path(wafer)
    if not os.path.isfile(path):
        raise SpecificationError(
            f"member '{member.name}': wafer '{wafer.identity}' has no "
            f"environment library at {path} — run `sabsim bootstrap "
            f"generate` in that folder, or copy a prepared "
            f"'{wafer.identity}/' folder there (ARCHITECTURE §1, DESIGN "
            f"§4.8)")
    library = read_environment_library(path)
    return library, check_library_against_study(
        library, member, wafer, bound_engine_name)
