"""T-37: how well does a first-shell bispectrum library separate a warm
silicon crystal from melt-quench glass, as a function of the descriptor
cutoff and of the warm-run temperature?

T-36 (job 16858023) built the library at a 2.6 A cutoff with 600 K warm
runs and the self-check refused it: no glass atom lay outside three
thermal scatters of the catalogue. This script reuses T-36's frames
(bulk, warm NVT/NPT at 600 K, melt-quench glass), adds a short 300 K
warm run, describes every frame at several cutoffs, and prints the
fraction of warm atoms and of glass atoms flagged as disordered at a
range of scatter multiples. Runs on a compute node (bundle lmp).
"""
import dataclasses
import glob
import sys
from pathlib import Path

import numpy as np
from ase.io import read as ase_read

from sabsim.bootstrap.collection1 import (
    _read_dump_frames, _run_dynamic, derive_phase_lattices,
    warm_run_script)
from sabsim.bootstrap.recipe import load_recipe
from sabsim.driver.descriptors import DescriptorSettings, describe_atoms
from sabsim.spec.records import Quantity

recipe_path, t36_collection, work = sys.argv[1], Path(sys.argv[2]), \
    Path(sys.argv[3])
work.mkdir(parents=True, exist_ok=True)
recipe = load_recipe(recipe_path)
type_map = {1: "Si"}
FRAMES_PER_FAMILY = 6


def frames_of(family_dir: str) -> list:
    frames = []
    for dump in sorted(glob.glob(f"{t36_collection}/{family_dir}/*/frames.dump")):
        frames += _read_dump_frames(dump, type_map)
    stride = max(1, len(frames) // FRAMES_PER_FAMILY)
    return frames[::stride][:FRAMES_PER_FAMILY]


bulk = ase_read(f"{t36_collection}/lattice/silicon-diamond/relaxed_bulk.data",
                format="lammps-data", style="atomic")
bulk.set_chemical_symbols(["Si"] * len(bulk))
bulk.set_pbc(True)
families = {"bulk": [bulk],
            "warm600": frames_of("warm_nvt") + frames_of("warm_npt"),
            "glass": frames_of("melt_quench")}

# A 300 K warm run — the temperature the gate actually judges at.
lattices = derive_phase_lattices(recipe, work)
spec600 = recipe.starting_collection.warm_runs[0]
spec300 = dataclasses.replace(
    spec600, temperature=Quantity(300.0, "K"))
warm300 = _run_dynamic(
    recipe, lattices, spec300.phase,
    recipe.starting_collection.bulk.cells_per_axis, warm_run_script,
    spec300, "warm300", 0, work)
families["warm300"] = [atoms for _, _, atoms in warm300][-FRAMES_PER_FAMILY:]
for name, frames in families.items():
    print(f"family {name}: {len(frames)} frames x {len(frames[0])} atoms")


def nearest(vectors, reference):
    return np.sqrt(((vectors[:, None, :] - reference[None, :, :]) ** 2)
                   .sum(-1)).min(1)


for cutoff in (2.6, 3.4, 4.2, 5.0):
    settings = DescriptorSettings(
        first_shell_cutoff=cutoff, expansion_order=6,
        species_weights={"Si": 1.0})
    described = {}
    for name, frames in families.items():
        described[name] = np.vstack([
            describe_atoms(atoms, settings, str(work),
                           f"c{cutoff:g}_{name}_{index}")
            for index, atoms in enumerate(frames)])
    cold = described["bulk"]
    glass_to_cold = nearest(described["glass"], cold)
    for warm_name in ("warm600", "warm300"):
        warm = described[warm_name]
        warm_to_cold = nearest(warm, cold)
        scatter = np.percentile(warm_to_cold, 90)
        catalogue = np.vstack([cold, warm])
        glass_to_catalogue = nearest(described["glass"], catalogue)
        print(f"\nT37 cutoff {cutoff:.1f} A, {warm_name}: scatter(p90) "
              f"{scatter:.3f}; glass->cold median {np.median(glass_to_cold):.3f}"
              f"  (warm->cold median {np.median(warm_to_cold):.3f})")
        print("  multiple  warm flagged  glass flagged vs cold  vs catalogue")
        for multiple in (1.0, 1.5, 2.0, 3.0):
            tolerance = multiple * scatter
            print(f"    {multiple:3.1f}      {np.mean(warm_to_cold > tolerance):5.3f}"
                  f"          {np.mean(glass_to_cold > tolerance):5.3f}"
                  f"              {np.mean(glass_to_catalogue > tolerance):5.3f}")
print("T37 DONE")
