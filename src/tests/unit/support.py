"""Small helpers shared by the driver unit tests.

The command generators are tested against ``MockEngine`` with no LAMMPS
present, so they only need SOME well-formed :class:`ForceModel` to emit.
The one here is LAMMPS's built-in ``zero`` pair style — a style that
computes no forces at all — used purely as a fixture: it is not a
potential SABSIM runs under (the pipeline uses the universal foundation
MLIP and the DeePMD production model, DESIGN.md §4.7), and it names no
interatomic model, so no test can mistake it for one.
"""

import numpy as np

from sabsim.driver.commands import ForceModel
from sabsim.driver.descriptors import (
    DESCRIPTOR_ENGINE_NAME,
    DescriptorSettings,
)
from sabsim.driver.environment_library import (
    EnvironmentLibrary,
    SelfCheck,
    warm_ruler,
)

# The one "cold" neighbourhood of the hand-built library below, and the
# size of its thermal jitter. Tests build descriptor vectors for a slab
# by hand: an undamaged atom gets COLD_VECTOR (plus a jitter smaller than
# the scatter), a damaged one gets a vector far from it.
COLD_VECTOR = np.array([1.0, 0.0, 0.0, 0.0])
THERMAL_SCATTER = 0.1


def hand_built_library(
        species=("Si",), warm_run_temperature: float = 600.0,
        model_name: str = "DPA-3.1-3M",
        engine: str = DESCRIPTOR_ENGINE_NAME,
        surfaces=None) -> EnvironmentLibrary:
    """A tiny environment library with a known ruler, for gate tests.

    Each species catalogues the cold vector and twenty warm copies
    jittered by up to ``THERMAL_SCATTER`` along the SECOND axis, so the
    second axis is the one direction thermal motion explores. The
    ruler (mean, whitening, scatter, warm distances) is built by the
    SAME functions the real builder uses (DESIGN §3.5, 2026-09-10), so
    a jitter along that axis smaller than the scatter reads as
    crystalline, and a displacement along any OTHER axis — a direction
    thermal motion never explores — reads as disordered however small;
    the false-alarm rate at a multiple of one is a known small number
    and zero at three.
    """
    generator = np.random.default_rng(7)
    jitters = generator.uniform(0.0, THERMAL_SCATTER, size=20)
    environments, scatter, warm, means, whitenings = {}, {}, {}, {}, {}
    for symbol in species:
        warm_rows = np.array([
            COLD_VECTOR + np.array([0.0, jitter, 0.0, 0.0])
            for jitter in jitters])
        environments[symbol] = np.vstack([[COLD_VECTOR], warm_rows])
        means[symbol], whitenings[symbol] = warm_ruler(warm_rows)
        whitened_warm = (warm_rows - means[symbol]) @ whitenings[symbol]
        whitened_cold = (COLD_VECTOR - means[symbol]) @ whitenings[symbol]
        distances = np.linalg.norm(whitened_warm - whitened_cold, axis=1)
        warm[symbol] = distances
        scatter[symbol] = float(np.percentile(distances, 90.0))
    if surfaces is None:
        surfaces = [{"phase": "silicon-diamond", "face": "100",
                     "termination": 0, "species": sorted(species)}]
    return EnvironmentLibrary(
        model_name=model_name, engine=engine,
        settings=DescriptorSettings(
            descriptor_cutoff=2.6, expansion_order=6,
            species_weights={symbol: 1.0 for symbol in species}),
        environments=environments, warm_mean=means,
        whitening=whitenings, thermal_scatter=scatter,
        warm_distances=warm,
        self_check=SelfCheck(scatter_multiple=3.0, warm_disordered=0.0,
                             melt_quench_disordered=1.0),
        warm_run_temperature=warm_run_temperature,
        provenance={"families": ["bulk", "surface", "warm_nvt"],
                    "frame_counts": {"bulk": 1, "surface": 1,
                                     "warm_nvt": 1},
                    "surfaces": surfaces})


def stand_in_force_model(type_map: dict) -> ForceModel:
    """A minimal, plugin-free, force-free ForceModel over ``type_map``.

    ``pair_style zero`` takes only a cutoff and one ``pair_coeff * *``
    line, whatever the species, so the fixture is the same shape for any
    type map — the command generators only need SOME well-formed model.
    """
    del type_map                     # any species set: zero has no coeffs
    return ForceModel(
        pair_style="zero 6.0",
        pair_coeff=("* *",))


# ---------------------------------------------------------------------
# Pair fixtures from the project-file template (revised 2026-08-30): a
# project holds ONE pair, so tests that need a real PairSpecification
# load the template's Si/SiO2 pair, or derive the same-material Si/Si
# pair from it — the reference pair a person would run as its own
# project (DESIGN.md §1.1).
# ---------------------------------------------------------------------

import os as _os
import shutil as _shutil
from dataclasses import replace as _replace

PROJECT_TEMPLATE = _os.path.abspath(_os.path.join(
    _os.path.dirname(__file__),
    "..", "..", "..", "share", "templates", "project_spec.toml"))


def template_pair():
    """The template's pair — Si(100) facing alpha-quartz SiO2(001).

    Loading (not the §1.5 reference check) is all this needs, so no
    prepared folders have to exist; the pair carries the protocol,
    numerical, ensemble and potential blocks the stages read.
    """
    from sabsim.spec.loader import load_and_validate_project
    return load_and_validate_project(PROJECT_TEMPLATE).pair


def si_si_pair():
    """The Si/Si same-material pair, derived from the template's pair.

    Both wafers silicon (the identity coincidence case), with the
    silicon-only material domain the silicon force-model registry
    covers. Wafer B keeps its own prep folder name (``prep_surf2_si``)
    so the two surfaces stay distinct, as a real Si/Si project's do.
    """
    from sabsim.spec.records import WaferPair
    pair = template_pair()
    wafer_a = pair.material.wafer_a
    project_directory = _os.path.dirname(wafer_a.preparation_directory)
    wafer_b = _replace(
        wafer_a,
        preparation_directory=_os.path.join(project_directory,
                                            "prep_surf2_si"))
    return _replace(
        pair, material=WaferPair(wafer_a=wafer_a, wafer_b=wafer_b),
        material_domain="diamond-cubic")


def project_in(directory) -> str:
    """Copy the template into ``directory`` as its ``sabsim.toml``.

    Returns the copied file's path. The template names its CIF files
    relative to the repository, so a project made from it elsewhere
    still LOADS (the loader reads text); only the phase-three reference
    check — which the walking skeleton never runs for the environment
    libraries — cares where the files are.
    """
    target = _os.path.join(str(directory), "sabsim.toml")
    _shutil.copy(PROJECT_TEMPLATE, target)
    return target
