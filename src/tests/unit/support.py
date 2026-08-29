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
    """A tiny environment library with a known scatter, for gate tests.

    Each species catalogues the cold vector and twenty warm copies
    jittered by up to ``THERMAL_SCATTER`` along the second axis; the
    thermal scatter is exactly ``THERMAL_SCATTER`` and the recorded
    warm-run distances are those jitters, so the false-alarm rate at a
    multiple of one is a known small number and zero at three.
    """
    generator = np.random.default_rng(7)
    jitters = generator.uniform(0.0, THERMAL_SCATTER, size=20)
    environments, scatter, warm = {}, {}, {}
    for symbol in species:
        rows = [COLD_VECTOR] + [
            COLD_VECTOR + np.array([0.0, jitter, 0.0, 0.0])
            for jitter in jitters]
        environments[symbol] = np.array(rows)
        scatter[symbol] = THERMAL_SCATTER
        warm[symbol] = np.array(jitters)
    if surfaces is None:
        surfaces = [{"phase": "silicon-diamond", "face": "100",
                     "termination": 0, "species": sorted(species)}]
    return EnvironmentLibrary(
        model_name=model_name, engine=engine,
        settings=DescriptorSettings(
            descriptor_cutoff=2.6, expansion_order=6,
            species_weights={symbol: 1.0 for symbol in species}),
        environments=environments, thermal_scatter=scatter,
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
